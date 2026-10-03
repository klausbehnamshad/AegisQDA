"""Byte-bound registration for sources under the repository fixture boundary."""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

from .config import ROOT
from .errors import BoundaryError, IntegrityError
from .manifests import sha256_bytes
from .safeio import read_stable_source, resolved_no_symlink

REGISTRY = ROOT / "tests" / "fixtures" / "synthetic_sources.json"


def _snapshot() -> tuple[list[dict[str, Any]], str]:
    raw = read_stable_source(resolved_no_symlink(REGISTRY))
    try:
        registry = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise IntegrityError("synthetic source registry is invalid JSON") from exc
    if not isinstance(registry, dict):
        raise IntegrityError("synthetic source registry must be an object")
    if registry.get("schema") != "aegisqda-synthetic-source-registry-v1":
        raise IntegrityError("synthetic source registry schema is invalid")
    entries = registry.get("files")
    if not isinstance(entries, list) or not entries:
        raise IntegrityError("synthetic source registry is empty or invalid")
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise IntegrityError("synthetic source registry entry is invalid")
        name = entry.get("path")
        digest = entry.get("source_sha256")
        if (
            not isinstance(name, str) or name in seen
            or not name.startswith("tests/fixtures/") or ".." in Path(name).parts
            or Path(name).suffix not in {".srt", ".txt"}
            or entry.get("language") not in {"de", "fr", "en", "lb"}
            or not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None
            or type(entry.get("source_bytes")) is not int or entry["source_bytes"] < 1
        ):
            raise IntegrityError("synthetic source registry entry is invalid")
        seen.add(name)
    return entries, sha256_bytes(raw)


def validate_source_registration(registration: object, source_hash: str, language: str) -> None:
    if registration == {"assurance": "EXPLICIT_SYNTHETIC_ASSERTION", "registered": False}:
        return
    entries, digest = _snapshot()
    if (
        not isinstance(registration, dict)
        or registration.get("registered") is not True
        or registration.get("assurance") != "REGISTERED_SYNTHETIC_FIXTURE"
        or registration.get("source_sha256") != source_hash
        or registration.get("registry_sha256") != digest
        or not any(
            item["source_sha256"] == source_hash and item["language"] == language
            for item in entries
        )
    ):
        raise IntegrityError("synthetic source registration is missing, changed or invalid; rescan required")


def source_registration(source: Path, raw: bytes, language: str) -> dict[str, Any]:
    """Repository fixtures require exact registered bytes and declared language.

    External synthetic test sources retain the explicit assertion assurance of
    the MVP. Neither registration nor an assertion authorizes real data.
    """
    source = source.expanduser().absolute()
    if not source.is_relative_to(ROOT):
        return {"assurance": "EXPLICIT_SYNTHETIC_ASSERTION", "registered": False}
    entries, digest = _snapshot()
    relative = source.relative_to(ROOT).as_posix()
    selected = None
    for entry in entries:
        name = entry.get("path")
        if name == relative:
            selected = entry
    if selected is None:
        raise BoundaryError("repository source is not a registered synthetic fixture")
    if (
        selected.get("source_sha256") != sha256_bytes(raw)
        or selected.get("source_bytes") != len(raw)
        or selected.get("language") != language
    ):
        raise BoundaryError("synthetic fixture bytes or language differ from registration")
    return {
        "assurance": "REGISTERED_SYNTHETIC_FIXTURE",
        "registered": True,
        "registry_sha256": digest,
        "source_sha256": sha256_bytes(raw),
    }
