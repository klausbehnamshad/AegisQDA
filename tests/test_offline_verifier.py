"""Offline verification stays read-only, source-free and fixture-bound."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

import pytest

import aegisqda.digqda_adapter as adapter
import aegisqda.offline_verifier as verifier
import aegisqda.output_review as output_review
from aegisqda.config import load_config
from aegisqda.detection import Finding
from aegisqda.errors import DownstreamBlocked
from aegisqda.manifests import canonical_bytes, seal, sha256_bytes, sha256_file
from aegisqda.review_signature import create_review_key
from aegisqda.safeio import atomic_json, load_json
from aegisqda.workbench import apply_code, declare_method, define_code, write_memo
from aegisqda.workflow import scan_source, transform_run, write_review

LABEL = "Synthetischer Kategorieterm"


@dataclass(frozen=True)
class SyntheticRun:
    run: Path
    key: Path

    @property
    def final(self) -> Path:
        return self.run / "digqda-run.json"

    @property
    def attempt(self) -> Path:
        return self.run / "digqda-attempts" / load_json(self.final)["attempt_id"]


def _reseal(path: Path, payload: dict[str, Any]) -> None:
    payload = deepcopy(payload)
    payload.pop("integrity_sha256", None)
    path.write_bytes(canonical_bytes(seal(payload)) + b"\n")


def _payloads(source: Path, case_id: str, model: str, digest: str) -> dict[str, dict[str, Any]]:
    source_sha = sha256_file(source)
    text = source.read_text().strip()
    unit = {"unit_id": "S01", "source_type": "txt", "source_range": "L1-L1",
            "source_text": text, "explicit_speaker": "not stated"}
    coding = {"_qda_run": {
        "library_version": "0.4", "contract_version": "0.1", "prompt_id": "QDA-GEN-DESCRIPTIVE-CODING",
        "prompt_version": "1.2", "prompt_source": "file", "backend": "ollama", "mode": "OPEN_DESCRIPTIVE",
        "provenance_level": "MODEL_BOUND", "model": model, "model_digest": digest,
        "source_sha256": source_sha, "n_units": 1, "n_ok": 1, "statuses": [{"unit_id": "S01", "status": "OK"}],
        **adapter.PINNED_OPEN_HASHES,
    }, "results": [{
        **unit, "concise_description": "Die Gruppe bespricht Gartenarbeit.",
        "narrative_function": "GENERAL_STATEMENT", "coding_decision": "CODES_ASSIGNED",
        "descriptive_codes": [{"code_label": LABEL, "definition": "Eine synthetische Kategorie.",
                               "status": "INDUCTIVE_CANDIDATE", "source_quote": text, "quote_locator": "L1-L1"}],
        "uncertainty": [],
    }]}
    validation = {"_qda_validation": {
        "validator_version": "0.4", "source_sha256": source_sha,
        "input_sha256": sha256_bytes(canonical_bytes(coding)), "result": {
            "verdict": "PASS", "quotes_fuzzy": 0, "quotes_wrong_unit": 0, "quotes_not_found": 0,
            "quotes_unbound": 0, "quotes_missing_evidence": 0, "locators_invalid": 0,
        },
    }, "data": deepcopy(coding)}
    segments = {"meta": {"source": case_id + ".txt", "source_type": "txt", "source_sha256": source_sha,
                         "mode": "paragraph", "note": adapter.SEGMENT_NOTE}, "source_units": [unit]}
    return {"segments": segments, "coding": coding, "validation": validation}


@pytest.fixture
def run_factory(
    fixture_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> Callable[..., SyntheticRun]:
    counter = 0

    def create(*, downstream: str = "none", research: bool = False) -> SyntheticRun:
        nonlocal counter
        counter += 1
        run = scan_source(
            fixture_root / "en" / "safe.txt", language="en", case_id=f"SYNTH-VERIFY-{counter}",
            run_root=tmp_path / "runs", synthetic=True,
        )
        assert not load_json(run / "detection-ledger.json")["findings"]
        key, _, _ = create_review_key(tmp_path / f"review-{counter}.pem")
        write_review(run, "SYNTHETIC-REVIEWER", [], signing_key=key)
        transform_run(run)
        if research:
            declare_method(run, "SYNTHETIC-ANALYST", "CODEBOOK")
            define_code(run, "SYNTHETIC-ANALYST", "CODE-1", "Protected label", "Protected synthetic definition.")
            text = (run / "transformed.txt").read_text()
            end = text.find("\n") if "\n" in text else len(text)
            apply_code(run, "SYNTHETIC-ANALYST", "CODE-1", 0, end, "Protected coding rationale.")
            write_memo(run, "SYNTHETIC-ANALYST", 0, end, "Protected synthetic memo.", "CODE-1")
        if downstream == "none":
            return SyntheticRun(run, key)
        config = load_config()
        pair = next(item for item in config.models.dpo_approved_local_pairs if item.tag == config.models.default)
        monkeypatch.setattr(adapter, "ollama_models", lambda endpoint: {pair.tag: pair.digest})

        def local_fixture(command: list[str], **kwargs: Any) -> SimpleNamespace:
            root = Path(command[command.index("--out-root") + 1]) / "protected-results"
            root.mkdir(mode=0o700)
            for role, payload in _payloads(Path(command[4]), command[3], pair.tag, pair.digest).items():
                atomic_json(root / (role + ".json"), payload)
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        def scanner(document: Any, language: str, policy: Any) -> list[Finding]:
            if downstream == "zero" or document.text != LABEL:
                return []
            return [Finding("F-SYNTHETIC", "PERSON", 0, len(LABEL), 0.9, "SyntheticLabelRecognizer",
                            "REPLACE_AND_REVIEW", sha256_bytes(LABEL.encode()))]

        monkeypatch.setattr(adapter.subprocess, "run", local_fixture)
        monkeypatch.setattr(adapter, "scan_document", scanner)
        if downstream == "zero":
            adapter.analyze_run(run)
        else:
            with pytest.raises(DownstreamBlocked, match="post-DigQDA scan"):
                adapter.analyze_run(run)
            attempt = next((run / "digqda-attempts").iterdir())
            if downstream == "reviewed":
                candidate = load_json(attempt / "aegis-attempt.json")["review_candidate"]
                decisions = [{"finding_id": item["finding_id"], "decision": "FALSE_POSITIVE",
                              "rationale": "Synthetic abstract category; no person is referenced."}
                             for item in candidate["findings"]]
                output_review.write_output_review(run, attempt.name, "SYNTHETIC-OUTPUT-REVIEWER", decisions, signing_key=key)
                output_review.finalize_output_review(run, attempt.name)
        return SyntheticRun(run, key)

    return create


def _phase(report: dict[str, object], name: str) -> dict[str, Any]:
    phases = report["phases"]
    assert isinstance(phases, list)
    return next(item for item in phases if item["phase"] == name)


@pytest.mark.parametrize("downstream", ["none", "zero", "reviewed"])
def test_valid_synthetic_run_is_source_free_read_only_and_offline(
    run_factory: Callable[..., SyntheticRun], monkeypatch: pytest.MonkeyPatch, downstream: str,
) -> None:
    item = run_factory(downstream=downstream, research=True)
    before = {str(path.relative_to(item.run)): path.read_bytes() for path in item.run.rglob("*") if path.is_file()}
    item.key.unlink()  # Verification uses embedded public signatures only.

    def forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("verification must never invoke network, model, signing or writes")

    monkeypatch.setattr("socket.create_connection", forbidden)
    monkeypatch.setattr("urllib.request.build_opener", forbidden)
    monkeypatch.setattr(adapter, "ollama_models", forbidden)
    monkeypatch.setattr(adapter.subprocess, "run", forbidden)
    monkeypatch.setattr("aegisqda.review_signature.sign_review", forbidden)
    monkeypatch.setattr("aegisqda.safeio.atomic_json", forbidden)
    report = verifier.verify_run(item.run)
    assert report["status"] == "SYNTHETIC_VERIFIED", report
    assert _phase(report, "PRIVACY")["review_assurance"] == "SELF_SIGNED_LOCAL"
    assert _phase(report, "RESEARCH")["event_count"] == 4
    if downstream == "reviewed":
        assert _phase(report, "DOWNSTREAM")["review_assurance"] == "SELF_SIGNED_LOCAL"
        assert _phase(report, "DOWNSTREAM")["reviewed_false_positive_count"] == 2
    assert report["network_used"] is False and report["release_authorization"] is False
    assert report["real_data_authorization"] is False and report["institutional_authorization"] is False
    rendered = json.dumps(report)
    for secret in (str(item.run), item.run.parent.name, "SYNTHETIC-REVIEWER", "SYNTHETIC-ANALYST", LABEL,
                   "Protected label", "Protected synthetic memo", "public_key", "model_digest"):
        assert secret not in rendered
    assert before == {str(path.relative_to(item.run)): path.read_bytes() for path in item.run.rglob("*") if path.is_file()}


@pytest.mark.parametrize("path", ["source.txt", "transformed.txt", "review.json", "privacy-release.json"])
def test_privacy_artifact_tamper_is_blocked_without_path_or_text_disclosure(
    run_factory: Callable[..., SyntheticRun], path: str,
) -> None:
    item = run_factory(downstream="zero")
    target = item.run / path
    target.write_bytes(target.read_bytes() + b"TAMPERED-SECRET")
    report = verifier.verify_run(item.run)
    assert report["status"] == "BLOCKED"
    assert "TAMPERED-SECRET" not in json.dumps(report) and str(item.run) not in json.dumps(report)


def test_legacy_or_changed_detector_is_blocked(
    run_factory: Callable[..., SyntheticRun], monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = run_factory()
    from aegisqda import privacy_gate
    current = privacy_gate.detector_versions
    monkeypatch.setattr(privacy_gate, "detector_versions", lambda language: {
        **current(language), "recognizer_pack": "aegis-custom-strict-v2",
    })
    assert verifier.verify_run(item.run)["status"] == "BLOCKED"


@pytest.mark.parametrize("kind", ["bytes", "new_finding", "pair", "contract", "extra_binding", "notice", "timestamp"])
def test_final_output_requires_exact_hashes_current_scan_and_known_bindings(
    run_factory: Callable[..., SyntheticRun], monkeypatch: pytest.MonkeyPatch, kind: str,
) -> None:
    item = run_factory(downstream="zero")
    final = load_json(item.final)
    if kind == "bytes":
        coding = next(item.attempt.rglob("coding.json"))
        coding.write_bytes(coding.read_bytes() + b" ")
    elif kind == "new_finding":
        monkeypatch.setattr(verifier, "_output_findings", lambda *args, **kwargs: [{"unreviewed": True}])
    elif kind == "pair":
        final["model_digest"] = "0" * 64
        _reseal(item.final, final)
    elif kind == "contract":
        final["prompt_sha256"] = "0" * 64
        _reseal(item.final, final)
    elif kind == "notice":
        final["notice"] = {"external_release": True}
        _reseal(item.final, final)
    elif kind == "timestamp":
        final["created_at"] = None
        _reseal(item.final, final)
    else:
        final["institutional_approval"] = True
        _reseal(item.final, final)
    assert verifier.verify_run(item.run)["status"] == "BLOCKED"


def test_forged_embedded_source_review_signature_cannot_be_resealed_as_valid(
    run_factory: Callable[..., SyntheticRun],
) -> None:
    item = run_factory()
    path = item.run / "review.json"
    review = load_json(path)
    review["signature"]["signature"] = "A" * 88
    _reseal(path, review)
    release_path = item.run / "privacy-release.json"
    release = load_json(release_path)
    release["review_sha256"] = sha256_file(path)
    _reseal(release_path, release)
    assert verifier.verify_run(item.run)["status"] == "BLOCKED"


def test_real_data_flag_cannot_inherit_a_synthetic_verification(
    run_factory: Callable[..., SyntheticRun],
) -> None:
    item = run_factory()
    path = item.run / "detection.json"
    detection = load_json(path)
    detection["synthetic_only"] = False
    _reseal(path, detection)
    assert verifier.verify_run(item.run)["status"] == "BLOCKED"


@pytest.mark.parametrize("kind", ["signature", "candidate", "decisions", "detectors"])
def test_reviewed_exemptions_cannot_inherit_changed_or_unsigned_bindings(
    run_factory: Callable[..., SyntheticRun], monkeypatch: pytest.MonkeyPatch, kind: str,
) -> None:
    item = run_factory(downstream="reviewed")
    review_path = item.attempt / output_review.REVIEW_FILE
    if kind == "detectors":
        current = output_review.detector_versions
        monkeypatch.setattr(output_review, "detector_versions", lambda language: {
            **current(language), "recognizer_pack": "synthetic-changed-pack",
        })
    elif kind == "candidate":
        path = item.attempt / "aegis-attempt.json"
        candidate = load_json(path)
        candidate["review_candidate"]["artifacts"]["coding"]["path"] = "../../coding.json"
        _reseal(path, candidate)
    else:
        review = load_json(review_path)
        if kind == "signature":
            review.pop("signature")
        else:
            review["decisions"][0]["decision"] = "KEEP"
        _reseal(review_path, review)
    assert verifier.verify_run(item.run)["status"] == "BLOCKED"


@pytest.mark.parametrize("kind", ["extra", "evidence", "missing", "duplicate_json"])
def test_research_event_log_tamper_remains_blocked(
    run_factory: Callable[..., SyntheticRun], kind: str,
) -> None:
    item = run_factory(research=True)
    path = item.run / "research" / "event-000003.json"
    event = load_json(path)
    if kind == "missing":
        path.unlink()
    elif kind == "duplicate_json":
        path.write_bytes(b'{"kind":"CODE_APPLIED","kind":"MEMO_WRITTEN"}')
    else:
        event["unreviewed_extra"] = "SECRET" if kind == "extra" else None
        if kind == "evidence":
            event.pop("unreviewed_extra")
            event["evidence_sha256"] = "0" * 64
        _reseal(path, event)
    assert verifier.verify_run(item.run)["status"] == "BLOCKED"


@pytest.mark.parametrize("kind", ["duplicate_artifact", "symlink", "foreign_attempt", "duplicate_json", "extra_detector_binding"])
def test_ambiguous_paths_and_malformed_history_fail_closed(
    run_factory: Callable[..., SyntheticRun], kind: str,
) -> None:
    item = run_factory(downstream="reviewed" if kind == "extra_detector_binding" else "zero")
    if kind == "duplicate_artifact":
        path = item.attempt / "duplicate"
        path.mkdir()
        (path / "coding.json").write_bytes(next(item.attempt.rglob("coding.json")).read_bytes())
    elif kind == "symlink":
        (item.run / "foreign-link").symlink_to(item.run / "source.txt")
    elif kind == "foreign_attempt":
        (item.run / "digqda-attempts" / "unknown").mkdir()
    elif kind == "extra_detector_binding":
        old_id = "0" * 32
        old = load_json(item.attempt / "aegis-attempt.json")
        old["attempt_id"] = old_id
        old["review_candidate"]["detector_versions"]["de"]["unknown_binding"] = True
        root = item.run / "digqda-attempts" / old_id
        root.mkdir()
        _reseal(root / "aegis-attempt.json", old)
    else:
        path = item.run / "privacy-release.json"
        path.write_bytes(b'{"state":"PRIVACY_RELEASED","state":"BLOCKED"}')
    assert verifier.verify_run(item.run)["status"] == "BLOCKED"


def test_current_runtime_control_change_invalidates_final(
    run_factory: Callable[..., SyntheticRun], monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = run_factory(downstream="zero")
    current = verifier._runtime_control_material
    monkeypatch.setattr(verifier, "_runtime_control_material", lambda root: (current(root)[0], "0" * 64))
    assert verifier.verify_run(item.run)["status"] == "BLOCKED"


def test_runtime_controls_must_still_match_after_output_scanning(
    run_factory: Callable[..., SyntheticRun], monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = run_factory(downstream="zero")
    controls, scan = verifier._runtime_control_material, verifier._output_findings
    changed = False

    def current(root: Path) -> tuple[dict[str, bytes], str]:
        files, digest = controls(root)
        return files, "0" * 64 if changed else digest

    def after_scan(*args: Any, **kwargs: Any) -> list[dict[str, object]]:
        nonlocal changed
        findings = scan(*args, **kwargs)
        changed = True
        return findings

    monkeypatch.setattr(verifier, "_runtime_control_material", current)
    monkeypatch.setattr(verifier, "_output_findings", after_scan)
    assert verifier.verify_run(item.run)["status"] == "BLOCKED"


@pytest.mark.parametrize("kind", ["release_bytes", "empty_attempt_directory"])
def test_stable_file_inventory_is_required_during_verification(
    run_factory: Callable[..., SyntheticRun], monkeypatch: pytest.MonkeyPatch, kind: str,
) -> None:
    item = run_factory(downstream="zero")
    original = verifier._output_findings

    def changed(*args: Any, **kwargs: Any) -> list[dict[str, object]]:
        findings = original(*args, **kwargs)
        if kind == "release_bytes":
            path = item.run / "privacy-release.json"
            path.write_bytes(path.read_bytes() + b" \n")
        else:
            (item.run / "digqda-attempts" / ("f" * 32)).mkdir()
        return findings

    monkeypatch.setattr(verifier, "_output_findings", changed)
    assert verifier.verify_run(item.run)["status"] == "BLOCKED"


def test_blocked_attempts_without_final_are_diagnosed_and_not_verified(
    run_factory: Callable[..., SyntheticRun],
) -> None:
    item = run_factory(downstream="blocked")
    report = verifier.verify_run(item.run)
    assert report["status"] == "BLOCKED"
    assert _phase(report, "DOWNSTREAM")["status"] == "NOT_PRESENT"


def test_clean_historical_failure_does_not_invalidate_later_verified_final(
    run_factory: Callable[..., SyntheticRun],
) -> None:
    item = run_factory(downstream="zero")
    final = load_json(item.final)
    old_id = "0" * 32
    old_root = item.run / "digqda-attempts" / old_id
    old_root.mkdir()
    atomic_json(old_root / "aegis-attempt.json", seal({
        "schema": "aegisqda-digqda-attempt-v1", "state": "BLOCKED", "attempt_id": old_id,
        "failure_kind": "DIGQDA_NONZERO", "ollama_think": False,
        "runtime_shim_sha256": final["runtime_shim_sha256"], "runtime_control_sha256": final["runtime_control_sha256"],
        "exit_code": 2, "stdout_sha256": sha256_bytes(b""), "stderr_sha256": sha256_bytes(b""),
    }))
    report = verifier.verify_run(item.run)
    assert report["status"] == "SYNTHETIC_VERIFIED", report
    assert _phase(report, "ATTEMPT_HISTORY")["blocked_attempts"] == 1
    assert _phase(report, "ATTEMPT_HISTORY")["DIGQDA_NONZERO"] == 1
