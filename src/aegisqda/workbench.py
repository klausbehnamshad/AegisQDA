"""Local, source-bound human coding and memoing for released synthetic material.

The event log records method and analyst decisions. It is integrity sealed,
not a trusted signature or external release. No model is called here.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from .errors import IntegrityError, ReviewRequired
from .formats.document import Document, parse_document_bytes
from .manifests import seal, sha256_bytes, sha256_file, verify_seal
from .privacy_gate import validate_release
from .safeio import (
    atomic_json, load_json, read_stable_source, resolved_no_symlink,
    secure_dir, validate_opaque_id, validate_run_dir,
)
from .workflow import utc_now

METHODS = {"CODEBOOK", "REFLEXIVE_THEMATIC", "GROUNDED_THEORY"}
SCHEMA = "aegisqda-research-event-v1"


def _span(document: Document, start: object, end: object) -> tuple[int, int]:
    if (
        type(start) is not int or type(end) is not int
        or not 0 <= start < end <= len(document.text)
        or not any(region.start <= start < end <= region.end for region in document.regions)
    ):
        raise ReviewRequired("coding evidence must be a valid single content-line span")
    return start, end


def _text(value: object, label: str, *, minimum: int = 8, maximum: int = 8000) -> str:
    if not isinstance(value, str) or not minimum <= len(value.strip()) <= maximum or "\x00" in value:
        raise ReviewRequired(f"{label} has an invalid length or contains a forbidden character")
    return value.strip()


def _id(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise IntegrityError(f"{label} must be a string identifier")
    return validate_opaque_id(value, label=label)


def _load(run_dir: Path) -> tuple[Path, Document, list[dict[str, Any]]]:
    run_dir = validate_run_dir(run_dir)
    transformed, release = validate_release(run_dir)
    raw = read_stable_source(resolved_no_symlink(transformed))
    if sha256_bytes(raw) != release.get("transformed_sha256"):
        raise IntegrityError("research source changed after privacy-release validation")
    document = parse_document_bytes(raw, transformed.suffix)
    root = run_dir / "research"
    if not root.exists():
        return root, document, []
    if root.is_symlink():
        raise IntegrityError("research directory cannot be a symlink")
    entries = sorted(root.iterdir())
    release_hash = sha256_file(run_dir / "privacy-release.json")
    transformed_hash = sha256_bytes(document.text.encode())
    events: list[dict[str, Any]] = []
    previous: str | None = None
    codes: set[str] = set()
    for sequence, path in enumerate(entries, 1):
        if path.name != f"event-{sequence:06d}.json":
            raise IntegrityError("research event sequence is incomplete or contains foreign files")
        event = load_json(path)
        verify_seal(event)
        if (
            event.get("schema") != SCHEMA
            or type(event.get("sequence")) is not int or event.get("sequence") != sequence
            or event.get("previous_event_sha256") != previous
            or event.get("privacy_release_sha256") != release_hash
            or event.get("transformed_sha256") != transformed_hash
            or event.get("assurance") != "UNKEYED_SYNTHETIC_RESEARCH_ONLY"
        ):
            raise IntegrityError("research event provenance binding failed")
        _id(event.get("analyst_id"), "analyst id")
        kind = event.get("kind")
        if sequence == 1:
            if kind != "METHOD_DECLARED" or event.get("method") not in METHODS:
                raise IntegrityError("first research event must declare a supported method")
        elif kind == "CODE_DEFINED":
            code_id = _id(event.get("code_id"), "code id")
            parent = event.get("parent_id")
            if parent is not None:
                _id(parent, "parent code id")
            if code_id in codes or (parent is not None and parent not in codes):
                raise IntegrityError("codebook definition or hierarchy is invalid")
            _text(event.get("label"), "code label", minimum=1, maximum=200)
            _text(event.get("definition"), "code definition")
            codes.add(code_id)
        elif kind in {"CODE_APPLIED", "MEMO_WRITTEN"}:
            start, end = _span(document, event.get("start"), event.get("end"))
            if event.get("evidence_sha256") != sha256_bytes(document.text[start:end].encode()):
                raise IntegrityError("research evidence binding failed")
            if kind == "CODE_APPLIED":
                _id(event.get("code_id"), "code id")
                if event.get("code_id") not in codes:
                    raise IntegrityError("coding refers to an undefined code")
                _text(event.get("rationale"), "coding rationale")
            else:
                _text(event.get("memo"), "memo")
                if event.get("code_id") is not None:
                    _id(event["code_id"], "code id")
                if event.get("code_id") is not None and event["code_id"] not in codes:
                    raise IntegrityError("memo refers to an undefined code")
        else:
            raise IntegrityError("research event kind is invalid")
        previous = sha256_file(path)
        events.append(event)
    return root, document, events


def _append(run_dir: Path, analyst_id: str, payload: dict[str, Any]) -> Path:
    validate_opaque_id(analyst_id, label="analyst id")
    root, document, events = _load(run_dir)
    kind = payload["kind"]
    if not events and kind != "METHOD_DECLARED":
        raise ReviewRequired("declare a research method before coding or memoing")
    if events and kind == "METHOD_DECLARED":
        raise ReviewRequired("research method is already declared for this run")
    if kind == "METHOD_DECLARED" and payload.get("method") not in METHODS:
        raise ReviewRequired("unsupported research method")
    codes = {item["code_id"] for item in events if item["kind"] == "CODE_DEFINED"}
    if kind == "CODE_DEFINED":
        validate_opaque_id(payload["code_id"], label="code id")
        if payload["code_id"] in codes:
            raise ReviewRequired("code already defined; use a new versioned code id")
        if payload.get("parent_id") is not None and payload["parent_id"] not in codes:
            raise ReviewRequired("parent code must already exist")
        payload["label"] = _text(payload["label"], "code label", minimum=1, maximum=200)
        payload["definition"] = _text(payload["definition"], "code definition")
    if kind in {"CODE_APPLIED", "MEMO_WRITTEN"}:
        start, end = _span(document, payload["start"], payload["end"])
        payload["evidence_sha256"] = sha256_bytes(document.text[start:end].encode())
        if kind == "CODE_APPLIED":
            if payload["code_id"] not in codes:
                raise ReviewRequired("define the code before applying it")
            payload["rationale"] = _text(payload["rationale"], "coding rationale")
        else:
            payload["memo"] = _text(payload["memo"], "memo")
            if payload.get("code_id") is not None and payload["code_id"] not in codes:
                raise ReviewRequired("memo code is undefined")
    previous_path = root / f"event-{len(events):06d}.json"
    transformed = run_dir / ("transformed." + document.kind)
    event = seal({
        **payload,
        "schema": SCHEMA,
        "sequence": len(events) + 1,
        "created_at": utc_now(),
        "analyst_id": analyst_id,
        "assurance": "UNKEYED_SYNTHETIC_RESEARCH_ONLY",
        "previous_event_sha256": sha256_file(previous_path) if events else None,
        "privacy_release_sha256": sha256_file(run_dir / "privacy-release.json"),
        "transformed_sha256": sha256_file(transformed),
    })
    secure_dir(root)
    path = root / f"event-{len(events) + 1:06d}.json"
    atomic_json(path, event)
    return path


def declare_method(run_dir: Path, analyst_id: str, method: str) -> Path:
    return _append(run_dir, analyst_id, {"kind": "METHOD_DECLARED", "method": method})


def define_code(
    run_dir: Path, analyst_id: str, code_id: str, label: str, definition: str,
    parent_id: str | None = None,
) -> Path:
    return _append(run_dir, analyst_id, {
        "kind": "CODE_DEFINED", "code_id": code_id, "label": label,
        "definition": definition, "parent_id": parent_id,
    })


def apply_code(
    run_dir: Path, analyst_id: str, code_id: str, start: int, end: int, rationale: str,
) -> Path:
    return _append(run_dir, analyst_id, {
        "kind": "CODE_APPLIED", "code_id": code_id,
        "start": start, "end": end, "rationale": rationale,
    })


def write_memo(
    run_dir: Path, analyst_id: str, start: int, end: int, memo: str, code_id: str | None = None,
) -> Path:
    return _append(run_dir, analyst_id, {
        "kind": "MEMO_WRITTEN", "start": start, "end": end,
        "memo": memo, "code_id": code_id,
    })


def research_summary(run_dir: Path) -> dict[str, Any]:
    """Aggregate human coding without disclosing source, labels or memo text.

    A unit here is an exact annotated span; co-occurrence uses actual overlap.
    Counts concern distinct evidence spans, not analyst duplicates.
    """
    _, _, events = _load(run_dir)
    if not events:
        raise ReviewRequired("research method is not declared")
    coding = {
        (event["code_id"], event["start"], event["end"])
        for event in events if event["kind"] == "CODE_APPLIED"
    }
    counts = Counter(item[0] for item in coding)
    pairs: Counter[tuple[str, str]] = Counter()
    active: list[tuple[str, int, int]] = []
    for right in sorted(coding, key=lambda item: (item[1], item[2], item[0])):
        active = [left for left in active if left[2] > right[1]]
        for left in active:
            if left[0] != right[0]:
                pairs[tuple(sorted((left[0], right[0])))] += 1
        active.append(right)
    return {
        "schema": "aegisqda-research-summary-v1",
        "state": "METHODOLOGICAL_REVIEW_REQUIRED",
        "method": events[0]["method"],
        "event_count": len(events),
        "code_count": sum(event["kind"] == "CODE_DEFINED" for event in events),
        "memo_count": sum(event["kind"] == "MEMO_WRITTEN" for event in events),
        "coding_counts": dict(sorted(counts.items())),
        "cooccurrences": [
            {"codes": list(pair), "overlapping_span_pairs": count}
            for pair, count in sorted(pairs.items())
        ],
        "assurance": "UNKEYED_SYNTHETIC_RESEARCH_ONLY",
        "notice": "Human interpretations; counts are descriptive, not validity or reliability evidence. "
                  "Code definitions and memos remain protected and have no external privacy release.",
    }
