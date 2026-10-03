"""Model-free tests for the spaCy NER integration and its two guards.

These never load a trained model: a spaCy blank pipeline plus an entity_ruler
emits exactly the labels the real de/fr/en models emit (PER/LOC/ORG, and GPE for
en), so the label normalisation, the regex-precedence suppression, and the
surrogate-aware second pass can be verified deterministically in CI.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest
import spacy
from spacy.pipeline import EntityRuler

import aegisqda.detection as det
import aegisqda.workflow as wf
from aegisqda.config import load_config, load_policy
from aegisqda.detection import Finding, scan_document
from aegisqda.errors import IntegrityError, ReviewRequired
from aegisqda.formats.document import Document, Region, parse_document_bytes
from aegisqda.manifests import sha256_bytes
from aegisqda.workflow import LEDGER_FILE, scan_source, transform_run, write_review
from aegisqda.safeio import load_json

MODEL = {"de": "de_core_news_lg", "fr": "fr_core_news_lg", "en": "en_core_web_lg"}


@pytest.fixture(autouse=True)
def _clear_engine():  # type: ignore[no-untyped-def]
    det._engine.cache_clear()
    yield
    det._engine.cache_clear()


def _sim_model(
    monkeypatch: pytest.MonkeyPatch, lang: str, patterns: list[dict[str, Any]]
) -> None:
    real = importlib.util.find_spec
    monkeypatch.setattr(det.importlib.util, "find_spec",
                        lambda n, *a, **k: object() if n == MODEL[lang] else real(n, *a, **k))

    def load(name: str, *args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        del name, args, kwargs
        nlp = spacy.blank(lang)
        ruler = nlp.add_pipe("entity_ruler")
        assert isinstance(ruler, EntityRuler)
        ruler.add_patterns(patterns)
        return nlp

    monkeypatch.setattr(det.spacy, "load", load)
    det._engine.cache_clear()


def _policy():  # type: ignore[no-untyped-def]
    return load_policy(load_config())


def _doc(text: str) -> Document:
    return Document("txt", text, (Region(0, len(text)),), {})


def test_de_fr_labels_are_normalized(monkeypatch):
    _sim_model(monkeypatch, "de", [
        {"label": "PER", "pattern": "Anna Beispiel"},
        {"label": "LOC", "pattern": "Musterstadt"},
        {"label": "ORG", "pattern": "Beispiel GmbH"},
    ])
    text = "Anna Beispiel arbeitet bei Beispiel GmbH in Musterstadt heute."
    got = {(f.entity_type, text[f.start:f.end]) for f in scan_document(_doc(text), "de", _policy())}
    assert ("PERSON", "Anna Beispiel") in got
    assert ("LOCATION", "Musterstadt") in got
    assert ("ORGANIZATION", "Beispiel GmbH") in got


def test_en_gpe_maps_to_location(monkeypatch):
    _sim_model(monkeypatch, "en", [{"label": "GPE", "pattern": "Springfield"}])
    text = "The team relocated and now works in Springfield full time."
    types = {f.entity_type for f in scan_document(_doc(text), "en", _policy())}
    assert "LOCATION" in types


def test_regex_precedence_suppresses_ner_over_structured(monkeypatch):
    _sim_model(monkeypatch, "de", [
        {"label": "LOC", "pattern": "anna@example.com"},
        {"label": "ORG", "pattern": [{"TEXT": {"REGEX": r"^LU\d{2}$"}}]},
    ])
    text = "Mail anna@example.com und IBAN LU28 0019 4006 4475 0000 hier."
    findings = scan_document(_doc(text), "de", _policy())
    email = {f.entity_type for f in findings if text[f.start:f.end] == "anna@example.com"}
    assert email == {"EMAIL_ADDRESS"}  # LOCATION false positive suppressed
    # no PERSON/LOCATION/ORGANIZATION finding overlaps the IBAN span
    iban_start = text.index("LU28")
    iban_end = text.index("0000") + 4
    ner_over_iban = [
        f for f in findings
        if f.entity_type in {"PERSON", "LOCATION", "ORGANIZATION"}
        and f.start < iban_end and iban_start < f.end
    ]
    assert ner_over_iban == []


def test_partial_structured_overlap_remains_reviewable(monkeypatch: pytest.MonkeyPatch) -> None:
    _sim_model(monkeypatch, "de", [{"label": "LOC", "pattern": "Projektkonto LU28"}])
    text = "Das Projektkonto LU28 0019 4006 4475 0000. Es wird verwendet."
    findings = scan_document(_doc(text), "de", _policy())
    got = {(f.entity_type, text[f.start:f.end]) for f in findings}
    assert ("LOCATION", "Projektkonto LU28") in got
    assert ("IBAN_CODE", "LU28 0019 4006 4475 0000") in got


def test_structured_field_cue_is_not_an_organization(monkeypatch: pytest.MonkeyPatch) -> None:
    _sim_model(monkeypatch, "en", [{"label": "ORG", "pattern": "IBAN"}])
    text = "IBAN: LU28 0019 4006 4475 0000"
    findings = scan_document(_doc(text), "en", _policy())
    got = {(f.entity_type, text[f.start:f.end]) for f in findings}
    assert got == {("IBAN_CODE", "LU28 0019 4006 4475 0000")}


def test_transcript_role_markers_are_structural(monkeypatch: pytest.MonkeyPatch) -> None:
    _sim_model(
        monkeypatch,
        "fr",
        [{"label": "LOC", "pattern": "I"}, {"label": "LOC", "pattern": "P"}],
    )
    text = "I: Première question.\nP: Première réponse."
    assert scan_document(_doc(text), "fr", _policy()) == []


def test_context_rule_overrules_contained_wrong_ner_label(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _sim_model(monkeypatch, "fr", [{"label": "LOC", "pattern": "Novaform"}])
    text = "Le projet est porté par le groupe Novaform."
    findings = scan_document(_doc(text), "fr", _policy())
    got = {(f.entity_type, text[f.start:f.end]) for f in findings}
    assert got == {("ORGANIZATION", "Novaform")}


def _confirm_all(run_dir: Path) -> None:
    ledger = load_json(run_dir / LEDGER_FILE)
    decisions = []
    for finding in ledger["findings"]:
        action = finding["action"]
        if action == "REPLACE_AND_REVIEW":
            decisions.append({"finding_id": finding["finding_id"], "decision": "CONFIRMED"})
        elif action == "GENERALIZE_AND_REVIEW":
            decisions.append({"finding_id": finding["finding_id"], "decision": "GENERALIZE_CONFIRMED"})
        else:
            raise AssertionError(f"unexpected block action in fixture: {action}")
    write_review(run_dir, "TEST-REVIEWER", decisions, [])


def _prepare_release(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(wf, "verify_upstream", lambda config: "test-bridged")
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.delenv(var, raising=False)
    src = tmp_path / "iv.txt"
    src.write_text("Kontakt: person@invalid.example ist alles.\n", encoding="utf-8")
    run_dir = scan_source(src, language="de", case_id="TEST-CASE",
                          run_root=tmp_path / "runs", synthetic=True)
    _confirm_all(run_dir)
    return run_dir


def test_second_pass_exempts_surrogate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = _prepare_release(tmp_path, monkeypatch)

    def inside(doc: Document, language: str, policy: object) -> list[Finding]:
        del language, policy
        i = doc.text.find("[")
        j = doc.text.find("]", i)
        inner = doc.text[i + 1:j]
        return [Finding("F-0001", "PERSON", i + 1, j, 0.9, "sim",
                        "REPLACE_AND_REVIEW", sha256_bytes(inner.encode()))]

    monkeypatch.setattr(wf, "scan_document", inside)
    release = transform_run(run_dir)  # must NOT raise
    assert release.name == "privacy-release.json"


def test_second_pass_blocks_real_residual(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = _prepare_release(tmp_path, monkeypatch)

    def outside(doc: Document, language: str, policy: object) -> list[Finding]:
        del language, policy
        return [Finding("F-0001", "PERSON", 0, 5, 0.9, "sim",
                        "REPLACE_AND_REVIEW", sha256_bytes(doc.text[0:5].encode()))]

    monkeypatch.setattr(wf, "scan_document", outside)
    with pytest.raises(ReviewRequired, match="second-pass"):
        transform_run(run_dir)


def test_second_pass_does_not_exempt_finding_crossing_surrogate_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = _prepare_release(tmp_path, monkeypatch)

    def crossing(doc: Document, language: str, policy: object) -> list[Finding]:
        del language, policy
        start = doc.text.index("[") + 1
        end = doc.text.index("]", start) + 2
        value = doc.text[start:end]
        return [
            Finding(
                "F-0001",
                "PERSON",
                start,
                end,
                0.9,
                "sim",
                "REPLACE_AND_REVIEW",
                sha256_bytes(value.encode()),
            )
        ]

    monkeypatch.setattr(wf, "scan_document", crossing)
    with pytest.raises(ReviewRequired, match="second-pass"):
        transform_run(run_dir)


def test_ner_span_across_srt_line_wrap_is_split_not_dropped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _sim_model(monkeypatch, "en", [
        {"label": "PERSON", "pattern": [{"TEXT": "Maria"}, {"IS_SPACE": True}, {"TEXT": "Gonzalez"}]},
    ])
    srt = "1\n00:00:01,000 --> 00:00:04,000\nYesterday I interviewed Maria\nGonzalez about it.\n"
    document = parse_document_bytes(srt.encode(), ".srt")
    got = {(f.entity_type, srt[f.start:f.end]) for f in scan_document(document, "en", _policy())}
    assert got == {("PERSON", "Maria"), ("PERSON", "Gonzalez")}


def test_bracketed_value_is_not_exempt_unless_surrogate_shaped() -> None:
    text = "My name is [Jane Example] and I live in Springfield."
    got = {(f.entity_type, text[f.start:f.end]) for f in scan_document(_doc(text), "en", _policy())}
    assert ("PERSON", "[Jane Example]") in got


def test_unicode_line_separators_are_rejected() -> None:
    with pytest.raises(IntegrityError, match="line separators"):
        parse_document_bytes("My name is Jane Example.\n".encode(), ".txt")


WRAPPED_SRT = (
    "1\n00:00:01,000 --> 00:00:04,000\nYesterday I interviewed Maria\nGonzalez about the garden.\n\n"
    "2\n00:00:05,000 --> 00:00:08,000\nLater Maria Gonzalez agreed.\n\n"
    "3\n00:00:09,000 --> 00:00:12,000\nWe then met with Peter\nMiller\n"
)
WRAPPED_PATTERNS: list[dict[str, Any]] = [
    {"label": "PERSON", "pattern": [{"TEXT": "Maria"}, {"IS_SPACE": True}, {"TEXT": "Gonzalez"}]},
    {"label": "PERSON", "pattern": "Maria Gonzalez"},
    {"label": "PERSON", "pattern": [{"TEXT": "Peter"}, {"IS_SPACE": True}, {"TEXT": "Miller"}]},
]


def _wrapped_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    _sim_model(monkeypatch, "en", WRAPPED_PATTERNS)
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.delenv(var, raising=False)
    source = tmp_path / "wrapped.srt"
    source.write_text(WRAPPED_SRT, encoding="utf-8")
    return scan_source(
        source, language="en", case_id="CASE-WRAP", run_root=tmp_path / "runs", synthetic=True
    )


def test_split_mention_pieces_share_one_group(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = _wrapped_run(tmp_path, monkeypatch)
    findings = load_json(run_dir / LEDGER_FILE)["findings"]
    text = WRAPPED_SRT
    got = [(text[f["start"]:f["end"]], f["group_id"]) for f in findings]
    assert got == [
        ("Maria", "G-0001"),
        ("Gonzalez", "G-0001"),
        ("Maria Gonzalez", None),
        ("Peter", "G-0002"),
        ("Miller", "G-0002"),
    ]


def test_split_mention_gets_one_surrogate_shared_with_unsplit_mention(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = _wrapped_run(tmp_path, monkeypatch)
    _confirm_all(run_dir)
    transform_run(run_dir)
    lines = (run_dir / "transformed.srt").read_text(encoding="utf-8").splitlines()
    assert lines[2:4] == ["Yesterday I interviewed [PERSON_001]", "about the garden."]
    assert lines[7] == "Later [PERSON_001] agreed."
    # The rest of the name was alone on its line; removing it would empty the
    # line and break the cue, so the continuation mark keeps the structure.
    assert lines[11:13] == ["We then met with [PERSON_002]", "[…]"]


def test_split_mention_pieces_need_the_same_decision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = _wrapped_run(tmp_path, monkeypatch)
    decisions = [
        {"finding_id": f["finding_id"], "decision": "CONFIRMED"}
        for f in load_json(run_dir / LEDGER_FILE)["findings"]
    ]
    decisions[1] = {
        "finding_id": decisions[1]["finding_id"],
        "decision": "FALSE_POSITIVE",
        "rationale": "only the first line is a name",
    }
    with pytest.raises(ReviewRequired, match="same decision"):
        write_review(run_dir, "TEST-REVIEWER", decisions, [])


def test_interactive_review_asks_once_per_split_mention(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = _wrapped_run(tmp_path, monkeypatch)
    prompts: list[str] = []

    def answer(prompt: str = "") -> str:
        prompts.append(prompt)
        return "c" if prompt.startswith("confirm replacement") else "n"

    monkeypatch.setattr("builtins.input", answer)
    wf.interactive_review(run_dir, "TEST-REVIEWER")
    assert sum(prompt.startswith("confirm replacement") for prompt in prompts) == 3
    review = load_json(run_dir / "review.json")
    assert {d["decision"] for d in review["decisions"]} == {"CONFIRMED"}
    assert len(review["decisions"]) == 5


def test_split_mention_as_last_finding_leaves_no_leading_space(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _sim_model(monkeypatch, "en", WRAPPED_PATTERNS[:1])
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.delenv(var, raising=False)
    source = tmp_path / "last.srt"
    source.write_text(
        "1\n00:00:01,000 --> 00:00:04,000\nYesterday I interviewed Maria\nGonzalez about it.\n",
        encoding="utf-8",
    )
    run_dir = scan_source(
        source, language="en", case_id="CASE-LAST", run_root=tmp_path / "runs", synthetic=True
    )
    _confirm_all(run_dir)
    transform_run(run_dir)
    lines = (run_dir / "transformed.srt").read_text(encoding="utf-8").splitlines()
    assert lines[2:4] == ["Yesterday I interviewed [PERSON_001]", "about it."]
