"""Consumer-owned, read-only adapter for the pinned DigQDA CLI."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Iterator

from .config import ROOT, load_config, load_policy
from .detection import scan_document
from .errors import DownstreamBlocked
from .formats.document import Document, Region
from .local_boundary import ollama_models, reject_proxy_environment, validate_loopback_url
from .manifests import canonical_bytes, seal, sha256_bytes, sha256_file
from .privacy_gate import validate_release
from .safeio import atomic_json, load_json, secure_dir, validate_run_dir
from .workflow import utc_now


def _strings(value: object) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)
    elif isinstance(value, dict):
        for key, item in value.items():
            if key not in {"_qda_run", "_qda_validation", "meta"}:
                yield from _strings(item)


def _field_strings(value: object, field: str = "") -> Iterator[tuple[str, str]]:
    if isinstance(value, str):
        yield field, value
    elif isinstance(value, list):
        for item in value:
            yield from _field_strings(item, field)
    elif isinstance(value, dict):
        for key, item in value.items():
            if key not in {"_qda_run", "_qda_validation", "meta"}:
                yield from _field_strings(item, key)


def _scan_outputs(paths: list[Path], language: str) -> int:
    policy = load_policy(load_config())
    count = 0
    for path in paths:
        payload = load_json(path)
        for field, value in _field_strings(payload):
            if not value:
                continue
            # The pinned DigQDA contract and prompt produce German analytical
            # prose, while bound evidence/source fields retain the source
            # language. Applying English NER to German nouns creates systematic
            # false PERSON hits; route each field to its actual language.
            scan_language = language if field in {"source_text", "source_quote"} else "de"
            chunk_size, overlap = 100_000, 1_024
            start = 0
            while start < len(value):
                chunk = value[start:start + chunk_size]
                document = Document("txt", chunk, (Region(0, len(chunk)),), {})
                count += len(scan_document(document, scan_language, policy))
                if start + chunk_size >= len(value):
                    break
                start += chunk_size - overlap
    return count


def _validate_digqda_contract(
    coding: dict[str, object], validation: dict[str, object], model: str, digest: str, source_sha: str
) -> dict[str, object]:
    manifest = coding.get("_qda_run")
    validation_manifest = validation.get("_qda_validation")
    if not isinstance(manifest, dict) or not isinstance(validation_manifest, dict):
        raise DownstreamBlocked("DigQDA provenance envelope is missing")
    statuses = manifest.get("statuses")
    result = validation_manifest.get("result")
    if not isinstance(statuses, list) or not isinstance(result, dict):
        raise DownstreamBlocked("DigQDA status or validation envelope is invalid")
    required = (
        manifest.get("library_version") == "0.4",
        manifest.get("contract_version") == "0.1",
        manifest.get("prompt_id") == "QDA-GEN-DESCRIPTIVE-CODING",
        manifest.get("prompt_version") == "1.2",
        manifest.get("prompt_source") == "file",
        manifest.get("backend") == "ollama",
        manifest.get("mode") == "OPEN_DESCRIPTIVE",
        manifest.get("provenance_level") == "MODEL_BOUND",
        manifest.get("model") == model,
        manifest.get("model_digest") == digest,
        manifest.get("source_sha256") == source_sha,
        isinstance(manifest.get("n_units"), int) and manifest.get("n_units", 0) > 0,
        manifest.get("n_ok") == manifest.get("n_units"),
        len(statuses) == manifest.get("n_units"),
        all(isinstance(item, dict) and item.get("status") == "OK" for item in statuses),
        all(
            isinstance(manifest.get(key), str)
            and re.fullmatch(r"[0-9a-f]{64}", str(manifest.get(key))) is not None
            for key in ("contract_sha256", "prompt_sha256", "schema_sha256", "grammar_sha256")
        ),
        validation_manifest.get("validator_version") == "0.4",
        validation_manifest.get("source_sha256") == source_sha,
        validation_manifest.get("input_sha256") == sha256_bytes(canonical_bytes(coding)),
        result.get("verdict") == "PASS",
        result.get("quotes_fuzzy") == 0,
        result.get("quotes_wrong_unit") == 0,
        result.get("quotes_not_found") == 0,
        result.get("quotes_unbound") == 0,
        result.get("quotes_missing_evidence") == 0,
        result.get("locators_invalid") == 0,
    )
    if not all(required):
        raise DownstreamBlocked("DigQDA contract or validation binding failed")
    return manifest


def analyze_run(run_dir: Path, model: str | None = None) -> Path:
    run_dir = validate_run_dir(run_dir)
    transformed, release = validate_release(run_dir)
    config = load_config()
    reject_proxy_environment()
    base_url = validate_loopback_url(config.execution.ollama_base_url)
    exact_model = model or config.models.default
    if exact_model not in config.models.dpo_approved_local_allowlist:
        raise DownstreamBlocked("requested model is not in the exact local allowlist")
    installed = ollama_models(base_url)
    digest = installed.get(exact_model)
    if digest is None:
        raise DownstreamBlocked(f"exact local model is not installed: {exact_model}")
    final_manifest_path = run_dir / "digqda-run.json"
    if final_manifest_path.exists():
        raise DownstreamBlocked("a completed DigQDA adapter manifest already exists")
    attempts_root = secure_dir(run_dir / "digqda-attempts")
    attempt_id = uuid.uuid4().hex
    output_root = attempts_root / attempt_id
    secure_dir(output_root)
    command = [
        sys.executable,
        str(ROOT / config.digqda.snapshot / "digqda"),
        "pilot",
        str(release["case_id"]),
        str(transformed),
        "--out-root",
        str(output_root),
        "--model",
        exact_model,
        "--mode",
        "open",
    ]
    environment = dict(os.environ)
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        environment.pop(key, None)
    environment["OLLAMA_HOST"] = base_url
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    runtime_shim = ROOT / "src" / "aegisqda" / "runtime_shim" / "sitecustomize.py"
    if not runtime_shim.is_file():
        raise DownstreamBlocked("required local Ollama runtime control is missing")
    environment["PYTHONPATH"] = str(runtime_shim.parent)

    def write_blocked_attempt(failure_kind: str, **details: object) -> None:
        attempt_path = output_root / "aegis-attempt.json"
        if attempt_path.exists():
            return
        atomic_json(
            attempt_path,
            seal(
                {
                    "schema": "aegisqda-digqda-attempt-v1",
                    "state": "BLOCKED",
                    "attempt_id": attempt_id,
                    "failure_kind": failure_kind,
                    "ollama_think": False,
                    "runtime_shim_sha256": sha256_file(runtime_shim),
                    **details,
                }
            ),
        )

    try:
        process = subprocess.run(
            command,
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=3600,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        write_blocked_attempt("LOCAL_EXECUTION_FAILURE")
        raise DownstreamBlocked("pinned DigQDA did not complete within the local bound") from exc
    if process.returncode != 0:
        write_blocked_attempt(
            "DIGQDA_NONZERO",
            exit_code=process.returncode,
            stdout_sha256=sha256_bytes(process.stdout.encode()),
            stderr_sha256=sha256_bytes(process.stderr.encode()),
        )
        raise DownstreamBlocked("pinned DigQDA exited non-zero; output is a non-result")
    coding_paths = list(output_root.rglob("coding.json"))
    validation_paths = list(output_root.rglob("validation.json"))
    segment_paths = list(output_root.rglob("segments.json"))
    if len(coding_paths) != 1 or len(validation_paths) != 1 or len(segment_paths) != 1:
        write_blocked_attempt("OUTPUT_ENVELOPE_INVALID")
        raise DownstreamBlocked("DigQDA did not produce one bound result envelope")
    coding = load_json(coding_paths[0])
    validation = load_json(validation_paths[0])
    try:
        run_manifest = _validate_digqda_contract(
            coding, validation, exact_model, digest, str(release["transformed_sha256"])
        )
    except DownstreamBlocked:
        write_blocked_attempt("CONTRACT_REVALIDATION_FAILED")
        raise
    output_hits = _scan_outputs(segment_paths + coding_paths + validation_paths, str(release["language"]))
    if output_hits:
        write_blocked_attempt("POST_SCAN_FINDINGS", finding_count=output_hits)
        raise DownstreamBlocked("post-DigQDA scan found identifying-risk output; external release blocked")
    adapter_manifest = seal(
        {
            "schema": "aegisqda-digqda-run-v1",
            "state": "DOWNSTREAM_REVIEW_REQUIRED",
            "created_at": utc_now(),
            "attempt_id": attempt_id,
            "privacy_release_sha256": sha256_file(run_dir / "privacy-release.json"),
            "model": exact_model,
            "model_digest": digest,
            "digqda_coding_sha256": sha256_file(coding_paths[0]),
            "digqda_validation_sha256": sha256_file(validation_paths[0]),
            "digqda_segments_sha256": sha256_file(segment_paths[0]),
            "contract_version": run_manifest["contract_version"],
            "contract_sha256": run_manifest["contract_sha256"],
            "prompt_version": run_manifest["prompt_version"],
            "prompt_sha256": run_manifest["prompt_sha256"],
            "schema_sha256": run_manifest["schema_sha256"],
            "validator_verdict": "PASS",
            "post_scan_findings": 0,
            "ollama_think": False,
            "runtime_shim_sha256": sha256_file(runtime_shim),
            "notice": "DigQDA output remains protected and requires methodological human review",
        }
    )
    atomic_json(final_manifest_path, adapter_manifest)
    return final_manifest_path
