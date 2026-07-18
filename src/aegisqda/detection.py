"""Local Presidio-backed custom detection with no remote dependencies."""

from __future__ import annotations

import importlib.metadata
import importlib.util
import re
from dataclasses import asdict, dataclass
from functools import lru_cache
from typing import Iterable, Iterator

import spacy
from spacy.tokens import Span
from presidio_analyzer import AnalyzerEngine, Pattern, PatternRecognizer, RecognizerRegistry
from presidio_analyzer.nlp_engine import NlpArtifacts, NlpEngine
from presidio_analyzer.predefined_recognizers import SpacyRecognizer

from .config import Policy
from .formats.document import Document, Region
from .manifests import sha256_bytes
from .languages import PACKS

# Presidio's SpacyRecognizer.analyze (2.2.x) matches the *raw* spaCy label
# against the recognizer's supported_entities and uses it verbatim as the
# result entity_type. It does not consult CHECK_LABEL_GROUPS. The de/fr models
# emit PER/LOC/ORG and the en model emits PERSON/GPE/LOC/ORG, so these must be
# normalized to AegisQDA's policy entity names here, in the NLP engine, before
# recognition. Labels with no mapping (e.g. MISC) are intentionally dropped.
SPACY_LABEL_MAP = {
    "PER": "PERSON",
    "PERSON": "PERSON",
    "LOC": "LOCATION",
    "GPE": "LOCATION",
    "LOCATION": "LOCATION",
    "ORG": "ORGANIZATION",
    "ORGANIZATION": "ORGANIZATION",
}

# spaCy NER entity types after normalization.
NER_ENTITY_TYPES = {"PERSON", "LOCATION", "ORGANIZATION"}
# High-precision structured recognizers (regex). When one of these fully contains
# a spaCy PERSON/LOCATION/ORGANIZATION span, the NER label is a false positive
# (e.g. part of an IBAN mislabelled ORGANIZATION) and is suppressed. Partial
# overlaps remain visible so the reviewer resolves genuine ambiguity.
STRONG_STRUCTURED_TYPES = {
    "EMAIL_ADDRESS",
    "IBAN_CODE",
    "URL",
    "IP_ADDRESS",
    "PHONE_NUMBER",
    "DATE_TIME",
    "PROJECT_IDENTIFIER",
    "CREDIT_CARD",
    "MEDICAL_LICENSE",
}

# Conventional role markers at the beginning of a transcript line. They are
# structural labels, not participant initials. Keep this deliberately narrow:
# arbitrary one-letter labels remain reviewable findings.
TRANSCRIPT_ROLE_MARKERS = {"I", "P"}

# Structured field labels can themselves be misclassified by NER (for example
# the English model labels the literal word "IBAN" as ORGANIZATION). Suppress
# only when the cue directly introduces a detected structured value.
STRUCTURED_FIELD_CUES = {"IBAN": "IBAN_CODE"}


@dataclass(frozen=True)
class Finding:
    finding_id: str
    entity_type: str
    start: int
    end: int
    score: float
    recognizer: str
    action: str
    value_sha256: str

    def public_dict(self) -> dict[str, object]:
        return asdict(self)


class LocalNlpEngine(NlpEngine):
    """Language-specific local spaCy engine with optional packaged NER."""

    def __init__(self, language: str) -> None:
        self.language = language
        optional_model = PACKS[language].optional_ner_model
        if optional_model and importlib.util.find_spec(optional_model):
            self.nlp = spacy.load(optional_model)
            self.model_name = optional_model
        else:
            self.nlp = spacy.blank(language)
            self.model_name = f"spacy.blank:{language}"

    def load(self) -> None:
        return None

    def is_loaded(self) -> bool:
        return True

    def process_text(self, text: str, language: str) -> NlpArtifacts:
        doc = self.nlp(text)
        normalized_entities = [
            Span(doc, ent.start, ent.end, label=SPACY_LABEL_MAP[ent.label_])
            for ent in doc.ents
            if ent.label_ in SPACY_LABEL_MAP
        ]
        return NlpArtifacts(
            entities=normalized_entities,
            tokens=doc,
            tokens_indices=[token.idx for token in doc],
            lemmas=[token.text for token in doc],
            nlp_engine=self,
            language=language,
        )

    def process_batch(
        self,
        texts: Iterable[str],
        language: str,
        batch_size: int = 1,
        n_process: int = 1,
        **kwargs: object,
    ) -> Iterator[tuple[str, NlpArtifacts]]:
        del batch_size, n_process, kwargs
        for text in texts:
            yield text, self.process_text(text, language)

    def is_stopword(self, word: str, language: str) -> bool:
        del word, language
        return False

    def is_punct(self, word: str, language: str) -> bool:
        del language
        return bool(re.fullmatch(r"\W+", word))

    def get_supported_entities(self) -> list[str]:
        return ["PERSON", "LOCATION", "ORGANIZATION"]

    def get_supported_languages(self) -> list[str]:
        return [self.language]


COMMON_PATTERNS: dict[str, list[tuple[str, str, float]]] = {
    "EMAIL_ADDRESS": [("email", r"(?i)(?<![\w.+-])[\w.+-]+@[a-z0-9.-]+\.[a-z]{2,}(?!\w)", 0.95)],
    "URL": [("url", r"(?i)\b(?:https?://|www\.)[^\s<>\"'(),;]+", 0.9)],
    "PHONE_NUMBER": [("phone", r"(?<!\w)\+\d{1,3}(?:[ .-]?\d{2,4}){2,5}(?!\w)", 0.75)],
    "IBAN_CODE": [("iban", r"(?i)\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]){11,30}\b", 0.95)],
    "IP_ADDRESS": [("ipv4", r"\b(?:25[0-5]|2[0-4]\d|1?\d?\d)(?:\.(?:25[0-5]|2[0-4]\d|1?\d?\d)){3}\b", 0.95)],
    "PROJECT_IDENTIFIER": [("project-id", r"\b(?:CASE|PROJ|STUDY|INT)[-_][A-Z0-9-]{3,}\b", 0.8)],
    "DATE_TIME": [("date", r"(?<![\d.])(?:\d{1,2}[./-]){2}\d{2,4}(?!\d)(?!\.\d)", 0.65)],
    "AGE": [("age", r"(?i)\b\d{1,3}\s*(?:Jahre? alt|ans?|years? old|Joer al)\b", 0.65)],
    "KINSHIP": [("kinship", r"(?i)\b(?:Mutter|Vater|Schwester|Bruder|mère|père|soeur|frère|mother|father|sister|brother|Mamm|Papp)\b", 0.55)],
    "JOB_TITLE": [("job", r"(?i)\b(?:Ärztin|Arzt|Lehrerin|Lehrer|médecin|enseignant(?:e)?|doctor|teacher|Dokter|Schoulmeeschter)\b", 0.6)],
    "RARE_EVENT": [("rare-event", r"(?i)\b(?:einzige[rn]? Überlebende[rn]?|seul[e]? survivant[e]?|only survivor|eenzege?n? Iwwerliewende?n?)\b", 0.7)],
    "SMALL_PLACE": [("small-place", r"(?i)\b(?:kleine[ns]? Dorf|petit village|small village|klengt Duerf)\b", 0.6)],
}

LANGUAGE_PATTERNS: dict[str, dict[str, list[tuple[str, str, float]]]] = {
    "de": {
        "PERSON": [
            ("de-name", r"(?<=heiße ).+?(?= und wohne)", 0.9),
            ("de-title-name", r"(?-i:\b(?:Herr|Frau|Dr\.) [A-ZÄÖÜ][\wÄÖÜäöüß'-]+(?: [A-ZÄÖÜ][\wÄÖÜäöüß'-]+){0,2})", 0.8),
        ],
        "LOCATION": [("de-location", r"(?<=wohne in )[A-ZÄÖÜ][\wÄÖÜäöüß-]+", 0.85)],
        "ORGANIZATION": [
            ("de-org", r"(?-i:\b(?:[A-ZÄÖÜ][\wÄÖÜäöüß-]+ ){1,3}(?:GmbH|AG|e\.V\.)\b)", 0.8),
            ("de-cultural-org", r"(?-i:\bKulturzentrum [A-ZÄÖÜ][\wÄÖÜäöüß'-]+)", 0.9),
        ],
    },
    "fr": {
        "PERSON": [
            ("fr-name", r"(?<=m'appelle ).+?(?= et j'habite)", 0.9),
            ("fr-title-name", r"(?-i:\b(?:M\.|Mme|Dr) [A-ZÀ-ÖØ-Þ][\wÀ-ÖØ-öø-ÿ'-]+(?: [A-ZÀ-ÖØ-Þ][\wÀ-ÖØ-öø-ÿ'-]+){0,2})", 0.8),
        ],
        "LOCATION": [("fr-location", r"(?<=habite à )[A-ZÀ-ÖØ-Þ][\wÀ-ÖØ-öø-ÿ-]+", 0.85)],
        "ORGANIZATION": [
            ("fr-org", r"(?-i:\b(?:Association|Société|Université) [A-ZÀ-ÖØ-Þ][\wÀ-ÖØ-öø-ÿ'-]+)", 0.8),
            ("fr-group-org", r"(?<=groupe )[A-ZÀ-ÖØ-Þ][\wÀ-ÖØ-öø-ÿ'-]+", 0.9),
            ("fr-cultural-org", r"(?<=centre culturel )[A-ZÀ-ÖØ-Þ][\wÀ-ÖØ-öø-ÿ'-]+", 0.9),
        ],
    },
    "en": {
        "PERSON": [
            ("en-name", r"(?<=name is ).+?(?= and I live)", 0.9),
            ("en-title-name", r"(?-i:\b(?:Mr\.|Ms\.|Mrs\.|Dr\.) [A-Z][A-Za-z'-]+(?: [A-Z][A-Za-z'-]+){0,2})", 0.8),
        ],
        "LOCATION": [
            ("en-location", r"(?<=live in )[A-Z][A-Za-z-]+", 0.85),
            ("en-based-location", r"(?<=based in )[A-Z][A-Za-z-]+", 0.9),
        ],
        "ORGANIZATION": [
            ("en-org", r"(?-i:\b(?:[A-Z][A-Za-z'-]+ ){1,3}(?:Inc\.|Ltd\.|University|Foundation)\b)", 0.8),
            ("en-cultural-org", r"(?-i:\b[A-Z][A-Za-z'-]+(?= cultural centre\b))", 0.9),
        ],
    },
    "lb": {
        "PERSON": [
            ("lb-name", r"(?<=heesche ).+?(?= a wunnen)", 0.9),
            ("lb-title-name", r"(?-i:\b(?:Här|Madamm|Dr\.) [A-ZÄÖÜ][\wÄÖÜäöü'-]+(?: [A-ZÄÖÜ][\wÄÖÜäöü'-]+){0,2})", 0.8),
        ],
        "LOCATION": [("lb-location", r"(?<=wunnen zu )[A-ZÄÖÜ][\wÄÖÜäöü-]+", 0.85)],
        "ORGANIZATION": [("lb-org", r"(?-i:\b(?:Fondatioun|Universitéit) [A-ZÄÖÜ][\wÄÖÜäöü'-]+)", 0.8)],
    },
}


@lru_cache(maxsize=4)
def _engine(language: str) -> AnalyzerEngine:
    registry = RecognizerRegistry(supported_languages=[language])
    combined = dict(COMMON_PATTERNS)
    for entity, patterns in LANGUAGE_PATTERNS.get(language, {}).items():
        combined.setdefault(entity, []).extend(patterns)
    for entity, definitions in combined.items():
        registry.add_recognizer(
            PatternRecognizer(
                supported_entity=entity,
                supported_language=language,
                name=f"Aegis-{language}-{entity}",
                patterns=[Pattern(name=name, regex=regex, score=score) for name, regex, score in definitions],
            )
        )
    optional_model = PACKS[language].optional_ner_model
    if optional_model and importlib.util.find_spec(optional_model):
        registry.add_recognizer(
            SpacyRecognizer(
                supported_language=language,
                supported_entities=["PERSON", "ORGANIZATION", "LOCATION"],
                name=f"Aegis-{language}-spaCy-NER",
            )
        )
    return AnalyzerEngine(
        registry=registry,
        nlp_engine=LocalNlpEngine(language),
        supported_languages=[language],
        log_decision_process=False,
    )


def detector_versions(language: str) -> dict[str, object]:
    optional_model = PACKS[language].optional_ner_model
    installed_model = (
        optional_model if optional_model and importlib.util.find_spec(optional_model) else None
    )
    return {
        "presidio_analyzer": importlib.metadata.version("presidio-analyzer"),
        "spacy": importlib.metadata.version("spacy"),
        "nlp_strategy": installed_model or f"spacy.blank:{language}",
        "ner_model": installed_model,
        "threshold": 0.5,
        "recognizer_pack": "aegis-custom-strict-v2",
    }


def _inside_regions(start: int, end: int, regions: tuple[Region, ...]) -> bool:
    return any(start >= region.start and end <= region.end for region in regions)


def scan_document(document: Document, language: str, policy: Policy) -> list[Finding]:
    results = _engine(language).analyze(
        text=document.text,
        language=language,
        score_threshold=0.5,
        return_decision_process=False,
    )
    candidates = [item for item in results if _inside_regions(item.start, item.end, document.regions)]
    candidates.sort(key=lambda item: (item.start, -(item.end - item.start), item.entity_type))
    strong_candidates = [item for item in candidates if item.entity_type in STRONG_STRUCTURED_TYPES]
    contextual_candidates = [
        item
        for item in candidates
        if item.entity_type in NER_ENTITY_TYPES
        and not str(item.recognition_metadata.get("recognizer_name", "")).endswith("spaCy-NER")
        and float(item.score) >= 0.8
    ]
    findings: list[Finding] = []
    seen_exact: set[tuple[int, int, str]] = set()
    for item in candidates:
        if document.text[item.start:item.end].startswith("[") and document.text[item.start:item.end].endswith("]"):
            continue
        recognizer = str(item.recognition_metadata.get("recognizer_name", ""))
        is_spacy_ner = item.entity_type in NER_ENTITY_TYPES and recognizer.endswith("spaCy-NER")
        if is_spacy_ner:
            value = document.text[item.start:item.end]
            line_start = item.start == 0 or document.text[item.start - 1] == "\n"
            if (
                value in TRANSCRIPT_ROLE_MARKERS
                and line_start
                and document.text[item.end:item.end + 1] == ":"
            ):
                continue

            # A structured recognizer may overrule NER only when it fully
            # contains the NER span. Partial overlap remains visible: it could
            # include real adjacent content and therefore requires review.
            if any(
                strong.start <= item.start and item.end <= strong.end
                for strong in strong_candidates
            ):
                continue

            cue_type = STRUCTURED_FIELD_CUES.get(value.upper())
            if cue_type and any(
                strong.entity_type == cue_type
                and item.end <= strong.start
                and re.fullmatch(r"\s*:\s*", document.text[item.end:strong.start])
                for strong in strong_candidates
            ):
                continue

            # High-confidence contextual rules (e.g. "based in Esch" or
            # "centre culturel Ariston") are more specific than a generic NER
            # label. Suppress only a contained NER span, never a partial one.
            if any(
                rule.start <= item.start and item.end <= rule.end
                for rule in contextual_candidates
            ):
                continue
        # Rules and NER may independently report the same typed span. Collapse
        # only that exact duplicate; preserve all partial or cross-type overlaps
        # so ambiguity remains visible to the reviewer and blocks release.
        exact_key = (item.start, item.end, item.entity_type)
        if exact_key in seen_exact:
            continue
        seen_exact.add(exact_key)
        value = document.text[item.start:item.end]
        finding_id = f"F-{len(findings) + 1:04d}"
        findings.append(
            Finding(
                finding_id=finding_id,
                entity_type=item.entity_type,
                start=item.start,
                end=item.end,
                score=round(float(item.score), 4),
                recognizer=str(item.recognition_metadata.get("recognizer_name", "AegisRule")),
                action=policy.action_for(item.entity_type).value,
                value_sha256=sha256_bytes(value.encode()),
            )
        )
    return findings
