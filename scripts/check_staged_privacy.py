#!/usr/bin/env python3
"""Inspect Git's index without exposing paths/content or changing registrations.

This is a local, opt-in pre-commit guard. Hash registration proves fixture byte
identity; it cannot establish that arbitrary newly registered material is
synthetic. Human responsibility and the repository privacy rules still apply.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
from typing import Sequence

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = "tests/fixtures/synthetic_sources.json"
LANGUAGES = {"de", "fr", "en", "lb"}
SENSITIVE_ROOTS = {
    "data", "run", "runs", "review", "reviews", "quarantine", "mapping", "mappings",
    "secret", "secrets", "output", "outputs", "source", "sources", "artifacts", "claude outputs",
}
PRIVATE_EXTENSIONS = {".pem", ".key", ".p12", ".pfx"}
RUNTIME_BASENAMES = {
    "detection.json", "detection-ledger.json", "review.json", "output-review.json", "privacy-release.json",
    "second-pass.json", "digqda-run.json", "aegis-attempt.json", "coding.json",
    "validation.json", "segments.json", "mapping.json", "mappings.json",
    "source.txt", "source.srt", "transformed.txt", "transformed.srt",
    "workspace.json",
}
# These are process artifact families, not every AegisQDA JSON document.
# Registries, hand-authored synthetic annotations and governance declarations
# have different schemas and remain versionable. Versions cannot evade a rule
# by upgrading from v1 to v2 or by copying an artifact under another extension.
RUNTIME_SCHEMA = re.compile(
    r"aegisqda-(?:detection(?:-ledger)?|review|output-review|privacy-release|second-pass|"
    r"digqda-(?:run|attempt)|release-approval|research-(?:event|summary|workspace(?:-summary)?|case|matrix)|workspace-case|"
    r"segment-(?:index|search)|analyst-dissent|offline-verification|detector-inventory|"
    r"review-plan|run-audit|synthetic-acceptance)-v[0-9]+\Z"
)
PRIVATE_KEY_MARKER = re.compile(rb"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----", re.IGNORECASE)
PUTTY_KEY_HEADER = re.compile(rb"^PuTTY-User-Key-File-[23]:", re.MULTILINE)
PUTTY_PRIVATE_LINES = re.compile(rb"^Private-Lines: *[1-9][0-9]*", re.MULTILINE)
MAX_BLOB_BYTES = 50 * 1024 * 1024


@dataclass(frozen=True)
class StagedEntry:
    path: str
    data: bytes | None
    status: str = "M"
    mode: str = "100644"


@dataclass(frozen=True)
class StagedValidation:
    checked_count: int
    violation_counts: dict[str, int]

    @property
    def ok(self) -> bool:
        return not self.violation_counts

    def public_dict(self) -> dict[str, object]:
        return {
            "schema": "aegisqda-staged-privacy-check-v1",
            "status": "PASSED" if self.ok else "BLOCKED",
            "checked_count": self.checked_count,
            "violation_counts": dict(sorted(self.violation_counts.items())),
            "read_only": True,
        }


def _valid_path(name: str) -> bool:
    path = PurePosixPath(name)
    return (
        bool(name) and bool(path.parts) and not path.is_absolute() and "\\" not in name and "\x00" not in name
        and path.as_posix() == name and all(part not in {".", ".."} for part in path.parts)
    )


def _path_language(name: str) -> str | None:
    parts = PurePosixPath(name).parts
    found = [part for part in parts[2:-1] if part in LANGUAGES]
    return found[0] if len(found) == 1 else None


def _is_runtime_json(content: bytes) -> bool:
    """Recognize actual top-level process schemas without inspecting PII."""
    try:
        payload = json.loads(content)
    except (ValueError, UnicodeError):
        return False
    if not isinstance(payload, dict):
        return False
    schema = payload.get("schema")
    return isinstance(schema, str) and RUNTIME_SCHEMA.fullmatch(schema) is not None


def _registry(raw: bytes | None) -> dict[str, dict[str, object]]:
    if raw is None:
        raise ValueError("synthetic fixture registry is unavailable")
    payload = json.loads(raw)
    if not isinstance(payload, dict) or payload.get("schema") != "aegisqda-synthetic-source-registry-v1":
        raise ValueError("synthetic fixture registry schema is invalid")
    files = payload.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError("synthetic fixture registry entries are invalid")
    entries: dict[str, dict[str, object]] = {}
    for entry in files:
        if not isinstance(entry, dict):
            raise ValueError("synthetic fixture registry entry is invalid")
        name, digest, size = entry.get("path"), entry.get("source_sha256"), entry.get("source_bytes")
        if (
            not isinstance(name, str) or not _valid_path(name) or name in entries
            or not name.startswith("tests/fixtures/") or PurePosixPath(name).suffix not in {".txt", ".srt"}
            or entry.get("language") not in LANGUAGES or entry.get("language") != _path_language(name)
            or not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None
            or type(size) is not int or size < 1
        ):
            raise ValueError("synthetic fixture registry entry is invalid")
        entries[name] = entry
    return entries


def validate_staged(
    entries: Sequence[StagedEntry], registry_bytes: bytes | None,
) -> StagedValidation:
    """Pure validation of index snapshots; report only fixed violation codes/counts."""
    violations: Counter[str] = Counter()
    fixture_entries: list[StagedEntry] = []
    registry_changed = False
    staged_registry = next((entry for entry in entries if entry.path == REGISTRY_PATH), None)
    selected_registry = staged_registry.data if staged_registry is not None else registry_bytes
    seen_paths: set[str] = set()
    for entry in entries:
        if entry.path in seen_paths:
            violations["DUPLICATE_STAGED_PATH"] += 1
        seen_paths.add(entry.path)
        if not _valid_path(entry.path):
            violations["INVALID_STAGED_PATH"] += 1
            continue
        parts = PurePosixPath(entry.path).parts
        if tuple(part.casefold() for part in parts[:2]) == ("vendor", "digqda"):
            violations["PINNED_UPSTREAM_CHANGE"] += 1
            continue
        # Removing sensitive material reduces exposure. It cannot introduce a
        # source, and therefore needs neither fixture registration nor an
        # exception to the rule against committing research data.
        if entry.status == "D":
            continue
        if entry.status not in {"A", "C", "M", "R", "T"}:
            violations["UNRESOLVED_STAGED_ENTRY"] += 1
            continue
        if entry.mode not in {"100644", "100755"}:
            violations["NON_REGULAR_STAGED_FILE"] += 1
            continue
        name = parts[-1].casefold()
        if parts[0].casefold() in SENSITIVE_ROOTS:
            violations["SENSITIVE_DIRECTORY"] += 1
        if PurePosixPath(name).suffix in PRIVATE_EXTENSIONS or name == ".env" or name.startswith(".env."):
            violations["SECRET_FILE"] += 1
        if name in RUNTIME_BASENAMES or re.fullmatch(r"(?:event|case)-[0-9]{6}\.json", name):
            violations["RUNTIME_ARTIFACT"] += 1
        if entry.data is None:
            violations["STAGED_CONTENT_UNAVAILABLE"] += 1
            continue
        if _is_runtime_json(entry.data):
            violations["RUNTIME_ARTIFACT_SCHEMA"] += 1
        if PRIVATE_KEY_MARKER.search(entry.data) or (
            PUTTY_KEY_HEADER.search(entry.data) and PUTTY_PRIVATE_LINES.search(entry.data)
        ):
            violations["PRIVATE_KEY_CONTENT"] += 1
        if entry.path == REGISTRY_PATH:
            registry_changed = True
        if PurePosixPath(name).suffix in {".txt", ".srt"}:
            if entry.path.startswith("tests/fixtures/"):
                fixture_entries.append(entry)
            elif entry.path != "requirements.txt":
                violations["UNREGISTERED_SOURCE_FILE"] += 1
    registry: dict[str, dict[str, object]] = {}
    if fixture_entries or registry_changed:
        try:
            registry = _registry(selected_registry)
        except (ValueError, UnicodeError, TypeError):
            violations["INVALID_SYNTHETIC_REGISTRY"] += 1
    for entry in fixture_entries:
        expected = registry.get(entry.path)
        if (
            expected is None or entry.data is None
            or expected.get("source_sha256") != hashlib.sha256(entry.data).hexdigest()
            or expected.get("source_bytes") != len(entry.data)
            or expected.get("language") != _path_language(entry.path)
        ):
            violations["SYNTHETIC_FIXTURE_MISMATCH"] += 1
    return StagedValidation(len(entries), dict(violations))


def _git(root: Path, args: Sequence[str]) -> bytes:
    result = subprocess.run(
        ["git", "--no-optional-locks", "-C", str(root), *args],
        check=False, capture_output=True,
    )
    if result.returncode:
        raise ValueError("local Git index inspection failed")
    return result.stdout


def collect_staged(root: Path = ROOT) -> tuple[list[StagedEntry], bytes | None]:
    """Read raw index entries and blobs, honoring the staged registry over disk."""
    raw = _git(root, ["diff", "--cached", "--raw", "--no-abbrev", "--no-renames", "--no-ext-diff", "-z"])
    fields = raw.split(b"\x00")
    if fields[-1] == b"":
        fields.pop()
    if len(fields) % 2:
        raise ValueError("local Git index entry format is invalid")
    entries: list[StagedEntry] = []
    for offset in range(0, len(fields), 2):
        header = fields[offset].decode("ascii").split()
        if len(header) != 5 or not header[0].startswith(":"):
            raise ValueError("local Git index entry format is invalid")
        mode, object_id, status = header[1], header[3], header[4]
        path = fields[offset + 1].decode("utf-8")
        data: bytes | None = None
        if status != "D" and mode in {"100644", "100755"}:
            if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", object_id) or not object_id.strip("0"):
                raise ValueError("local Git staged object is invalid")
            size = int(_git(root, ["cat-file", "-s", object_id]))
            if not 0 <= size <= MAX_BLOB_BYTES:
                raise ValueError("local Git staged object exceeds the inspection bound")
            data = _git(root, ["cat-file", "blob", object_id])
            if len(data) != size:
                raise ValueError("local Git staged object changed during inspection")
        entries.append(StagedEntry(path, data, status, mode))
    registry_entry = next((item for item in entries if item.path == REGISTRY_PATH), None)
    if registry_entry is not None:
        registry_bytes = registry_entry.data
    else:
        registry_path = root / REGISTRY_PATH
        registry_bytes = None if registry_path.is_symlink() or not registry_path.is_file() else registry_path.read_bytes()
    if raw != _git(root, ["diff", "--cached", "--raw", "--no-abbrev", "--no-renames", "--no-ext-diff", "-z"]):
        raise ValueError("local Git index changed during inspection")
    return entries, registry_bytes


def main() -> int:
    try:
        entries, registry_bytes = collect_staged()
        result = validate_staged(entries, registry_bytes)
    except (OSError, ValueError, UnicodeError, TypeError):
        result = StagedValidation(0, {"INDEX_INSPECTION_FAILED": 1})
    print(json.dumps(result.public_dict(), sort_keys=True))
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
