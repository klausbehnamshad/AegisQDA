"""Deterministic, closed-vocabulary generalizations for reviewed findings.

These transformations preserve coarse analytic categories, not anonymity.
The workflow must still require review, policy permission and a second scan.
Unsupported values stop rather than fall back to keeping the original value.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import re
import unicodedata

from .errors import ReviewRequired, UnsupportedLanguage


@dataclass(frozen=True)
class GeneralizationResult:
    entity_type: str
    text: str
    rule_id: str


AGE_RULE = "AGE_TEN_YEAR_BANDS_TOPCODE_90_V1"
DATE_RULE = "DATE_VALID_CALENDAR_YEAR_V1"
KINSHIP_RULE = "KINSHIP_FAMILY_CATEGORY_V1"
JOB_RULE = "JOB_CONTROLLED_SECTOR_V1"

_AGE = re.compile(r"([0-9]{1,3})\s+(?:Jahre? alt|ans?|years? old)", re.IGNORECASE)
_LOCAL_DATE = re.compile(r"([0-9]{1,2})([./-])([0-9]{1,2})\2([0-9]{4})")
_ISO_DATE = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})")
_KINSHIP = frozenset({
    "mutter", "vater", "schwester", "bruder", "mère", "père", "soeur", "sœur", "frère",
    "mother", "father", "sister", "brother",
})
_JOB_SECTORS = {
    "ärztin": "HEALTH", "arzt": "HEALTH", "médecin": "HEALTH", "doctor": "HEALTH",
    "lehrerin": "EDUCATION", "lehrer": "EDUCATION", "enseignant": "EDUCATION",
    "enseignante": "EDUCATION", "teacher": "EDUCATION",
}


def generalize(entity_type: str, value: str, language: str) -> GeneralizationResult:
    """Generalize one complete, reviewed entity value or stop for review.

    Accepted multilingual words are an explicit de/fr/en vocabulary, also
    usable in a code-switched passage of a supported-language source. No
    language inference, substring extraction or arbitrary title mapping occurs.
    Date order is fixed by language (de/fr DMY, en MDY); ISO dates are universal.
    """
    if language not in {"de", "fr", "en"}:
        raise UnsupportedLanguage("generalization requires a supported language pack")
    if not isinstance(value, str) or not value or any(c in value for c in "\r\n\x00"):
        raise ReviewRequired("generalization requires one complete single-line value")
    normalized = unicodedata.normalize("NFC", value.strip())
    if entity_type == "AGE":
        match = _AGE.fullmatch(normalized)
        if match is None:
            raise ReviewRequired("age generalization requires an exact age with an age unit")
        age = int(match[1])
        if age > 120:
            raise ReviewRequired("age falls outside the supported generalization range")
        band = "90_PLUS" if age >= 90 else f"{age // 10 * 10}_{age // 10 * 10 + 9}"
        return GeneralizationResult(entity_type, f"[AGE_BAND_{band}]", AGE_RULE)
    if entity_type == "DATE_TIME":
        iso = _ISO_DATE.fullmatch(normalized)
        local = _LOCAL_DATE.fullmatch(normalized)
        if iso is not None:
            year, month, day = (int(part) for part in iso.groups())
        elif local is not None:
            first, separator, second, year_text = local.groups()
            year = int(year_text)
            if language == "en" and separator == "/":
                month, day = int(first), int(second)
            elif language in {"de", "fr"} or separator == ".":
                day, month = int(first), int(second)
            else:
                raise ReviewRequired("date order is not covered by the generalization rule")
        else:
            raise ReviewRequired("date generalization requires an exact date with four-digit year")
        try:
            date(year, month, day)
        except ValueError as exc:
            raise ReviewRequired("date generalization requires a valid calendar date") from exc
        return GeneralizationResult(entity_type, f"[YEAR_{year:04d}]", DATE_RULE)
    if entity_type == "KINSHIP" and normalized.casefold() in _KINSHIP:
        return GeneralizationResult(entity_type, "[FAMILY_RELATION]", KINSHIP_RULE)
    if entity_type == "JOB_TITLE" and normalized.casefold() in _JOB_SECTORS:
        sector = _JOB_SECTORS[normalized.casefold()]
        return GeneralizationResult(entity_type, f"[OCCUPATION_{sector}]", JOB_RULE)
    raise ReviewRequired("finding has no approved deterministic generalization rule")


def is_generalized_output(entity_type: str, text: str, rule_id: str) -> bool:
    """Recognize generated vocabulary; this alone never exempts a scan finding.

    Callers must bind the output to the actual transformation and its exact
    character range. A look-alike token already present in a source is untrusted.
    """
    if entity_type == "AGE" and rule_id == AGE_RULE:
        outputs = {f"[AGE_BAND_{start}_{start + 9}]" for start in range(0, 90, 10)}
        return text in outputs or text == "[AGE_BAND_90_PLUS]"
    if entity_type == "DATE_TIME" and rule_id == DATE_RULE:
        match = re.fullmatch(r"\[YEAR_([0-9]{4})\]", text)
        return match is not None and int(match[1]) > 0
    if entity_type == "KINSHIP" and rule_id == KINSHIP_RULE:
        return text == "[FAMILY_RELATION]"
    if entity_type == "JOB_TITLE" and rule_id == JOB_RULE:
        return text in {"[OCCUPATION_HEALTH]", "[OCCUPATION_EDUCATION]"}
    return False
