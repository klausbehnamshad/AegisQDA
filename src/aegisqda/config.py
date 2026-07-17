"""Strict project configuration and policy loading."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
import re
from typing import Literal

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .errors import IntegrityError

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = ROOT / "config" / "aegisqda.local.yaml"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExecutionConfig(StrictModel):
    local_only: Literal[True]
    allow_remote_api: Literal[False]
    allow_cloud_service: Literal[False]
    ollama_base_url: str
    require_loopback: Literal[True]
    fail_on_proxy_environment: Literal[True]


class LanguageConfig(StrictModel):
    required: list[Literal["de", "fr", "lb", "en"]]
    optional: list[Literal["de", "fr", "lb", "en"]] = []
    reject_undeclared_language: Literal[True]

    @model_validator(mode="after")
    def all_required_once(self) -> "LanguageConfig":
        if set(self.required) != {"de", "fr", "en"} or len(self.required) != 3:
            raise ValueError("required languages must be exactly de, fr, en")
        if self.optional != ["lb"] or set(self.required) & set(self.optional):
            raise ValueError("optional languages must be exactly lb and disjoint from required")
        return self


class ModelConfig(StrictModel):
    default: Literal["gemma3:4b"]
    dpo_approved_local_allowlist: list[str]
    require_exact_ollama_tag: Literal[True]
    require_digest_binding: Literal[True]
    forbid_silent_fallback: Literal[True]

    @model_validator(mode="after")
    def exact_allowlist(self) -> "ModelConfig":
        if self.dpo_approved_local_allowlist != ["gemma3:4b", "gemma4:e4b"]:
            raise ValueError("model allowlist differs from the encoded DPO boundary")
        return self


class PrivacyConfig(StrictModel):
    policy: str
    default_action: Literal["block"]
    require_second_pass_scan: Literal[True]
    require_human_review: Literal[True]
    require_structural_equivalence: Literal[True]
    reversible_mapping: Literal[False]
    cross_document_linkability: Literal[False]


class DigQDAConfig(StrictModel):
    snapshot: str
    lock: str
    invoke_only_after_privacy_release: Literal[True]


class AuthorizationConfig(StrictModel):
    real_data_enabled: Literal[False]
    required_attestation_schema: Literal["aegisqda-infrastructure-attestation-v1"]
    trusted_review_key_ids: list[str]


class AppConfig(StrictModel):
    execution: ExecutionConfig
    languages: LanguageConfig
    models: ModelConfig
    privacy: PrivacyConfig
    digqda: DigQDAConfig
    authorization: AuthorizationConfig


class PolicyAction(StrEnum):
    REPLACE_AND_REVIEW = "REPLACE_AND_REVIEW"
    GENERALIZE_AND_REVIEW = "GENERALIZE_AND_REVIEW"
    BLOCK_AND_REVIEW = "BLOCK_AND_REVIEW"
    BLOCK = "BLOCK"


class ReplacementPolicy(StrictModel):
    style: Literal["typed_sequential_surrogate"]
    examples: list[str]
    stable_within_document: Literal[True]
    stable_across_documents: Literal[False]
    retain_mapping_after_release: Literal[False]


class Policy(StrictModel):
    policy_id: str = Field(pattern=r"^[A-Z0-9._-]+$")
    version: str
    default_action: Literal["BLOCK"]
    release_requirements: list[str]
    replacement: ReplacementPolicy
    entities: dict[str, PolicyAction]
    unsupported_or_ambiguous: Literal["BLOCK"]

    @model_validator(mode="after")
    def strict_release_contract(self) -> "Policy":
        expected = [
            "analyzer_completed",
            "all_detections_resolved",
            "second_pass_has_no_unresolved_findings",
            "source_structure_preserved",
            "human_reviewer_signed",
            "no_remote_endpoint_observed",
        ]
        if self.release_requirements != expected:
            raise ValueError("strict policy release requirements are incomplete or reordered")
        if any(not re.fullmatch(r"[A-Z][A-Z0-9_]*", entity) for entity in self.entities):
            raise ValueError("policy entity names must be uppercase identifiers")
        return self

    def action_for(self, entity_type: str) -> PolicyAction:
        return self.entities.get(entity_type, PolicyAction.BLOCK)


def _yaml_mapping(path: Path) -> dict[str, object]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise IntegrityError("configuration cannot be read safely") from exc
    if not isinstance(data, dict):
        raise IntegrityError("configuration root must be a mapping")
    return data


def confined_project_path(value: str) -> Path:
    candidate = (ROOT / value).resolve(strict=False)
    if not candidate.is_relative_to(ROOT):
        raise IntegrityError("configured project path escapes the repository")
    return candidate


def load_config(path: Path = DEFAULT_CONFIG) -> AppConfig:
    try:
        config = AppConfig.model_validate(_yaml_mapping(path))
    except ValueError as exc:
        raise IntegrityError("configuration schema validation failed") from exc
    confined_project_path(config.privacy.policy)
    confined_project_path(config.digqda.snapshot)
    confined_project_path(config.digqda.lock)
    return config


def load_policy(config: AppConfig) -> Policy:
    try:
        return Policy.model_validate(_yaml_mapping(confined_project_path(config.privacy.policy)))
    except ValueError as exc:
        raise IntegrityError("policy schema validation failed") from exc
