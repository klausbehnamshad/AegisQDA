"""Reject content-empty detections without exempting nearby identifiers."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import aegisqda.detection as detection
from aegisqda.config import load_config, load_policy
from aegisqda.formats.document import Document, Region, parse_document_bytes


@pytest.fixture
def rules_only(monkeypatch: pytest.MonkeyPatch):
    original = detection.importlib.util.find_spec
    models = {pack.optional_ner_model for pack in detection.PACKS.values() if pack.optional_ner_model}

    def no_models(name: str, *args, **kwargs):
        return None if name in models else original(name, *args, **kwargs)

    monkeypatch.setattr(detection.importlib.util, "find_spec", no_models)
    detection._engine.cache_clear()
    yield
    detection._engine.cache_clear()


@pytest.mark.parametrize("blank", [" " * 12, "\t \t", "\u00a0" * 12])
def test_real_context_rule_does_not_report_masked_whitespace_as_person(
    blank: str, rules_only,
) -> None:
    text = f"My name is {blank} and I live in the area."
    doc = parse_document_bytes(text.encode(), ".txt")
    findings = detection.scan_document(doc, "en", load_policy(load_config()))
    assert not any(finding.entity_type == "PERSON" for finding in findings)


@pytest.mark.parametrize("value", [" Jane Example ", "\tJane Example\t", "[Jane Example]"])
def test_real_context_rule_keeps_identity_characters_next_to_whitespace(
    value: str, rules_only,
) -> None:
    text = f"My name is {value} and I live in the area."
    doc = parse_document_bytes(text.encode(), ".txt")
    findings = detection.scan_document(doc, "en", load_policy(load_config()))
    persons = [doc.text[finding.start:finding.end] for finding in findings if finding.entity_type == "PERSON"]
    assert any("Jane Example" in person for person in persons)


def test_filter_keeps_real_identifiers_beside_masked_content(rules_only) -> None:
    text = "My name is             and I live in the area. Contact synthetic@fixture.example."
    doc = parse_document_bytes(text.encode(), ".txt")
    findings = detection.scan_document(doc, "en", load_policy(load_config()))
    assert not any(finding.entity_type == "PERSON" for finding in findings)
    assert any(
        finding.entity_type == "EMAIL_ADDRESS"
        and doc.text[finding.start:finding.end] == "synthetic@fixture.example"
        for finding in findings
    )


@pytest.mark.parametrize("entity", ["PERSON", "LOCATION", "ORGANIZATION", "EMAIL_ADDRESS"])
def test_whitespace_filter_applies_to_actual_span_for_every_entity(
    entity: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = " \t "

    def analyze(**kwargs):
        return [SimpleNamespace(
            entity_type=entity, start=0, end=len(kwargs["text"]), score=0.9,
            recognition_metadata={"recognizer_name": "SyntheticWhitespaceRecognizer"},
        )]

    monkeypatch.setattr(detection, "_engine", lambda language: SimpleNamespace(analyze=analyze))
    doc = Document("txt", text, (Region(0, len(text)),), {})
    assert detection.scan_document(doc, "en", load_policy(load_config())) == []


def test_line_projection_cannot_reintroduce_content_empty_person(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = "\t \n \t"

    def analyze(**kwargs):
        return [SimpleNamespace(
            entity_type="PERSON", start=0, end=len(kwargs["text"]), score=0.9,
            recognition_metadata={"recognizer_name": "SyntheticWhitespaceRecognizer"},
        )]

    monkeypatch.setattr(detection, "_engine", lambda language: SimpleNamespace(analyze=analyze))
    doc = Document("txt", text, (Region(0, 2), Region(3, 5)), {})
    assert detection.scan_document(doc, "en", load_policy(load_config())) == []
