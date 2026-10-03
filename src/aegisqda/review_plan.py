"""Source-free planning for overlaps among current, source-bound detections.

This does not resolve a finding, suppress an interval, or authorize a transform
or release. Each overlap edge concerns real atomic content segments, not the
bounding envelope of a projected multi-line mention.
"""

from __future__ import annotations

import heapq
import json
from pathlib import Path
import re
from typing import Any

from .config import ROOT, PolicyAction
from .errors import IntegrityError
from .manifests import canonical_bytes, sha256_bytes
from .safeio import read_stable_source, resolved_no_symlink, validate_run_dir
from .workflow import DETECTION_FILE, LEDGER_FILE, _finding_segments, _load_detection

SCHEMA = "aegisqda-review-plan-v1"
FINDING_ID = re.compile(r"F-[0-9]{4,}\Z")


def _read(path: Path) -> bytes:
    return read_stable_source(resolved_no_symlink(path))


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise IntegrityError("review planning artifact contains duplicate JSON keys")
        result[key] = value
    return result


class _Components:
    def __init__(self, count: int) -> None:
        self.parent = list(range(count))
        self.size = [1] * count

    def find(self, index: int) -> int:
        while self.parent[index] != index:
            self.parent[index] = self.parent[self.parent[index]]
            index = self.parent[index]
        return index

    def union(self, left: int, right: int) -> None:
        left, right = self.find(left), self.find(right)
        if left == right:
            return
        if self.size[left] < self.size[right]:
            left, right = right, left
        self.parent[right] = left
        self.size[left] += self.size[right]


def _overlap_components(intervals: list[tuple[int, int, int]], count: int) -> _Components:
    components = _Components(count)
    active: dict[int, int] = {}
    ends: list[tuple[int, int]] = []
    for interval_id, (start, end, index) in enumerate(sorted(intervals)):
        while ends and ends[0][0] <= start:
            _, expired_id = heapq.heappop(ends)
            del active[expired_id]
        # All retained intervals begin no later than start and end after it.
        # These are actual overlap edges; adjacent endpoints never enter here.
        for other in active.values():
            components.union(index, other)
        active[interval_id] = index
        heapq.heappush(ends, (end, interval_id))
    return components


def review_plan(run_dir: Path) -> dict[str, Any]:
    """Plan actual overlap components without changing a protected artifact."""
    try:
        return _review_plan(validate_run_dir(run_dir))
    except (OSError, KeyError, TypeError, ValueError) as exc:
        raise IntegrityError("review planning requires valid current source-bound artifacts") from exc


def _review_plan(run_dir: Path) -> dict[str, Any]:
    before = {
        run_dir / DETECTION_FILE: _read(run_dir / DETECTION_FILE),
        run_dir / LEDGER_FILE: _read(run_dir / LEDGER_FILE),
    }
    detection, ledger, document, config, policy = _load_detection(run_dir)
    for path, loaded in ((run_dir / DETECTION_FILE, detection), (run_dir / LEDGER_FILE, ledger)):
        original = json.loads(before[path], object_pairs_hook=_object)
        if original != loaded:
            raise IntegrityError("review planning artifacts changed during validation")
    detection_sha = sha256_bytes(before[run_dir / DETECTION_FILE])
    source_path = run_dir / detection["source_file"]
    source_raw = _read(source_path)
    if source_raw != document.text.encode() or sha256_bytes(source_raw) != detection["source_sha256"]:
        raise IntegrityError("review planning source changed during validation")
    before[source_path] = source_raw
    for path, expected in (
        (ROOT / "config" / "aegisqda.local.yaml", detection["config_sha256"]),
        (ROOT / config.privacy.policy, detection["policy_sha256"]),
    ):
        before[path] = _read(path)
        if sha256_bytes(before[path]) != expected:
            raise IntegrityError("review planning controls changed during validation")

    findings = ledger["findings"]
    records: list[dict[str, str]] = []
    intervals: list[tuple[int, int, int]] = []
    for index, finding in enumerate(findings):
        identifier, entity, action = finding.get("finding_id"), finding.get("entity_type"), finding.get("action")
        if (
            not isinstance(identifier, str) or FINDING_ID.fullmatch(identifier) is None
            or not isinstance(entity, str) or entity not in policy.entities
            or action not in {item.value for item in PolicyAction}
            or action != policy.action_for(entity).value
        ):
            raise IntegrityError("review planning finding metadata is invalid")
        records.append({"finding_id": identifier, "entity_type": entity, "action": action})
        intervals.extend((start, end, index) for start, end in _finding_segments(finding, document))

    components = _overlap_components(intervals, len(records))
    members: dict[int, list[dict[str, str]]] = {}
    for index, record in enumerate(records):
        members.setdefault(components.find(index), []).append(record)
    groups: list[dict[str, Any]] = []
    for component in members.values():
        if len(component) < 2:
            continue
        ordered = sorted(component, key=lambda item: item["finding_id"])
        identity = {"detection_sha256": detection_sha, "finding_ids": [item["finding_id"] for item in ordered]}
        groups.append({
            "group_id": "OVL-" + sha256_bytes(canonical_bytes(identity))[:48],
            "finding_count": len(ordered), "findings": ordered,
        })
    groups.sort(key=lambda group: tuple(item["finding_id"] for item in group["findings"]))
    if any(_read(path) != raw for path, raw in before.items()):
        raise IntegrityError("review planning snapshot changed before completion")
    overlapping = sum(group["finding_count"] for group in groups)
    ungrouped = len(records) - overlapping
    return {
        "schema": SCHEMA, "state": "REVIEW_REQUIRED", "detection_sha256": detection_sha,
        "finding_count": len(records), "overlap_group_count": len(groups),
        "overlapping_finding_count": overlapping,
        "singleton_count": ungrouped, "ungrouped_finding_count": ungrouped,
        "overlap_groups": groups,
        "decision_authority": False, "transformation_authorized": False, "release_authorized": False,
        "notice": "Source-bound review planning only. Every finding still requires its own decision "
        "under the existing source-review and signature gates. "
        "No suppression, overlap resolution, transformation, or privacy-release authority.",
    }
