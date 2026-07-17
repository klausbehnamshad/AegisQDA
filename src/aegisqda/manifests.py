"""Canonical hashes and integrity-sealed JSON artifacts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .errors import IntegrityError


def canonical_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def seal(payload: dict[str, Any]) -> dict[str, Any]:
    if "integrity_sha256" in payload:
        raise IntegrityError("artifact is already sealed")
    result = dict(payload)
    result["integrity_sha256"] = sha256_bytes(canonical_bytes(payload))
    return result


def verify_seal(payload: dict[str, Any]) -> None:
    actual = payload.get("integrity_sha256")
    unsigned = {key: value for key, value in payload.items() if key != "integrity_sha256"}
    if not isinstance(actual, str) or actual != sha256_bytes(canonical_bytes(unsigned)):
        raise IntegrityError("artifact integrity check failed")
