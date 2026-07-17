"""Owner-only, non-overwriting filesystem operations."""

from __future__ import annotations

import json
import os
import re
import stat
import tempfile
from pathlib import Path
from typing import Any

from .config import ROOT
from .errors import BoundaryError, IntegrityError
from .manifests import canonical_bytes

OPAQUE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{2,63}")
CLOUD_PARTS = {
    "icloud drive",
    "mobile documents",
    "com~apple~clouddocs",
    "dropbox",
    "onedrive",
    "google drive",
    "box",
    "sharepoint",
}
MAX_SOURCE_BYTES = 50 * 1024 * 1024


def is_cloud_path(path: Path) -> bool:
    return any(marker in part.casefold() for part in path.parts for marker in CLOUD_PARTS)


def validate_opaque_id(value: str, *, label: str = "opaque id") -> str:
    if not OPAQUE_RE.fullmatch(value):
        raise BoundaryError(f"{label} must contain only 3-64 path-safe opaque characters")
    return value


def resolved_no_symlink(path: Path, *, must_exist: bool = True) -> Path:
    absolute = path.expanduser().absolute()
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current = current / part
        if current.exists() and current.is_symlink():
            raise BoundaryError("symlinks are forbidden at the protected boundary")
    try:
        return absolute.resolve(strict=must_exist)
    except OSError as exc:
        raise BoundaryError("protected path cannot be resolved") from exc


def validate_source(path: Path, *, synthetic: bool) -> Path:
    source = resolved_no_symlink(path)
    if not source.is_file() or source.suffix.lower() not in {".srt", ".txt"}:
        raise BoundaryError("source must be a local regular .srt or .txt file")
    if is_cloud_path(source):
        raise BoundaryError("cloud-sync paths are forbidden")
    if not synthetic:
        raise BoundaryError("real-data authorization is not implemented; use synthetic material only")
    if source.is_relative_to(ROOT) and not source.is_relative_to(ROOT / "tests" / "fixtures"):
        raise BoundaryError("repository sources are forbidden outside synthetic fixtures")
    return source


def read_stable_source(path: Path) -> bytes:
    """Read one regular file through a no-follow descriptor and reject concurrent changes."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise BoundaryError("protected source cannot be opened safely") from exc
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise BoundaryError("source must remain a regular file")
        if before.st_size > MAX_SOURCE_BYTES:
            raise BoundaryError("source exceeds the configured 50 MiB local bound")
        blocks: list[bytes] = []
        total = 0
        while True:
            block = os.read(fd, 1024 * 1024)
            if not block:
                break
            total += len(block)
            if total > MAX_SOURCE_BYTES:
                raise BoundaryError("source exceeds the configured 50 MiB local bound")
            blocks.append(block)
        after = os.fstat(fd)
        identity = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        if identity != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
            raise BoundaryError("source changed while it was being read")
        return b"".join(blocks)
    finally:
        os.close(fd)


def validate_run_root(path: Path) -> Path:
    root = resolved_no_symlink(path, must_exist=False)
    if root.is_relative_to(ROOT):
        raise BoundaryError("run directories must be outside Git")
    if is_cloud_path(root):
        raise BoundaryError("run directories cannot use a cloud-sync path")
    return root


def secure_dir(path: Path, *, create: bool = True) -> Path:
    if create:
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
    resolved_no_symlink(path)
    if not path.is_dir():
        raise BoundaryError("protected directory is not a directory")
    os.chmod(path, 0o700)
    return path


def fresh_run_dir(root: Path, case_id: str) -> Path:
    root = secure_dir(validate_run_root(root))
    case_dir = root / validate_opaque_id(case_id, label="case id")
    secure_dir(case_dir)
    return Path(tempfile.mkdtemp(prefix="run-", dir=case_dir)).resolve()


def atomic_write(path: Path, data: bytes) -> None:
    secure_dir(path.parent)
    if path.exists() or path.is_symlink():
        raise IntegrityError("protected artifact already exists")
    fd, temporary = tempfile.mkstemp(prefix=".aegis-", dir=path.parent)
    temp_path = Path(temporary)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temp_path, path)
        except FileExistsError as exc:
            raise IntegrityError("protected artifact already exists") from exc
        temp_path.unlink()
        os.chmod(path, 0o600)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    atomic_write(path, canonical_bytes(payload) + b"\n")


def load_json(path: Path) -> dict[str, Any]:
    path = resolved_no_symlink(path)
    if not path.is_file():
        raise IntegrityError("required protected artifact is missing")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise IntegrityError("protected artifact is not valid JSON") from exc
    if not isinstance(data, dict):
        raise IntegrityError("protected artifact root must be an object")
    return data


def validate_run_dir(path: Path) -> Path:
    run_dir = resolved_no_symlink(path)
    if run_dir.is_relative_to(ROOT) or is_cloud_path(run_dir) or not run_dir.is_dir():
        raise BoundaryError("run directory violates the protected boundary")
    return run_dir
