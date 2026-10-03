"""Synthetic source/event alignment tests for read-only protected research queries."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import aegisqda.workbench_queries as queries
from aegisqda.errors import DownstreamBlocked, IntegrityError, ReviewRequired
from aegisqda.formats.document import parse_document_bytes
from aegisqda.manifests import canonical_bytes, seal, sha256_bytes
from aegisqda.safeio import load_json
from aegisqda.workbench import apply_code, declare_method, define_code, write_memo
from aegisqda.workbench_queries import analyst_dissent, list_segments, read_segment, search_segments
from aegisqda.workflow import scan_source, transform_run, write_review

SAFE_TEXT = "We learned together.\n\nLater we tried another approach.\n"


@pytest.fixture(autouse=True)
def deterministic_privacy_scans(monkeypatch: pytest.MonkeyPatch) -> None:
    # Every gate and byte/event binding runs. Only NER is replaced so the safe,
    # invented material remains independent of optional model installations.
    monkeypatch.setattr("aegisqda.workflow.scan_document", lambda *args: [])
    monkeypatch.setattr("aegisqda.privacy_gate.scan_document", lambda *args: [])


def _release(tmp_path: Path, text: str = SAFE_TEXT, *, kind: str = "txt", method: bool = True) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    source = tmp_path / f"synthetic.{kind}"
    source.write_bytes(text.encode())
    run_dir = scan_source(
        source, language="en", case_id="CASE-QUERIES", run_root=tmp_path / "runs", synthetic=True,
    )
    write_review(run_dir, "REVIEWER-TEST", [])
    transform_run(run_dir)
    if method:
        declare_method(run_dir, "ANALYST-001", "REFLEXIVE_THEMATIC")
    return run_dir


def _snapshot(run_dir: Path) -> dict[str, bytes]:
    return {path.relative_to(run_dir).as_posix(): path.read_bytes() for path in run_dir.rglob("*") if path.is_file()}


def _reseal(path: Path, changes: dict[str, object]) -> None:
    payload = load_json(path)
    payload.pop("integrity_sha256")
    payload.update(changes)
    path.write_bytes(canonical_bytes(seal(payload)))


def test_segment_index_is_source_bound_stable_and_source_free(tmp_path: Path) -> None:
    run_dir = _release(tmp_path)
    before = _snapshot(run_dir)
    first = list_segments(run_dir)
    assert first == list_segments(run_dir)
    assert first["segment_count"] == 2
    assert [(item["start"], item["end"]) for item in first["segments"]] == [(0, 20), (22, 54)]
    assert first["segments"][0]["evidence_sha256"] == sha256_bytes(b"We learned together.")
    assert first["segments"][0]["character_count"] == 20
    assert SAFE_TEXT not in json.dumps(first) and "We learned" not in json.dumps(first)
    assert "text" not in first["segments"][0] and "quote" not in first["segments"][0]
    assert _snapshot(run_dir) == before


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_srt_segments_exclude_structure_and_preserve_exact_offsets(tmp_path: Path, newline: str) -> None:
    text = newline.join([
        "1", "00:00:01,000 --> 00:00:03,000", "We learned together.", "A shared approach.", "",
        "2", "00:00:04,000 --> 00:00:06,000", "Later we tried another approach.", "",
    ])
    run_dir = _release(tmp_path, text, kind="srt")
    index = list_segments(run_dir)
    assert index["segment_count"] == 3
    document = parse_document_bytes(text.encode(), ".srt")
    assert [(item["start"], item["end"]) for item in index["segments"]] == [
        (region.start, region.end) for region in document.regions
    ]
    assert [read_segment(run_dir, item["segment_id"]) for item in index["segments"]] == [
        "We learned together.", "A shared approach.", "Later we tried another approach.",
    ]
    assert search_segments(run_dir, "00:00")["match_count"] == 0
    assert search_segments(run_dir, "1")["match_count"] == 0


def test_unicode_offsets_are_characters_and_search_is_casefold_literal(tmp_path: Path) -> None:
    text = "A shared café approach.\nThe Straße is discussed in invented terms.\n"
    run_dir = _release(tmp_path, text)
    index = list_segments(run_dir)
    assert index["segments"][1]["start"] == len("A shared café approach.\n")
    result = search_segments(run_dir, "STRASSE")
    assert result["match_count"] == 1
    assert result["segments"] == [index["segments"][1]]
    assert "STRASSE" not in json.dumps(result) and "Straße" not in json.dumps(result)
    assert search_segments(run_dir, ".*")["match_count"] == 0


def test_read_segment_is_explicit_exact_and_creates_no_export(tmp_path: Path) -> None:
    run_dir = _release(tmp_path)
    index = list_segments(run_dir)
    before = _snapshot(run_dir)
    assert read_segment(run_dir, index["segments"][0]["segment_id"]) == "We learned together."
    assert _snapshot(run_dir) == before
    with pytest.raises(ReviewRequired, match="unknown") as error:
        read_segment(run_dir, "SEG-" + "0" * 48)
    assert "We learned" not in str(error.value)


def test_segment_ids_cannot_be_reused_for_another_released_run(tmp_path: Path) -> None:
    run_a = _release(tmp_path / "a")
    run_b = _release(tmp_path / "b")
    id_a = list_segments(run_a)["segments"][0]["segment_id"]
    id_b = list_segments(run_b)["segments"][0]["segment_id"]
    assert id_a != id_b
    with pytest.raises(ReviewRequired, match="unknown"):
        read_segment(run_b, id_a)


@pytest.mark.parametrize("api", ["list", "search", "read", "dissent"])
def test_all_queries_require_a_declared_method(tmp_path: Path, api: str) -> None:
    run_dir = _release(tmp_path, method=False)
    calls = {
        "list": lambda: list_segments(run_dir), "search": lambda: search_segments(run_dir, "learned"),
        "read": lambda: read_segment(run_dir, "SEG-" + "0" * 48), "dissent": lambda: analyst_dissent(run_dir),
    }
    with pytest.raises(ReviewRequired, match="declare"):
        calls[api]()
    assert not (run_dir / "research").exists()


@pytest.mark.parametrize("query", ["", "  ", "x" * 2001, "invented\x00query"])
def test_search_rejects_invalid_query_without_echoing_it(tmp_path: Path, query: str) -> None:
    run_dir = _release(tmp_path)
    with pytest.raises(ReviewRequired, match="bounded") as error:
        search_segments(run_dir, query)
    assert "invented" not in str(error.value)


@pytest.mark.parametrize("target", ["source.txt", "transformed.txt"])
def test_queries_block_when_released_source_bytes_change(tmp_path: Path, target: str) -> None:
    run_dir = _release(tmp_path)
    segment_id = list_segments(run_dir)["segments"][0]["segment_id"]
    (run_dir / target).write_text("Changed protected synthetic content.\n")
    for call in (lambda: list_segments(run_dir), lambda: search_segments(run_dir, "learned"),
                 lambda: read_segment(run_dir, segment_id), lambda: analyst_dissent(run_dir)):
        with pytest.raises(DownstreamBlocked):
            call()


def test_queries_reject_a_source_change_after_the_existing_context_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = _release(tmp_path)
    original = queries._load

    def changed_after_load(run: Path):  # type: ignore[no-untyped-def]
        result = original(run)
        (run / "transformed.txt").write_text("Changed protected synthetic content.\n")
        return result

    monkeypatch.setattr(queries, "_load", changed_after_load)
    with pytest.raises(IntegrityError, match="changed"):
        list_segments(run_dir)


def test_queries_reject_an_event_change_after_the_existing_context_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = _release(tmp_path)
    original = queries._load

    def changed_after_load(run: Path):  # type: ignore[no-untyped-def]
        result = original(run)
        _reseal(run / "research" / "event-000001.json", {"analyst_id": "ANALYST-002"})
        return result

    monkeypatch.setattr(queries, "_load", changed_after_load)
    with pytest.raises(IntegrityError, match="snapshot changed"):
        analyst_dissent(run_dir)


@pytest.mark.parametrize("change", ["legacy_detector", "real_data"])
def test_queries_keep_current_detector_and_synthetic_privacy_gates(tmp_path: Path, change: str) -> None:
    run_dir = _release(tmp_path)
    detection = load_json(run_dir / "detection.json")
    if change == "legacy_detector":
        detector = detection["detector"]
        detector["recognizer_pack"] = "aegis-custom-strict-v2"
        _reseal(run_dir / "detection.json", {"detector": detector})
    else:
        _reseal(run_dir / "detection.json", {"synthetic_only": False})
    with pytest.raises(DownstreamBlocked):
        list_segments(run_dir)


def test_queries_reject_resealed_event_chain_changes(tmp_path: Path) -> None:
    run_dir = _release(tmp_path)
    define_code(run_dir, "ANALYST-001", "CODE-A", "Shared learning", "A synthetic learning definition")
    _reseal(run_dir / "research" / "event-000001.json", {"method": "CODEBOOK"})
    with pytest.raises(IntegrityError, match="provenance"):
        list_segments(run_dir)


def _codes(run_dir: Path) -> None:
    define_code(run_dir, "ANALYST-001", "CODE-A", "Shared learning", "A synthetic learning definition")
    define_code(run_dir, "ANALYST-002", "CODE-B", "Changed approach", "A synthetic approach definition")


def test_dissent_compares_exact_evidence_and_deduplicated_explicit_analyst_code_sets(tmp_path: Path) -> None:
    run_dir = _release(tmp_path)
    _codes(run_dir)
    apply_code(run_dir, "ANALYST-001", "CODE-A", 3, 10, "A synthetic first interpretation")
    apply_code(run_dir, "ANALYST-001", "CODE-A", 3, 10, "A duplicate synthetic interpretation")
    apply_code(run_dir, "ANALYST-002", "CODE-A", 3, 10, "A shared synthetic interpretation")
    apply_code(run_dir, "ANALYST-002", "CODE-B", 3, 10, "A different synthetic interpretation")
    write_memo(run_dir, "ANALYST-003", 3, 10, "A protected reflexive memo for discussion.")
    before = _snapshot(run_dir)
    report = analyst_dissent(run_dir)
    assert report["comparable_span_count"] == 1 and report["dissent_span_count"] == 1
    assert report["groups"] == [{
        "start": 3, "end": 10, "evidence_sha256": sha256_bytes(b"learned"),
        "analysts": [{"analyst_id": "ANALYST-001", "code_ids": ["CODE-A"]},
                     {"analyst_id": "ANALYST-002", "code_ids": ["CODE-A", "CODE-B"]}],
    }]
    assert "learned" not in json.dumps(report) and "Shared learning" not in json.dumps(report)
    assert "protected reflexive" not in json.dumps(report) and "ANALYST-003" not in json.dumps(report)
    assert "kappa" not in report and "reliability" not in report
    assert report["state"] == "METHODOLOGICAL_REVIEW_REQUIRED"
    assert _snapshot(run_dir) == before


def test_equal_sets_different_order_and_duplicate_events_do_not_create_dissent(tmp_path: Path) -> None:
    run_dir = _release(tmp_path)
    _codes(run_dir)
    for analyst, code in ("ANALYST-001", "CODE-A"), ("ANALYST-001", "CODE-B"), ("ANALYST-002", "CODE-B"), ("ANALYST-002", "CODE-A"), ("ANALYST-002", "CODE-A"):
        apply_code(run_dir, analyst, code, 3, 10, "A synthetic explicit interpretation")
    report = analyst_dissent(run_dir)
    assert report["comparable_span_count"] == 1 and report["dissent_span_count"] == 0
    assert report["groups"] == []


def test_missing_coding_and_different_overlapping_spans_are_not_inferred_disagreement(tmp_path: Path) -> None:
    run_dir = _release(tmp_path)
    _codes(run_dir)
    apply_code(run_dir, "ANALYST-001", "CODE-A", 3, 10, "A synthetic explicit interpretation")
    apply_code(run_dir, "ANALYST-002", "CODE-B", 3, 12, "A synthetic wider interpretation")
    write_memo(run_dir, "ANALYST-003", 3, 10, "A protected reflexive memo for discussion.")
    report = analyst_dissent(run_dir)
    assert report["comparable_span_count"] == 0 and report["dissent_span_count"] == 0


def test_identical_text_at_different_positions_is_not_the_same_evidence_span(tmp_path: Path) -> None:
    text = "We learned together.\nWe learned together.\n"
    run_dir = _release(tmp_path, text)
    _codes(run_dir)
    apply_code(run_dir, "ANALYST-001", "CODE-A", 3, 10, "A synthetic first interpretation")
    second = len("We learned together.\n")
    apply_code(run_dir, "ANALYST-002", "CODE-B", second + 3, second + 10, "A synthetic later interpretation")
    assert analyst_dissent(run_dir)["comparable_span_count"] == 0
