"""Synthetic overlap planning must preserve current source and review gates."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import aegisqda.review_plan as planner
from aegisqda.detection import Finding
from aegisqda.errors import AegisError, IntegrityError
from aegisqda.manifests import canonical_bytes, seal, sha256_bytes, sha256_file
from aegisqda.review_plan import review_plan
from aegisqda.safeio import load_json
from aegisqda.workflow import scan_source


def _run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    spans: list[tuple[str, int, int]], text: str = "ABCDEFGHIJKLMNOPQRSTUVWXYZ\n",
) -> Path:
    source = tmp_path / "synthetic.txt"
    source.write_bytes(text.encode())

    def findings(document: Any, language: str, policy: Any) -> list[Finding]:
        del language
        return [Finding(
            finding_id=f"F-{index:04d}", entity_type=entity, start=start, end=end,
            score=0.9, recognizer="SYNTHETIC-OVERLAP", action=policy.action_for(entity).value,
            value_sha256=sha256_bytes(document.text[start:end].encode()),
        ) for index, (entity, start, end) in enumerate(spans, 1)]

    # Deterministic invented detections; the actual current loader, source
    # registry, policy/config bindings and filesystem gates remain enabled.
    monkeypatch.setattr("aegisqda.workflow.scan_document", findings)
    return scan_source(
        source, language="en", case_id="CASE-PLAN", run_root=tmp_path / "runs", synthetic=True,
    )


def _reseal(path: Path, changes: dict[str, Any]) -> None:
    value = load_json(path)
    value.pop("integrity_sha256")
    value.update(changes)
    path.write_bytes(canonical_bytes(seal(value)) + b"\n")


def _ledger_change(run: Path, update: dict[str, Any]) -> None:
    findings = load_json(run / "detection-ledger.json")["findings"]
    findings[0].update(update)
    _reseal(run / "detection-ledger.json", {"findings": findings})
    _reseal(run / "detection.json", {"ledger_sha256": sha256_file(run / "detection-ledger.json")})


def _members(report: dict[str, Any]) -> list[list[str]]:
    return [[item["finding_id"] for item in group["findings"]] for group in report["overlap_groups"]]


def test_cross_type_overlap_is_source_free_bound_and_read_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _run(tmp_path, monkeypatch, [("PERSON", 0, 10), ("ORGANIZATION", 4, 15), ("AGE", 20, 23)])
    before = {path.name: path.read_bytes() for path in run.iterdir()}
    report = review_plan(run)
    assert report == review_plan(run)
    assert report["schema"] == "aegisqda-review-plan-v1" and report["state"] == "REVIEW_REQUIRED"
    assert report["detection_sha256"] == sha256_file(run / "detection.json")
    assert _members(report) == [["F-0001", "F-0002"]]
    assert report["overlap_group_count"] == 1 and report["overlapping_finding_count"] == 2
    assert report["singleton_count"] == report["ungrouped_finding_count"] == 1
    assert report["overlap_groups"][0]["findings"] == [
        {"finding_id": "F-0001", "entity_type": "PERSON", "action": "REPLACE_AND_REVIEW"},
        {"finding_id": "F-0002", "entity_type": "ORGANIZATION", "action": "REPLACE_AND_REVIEW"},
    ]
    assert report["decision_authority"] is False and report["release_authorized"] is False
    assert report["transformation_authorized"] is False
    serialized = json.dumps(report)
    assert "ABCDEFGHIJ" not in serialized and str(run) not in serialized
    assert "source.txt" not in serialized and "value_sha256" not in serialized
    assert {path.name: path.read_bytes() for path in run.iterdir()} == before
    assert not (run / "review.json").exists() and not (run / "privacy-release.json").exists()


def test_transitive_overlap_and_separate_components(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _run(tmp_path, monkeypatch, [
        ("PERSON", 0, 5), ("LOCATION", 4, 10), ("ORGANIZATION", 9, 14),
        ("AGE", 19, 22), ("DATE_TIME", 20, 23),
    ])
    report = review_plan(run)
    assert _members(report) == [["F-0001", "F-0002", "F-0003"], ["F-0004", "F-0005"]]
    assert report["finding_count"] == 5 and report["singleton_count"] == 0


def test_adjacent_endpoints_and_content_lines_do_not_overlap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _run(tmp_path, monkeypatch, [
        ("PERSON", 0, 3), ("LOCATION", 3, 5), ("ORGANIZATION", 6, 10),
    ], text="ABCDE\nFGHIJK\n")
    report = review_plan(run)
    assert report["overlap_groups"] == [] and report["singleton_count"] == 3


def test_projected_multiline_mention_uses_real_segments_as_one_finding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _run(tmp_path, monkeypatch, [
        ("PERSON", 2, 10), ("ORGANIZATION", 0, 2), ("EMAIL_ADDRESS", 10, 13),
        ("LOCATION", 3, 4), ("ORGANIZATION", 8, 9),
    ], text="ABCDE\nFGHIJKL\n")
    report = review_plan(run)
    assert _members(report) == [["F-0001", "F-0004", "F-0005"]]
    assert report["overlapping_finding_count"] == 3 and report["singleton_count"] == 2


def test_one_projected_finding_does_not_overlap_itself(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _run(tmp_path, monkeypatch, [("PERSON", 2, 10)], text="ABCDE\nFGHIJKL\n")
    report = review_plan(run)
    assert report["overlap_group_count"] == 0 and report["ungrouped_finding_count"] == 1


def test_empty_ledger_returns_empty_plan(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    report = review_plan(_run(tmp_path, monkeypatch, []))
    assert report["finding_count"] == report["overlap_group_count"] == report["singleton_count"] == 0
    assert report["overlap_groups"] == []


def test_group_id_changes_with_detection_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _run(tmp_path, monkeypatch, [("PERSON", 0, 10), ("LOCATION", 5, 12)])
    before = review_plan(run)
    _reseal(run / "detection.json", {"created_at": "2026-10-03T02:03:04Z"})
    after = review_plan(run)
    assert _members(before) == _members(after)
    assert before["overlap_groups"][0]["group_id"] != after["overlap_groups"][0]["group_id"]


def test_disconnected_atomic_intervals_do_not_create_bounding_envelope_overlap() -> None:
    # Finding 0's envelope would contain finding 1; the actual intervals are
    # disjoint. This protects the sweep contract for projected mention units.
    components = planner._overlap_components([(0, 3, 0), (8, 12, 0), (3, 8, 1)], 2)
    assert components.find(0) != components.find(1)


@pytest.mark.parametrize("change", [
    {"start": -1}, {"start": True}, {"end": 50}, {"end": 0},
    {"segments": [[0, 3], [4, 5]]}, {"value_sha256": "0" * 64},
    {"canonical_value_sha256": "0" * 64},
])
def test_malformed_bounds_or_source_bindings_are_blocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: dict[str, Any],
) -> None:
    run = _run(tmp_path, monkeypatch, [("PERSON", 0, 5)])
    _ledger_change(run, change)
    with pytest.raises(IntegrityError):
        review_plan(run)


@pytest.mark.parametrize("change", [
    {"finding_id": "invented identifying text"}, {"entity_type": "invented identifying text"},
    {"action": "invented identifying text"}, {"action": "BLOCK"},
])
def test_unknown_finding_metadata_is_not_disclosed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: dict[str, Any],
) -> None:
    run = _run(tmp_path, monkeypatch, [("PERSON", 0, 5)])
    _ledger_change(run, change)
    with pytest.raises(IntegrityError) as error:
        review_plan(run)
    assert "identifying" not in str(error.value)


@pytest.mark.parametrize("change", ["legacy", "missing_detector", "real_data", "registration", "config", "language"])
def test_existing_current_synthetic_and_control_gates_remain_enforced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str,
) -> None:
    run = _run(tmp_path, monkeypatch, [("PERSON", 0, 5)])
    detection = load_json(run / "detection.json")
    if change == "legacy":
        detection["detector"]["recognizer_pack"] = "aegis-custom-strict-v2"
        changes = {"detector": detection["detector"]}
    else:
        changes = {
            "missing_detector": {"detector": None}, "real_data": {"synthetic_only": False},
            "registration": {"source_registration": None}, "config": {"config_sha256": "0" * 64},
            "language": {"language": "unknown"},
        }[change]
    _reseal(run / "detection.json", changes)
    with pytest.raises(AegisError) as error:
        review_plan(run)
    assert str(run) not in str(error.value)


def test_newline_gap_is_not_a_valid_finding_even_inside_a_mention_envelope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _run(tmp_path, monkeypatch, [("PERSON", 2, 10), ("LOCATION", 5, 6)], text="ABCDE\nFGHIJKL\n")
    with pytest.raises(IntegrityError, match="content span"):
        review_plan(run)


@pytest.mark.parametrize("target", ["source.txt", "detection.json", "detection-ledger.json"])
def test_changes_after_existing_loader_are_blocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, target: str,
) -> None:
    run = _run(tmp_path, monkeypatch, [("PERSON", 0, 5), ("LOCATION", 4, 10)])
    original = planner._load_detection

    def changed(path: Path):  # type: ignore[no-untyped-def]
        loaded = original(path)
        (run / target).write_bytes(b"CHANGED SYNTHETIC INPUT")
        return loaded

    monkeypatch.setattr(planner, "_load_detection", changed)
    with pytest.raises(IntegrityError, match="changed"):
        review_plan(run)


def test_source_change_before_planning_is_blocked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    run = _run(tmp_path, monkeypatch, [("PERSON", 0, 5)])
    (run / "source.txt").write_bytes(b"CHANGED SYNTHETIC INPUT")
    with pytest.raises(IntegrityError, match="source changed"):
        review_plan(run)


def test_missing_artifact_failure_is_source_free(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    run = _run(tmp_path, monkeypatch, [])
    (run / "detection-ledger.json").unlink()
    with pytest.raises(AegisError) as error:
        review_plan(run)
    assert str(run) not in str(error.value) and "synthetic.txt" not in str(error.value)


def test_duplicate_json_keys_are_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    run = _run(tmp_path, monkeypatch, [])
    path = run / "detection.json"
    raw = path.read_bytes()
    assert raw.startswith(b"{")
    path.write_bytes(b'{"synthetic_only":true,' + raw[1:])
    with pytest.raises(IntegrityError, match="duplicate JSON keys"):
        review_plan(run)
