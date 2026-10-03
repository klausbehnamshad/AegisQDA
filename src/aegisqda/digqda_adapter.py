"""Consumer-owned, read-only adapter for the pinned DigQDA CLI."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import uuid
from copy import deepcopy
from collections.abc import Collection
from pathlib import Path
from typing import Iterator

from .config import ROOT, load_config, load_policy
from .detection import detector_versions, scan_document
from .errors import AegisError, DownstreamBlocked
from .formats.document import Document, Region
from .generalization import AGE_RULE, DATE_RULE, JOB_RULE, KINSHIP_RULE, is_generalized_output
from .local_boundary import ollama_models, reject_proxy_environment, validate_loopback_url
from .manifests import canonical_bytes, seal, sha256_bytes, sha256_file
from .privacy_gate import validate_release
from .safeio import (
    atomic_json, atomic_write, read_stable_source, resolved_no_symlink,
    secure_dir, validate_run_dir,
)
from .workflow import utc_now

# These fingerprints describe the reviewed, pinned OPEN_DESCRIPTIVE contract.
# A successor prompt needs an explicit language-contract review in this adapter;
# changing a file or a version string must never silently change detector routing.
PINNED_OPEN_HASHES = {
    "prompt_sha256": "72f1bc785a275264325b47202441823b597d61493ffb5e6ad1369264dd94344e",
    "schema_sha256": "c09ddafc7b9db9ff8c8b4b76c62f29324e8c3aacd5ffe53c70bbb1229520ff84",
    "grammar_sha256": "08d7f904525262efe967fc19523891fbc576b01b4b46740525fc160abbd8437a",
    "contract_sha256": "477179f1e7afa29d7d84e35c130a8957b5cb78fa9c127dce40df74b6023441c8",
}
SOURCE_LANGUAGE_FIELDS = {"source_text", "source_quote", "explicit_speaker", "closest_source"}
SURROGATE_TOKEN = re.compile(r"(?:\[[A-Z][A-Z0-9_]*_[0-9]{3,}\]|\[…\])\Z")
GENERALIZATION_RULES = (
    ("AGE", AGE_RULE), ("DATE_TIME", DATE_RULE),
    ("JOB_TITLE", JOB_RULE), ("KINSHIP", KINSHIP_RULE),
)
RUNTIME_CONTROL_ROOT = ROOT / "src" / "aegisqda" / "runtime_shim"
REQUIRED_RUNTIME_CONTROLS = {"__init__.py", "sitecustomize.py", "ollama_inventory.py", "ollama"}
FieldPath = tuple[str | int, ...]
NARRATIVE_FUNCTIONS = {
    "ORIENTATION", "EVENT_REPORT", "EVALUATION", "EXPLANATION_JUSTIFICATION",
    "COMPARISON", "GENERAL_STATEMENT", "OTHER",
}
VALID_LOCATOR_RESULTS = {"EXACT", "WITHIN", "SPAN", "PRESENT"}
RUN_CONSTANTS = {
    "runner_id": "QDA-P1-RUNNER", "library_version": "0.4", "contract_version": "0.1",
    "prompt_id": "QDA-GEN-DESCRIPTIVE-CODING", "prompt_version": "1.2", "prompt_source": "file",
    "backend": "ollama", "mode": "OPEN_DESCRIPTIVE", "provenance_level": "MODEL_BOUND",
    "allowed_method_claim": "GENERIC_SOURCE_NEAR_CONTROLLED_QDA_CODING",
    "note": "seed+temp0 verbessern die Wiederholbarkeit, garantieren sie nicht.",
    **PINNED_OPEN_HASHES,
}
RUN_HASH_FIELDS = {
    "model_digest", "source_sha256", "scope_sha256", "research_question_sha256",
}
QUANTIZATIONS = {
    "F32", "F16", "BF16", "Q4_0", "Q4_1", "Q5_0", "Q5_1", "Q8_0", "Q2_K",
    "Q3_K_S", "Q3_K_M", "Q3_K_L", "Q4_K_S", "Q4_K_M", "Q5_K_S", "Q5_K_M", "Q6_K",
}
VALIDATOR_PASS_REASON = "Jedes Zitat zeichengetreu in seiner Einheit belegt, Locatoren gueltig."
SEGMENT_NOTE = (
    "source_units sind mechanische Verarbeitungseinheiten, keine analytischen Segmente. "
    "Analytische Segmentierung bleibt P1/Mensch."
)


class _OutputChangedDuringScan(DownstreamBlocked):
    """An output fingerprint no longer describes the bytes that were scanned."""


def _json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _stable_json(path: Path) -> tuple[dict[str, object], str]:
    """Parse exactly the stable UTF-8 bytes whose fingerprint is returned."""
    try:
        raw = read_stable_source(resolved_no_symlink(path))
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_json_object)
        if not isinstance(payload, dict):
            raise ValueError("invalid root")
    except (AegisError, OSError, ValueError, UnicodeError) as exc:
        raise DownstreamBlocked("protected downstream JSON snapshot is invalid") from exc
    return payload, sha256_bytes(raw)


def _assert_artifact_snapshots(snapshots: dict[Path, str]) -> None:
    try:
        for path, expected in snapshots.items():
            if sha256_bytes(read_stable_source(resolved_no_symlink(path))) != expected:
                raise _OutputChangedDuringScan("output changed during protected post-scan")
    except (AegisError, OSError) as exc:
        raise _OutputChangedDuringScan("output changed during protected post-scan") from exc


def _runtime_control_material(runtime_root: Path) -> tuple[dict[str, bytes], str]:
    """Bind every executable source/control file, excluding unused bytecode."""
    try:
        runtime_root = resolved_no_symlink(runtime_root)
        files: dict[str, bytes] = {}
        fingerprints: dict[str, dict[str, str | bool]] = {}
        for path in sorted(runtime_root.rglob("*")):
            if path.is_symlink():
                raise DownstreamBlocked("runtime controls cannot contain symlinks")
            relative = path.relative_to(runtime_root)
            if "__pycache__" in relative.parts or path.suffix in {".pyc", ".pyo"} or not path.is_file():
                continue
            content = read_stable_source(path)
            name = relative.as_posix()
            files[name] = content
            fingerprints[name] = {
                "sha256": sha256_bytes(content), "executable": bool(path.stat().st_mode & 0o111),
            }
        if not REQUIRED_RUNTIME_CONTROLS <= files.keys() or not fingerprints["ollama"]["executable"]:
            raise DownstreamBlocked("required executable local Ollama runtime controls are missing")
    except (OSError, AegisError) as exc:
        raise DownstreamBlocked("local Ollama runtime controls cannot be bound safely") from exc
    return files, sha256_bytes(canonical_bytes(fingerprints))


def _analytical_language(prompt_sha256: str | None = None) -> str:
    expected = PINNED_OPEN_HASHES["prompt_sha256"]
    config = load_config()
    prompt_path = ROOT / config.digqda.snapshot / "10_GENERIC" / "p1_prompt.txt"
    if sha256_file(prompt_path) != expected or (prompt_sha256 is not None and prompt_sha256 != expected):
        raise DownstreamBlocked("pinned analytical output-language contract is unsupported")
    return "de"


def _field_strings(value: object, path: FieldPath = ()) -> Iterator[tuple[FieldPath, str]]:
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _field_strings(item, path + (index,))
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _field_strings(item, path + (str(key),))


def _validation_copy_input(
    validation: dict[str, object], expected_coding: dict[str, object] | None = None,
) -> dict[str, object]:
    """Reverse only the pinned validator's exact annotation paths.

    The validator copies the coding object to root ``data`` and adds locator
    and quote checks. Its input fingerprint must reconstruct exactly; unknown
    metadata or a changed evidence value cannot acquire a provenance exemption.
    """
    copied = validation.get("data")
    envelope = validation.get("_qda_validation")
    if not isinstance(copied, dict) or not isinstance(envelope, dict):
        raise DownstreamBlocked("DigQDA validation copied-input envelope is missing")
    restored = deepcopy(copied)
    units = restored.get("results")
    if not isinstance(units, list):
        raise DownstreamBlocked("DigQDA validation copied-input structure is invalid")
    for unit in units:
        if not isinstance(unit, dict) or not isinstance(unit.get("descriptive_codes"), list):
            raise DownstreamBlocked("DigQDA validation copied unit is invalid")
        for key in ("source_range_match", "source_range_unverified_match"):
            unit.pop(key, None)
        for code in unit["descriptive_codes"]:
            if not isinstance(code, dict):
                raise DownstreamBlocked("DigQDA validation copied code is invalid")
            for key in ("source_quote_match", "quote_locator_match"):
                code.pop(key, None)
    if (
        sha256_bytes(canonical_bytes(restored)) != envelope.get("input_sha256")
        or (expected_coding is not None and canonical_bytes(restored) != canonical_bytes(expected_coding))
    ):
        raise DownstreamBlocked("DigQDA validation copy is not bound to its exact coding input")
    return restored


def _control_string(role: str, path: FieldPath, value: str, source_label: str | None) -> bool:
    """Recognize reviewed machine vocabulary only at its canonical field path."""
    if role == "validation" and path[:1] == ("data",):
        path = path[1:]
        role = "annotated_coding"
    if role in {"coding", "annotated_coding"} and path[:1] == ("_qda_run",):
        tail = path[1:]
        if len(tail) == 1:
            key = tail[0]
            if key in RUN_CONSTANTS:
                return value == RUN_CONSTANTS[key]
            if key in RUN_HASH_FIELDS:
                return re.fullmatch(r"[0-9a-f]{64}", value) is not None
            if key == "run_id":
                return re.fullmatch(r"[0-9a-f]{32}", value) is not None
            if key == "model":
                return value in {"gemma3:4b", "gemma4:e4b"}
            if key == "model_quantization":
                return value in QUANTIZATIONS
            if key == "backend_client_version":
                return re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,3}", value) is not None
            if key == "timestamp":
                return re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2} UTC", value) is not None
        if len(tail) == 3 and tail[0] == "statuses" and type(tail[1]) is int:
            if tail[2] == "status":
                return value == "OK"
            if tail[2] in {"unit_input_sha256", "rendered_prompt_sha256"}:
                return re.fullmatch(r"[0-9a-f]{64}", value) is not None
            if tail[2] == "unit_id":
                return re.fullmatch(r"S[0-9]{2,}", value) is not None
    if role == "validation" and path[:1] == ("_qda_validation",):
        tail = path[1:]
        constants: dict[FieldPath, str] = {
            ("validator_id",): "QDA-UTIL-QUOTE-LOCATOR-VALIDATION", ("validator_version",): "0.4",
            ("result", "verdict"): "PASS", ("result", "reason"): VALIDATOR_PASS_REASON,
        }
        if tail in constants:
            return value == constants[tail]
        if tail in {("source_sha256",), ("input_sha256",)}:
            return re.fullmatch(r"[0-9a-f]{64}", value) is not None
        if tail == ("timestamp",):
            return re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2} UTC", value) is not None
    if role == "segments" and path[:1] == ("meta",):
        if path == ("meta", "source"):
            return source_label is not None and value == source_label
        if path == ("meta", "source_type"):
            return value in {"srt", "txt"}
        if path == ("meta", "source_sha256"):
            return re.fullmatch(r"[0-9a-f]{64}", value) is not None
        if path == ("meta", "mode"):
            return value in {"window", "cue", "paragraph"}
        if path == ("meta", "note"):
            return value == SEGMENT_NOTE
    unit_root = "source_units" if role == "segments" else "results"
    if role not in {"segments", "coding", "annotated_coding"} or (
        len(path) < 3 or path[0] != unit_root or type(path[1]) is not int
    ):
        return False
    tail = path[2:]
    if tail == ("unit_id",):
        return re.fullmatch(r"S[0-9]{2,}", value) is not None
    if tail == ("source_type",):
        return value in {"srt", "txt"}
    if tail == ("explicit_speaker",):
        return value in {"not stated", "multiple", "I", "P"}
    if tail == ("narrative_function",) and role != "segments":
        return value in NARRATIVE_FUNCTIONS
    if tail == ("coding_decision",) and role != "segments":
        return value in {"CODES_ASSIGNED", "NOTHING_CODABLE"}
    if tail == ("source_range",) or (
        len(tail) == 3 and tail[0] == "descriptive_codes" and type(tail[1]) is int and tail[2] == "quote_locator"
    ):
        return re.fullmatch(
            r"(?:[0-9]{2}:[0-9]{2}:[0-9]{2},[0-9]{3} --> [0-9]{2}:[0-9]{2}:[0-9]{2},[0-9]{3}|L[0-9]+-L[0-9]+)", value,
        ) is not None
    if len(tail) >= 3 and tail[0] == "descriptive_codes" and type(tail[1]) is int:
        code_tail = tail[2:]
        if code_tail == ("status",):
            return value == "INDUCTIVE_CANDIDATE"
        if role == "annotated_coding":
            if code_tail == ("source_quote_match", "result"):
                return value == "EXACT"
            if code_tail == ("quote_locator_match", "result"):
                return value in VALID_LOCATOR_RESULTS
            if code_tail == ("quote_locator_match", "match"):
                return value == "cue_index"
    if role == "annotated_coding":
        if tail in {("source_range_match", "result"), ("source_range_unverified_match", "result")}:
            return value in VALID_LOCATOR_RESULTS
        if tail in {("source_range_match", "match"), ("source_range_unverified_match", "match")}:
            return value == "cue_index"
    return False


def _scan_views(value: str, trusted_surrogates: Collection[str]) -> Iterator[str]:
    # Exempt only exact tokens whose positions were bound to the transformed
    # source. Arbitrary bracketed output is never an anonymization exemption.
    for token in sorted(trusted_surrogates, key=len, reverse=True):
        if SURROGATE_TOKEN.fullmatch(token) is None and not any(
            is_generalized_output(entity, token, rule) for entity, rule in GENERALIZATION_RULES
        ):
            raise DownstreamBlocked("downstream surrogate binding is invalid")
        value = value.replace(token, " " * len(token))
    yield value
    # Scan reconstructed views as well: formatting must not turn a name,
    # address, or identifier into a detector escape. These views are internal
    # only and never rewrite the protected DigQDA output or its evidence.
    unbracketed = value.translate(str.maketrans("", "", "[]"))
    seen = {value}
    for candidate in (
        unbracketed,
        re.sub(r"[\r\n]+", " ", unbracketed),
        re.sub(r"[\r\n]+[ \t]*", "", unbracketed),
    ):
        if candidate not in seen:
            seen.add(candidate)
            yield candidate


def _output_findings(
    paths: list[Path], language: str, *, prompt_sha256: str | None = None,
    trusted_surrogates: Collection[str] = (),
    expected_coding: dict[str, object] | None = None, source_label: str | None = None,
    artifact_root: Path | None = None,
) -> list[dict[str, object]]:
    policy = load_policy(load_config())
    analytical_language = _analytical_language(prompt_sha256)
    findings: dict[str, dict[str, object]] = {}
    material = [(path, *_stable_json(path)) for path in paths]
    for path, payload, _ in material:
        try:
            artifact_path = path.relative_to(artifact_root).as_posix() if artifact_root is not None else path.name
        except ValueError as exc:
            raise DownstreamBlocked("downstream scan artifact escaped its candidate root") from exc
        role = {"segments.json": "segments", "coding.json": "coding", "validation.json": "validation"}.get(path.name, "unknown")
        if role == "coding" and expected_coding is not None and canonical_bytes(payload) != canonical_bytes(expected_coding):
            raise DownstreamBlocked("DigQDA coding input changed before its post-scan")
        if role == "validation":
            _validation_copy_input(payload, expected_coding)
        for field_path, value in _field_strings(payload):
            if not value:
                continue
            if _control_string(role, field_path, value, source_label):
                continue
            # The pinned DigQDA contract and prompt produce German analytical
            # prose, while bound evidence/source fields retain the source
            # language. Applying English NER to German nouns creates systematic
            # false PERSON hits; route each field to its actual language.
            field = next((item for item in reversed(field_path) if isinstance(item, str)), "")
            scan_language = language if field in SOURCE_LANGUAGE_FIELDS else analytical_language
            chunk_size, overlap = 100_000, 1_024
            for view_index, view in enumerate(_scan_views(value, trusted_surrogates)):
                start = 0
                while start < len(view):
                    chunk = view[start:start + chunk_size]
                    document = Document("txt", chunk, (Region(0, len(chunk)),), {})
                    for finding in scan_document(document, scan_language, policy):
                        record: dict[str, object] = {
                            "path_name": path.name, "artifact_path": artifact_path,
                            "field_path": list(field_path), "view_index": view_index,
                            "start": start + finding.start, "end": start + finding.end,
                            "entity_type": finding.entity_type, "value_sha256": finding.value_sha256,
                            "scan_language": scan_language,
                        }
                        finding_id = sha256_bytes(canonical_bytes(record))
                        findings[finding_id] = {"finding_id": finding_id, **record}
                    if start + chunk_size >= len(view):
                        break
                    start += chunk_size - overlap
    _assert_artifact_snapshots({path: content_sha for path, _, content_sha in material})
    return [findings[finding_id] for finding_id in sorted(findings)]


def _scan_outputs(
    paths: list[Path], language: str, *, prompt_sha256: str | None = None,
    trusted_surrogates: Collection[str] = (),
    expected_coding: dict[str, object] | None = None, source_label: str | None = None,
    artifact_root: Path | None = None,
) -> int:
    """Compatibility count wrapper around deterministic post-scan evidence."""
    return len(_output_findings(
        paths, language, prompt_sha256=prompt_sha256, trusted_surrogates=trusted_surrogates,
        expected_coding=expected_coding, source_label=source_label, artifact_root=artifact_root,
    ))


def _released_surrogates(run_dir: Path, transformed: Path, release: dict[str, object]) -> set[str]:
    """Read exemptions from the exact already-released byte snapshots."""
    second_bytes = read_stable_source(run_dir / "second-pass.json")
    transformed_bytes = read_stable_source(transformed)
    if (
        sha256_bytes(second_bytes) != release.get("second_pass_sha256")
        or sha256_bytes(transformed_bytes) != release.get("transformed_sha256")
    ):
        raise DownstreamBlocked("released surrogate provenance changed before downstream scan")
    try:
        second_pass = json.loads(second_bytes)
        text = transformed_bytes.decode("utf-8")
        ranges = second_pass["surrogate_ranges"]
        if not isinstance(ranges, list):
            raise ValueError("invalid ranges")
        tokens: set[str] = set()
        for bounds in ranges:
            if (
                not isinstance(bounds, list) or len(bounds) != 2
                or type(bounds[0]) is not int or type(bounds[1]) is not int
                or not 0 <= bounds[0] < bounds[1] <= len(text)
            ):
                raise ValueError("invalid range")
            token = text[bounds[0]:bounds[1]]
            if SURROGATE_TOKEN.fullmatch(token) is None:
                raise ValueError("invalid surrogate")
            tokens.add(token)
        generalizations = second_pass.get("generalizations", [])
        if not isinstance(generalizations, list):
            raise ValueError("invalid generalizations")
        for record in generalizations:
            if not isinstance(record, dict):
                raise ValueError("invalid generalization")
            start, end = record.get("start"), record.get("end")
            if (
                type(start) is not int or type(end) is not int
                or not 0 <= start < end <= len(text)
                or not all(isinstance(record.get(key), str) for key in ("entity_type", "text", "rule_id"))
                or record["text"] != text[start:end]
                or not is_generalized_output(record["entity_type"], record["text"], record["rule_id"])
            ):
                raise ValueError("invalid bound generalization")
            tokens.add(record["text"])
    except (KeyError, TypeError, ValueError, UnicodeError) as exc:
        raise DownstreamBlocked("released surrogate binding is invalid") from exc
    return tokens


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
    if "data" in validation:
        _validation_copy_input(validation, coding)
    _analytical_language(str(manifest.get("prompt_sha256", "")))
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
            manifest.get(key) == expected
            for key, expected in PINNED_OPEN_HASHES.items()
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
    release_snapshot, release_sha = _stable_json(run_dir / "privacy-release.json")
    transformed_sha = sha256_bytes(read_stable_source(resolved_no_symlink(transformed)))
    if (
        canonical_bytes(release_snapshot) != canonical_bytes(release)
        or transformed_sha != release.get("transformed_sha256")
    ):
        raise DownstreamBlocked("privacy release changed before the downstream attempt")
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
    approved_pairs = {(item.tag, item.digest) for item in config.models.dpo_approved_local_pairs}
    if (exact_model, digest) not in approved_pairs:
        raise DownstreamBlocked("installed model digest differs from the approved exact tag/digest pair")
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
    environment.pop("OLLAMA_API_KEY", None)
    environment["AEGISQDA_APPROVED_MODEL"] = exact_model
    environment["AEGISQDA_APPROVED_MODEL_DIGEST"] = digest
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    runtime_files, runtime_control_sha = _runtime_control_material(RUNTIME_CONTROL_ROOT)
    runtime_shim_sha = sha256_bytes(runtime_files["sitecustomize.py"])
    # Freeze the runtime controls used by every child. A concurrent repo edit
    # cannot change a later-started runner inside this attempt.
    runtime_snapshot = secure_dir(output_root / "runtime-control")
    for name, content in runtime_files.items():
        atomic_write(runtime_snapshot / name, content)
    (runtime_snapshot / "ollama").chmod(0o700)
    environment["PYTHONPATH"] = str(runtime_snapshot)
    environment["PYTHONPYCACHEPREFIX"] = str(output_root / "unused-python-cache")
    environment["PATH"] = str(runtime_snapshot) + os.pathsep + environment.get("PATH", os.defpath)
    environment["AEGISQDA_RUNTIME_PYTHON"] = sys.executable
    environment["AEGISQDA_INVENTORY_PROBE"] = str(runtime_snapshot / "ollama_inventory.py")

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
                    "runtime_shim_sha256": runtime_shim_sha,
                    "runtime_control_sha256": runtime_control_sha,
                    **details,
                }
            ),
        )

    def revalidate_input_release() -> None:
        try:
            current_transformed, current_release = validate_release(run_dir)
            stable_release, current_release_sha = _stable_json(run_dir / "privacy-release.json")
            if (
                current_transformed != transformed
                or current_release_sha != release_sha
                or canonical_bytes(current_release) != canonical_bytes(release_snapshot)
                or canonical_bytes(stable_release) != canonical_bytes(release_snapshot)
                or sha256_bytes(read_stable_source(resolved_no_symlink(transformed))) != transformed_sha
            ):
                raise DownstreamBlocked("changed input release")
        except (AegisError, OSError, ValueError, TypeError) as exc:
            write_blocked_attempt("INPUT_RELEASE_CHANGED")
            raise DownstreamBlocked("privacy release changed during the downstream attempt") from exc

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
    try:
        _, current_runtime_sha = _runtime_control_material(RUNTIME_CONTROL_ROOT)
        if current_runtime_sha != runtime_control_sha:
            raise DownstreamBlocked("local runtime controls changed during the downstream attempt")
    except DownstreamBlocked:
        write_blocked_attempt("RUNTIME_CONTROL_CHANGED")
        raise
    revalidate_input_release()
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
    try:
        material = {
            name: (path, *_stable_json(path))
            for name, path in (
                ("segments", segment_paths[0]), ("coding", coding_paths[0]),
                ("validation", validation_paths[0]),
            )
        }
    except DownstreamBlocked:
        write_blocked_attempt("OUTPUT_ENVELOPE_INVALID")
        raise
    coding, validation = material["coding"][1], material["validation"][1]
    try:
        run_manifest = _validate_digqda_contract(
            coding, validation, exact_model, digest, str(release["transformed_sha256"])
        )
    except DownstreamBlocked:
        write_blocked_attempt("CONTRACT_REVALIDATION_FAILED")
        raise
    try:
        trusted_surrogates = _released_surrogates(run_dir, transformed, release)
        output_findings = _output_findings(
            segment_paths + coding_paths + validation_paths,
            str(release["language"]),
            prompt_sha256=str(run_manifest["prompt_sha256"]),
            trusted_surrogates=trusted_surrogates,
            expected_coding=coding,
            source_label=str(release["case_id"]) + transformed.suffix.lower(),
            artifact_root=output_root,
        )
    except _OutputChangedDuringScan:
        write_blocked_attempt("OUTPUT_CHANGED_DURING_SCAN")
        raise
    except DownstreamBlocked:
        write_blocked_attempt("POST_SCAN_CONTRACT_INVALID")
        raise
    try:
        _assert_artifact_snapshots({path: content_sha for path, _, content_sha in material.values()})
    except _OutputChangedDuringScan:
        write_blocked_attempt("OUTPUT_CHANGED_DURING_SCAN")
        raise
    revalidate_input_release()
    if output_findings:
        candidate = {
            "synthetic_only": True,
            "language": str(release["language"]),
            "source_label": str(release["case_id"]) + transformed.suffix.lower(),
            "model": exact_model, "model_digest": digest,
            "privacy_release_sha256": release_sha,
            "artifacts": {
                name: {"path": path.relative_to(output_root).as_posix(), "sha256": content_sha}
                for name, (path, _, content_sha) in material.items()
            },
            "contract": {
                "contract_version": run_manifest["contract_version"],
                "prompt_version": run_manifest["prompt_version"], **PINNED_OPEN_HASHES,
            },
            "detector_versions": {
                scan_language: detector_versions(scan_language)
                for scan_language in {str(release["language"]), "de"}
            },
            "findings": output_findings,
        }
        write_blocked_attempt("POST_SCAN_FINDINGS", finding_count=len(output_findings), review_candidate=candidate)
        raise DownstreamBlocked(
            f"post-DigQDA scan found identifying-risk output; attempt_id={attempt_id}; protected review required"
        )
    adapter_manifest = seal(
        {
            "schema": "aegisqda-digqda-run-v1",
            "state": "DOWNSTREAM_REVIEW_REQUIRED",
            "created_at": utc_now(),
            "attempt_id": attempt_id,
            "privacy_release_sha256": release_sha,
            "model": exact_model,
            "model_digest": digest,
            "digqda_coding_sha256": material["coding"][2],
            "digqda_validation_sha256": material["validation"][2],
            "digqda_segments_sha256": material["segments"][2],
            "contract_version": run_manifest["contract_version"],
            "contract_sha256": run_manifest["contract_sha256"],
            "prompt_version": run_manifest["prompt_version"],
            "prompt_sha256": run_manifest["prompt_sha256"],
            "schema_sha256": run_manifest["schema_sha256"],
            "validator_verdict": "PASS",
            "post_scan_findings": 0,
            "post_scan_analytical_language": _analytical_language(str(run_manifest["prompt_sha256"])),
            "post_scan_source_language": release["language"],
            "ollama_think": False,
            "runtime_shim_sha256": runtime_shim_sha,
            "runtime_control_sha256": runtime_control_sha,
            "notice": "DigQDA output remains protected and requires methodological human review",
        }
    )
    atomic_json(final_manifest_path, adapter_manifest)
    return final_manifest_path
