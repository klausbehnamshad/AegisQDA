"""Strict project configuration and policy loading."""

from __future__ import annotations

from enum import StrEnum
import re
from pathlib import Path
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


APPROVED_MODEL_PAIRS = {
    "gemma3:4b": "a2af6cc3eb7fa8be8504abaf9b04e88f17a119ec3f04a3addf55f92841195f5a",
    "gemma4:e4b": "c6eb396dbd5992bbe3f5cdb947e8bbc0ee413d7c17e2beaae69f5d569cf982eb",
}


class PinnedModel(StrictModel):
    tag: str
    digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class ModelConfig(StrictModel):
    default: Literal["gemma3:4b"]
    dpo_approved_local_allowlist: list[str]
    dpo_approved_local_pairs: list[PinnedModel] = Field(default_factory=lambda: [
        PinnedModel(tag=tag, digest=digest) for tag, digest in APPROVED_MODEL_PAIRS.items()
    ])
    require_exact_ollama_tag: Literal[True]
    require_digest_binding: Literal[True]
    forbid_silent_fallback: Literal[True]

    @model_validator(mode="after")
    def exact_allowlist(self) -> "ModelConfig":
        if self.dpo_approved_local_allowlist != ["gemma3:4b", "gemma4:e4b"]:
            raise ValueError("model allowlist differs from the encoded DPO boundary")
        if (
            len(self.dpo_approved_local_pairs) != len(APPROVED_MODEL_PAIRS)
            or {item.tag: item.digest for item in self.dpo_approved_local_pairs} != APPROVED_MODEL_PAIRS
        ):
            raise ValueError("model pairs differ from the qualified local evidence")
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
    trusted_review_key_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def valid_key_ids(self) -> "AuthorizationConfig":
        if len(set(self.trusted_review_key_ids)) != len(self.trusted_review_key_ids) or any(
            re.fullmatch(r"[0-9a-f]{64}", value) is None
            for value in self.trusted_review_key_ids
        ):
            raise ValueError("trusted reviewer IDs must be unique SHA-256 fingerprints")
        return self


class GovernanceConfig(StrictModel):
    """Governance-contract wiring (PR1 declaration; PR2 enforcement).

    ``contract_version`` pins the version of docs/GOVERNANCE_CONTRACT.md this
    installation is bound to. Bumping the contract requires a signed successor
    (see the contract's §9) and an explicit config change here.

    ``trust_store_path`` is where PR2 will look for the signed trust store.
    Until the complete trust-store enforcement exists this must remain null;
    unsupported configuration fails closed rather than silently being ignored.
    The future store must live outside Git and cloud-sync locations.

    ``allow_retained_risk_claim`` mirrors the policy manifest's permission
    for the ``PROCESS_RELEASED_WITH_RETAINED_RISK`` claim. A `false` here is
    a hard strict mode. The current implementation rejects true because the
    full retained-risk authorization chain does not exist yet.

    ``two_person_release_required`` is the switch that turns on the
    four-eyes rule in PR2. It defaults to ``true`` for real-data mode; the
    current MVP forces ``real_data_enabled=false`` so this bit only
    documents the intended default, not an implemented synthetic two-person
    release. False is refused until a governed successor contract exists.
    """

    contract_version: str = "v0.1.0"
    trust_store_path: str | None = None
    allow_retained_risk_claim: bool = False
    two_person_release_required: bool = True

    @model_validator(mode="after")
    def unavailable_capabilities_fail_closed(self) -> "GovernanceConfig":
        if (
            self.contract_version != "v0.1.0"
            or self.trust_store_path is not None
            or self.allow_retained_risk_claim
            or not self.two_person_release_required
        ):
            raise ValueError("governed release capabilities are not implemented; strict defaults required")
        return self


class AppConfig(StrictModel):
    execution: ExecutionConfig
    languages: LanguageConfig
    models: ModelConfig
    privacy: PrivacyConfig
    digqda: DigQDAConfig
    authorization: AuthorizationConfig
    # Governance is optional in the YAML so the config change is
    # backward-compatible with existing installs. When absent, the default
    # ``GovernanceConfig()`` is used — the strictest safe defaults.
    governance: GovernanceConfig = Field(default_factory=GovernanceConfig)


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
