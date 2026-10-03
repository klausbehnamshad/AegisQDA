"""Governance contract: roles, claim types, state machine, model/policy manifests.

PR1 delivers the *contract*: types, invariants, and hash-binding helpers that
downstream PRs (PR2 trusted two-person release, PR3 finding semantics,
PR4 operational assurance) will wire into the workflow. This module does NOT
change any existing release path yet; it introduces the vocabulary the rest of
the pipeline will be refactored to speak.

Design invariants (see docs/GOVERNANCE_CONTRACT.md):
    * Roles are separations of duty, not people. A person may hold at most one
      role per Run at the moment of signing.
    * A ``Run`` may not use the same key fingerprint for the primary review and
      for release approval (four-eyes rule enforced at the signature layer;
      wiring lands in PR2).
    * A DigQDA ``PASS`` remains downstream evidence only; the terminal
      governance state stays ``DOWNSTREAM_REVIEW_REQUIRED``. This module never
      exposes a transition that upgrades a downstream PASS to
      ``PROCESS_RELEASED_*``.
    * Claim types are the ONLY vocabulary released artifacts use to describe
      what was done. The free-text ``release_claim`` string from
      privacy-release-v1 remains for humans but is no longer authoritative once
      privacy-release-v2 is wired in PR2.
    * Mixed-document rule: the manifest-level claim is the weakest claim any
      finding within the manifest carries. Per-finding decisions remain
      auditable.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
import math
import re
from typing import Any

from .errors import IntegrityError
from .manifests import canonical_bytes, sha256_bytes


def _validate_sha256(label: str, value: object) -> None:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise IntegrityError(f"{label} is not a sha256 hex")


def _utc_timestamp(value: object) -> datetime:
    """Parse a valid UTC instant instead of comparing timestamp spellings."""
    if not isinstance(value, str) or re.fullmatch(
        r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?Z", value
    ) is None:
        raise IntegrityError("governance timestamp must be an RFC3339 UTC instant")
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise IntegrityError("governance timestamp is not a valid UTC instant") from exc

# --------------------------------------------------------------------------- #
# Roles                                                                       #
# --------------------------------------------------------------------------- #


class Role(StrEnum):
    """The five governance roles defined in docs/GOVERNANCE_CONTRACT.md.

    A person may hold more than one role over time (e.g. deputise), but never
    two roles on the same run at the same signing moment. Role assignments are
    per-run and per-key-fingerprint, not per-person: the trust store maps
    key fingerprints to roles at a specific validity window.
    """

    REGISTER_OWNER = "REGISTER_OWNER"
    DPO = "DPO"
    PI = "PI"
    REVIEWER = "REVIEWER"
    RELEASE_APPROVER = "RELEASE_APPROVER"


# Roles that are structurally forbidden from also being release approver on the
# same run (four-eyes rule). Kept explicit so the guard reads at the call site.
FOUR_EYES_INCOMPATIBLE_WITH_APPROVER: frozenset[Role] = frozenset({Role.REVIEWER})


@dataclass(frozen=True)
class RoleAssignment:
    """One (key_fingerprint, role) grant with a validity window.

    The trust store is a list of these entries plus a monotonic serial number
    and a ``previous_sha256`` chain link. PR2 implements the persistence and
    signed distribution of the trust store; PR1 only defines the shape.

    ``key_fingerprint`` is the sha256 of the Ed25519 public key raw bytes, i.e.
    what ``review_signature.sign_review`` already emits as ``key_id_sha256``.

    ``valid_from`` / ``valid_until`` are RFC3339 UTC strings; ``None`` on
    ``valid_until`` means "still active". A revoked key is expressed by an
    explicit later trust-store entry with ``status=REVOKED`` overriding the
    ``ACTIVE`` grant; the module does not mutate prior grants.
    """

    key_fingerprint: str
    role: Role
    valid_from: str
    valid_until: str | None
    status: str  # "ACTIVE" or "REVOKED"

    def __post_init__(self) -> None:
        _validate_sha256("role key_fingerprint", self.key_fingerprint)
        if (
            not isinstance(self.role, Role) or not isinstance(self.status, str)
            or self.status not in {"ACTIVE", "REVOKED"}
        ):
            raise IntegrityError("role assignment has an unknown role or status")
        start = _utc_timestamp(self.valid_from)
        if self.valid_until is not None and _utc_timestamp(self.valid_until) <= start:
            raise IntegrityError("role validity window must have a strictly later end")

    def is_active_at(self, timestamp: str) -> bool:
        """Return whether this grant is active at the given RFC3339 timestamp.

        A grant is active iff status is ``ACTIVE`` and ``valid_from`` is not
        after ``timestamp`` and (``valid_until`` is ``None`` or after
        ``timestamp``). Validated UTC instants are compared chronologically,
        including fractional seconds. Timestamps ARE part of the signed payload.
        """
        instant = _utc_timestamp(timestamp)
        if self.status != "ACTIVE":
            return False
        if instant < _utc_timestamp(self.valid_from):
            return False
        return not (
            self.valid_until is not None and instant >= _utc_timestamp(self.valid_until)
        )


# --------------------------------------------------------------------------- #
# Claim types                                                                 #
# --------------------------------------------------------------------------- #


class ClaimType(StrEnum):
    """The vocabulary a release artifact may claim about its transformation.

    The three positive states are ordered by strength:
        1. PROCESS_RELEASED_REPLACED  — strongest: every confirmed identifier
           was replaced by a typed surrogate or genuinely generalized.
        2. PROCESS_RELEASED_WITH_RETAINED_RISK — at least one finding was
           deliberately kept (``KEEP_AND_REVIEW`` in PR3). Requires an
           explicit retained-risk rationale bound into the release.
        3. BLOCKED — no release; the run terminates.

    Two operational states are also encoded:
        * REVIEW_UNAVAILABLE — reviewer or approver role not currently
          staffed. This is neither a release nor an emergency waiver: it
          just says the run cannot progress.
        * DOWNSTREAM_REVIEW_REQUIRED — the current terminal state after a
          DigQDA PASS; retained verbatim so this module does not silently
          alter existing semantics.
    """

    PROCESS_RELEASED_REPLACED = "PROCESS_RELEASED_REPLACED"
    PROCESS_RELEASED_WITH_RETAINED_RISK = "PROCESS_RELEASED_WITH_RETAINED_RISK"
    BLOCKED = "BLOCKED"
    REVIEW_UNAVAILABLE = "REVIEW_UNAVAILABLE"
    DOWNSTREAM_REVIEW_REQUIRED = "DOWNSTREAM_REVIEW_REQUIRED"


# Strength order for the weakest-claim-wins mixed-document rule. Values are
# only compared inside this module; lower strength wins the manifest header.
_CLAIM_STRENGTH: dict[ClaimType, int] = {
    ClaimType.BLOCKED: 0,
    ClaimType.REVIEW_UNAVAILABLE: 0,
    ClaimType.DOWNSTREAM_REVIEW_REQUIRED: 1,
    ClaimType.PROCESS_RELEASED_WITH_RETAINED_RISK: 2,
    ClaimType.PROCESS_RELEASED_REPLACED: 3,
}


def weakest_claim(claims: Iterable[ClaimType]) -> ClaimType:
    """Return the weakest claim from a non-empty iterable.

    Enforces the mixed-document rule: a manifest that aggregates multiple
    finding-level decisions inherits the weakest one at the header. ``BLOCKED``
    and ``REVIEW_UNAVAILABLE`` are tied at strength 0; the tie is broken in
    favour of ``BLOCKED`` because a run that contains any BLOCKED finding must
    surface that outcome rather than the softer "unavailable".
    """
    materialised = list(claims)
    if not materialised:
        raise IntegrityError("weakest_claim requires at least one claim")
    if any(not isinstance(claim, ClaimType) for claim in materialised):
        raise IntegrityError("weakest_claim requires defined claim types")
    weakest = min(materialised, key=lambda claim: _CLAIM_STRENGTH[claim])
    if weakest is ClaimType.REVIEW_UNAVAILABLE and ClaimType.BLOCKED in materialised:
        return ClaimType.BLOCKED
    return weakest


# --------------------------------------------------------------------------- #
# State machine                                                               #
# --------------------------------------------------------------------------- #


class RunState(StrEnum):
    """Coarse-grained states a governed run can hold.

    This is the outer envelope state, complementary to the existing artifact
    schemas' ``state`` fields (``REVIEW_REQUIRED``, ``ACCEPTED``,
    ``PRIVACY_RELEASED``). PR2 wires the outer state into privacy-release-v2.
    """

    DETECTED = "DETECTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    REVIEW_UNAVAILABLE = "REVIEW_UNAVAILABLE"
    REVIEWED = "REVIEWED"
    PENDING_RELEASE_APPROVAL = "PENDING_RELEASE_APPROVAL"
    RELEASED = "RELEASED"
    BLOCKED = "BLOCKED"
    RESCINDED = "RESCINDED"  # PR4 introduces the revocation registry


# Allowed transitions. Anything not listed is a hard error and must never be
# permitted implicitly. The state machine is intentionally sparse: it does not
# encode intra-review branching (which lives in workflow.py); it encodes the
# outer governance envelope.
ALLOWED_TRANSITIONS: dict[RunState, frozenset[RunState]] = {
    RunState.DETECTED: frozenset({RunState.UNDER_REVIEW, RunState.REVIEW_UNAVAILABLE, RunState.BLOCKED}),
    RunState.UNDER_REVIEW: frozenset({RunState.REVIEWED, RunState.BLOCKED, RunState.REVIEW_UNAVAILABLE}),
    RunState.REVIEW_UNAVAILABLE: frozenset({RunState.UNDER_REVIEW, RunState.BLOCKED}),
    RunState.REVIEWED: frozenset({RunState.PENDING_RELEASE_APPROVAL, RunState.BLOCKED}),
    RunState.PENDING_RELEASE_APPROVAL: frozenset({RunState.RELEASED, RunState.BLOCKED}),
    RunState.RELEASED: frozenset({RunState.RESCINDED}),
    RunState.BLOCKED: frozenset(),  # Terminal by design; a new run is a new envelope.
    RunState.RESCINDED: frozenset(),
}


def assert_transition(current: RunState, next_state: RunState) -> None:
    """Raise IntegrityError if the transition is not permitted."""
    if not isinstance(current, RunState) or not isinstance(next_state, RunState):
        raise IntegrityError("run-state transition requires defined states")
    permitted = ALLOWED_TRANSITIONS[current]
    if next_state not in permitted:
        raise IntegrityError(
            f"forbidden run-state transition: {current.value} -> {next_state.value}"
        )


# --------------------------------------------------------------------------- #
# Policy and model manifest bindings                                          #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ModelManifest:
    """Signed record of a language model's exact deployed identity.

    PR1 defines the shape; PR4 wires actual hash computation over model tree
    files. The workflow will require an equality check between the manifest
    the trust store approves and the manifest the detector loads at scan
    time. A mismatch is a hard BLOCK.

    ``qualification_suite_sha256`` is the fingerprint of the pass/fail suite
    the manifest was qualified against (the annotated interview suite for
    de/fr/en; the future code-switching suite for CHILDLUX). A manifest is
    only trustworthy in combination with the suite it survived.
    """

    language: str
    package_name: str
    package_version: str
    model_tree_sha256: str  # sha256 of a stable serialisation of the model dir
    meta_json_sha256: str
    tokenizer_config_sha256: str
    recognizer_pack_sha256: str
    threshold: float
    qualification_suite_sha256: str

    def validate(self) -> None:
        if not isinstance(self.language, str) or self.language not in {"de", "fr", "en", "lb"}:
            raise IntegrityError("model manifest has an unsupported language")
        if any(
            not isinstance(value, str) or not value.strip()
            for value in (self.package_name, self.package_version)
        ):
            raise IntegrityError("model manifest requires a package identity")
        if (
            isinstance(self.threshold, bool)
            or not isinstance(self.threshold, (int, float))
            or not math.isfinite(self.threshold)
            or not 0 <= self.threshold <= 1
        ):
            raise IntegrityError("model manifest threshold must be finite and between zero and one")
        for label in (
            "model_tree_sha256", "meta_json_sha256", "tokenizer_config_sha256",
            "recognizer_pack_sha256", "qualification_suite_sha256",
        ):
            _validate_sha256(f"model manifest {label}", getattr(self, label))

    def canonical(self) -> dict[str, Any]:
        """Deterministic dict for hashing/signing (all values sorted by key)."""
        self.validate()
        return {
            "language": self.language,
            "meta_json_sha256": self.meta_json_sha256,
            "model_tree_sha256": self.model_tree_sha256,
            "package_name": self.package_name,
            "package_version": self.package_version,
            "qualification_suite_sha256": self.qualification_suite_sha256,
            "recognizer_pack_sha256": self.recognizer_pack_sha256,
            "threshold": self.threshold,
            "tokenizer_config_sha256": self.tokenizer_config_sha256,
        }

    def fingerprint(self) -> str:
        """Stable sha256 fingerprint of the manifest, suitable for release binding."""
        return sha256_bytes(canonical_bytes(self.canonical()))


@dataclass(frozen=True)
class PolicyManifest:
    """Signed record of a policy's exact identity at release time.

    The current release envelope already binds ``policy_sha256`` from the raw
    YAML file. PolicyManifest adds two things PR2/PR3 will need:
        * the ``entity_actions`` map as a canonical dict, so a policy change
          that keeps the file hash stable (e.g. YAML re-ordering) still
          produces a stable manifest, and
        * the ``allowed_claim_types`` set: a policy may forbid
          ``PROCESS_RELEASED_WITH_RETAINED_RISK`` (strict policies) or allow
          it (interview policies).
    """

    policy_id: str
    version: str
    policy_file_sha256: str
    entity_actions: dict[str, str]
    allowed_claim_types: frozenset[ClaimType]

    def validate(self) -> None:
        if not isinstance(self.policy_id, str) or re.fullmatch(r"[A-Z0-9._-]+", self.policy_id) is None:
            raise IntegrityError("policy manifest requires a valid policy identity")
        if not isinstance(self.version, str) or not self.version.strip():
            raise IntegrityError("policy manifest requires a version")
        _validate_sha256("policy manifest policy_file_sha256", self.policy_file_sha256)
        if not isinstance(self.entity_actions, dict) or any(
            not isinstance(entity, str) or re.fullmatch(r"[A-Z][A-Z0-9_]*", entity) is None
            or not isinstance(action, str) or action not in {
                "REPLACE_AND_REVIEW", "GENERALIZE_AND_REVIEW", "BLOCK_AND_REVIEW", "BLOCK",
            }
            for entity, action in self.entity_actions.items()
        ):
            raise IntegrityError("policy manifest contains an unsupported entity action")
        if not isinstance(self.allowed_claim_types, frozenset) or not self.allowed_claim_types or any(
            not isinstance(claim, ClaimType) for claim in self.allowed_claim_types
        ):
            raise IntegrityError("policy manifest requires defined allowed claim types")

    def canonical(self) -> dict[str, Any]:
        self.validate()
        return {
            "allowed_claim_types": sorted(claim.value for claim in self.allowed_claim_types),
            "entity_actions": dict(sorted(self.entity_actions.items())),
            "policy_file_sha256": self.policy_file_sha256,
            "policy_id": self.policy_id,
            "version": self.version,
        }

    def fingerprint(self) -> str:
        return sha256_bytes(canonical_bytes(self.canonical()))

    def permits(self, claim: ClaimType) -> bool:
        self.validate()
        if not isinstance(claim, ClaimType):
            raise IntegrityError("policy permission requires a defined claim type")
        return claim in self.allowed_claim_types


# --------------------------------------------------------------------------- #
# Claim envelope (schema v2 payload, wiring in PR2)                           #
# --------------------------------------------------------------------------- #

CLAIM_ENVELOPE_SCHEMA = "aegisqda-privacy-release-v2"


@dataclass(frozen=True)
class ClaimEnvelope:
    """Payload the v2 release manifest carries under its ``claim`` key.

    Every field below is signed. Any change to any bound hash after signing
    invalidates the envelope. PR2 wires the reviewer signature; PR2 also
    adds a *second* signature from the release approver (four-eyes). This
    dataclass is intentionally hash-only: no clear-text identifiers.
    """

    claim_type: ClaimType
    source_sha256: str
    detection_ledger_sha256: str
    review_decisions_sha256: str
    policy_manifest_sha256: str
    model_manifest_sha256: str
    transformed_artifact_sha256: str
    second_pass_sha256: str
    retained_risk_rationale_sha256: str | None  # required iff RETAINED_RISK

    def canonical(self) -> dict[str, Any]:
        if not isinstance(self.claim_type, ClaimType):
            raise IntegrityError("envelope requires a defined claim type")
        return {
            "claim_type": self.claim_type.value,
            "detection_ledger_sha256": self.detection_ledger_sha256,
            "model_manifest_sha256": self.model_manifest_sha256,
            "policy_manifest_sha256": self.policy_manifest_sha256,
            "retained_risk_rationale_sha256": self.retained_risk_rationale_sha256,
            "review_decisions_sha256": self.review_decisions_sha256,
            "second_pass_sha256": self.second_pass_sha256,
            "source_sha256": self.source_sha256,
            "transformed_artifact_sha256": self.transformed_artifact_sha256,
        }

    def validate(self, policy_manifest: PolicyManifest) -> None:
        """Raise IntegrityError on any invariant violation.

        Enforces:
            * the policy permits this claim type,
            * RETAINED_RISK requires a bound rationale hash,
            * REPLACED forbids a rationale hash (a rationale on REPLACED would
              suggest hidden retained risk not surfaced by the claim type),
            * every bound hash looks like a lowercase sha256 hex.
            * the policy manifest fingerprint matches the bound policy hash.

        This is structural validation, not signature/trust verification, nor
        evidence that findings were transformed. The release path must bind
        and verify those independently before emitting any process claim.
        """
        if not isinstance(self.claim_type, ClaimType):
            raise IntegrityError("envelope requires a defined claim type")
        if not policy_manifest.permits(self.claim_type):
            raise IntegrityError(
                f"policy {policy_manifest.policy_id} does not permit claim {self.claim_type.value}"
            )
        if self.claim_type is ClaimType.PROCESS_RELEASED_WITH_RETAINED_RISK:
            if self.retained_risk_rationale_sha256 is None:
                raise IntegrityError("retained-risk claim requires a rationale binding")
        elif self.claim_type is ClaimType.PROCESS_RELEASED_REPLACED:
            if self.retained_risk_rationale_sha256 is not None:
                raise IntegrityError("replaced claim must not carry a retained-risk rationale")
        else:
            raise IntegrityError(
                f"claim_type {self.claim_type.value} is not a releasable state"
            )
        for label, value in self.canonical().items():
            if label == "claim_type" or (label == "retained_risk_rationale_sha256" and value is None):
                continue
            _validate_sha256(f"envelope field {label}", value)
        if self.policy_manifest_sha256 != policy_manifest.fingerprint():
            raise IntegrityError("envelope policy manifest binding does not match")


# --------------------------------------------------------------------------- #
# Four-eyes guard                                                             #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class SignerContext:
    """Identity of a signer at a specific run stage."""

    key_fingerprint: str
    role: Role

    def __post_init__(self) -> None:
        _validate_sha256("signer key_fingerprint", self.key_fingerprint)
        if not isinstance(self.role, Role):
            raise IntegrityError("signer context requires a defined role")


def enforce_four_eyes(reviewer: SignerContext, approver: SignerContext) -> None:
    """Raise IntegrityError if reviewer and approver share a fingerprint.

    The guard also rejects the trivial mis-assignment where the approver is
    tagged as REVIEWER. PR2 wires this guard into the release path; PR1 keeps
    the invariant colocated with the vocabulary it protects so it cannot be
    forgotten when the wiring lands.
    """
    if reviewer.key_fingerprint == approver.key_fingerprint:
        raise IntegrityError("four-eyes rule: reviewer and approver keys must differ")
    if approver.role in FOUR_EYES_INCOMPATIBLE_WITH_APPROVER:
        raise IntegrityError(
            f"role {approver.role.value} may not act as release approver on the same run"
        )
    if approver.role is not Role.RELEASE_APPROVER:
        raise IntegrityError("approver must hold the RELEASE_APPROVER role")
    if reviewer.role is not Role.REVIEWER:
        raise IntegrityError("reviewer must hold the REVIEWER role")


# --------------------------------------------------------------------------- #
# Introspection helpers (used by tests and CLI in later PRs)                  #
# --------------------------------------------------------------------------- #


def defined_claim_types() -> list[ClaimType]:
    """Return the full ordered list of claim types."""
    return list(ClaimType)


def releasable_claim_types() -> frozenset[ClaimType]:
    """Claim types that represent an actual release (as opposed to a stop)."""
    return frozenset(
        {ClaimType.PROCESS_RELEASED_REPLACED, ClaimType.PROCESS_RELEASED_WITH_RETAINED_RISK}
    )
