"""DH CLI commands must preserve source-free defaults and protected access."""

import json
from pathlib import Path

import pytest

from aegisqda.cli import main
from aegisqda.safeio import load_json
from aegisqda.workbench import apply_code, declare_method, define_code
from aegisqda.workflow import scan_source, transform_run, write_review


@pytest.fixture
def research_run(fixture_root: Path, tmp_path: Path) -> Path:
    run = scan_source(
        fixture_root / "en/safe.txt", language="en", case_id="SYNTH-CLI-001",
        run_root=tmp_path.resolve() / "runs", synthetic=True,
    )
    assert load_json(run / "detection-ledger.json")["findings"] == []
    write_review(run, "SYNTH-REVIEWER", [])
    transform_run(run)
    declare_method(run, "ANALYST-001", "CODEBOOK")
    define_code(run, "ANALYST-001", "CODE-A-V1", "Shared practice", "A documented shared practice.")
    define_code(run, "ANALYST-001", "CODE-B-V1", "Another reading", "A distinct possible reading.")
    apply_code(run, "ANALYST-001", "CODE-A-V1", 0, 10, "The first explicit reading.")
    apply_code(run, "ANALYST-002", "CODE-B-V1", 0, 10, "The alternative explicit reading.")
    return run


def test_cli_segments_search_and_explicit_evidence_access(
    research_run: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    source = (research_run / "transformed.txt").read_text().strip()
    assert main(["qda-segments", str(research_run)]) == 0
    raw = capsys.readouterr().out
    index = json.loads(raw)
    assert index["segment_count"] == 1
    assert source not in raw
    segment = index["segments"][0]
    monkeypatch.setattr("builtins.input", lambda prompt: "gardening")
    assert main(["qda-search", str(research_run)]) == 0
    raw = capsys.readouterr().out
    assert json.loads(raw)["match_count"] == 1
    assert "gardening" not in raw
    assert source not in raw
    assert main(["qda-evidence", str(research_run), "--segment-id", segment["segment_id"]]) == 0
    raw = capsys.readouterr().out
    assert "PROTECTED LOCAL EVIDENCE" in raw
    assert source in raw


def test_cli_dissent_and_offline_verification_stay_descriptive(
    research_run: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["qda-dissent", str(research_run)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["dissent_span_count"] == 1
    assert {entry["analyst_id"] for entry in report["groups"][0]["analysts"]} == {"ANALYST-001", "ANALYST-002"}
    assert main(["verify", str(research_run)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "SYNTHETIC_VERIFIED"
    assert report["network_used"] is False
    assert report["release_authorization"] is False
    assert report["real_data_authorization"] is False


def test_cli_overlap_plan_is_readonly_and_contains_no_source_text(
    research_run: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    before = {path.relative_to(research_run): path.read_bytes() for path in research_run.rglob("*") if path.is_file()}
    assert main(["review-plan", str(research_run)]) == 0
    raw = capsys.readouterr().out
    report = json.loads(raw)
    assert report["state"] == "REVIEW_REQUIRED"
    assert report["finding_count"] == 0
    assert report["overlap_group_count"] == 0
    assert (research_run / "transformed.txt").read_text().strip() not in raw
    assert str(research_run) not in raw
    assert {path.relative_to(research_run): path.read_bytes() for path in research_run.rglob("*") if path.is_file()} == before


def test_cli_workspace_registration_and_source_free_matrix(
    research_run: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    workspace = tmp_path.resolve() / "workspace"
    assert main(["qda-workspace-init", str(workspace)]) == 0
    assert "WORKSPACE_CREATED" in capsys.readouterr().out
    assert main(["qda-workspace-add", str(workspace), str(research_run), "--case-id", "CASE-CLI-001"]) == 0
    assert "CASE_REGISTERED" in capsys.readouterr().out
    assert main(["qda-matrix", str(workspace)]) == 0
    raw = capsys.readouterr().out
    report = json.loads(raw)
    assert report["case_count"] == 1
    assert report["matrix"] == [{"case_id": "CASE-CLI-001", "coding_counts": {"CODE-A-V1": 1, "CODE-B-V1": 1}}]
    assert "Shared practice" not in raw
    assert "alternative explicit" not in raw
    assert str(research_run) not in raw


def test_cli_blocked_verifier_and_missing_method_have_nonzero_exit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["verify", str(tmp_path.resolve())]) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "BLOCKED"
    assert main(["qda-segments", str(tmp_path.resolve())]) == 2
    assert "BLOCKED" in capsys.readouterr().err
