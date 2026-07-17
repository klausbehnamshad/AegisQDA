"""Scan, review, transform, and privacy-release state transitions."""

from __future__ import annotations

import importlib.metadata
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from presidio_anonymizer import AnonymizerEngine
from presidio_anonymizer.entities import OperatorConfig, RecognizerResult

from .config import AppConfig, Policy, PolicyAction, ROOT, load_config, load_policy
from .detection import detector_versions, scan_document
from .errors import IntegrityError, ReviewRequired
from .formats.document import Document, fingerprint_text, parse_document, parse_document_bytes
from .languages import get_pack
from .local_boundary import reject_proxy_environment, validate_loopback_url, verify_upstream
from .manifests import seal, sha256_bytes, sha256_file, verify_seal
from .review_signature import sign_review, verify_review_signature
from .safeio import (
    atomic_json,
    atomic_write,
    fresh_run_dir,
    load_json,
    read_stable_source,
    validate_opaque_id,
    validate_run_dir,
    validate_source,
)

DETECTION_FILE = "detection.json"
LEDGER_FILE = "detection-ledger.json"
REVIEW_FILE = "review.json"
RELEASE_FILE = "privacy-release.json"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _policy_hash(config: AppConfig) -> str:
    return sha256_file((ROOT / config.privacy.policy).resolve())


def _config_hash() -> str:
    return sha256_file((ROOT / "config" / "aegisqda.local.yaml").resolve())


def _preflight(config: AppConfig) -> None:
    reject_proxy_environment()
    validate_loopback_url(config.execution.ollama_base_url)
    verify_upstream(config)


def scan_source(
    source_path: Path,
    *,
    language: str,
    case_id: str,
    run_root: Path,
    synthetic: bool,
) -> Path:
    """Create a protected run and stop in REVIEW_REQUIRED state."""
    config = load_config()
    policy = load_policy(config)
    _preflight(config)  # Deliberately before source validation/read.
    get_pack(language)
    validate_opaque_id(case_id, label="case id")
    source = validate_source(source_path, synthetic=synthetic)
    source_bytes = read_stable_source(source)
    document = parse_document_bytes(source_bytes, source.suffix)
    findings = scan_document(document, language, policy)
    run_dir = fresh_run_dir(run_root, case_id)
    source_name = "source" + source.suffix.lower()
    atomic_write(run_dir / source_name, source_bytes)
    ledger = seal(
        {
            "schema": "aegisqda-detection-ledger-v1",
            "created_at": utc_now(),
            "findings": [finding.public_dict() for finding in findings],
        }
    )
    atomic_json(run_dir / LEDGER_FILE, ledger)
    manifest = seal(
        {
            "schema": "aegisqda-detection-v1",
            "state": "REVIEW_REQUIRED",
            "created_at": utc_now(),
            "case_id": case_id,
            "language": language,
            "synthetic_only": synthetic,
            "source_file": source_name,
            "source_sha256": sha256_file(run_dir / source_name),
            "structure": document.fingerprint,
            "finding_count": len(findings),
            "ledger_sha256": sha256_file(run_dir / LEDGER_FILE),
            "policy_id": policy.policy_id,
            "policy_sha256": _policy_hash(config),
            "config_sha256": _config_hash(),
            "detector": detector_versions(language),
            "endpoint": config.execution.ollama_base_url,
            "upstream_sha256": verify_upstream(config),
        }
    )
    atomic_json(run_dir / DETECTION_FILE, manifest)
    return run_dir


def _load_detection(run_dir: Path) -> tuple[dict[str, Any], dict[str, Any], Document, AppConfig, Policy]:
    run_dir = validate_run_dir(run_dir)
    config = load_config()
    policy = load_policy(config)
    _preflight(config)
    detection = load_json(run_dir / DETECTION_FILE)
    ledger = load_json(run_dir / LEDGER_FILE)
    verify_seal(detection)
    verify_seal(ledger)
    if detection.get("state") != "REVIEW_REQUIRED":
        raise IntegrityError("detection artifact is not in REVIEW_REQUIRED state")
    if detection.get("ledger_sha256") != sha256_file(run_dir / LEDGER_FILE):
        raise IntegrityError("detection ledger binding failed")
    if detection.get("policy_sha256") != _policy_hash(config):
        raise IntegrityError("policy changed after detection")
    if detection.get("config_sha256") != _config_hash():
        raise IntegrityError("configuration changed after detection")
    source_file = detection.get("source_file")
    if not isinstance(source_file, str) or source_file not in {"source.srt", "source.txt"}:
        raise IntegrityError("detection source reference is invalid")
    source = run_dir / source_file
    if detection.get("source_sha256") != sha256_file(source):
        raise IntegrityError("protected source changed after detection")
    document = parse_document(source)
    if document.fingerprint != detection.get("structure"):
        raise IntegrityError("protected source structure changed after detection")
    return detection, ledger, document, config, policy


def _context(text: str, start: int, end: int, radius: int = 45) -> str:
    return text[max(0, start - radius):min(len(text), end + radius)].replace("\r", " ").replace("\n", " ↵ ")


def interactive_review(run_dir: Path, reviewer_id: str, signing_key: Path | None = None) -> Path:
    """Deliberately reveal local protected context and collect complete decisions."""
    validate_opaque_id(reviewer_id, label="reviewer id")
    detection, ledger, document, config, policy = _load_detection(run_dir)
    decisions: list[dict[str, str]] = []
    findings = ledger.get("findings")
    if not isinstance(findings, list):
        raise IntegrityError("detection ledger findings are invalid")
    print("PROTECTED LOCAL REVIEW — context below may contain identifying text")
    for finding in findings:
        if not isinstance(finding, dict):
            raise IntegrityError("detection ledger finding is invalid")
        finding_id = finding.get("finding_id")
        start, end = finding.get("start"), finding.get("end")
        entity = finding.get("entity_type")
        if not isinstance(finding_id, str) or not isinstance(start, int) or not isinstance(end, int):
            raise IntegrityError("detection ledger offsets are invalid")
        print(f"\n{finding_id} {entity} [{start}:{end}]\n{_context(document.text, start, end)}")
        action = str(finding.get("action"))
        allowed_answers = {"f", "a"}
        prompt = "false positive [f], abort [a]: "
        if action == PolicyAction.REPLACE_AND_REVIEW.value:
            allowed_answers.add("c")
            prompt = "confirm replacement [c], false positive [f], abort [a]: "
        elif action == PolicyAction.GENERALIZE_AND_REVIEW.value:
            allowed_answers.add("g")
            prompt = "confirm generalization [g], false positive [f], abort [a]: "
        while True:
            answer = input(prompt).strip().casefold()
            if answer in allowed_answers:
                break
        if answer == "a":
            raise ReviewRequired("review aborted; no review artifact was written")
        if answer == "f":
            rationale = input("false-positive rationale (required): ").strip()
            if len(rationale) < 8:
                raise ReviewRequired("false-positive rationale is too short; review was not written")
            decisions.append(
                {"finding_id": finding_id, "decision": "FALSE_POSITIVE", "rationale": rationale}
            )
        else:
            decision = "CONFIRMED" if answer == "c" else "GENERALIZE_CONFIRMED"
            decisions.append({"finding_id": finding_id, "decision": decision})
    additions: list[dict[str, object]] = []
    while input("add a missed detection? [y/N]: ").strip().casefold() == "y":
        try:
            start = int(input("start offset: "))
            end = int(input("end offset: "))
        except ValueError as exc:
            raise ReviewRequired("invalid added-detection offset; review was not written") from exc
        entity_type = input("entity type (for example PERSON): ").strip().upper()
        if not (0 <= start < end <= len(document.text)) or "\n" in document.text[start:end]:
            raise ReviewRequired("added detection must be a valid single-line source span")
        action = policy.action_for(entity_type)
        if action is PolicyAction.REPLACE_AND_REVIEW:
            resolution = "CONFIRMED"
        elif action is PolicyAction.GENERALIZE_AND_REVIEW:
            resolution = "GENERALIZE_CONFIRMED"
        else:
            raise ReviewRequired("added detection is blocking under the current policy")
        additions.append(
            {
                "finding_id": f"A-{len(additions) + 1:04d}",
                "entity_type": entity_type,
                "start": start,
                "end": end,
                "value_sha256": sha256_bytes(document.text[start:end].encode()),
                "action": action.value,
                "decision": resolution,
            }
        )
    return write_review(run_dir, reviewer_id, decisions, additions, signing_key=signing_key)


def write_review(
    run_dir: Path,
    reviewer_id: str,
    decisions: list[dict[str, str]],
    additions: list[dict[str, object]] | None = None,
    *,
    signing_key: Path | None = None,
) -> Path:
    """Write one complete review artifact; intended for CLI and model-free tests."""
    validate_opaque_id(reviewer_id, label="reviewer id")
    run_dir = validate_run_dir(run_dir)
    detection, ledger, document, config, policy = _load_detection(run_dir)
    findings = ledger.get("findings")
    if not isinstance(findings, list):
        raise IntegrityError("detection ledger findings are invalid")
    expected = {item.get("finding_id") for item in findings if isinstance(item, dict)}
    received = {item.get("finding_id") for item in decisions}
    if received != expected or len(decisions) != len(expected):
        raise ReviewRequired("every finding requires exactly one review decision")
    finding_by_id = {item["finding_id"]: item for item in findings if isinstance(item, dict)}
    for decision in decisions:
        finding = finding_by_id.get(decision.get("finding_id"))
        if finding is None:
            raise ReviewRequired("review refers to an unknown finding")
        try:
            action = PolicyAction(str(finding.get("action")))
        except ValueError as exc:
            raise ReviewRequired("finding contains an unknown policy action") from exc
        resolution = decision.get("decision")
        if resolution == "FALSE_POSITIVE":
            if len(decision.get("rationale", "").strip()) < 8:
                raise ReviewRequired("false-positive decisions require a rationale")
        elif resolution == "CONFIRMED" and action is PolicyAction.REPLACE_AND_REVIEW:
            pass
        elif resolution == "GENERALIZE_CONFIRMED" and action is PolicyAction.GENERALIZE_AND_REVIEW:
            pass
        else:
            raise ReviewRequired("review decision is not permitted by the policy action")
    additions = additions or []
    for addition in additions:
        start, end = addition.get("start"), addition.get("end")
        entity = addition.get("entity_type")
        if not isinstance(start, int) or not isinstance(end, int) or not isinstance(entity, str):
            raise ReviewRequired("added detection has invalid fields")
        if not (0 <= start < end <= len(document.text)) or "\n" in document.text[start:end]:
            raise ReviewRequired("added detection has invalid bounds")
        if addition.get("value_sha256") != sha256_bytes(document.text[start:end].encode()):
            raise ReviewRequired("added detection hash does not match the source")
        action = policy.action_for(entity)
        expected_resolution = (
            "CONFIRMED"
            if action is PolicyAction.REPLACE_AND_REVIEW
            else "GENERALIZE_CONFIRMED"
            if action is PolicyAction.GENERALIZE_AND_REVIEW
            else None
        )
        if addition.get("action") != action.value or addition.get("decision") != expected_resolution:
            raise ReviewRequired("added detection is not resolvable under the policy")
    review_payload: dict[str, Any] = {
        "schema": "aegisqda-review-v1",
        "state": "ACCEPTED",
        "reviewer_id": reviewer_id,
        "reviewed_at": utc_now(),
        "detection_sha256": sha256_file(run_dir / DETECTION_FILE),
        "ledger_sha256": sha256_file(run_dir / LEDGER_FILE),
        "policy_sha256": _policy_hash(config),
        "decisions": decisions,
        "additions": additions,
        "assurance": "SELF_SIGNED_LOCAL" if signing_key else "UNKEYED_SYNTHETIC_ONLY",
    }
    if signing_key:
        review_payload["signature"] = sign_review(review_payload, signing_key)
    review = seal(review_payload)
    atomic_json(run_dir / REVIEW_FILE, review)
    return run_dir / REVIEW_FILE


def _presidio_replace(value: str, entity_type: str, replacement: str) -> str:
    result = AnonymizerEngine().anonymize(
        text=value,
        analyzer_results=[RecognizerResult(entity_type=entity_type, start=0, end=len(value), score=1.0)],
        operators={entity_type: OperatorConfig("replace", {"new_value": replacement})},
    )
    return result.text


def _resolved_findings(
    ledger: dict[str, Any], review: dict[str, Any], document: Document
) -> tuple[list[dict[str, Any]], set[tuple[str, str]]]:
    findings = ledger.get("findings")
    decisions = review.get("decisions")
    if not isinstance(findings, list) or not isinstance(decisions, list):
        raise IntegrityError("review binding is invalid")
    by_id = {item.get("finding_id"): item for item in findings if isinstance(item, dict)}
    confirmed: list[dict[str, Any]] = []
    false_exemptions: set[tuple[str, str]] = set()
    for decision in decisions:
        if not isinstance(decision, dict) or decision.get("finding_id") not in by_id:
            raise IntegrityError("review refers to an unknown finding")
        finding = by_id[decision["finding_id"]]
        if decision.get("decision") in {"CONFIRMED", "GENERALIZE_CONFIRMED"}:
            resolved = dict(finding)
            resolved["resolution"] = decision.get("decision")
            confirmed.append(resolved)
        elif decision.get("decision") == "FALSE_POSITIVE":
            false_exemptions.add(
                (str(finding.get("entity_type")), str(finding.get("value_sha256")))
            )
        else:
            raise ReviewRequired("review contains an unresolved finding")
    for addition in review.get("additions", []):
        if isinstance(addition, dict):
            resolved = dict(addition)
            resolved["resolution"] = addition.get("decision")
            confirmed.append(resolved)
    for finding in confirmed:
        start, end = finding.get("start"), finding.get("end")
        if not isinstance(start, int) or not isinstance(end, int):
            raise IntegrityError("reviewed finding offsets are invalid")
        value = document.text[start:end]
        if finding.get("value_sha256") != sha256_bytes(value.encode()):
            raise IntegrityError("reviewed finding no longer matches the source")
    return confirmed, false_exemptions


def transform_run(run_dir: Path) -> Path:
    run_dir = validate_run_dir(run_dir)
    detection, ledger, document, config, policy = _load_detection(run_dir)
    if not (run_dir / REVIEW_FILE).is_file():
        raise ReviewRequired("accepted human review is required")
    review = load_json(run_dir / REVIEW_FILE)
    verify_seal(review)
    signed_review = verify_review_signature(review)
    if not signed_review and detection.get("synthetic_only") is not True:
        raise ReviewRequired("real-data review requires a trusted local signature")
    if review.get("state") != "ACCEPTED":
        raise ReviewRequired("accepted human review is required")
    if review.get("detection_sha256") != sha256_file(run_dir / DETECTION_FILE):
        raise IntegrityError("review is stale or bound to another detection")
    if review.get("ledger_sha256") != sha256_file(run_dir / LEDGER_FILE):
        raise IntegrityError("review ledger binding failed")
    if review.get("policy_sha256") != _policy_hash(config):
        raise IntegrityError("policy changed after review")
    confirmed, false_exemptions = _resolved_findings(ledger, review, document)
    confirmed.sort(key=lambda item: (int(item["start"]), -int(item["end"])))
    for left, right in zip(confirmed, confirmed[1:]):
        if int(right["start"]) < int(left["end"]):
            raise ReviewRequired("overlapping reviewed findings require manual resolution")
    counters: defaultdict[str, int] = defaultdict(int)
    mapping: dict[tuple[str, str], str] = {}
    replacements: list[tuple[int, int, str]] = []
    for finding in confirmed:
        entity = str(finding["entity_type"]).upper()
        action = policy.action_for(entity)
        resolution = finding.get("resolution")
        if action is PolicyAction.REPLACE_AND_REVIEW and resolution == "CONFIRMED":
            surrogate_entity = entity
        elif action is PolicyAction.GENERALIZE_AND_REVIEW and resolution == "GENERALIZE_CONFIRMED":
            surrogate_entity = f"{entity}_GENERALIZED"
        else:
            raise ReviewRequired("policy action has no release-authorized transform")
        start, end = int(finding["start"]), int(finding["end"])
        value = document.text[start:end]
        key = (surrogate_entity, value)
        if key not in mapping:
            counters[surrogate_entity] += 1
            mapping[key] = f"[{surrogate_entity}_{counters[surrogate_entity]:03d}]"
        replacements.append((start, end, mapping[key]))
    transformed = document.text
    for start, end, replacement in reversed(replacements):
        transformed = transformed[:start] + _presidio_replace(transformed[start:end], "AEGIS_VALUE", replacement) + transformed[end:]
    mapping.clear()
    if fingerprint_text(transformed, document.kind) != document.fingerprint:
        raise IntegrityError("transform caused structural drift")
    transformed_name = "transformed." + document.kind
    atomic_write(run_dir / transformed_name, transformed.encode())
    transformed_doc = parse_document(run_dir / transformed_name)
    second_findings = scan_document(transformed_doc, str(detection["language"]), policy)
    unresolved = [
        finding
        for finding in second_findings
        if (finding.entity_type, finding.value_sha256) not in false_exemptions
    ]
    second_pass = seal(
        {
            "schema": "aegisqda-second-pass-v1",
            "created_at": utc_now(),
            "finding_count": len(second_findings),
            "unresolved_count": len(unresolved),
            "findings": [finding.public_dict() for finding in second_findings],
        }
    )
    atomic_json(run_dir / "second-pass.json", second_pass)
    if unresolved:
        raise ReviewRequired("second-pass scan found unresolved identifiers; privacy release blocked")
    release = seal(
        {
            "schema": "aegisqda-privacy-release-v1",
            "state": "PRIVACY_RELEASED",
            "released_at": utc_now(),
            "case_id": detection["case_id"],
            "language": detection["language"],
            "policy_id": detection["policy_id"],
            "policy_sha256": detection["policy_sha256"],
            "config_sha256": detection["config_sha256"],
            "ledger_sha256": detection["ledger_sha256"],
            "reviewer_id": review["reviewer_id"],
            "review_assurance": review["assurance"],
            "review_key_id_sha256": (
                review.get("signature", {}).get("key_id_sha256")
                if isinstance(review.get("signature"), dict)
                else None
            ),
            "review_sha256": sha256_file(run_dir / REVIEW_FILE),
            "detection_sha256": sha256_file(run_dir / DETECTION_FILE),
            "source_sha256": detection["source_sha256"],
            "transformed_file": transformed_name,
            "transformed_sha256": sha256_file(run_dir / transformed_name),
            "second_pass_sha256": sha256_file(run_dir / "second-pass.json"),
            "structure": document.fingerprint,
            "endpoint": config.execution.ollama_base_url,
            "upstream_sha256": detection["upstream_sha256"],
            "release_claim": f"PRIVACY_RELEASED under policy {policy.policy_id} after automatic checks and human sign-off",
            "residual_risk": "Fixture-scoped process release; free-text anonymity is not guaranteed",
            "presidio_anonymizer": importlib.metadata.version("presidio-anonymizer"),
        }
    )
    atomic_json(run_dir / RELEASE_FILE, release)
    return run_dir / RELEASE_FILE
