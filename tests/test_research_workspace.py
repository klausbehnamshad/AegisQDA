"""Synthetic release/history bindings and source-free multi-case comparisons."""

from __future__ import annotations

import json
import stat
from pathlib import Path
from typing import Callable

import pytest

from aegisqda.config import ROOT
from aegisqda.errors import AegisError, BoundaryError, IntegrityError, ReviewRequired
from aegisqda.manifests import canonical_bytes, seal, sha256_file
from aegisqda.research_workspace import (
    ASSURANCE, CASE_SCHEMA, SCHEMA, SUMMARY_SCHEMA, add_case, create_workspace, workspace_summary,
)
from aegisqda.safeio import load_json
from aegisqda.workbench import apply_code, declare_method, define_code, write_memo
from aegisqda.workflow import scan_source, transform_run, write_review


@pytest.fixture
def released_factory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Callable[..., Path]:
    # Actual release replay and workbench validation run, with no model inference.
    # Detection is patched only for this safe synthetic initial input scan.
    monkeypatch.setattr("aegisqda.workflow.scan_document", lambda *args: [])
    root = tmp_path.resolve()
    sequence = 0

    def make(*, method: str | None = "CODEBOOK") -> Path:
        nonlocal sequence
        sequence += 1
        source = root / f"synthetic-{sequence}.txt"
        source.write_text("We learned together and tried a different approach.\n")
        run = scan_source(
            source, language="en", case_id=f"INPUT-{sequence:03d}",
            run_root=root / "runs", synthetic=True,
        )
        write_review(run, "REVIEWER-TEST", [])
        transform_run(run)
        if method is not None:
            declare_method(run, "ANALYST-001", method)
        return run

    return make


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    return create_workspace(tmp_path.resolve() / "research-workspace")


def _reseal(path: Path, changes: dict[str, object], *, remove: str | None = None) -> None:
    value = load_json(path)
    value.pop("integrity_sha256")
    if remove is not None:
        value.pop(remove)
    value.update(changes)
    path.write_bytes(canonical_bytes(seal(value)) + b"\n")


def _code(run: Path, code_id: str = "CODE-CARE", *, definition: str = "Private definition marker",
          parent_id: str | None = None, label: str = "Private label marker") -> Path:
    return define_code(run, "ANALYST-001", code_id, label, definition, parent_id)


def test_empty_workspace_is_protected_and_honest(workspace: Path) -> None:
    manifest = load_json(workspace / "workspace.json")
    assert manifest["schema"] == SCHEMA
    assert manifest["synthetic_only"] is True
    assert manifest["assurance"] == ASSURANCE
    for directory in (workspace, workspace / "cases"):
        assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    assert stat.S_IMODE((workspace / "workspace.json").stat().st_mode) == 0o600
    summary = workspace_summary(workspace)
    assert summary["schema"] == SUMMARY_SCHEMA
    assert summary["state"] == "METHODOLOGICAL_REVIEW_REQUIRED"
    assert summary["case_count"] == summary["code_count"] == 0
    assert summary["method"] is None
    assert summary["codes"] == summary["matrix"] == []
    assert "Unkeyed" in summary["notice"]


def test_multi_case_matrix_deduplicates_exact_spans_and_keeps_private_text_local(
    workspace: Path, released_factory: Callable[..., Path],
) -> None:
    first, second = released_factory(), released_factory()
    _code(first)
    _code(second)
    _code(first, "CODE-AGENCY")
    apply_code(first, "ANALYST-001", "CODE-CARE", 3, 19, "Private rationale marker")
    apply_code(first, "ANALYST-002", "CODE-CARE", 3, 19, "Another private rationale")
    apply_code(second, "ANALYST-001", "CODE-CARE", 3, 19, "Private rationale marker")
    apply_code(second, "ANALYST-001", "CODE-CARE", 20, 29, "Private rationale marker")
    write_memo(first, "ANALYST-001", 3, 19, "Private memo marker", "CODE-CARE")
    path1 = add_case(workspace, first, "CASE-ALPHA")
    path2 = add_case(workspace, second, "CASE-BETA")
    registered = load_json(path1)
    assert registered["schema"] == CASE_SCHEMA
    assert registered["privacy_release_sha256"] == sha256_file(first / "privacy-release.json")
    assert registered["workspace_manifest_sha256"] == sha256_file(workspace / "workspace.json")
    assert registered["run_dir"] == str(first)
    assert load_json(path2)["previous_registration_sha256"] == sha256_file(path1)
    assert stat.S_IMODE(path1.stat().st_mode) == stat.S_IMODE(path2.stat().st_mode) == 0o600
    summary = workspace_summary(workspace)
    assert summary["method"] == "CODEBOOK"
    assert summary["case_count"] == summary["code_count"] == 2
    assert summary["codes"] == ["CODE-AGENCY", "CODE-CARE"]
    assert summary["matrix"] == [
        {"case_id": "CASE-ALPHA", "coding_counts": {"CODE-AGENCY": 0, "CODE-CARE": 1}},
        {"case_id": "CASE-BETA", "coding_counts": {"CODE-AGENCY": 0, "CODE-CARE": 2}},
    ]
    serialized = json.dumps(summary)
    for private in ("learned", "Private", str(first), str(second), "ANALYST-001", "INPUT-001"):
        assert private not in serialized
    assert {path.name for path in workspace.iterdir()} == {"workspace.json", "cases"}


def test_live_appends_are_allowed_without_rewriting_registration(
    workspace: Path, released_factory: Callable[..., Path],
) -> None:
    run = released_factory()
    _code(run)
    path = add_case(workspace, run, "CASE-ALPHA")
    original = path.read_bytes()
    apply_code(run, "ANALYST-001", "CODE-CARE", 3, 19, "A synthetic interpretation")
    write_memo(run, "ANALYST-001", 3, 19, "An appended private memo")
    summary = workspace_summary(workspace)
    assert summary["matrix"][0]["coding_counts"] == {"CODE-CARE": 1}
    assert path.read_bytes() == original


def test_case_id_and_run_cannot_be_registered_twice_or_rebound(
    workspace: Path, released_factory: Callable[..., Path],
) -> None:
    first, second = released_factory(), released_factory()
    path = add_case(workspace, first, "CASE-ALPHA")
    original = path.read_bytes()
    with pytest.raises(ReviewRequired, match="already registered"):
        add_case(workspace, second, "CASE-ALPHA")
    with pytest.raises(ReviewRequired, match="already registered"):
        add_case(workspace, first, "CASE-BETA")
    assert path.read_bytes() == original
    assert len(list((workspace / "cases").iterdir())) == 1


def test_registration_requires_a_declared_method(
    workspace: Path, released_factory: Callable[..., Path],
) -> None:
    with pytest.raises(ReviewRequired, match="declare"):
        add_case(workspace, released_factory(method=None), "CASE-ALPHA")
    assert list((workspace / "cases").iterdir()) == []


def test_incompatible_methods_block_registration(
    workspace: Path, released_factory: Callable[..., Path],
) -> None:
    add_case(workspace, released_factory(method="CODEBOOK"), "CASE-ALPHA")
    with pytest.raises(ReviewRequired, match="incompatible"):
        add_case(workspace, released_factory(method="GROUNDED_THEORY"), "CASE-BETA")
    assert len(list((workspace / "cases").iterdir())) == 1


@pytest.mark.parametrize("conflict", ["definition", "label", "hierarchy"])
def test_shared_code_ids_cannot_silently_change_semantics(
    workspace: Path, released_factory: Callable[..., Path], conflict: str,
) -> None:
    first, second = released_factory(), released_factory()
    _code(first)
    _code(second, "CODE-PARENT")
    kwargs = {
        "definition": "Conflicting private definition" if conflict == "definition" else "Private definition marker",
        "label": "Conflicting private label" if conflict == "label" else "Private label marker",
        "parent_id": "CODE-PARENT" if conflict == "hierarchy" else None,
    }
    _code(second, **kwargs)
    add_case(workspace, first, "CASE-ALPHA")
    with pytest.raises(ReviewRequired, match="conflicting"):
        add_case(workspace, second, "CASE-BETA")


def test_later_shared_code_conflict_blocks_matrix(
    workspace: Path, released_factory: Callable[..., Path],
) -> None:
    first, second = released_factory(), released_factory()
    add_case(workspace, first, "CASE-ALPHA")
    add_case(workspace, second, "CASE-BETA")
    _code(first)
    _code(second, definition="A contradictory private definition")
    with pytest.raises(ReviewRequired, match="conflicting"):
        workspace_summary(workspace)


def test_exact_release_hash_blocks_a_resealed_stale_registration(
    workspace: Path, released_factory: Callable[..., Path],
) -> None:
    run = released_factory()
    add_case(workspace, run, "CASE-ALPHA")
    # Additional metadata can leave the privacy gate itself structurally valid;
    # the workspace nevertheless requires the exact registered release bytes.
    _reseal(run / "privacy-release.json", {"extra_metadata": "changed"})
    with pytest.raises(IntegrityError, match="registered privacy release changed"):
        workspace_summary(workspace)


def test_registration_cannot_refer_to_another_run_with_the_old_release_binding(
    workspace: Path, released_factory: Callable[..., Path],
) -> None:
    first, second = released_factory(), released_factory()
    path = add_case(workspace, first, "CASE-ALPHA")
    _reseal(path, {"run_dir": str(second)})
    with pytest.raises(IntegrityError, match="registered privacy release changed"):
        workspace_summary(workspace)


@pytest.mark.parametrize("artifact", ["source.txt", "transformed.txt"])
def test_every_matrix_read_revalidates_released_sources(
    workspace: Path, released_factory: Callable[..., Path], artifact: str,
) -> None:
    run = released_factory()
    add_case(workspace, run, "CASE-ALPHA")
    (run / artifact).write_text("Changed synthetic material.\n")
    with pytest.raises(AegisError, match="hash revalidation"):
        workspace_summary(workspace)


def test_non_synthetic_release_is_blocked_even_after_resealing(
    workspace: Path, released_factory: Callable[..., Path],
) -> None:
    run = released_factory()
    _reseal(run / "detection.json", {"synthetic_only": False})
    with pytest.raises(AegisError, match="real-data authorization"):
        add_case(workspace, run, "CASE-ALPHA")


@pytest.mark.parametrize("change", ["rewrite", "truncate"])
def test_registered_event_prefix_cannot_be_rewritten_or_truncated(
    workspace: Path, released_factory: Callable[..., Path], change: str,
) -> None:
    run = released_factory()
    event = _code(run)
    add_case(workspace, run, "CASE-ALPHA")
    if change == "rewrite":
        # It is the chain head, so the workbench alone cannot observe an ancestor
        # mismatch. The workspace's previously bound prefix detects the rewrite.
        _reseal(event, {"definition": "A rewritten private definition"})
    else:
        event.unlink()
    with pytest.raises(IntegrityError, match="rewritten or truncated"):
        workspace_summary(workspace)


@pytest.mark.parametrize("changes", [
    {"schema": "wrong"}, {"sequence": True}, {"research_prefix_count": True},
    {"research_prefix_count": 0}, {"privacy_release_sha256": "a" * 63},
    {"research_prefix_head_sha256": None}, {"method": None}, {"run_dir": None},
    {"synthetic_only": 1}, {"assurance": "TRUSTED"}, {"created_at": "not-a-date"},
    {"unknown_field": "not allowed"}, {"case_id": None},
])
def test_malformed_resealed_registration_is_rejected(
    workspace: Path, released_factory: Callable[..., Path], changes: dict[str, object],
) -> None:
    path = add_case(workspace, released_factory(), "CASE-ALPHA")
    _reseal(path, changes)
    with pytest.raises(AegisError):
        workspace_summary(workspace)


@pytest.mark.parametrize("changes", [
    {"schema": "wrong"}, {"synthetic_only": False}, {"assurance": "TRUSTED"},
    {"created_at": "2026-01-01"}, {"unknown_field": "not allowed"},
])
def test_malformed_resealed_workspace_manifest_is_rejected(
    workspace: Path, changes: dict[str, object],
) -> None:
    _reseal(workspace / "workspace.json", changes)
    with pytest.raises(IntegrityError, match="manifest contract"):
        workspace_summary(workspace)


def test_registration_chain_detects_an_edited_ancestor(
    workspace: Path, released_factory: Callable[..., Path],
) -> None:
    first = add_case(workspace, released_factory(), "CASE-ALPHA")
    add_case(workspace, released_factory(), "CASE-BETA")
    _reseal(first, {"case_id": "CASE-CHANGED"})
    with pytest.raises(IntegrityError, match="provenance"):
        workspace_summary(workspace)


@pytest.mark.parametrize("tamper", ["seal", "missing", "gap", "foreign"])
def test_corrupt_or_incomplete_registration_artifacts_fail_closed(
    workspace: Path, released_factory: Callable[..., Path], tamper: str,
) -> None:
    path = add_case(workspace, released_factory(), "CASE-ALPHA")
    if tamper == "seal":
        value = load_json(path)
        value["case_id"] = "CASE-CHANGED"
        path.write_bytes(canonical_bytes(value))
    elif tamper == "missing":
        (workspace / "workspace.json").unlink()
    elif tamper == "gap":
        path.rename(path.with_name("case-000002.json"))
    else:
        (workspace / "cases" / "notes.txt").write_text("Foreign file")
    with pytest.raises(AegisError):
        workspace_summary(workspace)


@pytest.mark.parametrize("case_id", [None, True, "../CASE", "ab", "with spaces"])
def test_opaque_case_id_is_required(
    workspace: Path, released_factory: Callable[..., Path], case_id: object,
) -> None:
    with pytest.raises(AegisError, match="id"):
        add_case(workspace, released_factory(), case_id)  # type: ignore[arg-type]


def test_initialization_never_overwrites_existing_workspace(workspace: Path) -> None:
    original = (workspace / "workspace.json").read_bytes()
    with pytest.raises(IntegrityError, match="new or empty"):
        create_workspace(workspace)
    assert (workspace / "workspace.json").read_bytes() == original


def test_unsafe_workspace_paths_are_rejected_before_creation(tmp_path: Path) -> None:
    root = tmp_path.resolve()
    for path in (ROOT / "forbidden-workspace", root / "Dropbox" / "workspace"):
        with pytest.raises(BoundaryError):
            create_workspace(path)
        assert not path.exists()
    other_git = root / "other-project"
    other_git.mkdir()
    (other_git / ".git").mkdir()
    with pytest.raises(BoundaryError, match="outside Git"):
        create_workspace(other_git / "workspace")
    assert not (other_git / "workspace").exists()


def test_symlinks_including_broken_symlinks_are_rejected(
    workspace: Path, released_factory: Callable[..., Path], tmp_path: Path,
) -> None:
    root = tmp_path.resolve()
    alias = root / "workspace-alias"
    alias.symlink_to(workspace, target_is_directory=True)
    with pytest.raises(BoundaryError, match="symlinks"):
        workspace_summary(alias)
    broken = root / "broken"
    broken.symlink_to(root / "absent")
    with pytest.raises(BoundaryError, match="symlinks"):
        create_workspace(broken / "workspace")
    run_alias = root / "run-alias"
    run_alias.symlink_to(released_factory(), target_is_directory=True)
    with pytest.raises(BoundaryError, match="symlinks"):
        add_case(workspace, run_alias, "CASE-ALPHA")


@pytest.mark.parametrize("artifact", ["root", "manifest", "cases", "registration", "run", "event"])
def test_owner_only_protection_must_remain_in_force(
    workspace: Path, released_factory: Callable[..., Path], artifact: str,
) -> None:
    run = released_factory()
    path = add_case(workspace, run, "CASE-ALPHA")
    changed = {
        "root": workspace, "manifest": workspace / "workspace.json", "cases": workspace / "cases",
        "registration": path, "run": run, "event": run / "research" / "event-000001.json",
    }[artifact]
    changed.chmod(0o755 if changed.is_dir() else 0o644)
    with pytest.raises(BoundaryError, match="owner-only"):
        workspace_summary(workspace)


def test_concurrent_registration_changes_are_detected_before_returning_a_matrix(
    workspace: Path, released_factory: Callable[..., Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    import aegisqda.research_workspace as collection

    path = add_case(workspace, released_factory(), "CASE-ALPHA")
    original = collection._case_state

    def race(*args: object, **kwargs: object) -> dict[str, object]:
        state = original(*args, **kwargs)  # type: ignore[arg-type]
        _reseal(path, {"case_id": "CASE-RACED"})
        return state

    monkeypatch.setattr(collection, "_case_state", race)
    with pytest.raises(IntegrityError, match="changed during validation"):
        workspace_summary(workspace)


@pytest.mark.parametrize("artifact", ["source.txt", "transformed.txt", "detection.json"])
def test_after_load_source_and_detection_changes_fail_closed(
    workspace: Path, released_factory: Callable[..., Path], monkeypatch: pytest.MonkeyPatch,
    artifact: str,
) -> None:
    import aegisqda.research_workspace as collection

    run = released_factory()
    add_case(workspace, run, "CASE-ALPHA")
    original = collection.workbench._load

    def race(path: Path) -> tuple[Path, object, list[dict[str, object]]]:
        result = original(path)
        if artifact == "detection.json":
            _reseal(run / artifact, {"synthetic_only": False})
        else:
            (run / artifact).write_text("Changed synthetic material after validated load.\n")
        return result

    monkeypatch.setattr(collection.workbench, "_load", race)
    with pytest.raises(IntegrityError, match="changed during validation"):
        workspace_summary(workspace)


@pytest.mark.parametrize("artifact", ["workspace.json", "registration"])
def test_duplicate_json_keys_are_rejected_even_when_last_value_has_a_valid_seal(
    workspace: Path, released_factory: Callable[..., Path], artifact: str,
) -> None:
    registration = add_case(workspace, released_factory(), "CASE-ALPHA")
    path = registration if artifact == "registration" else workspace / artifact
    original = path.read_text()
    # Standard json.loads would silently use the valid last schema occurrence,
    # leaving verify_seal successful despite the ambiguous serialized contract.
    path.write_text('{"schema":"forged",' + original[1:])
    with pytest.raises(IntegrityError, match="duplicate JSON keys"):
        workspace_summary(workspace)


@pytest.mark.parametrize("artifact", ["source.txt", "transformed.txt", "privacy-release.json"])
def test_missing_released_artifact_is_a_source_free_gate_failure(
    workspace: Path, released_factory: Callable[..., Path], artifact: str,
) -> None:
    run = released_factory()
    add_case(workspace, run, "CASE-ALPHA")
    (run / artifact).unlink()
    with pytest.raises(AegisError) as caught:
        workspace_summary(workspace)
    assert str(run) not in str(caught.value)


def test_optional_absent_parent_preserves_workbench_hierarchy_semantics(
    workspace: Path, released_factory: Callable[..., Path],
) -> None:
    run = released_factory()
    event = _code(run)
    _reseal(event, {}, remove="parent_id")
    add_case(workspace, run, "CASE-ALPHA")
    assert workspace_summary(workspace)["codes"] == ["CODE-CARE"]
