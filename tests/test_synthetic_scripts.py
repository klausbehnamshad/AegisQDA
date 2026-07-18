from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

from aegisqda.privacy_gate import _second_pass_is_consistent

ROOT = Path(__file__).parents[1]


def _load_script(name: str) -> ModuleType:
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"test_{name}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_auto_review_allowlist_is_fixed_and_matches_all_corpus_files() -> None:
    module = _load_script("auto_review_synthetic")
    hashes = module.registered_hashes()
    assert len(hashes) == 9


def test_auto_review_has_no_caller_supplied_allowlist_option() -> None:
    module = _load_script("auto_review_synthetic")
    with pytest.raises(SystemExit) as exc:
        module.main(["/nonexistent", "--test-allowlist", "/tmp/foreign.json"])
    assert exc.value.code == 2


def test_verifier_rejects_manifest_path_escape() -> None:
    module = _load_script("verify_interviews")
    manifest_path = ROOT / "tests" / "fixtures" / "interviews" / "interviews_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"][0]["path"] = "../risk.txt"
    with pytest.raises(ValueError, match="escapes"):
        module.validate_manifest(manifest)


def test_second_pass_consistency_binds_exempt_finding_to_surrogate_range() -> None:
    finding: dict[str, object] = {"finding_id": "F-0001", "start": 11, "end": 21}
    payload = {
        "finding_count": 1,
        "surrogate_ranges": [[10, 22]],
        "surrogate_exempt_count": 1,
        "surrogate_exempt_finding_ids": ["F-0001"],
        "findings": [finding],
    }
    assert _second_pass_is_consistent(payload)
    finding["end"] = 23
    assert not _second_pass_is_consistent(payload)
