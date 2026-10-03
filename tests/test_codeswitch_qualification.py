"""SHA-bound annotated code-switch fixtures, not open-world recall evidence.

Each supported language has exactly three declared typed spans: one invented
foreign name, one email and one phone. All declared spans must be found; other
findings are not scored as precision evidence. The embedded lb sentence does
not qualify Luxembourgish identifiers or turn lb readiness on. Missing trained
models visibly skip the NER qualification rather than passing on blank NLP.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import importlib.util

import pytest

import aegisqda.detection as detection
from aegisqda.config import load_config, load_policy
from aegisqda.errors import UnsupportedLanguage
from aegisqda.formats.document import parse_document_bytes
from aegisqda.languages import PACKS, get_pack
from aegisqda.manifests import sha256_bytes


@dataclass(frozen=True)
class AnnotatedCase:
    language: str
    text: str
    source_sha256: str
    # Entity type, exact character start/end, declared synthetic value.
    annotations: tuple[tuple[str, int, int, str], ...]


CASES = (
    AnnotatedCase(
        "de",
        "P: Gestern traf ich Naoko Tanaka. She said: «Mir schaffen zesummen.» "
        "Kontakt: naoko.tanaka@fixture.example und +352 621 123 456.\n",
        "fb9f6075c3b9fce27abaad9407371a59126550643b437877f668a1439de0bc4a",
        (
            ("PERSON", 20, 32, "Naoko Tanaka"),
            ("EMAIL_ADDRESS", 78, 106, "naoko.tanaka@fixture.example"),
            ("PHONE_NUMBER", 111, 127, "+352 621 123 456"),
        ),
    ),
    AnnotatedCase(
        "fr",
        "P: J'ai discuté avec Lukas Muster. Er sagte: «Mir schaffen zesummen.» "
        "Contact: lukas.muster@fixture.example et +352 621 234 567.\n",
        "04c7c6dfac18a504bf51371e3cee2103421018f428d8c0ceef863d0a458c6f40",
        (
            ("PERSON", 21, 33, "Lukas Muster"),
            ("EMAIL_ADDRESS", 79, 107, "lukas.muster@fixture.example"),
            ("PHONE_NUMBER", 111, 127, "+352 621 234 567"),
        ),
    ),
    AnnotatedCase(
        "en",
        "P: I interviewed Élodie Martin. Elle a dit: «Mir schaffen zesummen.» "
        "Contact: elodie.martin@fixture.example, +352 621 345 678.\n",
        "6da374db0e2d0b0376919b65b87c218d35a6d2ad955d85dd8e7e4d3ab04573eb",
        (
            ("PERSON", 17, 30, "Élodie Martin"),
            ("EMAIL_ADDRESS", 78, 107, "elodie.martin@fixture.example"),
            ("PHONE_NUMBER", 109, 125, "+352 621 345 678"),
        ),
    ),
)


@pytest.fixture(autouse=True)
def _clear_detector_cache():
    detection._engine.cache_clear()
    yield
    detection._engine.cache_clear()


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.language)
def test_codeswitch_annotation_hashes_spans_and_denominators_are_explicit(case: AnnotatedCase) -> None:
    assert sha256_bytes(case.text.encode()) == case.source_sha256
    assert len(case.annotations) == 3
    for _, start, end, value in case.annotations:
        assert 0 <= start < end <= len(case.text)
        assert case.text[start:end] == value
        assert case.text.count(value) == 1
    # Each category has a real denominator. A zero-recall category cannot be
    # obscured by successful emails/phones or by a vacuous empty annotation list.
    assert Counter(item[0] for item in case.annotations) == {
        "PERSON": 1, "EMAIL_ADDRESS": 1, "PHONE_NUMBER": 1,
    }


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.language)
def test_real_installed_nlp_finds_every_declared_codeswitch_span(
    case: AnnotatedCase, record_property,
) -> None:
    model = PACKS[case.language].optional_ner_model
    if model is None or importlib.util.find_spec(model) is None:
        pytest.skip(f"{case.language}: trained model {model} absent; annotated foreign-name recall unqualified")
    doc = parse_document_bytes(case.text.encode(), ".txt")
    findings = detection.scan_document(doc, case.language, load_policy(load_config()))
    # A cached mocked pipeline or blank fallback must never count as trained
    # model qualification; this test actually loads the local installed package.
    assert detection._engine(case.language).nlp_engine.model_name == model
    actual = {(finding.entity_type, finding.start, finding.end) for finding in findings}
    required = {(entity, start, end) for entity, start, end, _ in case.annotations}
    matched = required & actual
    record_property("metric_scope", "ANNOTATED_SYNTHETIC_TYPED_SPANS_ONLY")
    record_property("source_sha256", case.source_sha256)
    record_property("trained_model", model)
    record_property("required_span_count", len(required))
    record_property("matched_span_count", len(matched))
    for entity in {item[0] for item in case.annotations}:
        expected_count = sum(item[0] == entity for item in required)
        matched_count = sum(item[0] == entity for item in matched)
        record_property(f"{entity}_required", expected_count)
        record_property(f"{entity}_matched", matched_count)
        assert expected_count > 0 and matched_count == expected_count, (
            f"{case.language}/{entity}: annotated recall {matched_count}/{expected_count}; "
            "synthetic fixture qualification failed"
        )
    assert matched == required


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.language)
def test_codeswitched_structured_ids_survive_absent_trained_models(
    case: AnnotatedCase, monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = detection.importlib.util.find_spec
    models = {pack.optional_ner_model for pack in PACKS.values() if pack.optional_ner_model}

    def no_models(name: str, *args, **kwargs):
        return None if name in models else original(name, *args, **kwargs)

    monkeypatch.setattr(detection.importlib.util, "find_spec", no_models)
    doc = parse_document_bytes(case.text.encode(), ".txt")
    findings = detection.scan_document(doc, case.language, load_policy(load_config()))
    assert detection._engine(case.language).nlp_engine.model_name == f"spacy.blank:{case.language}"
    actual = {(finding.entity_type, finding.start, finding.end) for finding in findings}
    required = {(entity, start, end) for entity, start, end, _ in case.annotations if entity != "PERSON"}
    assert len(required) == 2 and required <= actual
    # This regression concerns structured rules, not qualification of the
    # unmeasured PERSON category in the absence of a trained model.


def test_codeswitch_fixture_success_never_unlocks_luxembourgish_pack() -> None:
    assert PACKS["lb"].release_ready is False
    assert PACKS["lb"].synthetic_rules_ready is False
    with pytest.raises(UnsupportedLanguage):
        get_pack("lb")
