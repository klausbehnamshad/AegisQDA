"""Read-only, non-identifying inspection of current and legacy privacy runs."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .config import DEFAULT_CONFIG, ROOT, load_config, load_policy
from .detection import (
    CURRENT_RECOGNIZER_PACK, canonical_person_value, detector_versions, scan_document,
)
from .errors import IntegrityError
from .formats.document import parse_document_bytes
from .languages import get_pack
from .manifests import sha256_bytes, sha256_file, verify_seal
from .privacy_gate import validate_release
from .safeio import load_json, read_stable_source, resolved_no_symlink, validate_run_dir
from .synthetic_registry import validate_source_registration
from .workflow import (
    DETECTION_FILE, LEDGER_FILE, RELEASE_FILE, REVIEW_FILE, _finding_segments, _resolved_findings,
)

LEGACY_PACKS = {"aegis-custom-strict-v1", "aegis-custom-strict-v2"}
SURROGATE_RE = re.compile(r"\[(?:[A-Z][A-Z0-9_]*_\d{3,}|…)\]")


def _artifact(run_dir: Path, filename: str) -> dict[str, Any]:
    payload = load_json(run_dir / filename)
    verify_seal(payload)
    return payload


def _report(status: str, version: str, reasons: set[str], *, findings: int = 0) -> dict[str, object]:
    return {
        "schema": "aegisqda-run-audit-v1",
        "status": status,
        "detector_version": version,
        "risk_codes": sorted(reasons),
        "new_risk_count": findings,
        "read_only": True,
        "release_authorization": False,
        "notice": "CURRENT means current detection provenance and a revalidated release bundle "
        "when one exists; open runs still require human review. Diagnostic inspection only; "
        "no privacy release or universal anonymity assurance. Legacy runs require a fresh scan "
        "and human review before downstream use.",
    }


def _legacy_inferred_ranges(
    document_text: str, transformed_text: str, confirmed: list[dict[str, Any]],
) -> list[tuple[int, int]]:
    """Replay the v1 transform to recover ranges bound to original reviewed spans.

    Syntax alone never grants an exemption: a literal source placeholder or a
    bracketed name cannot become trusted output merely by looking like a token.
    """
    mapping: dict[tuple[str, str], str] = {}
    counters: dict[str, int] = {}
    replacements: list[tuple[int, int, str]] = []
    previous_end = -1
    for finding in sorted(confirmed, key=lambda item: (item["start"], item["end"])):
        start, end = finding["start"], finding["end"]
        entity = finding.get("entity_type")
        if not isinstance(entity, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]*", entity):
            raise IntegrityError("audit legacy transform entity is invalid")
        if start < previous_end or "\n" in document_text[start:end]:
            raise IntegrityError("audit legacy transform cannot be reconstructed safely")
        previous_end = end
        if finding.get("resolution") == "CONFIRMED" and finding.get("action") == "REPLACE_AND_REVIEW":
            surrogate_entity = entity
        elif finding.get("resolution") == "GENERALIZE_CONFIRMED" and finding.get("action") == "GENERALIZE_AND_REVIEW":
            surrogate_entity = f"{entity}_GENERALIZED"
        else:
            raise IntegrityError("audit legacy transform policy binding is invalid")
        key = (surrogate_entity, document_text[start:end])
        if key not in mapping:
            counters[surrogate_entity] = counters.get(surrogate_entity, 0) + 1
            mapping[key] = f"[{surrogate_entity}_{counters[surrogate_entity]:03d}]"
        replacements.append((start, end, mapping[key]))
    expected = document_text
    for start, end, replacement in reversed(replacements):
        expected = expected[:start] + replacement + expected[end:]
    if expected != transformed_text:
        raise IntegrityError("audit legacy transform does not match reviewed source reconstruction")
    ranges: list[tuple[int, int]] = []
    delta = 0
    for start, end, replacement in replacements:
        ranges.append((start + delta, start + delta + len(replacement)))
        delta += len(replacement) - (end - start)
    return ranges


def audit_run(run_dir: Path) -> dict[str, object]:
    """Classify a run without writes, source excerpts, case IDs, or path disclosure."""
    run_dir = validate_run_dir(run_dir)
    detection = _artifact(run_dir, DETECTION_FILE)
    ledger = _artifact(run_dir, LEDGER_FILE)
    detector = detection.get("detector")
    version = detector.get("recognizer_pack") if isinstance(detector, dict) else None
    if not isinstance(version, str) or version not in LEGACY_PACKS | {CURRENT_RECOGNIZER_PACK}:
        raise IntegrityError("audit cannot classify an unknown detector artifact")
    if detection.get("state") != "REVIEW_REQUIRED":
        raise IntegrityError("audit detection state is invalid")
    if detection.get("ledger_sha256") != sha256_file(run_dir / LEDGER_FILE):
        raise IntegrityError("audit ledger binding failed")
    source_file = detection.get("source_file")
    if source_file not in {"source.srt", "source.txt"}:
        raise IntegrityError("audit protected-source reference is invalid")
    source = resolved_no_symlink(run_dir / str(source_file))
    raw = read_stable_source(source)
    if detection.get("source_sha256") != sha256_bytes(raw):
        raise IntegrityError("audit protected-source binding failed")
    document = parse_document_bytes(raw, source.suffix)
    if detection.get("structure") != document.fingerprint:
        raise IntegrityError("audit protected-source structure binding failed")
    findings = ledger.get("findings")
    if not isinstance(findings, list) or detection.get("finding_count") != len(findings):
        raise IntegrityError("audit finding count is invalid")
    identifiers: set[str] = set()
    for finding in findings:
        if not isinstance(finding, dict) or not isinstance(finding.get("finding_id"), str):
            raise IntegrityError("audit finding identifiers are invalid")
        if finding["finding_id"] in identifiers:
            raise IntegrityError("audit finding identifiers are duplicated")
        identifiers.add(finding["finding_id"])
        _finding_segments(finding, document)
    language = detection.get("language")
    if not isinstance(language, str):
        raise IntegrityError("audit language binding is invalid")
    get_pack(language)
    if version == CURRENT_RECOGNIZER_PACK:
        reasons: set[str] = set()
        if detector != detector_versions(language):
            reasons.add("DETECTOR_ENVIRONMENT_CHANGED")
        config = load_config()
        if detection.get("config_sha256") != sha256_file(DEFAULT_CONFIG):
            reasons.add("CONFIGURATION_CHANGED")
        if detection.get("policy_sha256") != sha256_file((ROOT / config.privacy.policy).resolve()):
            reasons.add("POLICY_CHANGED")
        if detection.get("synthetic_only") is not True:
            reasons.add("SYNTHETIC_AUTHORIZATION_MISSING")
        try:
            validate_source_registration(
                detection.get("source_registration"), str(detection.get("source_sha256")), language,
            )
        except IntegrityError:
            reasons.add("SOURCE_REGISTRATION_CHANGED")
        if reasons:
            return _report("RESCAN_REQUIRED", version, reasons)
        if (run_dir / RELEASE_FILE).exists():
            try:
                validate_release(run_dir)
            except Exception as exc:
                raise IntegrityError("audit current-release bundle failed provenance revalidation") from exc
        return _report("CURRENT", version, set())
    release_path = run_dir / RELEASE_FILE
    if not release_path.exists():
        return _report("RESCAN_REQUIRED", version, {"LEGACY_DETECTOR"})

    release = _artifact(run_dir, RELEASE_FILE)
    review = _artifact(run_dir, REVIEW_FILE)
    second_pass = _artifact(run_dir, "second-pass.json")
    bindings = (
        release.get("state") == "PRIVACY_RELEASED",
        review.get("state") == "ACCEPTED",
        release.get("detection_sha256") == sha256_file(run_dir / DETECTION_FILE),
        review.get("detection_sha256") == sha256_file(run_dir / DETECTION_FILE),
        release.get("ledger_sha256") == sha256_file(run_dir / LEDGER_FILE),
        review.get("ledger_sha256") == sha256_file(run_dir / LEDGER_FILE),
        release.get("review_sha256") == sha256_file(run_dir / REVIEW_FILE),
        release.get("second_pass_sha256") == sha256_file(run_dir / "second-pass.json"),
        release.get("source_sha256") == detection.get("source_sha256"),
        release.get("structure") == document.fingerprint,
        second_pass.get("unresolved_count") == 0,
    )
    if not all(bindings):
        raise IntegrityError("audit legacy-release provenance binding failed")
    transformed_file = release.get("transformed_file")
    if transformed_file not in {"transformed.srt", "transformed.txt"}:
        raise IntegrityError("audit transformed-source reference is invalid")
    transformed = resolved_no_symlink(run_dir / str(transformed_file))
    transformed_raw = read_stable_source(transformed)
    if release.get("transformed_sha256") != sha256_bytes(transformed_raw):
        raise IntegrityError("audit transformed-source binding failed")
    transformed_document = parse_document_bytes(transformed_raw, transformed.suffix)
    if transformed_document.fingerprint != document.fingerprint:
        raise IntegrityError("audit transformed-source structure binding failed")

    confirmed, false_exemptions = _resolved_findings(ledger, review, document)
    by_id = {item["finding_id"]: item for item in findings if isinstance(item, dict)}
    reviewed_persons = [item for item in confirmed if item.get("entity_type") == "PERSON"]
    reviewed_persons.extend(
        by_id[decision["finding_id"]]
        for decision in review["decisions"]
        if decision.get("decision") == "FALSE_POSITIVE"
        and by_id[decision["finding_id"]].get("entity_type") == "PERSON"
    )
    policy = load_policy(load_config())
    current_source_findings = scan_document(document, language, policy)
    unreviewed_mentions = [
        finding
        for finding in current_source_findings
        if finding.entity_type == "PERSON"
        and not any(
            finding.start <= item["start"] < item["end"] <= finding.end
            and canonical_person_value(document.text[finding.start:finding.end])
            == canonical_person_value(document.text[item["start"]:item["end"]])
            for item in reviewed_persons
        )
    ]
    ranges = second_pass.get("surrogate_ranges")
    validated_ranges: list[tuple[int, int]] = []
    if ranges is None and version == "aegis-custom-strict-v1":
        validated_ranges = _legacy_inferred_ranges(document.text, transformed_document.text, confirmed)
        ranges = []
    if not isinstance(ranges, list):
        raise IntegrityError("audit surrogate provenance is invalid")
    for bounds in ranges:
        if (
            not isinstance(bounds, list) or len(bounds) != 2
            or type(bounds[0]) is not int or type(bounds[1]) is not int
            or not 0 <= bounds[0] < bounds[1] <= len(transformed_document.text)
            or not SURROGATE_RE.fullmatch(transformed_document.text[bounds[0]:bounds[1]])
        ):
            raise IntegrityError("audit surrogate provenance is invalid")
        validated_ranges.append((bounds[0], bounds[1]))
    residuals = [
        finding
        for finding in scan_document(transformed_document, language, policy)
        if (finding.entity_type, finding.value_sha256) not in false_exemptions
        and not any(start <= finding.start and finding.end <= end for start, end in validated_ranges)
    ]
    reasons = {"LEGACY_DETECTOR"}
    if unreviewed_mentions:
        reasons.add("PERSON_MENTION_NOT_REVIEWED_AS_UNIT")
    if residuals:
        reasons.add("RESIDUAL_IDENTIFIERS")
    affected = bool(unreviewed_mentions or residuals)
    return _report(
        "AFFECTED" if affected else "LEGACY_NO_NEW_FINDINGS", version, reasons,
        findings=len(unreviewed_mentions) + len(residuals),
    )
