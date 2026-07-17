"""Deterministic, provenance-bound speaker-role scope filtering."""

from __future__ import annotations

import hashlib
import json

from digqda_errors import WorkflowError


def apply_role_scope(
    envelope: dict,
    role_map: dict[str, str],
    included_roles: list[str],
) -> tuple[dict, list[str]]:
    """Filter P0 units by an explicit per-case speaker-role map, fail-closed."""
    units = envelope.get("source_units")
    meta = envelope.get("meta")
    if not isinstance(units, list) or not isinstance(meta, dict):
        raise WorkflowError("P0-Envelope ist fuer Rollen-Scope ungueltig")
    unmapped = sorted({
        str(unit.get("explicit_speaker", ""))
        for unit in units
        if not isinstance(unit.get("explicit_speaker"), str)
        or unit.get("explicit_speaker") not in role_map
    })
    if unmapped:
        shown = ", ".join(label or "<fehlt>" for label in unmapped)
        raise WorkflowError("Rollen-Scope kann Sprecher nicht eindeutig zuordnen: " + shown)
    kept = [unit for unit in units if role_map[unit["explicit_speaker"]] in included_roles]
    excluded = [unit["unit_id"] for unit in units if unit not in kept]
    if not kept:
        raise WorkflowError("Rollen-Scope wuerde alle P0-Units ausschliessen")
    scope_config = {"role_map": role_map, "included_roles": included_roles}
    scope_sha = hashlib.sha256(json.dumps(
        scope_config, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")).hexdigest()
    scoped = {
        **envelope,
        "meta": {
            **meta,
            "n_units": len(kept),
            "scope_applied": True,
            "scope_sha256": scope_sha,
            "scope_included_roles": included_roles,
            "scope_full_n_units": len(units),
            "scope_excluded_n_units": len(excluded),
        },
        "source_units": kept,
    }
    return scoped, excluded
