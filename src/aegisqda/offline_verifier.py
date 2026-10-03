"""Read-only verification of local synthetic privacy and research bundles.

The report discloses counts and fixed diagnostic codes only. This module never
contacts Ollama, signs a decision, writes a release, or approves a real pilot.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Any

from .config import load_config
from .digqda_adapter import (
    PINNED_OPEN_HASHES, RUNTIME_CONTROL_ROOT, _output_findings, _released_surrogates,
    _runtime_control_material, _validate_digqda_contract,
)
from .errors import IntegrityError
from .manifests import canonical_bytes, sha256_bytes, verify_seal
from .output_review import ATTEMPT_ID, OUTPUT_CONTRACT, REVIEW_FILE, _candidate, _decisions, _read
from .privacy_gate import validate_release
from .review_signature import verify_synthetic_review
from .safeio import read_stable_source, resolved_no_symlink, validate_opaque_id, validate_run_dir
from .workbench import _load as _load_research

SHA = re.compile(r"[0-9a-f]{64}\Z")
PRIVACY_FILES = (
    "detection.json", "detection-ledger.json", "review.json", "second-pass.json", "privacy-release.json",
)
FINAL_COMMON = {
    "schema", "state", "created_at", "attempt_id", "privacy_release_sha256", "model", "model_digest",
    "digqda_coding_sha256", "digqda_validation_sha256", "digqda_segments_sha256", "contract_version",
    "contract_sha256", "prompt_version", "prompt_sha256", "schema_sha256", "validator_verdict",
    "post_scan_findings", "post_scan_analytical_language", "post_scan_source_language", "ollama_think",
    "runtime_shim_sha256", "runtime_control_sha256", "notice", "integrity_sha256",
}
FINAL_REVIEWED = {
    "grammar_sha256", "post_scan_false_positive_count", "post_scan_unresolved",
    "output_review_sha256", "output_review_assurance",
}
ATTEMPT_COMMON = {
    "schema", "state", "attempt_id", "failure_kind", "ollama_think", "runtime_shim_sha256",
    "runtime_control_sha256", "integrity_sha256",
}
FAILURES = {
    "LOCAL_EXECUTION_FAILURE", "RUNTIME_CONTROL_CHANGED", "INPUT_RELEASE_CHANGED", "DIGQDA_NONZERO",
    "OUTPUT_ENVELOPE_INVALID", "CONTRACT_REVALIDATION_FAILED", "OUTPUT_CHANGED_DURING_SCAN",
    "POST_SCAN_CONTRACT_INVALID", "POST_SCAN_FINDINGS",
}
EVENT_COMMON = {
    "schema", "sequence", "created_at", "analyst_id", "assurance", "previous_event_sha256",
    "privacy_release_sha256", "transformed_sha256", "kind", "integrity_sha256",
}
EVENT_FIELDS = {
    "METHOD_DECLARED": {"method"},
    "CODE_DEFINED": {"code_id", "label", "definition", "parent_id"},
    "CODE_APPLIED": {"code_id", "start", "end", "rationale", "evidence_sha256"},
    "MEMO_WRITTEN": {"start", "end", "memo", "code_id", "evidence_sha256"},
}
CANDIDATE_FIELDS = {
    "synthetic_only", "language", "source_label", "model", "model_digest", "privacy_release_sha256",
    "artifacts", "contract", "detector_versions", "findings",
}
FINDING_FIELDS = {
    "finding_id", "path_name", "artifact_path", "field_path", "view_index", "start", "end",
    "entity_type", "value_sha256", "scan_language",
}
DETECTOR_FIELDS = {
    "presidio_analyzer", "spacy", "nlp_strategy", "ner_model", "threshold", "recognizer_pack",
}
FINAL_NOTICE = "DigQDA output remains protected and requires methodological human review"
REVIEWED_NOTICE = (
    "Protected synthetic output; signed detector review does not replace methodological human review "
    "or authorize external release"
)


def _require(condition: bool) -> None:
    if not condition:
        raise IntegrityError("offline verification binding is invalid")


def _sha(value: object) -> bool:
    return isinstance(value, str) and SHA.fullmatch(value) is not None


def _timestamp(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = datetime.fromisoformat(value)
        return parsed.tzinfo is not None and parsed.utcoffset() == timezone.utc.utcoffset(parsed)
    except ValueError:
        return False


def _snapshot(root: Path) -> dict[str, str]:
    """Reject symlinks and bind the file inventory throughout verification."""
    result: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        _require(not path.is_symlink())
        if path.is_file():
            result[path.relative_to(root).as_posix()] = sha256_bytes(read_stable_source(path))
        elif path.is_dir():
            result[path.relative_to(root).as_posix() + "/"] = "DIRECTORY"
        else:
            raise IntegrityError("offline file inventory contains a foreign filesystem object")
    return result


def _runtime(root: Path, manifest: dict[str, Any]) -> None:
    for location in (RUNTIME_CONTROL_ROOT, root / "runtime-control"):
        files, tree_sha = _runtime_control_material(location)
        _require(
            tree_sha == manifest.get("runtime_control_sha256")
            and sha256_bytes(files["sitecustomize.py"]) == manifest.get("runtime_shim_sha256")
        )


def _review_shape(review: dict[str, Any], attempt_id: str) -> None:
    _require(set(review) == {
        "schema", "state", "synthetic_only", "attempt_id", "reviewer_id", "reviewed_at", "binding",
        "decisions", "assurance", "signature", "integrity_sha256",
    })
    _require(
        review.get("schema") == "aegisqda-output-review-v1" and review.get("state") == "ACCEPTED"
        and review.get("synthetic_only") is True and review.get("attempt_id") == attempt_id
        and _timestamp(review.get("reviewed_at"))
    )
    validate_opaque_id(review["reviewer_id"], label="reviewer id")
    verify_seal(review)
    _require(verify_synthetic_review(review, load_config().authorization.trusted_review_key_ids))


def _candidate_shape(candidate: object) -> dict[str, Any]:
    _require(isinstance(candidate, dict) and set(candidate) == CANDIDATE_FIELDS)
    assert isinstance(candidate, dict)
    findings, artifacts = candidate["findings"], candidate["artifacts"]
    _require(
        candidate["synthetic_only"] is True and isinstance(findings, list) and bool(findings)
        and candidate["language"] in {"de", "en", "fr", "tr"}
        and _sha(candidate["privacy_release_sha256"])
        and canonical_bytes(candidate["contract"]) == canonical_bytes(OUTPUT_CONTRACT)
        and isinstance(candidate["detector_versions"], dict)
        and set(candidate["detector_versions"]) == {candidate["language"], "de"}
        and (candidate["model"], candidate["model_digest"]) in {
            (item.tag, item.digest) for item in load_config().models.dpo_approved_local_pairs
        }
    )
    label = candidate["source_label"]
    _require(isinstance(label, str) and Path(label).name == label and Path(label).suffix in {".txt", ".srt"})
    validate_opaque_id(Path(label).stem, label="source label")
    for detector in candidate["detector_versions"].values():
        _require(isinstance(detector, dict) and set(detector) == DETECTOR_FIELDS)
        _require(
            all(isinstance(detector[key], str) and bool(detector[key])
                for key in ("presidio_analyzer", "spacy", "nlp_strategy", "recognizer_pack"))
            and (detector["ner_model"] is None or isinstance(detector["ner_model"], str))
            and type(detector["threshold"]) in {float, int} and detector["threshold"] == 0.5
            and detector["recognizer_pack"] in {
                "aegis-custom-strict-v1", "aegis-custom-strict-v2", "aegis-custom-strict-v3",
            }
        )
    _require(isinstance(artifacts, dict) and set(artifacts) == {"segments", "coding", "validation"})
    for role, record in artifacts.items():
        _require(isinstance(record, dict) and set(record) == {"path", "sha256"} and _sha(record["sha256"]))
        relative = record["path"]
        _require(
            isinstance(relative, str) and not Path(relative).is_absolute()
            and ".." not in Path(relative).parts and Path(relative).name == role + ".json"
        )
    ids: set[str] = set()
    for finding in findings:
        _require(isinstance(finding, dict) and set(finding) == FINDING_FIELDS)
        finding_id = finding["finding_id"]
        _require(_sha(finding_id) and finding_id not in ids and _sha(finding["value_sha256"]))
        _require(finding_id == sha256_bytes(canonical_bytes({
            key: value for key, value in finding.items() if key != "finding_id"
        })))
        _require(
            type(finding["start"]) is int and type(finding["end"]) is int
            and 0 <= finding["start"] < finding["end"]
            and type(finding["view_index"]) is int and finding["view_index"] >= 0
            and isinstance(finding["field_path"], list)
            and all(type(item) is str or (type(item) is int and item >= 0) for item in finding["field_path"])
            and finding["path_name"] in {"segments.json", "coding.json", "validation.json"}
            and finding["artifact_path"] == artifacts[finding["path_name"].removesuffix(".json")]["path"]
            and finding["scan_language"] in {candidate["language"], "de"}
            and isinstance(finding["entity_type"], str)
            and re.fullmatch(r"[A-Z][A-Z0-9_]*", finding["entity_type"]) is not None
        )
        ids.add(finding_id)
    return candidate


def _history(run: Path, selected: str | None) -> dict[str, int]:
    root = run / "digqda-attempts"
    if not root.exists():
        _require(selected is None)
        return {"attempts": 0, "blocked_attempts": 0}
    _require(root.is_dir() and not root.is_symlink())
    counts: Counter[str] = Counter()
    found: set[str] = set()
    for location in sorted(root.iterdir()):
        _require(location.is_dir() and not location.is_symlink() and bool(ATTEMPT_ID.fullmatch(location.name)))
        found.add(location.name)
        counts["attempts"] += 1
        path = location / "aegis-attempt.json"
        if not path.exists():
            _require(location.name == selected and not (location / REVIEW_FILE).exists())
            continue
        attempt, attempt_sha = _read(path)
        verify_seal(attempt)
        kind = attempt.get("failure_kind")
        _require(isinstance(kind, str) and kind in FAILURES)
        assert isinstance(kind, str)
        extra = {"finding_count", "review_candidate"} if kind == "POST_SCAN_FINDINGS" else (
            {"exit_code", "stdout_sha256", "stderr_sha256"} if kind == "DIGQDA_NONZERO" else set()
        )
        _require(set(attempt) == ATTEMPT_COMMON | extra)
        _require(
            attempt.get("schema") == "aegisqda-digqda-attempt-v1" and attempt.get("state") == "BLOCKED"
            and attempt.get("attempt_id") == location.name and attempt.get("ollama_think") is False
            and _sha(attempt.get("runtime_shim_sha256")) and _sha(attempt.get("runtime_control_sha256"))
        )
        if kind == "DIGQDA_NONZERO":
            _require(type(attempt["exit_code"]) is int and attempt["exit_code"] != 0)
            _require(_sha(attempt["stdout_sha256"]) and _sha(attempt["stderr_sha256"]))
        if kind == "POST_SCAN_FINDINGS":
            candidate = _candidate_shape(attempt["review_candidate"])
            _require(type(attempt["finding_count"]) is int and attempt["finding_count"] == len(candidate["findings"]))
            if (location / REVIEW_FILE).exists():
                review, _ = _read(location / REVIEW_FILE)
                _review_shape(review, location.name)
                binding = review["binding"]
                _require(isinstance(binding, dict) and set(binding) == {
                    "attempt_sha256", "privacy_release_sha256", "detectors", "contract",
                })
                _require(
                    binding["attempt_sha256"] == attempt_sha
                    and binding["privacy_release_sha256"] == candidate["privacy_release_sha256"]
                    and canonical_bytes(binding["detectors"]) == canonical_bytes(candidate["detector_versions"])
                    and canonical_bytes(binding["contract"]) == canonical_bytes(candidate["contract"])
                )
                _decisions(review["decisions"], candidate["findings"])
        else:
            _require(not (location / REVIEW_FILE).exists())
        counts["blocked_attempts"] += 1
        counts[kind] += 1
    _require(selected is None or selected in found)
    return {"attempts": counts["attempts"], "blocked_attempts": counts["blocked_attempts"], **{
        kind: counts[kind] for kind in sorted(FAILURES) if counts[kind]
    }}


def _downstream(run: Path, transformed: Path, release: dict[str, Any], release_sha: str) -> dict[str, Any]:
    final, _ = _read(run / "digqda-run.json")
    verify_seal(final)
    reviewed = "output_review_sha256" in final
    _require(set(final) == FINAL_COMMON | (FINAL_REVIEWED if reviewed else set()))
    config = load_config()
    _require(
        final.get("schema") == "aegisqda-digqda-run-v1" and final.get("state") == "DOWNSTREAM_REVIEW_REQUIRED"
        and _timestamp(final.get("created_at"))
        and final.get("notice") == (REVIEWED_NOTICE if reviewed else FINAL_NOTICE)
        and final.get("privacy_release_sha256") == release_sha
        and (final.get("model"), final.get("model_digest")) in {
            (item.tag, item.digest) for item in config.models.dpo_approved_local_pairs
        }
        and final.get("model") in config.models.dpo_approved_local_allowlist
        and final.get("contract_version") == "0.1" and final.get("prompt_version") == "1.2"
        and all(final.get(key) == value for key, value in PINNED_OPEN_HASHES.items() if key != "grammar_sha256" or reviewed)
        and final.get("validator_verdict") == "PASS" and final.get("ollama_think") is False
        and final.get("post_scan_source_language") == release.get("language")
        and final.get("post_scan_analytical_language") == "de"
        and isinstance(final.get("attempt_id"), str) and bool(ATTEMPT_ID.fullmatch(final["attempt_id"]))
    )
    root = resolved_no_symlink(run / "digqda-attempts" / final["attempt_id"])
    _runtime(root, final)
    paths: dict[str, Path] = {}
    payloads: dict[str, dict[str, Any]] = {}
    for role in ("segments", "coding", "validation"):
        matches = list(root.rglob(role + ".json"))
        _require(len(matches) == 1)
        paths[role] = resolved_no_symlink(matches[0])
        payload, content_sha = _read(paths[role])
        _require(content_sha == final.get(f"digqda_{role}_sha256"))
        payloads[role] = payload
    _validate_digqda_contract(
        payloads["coding"], payloads["validation"], final["model"], final["model_digest"], release["transformed_sha256"],
    )
    if reviewed:
        attempt, candidate, _, candidate_paths, binding = _candidate(run, final["attempt_id"])
        _candidate_shape(candidate)
        _require(candidate_paths == paths)
        review, review_sha = _read(root / REVIEW_FILE)
        _review_shape(review, final["attempt_id"])
        _require(canonical_bytes(review["binding"]) == canonical_bytes(binding))
        _decisions(review["decisions"], candidate["findings"])
        _require(
            final["output_review_sha256"] == review_sha and final["output_review_assurance"] == review["assurance"]
            and type(final["post_scan_findings"]) is int and final["post_scan_findings"] == len(candidate["findings"])
            and type(final["post_scan_false_positive_count"]) is int
            and final["post_scan_false_positive_count"] == len(review["decisions"])
            and type(final["post_scan_unresolved"]) is int and final["post_scan_unresolved"] == 0
            and final["runtime_shim_sha256"] == attempt["runtime_shim_sha256"]
            and final["runtime_control_sha256"] == attempt["runtime_control_sha256"]
            and final["model"] == candidate["model"] and final["model_digest"] == candidate["model_digest"]
        )
    else:
        _require(not (root / "aegis-attempt.json").exists() and not (root / REVIEW_FILE).exists())
        trusted = _released_surrogates(run, transformed, release)
        findings = _output_findings(
            list(paths.values()), release["language"], prompt_sha256=final["prompt_sha256"],
            trusted_surrogates=trusted, expected_coding=payloads["coding"],
            source_label=release["case_id"] + transformed.suffix.lower(), artifact_root=root,
        )
        _require(type(final["post_scan_findings"]) is int and final["post_scan_findings"] == 0 and not findings)
    return {
        "attempt_id": final["attempt_id"], "finding_count": final["post_scan_findings"],
        "reviewed_false_positive_count": final.get("post_scan_false_positive_count", 0),
        "review_assurance": final.get("output_review_assurance", "NO_OUTPUT_EXEMPTIONS"),
    }


def verify_run(run_dir: Path) -> dict[str, object]:
    """Return a source-free current verification report without any mutation."""
    phases: list[dict[str, object]] = []
    report: dict[str, object] = {
        "schema": "aegisqda-offline-verification-v1", "status": "BLOCKED", "read_only": True,
        "network_used": False, "release_authorization": False, "real_data_authorization": False,
        "institutional_authorization": False, "phases": phases,
        "notice": "Current local synthetic bundle verification only. Checks privacy, core downstream artifacts, "
        "research events and attempt markers; supplementary outputs remain protected. Self-signed signatures "
        "prove local key possession. Methodological human review remains required; no external release, "
        "real-data pilot authorization or universal anonymity assurance.",
    }
    phase = "PRIVACY"
    try:
        run = validate_run_dir(run_dir)
        before = _snapshot(run)
        privacy = {name: _read(run / name)[0] for name in PRIVACY_FILES}
        transformed, release = validate_release(run)
        release_sha = before["privacy-release.json"]
        ledger = privacy["detection-ledger.json"]
        _require(isinstance(ledger.get("findings"), list))
        phases.append({"phase": phase, "status": "VERIFIED", "finding_count": len(ledger["findings"]),
                       "review_assurance": privacy["review.json"]["assurance"]})
        phase = "RESEARCH"
        root = run / "research"
        if root.exists():
            for path in sorted(root.iterdir()):
                event, _ = _read(path)
                kind = event.get("kind")
                _require(kind in EVENT_FIELDS and set(event) == EVENT_COMMON | EVENT_FIELDS[kind])
            _, _, events = _load_research(run)
            _require(bool(events))
            phases.append({"phase": phase, "status": "VERIFIED", "event_count": len(events),
                           "assurance": "UNKEYED_SYNTHETIC_RESEARCH_ONLY"})
        else:
            phases.append({"phase": phase, "status": "NOT_PRESENT", "event_count": 0})
        phase = "DOWNSTREAM"
        selected: str | None = None
        if (run / "digqda-run.json").exists():
            downstream = _downstream(run, transformed, release, release_sha)
            selected = downstream.pop("attempt_id")
            phases.append({"phase": phase, "status": "VERIFIED", **downstream})
        else:
            phases.append({"phase": phase, "status": "NOT_PRESENT", "finding_count": 0})
        phase = "ATTEMPT_HISTORY"
        history = _history(run, selected)
        incomplete = selected is None and history["attempts"] > 0
        phases.append({"phase": phase, "status": "BLOCKED" if incomplete else "VERIFIED", **history,
                       **({"code": "NO_VERIFIED_DOWNSTREAM_RESULT"} if incomplete else {})})
        phase = "SNAPSHOT"
        validate_release(run)
        if selected is not None:
            _runtime(run / "digqda-attempts" / selected, _read(run / "digqda-run.json")[0])
        _require(before == _snapshot(run))
        phases.append({"phase": phase, "status": "VERIFIED"})
        if not incomplete:
            report["status"] = "SYNTHETIC_VERIFIED"
    except Exception:
        # Exception text can contain source strings or protected paths. Never
        # disclose it through the source-free diagnostic surface.
        phases.append({"phase": phase, "status": "BLOCKED", "code": "INVALID_OR_CHANGED_BINDING"})
    return report
