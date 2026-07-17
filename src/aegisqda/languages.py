"""Explicit language readiness; no fallback is ever permitted."""

from __future__ import annotations

from dataclasses import dataclass
from importlib.util import find_spec

from .errors import UnsupportedLanguage


@dataclass(frozen=True)
class LanguagePack:
    code: str
    nlp_engine: str
    optional_ner_model: str | None
    synthetic_rules_ready: bool
    release_ready: bool
    reason: str


PACKS = {
    "de": LanguagePack("de", "spacy.blank:de", "de_core_news_lg", True, True, "strict custom pack"),
    "fr": LanguagePack("fr", "spacy.blank:fr", "fr_core_news_lg", True, True, "strict custom pack"),
    "en": LanguagePack("en", "spacy.blank:en", "en_core_web_lg", True, True, "strict custom pack"),
    "lb": LanguagePack(
        "lb",
        "spacy.blank:lb",
        None,
        False,
        False,
        "Luxembourgish tokenizer/NER strategy has not passed its synthetic suite",
    ),
}


def get_pack(language: str, *, require_release_ready: bool = True) -> LanguagePack:
    pack = PACKS.get(language)
    if pack is None:
        raise UnsupportedLanguage("undeclared language is blocked; no fallback is allowed")
    if require_release_ready and not pack.release_ready:
        raise UnsupportedLanguage(pack.reason)
    return pack


def model_status() -> dict[str, dict[str, object]]:
    status: dict[str, dict[str, object]] = {}
    for code, pack in PACKS.items():
        optional_installed = bool(pack.optional_ner_model and find_spec(pack.optional_ner_model))
        active_nlp = pack.optional_ner_model if optional_installed else pack.nlp_engine
        status[code] = {
            "nlp_engine": active_nlp,
            "nlp_engine_installed": find_spec("spacy") is not None,
            "optional_ner_model": pack.optional_ner_model,
            "optional_ner_model_installed": optional_installed,
            "synthetic_rules_ready": pack.synthetic_rules_ready,
            "release_ready": pack.release_ready,
            "reason": pack.reason,
        }
    return status
