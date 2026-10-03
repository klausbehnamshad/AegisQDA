from pathlib import Path
import json

import pytest
from pydantic import ValidationError

from aegisqda.config import GovernanceConfig, ROOT
from aegisqda.errors import BoundaryError, IntegrityError
from aegisqda.manifests import sha256_bytes
from aegisqda.synthetic_registry import source_registration, validate_source_registration


def test_repository_fixture_bytes_and_language_are_bound() -> None:
    source = ROOT / "tests/fixtures/en/sample.srt"
    raw = source.read_bytes()
    assert source_registration(source, raw, "en")["registered"] is True
    with pytest.raises(BoundaryError, match="bytes or language"):
        source_registration(source, raw + b" altered", "en")
    with pytest.raises(BoundaryError, match="bytes or language"):
        source_registration(source, raw, "fr")


def test_unregistered_repository_source_is_blocked() -> None:
    with pytest.raises(BoundaryError, match="not a registered"):
        source_registration(ROOT / "tests/fixtures/en/foreign.txt", b"Synthetic example", "en")


def test_external_assertion_has_honest_lower_assurance(tmp_path: Path) -> None:
    result = source_registration(tmp_path / "synthetic.txt", b"Synthetic example", "en")
    assert result == {"registered": False, "assurance": "EXPLICIT_SYNTHETIC_ASSERTION"}


@pytest.mark.parametrize("override", [
    {"trust_store_path": "/unavailable/store.json"},
    {"allow_retained_risk_claim": True},
    {"two_person_release_required": False},
    {"contract_version": "unknown"},
])
def test_unimplemented_governance_capabilities_cannot_be_enabled(override: dict[str, object]) -> None:
    with pytest.raises(ValidationError, match="not implemented"):
        GovernanceConfig.model_validate(override)


def test_relative_repository_paths_cannot_claim_external_assertion(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(ROOT)
    source = Path("tests/fixtures/en/sample.srt")
    assert source_registration(source, source.read_bytes(), "en")["registered"] is True
    with pytest.raises(BoundaryError, match="not a registered"):
        source_registration(Path("tests/fixtures/en/foreign.txt"), b"Synthetic example", "en")


def _registry_for(source: Path, raw: bytes) -> dict[str, object]:
    return {
        "schema": "aegisqda-synthetic-source-registry-v1",
        "files": [{
            "path": source.relative_to(ROOT).as_posix(),
            "language": "en", "source_sha256": sha256_bytes(raw), "source_bytes": len(raw),
        }],
    }


def test_registry_fingerprint_binds_the_same_snapshot_that_was_validated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import aegisqda.synthetic_registry as registry

    source = ROOT / "tests/fixtures/en/sample.srt"
    source_bytes = source.read_bytes()
    path = tmp_path / "registry.json"
    snapshot = json.dumps(_registry_for(source, source_bytes)).encode()
    path.write_bytes(snapshot)
    monkeypatch.setattr(registry, "REGISTRY", path)
    stable_read = registry.read_stable_source
    reads: list[Path] = []

    def read_then_replace(candidate: Path) -> bytes:
        reads.append(candidate)
        captured = stable_read(candidate)
        # Simulate a successor registry appearing immediately after one stable
        # read. The returned registration must bind the inspected snapshot.
        path.write_bytes(b'{"schema":"synthetic-successor"}')
        return captured

    monkeypatch.setattr(registry, "read_stable_source", read_then_replace)
    registered = source_registration(source, source_bytes, "en")
    assert registered["registry_sha256"] == sha256_bytes(snapshot)
    assert registered["registry_sha256"] != sha256_bytes(path.read_bytes())
    assert reads == [path]


@pytest.mark.parametrize("invalid_field", [
    {"source_bytes": True}, {"source_bytes": 0}, {"source_sha256": "not-a-hash"},
    {"source_sha256": "F" * 64}, {"language": "unknown"},
    {"path": "tests/fixtures/../en/sample.srt"},
])
def test_invalid_registry_entries_fail_before_any_fixture_is_registered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, invalid_field: dict[str, object],
) -> None:
    import aegisqda.synthetic_registry as registry

    source = ROOT / "tests/fixtures/en/sample.srt"
    source_bytes = source.read_bytes()
    data = _registry_for(source, source_bytes)
    data["files"][0].update(invalid_field)
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(data))
    monkeypatch.setattr(registry, "REGISTRY", path)
    with pytest.raises(IntegrityError, match="entry"):
        source_registration(source, source_bytes, "en")


def test_registration_revalidation_binds_current_registry_source_and_language() -> None:
    source = ROOT / "tests/fixtures/en/sample.srt"
    digest = sha256_bytes(source.read_bytes())
    registration = source_registration(source, source.read_bytes(), "en")
    validate_source_registration(registration, digest, "en")
    with pytest.raises(IntegrityError, match="registration"):
        validate_source_registration(registration, digest, "fr")
    with pytest.raises(IntegrityError, match="registration"):
        validate_source_registration(registration, "a" * 64, "en")
    with pytest.raises(IntegrityError, match="registration"):
        validate_source_registration({**registration, "registry_sha256": "a" * 64}, digest, "en")
