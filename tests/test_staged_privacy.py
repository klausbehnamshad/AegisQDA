"""Pure synthetic snapshots: these tests never stage, commit, or configure Git."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType

import pytest

ROOT = Path(__file__).parents[1]


@pytest.fixture
def guard() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "aegis_staged_guard_test", ROOT / "scripts" / "check_staged_privacy.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _registry(path: str, content: bytes, *, language: str = "en") -> bytes:
    return json.dumps({
        "schema": "aegisqda-synthetic-source-registry-v1",
        "files": [{"path": path, "language": language,
                   "source_sha256": hashlib.sha256(content).hexdigest(),
                   "source_bytes": len(content)}],
    }).encode()


@pytest.mark.parametrize("path", [
    "sources/interview.txt", "runs/case/source.srt", "outputs/report.md", "data/notes.csv",
    "review/local.md", "mappings/table.csv", "secrets/credentials.yaml", "Claude outputs/pilot.md",
])
def test_sensitive_root_material_is_blocked_without_filename_disclosure(guard: ModuleType, path: str) -> None:
    result = guard.validate_staged([guard.StagedEntry(path, b"synthetic content")], None)
    assert not result.ok
    assert result.violation_counts["SENSITIVE_DIRECTORY"] == 1
    assert path not in json.dumps(result.public_dict())
    assert "synthetic content" not in json.dumps(result.public_dict())


@pytest.mark.parametrize("path", [
    "key.pem", "cert.KEY", "nested/key.p12", "certificate.pfx", ".env", "nested/.env.local",
])
def test_private_key_files_and_dotenv_are_blocked(guard: ModuleType, path: str) -> None:
    result = guard.validate_staged([guard.StagedEntry(path, b"synthetic")], None)
    assert result.violation_counts["SECRET_FILE"] == 1


@pytest.mark.parametrize("kind", ["", "RSA ", "EC ", "OPENSSH ", "ENCRYPTED "])
def test_private_key_markers_are_blocked_even_in_code_files(guard: ModuleType, kind: str) -> None:
    # Deliberately build the marker from parts: this source file contains no
    # complete marker that would itself trip the guard when committed.
    marker = ("-----BEGIN " + kind + "PRIVATE KEY" + "-----").encode()
    result = guard.validate_staged([guard.StagedEntry("src/accidental_secret.py", marker)], None)
    assert result.violation_counts == {"PRIVATE_KEY_CONTENT": 1}
    assert marker.decode() not in json.dumps(result.public_dict())


def test_putty_private_key_header_is_blocked(guard: ModuleType) -> None:
    content = b"PuTTY-User-Key-File-" + b"3: ssh-rsa\nPrivate-Lines: 1\nsynthetic-key-body\n"
    assert guard.validate_staged([guard.StagedEntry("misc/key.md", content)], None).violation_counts == {
        "PRIVATE_KEY_CONTENT": 1,
    }


def test_guard_and_its_tests_do_not_trigger_their_own_marker_rules(guard: ModuleType) -> None:
    entries = [
        guard.StagedEntry(path, (ROOT / path).read_bytes(), "A")
        for path in ("scripts/check_staged_privacy.py", "tests/test_staged_privacy.py", ".githooks/pre-commit")
    ]
    assert guard.validate_staged(entries, None).ok


@pytest.mark.parametrize("name", [
    "detection.json", "detection-ledger.json", "review.json", "output-review.json", "privacy-release.json",
    "second-pass.json", "digqda-run.json", "coding.json", "validation.json", "segments.json",
    "source.srt", "transformed.txt", "event-000001.json", "case-000001.json", "workspace.json",
])
def test_runtime_artifacts_are_blocked_outside_runtime_directory(guard: ModuleType, name: str) -> None:
    result = guard.validate_staged([guard.StagedEntry(f"misc/{name}", b"synthetic")], None)
    assert result.violation_counts["RUNTIME_ARTIFACT"] == 1


@pytest.mark.parametrize("schema", [
    "aegisqda-research-event-v1", "aegisqda-research-summary-v1",
    "aegisqda-privacy-release-v1", "aegisqda-privacy-release-v2",
    "aegisqda-detection-v1", "aegisqda-detection-ledger-v1", "aegisqda-review-v1",
    "aegisqda-second-pass-v1", "aegisqda-digqda-run-v1", "aegisqda-digqda-attempt-v1",
    "aegisqda-release-approval-v1", "aegisqda-output-review-v1",
    "aegisqda-research-workspace-v1", "aegisqda-research-case-v1", "aegisqda-research-matrix-v1",
    "aegisqda-workspace-case-v1", "aegisqda-research-workspace-summary-v1",
    "aegisqda-segment-index-v1", "aegisqda-segment-search-v1", "aegisqda-analyst-dissent-v1",
    "aegisqda-offline-verification-v1", "aegisqda-detector-inventory-v1",
    "aegisqda-review-plan-v1",
])
def test_renamed_runtime_json_schema_is_blocked_anywhere(guard: ModuleType, schema: str) -> None:
    content = json.dumps({"schema": schema, "memo": "Synthetic protected research note."}).encode()
    entry = guard.StagedEntry("misc/renamed-private-export.bin", content)
    result = guard.validate_staged([entry], None)
    assert result.violation_counts == {"RUNTIME_ARTIFACT_SCHEMA": 1}
    assert "renamed-private-export" not in json.dumps(result.public_dict())
    assert "Synthetic protected" not in json.dumps(result.public_dict())


@pytest.mark.parametrize("schema", [
    "aegisqda-synthetic-source-registry-v1", "aegisqda-synthetic-interview-corpus-v2",
    "aegisqda-synthetic-annotation-manifest-v1", "aegisqda-infrastructure-attestation-v1",
    "aegisqda-model-manifest-v1", "aegisqda-roles-v1",
])
def test_synthetic_manifests_and_governance_templates_remain_allowed(guard: ModuleType, schema: str) -> None:
    entry = guard.StagedEntry("governance/hand-authored.example.json", json.dumps({"schema": schema}).encode())
    assert guard.validate_staged([entry], None).ok


def test_readme_with_a_runtime_schema_example_is_documentation(guard: ModuleType) -> None:
    content = b'# Example\n\n```json\n{"schema":"aegisqda-research-event-v1"}\n```\n'
    assert guard.validate_staged([guard.StagedEntry("README.md", content)], None).ok


@pytest.mark.parametrize("status", ["A", "M", "D", "T"])
def test_pinned_vendor_changes_and_deletions_are_blocked(guard: ModuleType, status: str) -> None:
    entry = guard.StagedEntry("vendor/digqda/README.md", None if status == "D" else b"changed", status)
    assert guard.validate_staged([entry], None).violation_counts == {"PINNED_UPSTREAM_CHANGE": 1}


def test_sensitive_deletions_and_fixture_removals_are_allowed(guard: ModuleType) -> None:
    entries = [
        guard.StagedEntry("sources/interview.txt", None, "D", "000000"),
        guard.StagedEntry("secrets/key.pem", None, "D", "000000"),
        guard.StagedEntry("tests/fixtures/en/retired.srt", None, "D", "000000"),
    ]
    assert guard.validate_staged(entries, None).ok


def test_registered_staged_fixture_matches_path_language_bytes_and_hash(guard: ModuleType) -> None:
    path, content = "tests/fixtures/en/synthetic.txt", b"An invented synthetic discussion.\n"
    result = guard.validate_staged([guard.StagedEntry(path, content)], _registry(path, content))
    assert result.ok and result.checked_count == 1


@pytest.mark.parametrize("mismatch", ["path", "bytes", "language", "hash", "length"])
def test_fixture_mismatches_fail_closed(guard: ModuleType, mismatch: str) -> None:
    path, content = "tests/fixtures/en/synthetic.txt", b"An invented synthetic discussion.\n"
    registry = json.loads(_registry(path, content))
    entry = registry["files"][0]
    if mismatch == "path":
        entry["path"] = "tests/fixtures/en/other.txt"
    elif mismatch == "bytes":
        content += b"Changed."
    elif mismatch == "language":
        entry["language"] = "fr"
    elif mismatch == "hash":
        entry["source_sha256"] = "0" * 64
    elif mismatch == "length":
        entry["source_bytes"] += 1
    result = guard.validate_staged([guard.StagedEntry(path, content)], json.dumps(registry).encode())
    assert not result.ok and result.violation_counts["SYNTHETIC_FIXTURE_MISMATCH"] == 1


def test_staged_registry_takes_precedence_over_worktree_registry(guard: ModuleType) -> None:
    path, content = "tests/fixtures/en/synthetic.txt", b"Invented discussion.\n"
    old_registry = _registry(path, b"Older discussion.\n")
    new_registry = _registry(path, content)
    entries = [guard.StagedEntry(path, content), guard.StagedEntry(guard.REGISTRY_PATH, new_registry)]
    assert guard.validate_staged(entries, old_registry).ok
    entries[1] = guard.StagedEntry(guard.REGISTRY_PATH, old_registry)
    assert not guard.validate_staged(entries, new_registry).ok


@pytest.mark.parametrize("registry", [None, b"not-json", b'{"schema":"wrong","files":[]}'])
def test_missing_or_invalid_fixture_registry_is_blocked(guard: ModuleType, registry: bytes | None) -> None:
    result = guard.validate_staged([guard.StagedEntry("tests/fixtures/en/synthetic.txt", b"synthetic")], registry)
    assert result.violation_counts["INVALID_SYNTHETIC_REGISTRY"] == 1


def test_deleting_registry_never_falls_back_to_worktree_for_a_staged_fixture(guard: ModuleType) -> None:
    path, content = "tests/fixtures/en/synthetic.txt", b"Invented discussion.\n"
    entries = [guard.StagedEntry(path, content), guard.StagedEntry(guard.REGISTRY_PATH, None, "D", "000000")]
    assert not guard.validate_staged(entries, _registry(path, content)).ok


def test_ordinary_code_docs_and_requirements_are_allowed(guard: ModuleType) -> None:
    entries = [
        guard.StagedEntry("src/aegisqda/example.py", b"answer = 42\n"),
        guard.StagedEntry("docs/example.md", b"Synthetic workflow documentation.\n"),
        guard.StagedEntry("requirements.txt", b"pytest\n"),
    ]
    assert guard.validate_staged(entries, None).ok


def test_unregistered_transcript_outside_fixtures_is_blocked(guard: ModuleType) -> None:
    result = guard.validate_staged([guard.StagedEntry("misc/interview.srt", b"invented transcript")], None)
    assert result.violation_counts == {"UNREGISTERED_SOURCE_FILE": 1}


@pytest.mark.parametrize("path", ["../source.txt", "/absolute.txt", "tests//fixtures/en/source.txt", "x\\y.txt"])
def test_noncanonical_paths_are_blocked(guard: ModuleType, path: str) -> None:
    assert guard.validate_staged([guard.StagedEntry(path, b"synthetic")], None).violation_counts == {
        "INVALID_STAGED_PATH": 1,
    }


def test_symlinks_and_unmerged_entries_are_blocked(guard: ModuleType) -> None:
    result = guard.validate_staged([
        guard.StagedEntry("safe_link", b"private-target", "A", "120000"),
        guard.StagedEntry("conflicted.py", None, "U", "000000"),
    ], None)
    assert result.violation_counts == {"NON_REGULAR_STAGED_FILE": 1, "UNRESOLVED_STAGED_ENTRY": 1}


def test_collector_reads_blobs_by_object_hash_and_staged_registry(
    guard: ModuleType, monkeypatch: pytest.MonkeyPatch,
) -> None:
    path, content = "tests/fixtures/en/synthetic.txt", b"Invented discussion.\n"
    registry = _registry(path, content)
    ids = ["a" * 40, "b" * 40]
    raw = (
        f":100644 100644 {'0' * 40} {ids[0]} M\0{path}\0"
        f":100644 100644 {'0' * 40} {ids[1]} M\0{guard.REGISTRY_PATH}\0"
    ).encode()
    objects = dict(zip(ids, [content, registry]))
    calls: list[list[str]] = []

    def fake_git(root: Path, args: list[str]) -> bytes:
        del root
        calls.append(args)
        if args[0] == "diff":
            return raw
        assert args[0] == "cat-file" and args[2] in objects
        return str(len(objects[args[2]])).encode() if args[1] == "-s" else objects[args[2]]

    monkeypatch.setattr(guard, "_git", fake_git)
    entries, selected = guard.collect_staged(ROOT)
    assert selected == registry
    assert guard.validate_staged(entries, selected).ok
    assert all("config" not in call and "add" not in call and "commit" not in call for call in calls)


def test_cli_suppresses_git_failure_details(
    guard: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    def failed() -> None:
        raise OSError("sensitive-name-and-content")

    monkeypatch.setattr(guard, "collect_staged", failed)
    assert guard.main() == 1
    output = capsys.readouterr()
    assert output.err == ""
    assert "sensitive-name-and-content" not in output.out
    assert json.loads(output.out)["violation_counts"] == {"INDEX_INSPECTION_FAILED": 1}
