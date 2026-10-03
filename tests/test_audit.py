"""Runs scanned with a revoked recognizer pack are blocked and found by the audit."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import aegisqda.detection as det
import aegisqda.workflow as wf
from aegisqda.audit import audit_runs
from aegisqda.errors import DownstreamBlocked, IntegrityError
from aegisqda.privacy_gate import validate_release
from aegisqda.safeio import load_json
from aegisqda.workflow import LEDGER_FILE, scan_source, transform_run, write_review

LEGACY_PACK = "aegis-custom-strict-v2"
SECRET = "person@invalid.example"


def _make_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case_id: str,
    *,
    legacy: bool = False,
    release: bool = False,
    blind: bool = False,
) -> Path:
    """Create a run; legacy runs are recorded as scanned with the revoked v2 pack."""
    source = tmp_path / f"{case_id}.txt"
    source.write_text(f"Contact {SECRET} today.\n", encoding="utf-8")
    with monkeypatch.context() as patch:
        if legacy:
            patch.setattr(det, "RECOGNIZER_PACK", LEGACY_PACK)
        if blind:  # a detector that misses the identifier, as v2 did for split names
            patch.setattr(wf, "scan_document", lambda document, language, policy: [])
        run_dir = scan_source(
            source, language="en", case_id=case_id, run_root=tmp_path / "runs", synthetic=True
        )
        if release:
            decisions = [
                {"finding_id": f["finding_id"], "decision": "CONFIRMED"}
                for f in load_json(run_dir / LEDGER_FILE)["findings"]
            ]
            write_review(run_dir, "REVIEWER-001", decisions, [])
            transform_run(run_dir)
    return run_dir


def _verdicts(report: dict[str, object]) -> dict[str, dict[str, object]]:
    runs = report["runs"]
    assert isinstance(runs, list)
    return {str(run["case_id"]): run for run in runs}


def test_current_run_needs_no_action(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _make_run(tmp_path, monkeypatch, "CASE-CURRENT", release=True)
    report, clean = audit_runs(tmp_path / "runs")
    assert clean
    assert _verdicts(report)["CASE-CURRENT"]["verdict"] == "CURRENT"


def test_legacy_release_with_missed_identifier_is_affected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _make_run(tmp_path, monkeypatch, "CASE-LEAK", legacy=True, release=True, blind=True)
    report, clean = audit_runs(tmp_path / "runs")
    entry = _verdicts(report)["CASE-LEAK"]
    assert not clean
    assert entry["verdict"] == "AFFECTED"
    assert entry["unresolved_types"] == ["EMAIL_ADDRESS"]
    assert entry["advisory"] == "AEGIS-2026-001"
    assert SECRET not in json.dumps(report)


def test_legacy_clean_release_reports_no_findings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _make_run(tmp_path, monkeypatch, "CASE-OLD-CLEAN", legacy=True, release=True)
    report, clean = audit_runs(tmp_path / "runs")
    assert clean
    assert _verdicts(report)["CASE-OLD-CLEAN"]["verdict"] == "NO_FINDINGS_UNDER_CURRENT_DETECTOR"


def test_legacy_release_cannot_be_analyzed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = _make_run(tmp_path, monkeypatch, "CASE-OLD-RELEASE", legacy=True, release=True)
    with pytest.raises(DownstreamBlocked, match="AEGIS-2026-001"):
        validate_release(run_dir)


def test_legacy_open_run_requires_rescan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = _make_run(tmp_path, monkeypatch, "CASE-OLD-OPEN", legacy=True)
    report, clean = audit_runs(tmp_path / "runs")
    assert not clean
    assert _verdicts(report)["CASE-OLD-OPEN"]["verdict"] == "RESCAN_REQUIRED"
    with pytest.raises(IntegrityError, match="AEGIS-2026-001"):
        write_review(run_dir, "REVIEWER-001", [], [])
