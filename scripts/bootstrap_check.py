#!/usr/bin/env python3
"""Model-free integrity check for the AegisQDA bootstrap repository."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCK = json.loads((ROOT / "UPSTREAM.lock.json").read_text(encoding="utf-8"))

required = [
    ROOT / "config" / "aegisqda.local.yaml",
    ROOT / "policies" / "strict.yaml",
    ROOT / "docs" / "MEGAPROMPT_NEXT_WINDOW.md",
    ROOT / LOCK["snapshot_path"] / "digqda",
    ROOT / LOCK["snapshot_path"] / "README.md",
]

failures = [f"missing: {path}" for path in required if not path.exists()]
if (ROOT / LOCK["snapshot_path"] / ".git").exists():
    failures.append("vendored DigQDA snapshot contains forbidden .git metadata")

manifest_lines = []
for path in sorted((ROOT / LOCK["snapshot_path"]).rglob("*")):
    if path.is_file():
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        relative = path.relative_to(ROOT).as_posix()
        manifest_lines.append(f"{digest}  {relative}\n")
actual = hashlib.sha256("".join(manifest_lines).encode()).hexdigest()

if actual != LOCK["snapshot_manifest_sha256"]:
    failures.append(
        "vendored DigQDA snapshot does not match UPSTREAM.lock.json: "
        f"expected {LOCK['snapshot_manifest_sha256']}, got {actual}"
    )

print(f"normalized_snapshot_manifest_sha256={actual}")
print(f"source_commit={LOCK['source_commit']}")
print(f"failures={len(failures)}")
for failure in failures:
    print(f"FAIL: {failure}")
raise SystemExit(1 if failures else 0)
