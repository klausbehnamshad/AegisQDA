"""Synthetic rule and ambiguity tests for useful, conservative generalization."""

from __future__ import annotations

import pytest

from aegisqda.errors import ReviewRequired, UnsupportedLanguage
from aegisqda.generalization import generalize, is_generalized_output


@pytest.mark.parametrize(("value", "language", "expected"), [
    ("37 Jahre alt", "de", "[AGE_BAND_30_39]"),
    ("39 ans", "fr", "[AGE_BAND_30_39]"),
    ("40 years old", "en", "[AGE_BAND_40_49]"),
    ("9 Jahre alt", "de", "[AGE_BAND_0_9]"),
    ("0 ans", "fr", "[AGE_BAND_0_9]"),
    ("89 years old", "en", "[AGE_BAND_80_89]"),
    ("90 Jahre alt", "de", "[AGE_BAND_90_PLUS]"),
    ("120 ans", "fr", "[AGE_BAND_90_PLUS]"),
])
def test_age_preserves_cohort_without_exact_age(value, language, expected):
    result = generalize("AGE", value, language)
    assert result.text == expected
    assert is_generalized_output(result.entity_type, result.text, result.rule_id)


@pytest.mark.parametrize(("value", "language", "expected"), [
    ("31.12.2020", "de", "[YEAR_2020]"),
    ("29/02/2020", "fr", "[YEAR_2020]"),
    ("12/31/2021", "en", "[YEAR_2021]"),
    ("2024-02-29", "en", "[YEAR_2024]"),
    ("29.02.2024", "en", "[YEAR_2024]"),
])
def test_calendar_validated_date_preserves_year(value, language, expected):
    result = generalize("DATE_TIME", value, language)
    assert result.text == expected
    assert is_generalized_output(result.entity_type, result.text, result.rule_id)


@pytest.mark.parametrize(("entity", "value", "language", "expected"), [
    ("KINSHIP", "Mutter", "de", "[FAMILY_RELATION]"),
    ("KINSHIP", "frère", "fr", "[FAMILY_RELATION]"),
    ("KINSHIP", "SISTER", "en", "[FAMILY_RELATION]"),
    ("JOB_TITLE", "Ärztin", "de", "[OCCUPATION_HEALTH]"),
    ("JOB_TITLE", "me\u0301decin", "fr", "[OCCUPATION_HEALTH]"),
    ("JOB_TITLE", "teacher", "en", "[OCCUPATION_EDUCATION]"),
    ("JOB_TITLE", "enseignante", "de", "[OCCUPATION_EDUCATION]"),
])
def test_closed_categories_and_code_switched_values(entity, value, language, expected):
    result = generalize(entity, value, language)
    assert result.text == expected
    assert is_generalized_output(result.entity_type, result.text, result.rule_id)


@pytest.mark.parametrize(("entity", "value", "language"), [
    ("AGE", "37", "de"), ("AGE", "-1 years old", "en"),
    ("AGE", "121 ans", "fr"), ("AGE", "about 37 years old", "en"),
    ("AGE", "37 to 39 years old", "en"), ("AGE", "37 years old Ada", "en"),
    ("DATE_TIME", "31.02.2020", "de"), ("DATE_TIME", "29/02/2021", "fr"),
    ("DATE_TIME", "31/12/2020", "en"), ("DATE_TIME", "12-31-2020", "en"),
    ("DATE_TIME", "31.12/2020", "de"), ("DATE_TIME", "31.12.20", "de"),
    ("DATE_TIME", "around 2020", "en"), ("DATE_TIME", "2020", "en"),
    ("DATE_TIME", "2020-02-01T12:30:00Z", "en"), ("DATE_TIME", "01.01.0000", "de"),
    ("KINSHIP", "mother of Ada", "en"), ("KINSHIP", "cousin", "en"),
    ("JOB_TITLE", "chief teacher at Novaform", "en"),
    ("JOB_TITLE", "rocket specialist", "en"), ("JOB_TITLE", "teacher\nAda", "en"),
    ("SMALL_PLACE", "small village", "en"), ("RARE_EVENT", "only survivor", "en"),
    ("PERSON", "Ada Synthetic", "en"),
])
def test_uncertain_or_unsupported_values_require_review_and_do_not_leak(entity, value, language):
    with pytest.raises(ReviewRequired) as captured:
        generalize(entity, value, language)
    assert value not in str(captured.value)


@pytest.mark.parametrize("language", ["lb", "auto", "xx"])
def test_generalization_does_not_unlock_unsupported_language(language):
    with pytest.raises(UnsupportedLanguage):
        generalize("AGE", "37 years old", language)


def test_rules_are_deterministic_and_output_validator_does_not_accept_lookalikes():
    a = generalize("AGE", "37 years old", "en")
    b = generalize("AGE", "39 years old", "en")
    assert a == b
    assert not is_generalized_output("AGE", a.text, "UNKNOWN_RULE")
    assert not is_generalized_output("PERSON", a.text, a.rule_id)
    assert not is_generalized_output("AGE", "[AGE_BAND_37_39]", a.rule_id)
    assert not is_generalized_output("AGE", a.text + " Ada Synthetic", a.rule_id)
    date = generalize("DATE_TIME", "01.01.2020", "de")
    assert not is_generalized_output("DATE_TIME", "[YEAR_0000]", date.rule_id)
