"""Protected synthetic case collections with source-free descriptive matrices.

Immutable registrations bind a released run and its existing research history.
Hashes detect inconsistent changes; these unkeyed seals do not establish trust,
anonymity, methodological validity, or permission to disclose research material.
"""

from __future__ import annotations

import json
import os
import re
import stat
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from . import workbench
from .errors import BoundaryError, IntegrityError, ReviewRequired
from .manifests import seal, sha256_bytes, verify_seal
from .privacy_gate import validate_release
from .safeio import (
    atomic_json, read_stable_source, resolved_no_symlink, secure_dir,
    validate_opaque_id, validate_run_dir, validate_run_root,
)
from .workflow import utc_now

SCHEMA = "aegisqda-research-workspace-v1"
CASE_SCHEMA = "aegisqda-workspace-case-v1"
SUMMARY_SCHEMA = "aegisqda-research-workspace-summary-v1"
ASSURANCE = "UNKEYED_SYNTHETIC_RESEARCH_ONLY"
MANIFEST_FILE = "workspace.json"
CASE_DIRECTORY = "cases"
_HASH = re.compile(r"[a-f0-9]{64}")
_MANIFEST_KEYS = {"schema", "created_at", "synthetic_only", "assurance", "integrity_sha256"}
_CASE_KEYS = {
    "schema", "sequence", "created_at", "case_id", "run_dir", "method",
    "workspace_manifest_sha256", "previous_registration_sha256", "privacy_release_sha256",
    "research_prefix_count", "research_prefix_head_sha256", "synthetic_only", "assurance",
    "integrity_sha256",
}


def _boundary(path: Path, *, existing: bool) -> Path:
    # Include broken symlinks, which do not satisfy Path.exists().
    absolute = path.expanduser().absolute()
    if any(part.is_symlink() for part in (absolute, *absolute.parents)):
        raise BoundaryError("symlinks are forbidden at the workspace boundary")
    result = validate_run_dir(absolute) if existing else validate_run_root(absolute)
    if any((part / ".git").exists() for part in (result, *result.parents)):
        raise BoundaryError("research workspaces and cases must be outside Git")
    return result


def _protected(path: Path, *, directory: bool = False) -> Path:
    path = resolved_no_symlink(path)
    try:
        metadata = path.stat()
    except OSError as exc:
        raise BoundaryError("protected workspace artifact is unavailable") from exc
    expected = 0o700 if directory else 0o600
    regular = stat.S_ISDIR(metadata.st_mode) if directory else stat.S_ISREG(metadata.st_mode)
    if not regular or metadata.st_uid != os.getuid() or stat.S_IMODE(metadata.st_mode) != expected:
        raise BoundaryError("workspace artifacts must remain owner-only regular files/directories")
    return path


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise IntegrityError("workspace artifact contains duplicate JSON keys")
        result[key] = value
    return result


def _read(path: Path) -> tuple[dict[str, Any], str]:
    raw = read_stable_source(_protected(path))
    try:
        value = json.loads(raw, object_pairs_hook=_unique_object)
    except (ValueError, UnicodeError) as exc:
        raise IntegrityError("workspace artifact is not valid JSON") from exc
    if not isinstance(value, dict):
        raise IntegrityError("workspace artifact must be an object")
    verify_seal(value)
    return value, sha256_bytes(raw)


def _timestamp(value: object) -> bool:
    if not isinstance(value, str) or not value.endswith("Z"):
        return False
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return False
    offset = parsed.utcoffset()
    return offset is not None and offset.total_seconds() == 0


def _hash(value: object) -> bool:
    return isinstance(value, str) and _HASH.fullmatch(value) is not None


def _id(value: object) -> str:
    if not isinstance(value, str):
        raise IntegrityError("workspace case id must be a string identifier")
    return validate_opaque_id(value, label="workspace case id")


def create_workspace(path: Path) -> Path:
    """Create an empty owner-only workspace outside any Git/cloud-sync path."""
    root = _boundary(path, existing=False)
    if root.exists() and (not root.is_dir() or any(root.iterdir())):
        raise IntegrityError("workspace initialization requires a new or empty directory")
    secure_dir(root)
    atomic_json(root / MANIFEST_FILE, seal({
        "schema": SCHEMA, "created_at": utc_now(), "synthetic_only": True,
        "assurance": ASSURANCE,
    }))
    secure_dir(root / CASE_DIRECTORY)
    return root


def _registrations(workspace: Path) -> tuple[Path, str, list[tuple[dict[str, Any], str]]]:
    root = _protected(_boundary(workspace, existing=True), directory=True)
    if {path.name for path in root.iterdir()} != {MANIFEST_FILE, CASE_DIRECTORY}:
        raise IntegrityError("workspace contains missing or unexpected artifacts")
    manifest, manifest_hash = _read(root / MANIFEST_FILE)
    if (
        set(manifest) != _MANIFEST_KEYS or manifest.get("schema") != SCHEMA
        or manifest.get("synthetic_only") is not True or manifest.get("assurance") != ASSURANCE
        or not _timestamp(manifest.get("created_at"))
    ):
        raise IntegrityError("workspace manifest contract is invalid")
    cases = _protected(root / CASE_DIRECTORY, directory=True)
    registrations: list[tuple[dict[str, Any], str]] = []
    previous: str | None = None
    ids: set[str] = set()
    runs: set[str] = set()
    releases: set[str] = set()
    for sequence, path in enumerate(sorted(cases.iterdir()), 1):
        if path.name != f"case-{sequence:06d}.json":
            raise IntegrityError("workspace registration sequence has gaps or foreign files")
        value, digest = _read(path)
        if (
            set(value) != _CASE_KEYS or value.get("schema") != CASE_SCHEMA
            or type(value.get("sequence")) is not int or value.get("sequence") != sequence
            or value.get("previous_registration_sha256") != previous
            or value.get("workspace_manifest_sha256") != manifest_hash
            or value.get("synthetic_only") is not True or value.get("assurance") != ASSURANCE
            or not _timestamp(value.get("created_at"))
            or not _hash(value.get("privacy_release_sha256"))
            or not _hash(value.get("research_prefix_head_sha256"))
            or type(value.get("research_prefix_count")) is not int
            or value["research_prefix_count"] < 1
            or not isinstance(value.get("method"), str) or value["method"] not in workbench.METHODS
            or not isinstance(value.get("run_dir"), str)
        ):
            raise IntegrityError("workspace registration provenance contract is invalid")
        case_id = _id(value.get("case_id"))
        run = _boundary(Path(value["run_dir"]), existing=True)
        if str(run) != value["run_dir"]:
            raise IntegrityError("workspace run reference must be a canonical absolute path")
        if case_id in ids or str(run) in runs or value["privacy_release_sha256"] in releases:
            raise IntegrityError("workspace case or run has duplicate/rebound registrations")
        ids.add(case_id)
        runs.add(str(run))
        releases.add(value["privacy_release_sha256"])
        registrations.append((value, digest))
        previous = digest
    return root, manifest_hash, registrations


def _research_snapshot(run: Path) -> list[tuple[dict[str, Any], str]]:
    research = run / "research"
    if not research.exists():
        raise ReviewRequired("declare a research method before registering a case")
    _protected(research, directory=True)
    result = []
    for sequence, path in enumerate(sorted(research.iterdir()), 1):
        if path.name != f"event-{sequence:06d}.json":
            raise IntegrityError("research event sequence has gaps or foreign files")
        result.append(_read(path))
    if not result:
        raise ReviewRequired("declare a research method before registering a case")
    return result


def _case_state(run_dir: Path, registration: dict[str, Any] | None = None) -> dict[str, Any]:
    run = _protected(_boundary(run_dir, existing=True), directory=True)
    try:
        _, validated = validate_release(run)
    except OSError as exc:
        raise IntegrityError("released research artifacts are unavailable") from exc
    release, release_hash = _read(run / "privacy-release.json")
    if release != validated:
        raise IntegrityError("privacy release changed after revalidation")
    detection, detection_hash = _read(run / "detection.json")
    if detection.get("synthetic_only") is not True:
        raise BoundaryError("research workspaces accept released synthetic cases only")
    if detection_hash != release.get("detection_sha256"):
        raise IntegrityError("synthetic detection changed after release revalidation")
    if registration is not None and release_hash != registration["privacy_release_sha256"]:
        raise IntegrityError("registered privacy release changed; case rebinding is forbidden")
    snapshot = _research_snapshot(run)
    # Reuse the workbench's method, hierarchy, evidence and event-chain validation.
    try:
        _, document, events = workbench._load(run)
    except OSError as exc:
        raise IntegrityError("released research artifacts are unavailable") from exc
    if [event for event, _ in snapshot] != events or _research_snapshot(run) != snapshot:
        raise IntegrityError("research history changed during workspace validation")
    transformed_hash = sha256_bytes(read_stable_source(_protected(run / f"transformed.{document.kind}")))
    source_hash = sha256_bytes(read_stable_source(_protected(run / f"source.{document.kind}")))
    if (
        transformed_hash != sha256_bytes(document.text.encode())
        or transformed_hash != release.get("transformed_sha256")
        or source_hash != release.get("source_sha256")
        or _read(run / "privacy-release.json")[1] != release_hash
        or _read(run / "detection.json")[1] != detection_hash
    ):
        raise IntegrityError("research source, detection or release changed during validation")
    if registration is not None:
        count = registration["research_prefix_count"]
        if (
            len(snapshot) < count or snapshot[count - 1][1] != registration["research_prefix_head_sha256"]
            or events[0]["method"] != registration["method"]
        ):
            raise IntegrityError("registered research history was rewritten or truncated")
    definitions = {
        event["code_id"]: (event["label"], event["definition"], event.get("parent_id"))
        for event in events if event["kind"] == "CODE_DEFINED"
    }
    coding = {
        (event["code_id"], event["start"], event["end"])
        for event in events if event["kind"] == "CODE_APPLIED"
    }
    return {
        "run_dir": str(run), "privacy_release_sha256": release_hash,
        "method": events[0]["method"], "definitions": definitions,
        "counts": dict(Counter(item[0] for item in coding)),
        "research_prefix_count": len(snapshot), "research_prefix_head_sha256": snapshot[-1][1],
    }


def _compatible(states: list[dict[str, Any]]) -> tuple[str | None, list[str]]:
    method: str | None = None
    definitions: dict[str, tuple[str, str, str | None]] = {}
    for state in states:
        if method is not None and method != state["method"]:
            raise ReviewRequired("workspace cases use incompatible declared research methods")
        method = state["method"]
        for code_id, definition in state["definitions"].items():
            if code_id in definitions and definitions[code_id] != definition:
                raise ReviewRequired("shared code id has conflicting labels, definitions or hierarchy")
            definitions[code_id] = definition
    return method, sorted(definitions)


def _unchanged(workspace: Path, manifest_hash: str, registrations: list[tuple[dict[str, Any], str]]) -> None:
    _, current_manifest, current_registrations = _registrations(workspace)
    if current_manifest != manifest_hash or current_registrations != registrations:
        raise IntegrityError("workspace registrations changed during validation")


def add_case(workspace: Path, run_dir: Path, case_id: str) -> Path:
    """Append one immutable case registration; existing ids/runs cannot be rebound."""
    case_id = _id(case_id)
    root, manifest_hash, registrations = _registrations(workspace)
    states = [_case_state(Path(item["run_dir"]), item) for item, _ in registrations]
    state = _case_state(run_dir)
    if (
        any(item["case_id"] == case_id for item, _ in registrations)
        or any(item["run_dir"] == state["run_dir"] for item, _ in registrations)
        or any(item["privacy_release_sha256"] == state["privacy_release_sha256"] for item, _ in registrations)
    ):
        raise ReviewRequired("workspace case id or released run is already registered; rebinding is forbidden")
    _compatible([*states, state])
    _unchanged(root, manifest_hash, registrations)
    value = seal({
        "schema": CASE_SCHEMA, "sequence": len(registrations) + 1, "created_at": utc_now(),
        "case_id": case_id, "run_dir": state["run_dir"], "method": state["method"],
        "workspace_manifest_sha256": manifest_hash,
        "previous_registration_sha256": registrations[-1][1] if registrations else None,
        "privacy_release_sha256": state["privacy_release_sha256"],
        "research_prefix_count": state["research_prefix_count"],
        "research_prefix_head_sha256": state["research_prefix_head_sha256"],
        "synthetic_only": True, "assurance": ASSURANCE,
    })
    path = root / CASE_DIRECTORY / f"case-{len(registrations) + 1:06d}.json"
    atomic_json(path, value)
    return path


def workspace_summary(workspace: Path) -> dict[str, Any]:
    """Revalidate every bound release/history and return only ids and exact-span counts."""
    root, manifest_hash, registrations = _registrations(workspace)
    states = [_case_state(Path(item["run_dir"]), item) for item, _ in registrations]
    method, codes = _compatible(states)
    _unchanged(root, manifest_hash, registrations)
    return {
        "schema": SUMMARY_SCHEMA, "state": "METHODOLOGICAL_REVIEW_REQUIRED",
        "synthetic_only": True, "method": method,
        "case_count": len(states), "code_count": len(codes), "codes": codes,
        "matrix": [
            {"case_id": item["case_id"], "coding_counts": {
                code: state["counts"].get(code, 0) for code in codes
            }}
            for (item, _), state in zip(registrations, states, strict=True)
        ],
        "assurance": ASSURANCE,
        "notice": "Synthetic descriptive counts of distinct exact evidence spans per code/case. "
                  "Each case is revalidated independently; no atomic cross-case snapshot. "
                  "Methodological review required; definitions, labels and memos remain protected. "
                  "Unkeyed integrity checks establish no trust, anonymity or external release.",
    }
