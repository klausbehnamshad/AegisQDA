"""Read-only segment access and exact-span coding comparisons for synthetic runs.

Indexes and searches return descriptors, never quotations or search terms.
Only explicit ``read_segment`` access returns protected content. Comparisons
describe recorded coding decisions and do not measure research reliability.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

from .errors import AegisError, DownstreamBlocked, IntegrityError, ReviewRequired
from .formats.document import Document, Region
from .manifests import canonical_bytes, sha256_bytes
from .safeio import read_stable_source, resolved_no_symlink, validate_run_dir
from .workbench import _load

SEGMENT_ID = re.compile(r"SEG-[0-9a-f]{48}\Z")
ASSURANCE = "UNKEYED_SYNTHETIC_RESEARCH_ONLY"


def _context(run_dir: Path) -> tuple[Document, list[dict[str, Any]], str, str]:
    """Use the existing gate/event validator, then retain one stable snapshot."""
    run_dir = validate_run_dir(run_dir)
    try:
        release_before = read_stable_source(resolved_no_symlink(run_dir / "privacy-release.json"))
    except (OSError, AegisError) as exc:
        raise DownstreamBlocked("research queries require a valid privacy release") from exc
    root, document, events = _load(run_dir)
    if not events:
        raise ReviewRequired("declare a research method before querying protected segments")
    release_sha = sha256_bytes(release_before)
    source_sha = sha256_bytes(document.text.encode())
    source_now = read_stable_source(resolved_no_symlink(run_dir / f"transformed.{document.kind}"))
    release_now = read_stable_source(resolved_no_symlink(run_dir / "privacy-release.json"))
    if sha256_bytes(source_now) != source_sha or release_now != release_before:
        raise IntegrityError("research source or release changed while the query was being validated")
    expected_paths = [root / f"event-{sequence:06d}.json" for sequence in range(1, len(events) + 1)]
    if sorted(root.iterdir()) != expected_paths:
        raise IntegrityError("research event inventory changed while the query was being validated")
    previous: str | None = None
    for path, event in zip(expected_paths, events, strict=True):
        raw = read_stable_source(resolved_no_symlink(path))
        try:
            current = json.loads(raw)
        except (ValueError, UnicodeError) as exc:
            raise IntegrityError("research event snapshot is invalid") from exc
        if (
            canonical_bytes(current) != canonical_bytes(event)
            or event["privacy_release_sha256"] != release_sha
            or event["transformed_sha256"] != source_sha
            or event["previous_event_sha256"] != previous
        ):
            raise IntegrityError("research event snapshot changed while the query was being validated")
        previous = sha256_bytes(raw)
    if (
        sorted(root.iterdir()) != expected_paths
        or sha256_bytes(read_stable_source(resolved_no_symlink(run_dir / f"transformed.{document.kind}"))) != source_sha
        or read_stable_source(resolved_no_symlink(run_dir / "privacy-release.json")) != release_before
    ):
        raise IntegrityError("research snapshot changed before the query completed")
    return document, events, release_sha, source_sha


def _descriptor(
    document: Document, region: Region, release_sha: str, source_sha: str,
) -> dict[str, object]:
    evidence_sha = sha256_bytes(document.text[region.start:region.end].encode())
    identity = {
        "privacy_release_sha256": release_sha, "transformed_sha256": source_sha,
        "start": region.start, "end": region.end, "evidence_sha256": evidence_sha,
    }
    return {
        "segment_id": "SEG-" + sha256_bytes(canonical_bytes(identity))[:48],
        "start": region.start, "end": region.end,
        "character_count": region.end - region.start, "evidence_sha256": evidence_sha,
    }


def _index(
    document: Document, events: list[dict[str, Any]], release_sha: str, source_sha: str,
) -> dict[str, Any]:
    segments = [_descriptor(document, region, release_sha, source_sha) for region in document.regions]
    if len({item["segment_id"] for item in segments}) != len(segments):
        raise IntegrityError("research segment identifiers are ambiguous")
    return {
        "schema": "aegisqda-segment-index-v1", "state": "METHODOLOGICAL_REVIEW_REQUIRED",
        "method": events[0]["method"], "source_kind": document.kind,
        "privacy_release_sha256": release_sha, "transformed_sha256": source_sha,
        "segment_count": len(segments), "segments": segments,
        "assurance": ASSURANCE,
        "notice": "Protected synthetic content-line descriptors; structural SRT headers are excluded. "
        "Quotations require explicit protected segment access. No external release.",
    }


def list_segments(run_dir: Path) -> dict[str, Any]:
    """List stable content-line IDs, character offsets and hashes without text."""
    return _index(*_context(run_dir))


def search_segments(run_dir: Path, query: str) -> dict[str, Any]:
    """Find literal, case-insensitive content-line matches without echoing a query."""
    document, events, release_sha, source_sha = _context(run_dir)
    if not isinstance(query, str) or not 1 <= len(query.strip()) <= 2000 or "\x00" in query:
        raise ReviewRequired("segment search requires a bounded nonempty text query")
    needle = query.strip().casefold()
    index = _index(document, events, release_sha, source_sha)
    index["schema"] = "aegisqda-segment-search-v1"
    index["segments"] = [
        item for item in index["segments"]
        if needle in document.text[item["start"]:item["end"]].casefold()
    ]
    index["match_count"] = len(index["segments"])
    return index


def read_segment(run_dir: Path, segment_id: str) -> str:
    """Explicitly retrieve exact protected content, without creating an export."""
    document, events, release_sha, source_sha = _context(run_dir)
    if not isinstance(segment_id, str) or SEGMENT_ID.fullmatch(segment_id) is None:
        raise ReviewRequired("segment identifier is unknown for this protected run")
    index = _index(document, events, release_sha, source_sha)
    matching = [item for item in index["segments"] if item["segment_id"] == segment_id]
    if len(matching) != 1:
        raise ReviewRequired("segment identifier is unknown for this protected run")
    selected = matching[0]
    return document.text[selected["start"]:selected["end"]]


def analyst_dissent(run_dir: Path) -> dict[str, Any]:
    """Compare only explicit analyst code sets on the same exact evidence span."""
    _, events, release_sha, source_sha = _context(run_dir)
    groups: dict[tuple[int, int, str], dict[str, set[str]]] = {}
    for event in events:
        if event["kind"] != "CODE_APPLIED":
            continue
        span = (event["start"], event["end"], event["evidence_sha256"])
        analysts = groups.setdefault(span, {})
        analysts.setdefault(event["analyst_id"], set()).add(event["code_id"])
    comparable = 0
    dissent: list[dict[str, object]] = []
    for (start, end, evidence_sha), analysts in sorted(groups.items()):
        if len(analysts) < 2:
            continue
        comparable += 1
        if len({frozenset(codes) for codes in analysts.values()}) < 2:
            continue
        dissent.append({
            "start": start, "end": end, "evidence_sha256": evidence_sha,
            "analysts": [
                {"analyst_id": analyst, "code_ids": sorted(codes)}
                for analyst, codes in sorted(analysts.items())
            ],
        })
    return {
        "schema": "aegisqda-analyst-dissent-v1", "state": "METHODOLOGICAL_REVIEW_REQUIRED",
        "method": events[0]["method"], "privacy_release_sha256": release_sha,
        "transformed_sha256": source_sha, "comparable_span_count": comparable,
        "dissent_span_count": len(dissent), "groups": dissent, "assurance": ASSURANCE,
        "notice": "Differences between explicit coding sets on identical evidence spans. "
        "Missing coding is not treated as disagreement. Descriptive support for human review; "
        "no reliability, validity, or external-release claim.",
    }
