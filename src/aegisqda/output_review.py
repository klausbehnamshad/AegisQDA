"""Signed, fixture-only review of exact blocked downstream output findings.

This resolves detector false positives, not methodological quality or an
external release. Identifying or uncertain model output must be rejected and
generated again; the review cannot retain an acknowledged identifier.
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any

from .config import load_config
from .detection import detector_versions
from .digqda_adapter import (
    PINNED_OPEN_HASHES, RUNTIME_CONTROL_ROOT, _output_findings, _released_surrogates,
    _runtime_control_material, _scan_views, _validate_digqda_contract,
)
from .errors import DownstreamBlocked, IntegrityError, ReviewRequired
from .manifests import canonical_bytes, seal, sha256_bytes, verify_seal
from .privacy_gate import validate_release
from .review_signature import sign_review, verify_synthetic_review
from .safeio import (
    atomic_json, read_stable_source, resolved_no_symlink, validate_opaque_id, validate_run_dir,
)
from .workflow import utc_now

REVIEW_FILE = "output-review.json"
ATTEMPT_ID = re.compile(r"[0-9a-f]{32}\Z")
OUTPUT_CONTRACT = {"contract_version": "0.1", "prompt_version": "1.2", **PINNED_OPEN_HASHES}


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object field")
        result[key] = value
    return result


def _read(path: Path) -> tuple[dict[str, Any], str]:
    content = read_stable_source(resolved_no_symlink(path))
    try:
        payload = json.loads(content, object_pairs_hook=_unique_object)
    except (ValueError, UnicodeError) as exc:
        raise IntegrityError("downstream review artifact is invalid JSON") from exc
    if not isinstance(payload, dict):
        raise IntegrityError("downstream review artifact root is invalid")
    return payload, sha256_bytes(content)


def _terminal_text(value: str) -> str:
    """Keep review context readable while making terminal controls visible."""
    escaped = json.dumps(value, ensure_ascii=False)
    return "".join(
        f"\\u{ord(character):04x}"
        if unicodedata.category(character) in {"Cc", "Cf", "Cs", "Zl", "Zp"}
        else character for character in escaped
    )


def _candidate(
    run_dir: Path, attempt_id: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Path], dict[str, object]]:
    """Revalidate source, contracts, controls and the entire current finding set."""
    if not ATTEMPT_ID.fullmatch(attempt_id):
        raise DownstreamBlocked("downstream attempt identifier is invalid")
    run_dir = validate_run_dir(run_dir)
    transformed, release = validate_release(run_dir)
    detection, _ = _read(run_dir / "detection.json")
    if detection.get("synthetic_only") is not True:
        raise DownstreamBlocked("downstream output review is synthetic-only")
    root = resolved_no_symlink(run_dir / "digqda-attempts" / attempt_id)
    attempt, attempt_sha = _read(root / "aegis-attempt.json")
    verify_seal(attempt)
    candidate = attempt.get("review_candidate")
    if (
        attempt.get("schema") != "aegisqda-digqda-attempt-v1"
        or attempt.get("state") != "BLOCKED"
        or attempt.get("failure_kind") != "POST_SCAN_FINDINGS"
        or attempt.get("attempt_id") != attempt_id
        or attempt.get("ollama_think") is not False
        or not isinstance(candidate, dict)
        or candidate.get("synthetic_only") is not True
        or candidate.get("language") != release.get("language")
    ):
        raise DownstreamBlocked("attempt has no reviewable synthetic post-scan candidate")
    _, release_sha = _read(run_dir / "privacy-release.json")
    if candidate.get("privacy_release_sha256") != release_sha:
        raise DownstreamBlocked("output candidate is bound to another privacy release")
    config = load_config()
    pair = (candidate.get("model"), candidate.get("model_digest"))
    if pair not in {(item.tag, item.digest) for item in config.models.dpo_approved_local_pairs}:
        raise DownstreamBlocked("output candidate model pair is not approved")
    for control_root in (RUNTIME_CONTROL_ROOT, root / "runtime-control"):
        files, control_sha = _runtime_control_material(control_root)
        if (
            control_sha != attempt.get("runtime_control_sha256")
            or sha256_bytes(files["sitecustomize.py"]) != attempt.get("runtime_shim_sha256")
        ):
            raise DownstreamBlocked("output candidate runtime controls changed; rerun required")
    records = candidate.get("artifacts")
    if not isinstance(records, dict) or set(records) != {"segments", "coding", "validation"}:
        raise DownstreamBlocked("output candidate artifact inventory is invalid")
    paths: dict[str, Path] = {}
    payloads: dict[str, dict[str, Any]] = {}
    for role, record in records.items():
        if not isinstance(record, dict) or set(record) != {"path", "sha256"}:
            raise DownstreamBlocked("output candidate artifact binding is invalid")
        relative = record["path"]
        if not isinstance(relative, str):
            raise DownstreamBlocked("output candidate artifact path is invalid")
        path = resolved_no_symlink(root / relative)
        if (
            Path(relative).is_absolute() or ".." in Path(relative).parts
            or not path.is_relative_to(root) or path.name != role + ".json"
        ):
            raise DownstreamBlocked("output candidate artifact escapes its protected attempt")
        payload, content_sha = _read(path)
        if content_sha != record["sha256"]:
            raise DownstreamBlocked("output candidate artifact changed")
        paths[role], payloads[role] = path, payload
    manifest = _validate_digqda_contract(
        payloads["coding"], payloads["validation"], str(pair[0]), str(pair[1]),
        str(release["transformed_sha256"]),
    )
    trusted = _released_surrogates(run_dir, transformed, release)
    findings = _output_findings(
        [paths[role] for role in ("segments", "coding", "validation")],
        str(release["language"]), prompt_sha256=str(manifest["prompt_sha256"]),
        trusted_surrogates=trusted, expected_coding=payloads["coding"],
        source_label=str(release["case_id"]) + transformed.suffix.lower(),
        artifact_root=root,
    )
    if (
        not findings or canonical_bytes(findings) != canonical_bytes(candidate.get("findings"))
        or attempt.get("finding_count") != len(findings)
    ):
        raise DownstreamBlocked("output candidate does not match the complete fresh post-scan")
    # A second read rejects changes during contract and detector evaluation.
    for role, path in paths.items():
        if sha256_bytes(read_stable_source(path)) != records[role]["sha256"]:
            raise DownstreamBlocked("output changed during review validation")
    current_transformed, current_release = validate_release(run_dir)
    if (
        current_transformed != transformed
        or canonical_bytes(current_release) != canonical_bytes(release)
        or _read(run_dir / "privacy-release.json")[1] != release_sha
        or _read(root / "aegis-attempt.json")[1] != attempt_sha
    ):
        raise DownstreamBlocked("source release or attempt changed during output review validation")
    binding: dict[str, object] = {
        "attempt_sha256": attempt_sha,
        "privacy_release_sha256": release_sha,
        "detectors": {language: detector_versions(language) for language in {str(release["language"]), "de"}},
        "contract": OUTPUT_CONTRACT,
    }
    if (
        canonical_bytes(candidate.get("contract")) != canonical_bytes(OUTPUT_CONTRACT)
        or canonical_bytes(candidate.get("detector_versions")) != canonical_bytes(binding["detectors"])
        or candidate.get("source_label") != str(release["case_id"]) + transformed.suffix.lower()
    ):
        raise DownstreamBlocked("output candidate detector or contract binding is obsolete")
    return attempt, candidate, release, paths, binding


def _decisions(decisions: object, findings: list[dict[str, Any]]) -> None:
    if not isinstance(decisions, list) or len(decisions) != len(findings):
        raise ReviewRequired("each downstream finding needs one explicit decision")
    expected = {finding["finding_id"] for finding in findings}
    received: set[str] = set()
    for decision in decisions:
        if not isinstance(decision, dict) or set(decision) != {"finding_id", "decision", "rationale"}:
            raise ReviewRequired("downstream review decision fields are invalid")
        finding_id, rationale = decision["finding_id"], decision["rationale"]
        if not isinstance(finding_id, str) or finding_id not in expected or finding_id in received:
            raise ReviewRequired("downstream review finding identifiers are not complete and unique")
        if decision["decision"] != "FALSE_POSITIVE":
            raise ReviewRequired("identifying or uncertain downstream output must remain blocked")
        if not isinstance(rationale, str) or not 8 <= len(rationale.strip()) <= 8000:
            raise ReviewRequired("downstream false-positive review requires a bounded rationale")
        received.add(finding_id)


def write_output_review(
    run_dir: Path, attempt_id: str, reviewer_id: str, decisions: list[dict[str, str]],
    *, signing_key: Path,
) -> Path:
    """Write a complete signed synthetic decision set without releasing output."""
    run_dir = validate_run_dir(run_dir)
    validate_opaque_id(reviewer_id, label="reviewer id")
    _, candidate, _, _, binding = _candidate(run_dir, attempt_id)
    _decisions(decisions, candidate["findings"])
    payload: dict[str, Any] = {
        "schema": "aegisqda-output-review-v1", "state": "ACCEPTED",
        "synthetic_only": True, "attempt_id": attempt_id, "reviewer_id": reviewer_id,
        "reviewed_at": utc_now(), "binding": binding, "decisions": decisions,
        "assurance": "SELF_SIGNED_LOCAL",
    }
    payload["signature"] = sign_review(payload, signing_key)
    verify_synthetic_review(payload, load_config().authorization.trusted_review_key_ids)
    path = run_dir / "digqda-attempts" / attempt_id / REVIEW_FILE
    atomic_json(path, seal(payload))
    return path


def interactive_output_review(
    run_dir: Path, attempt_id: str, reviewer_id: str, signing_key: Path,
) -> Path:
    _, candidate, release, paths, _ = _candidate(run_dir, attempt_id)
    transformed, _ = validate_release(run_dir)
    trusted = _released_surrogates(run_dir, transformed, release)
    print("PROTECTED SYNTHETIC OUTPUT REVIEW — no external or methodological release")
    decisions: list[dict[str, str]] = []
    for finding in candidate["findings"]:
        role = finding["path_name"].removesuffix(".json")
        payload, _ = _read(paths[role])
        value: Any = payload
        try:
            for part in finding["field_path"]:
                value = value[part]
            view = list(_scan_views(value, trusted))[finding["view_index"]]
            snippet = view[finding["start"]:finding["end"]]
            if sha256_bytes(snippet.encode()) != finding["value_sha256"]:
                raise ValueError("unbound finding")
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise IntegrityError("output finding display is not bound to the candidate") from exc
        context = view[max(0, finding["start"] - 120):finding["end"] + 120]
        field = json.dumps(finding["field_path"], ensure_ascii=False)[:1000]
        print(f"{finding['finding_id']} {finding['entity_type']} ({role})")
        print(f"Field: {_terminal_text(field)}")
        print(f"Finding: {_terminal_text(snippet)}")
        print(f"Bound context: {_terminal_text(context)}")
        if input("Detector false positive? Type FALSE_POSITIVE or ABORT: ").strip() != "FALSE_POSITIVE":
            raise ReviewRequired("output review aborted; attempt remains blocked")
        decisions.append({"finding_id": finding["finding_id"], "decision": "FALSE_POSITIVE", "rationale": input("Rationale: ")})
    return write_output_review(run_dir, attempt_id, reviewer_id, decisions, signing_key=signing_key)


def finalize_output_review(run_dir: Path, attempt_id: str) -> Path:
    """Accept exact reviewed false positives, retaining methodological review."""
    run_dir = validate_run_dir(run_dir)
    path = run_dir / "digqda-run.json"
    if path.exists():
        raise DownstreamBlocked("a completed DigQDA adapter manifest already exists")
    attempt, candidate, release, _, binding = _candidate(run_dir, attempt_id)
    review, review_sha = _read(run_dir / "digqda-attempts" / attempt_id / REVIEW_FILE)
    verify_seal(review)
    if (
        review.get("schema") != "aegisqda-output-review-v1" or review.get("state") != "ACCEPTED"
        or review.get("synthetic_only") is not True or review.get("attempt_id") != attempt_id
        or canonical_bytes(review.get("binding")) != canonical_bytes(binding)
        or not isinstance(review.get("reviewer_id"), str)
    ):
        raise DownstreamBlocked("output review binding is invalid or obsolete")
    validate_opaque_id(review["reviewer_id"], label="reviewer id")
    if not verify_synthetic_review(review, load_config().authorization.trusted_review_key_ids):
        raise DownstreamBlocked("downstream false-positive decisions require a signature")
    _decisions(review.get("decisions"), candidate["findings"])
    records = candidate["artifacts"]
    payload = {
        "schema": "aegisqda-digqda-run-v1", "state": "DOWNSTREAM_REVIEW_REQUIRED",
        "created_at": utc_now(), "attempt_id": attempt_id,
        "privacy_release_sha256": binding["privacy_release_sha256"],
        "model": candidate["model"], "model_digest": candidate["model_digest"],
        **{f"digqda_{role}_sha256": record["sha256"] for role, record in records.items()},
        "contract_version": "0.1", "prompt_version": "1.2", **PINNED_OPEN_HASHES,
        "validator_verdict": "PASS", "post_scan_findings": len(candidate["findings"]),
        "post_scan_false_positive_count": len(review["decisions"]), "post_scan_unresolved": 0,
        "output_review_sha256": review_sha, "output_review_assurance": review["assurance"],
        "post_scan_analytical_language": "de", "post_scan_source_language": release["language"],
        "ollama_think": False, "runtime_shim_sha256": attempt["runtime_shim_sha256"],
        "runtime_control_sha256": attempt["runtime_control_sha256"],
        "notice": "Protected synthetic output; signed detector review does not replace methodological human review or authorize external release",
    }
    atomic_json(path, seal(payload))
    return path
