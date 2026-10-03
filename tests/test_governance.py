"""Tests for the PR1 governance contract module.

PR1 does NOT wire governance into the workflow. These tests pin the shape,
invariants, and helper semantics so PR2/PR3/PR4 can rely on them.
"""

from __future__ import annotations

import pytest
from dataclasses import replace
from aegisqda.config import AppConfig, load_config
from aegisqda.errors import IntegrityError
from aegisqda.governance import (
    ALLOWED_TRANSITIONS,
    CLAIM_ENVELOPE_SCHEMA,
    ClaimEnvelope,
    ClaimType,
    ModelManifest,
    PolicyManifest,
    Role,
    RoleAssignment,
    RunState,
    SignerContext,
    assert_transition,
    defined_claim_types,
    enforce_four_eyes,
    releasable_claim_types,
    weakest_claim,
)

# --------------------------------------------------------------------------- #
# Roles                                                                       #
# --------------------------------------------------------------------------- #


def test_five_roles_exactly_and_stable_names():
    """The five roles are stable identifiers; changes are governance events."""
    assert {r.value for r in Role} == {
        "REGISTER_OWNER",
        "DPO",
        "PI",
        "REVIEWER",
        "RELEASE_APPROVER",
    }


def test_role_assignment_is_active_only_within_window():
    grant = RoleAssignment(
        key_fingerprint="a" * 64,
        role=Role.REVIEWER,
        valid_from="2026-08-01T00:00:00Z",
        valid_until="2026-09-01T00:00:00Z",
        status="ACTIVE",
    )
    assert grant.is_active_at("2026-08-15T00:00:00Z")
    assert not grant.is_active_at("2026-07-31T00:00:00Z")
    assert not grant.is_active_at("2026-09-01T00:00:00Z")  # end is exclusive
    assert not grant.is_active_at("2026-09-02T00:00:00Z")


def test_role_assignment_revoked_is_never_active():
    grant = RoleAssignment(
        key_fingerprint="b" * 64,
        role=Role.REVIEWER,
        valid_from="2026-08-01T00:00:00Z",
        valid_until=None,
        status="REVOKED",
    )
    assert not grant.is_active_at("2026-08-15T00:00:00Z")


def test_role_assignment_open_ended_is_active_after_valid_from():
    grant = RoleAssignment(
        key_fingerprint="c" * 64,
        role=Role.RELEASE_APPROVER,
        valid_from="2026-08-01T00:00:00Z",
        valid_until=None,
        status="ACTIVE",
    )
    assert grant.is_active_at("2030-01-01T00:00:00Z")


# --------------------------------------------------------------------------- #
# Claim types                                                                 #
# --------------------------------------------------------------------------- #


def test_five_claim_types_exactly():
    assert {c.value for c in ClaimType} == {
        "PROCESS_RELEASED_REPLACED",
        "PROCESS_RELEASED_WITH_RETAINED_RISK",
        "BLOCKED",
        "REVIEW_UNAVAILABLE",
        "DOWNSTREAM_REVIEW_REQUIRED",
    }


def test_releasable_claim_types_are_just_the_two_process_states():
    assert releasable_claim_types() == frozenset(
        {ClaimType.PROCESS_RELEASED_REPLACED, ClaimType.PROCESS_RELEASED_WITH_RETAINED_RISK}
    )


def test_weakest_claim_prefers_blocked_over_review_unavailable():
    """Both are strength 0; the tie-breaker is BLOCKED so a run with any
    BLOCKED finding surfaces that outcome rather than the softer 'unavailable'."""
    assert (
        weakest_claim([ClaimType.REVIEW_UNAVAILABLE, ClaimType.BLOCKED])
        is ClaimType.BLOCKED
    )
    assert (
        weakest_claim([ClaimType.PROCESS_RELEASED_REPLACED, ClaimType.BLOCKED])
        is ClaimType.BLOCKED
    )


def test_weakest_claim_orders_by_strength():
    ordered = [
        ClaimType.PROCESS_RELEASED_REPLACED,
        ClaimType.PROCESS_RELEASED_WITH_RETAINED_RISK,
        ClaimType.DOWNSTREAM_REVIEW_REQUIRED,
    ]
    assert weakest_claim(ordered) is ClaimType.DOWNSTREAM_REVIEW_REQUIRED
    assert weakest_claim([ClaimType.PROCESS_RELEASED_REPLACED]) is ClaimType.PROCESS_RELEASED_REPLACED


def test_weakest_claim_rejects_empty():
    with pytest.raises(IntegrityError):
        weakest_claim([])


def test_defined_claim_types_returns_all_five():
    assert len(defined_claim_types()) == 5


# --------------------------------------------------------------------------- #
# State machine                                                               #
# --------------------------------------------------------------------------- #


def test_terminal_states_have_no_outgoing_transitions():
    assert ALLOWED_TRANSITIONS[RunState.BLOCKED] == frozenset()
    assert ALLOWED_TRANSITIONS[RunState.RESCINDED] == frozenset()


def test_released_can_only_transition_to_rescinded():
    assert ALLOWED_TRANSITIONS[RunState.RELEASED] == frozenset({RunState.RESCINDED})


def test_assert_transition_allows_documented_paths():
    assert_transition(RunState.DETECTED, RunState.UNDER_REVIEW)
    assert_transition(RunState.UNDER_REVIEW, RunState.REVIEWED)
    assert_transition(RunState.REVIEWED, RunState.PENDING_RELEASE_APPROVAL)
    assert_transition(RunState.PENDING_RELEASE_APPROVAL, RunState.RELEASED)
    assert_transition(RunState.RELEASED, RunState.RESCINDED)


def test_assert_transition_blocks_undocumented_paths():
    with pytest.raises(IntegrityError):
        assert_transition(RunState.DETECTED, RunState.RELEASED)
    with pytest.raises(IntegrityError):
        assert_transition(RunState.RELEASED, RunState.UNDER_REVIEW)
    with pytest.raises(IntegrityError):
        assert_transition(RunState.BLOCKED, RunState.UNDER_REVIEW)


def test_every_state_has_a_transitions_entry():
    """No state may fall off the map; unknown states would silently allow anything."""
    for state in RunState:
        assert state in ALLOWED_TRANSITIONS


# --------------------------------------------------------------------------- #
# Four-eyes rule                                                              #
# --------------------------------------------------------------------------- #


def _reviewer(fp: str) -> SignerContext:
    return SignerContext(key_fingerprint=fp, role=Role.REVIEWER)


def _approver(fp: str) -> SignerContext:
    return SignerContext(key_fingerprint=fp, role=Role.RELEASE_APPROVER)


def test_four_eyes_permits_distinct_correctly_roled_signers():
    enforce_four_eyes(_reviewer("a" * 64), _approver("b" * 64))


def test_four_eyes_blocks_identical_fingerprints():
    with pytest.raises(IntegrityError, match="four-eyes"):
        enforce_four_eyes(_reviewer("a" * 64), _approver("a" * 64))


def test_four_eyes_requires_reviewer_role_on_reviewer_slot():
    bad_reviewer = SignerContext(key_fingerprint="a" * 64, role=Role.DPO)
    with pytest.raises(IntegrityError, match="reviewer must hold"):
        enforce_four_eyes(bad_reviewer, _approver("b" * 64))


def test_four_eyes_requires_approver_role_on_approver_slot():
    bad_approver = SignerContext(key_fingerprint="b" * 64, role=Role.PI)
    with pytest.raises(IntegrityError, match="approver must hold"):
        enforce_four_eyes(_reviewer("a" * 64), bad_approver)


def test_four_eyes_forbids_reviewer_acting_as_approver():
    """Structural guard: a REVIEWER on the approver slot is a mis-assignment."""
    # We construct a SignerContext with role=REVIEWER on the approver slot;
    # the guard's own approver-role check catches this too, but the
    # FOUR_EYES_INCOMPATIBLE_WITH_APPROVER set is what documents the rule.
    reviewer_as_approver = SignerContext(key_fingerprint="b" * 64, role=Role.REVIEWER)
    with pytest.raises(IntegrityError):
        enforce_four_eyes(_reviewer("a" * 64), reviewer_as_approver)


# --------------------------------------------------------------------------- #
# Model and policy manifests                                                  #
# --------------------------------------------------------------------------- #


def _hex(fill: str) -> str:
    return (fill * 64)[:64]


def test_model_manifest_fingerprint_is_stable_across_key_order():
    a = ModelManifest(
        language="de",
        package_name="de_core_news_lg",
        package_version="3.7.0",
        model_tree_sha256=_hex("1"),
        meta_json_sha256=_hex("2"),
        tokenizer_config_sha256=_hex("3"),
        recognizer_pack_sha256=_hex("4"),
        threshold=0.5,
        qualification_suite_sha256=_hex("5"),
    )
    # Same content constructed identically must yield the same fingerprint.
    b = ModelManifest(**a.__dict__)
    assert a.fingerprint() == b.fingerprint()


def test_model_manifest_fingerprint_changes_when_any_field_changes():
    base = ModelManifest(
        language="de",
        package_name="de_core_news_lg",
        package_version="3.7.0",
        model_tree_sha256=_hex("1"),
        meta_json_sha256=_hex("2"),
        tokenizer_config_sha256=_hex("3"),
        recognizer_pack_sha256=_hex("4"),
        threshold=0.5,
        qualification_suite_sha256=_hex("5"),
    )
    changed = ModelManifest(**{**base.__dict__, "threshold": 0.6})
    assert base.fingerprint() != changed.fingerprint()


def test_policy_manifest_permits_matches_allowed_set():
    strict = PolicyManifest(
        policy_id="AEGIS-STRICT-LOCAL-001",
        version="0.1.0",
        policy_file_sha256=_hex("a"),
        entity_actions={"PERSON": "REPLACE_AND_REVIEW"},
        allowed_claim_types=frozenset({ClaimType.PROCESS_RELEASED_REPLACED, ClaimType.BLOCKED}),
    )
    assert strict.permits(ClaimType.PROCESS_RELEASED_REPLACED)
    assert not strict.permits(ClaimType.PROCESS_RELEASED_WITH_RETAINED_RISK)


def test_policy_manifest_fingerprint_is_key_order_insensitive():
    m = PolicyManifest(
        policy_id="AEGIS-STRICT-LOCAL-001",
        version="0.1.0",
        policy_file_sha256=_hex("a"),
        entity_actions={"PERSON": "REPLACE_AND_REVIEW", "LOCATION": "REPLACE_AND_REVIEW"},
        allowed_claim_types=frozenset({ClaimType.PROCESS_RELEASED_REPLACED}),
    )
    m_reordered = PolicyManifest(
        policy_id="AEGIS-STRICT-LOCAL-001",
        version="0.1.0",
        policy_file_sha256=_hex("a"),
        entity_actions={"LOCATION": "REPLACE_AND_REVIEW", "PERSON": "REPLACE_AND_REVIEW"},
        allowed_claim_types=frozenset({ClaimType.PROCESS_RELEASED_REPLACED}),
    )
    assert m.fingerprint() == m_reordered.fingerprint()


# --------------------------------------------------------------------------- #
# Claim envelope                                                              #
# --------------------------------------------------------------------------- #


def _envelope(**overrides) -> ClaimEnvelope:
    defaults: dict[str, object] = {
        "claim_type": ClaimType.PROCESS_RELEASED_REPLACED,
        "source_sha256": _hex("1"),
        "detection_ledger_sha256": _hex("2"),
        "review_decisions_sha256": _hex("3"),
        "policy_manifest_sha256": _permissive_manifest(
            ClaimType.PROCESS_RELEASED_REPLACED
        ).fingerprint(),
        "model_manifest_sha256": _hex("5"),
        "transformed_artifact_sha256": _hex("6"),
        "second_pass_sha256": _hex("7"),
        "retained_risk_rationale_sha256": None,
    }
    defaults.update(overrides)
    return ClaimEnvelope(**defaults)


def _permissive_manifest(*claims: ClaimType) -> PolicyManifest:
    return PolicyManifest(
        policy_id="AEGIS-TEST",
        version="0.1.0",
        policy_file_sha256=_hex("a"),
        entity_actions={"PERSON": "REPLACE_AND_REVIEW"},
        allowed_claim_types=frozenset(claims),
    )


def test_release_envelope_schema_string_pinned():
    """The schema string is public API. Changing it is a governance event."""
    assert CLAIM_ENVELOPE_SCHEMA == "aegisqda-privacy-release-v2"


def test_envelope_validates_replaced_claim():
    envelope = _envelope()
    envelope.validate(_permissive_manifest(ClaimType.PROCESS_RELEASED_REPLACED))


def test_envelope_replaced_forbids_rationale_hash():
    envelope = _envelope(retained_risk_rationale_sha256=_hex("9"))
    with pytest.raises(IntegrityError, match="replaced claim"):
        envelope.validate(_permissive_manifest(ClaimType.PROCESS_RELEASED_REPLACED))


def test_envelope_retained_risk_requires_rationale_hash():
    envelope = _envelope(
        claim_type=ClaimType.PROCESS_RELEASED_WITH_RETAINED_RISK,
        retained_risk_rationale_sha256=None,
    )
    with pytest.raises(IntegrityError, match="retained-risk claim"):
        envelope.validate(_permissive_manifest(ClaimType.PROCESS_RELEASED_WITH_RETAINED_RISK))


def test_envelope_retained_risk_ok_with_rationale():
    policy = _permissive_manifest(ClaimType.PROCESS_RELEASED_WITH_RETAINED_RISK)
    envelope = _envelope(
        claim_type=ClaimType.PROCESS_RELEASED_WITH_RETAINED_RISK,
        retained_risk_rationale_sha256=_hex("9"),
        policy_manifest_sha256=policy.fingerprint(),
    )
    envelope.validate(policy)


def test_envelope_rejects_claim_type_the_policy_forbids():
    envelope = _envelope(
        claim_type=ClaimType.PROCESS_RELEASED_WITH_RETAINED_RISK,
        retained_risk_rationale_sha256=_hex("9"),
    )
    # policy only permits REPLACED
    with pytest.raises(IntegrityError, match="does not permit"):
        envelope.validate(_permissive_manifest(ClaimType.PROCESS_RELEASED_REPLACED))


def test_envelope_rejects_non_releasable_claim_types():
    """BLOCKED / REVIEW_UNAVAILABLE / DOWNSTREAM_REVIEW_REQUIRED are not
    valid claim_type values on a release envelope; they belong on a
    separate blocked-run artifact (PR2)."""
    for non_release in (
        ClaimType.BLOCKED,
        ClaimType.REVIEW_UNAVAILABLE,
        ClaimType.DOWNSTREAM_REVIEW_REQUIRED,
    ):
        envelope = _envelope(claim_type=non_release, retained_risk_rationale_sha256=None)
        with pytest.raises(IntegrityError, match="not a releasable state"):
            envelope.validate(_permissive_manifest(non_release))


def test_envelope_rejects_non_hex_fields():
    envelope = _envelope(source_sha256="not-a-hex")
    with pytest.raises(IntegrityError, match="is not a sha256 hex"):
        envelope.validate(_permissive_manifest(ClaimType.PROCESS_RELEASED_REPLACED))


def test_envelope_rejects_unbound_policy_even_if_claim_is_allowed():
    policy = _permissive_manifest(ClaimType.PROCESS_RELEASED_REPLACED)
    changed = replace(policy, entity_actions={"PERSON": "BLOCK"})
    with pytest.raises(IntegrityError, match="policy manifest binding"):
        _envelope().validate(changed)


@pytest.mark.parametrize("rationale", ["", "not-a-hash", "A" * 64, 42])
def test_envelope_retained_risk_rejects_malformed_rationale_binding(rationale):
    policy = _permissive_manifest(ClaimType.PROCESS_RELEASED_WITH_RETAINED_RISK)
    envelope = _envelope(
        claim_type=ClaimType.PROCESS_RELEASED_WITH_RETAINED_RISK,
        retained_risk_rationale_sha256=rationale,
        policy_manifest_sha256=policy.fingerprint(),
    )
    with pytest.raises(IntegrityError, match="retained_risk_rationale_sha256"):
        envelope.validate(policy)


def test_role_assignment_handles_fractional_seconds_chronologically():
    grant = RoleAssignment(
        key_fingerprint="a" * 64, role=Role.REVIEWER,
        valid_from="2026-08-01T00:00:00.1Z", valid_until="2026-08-01T00:00:01Z",
        status="ACTIVE",
    )
    assert not grant.is_active_at("2026-08-01T00:00:00Z")
    assert grant.is_active_at("2026-08-01T00:00:00.10Z")
    assert grant.is_active_at("2026-08-01T00:00:00.9Z")
    assert not grant.is_active_at("2026-08-01T00:00:01.0Z")


@pytest.mark.parametrize("timestamp", [
    "2026-08-01", "2026-08-01T00:00:00+02:00", "2026-02-30T00:00:00Z",
    "2026-08-01T00:00:60Z", "2026-08-01T00:00:00.0000001Z", "",
])
def test_role_assignment_rejects_invalid_timestamp_instead_of_authorizing(timestamp):
    grant = RoleAssignment(
        "a" * 64, Role.REVIEWER, "2026-08-01T00:00:00Z", None, "ACTIVE"
    )
    with pytest.raises(IntegrityError, match="timestamp"):
        grant.is_active_at(timestamp)


@pytest.mark.parametrize("overrides", [
    {"key_fingerprint": ""}, {"role": "REVIEWER"}, {"status": "UNKNOWN"},
    {"valid_from": "2026-99-01T00:00:00Z"},
    {"valid_until": "2026-07-01T00:00:00Z"},
    {"valid_until": "2026-08-01T00:00:00.000Z"},
])
def test_role_assignment_rejects_invalid_grant_structure(overrides):
    values = dict(
        key_fingerprint="a" * 64, role=Role.REVIEWER, valid_from="2026-08-01T00:00:00Z",
        valid_until=None, status="ACTIVE",
    )
    with pytest.raises(IntegrityError):
        RoleAssignment(**{**values, **overrides})


@pytest.mark.parametrize("overrides", [
    {"model_tree_sha256": "bad"}, {"qualification_suite_sha256": "F" * 64},
    {"threshold": float("nan")}, {"threshold": float("inf")}, {"threshold": True},
    {"threshold": -0.1}, {"threshold": 1.1}, {"package_name": ""}, {"language": "unknown"},
])
def test_model_manifest_cannot_fingerprint_invalid_identity(overrides):
    values = dict(
        language="de", package_name="de_core_news_lg", package_version="3.7.0",
        model_tree_sha256="a" * 64, meta_json_sha256="b" * 64,
        tokenizer_config_sha256="c" * 64, recognizer_pack_sha256="d" * 64,
        threshold=0.5, qualification_suite_sha256="e" * 64,
    )
    with pytest.raises(IntegrityError):
        ModelManifest(**{**values, **overrides}).fingerprint()


@pytest.mark.parametrize("overrides", [
    {"policy_file_sha256": "bad"}, {"allowed_claim_types": frozenset({"BLOCKED"})},
    {"allowed_claim_types": frozenset()}, {"entity_actions": {"person": "REPLACE_AND_REVIEW"}},
    {"entity_actions": {"PERSON": "KEEP_AND_REVIEW"}}, {"policy_id": "lowercase"},
])
def test_policy_manifest_cannot_fingerprint_unchecked_values(overrides):
    manifest = _permissive_manifest(ClaimType.PROCESS_RELEASED_REPLACED)
    with pytest.raises(IntegrityError):
        replace(manifest, **overrides).fingerprint()


def test_raw_strings_cannot_bypass_typed_governance_guards():
    with pytest.raises(IntegrityError):
        weakest_claim(["BLOCKED"])
    with pytest.raises(IntegrityError):
        assert_transition("DETECTED", "UNDER_REVIEW")
    with pytest.raises(IntegrityError):
        SignerContext("a" * 64, "REVIEWER")
    with pytest.raises(IntegrityError):
        _envelope(claim_type="PROCESS_RELEASED_REPLACED").validate(
            _permissive_manifest(ClaimType.PROCESS_RELEASED_REPLACED)
        )


# --------------------------------------------------------------------------- #
# Config: governance section defaults                                         #
# --------------------------------------------------------------------------- #


def test_load_config_populates_governance_section_with_safe_defaults():
    """The YAML now carries a governance block; when absent, defaults apply.

    The strictest safe defaults are: retained-risk claim forbidden,
    four-eyes required. These are what a fresh install lands on.
    """
    config = load_config()
    assert isinstance(config, AppConfig)
    assert config.governance.two_person_release_required is True
    # Strictest default: retained-risk claim is off unless explicitly enabled.
    # The shipped config sets it false; the schema also defaults to false.
    assert config.governance.allow_retained_risk_claim is False
    # Contract version is pinned to the docs it was reviewed against.
    assert config.governance.contract_version == "v0.1.0"
