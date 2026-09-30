from __future__ import annotations

import json
from pathlib import Path

import pytest

from aegisqda.config import load_config, load_policy
from aegisqda.detection import MAX_SCAN_CHARS, scan_document
from aegisqda.errors import BoundaryError, IntegrityError
from aegisqda.formats.document import (
    Document,
    Region,
    fingerprint_text,
    parse_document,
    parse_document_bytes,
)


@pytest.mark.parametrize("language", ["de", "fr", "en", "lb"])
def test_seeded_fixture_direct_identifiers_detected(fixture_root: Path, language: str) -> None:
    document = parse_document(fixture_root / language / "sample.srt")
    types = {item.entity_type for item in scan_document(document, language, load_policy(load_config()))}
    assert {"PERSON", "LOCATION", "EMAIL_ADDRESS"} <= types


def test_srt_structure_fingerprint_ignores_replacement_length(fixture_root: Path) -> None:
    document = parse_document(fixture_root / "en" / "sample.srt")
    changed = document.text.replace("Jane Example", "[PERSON_001]")
    assert fingerprint_text(changed, "srt") == document.fingerprint


def test_malformed_srt_blocks(tmp_path: Path) -> None:
    source = tmp_path / "bad.srt"
    source.write_text("2\nnot a timing line\nhello\n", encoding="utf-8")
    with pytest.raises(IntegrityError, match="cue sequence"):
        parse_document(source)


def test_mixed_newlines_block(tmp_path: Path) -> None:
    source = tmp_path / "bad.txt"
    source.write_bytes(b"one\r\ntwo\n")
    with pytest.raises(IntegrityError, match="mixed"):
        parse_document(source)


def test_indirect_and_network_identifiers_detect(tmp_path: Path) -> None:
    source = tmp_path / "risk.txt"
    source.write_text(
        "The only survivor is 97 years old, a doctor in a small village. "
        "Call +352 621 123 456 from 192.168.1.9 or see https://example.test.",
        encoding="utf-8",
    )
    document = parse_document(source)
    types = {item.entity_type for item in scan_document(document, "en", load_policy(load_config()))}
    assert {"RARE_EVENT", "AGE", "JOB_TITLE", "SMALL_PLACE", "PHONE_NUMBER", "IP_ADDRESS", "URL"} <= types


def test_safe_control_has_no_direct_findings(tmp_path: Path) -> None:
    source = tmp_path / "safe.txt"
    source.write_text("The group discussed gardening and public transport.", encoding="utf-8")
    findings = scan_document(parse_document(source), "en", load_policy(load_config()))
    assert findings == []


@pytest.mark.parametrize("language", ["de", "fr", "en", "lb"])
def test_per_language_risk_fixture_recall(fixture_root: Path, language: str) -> None:
    expected = json.loads((fixture_root / "expected.json").read_text(encoding="utf-8"))
    required = {tuple(item) for item in expected["seeds"][language]}
    text = (fixture_root / language / "risk.txt").read_text(encoding="utf-8")
    findings = scan_document(
        parse_document(fixture_root / language / "risk.txt"),
        language,
        load_policy(load_config()),
    )
    observed = {(finding.entity_type, text[finding.start:finding.end]) for finding in findings}
    assert required <= observed


@pytest.mark.parametrize("language", ["de", "fr", "en", "lb"])
def test_per_language_safe_control_false_positives(fixture_root: Path, language: str) -> None:
    findings = scan_document(
        parse_document(fixture_root / language / "safe.txt"),
        language,
        load_policy(load_config()),
    )
    assert findings == []


@pytest.mark.parametrize(
    ("language", "text", "expected"),
    [
        ("de", "Frau Erika Muster sagte zu.", "Frau Erika Muster"),
        ("fr", "Mme Élise Exemple a répondu.", "Mme Élise Exemple"),
        ("en", "Dr. Jane Example agreed.", "Dr. Jane Example"),
        ("lb", "Här Jean Beispill huet geäntwert.", "Här Jean Beispill"),
    ],
)
def test_title_based_person_variants(
    tmp_path: Path, language: str, text: str, expected: str
) -> None:
    source = tmp_path / f"{language}.txt"
    source.write_text(text, encoding="utf-8")
    document = parse_document(source)
    values = {
        document.text[finding.start:finding.end]
        for finding in scan_document(document, language, load_policy(load_config()))
        if finding.entity_type == "PERSON"
    }
    assert expected in values


def test_srt_byte_order_mark_is_not_part_of_the_first_cue() -> None:
    raw = "\ufeff1\n00:00:01,000 --> 00:00:02,000\nHello there.\n".encode()
    document = parse_document_bytes(raw, ".srt")
    assert document.text.startswith("1\n")
    assert document.fingerprint["cue_count"] == 1


@pytest.mark.parametrize(
    "srt",
    [
        "\u00b2\n00:00:01,000 --> 00:00:02,000\nHello.\n",
        "\u0661\n00:00:01,000 --> 00:00:02,000\nHello.\n",
        "1\n\u0660\u0660:00:01,000 --> 00:00:02,000\nHello.\n",
    ],
)
def test_srt_numbers_must_be_ascii_digits(srt: str) -> None:
    with pytest.raises(IntegrityError, match="malformed SRT"):
        parse_document_bytes(srt.encode(), ".srt")


def test_detector_length_bound_blocks_with_clear_message() -> None:
    text = "a" * (MAX_SCAN_CHARS + 1)
    document = Document("txt", text, (Region(0, len(text)),), {})
    with pytest.raises(BoundaryError, match="character local detector bound"):
        scan_document(document, "en", load_policy(load_config()))
