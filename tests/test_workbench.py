"""Method/evidence gates for human coding, without model calls."""

from pathlib import Path

import pytest

from aegisqda.errors import AegisError, IntegrityError, ReviewRequired
from aegisqda.manifests import canonical_bytes, seal
from aegisqda.safeio import load_json
from aegisqda.workbench import (
    apply_code, declare_method, define_code, research_summary, write_memo,
)
from aegisqda.workflow import scan_source, transform_run, write_review


@pytest.fixture
def released(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    # The real privacy gate and workflow run; a safe rule-only synthetic source
    # makes these tests independent of trained NLP models or Ollama availability.
    monkeypatch.setattr("aegisqda.workflow.scan_document", lambda *args: [])
    source = tmp_path / "safe.txt"
    source.write_text("We learned together and tried a different approach.\n")
    run = scan_source(source, language="en", case_id="CASE-RESEARCH", run_root=tmp_path / "runs", synthetic=True)
    write_review(run, "REVIEWER-TEST", [])
    transform_run(run)
    return run


def test_method_required_and_immutable(released: Path) -> None:
    with pytest.raises(ReviewRequired, match="declare"):
        define_code(released, "ANALYST-001", "CODE-001", "Learning together", "Learning with others")
    declare_method(released, "ANALYST-001", "REFLEXIVE_THEMATIC")
    with pytest.raises(ReviewRequired, match="already"):
        declare_method(released, "ANALYST-001", "CODEBOOK")


def test_codebook_hierarchy_and_evidence_gates(released: Path) -> None:
    declare_method(released, "ANALYST-001", "CODEBOOK")
    with pytest.raises(ReviewRequired, match="parent"):
        define_code(released, "ANALYST-001", "CODE-001", "Learning together", "Learning with others", "MISSING")
    define_code(released, "ANALYST-001", "CODE-001", "Learning together", "Learning with others")
    define_code(released, "ANALYST-001", "CODE-002", "Learning changed", "Changing an approach", "CODE-001")
    with pytest.raises(ReviewRequired, match="already"):
        define_code(released, "ANALYST-001", "CODE-001", "Learning changed", "Changing an approach")
    with pytest.raises(ReviewRequired, match="span"):
        apply_code(released, "ANALYST-001", "CODE-001", 0, 999, "Unsupported span")
    with pytest.raises(ReviewRequired, match="define"):
        apply_code(released, "ANALYST-001", "MISSING", 0, 10, "Unknown interpretation")


def test_source_free_summary_and_deduplication(released: Path) -> None:
    declare_method(released, "ANALYST-001", "GROUNDED_THEORY")
    define_code(released, "ANALYST-001", "CODE-001", "Learning together", "Learning with others")
    define_code(released, "ANALYST-002", "CODE-002", "Learning changed", "Changing an approach")
    apply_code(released, "ANALYST-001", "CODE-001", 3, 19, "Collaborative learning")
    apply_code(released, "ANALYST-002", "CODE-001", 3, 19, "Alternative reading")
    apply_code(released, "ANALYST-002", "CODE-002", 10, 27, "Changing the practice")
    write_memo(released, "ANALYST-001", 3, 19, "I bring my own assumptions into this reading.", "CODE-001")
    summary = research_summary(released)
    assert summary["coding_counts"] == {"CODE-001": 1, "CODE-002": 1}
    assert summary["cooccurrences"] == [{"codes": ["CODE-001", "CODE-002"], "overlapping_span_pairs": 1}]
    assert summary["memo_count"] == 1
    assert "learned" not in str(summary)
    assert "my own assumptions" not in str(summary)


def test_event_chain_rejects_reordered_or_resealed_ancestor(released: Path) -> None:
    first = declare_method(released, "ANALYST-001", "CODEBOOK")
    define_code(released, "ANALYST-001", "CODE-001", "Learning together", "Learning with others")
    payload = load_json(first)
    payload.pop("integrity_sha256")
    payload["method"] = "REFLEXIVE_THEMATIC"
    from aegisqda.manifests import canonical_bytes
    first.write_bytes(canonical_bytes(seal(payload)))
    with pytest.raises(IntegrityError, match="provenance"):
        research_summary(released)


def test_research_requires_valid_privacy_release(tmp_path: Path) -> None:
    from aegisqda.errors import DownstreamBlocked
    with pytest.raises(DownstreamBlocked):
        declare_method(tmp_path, "ANALYST-001", "CODEBOOK")


@pytest.mark.parametrize("label", ["A", "Care", "Agency", "x" * 200])
def test_short_and_bounded_code_labels_preserve_normal_qda_usage(released: Path, label: str) -> None:
    declare_method(released, "ANALYST-001", "CODEBOOK")
    define_code(released, "ANALYST-001", "CODE-001", label, "A bounded synthetic definition")
    assert research_summary(released)["code_count"] == 1


@pytest.mark.parametrize("label", ["", "   ", "x" * 201])
def test_code_label_bounds_still_reject_empty_or_oversized_labels(released: Path, label: str) -> None:
    declare_method(released, "ANALYST-001", "CODEBOOK")
    with pytest.raises(ReviewRequired, match="code label"):
        define_code(released, "ANALYST-001", "CODE-001", label, "A bounded synthetic definition")


def _reseal_event(path: Path, changes: dict[str, object], *, remove: str | None = None) -> None:
    payload = load_json(path)
    payload.pop("integrity_sha256")
    if remove is not None:
        payload.pop(remove)
    payload.update(changes)
    path.write_bytes(canonical_bytes(seal(payload)))


@pytest.mark.parametrize("invalid_id", [None, 123, True])
def test_resealed_event_rejects_non_string_analyst_id(released: Path, invalid_id: object) -> None:
    first = declare_method(released, "ANALYST-001", "CODEBOOK")
    _reseal_event(first, {"analyst_id": invalid_id})
    with pytest.raises(IntegrityError, match="analyst id"):
        research_summary(released)


def test_resealed_event_rejects_missing_analyst_id(released: Path) -> None:
    first = declare_method(released, "ANALYST-001", "CODEBOOK")
    _reseal_event(first, {}, remove="analyst_id")
    with pytest.raises(IntegrityError, match="analyst id"):
        research_summary(released)


@pytest.mark.parametrize("invalid_sequence", [True, 1.0, "1"])
def test_resealed_event_rejects_sequence_values_equal_to_int_but_untyped(
    released: Path, invalid_sequence: object,
) -> None:
    first = declare_method(released, "ANALYST-001", "CODEBOOK")
    _reseal_event(first, {"sequence": invalid_sequence})
    with pytest.raises(IntegrityError, match="provenance"):
        research_summary(released)


@pytest.mark.parametrize("invalid_id", [None, 123, True])
def test_resealed_code_definition_rejects_non_string_code_id(
    released: Path, invalid_id: object,
) -> None:
    declare_method(released, "ANALYST-001", "CODEBOOK")
    event = define_code(released, "ANALYST-001", "CODE-001", "Care", "A synthetic code definition")
    _reseal_event(event, {"code_id": invalid_id})
    with pytest.raises(IntegrityError, match="code id"):
        research_summary(released)


@pytest.mark.parametrize("invalid_parent", ["", False, 0])
def test_resealed_code_definition_rejects_falsy_parent_instead_of_ignoring_it(
    released: Path, invalid_parent: object,
) -> None:
    declare_method(released, "ANALYST-001", "CODEBOOK")
    event = define_code(released, "ANALYST-001", "CODE-001", "Care", "A synthetic code definition")
    _reseal_event(event, {"parent_id": invalid_parent})
    with pytest.raises(AegisError, match="parent code id"):
        research_summary(released)


def test_summary_provenance_does_not_reread_source_hash_for_every_event(
    released: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from collections import Counter
    import aegisqda.workbench as workbench

    declare_method(released, "ANALYST-001", "CODEBOOK")
    define_code(released, "ANALYST-001", "CODE-001", "Care", "A synthetic code definition")
    for start in range(5):
        apply_code(released, "ANALYST-001", "CODE-001", start, start + 8, "Synthetic interpretation")
    original = workbench.sha256_file
    reads: Counter[Path] = Counter()

    def count_reads(path: Path) -> str:
        reads[path] += 1
        return original(path)

    monkeypatch.setattr(workbench, "sha256_file", count_reads)
    summary = research_summary(released)
    assert summary["event_count"] == 7
    assert summary["coding_counts"] == {"CODE-001": 5}
    assert reads[released / "privacy-release.json"] <= 1
    assert reads[released / "transformed.txt"] <= 1


def test_cooccurrences_count_nested_and_equal_spans_but_not_adjacency(released: Path) -> None:
    declare_method(released, "ANALYST-001", "CODEBOOK")
    for code in ("CODE-A", "CODE-B", "CODE-C", "CODE-D"):
        define_code(released, "ANALYST-001", code, "Care", "A synthetic code definition")
    for code, start, end in (
        ("CODE-A", 0, 12), ("CODE-B", 3, 7), ("CODE-A", 9, 15),
        ("CODE-C", 12, 20), ("CODE-D", 24, 32), ("CODE-C", 24, 32),
    ):
        apply_code(released, "ANALYST-001", code, start, end, "Synthetic interpretation")
    apply_code(released, "ANALYST-002", "CODE-A", 0, 12, "Independent synthetic interpretation")
    summary = research_summary(released)
    assert summary["coding_counts"] == {"CODE-A": 2, "CODE-B": 1, "CODE-C": 2, "CODE-D": 1}
    assert summary["cooccurrences"] == [
        {"codes": ["CODE-A", "CODE-B"], "overlapping_span_pairs": 1},
        {"codes": ["CODE-A", "CODE-C"], "overlapping_span_pairs": 1},
        {"codes": ["CODE-C", "CODE-D"], "overlapping_span_pairs": 1},
    ]
