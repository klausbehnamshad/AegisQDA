"""Signed, exact synthetic downstream reviews; no retained identifier waiver."""

from __future__ import annotations

import base64
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import aegisqda.digqda_adapter as adapter
import aegisqda.output_review as output_review
from aegisqda.config import load_config
from aegisqda.detection import Finding
from aegisqda.errors import AegisError, DownstreamBlocked, IntegrityError, ReviewRequired
from aegisqda.manifests import canonical_bytes, seal, sha256_bytes, sha256_file, verify_seal
from aegisqda.review_signature import create_review_key, verify_review_signature
from aegisqda.safeio import atomic_json, load_json
from aegisqda.workflow import scan_source, transform_run, write_review

LABEL = "Synthetischer Kategorieterm"


def test_duplicate_json_fields_are_not_reviewable(tmp_path: Path) -> None:
    path = tmp_path / "ambiguous.json"
    path.write_text('{"state":"BLOCKED","state":"ACCEPTED"}')
    with pytest.raises(IntegrityError, match="invalid JSON"):
        output_review._read(path)


@dataclass(frozen=True)
class BlockedOutput:
    run: Path
    attempt_id: str
    key: Path

    @property
    def attempt_root(self) -> Path:
        return self.run / "digqda-attempts" / self.attempt_id

    @property
    def attempt_path(self) -> Path:
        return self.attempt_root / "aegis-attempt.json"

    @property
    def review_path(self) -> Path:
        return self.attempt_root / output_review.REVIEW_FILE

    @property
    def decisions(self) -> list[dict[str, str]]:
        candidate = load_json(self.attempt_path)["review_candidate"]
        return [{
            "finding_id": finding["finding_id"], "decision": "FALSE_POSITIVE",
            "rationale": "Synthetic abstract category; no person is referenced.",
        } for finding in candidate["findings"]]

    def sign(self) -> Path:
        return output_review.write_output_review(
            self.run, self.attempt_id, "SYNTHETIC-OUTPUT-REVIEWER", self.decisions,
            signing_key=self.key,
        )


def _reseal(path: Path, payload: dict[str, Any]) -> None:
    payload = deepcopy(payload)
    payload.pop("integrity_sha256", None)
    path.write_bytes(canonical_bytes(seal(payload)) + b"\n")


def _payloads(source: Path, case_id: str, model: str, digest: str) -> dict[str, dict[str, Any]]:
    source_sha = sha256_file(source)
    source_text = source.read_text(encoding="utf-8").strip()
    unit = {
        "unit_id": "S01", "source_type": "txt", "source_range": "L1-L1",
        "source_text": source_text, "explicit_speaker": "not stated",
    }
    segments = {
        "meta": {
            "source": case_id + ".txt", "source_type": "txt", "source_sha256": source_sha,
            "mode": "paragraph", "note": adapter.SEGMENT_NOTE,
        },
        "source_units": [deepcopy(unit)],
    }
    coding = {
        "_qda_run": {
            "library_version": "0.4", "contract_version": "0.1",
            "prompt_id": "QDA-GEN-DESCRIPTIVE-CODING", "prompt_version": "1.2",
            "prompt_source": "file", "backend": "ollama", "mode": "OPEN_DESCRIPTIVE",
            "provenance_level": "MODEL_BOUND", "model": model, "model_digest": digest,
            "source_sha256": source_sha, "n_units": 1, "n_ok": 1,
            "statuses": [{"unit_id": "S01", "status": "OK"}],
            **adapter.PINNED_OPEN_HASHES,
        },
        "results": [{
            **unit, "concise_description": "Die Gruppe bespricht Gartenarbeit und Verkehr.",
            "narrative_function": "GENERAL_STATEMENT", "coding_decision": "CODES_ASSIGNED",
            "descriptive_codes": [{
                "code_label": LABEL, "definition": "Eine synthetische Kategorie der Diskussion.",
                "status": "INDUCTIVE_CANDIDATE", "source_quote": source_text,
                "quote_locator": "L1-L1",
            }], "uncertainty": [],
        }],
    }
    validation = {
        "_qda_validation": {
            "validator_version": "0.4", "source_sha256": source_sha,
            "input_sha256": sha256_bytes(canonical_bytes(coding)),
            "result": {
                "verdict": "PASS", "quotes_fuzzy": 0, "quotes_wrong_unit": 0,
                "quotes_not_found": 0, "quotes_unbound": 0, "quotes_missing_evidence": 0,
                "locators_invalid": 0,
            },
        }, "data": deepcopy(coding),
    }
    return {"segments": segments, "coding": coding, "validation": validation}


@pytest.fixture
def blocked_output(
    fixture_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> BlockedOutput:
    # The real registered fixture workflow and privacy replay run without
    # monkeypatching detection, signatures, source registration or privacy gates.
    root = tmp_path.resolve()
    run = scan_source(
        fixture_root / "en" / "safe.txt", language="en", case_id="SYNTH-OUTPUT-REVIEW",
        run_root=root / "runs", synthetic=True,
    )
    assert load_json(run / "detection-ledger.json")["findings"] == []
    write_review(run, "SYNTHETIC-SOURCE-REVIEWER", [])
    transform_run(run)
    key, _, _ = create_review_key(root / "synthetic-output-review.pem")
    config = load_config()
    pair = next(item for item in config.models.dpo_approved_local_pairs if item.tag == config.models.default)
    monkeypatch.setattr(adapter, "ollama_models", lambda endpoint: {pair.tag: pair.digest})

    def fake_downstream(command: list[str], **kwargs: Any) -> SimpleNamespace:
        destination = Path(command[command.index("--out-root") + 1]) / "protected-results"
        destination.mkdir(mode=0o700)
        payloads = _payloads(Path(command[4]), command[3], pair.tag, pair.digest)
        assert kwargs["env"]["AEGISQDA_APPROVED_MODEL_DIGEST"] == pair.digest
        for role, payload in payloads.items():
            atomic_json(destination / f"{role}.json", payload)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def abstract_label_finding(document, language, policy):
        if document.text != LABEL:
            return []
        return [Finding(
            "F-SYNTHETIC", "PERSON", 0, len(LABEL), 0.9, "SyntheticLabelRecognizer",
            "REPLACE_AND_REVIEW", sha256_bytes(LABEL.encode()),
        )]

    monkeypatch.setattr(adapter.subprocess, "run", fake_downstream)
    monkeypatch.setattr(adapter, "scan_document", abstract_label_finding)
    with pytest.raises(DownstreamBlocked, match="post-DigQDA scan"):
        adapter.analyze_run(run, pair.tag)
    attempts = list((run / "digqda-attempts").iterdir())
    assert len(attempts) == 1
    result = BlockedOutput(run, attempts[0].name, key)
    attempt = load_json(result.attempt_path)
    verify_seal(attempt)
    assert attempt["failure_kind"] == "POST_SCAN_FINDINGS"
    assert attempt["state"] == "BLOCKED"
    # The exact copied label in validation is a separate reviewed occurrence.
    assert attempt["finding_count"] == 2
    assert len(result.decisions) == 2
    assert not (run / "digqda-run.json").exists()
    return result


def test_signed_complete_output_review_reaches_only_methodological_review(
    blocked_output: BlockedOutput,
) -> None:
    original_attempt = sha256_file(blocked_output.attempt_path)
    review_path = blocked_output.sign()
    review = load_json(review_path)
    assert verify_review_signature(review)
    assert review["assurance"] == "SELF_SIGNED_LOCAL"
    assert not (blocked_output.run / "digqda-run.json").exists()
    finalized = output_review.finalize_output_review(blocked_output.run, blocked_output.attempt_id)
    manifest = load_json(finalized)
    verify_seal(manifest)
    assert manifest["state"] == "DOWNSTREAM_REVIEW_REQUIRED"
    assert manifest["post_scan_findings"] == 2
    assert manifest["post_scan_false_positive_count"] == 2
    assert manifest["post_scan_unresolved"] == 0
    assert manifest["output_review_sha256"] == sha256_file(review_path)
    assert manifest["output_review_assurance"] == "SELF_SIGNED_LOCAL"
    assert "external release" in manifest["notice"]
    assert sha256_file(blocked_output.attempt_path) == original_attempt
    assert load_json(blocked_output.attempt_path)["state"] == "BLOCKED"
    with pytest.raises(DownstreamBlocked, match="already exists"):
        output_review.finalize_output_review(blocked_output.run, blocked_output.attempt_id)


def test_output_bytes_changed_after_review_remain_blocked(blocked_output: BlockedOutput) -> None:
    blocked_output.sign()
    candidate = load_json(blocked_output.attempt_path)["review_candidate"]
    coding = blocked_output.attempt_root / candidate["artifacts"]["coding"]["path"]
    coding.write_bytes(coding.read_bytes() + b" ")
    with pytest.raises(DownstreamBlocked, match="artifact changed"):
        output_review.finalize_output_review(blocked_output.run, blocked_output.attempt_id)
    assert not (blocked_output.run / "digqda-run.json").exists()


def test_resealed_candidate_after_review_cannot_inherit_signed_decisions(
    blocked_output: BlockedOutput,
) -> None:
    blocked_output.sign()
    attempt = load_json(blocked_output.attempt_path)
    attempt["review_candidate"]["diagnostic_note"] = "A resealed synthetic successor"
    _reseal(blocked_output.attempt_path, attempt)
    with pytest.raises(DownstreamBlocked, match="review binding"):
        output_review.finalize_output_review(blocked_output.run, blocked_output.attempt_id)
    assert not (blocked_output.run / "digqda-run.json").exists()


@pytest.mark.parametrize("changed_artifact", ["privacy-release.json", "aegis-attempt.json"])
def test_bindings_changed_during_output_scan_cannot_be_signed(
    blocked_output: BlockedOutput, monkeypatch: pytest.MonkeyPatch, changed_artifact: str,
) -> None:
    original_scan = output_review._output_findings

    def changed_during_scan(*args: Any, **kwargs: Any) -> list[dict[str, object]]:
        result = original_scan(*args, **kwargs)
        path = (
            blocked_output.run / changed_artifact
            if changed_artifact == "privacy-release.json" else blocked_output.attempt_path
        )
        # Whitespace preserves parsed content and its seal; the signed byte
        # binding must still reject this change during the scan transaction.
        path.write_bytes(path.read_bytes() + b" \n")
        return result

    monkeypatch.setattr(output_review, "_output_findings", changed_during_scan)
    with pytest.raises(DownstreamBlocked, match="changed during output review validation"):
        blocked_output.sign()
    assert not blocked_output.review_path.exists()
    assert not (blocked_output.run / "digqda-run.json").exists()


@pytest.mark.parametrize("problem", ["missing", "duplicate", "unknown", "extra_field", "short_rationale"])
def test_every_output_occurrence_needs_one_bounded_explicit_decision(
    blocked_output: BlockedOutput, problem: str,
) -> None:
    decisions = blocked_output.decisions
    if problem == "missing":
        decisions.pop()
    elif problem == "duplicate":
        decisions[1] = deepcopy(decisions[0])
    elif problem == "unknown":
        decisions[0]["finding_id"] = "0" * 64
    elif problem == "extra_field":
        decisions[0]["retained_risk"] = "not authorized"
    else:
        decisions[0]["rationale"] = "short"
    with pytest.raises(ReviewRequired):
        output_review.write_output_review(
            blocked_output.run, blocked_output.attempt_id, "SYNTHETIC-OUTPUT-REVIEWER",
            decisions, signing_key=blocked_output.key,
        )
    assert not blocked_output.review_path.exists()
    assert not (blocked_output.run / "digqda-run.json").exists()


@pytest.mark.parametrize("decision", ["CONFIRMED", "KEEP", "KEEP_AND_REVIEW", "UNSURE"])
def test_true_or_uncertain_output_identifiers_have_no_keep_path(
    blocked_output: BlockedOutput, decision: str,
) -> None:
    decisions = blocked_output.decisions
    decisions[0]["decision"] = decision
    with pytest.raises(ReviewRequired, match="must remain blocked"):
        output_review.write_output_review(
            blocked_output.run, blocked_output.attempt_id, "SYNTHETIC-OUTPUT-REVIEWER",
            decisions, signing_key=blocked_output.key,
        )
    assert not blocked_output.review_path.exists()


@pytest.mark.parametrize("problem", ["absent", "absent_unkeyed", "forged"])
def test_missing_or_forged_review_signature_never_finalizes(
    blocked_output: BlockedOutput, problem: str,
) -> None:
    blocked_output.sign()
    review = load_json(blocked_output.review_path)
    if problem.startswith("absent"):
        review.pop("signature")
        if problem == "absent_unkeyed":
            review["assurance"] = "UNKEYED_SYNTHETIC_ONLY"
    else:
        review["signature"]["signature"] = base64.b64encode(b"\x00" * 64).decode()
    _reseal(blocked_output.review_path, review)
    with pytest.raises(AegisError):
        output_review.finalize_output_review(blocked_output.run, blocked_output.attempt_id)
    assert not (blocked_output.run / "digqda-run.json").exists()


def test_unapproved_candidate_model_pair_remains_blocked(blocked_output: BlockedOutput) -> None:
    attempt = load_json(blocked_output.attempt_path)
    attempt["review_candidate"]["model_digest"] = "0" * 64
    _reseal(blocked_output.attempt_path, attempt)
    with pytest.raises(DownstreamBlocked, match="model pair is not approved"):
        blocked_output.sign()
    assert not blocked_output.review_path.exists()


def test_changed_detector_manifest_invalidates_output_review(
    blocked_output: BlockedOutput, monkeypatch: pytest.MonkeyPatch,
) -> None:
    blocked_output.sign()
    original = output_review.detector_versions
    monkeypatch.setattr(output_review, "detector_versions", lambda language: {
        **original(language), "recognizer_pack": "synthetic-successor-pack",
    })
    with pytest.raises(DownstreamBlocked, match="obsolete"):
        output_review.finalize_output_review(blocked_output.run, blocked_output.attempt_id)


def test_newly_detected_output_finding_cannot_inherit_old_decisions(
    blocked_output: BlockedOutput, monkeypatch: pytest.MonkeyPatch,
) -> None:
    blocked_output.sign()
    original = adapter.scan_document

    def additional_finding(document, language, policy):
        current = original(document, language, policy)
        if document.text.startswith("Eine synthetische Kategorie"):
            current.append(Finding(
                "F-ADDITIONAL", "PERSON", 0, 4, 0.9, "SyntheticSuccessorRecognizer",
                "REPLACE_AND_REVIEW", sha256_bytes(document.text[:4].encode()),
            ))
        return current

    monkeypatch.setattr(adapter, "scan_document", additional_finding)
    with pytest.raises(DownstreamBlocked, match="complete fresh post-scan"):
        output_review.finalize_output_review(blocked_output.run, blocked_output.attempt_id)


def test_changed_frozen_runtime_control_invalidates_review(blocked_output: BlockedOutput) -> None:
    blocked_output.sign()
    shim = blocked_output.attempt_root / "runtime-control/sitecustomize.py"
    shim.write_bytes(shim.read_bytes() + b"\n# Synthetic changed control\n")
    with pytest.raises(DownstreamBlocked, match="runtime controls changed"):
        output_review.finalize_output_review(blocked_output.run, blocked_output.attempt_id)


def test_changed_repository_runtime_binding_invalidates_review(
    blocked_output: BlockedOutput, monkeypatch: pytest.MonkeyPatch,
) -> None:
    blocked_output.sign()
    original = output_review._runtime_control_material

    def changed_material(path: Path):
        files, digest = original(path)
        return files, "0" * 64 if path == output_review.RUNTIME_CONTROL_ROOT else digest

    monkeypatch.setattr(output_review, "_runtime_control_material", changed_material)
    with pytest.raises(DownstreamBlocked, match="runtime controls changed"):
        output_review.finalize_output_review(blocked_output.run, blocked_output.attempt_id)


@pytest.mark.parametrize("escape", ["parent", "absolute", "symlink"])
def test_candidate_cannot_read_artifacts_outside_its_protected_attempt(
    blocked_output: BlockedOutput, escape: str,
) -> None:
    attempt = load_json(blocked_output.attempt_path)
    record = attempt["review_candidate"]["artifacts"]["coding"]
    original = blocked_output.attempt_root / record["path"]
    outside = blocked_output.attempt_root.parent / "outside"
    outside.mkdir()
    target = outside / "coding.json"
    target.write_bytes(original.read_bytes())
    if escape == "parent":
        record["path"] = "../outside/coding.json"
    elif escape == "absolute":
        record["path"] = str(target)
    else:
        (blocked_output.attempt_root / "escaped").symlink_to(outside, target_is_directory=True)
        record["path"] = "escaped/coding.json"
    _reseal(blocked_output.attempt_path, attempt)
    with pytest.raises(AegisError):
        blocked_output.sign()
    assert not blocked_output.review_path.exists()
    assert not (blocked_output.run / "digqda-run.json").exists()


def test_terminal_context_shows_control_and_bidi_characters_as_visible_escapes() -> None:
    escaped = output_review._terminal_text("Care\x1b[31m\x9b\u202e\u2066Ü\n")
    assert "\\u001b" in escaped and "\\u009b" in escaped
    assert "\\u202e" in escaped and "\\u2066" in escaped
    assert "Ü" in escaped and "\\n" in escaped
    for unsafe in ("\x1b", "\x9b", "\u202e", "\u2066", "\n"):
        assert unsafe not in escaped


def test_interactive_review_displays_bound_field_and_context_then_signs(
    blocked_output: BlockedOutput, monkeypatch: pytest.MonkeyPatch, capsys,
) -> None:
    answers = iter([answer for _ in blocked_output.decisions for answer in (
        "FALSE_POSITIVE", "Synthetic abstract category; no person is referenced.",
    )])
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))
    path = output_review.interactive_output_review(
        blocked_output.run, blocked_output.attempt_id, "SYNTHETIC-OUTPUT-REVIEWER", blocked_output.key,
    )
    display = capsys.readouterr().out
    assert LABEL in display
    assert "code_label" in display
    assert "Bound context:" in display
    assert "no external or methodological release" in display
    assert path == blocked_output.review_path
    assert verify_review_signature(load_json(path))
    assert not (blocked_output.run / "digqda-run.json").exists()
