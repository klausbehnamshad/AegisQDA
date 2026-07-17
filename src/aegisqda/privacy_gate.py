"""Revalidation of a privacy release immediately before downstream use."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import DEFAULT_CONFIG, ROOT, load_config, load_policy
from .errors import DownstreamBlocked
from .formats.document import parse_document
from .local_boundary import reject_proxy_environment, validate_loopback_url, verify_upstream
from .manifests import sha256_file, verify_seal
from .safeio import load_json, validate_run_dir
from .review_signature import verify_review_signature
from .workflow import DETECTION_FILE, LEDGER_FILE, RELEASE_FILE, REVIEW_FILE


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
        signed_review = verify_review_signature(review)
    except Exception as exc:
        raise DownstreamBlocked("valid privacy release artifacts are required") from exc
    checks = (
        release.get("state") == "PRIVACY_RELEASED",
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
        second_pass.get("unresolved_count") == 0,
        release.get("source_sha256") == detection.get("source_sha256"),
        signed_review or detection.get("synthetic_only") is True,
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
    if parse_document(transformed).fingerprint != release.get("structure"):
        raise DownstreamBlocked("transformed source structure revalidation failed")
    return transformed, release
