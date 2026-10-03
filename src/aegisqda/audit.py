"""Read-only audit of existing runs against the current recognizer pack.

Runs scanned with a revoked pack cannot continue (see ``stale_pack_reason``).
This audit tells the operator which runs that concerns and, for runs that were
already privacy-released, whether the current detector finds identifiers in the
released text. It writes nothing and reports no source text: only run names,
opaque case IDs, states, counts and entity types.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Any

from .config import Policy, load_config, load_policy
from .detection import RECOGNIZER_PACK, REVOKED_RECOGNIZER_PACKS, SURROGATE_RE, scan_document
from .errors import AegisError, BoundaryError
from .formats.document import parse_document
from .local_boundary import reject_proxy_environment
from .manifests import sha256_file, verify_seal
from .safeio import load_json, validate_run_dir, validate_run_root
from .workflow import DETECTION_FILE, LEDGER_FILE, RELEASE_FILE, REVIEW_FILE, utc_now

# Verdicts that leave the operator something to do.
ACTION_VERDICTS = {"AFFECTED", "RESCAN_REQUIRED", "INVALID"}


def _state(run_dir: Path, detection: dict[str, Any]) -> str:
    if (run_dir / "digqda-run.json").is_file():
        return "ANALYZED"
    if (run_dir / RELEASE_FILE).is_file():
        return "PRIVACY_RELEASED"
    if (run_dir / REVIEW_FILE).is_file():
        return "REVIEWED"
    return str(detection.get("state"))


def _recheck_release(run_dir: Path, language: str, policy: Policy) -> dict[str, Any]:
    """Re-run the second pass over released text with the current detector."""
    release = load_json(run_dir / RELEASE_FILE)
    review = load_json(run_dir / REVIEW_FILE)
    ledger = load_json(run_dir / LEDGER_FILE)
    second_pass = load_json(run_dir / "second-pass.json")
    for artifact in (release, review, ledger, second_pass):
        verify_seal(artifact)
    transformed_file = release.get("transformed_file")
    if transformed_file not in {"transformed.srt", "transformed.txt"}:
        return {"verdict": "INVALID", "reason": "release names no transformed source"}
    transformed = run_dir / str(transformed_file)
    if release.get("transformed_sha256") != sha256_file(transformed):
        return {"verdict": "INVALID", "reason": "released text does not match its release"}
    try:
        document = parse_document(transformed)
    except AegisError:
        return {
            "verdict": "AFFECTED",
            "reason": "released text fails the current parser (e.g. Unicode line separators)",
        }
    # Exempt what AegisQDA itself wrote: the recorded surrogate ranges plus any
    # surrogate-shaped token (older releases did not record ranges).
    ranges = [
        (bounds[0], bounds[1])
        for bounds in second_pass.get("surrogate_ranges", [])
        if isinstance(bounds, list) and len(bounds) == 2
    ]
    ranges += [match.span() for match in SURROGATE_RE.finditer(document.text)]
    by_id = {
        item.get("finding_id"): item for item in ledger.get("findings", []) if isinstance(item, dict)
    }
    exempt = {
        (str(by_id[d["finding_id"]].get("entity_type")), str(by_id[d["finding_id"]].get("value_sha256")))
        for d in review.get("decisions", [])
        if isinstance(d, dict) and d.get("decision") == "FALSE_POSITIVE" and d.get("finding_id") in by_id
    }
    unresolved = [
        finding
        for finding in scan_document(document, language, policy)
        if (finding.entity_type, finding.value_sha256) not in exempt
        and not any(start <= finding.start and finding.end <= end for start, end in ranges)
    ]
    if unresolved:
        return {
            "verdict": "AFFECTED",
            "unresolved_count": len(unresolved),
            "unresolved_types": sorted({finding.entity_type for finding in unresolved}),
        }
    return {"verdict": "NO_FINDINGS_UNDER_CURRENT_DETECTOR", "unresolved_count": 0}


def audit_run(run_dir: Path, policy: Policy) -> dict[str, Any]:
    entry: dict[str, Any] = {"run": f"{run_dir.parent.name}/{run_dir.name}"}
    try:
        run_dir = validate_run_dir(run_dir)
        detection = load_json(run_dir / DETECTION_FILE)
        verify_seal(detection)
    except AegisError:
        entry.update(verdict="INVALID", reason="detection artifact is missing or fails its integrity check")
        return entry
    detector = detection.get("detector")
    pack = detector.get("recognizer_pack") if isinstance(detector, dict) else None
    state = _state(run_dir, detection)
    entry.update(
        case_id=detection.get("case_id"),
        language=detection.get("language"),
        recognizer_pack=pack,
        advisory=REVOKED_RECOGNIZER_PACKS.get(str(pack)),
        state=state,
    )
    if pack == RECOGNIZER_PACK:
        entry["verdict"] = "CURRENT"
    elif state not in {"PRIVACY_RELEASED", "ANALYZED"}:
        entry["verdict"] = "RESCAN_REQUIRED"
    else:
        try:
            entry.update(_recheck_release(run_dir, str(detection.get("language")), policy))
        except AegisError:
            entry.update(verdict="INVALID", reason="release artifacts are missing or fail their integrity check")
    return entry


def audit_runs(run_root: Path) -> tuple[dict[str, Any], bool]:
    """Audit every run under run_root; the flag is True when no run needs action."""
    reject_proxy_environment()
    root = validate_run_root(run_root)
    if not root.is_dir():
        raise BoundaryError("run root does not exist")
    policy = load_policy(load_config())
    runs = [
        audit_run(run_dir, policy)
        for run_dir in sorted(root.glob("*/run-*"))
        if run_dir.is_dir() and not run_dir.is_symlink() and re.fullmatch(r"run-\w+", run_dir.name)
    ]
    report: dict[str, Any] = {
        "schema": "aegisqda-run-audit-v1",
        "audited_at": utc_now(),
        "recognizer_pack": RECOGNIZER_PACK,
        "revoked_recognizer_packs": REVOKED_RECOGNIZER_PACKS,
        "summary": dict(sorted(Counter(run["verdict"] for run in runs).items())),
        "runs": runs,
    }
    return report, not any(run["verdict"] in ACTION_VERDICTS for run in runs)
