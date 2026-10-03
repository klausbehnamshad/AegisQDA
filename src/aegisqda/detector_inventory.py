"""Read-only local asset fingerprints for future detector qualification.

An inventory establishes current byte identity, not recall, model approval or
institutional authorization. No model download or inference is performed.
"""

from __future__ import annotations

import hashlib
import importlib.util
import os
import stat
from pathlib import Path
from typing import Any

from .config import DEFAULT_CONFIG, ROOT, load_config
from .detection import detector_versions
from .errors import IntegrityError
from .languages import get_pack
from .manifests import canonical_bytes, sha256_bytes
from .safeio import read_stable_source, resolved_no_symlink

MAX_MODEL_FILE = 1024 * 1024 * 1024
MAX_MODEL_TREE = 2 * MAX_MODEL_FILE
CONTROL_FILES = (
    "src/aegisqda/detection.py", "src/aegisqda/languages.py",
    "src/aegisqda/generalization.py", "src/aegisqda/formats/document.py",
)


def _identity(metadata: os.stat_result) -> tuple[int, int, int, int, int]:
    return metadata.st_dev, metadata.st_ino, metadata.st_size, metadata.st_mtime_ns, metadata.st_ctime_ns


def _files(root: Path) -> list[Path]:
    result: list[Path] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise IntegrityError("detector asset tree contains a symlink")
        relative = path.relative_to(root)
        if "__pycache__" in relative.parts or path.suffix in {".pyc", ".pyo"}:
            continue
        if path.is_file():
            result.append(path)
        elif not path.is_dir():
            raise IntegrityError("detector asset tree contains a nonregular entry")
    return result


def _file_digest(path: Path) -> tuple[str, os.stat_result]:
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError as exc:
        raise IntegrityError("detector asset cannot be opened safely") from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_MODEL_FILE:
            raise IntegrityError("detector asset is not a bounded regular file")
        digest = hashlib.sha256()
        total = 0
        while block := os.read(descriptor, 1024 * 1024):
            total += len(block)
            if total > MAX_MODEL_FILE:
                raise IntegrityError("detector asset exceeds the local inventory bound")
            digest.update(block)
        if _identity(before) != _identity(os.fstat(descriptor)) or total != before.st_size:
            raise IntegrityError("detector asset changed while fingerprinting")
        return digest.hexdigest(), before
    finally:
        os.close(descriptor)


def fingerprint_model_tree(root: Path) -> dict[str, object]:
    root = resolved_no_symlink(root)
    if not root.is_dir():
        raise IntegrityError("detector model package root is invalid")
    files = _files(root)
    if not files:
        raise IntegrityError("detector model package is empty")
    material: dict[str, dict[str, object]] = {}
    identities: dict[Path, tuple[int, int, int, int, int]] = {}
    total = 0
    for path in files:
        digest, metadata = _file_digest(path)
        total += metadata.st_size
        if total > MAX_MODEL_TREE:
            raise IntegrityError("detector model tree exceeds the local inventory bound")
        material[path.relative_to(root).as_posix()] = {"sha256": digest, "bytes": metadata.st_size}
        identities[path] = _identity(metadata)
    if files != _files(root) or any(_identity(path.stat()) != identity for path, identity in identities.items()):
        raise IntegrityError("detector model tree changed while fingerprinting")
    return {"tree_sha256": sha256_bytes(canonical_bytes(material)), "file_count": len(files), "bytes": total}


def detector_inventory(language: str) -> dict[str, Any]:
    pack = get_pack(language, require_release_ready=False)
    config_sha = sha256_bytes(read_stable_source(resolved_no_symlink(DEFAULT_CONFIG)))
    config = load_config(DEFAULT_CONFIG)
    control_material = {
        relative: sha256_bytes(read_stable_source(resolved_no_symlink(ROOT / relative)))
        for relative in CONTROL_FILES
    }
    config_relative = DEFAULT_CONFIG.relative_to(ROOT).as_posix()
    control_material[config_relative] = config_sha
    policy_path = resolved_no_symlink(ROOT / config.privacy.policy)
    if not policy_path.is_relative_to(ROOT):
        raise IntegrityError("detector inventory policy must stay in the repository")
    control_material[policy_path.relative_to(ROOT).as_posix()] = sha256_bytes(read_stable_source(policy_path))
    versions = detector_versions(language)
    model = pack.optional_ner_model
    spec = importlib.util.find_spec(model) if model else None
    assets = None
    if spec is not None:
        locations = list(spec.submodule_search_locations or ())
        if len(locations) != 1:
            raise IntegrityError("detector model package root is ambiguous")
        assets = fingerprint_model_tree(Path(locations[0]))
    for relative, expected in control_material.items():
        if sha256_bytes(read_stable_source(resolved_no_symlink(ROOT / relative))) != expected:
            raise IntegrityError("detector controls changed during inventory")
    if versions != detector_versions(language):
        raise IntegrityError("detector versions changed during inventory")
    return {
        "schema": "aegisqda-detector-inventory-v1",
        "state": "UNQUALIFIED_LOCAL_INVENTORY",
        "language": language, "detector_versions": versions,
        "recognizer_controls_sha256": sha256_bytes(canonical_bytes(control_material)),
        "controls": control_material, "model_assets": assets,
        "model_installed": assets is not None,
        "synthetic_language_ready": pack.release_ready,
        "governed_pilot_authorized": False,
        "notice": "Read-only current byte identity; no recall, qualification, trusted approval or real-data authorization.",
    }
