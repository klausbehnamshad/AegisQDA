"""Detector assets must be stable; a fingerprint cannot bless a model."""

from pathlib import Path
from types import SimpleNamespace

import pytest

import aegisqda.detector_inventory as inventory
from aegisqda.errors import AegisError, IntegrityError


def test_asset_content_and_names_change_fingerprint(tmp_path: Path) -> None:
    root = tmp_path / "model"
    root.mkdir()
    asset = root / "weights.bin"
    asset.write_bytes(b"SYNTHETIC MODEL ASSET")
    original = inventory.fingerprint_model_tree(root)
    asset.write_bytes(b"SYNTHETIC MODEL ASSET CHANGED")
    assert inventory.fingerprint_model_tree(root)["tree_sha256"] != original["tree_sha256"]
    changed = inventory.fingerprint_model_tree(root)
    asset.rename(root / "other.bin")
    assert inventory.fingerprint_model_tree(root)["tree_sha256"] != changed["tree_sha256"]


def test_bytecode_is_unused_but_symlinks_fail_closed(tmp_path: Path) -> None:
    root = tmp_path / "model"
    root.mkdir()
    (root / "weights.bin").write_bytes(b"SYNTHETIC")
    original = inventory.fingerprint_model_tree(root)
    (root / "__pycache__").mkdir()
    (root / "__pycache__/cache.pyc").write_bytes(b"ignored")
    assert inventory.fingerprint_model_tree(root) == original
    (root / "alias").symlink_to(root / "weights.bin")
    with pytest.raises(AegisError, match="symlink"):
        inventory.fingerprint_model_tree(root)


def test_replacement_during_inventory_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "model"
    root.mkdir()
    asset = root / "weights.bin"
    asset.write_bytes(b"SYNTHETIC")
    original = inventory._file_digest

    def changed(path: Path):
        result = original(path)
        replacement = root / "replacement"
        replacement.write_bytes(b"SYNTHETIC")
        replacement.replace(path)
        return result

    monkeypatch.setattr(inventory, "_file_digest", changed)
    with pytest.raises(IntegrityError, match="changed"):
        inventory.fingerprint_model_tree(root)


def test_inventory_uses_installed_assets_without_qualification(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "synthetic-model"
    root.mkdir()
    (root / "tokenizer").write_bytes(b"SYNTHETIC TOKENIZER")
    monkeypatch.setattr(inventory.importlib.util, "find_spec", lambda name: SimpleNamespace(submodule_search_locations=[str(root)]))
    report = inventory.detector_inventory("en")
    assert report["model_installed"] is True
    assert report["model_assets"]["file_count"] == 1
    assert report["state"] == "UNQUALIFIED_LOCAL_INVENTORY"
    assert report["governed_pilot_authorized"] is False
    assert str(root) not in str(report)


def test_missing_or_optional_model_never_claims_pilot_readiness(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(inventory.importlib.util, "find_spec", lambda name: None)
    for language in ("en", "lb"):
        report = inventory.detector_inventory(language)
        assert report["model_installed"] is False
        assert report["model_assets"] is None
        assert report["governed_pilot_authorized"] is False
    assert inventory.detector_inventory("lb")["synthetic_language_ready"] is False


def test_empty_and_oversized_assets_are_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "model"
    root.mkdir()
    with pytest.raises(IntegrityError, match="empty"):
        inventory.fingerprint_model_tree(root)
    (root / "weights.bin").write_bytes(b"SYNTHETIC")
    monkeypatch.setattr(inventory, "MAX_MODEL_FILE", 2)
    with pytest.raises(IntegrityError, match="bounded"):
        inventory.fingerprint_model_tree(root)


def test_changed_configuration_during_model_inventory_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = inventory.load_config()
    for relative in (*inventory.CONTROL_FILES, config.privacy.policy, "config/aegisqda.local.yaml"):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((inventory.ROOT / relative).read_bytes())
    model = tmp_path / "synthetic-model"
    model.mkdir()
    (model / "tokenizer").write_bytes(b"SYNTHETIC TOKENIZER")
    local_config = tmp_path / "config/aegisqda.local.yaml"
    monkeypatch.setattr(inventory, "ROOT", tmp_path)
    monkeypatch.setattr(inventory, "DEFAULT_CONFIG", local_config)
    monkeypatch.setattr(inventory.importlib.util, "find_spec", lambda name: SimpleNamespace(submodule_search_locations=[str(model)]))
    original = inventory.fingerprint_model_tree

    def changed(root: Path):
        result = original(root)
        local_config.write_bytes(local_config.read_bytes() + b"\n# synthetic concurrent configuration change\n")
        return result

    monkeypatch.setattr(inventory, "fingerprint_model_tree", changed)
    with pytest.raises(IntegrityError, match="controls changed"):
        inventory.detector_inventory("en")
