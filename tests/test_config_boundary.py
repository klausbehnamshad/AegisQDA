from __future__ import annotations

import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from aegisqda.config import Policy, load_config, load_policy
from aegisqda.errors import BoundaryError, UnsupportedLanguage
from aegisqda.languages import get_pack
from aegisqda.local_boundary import reject_proxy_environment, validate_loopback_url
from aegisqda.safeio import is_cloud_path, validate_source
from aegisqda.workflow import scan_source


def test_config_and_policy_are_strict() -> None:
    config = load_config()
    policy = load_policy(config)
    assert config.models.default == "gemma3:4b"
    assert config.models.dpo_approved_local_allowlist == ["gemma3:4b", "gemma4:e4b"]
    assert policy.action_for("UNDECLARED_ENTITY") == "BLOCK"


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1:11434",
        "http://example.com:11434",
        "http://127.0.0.1:11434/api",
        "http://user@127.0.0.1:11434",
    ],
)
def test_remote_or_ambiguous_endpoints_block(url: str) -> None:
    with pytest.raises(BoundaryError):
        validate_loopback_url(url)


def test_loopback_endpoint_passes() -> None:
    assert validate_loopback_url("http://127.0.0.1:11434") == "http://127.0.0.1:11434"


def test_active_proxy_blocks() -> None:
    with pytest.raises(BoundaryError):
        reject_proxy_environment({"HTTPS_PROXY": "http://proxy.invalid"})


def test_luxembourgish_is_explicitly_unsupported() -> None:
    with pytest.raises(UnsupportedLanguage, match="Luxembourgish"):
        get_pack("lb")


def test_symlink_source_blocks(tmp_path: Path) -> None:
    target = tmp_path / "target.txt"
    target.write_text("synthetic", encoding="utf-8")
    link = tmp_path / "link.txt"
    link.symlink_to(target)
    with pytest.raises(BoundaryError, match="symlinks"):
        validate_source(link, synthetic=True)


def test_cloud_path_blocks(tmp_path: Path) -> None:
    cloud = tmp_path / "Dropbox"
    cloud.mkdir()
    source = cloud / "source.txt"
    source.write_text("synthetic", encoding="utf-8")
    with pytest.raises(BoundaryError, match="cloud"):
        validate_source(source, synthetic=True)


def test_named_onedrive_path_blocks(tmp_path: Path) -> None:
    cloud = tmp_path / "OneDrive - Institution"
    cloud.mkdir()
    source = cloud / "source.txt"
    source.write_text("synthetic", encoding="utf-8")
    with pytest.raises(BoundaryError, match="cloud"):
        validate_source(source, synthetic=True)


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/Users/r/Library/CloudStorage/GoogleDrive-r@example.org/My Drive/runs", True),
        ("/Users/r/Library/CloudStorage/OneDrive-Personal/runs", True),
        ("/Users/r/Library/CloudStorage/Box-Box/runs", True),
        ("/Users/r/Box Sync/runs", True),
        ("/Volumes/GoogleDrive/My Drive/runs", True),
        ("/Users/r/Nextcloud/runs", True),
        ("/Users/r/ownCloud/runs", True),
        ("/Users/r/Sandbox/runs", False),
        ("/Users/r/inbox-export/runs", False),
        ("/Users/r/toolbox/runs", False),
        ("/Users/r/my drivers/runs", False),
    ],
)
def test_cloud_path_markers(path: str, expected: bool) -> None:
    assert is_cloud_path(Path(path)) is expected


def test_repository_source_outside_fixtures_blocks() -> None:
    source = Path(__file__).parents[1] / "vendor/digqda/90_UTILITIES/tests/fixtures/interview.txt"
    with pytest.raises(BoundaryError):
        validate_source(source, synthetic=True)


def test_real_data_gate_is_absent(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("synthetic", encoding="utf-8")
    with pytest.raises(BoundaryError, match="real-data authorization"):
        validate_source(source, synthetic=False)


def test_environment_has_no_proxy_for_workflow() -> None:
    assert not any(os.environ.get(name) for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"))


def test_proxy_blocks_scan_preflight(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "secret.txt"
    source.write_text("synthetic content", encoding="utf-8")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.invalid")
    with pytest.raises(BoundaryError, match="proxy"):
        scan_source(
            source,
            language="en",
            case_id="CASE-PROXY",
            run_root=tmp_path / "runs",
            synthetic=True,
        )


def test_unknown_policy_action_is_schema_error() -> None:
    policy = load_policy(load_config()).model_dump(mode="json")
    policy["entities"]["PERSON"] = "BLOKC"
    with pytest.raises(ValidationError):
        Policy.model_validate(policy)
