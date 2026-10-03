"""Revalidation of a privacy release immediately before downstream use."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from .config import DEFAULT_CONFIG, ROOT, load_config, load_policy
from .detection import detector_versions, require_current_detector, scan_document
from .errors import DownstreamBlocked
from .formats.document import parse_document
from .generalization import generalize, is_generalized_output
from .local_boundary import reject_proxy_environment, validate_loopback_url, verify_upstream
from .manifests import canonical_bytes, sha256_bytes, sha256_file, verify_seal
from .safeio import load_json, validate_run_dir
from .review_signature import verify_synthetic_review
from .synthetic_registry import validate_source_registration
from .workflow import DETECTION_FILE, LEDGER_FILE, RELEASE_FILE, REVIEW_FILE, render_reviewed_source


def _second_pass_is_consistent(second_pass: dict[str, Any]) -> bool:
    findings = second_pass.get("findings")
    ranges = second_pass.get("surrogate_ranges")
    exempt_ids = second_pass.get("surrogate_exempt_finding_ids")
    generalizations = second_pass.get("generalizations", [])
    false_bindings = second_pass.get("false_positive_bindings", [])
    general_ids = second_pass.get("generalization_exempt_finding_ids", [])
    false_ids = second_pass.get("false_positive_exempt_finding_ids", [])
    if not isinstance(generalizations, list) or not isinstance(false_bindings, list):
        return False
    for ids, key in (
        (general_ids, "generalization_exempt_count"), (false_ids, "false_positive_exempt_count"),
    ):
        if (
            not isinstance(ids, list) or not all(isinstance(item, str) for item in ids)
            or len(set(ids)) != len(ids) or second_pass.get(key, 0) != len(ids)
        ):
            return False
    for item in generalizations + false_bindings:
        if (
            not isinstance(item, dict) or not isinstance(item.get("finding_id"), str)
            or not isinstance(item.get("entity_type"), str)
            or type(item.get("start")) is not int or type(item.get("end")) is not int
            or not 0 <= item["start"] < item["end"]
        ):
            return False
    for item in generalizations:
        if not all(isinstance(item.get(key), str) for key in ("text", "rule_id")):
            return False
        if not is_generalized_output(item["entity_type"], item["text"], item["rule_id"]):
            return False
    if not isinstance(findings, list) or not isinstance(ranges, list):
        return False
    if not isinstance(exempt_ids, list) or not all(isinstance(item, str) for item in exempt_ids):
        return False
    if second_pass.get("finding_count") != len(findings):
        return False
    if second_pass.get("surrogate_exempt_count") != len(exempt_ids):
        return False
    if len(set(exempt_ids)) != len(exempt_ids):
        return False
    validated_ranges: list[tuple[int, int]] = []
    for bounds in ranges:
        if (
            not isinstance(bounds, list)
            or len(bounds) != 2
            or type(bounds[0]) is not int
            or type(bounds[1]) is not int
            or not 0 <= bounds[0] < bounds[1]
        ):
            return False
        validated_ranges.append((bounds[0], bounds[1]))
    finding_ids: set[str] = set()
    for finding in findings:
        if not isinstance(finding, dict):
            return False
        finding_id = finding.get("finding_id")
        start, end = finding.get("start"), finding.get("end")
        if not isinstance(finding_id, str) or type(start) is not int or type(end) is not int or not 0 <= start < end:
            return False
        if finding_id in finding_ids:
            return False
        finding_ids.add(finding_id)
        if finding_id in exempt_ids and not any(
            range_start <= start and end <= range_end
            for range_start, range_end in validated_ranges
        ):
            return False
        if finding_id in general_ids and not any(
            (item["entity_type"] == finding.get("entity_type") or finding.get("entity_type") in {"PERSON", "LOCATION", "ORGANIZATION"})
            and item["start"] <= start < end <= item["end"] for item in generalizations
        ):
            return False
        if finding_id in false_ids and not any(
            item["entity_type"] == finding.get("entity_type")
            and item.get("value_sha256") == finding.get("value_sha256")
            and item["start"] == start and item["end"] == end for item in false_bindings
        ):
            return False
    all_exemptions = set(exempt_ids) | set(general_ids) | set(false_ids)
    return (
        all_exemptions <= finding_ids
        and second_pass.get("unresolved_count", len(finding_ids - all_exemptions)) == len(finding_ids - all_exemptions)
    )


def validate_release(run_dir: Path) -> tuple[Path, dict[str, Any]]:
    run_dir = validate_run_dir(run_dir)
    config = load_config()
    policy = load_policy(config)
    reject_proxy_environment()
    validate_loopback_url(config.execution.ollama_base_url)
    upstream_hash = verify_upstream(config)
    try:
        release = load_json(run_dir / RELEASE_FILE)
        review = load_json(run_dir / REVIEW_FILE)
        detection = load_json(run_dir / DETECTION_FILE)
        ledger = load_json(run_dir / LEDGER_FILE)
        second_pass = load_json(run_dir / "second-pass.json")
        verify_seal(release)
        verify_seal(review)
        verify_seal(detection)
        verify_seal(ledger)
        verify_seal(second_pass)
    except Exception as exc:
        raise DownstreamBlocked("valid privacy release artifacts are required") from exc
    # A legacy release must not bypass a detector upgrade or the fixture-only
    # runtime boundary simply because its unkeyed seals are still consistent.
    if detection.get("synthetic_only") is not True:
        raise DownstreamBlocked("real-data authorization is not implemented; downstream remains blocked")
    try:
        require_current_detector(detection)
        language = detection.get("language")
        if not isinstance(language, str) or detection.get("detector") != detector_versions(language):
            raise DownstreamBlocked("detector changed; a fresh scan and human review are required")
        verify_synthetic_review(review, config.authorization.trusted_review_key_ids)
        validate_source_registration(
            detection.get("source_registration"), str(detection.get("source_sha256")), language,
        )
    except Exception as exc:
        raise DownstreamBlocked("current detector and authorized synthetic review are required") from exc
    second_pass_consistent = _second_pass_is_consistent(second_pass)
    checks = (
        release.get("schema") == "aegisqda-privacy-release-v1",
        review.get("schema") == "aegisqda-review-v1",
        detection.get("schema") == "aegisqda-detection-v1",
        ledger.get("schema") == "aegisqda-detection-ledger-v1",
        release.get("state") == "PRIVACY_RELEASED",
        release.get("case_id") == detection.get("case_id"),
        release.get("language") == detection.get("language"),
        release.get("policy_id") == detection.get("policy_id"),
        release.get("review_sha256") == sha256_file(run_dir / REVIEW_FILE),
        release.get("detection_sha256") == sha256_file(run_dir / DETECTION_FILE),
        release.get("ledger_sha256") == sha256_file(run_dir / LEDGER_FILE),
        release.get("second_pass_sha256") == sha256_file(run_dir / "second-pass.json"),
        release.get("policy_sha256") == sha256_file((ROOT / config.privacy.policy).resolve()),
        release.get("config_sha256") == sha256_file(DEFAULT_CONFIG),
        release.get("policy_id") == policy.policy_id,
        release.get("reviewer_id") == review.get("reviewer_id"),
        release.get("review_assurance") == review.get("assurance"),
        release.get("review_key_id_sha256")
        == (
            review.get("signature", {}).get("key_id_sha256")
            if isinstance(review.get("signature"), dict)
            else None
        ),
        release.get("endpoint") == config.execution.ollama_base_url,
        release.get("upstream_sha256") == upstream_hash,
        detection.get("state") == "REVIEW_REQUIRED",
        detection.get("ledger_sha256") == sha256_file(run_dir / LEDGER_FILE),
        detection.get("policy_sha256") == release.get("policy_sha256"),
        detection.get("config_sha256") == release.get("config_sha256"),
        review.get("state") == "ACCEPTED",
        review.get("detection_sha256") == sha256_file(run_dir / DETECTION_FILE),
        review.get("ledger_sha256") == sha256_file(run_dir / LEDGER_FILE),
        review.get("policy_sha256") == release.get("policy_sha256"),
        second_pass.get("schema") == "aegisqda-second-pass-v1",
        second_pass_consistent,
        second_pass.get("unresolved_count") == 0,
        release.get("source_sha256") == detection.get("source_sha256"),
    )
    if not all(checks):
        raise DownstreamBlocked("privacy release provenance revalidation failed")
    transformed_file = release.get("transformed_file")
    if transformed_file not in {"transformed.srt", "transformed.txt"}:
        raise DownstreamBlocked("privacy release transformed-source reference is invalid")
    transformed = run_dir / str(transformed_file)
    source_file = detection.get("source_file")
    if source_file not in {"source.srt", "source.txt"}:
        raise DownstreamBlocked("privacy release protected-source reference is invalid")
    source = run_dir / str(source_file)
    if detection.get("source_sha256") != sha256_file(source):
        raise DownstreamBlocked("protected source hash revalidation failed")
    if release.get("transformed_sha256") != sha256_file(transformed):
        raise DownstreamBlocked("transformed source hash revalidation failed")
    transformed_document = parse_document(transformed)
    source_document = parse_document(source)
    if (
        transformed_document.fingerprint != release.get("structure")
        or source_document.fingerprint != detection.get("structure")
        or source_document.fingerprint != transformed_document.fingerprint
    ):
        raise DownstreamBlocked("transformed source structure revalidation failed")
    try:
        replay, ranges, generalizations, false_bindings = render_reviewed_source(
            source_document, ledger, review, policy, language,
        )
        if (
            replay != transformed_document.text
            or second_pass["surrogate_ranges"] != [list(bounds) for bounds in ranges]
            or second_pass.get("generalizations", []) != generalizations
            or second_pass.get("false_positive_bindings", []) != false_bindings
        ):
            raise DownstreamBlocked("released text differs from the policy-authorized review transformation")
        current_findings = scan_document(transformed_document, language, policy)
        if canonical_bytes(second_pass["findings"]) != canonical_bytes([
            finding.public_dict() for finding in current_findings
        ]):
            raise DownstreamBlocked("second-pass findings differ from the current detector replay")
        finding_by_id = {item["finding_id"]: item for item in ledger["findings"]}
        finding_by_id.update({item["finding_id"]: item for item in review.get("additions", [])})
        decisions = {item["finding_id"]: item["decision"] for item in review["decisions"]}
        decisions.update({item["finding_id"]: item["decision"] for item in review.get("additions", [])})
        for start, end in second_pass["surrogate_ranges"]:
            if not re.fullmatch(r"\[(?:[A-Z][A-Z0-9_]*_[0-9]{3,}|…)\]", transformed_document.text[start:end]):
                raise DownstreamBlocked("surrogate range does not contain an emitted token")
        for item in second_pass.get("generalizations", []):
            original = finding_by_id[item["finding_id"]]
            result = generalize(
                original["entity_type"], source_document.text[original["start"]:original["end"]], language,
            )
            if (
                decisions[item["finding_id"]] != "GENERALIZE_CONFIRMED"
                or policy.action_for(original["entity_type"]).value != "GENERALIZE_AND_REVIEW"
                or item["entity_type"] != result.entity_type
                or item["rule_id"] != result.rule_id or item["text"] != result.text
                or transformed_document.text[item["start"]:item["end"]] != result.text
            ):
                raise DownstreamBlocked("generalization provenance binding failed")
        for item in second_pass.get("false_positive_bindings", []):
            original = finding_by_id[item["finding_id"]]
            if (
                decisions[item["finding_id"]] != "FALSE_POSITIVE"
                or original["entity_type"] != item["entity_type"]
                or original["value_sha256"] != item["value_sha256"]
                or sha256_bytes(transformed_document.text[item["start"]:item["end"]].encode()) != item["value_sha256"]
            ):
                raise DownstreamBlocked("false-positive provenance binding failed")
        for finding in second_pass["findings"]:
            if sha256_bytes(transformed_document.text[finding["start"]:finding["end"]].encode()) != finding.get("value_sha256"):
                raise DownstreamBlocked("second-pass finding source binding failed")
    except (KeyError, TypeError, ValueError) as exc:
        raise DownstreamBlocked("second-pass provenance fields are invalid") from exc
    return transformed, release
