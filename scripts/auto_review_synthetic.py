#!/usr/bin/env python3
"""Synthetic-only, non-interactive review helper bound to the corpus allowlist.

PURPOSE
    Let a batch smoke run of the *registered synthetic corpus* proceed past the
    mandatory review gate without a human, exactly like the model-free test
    harness does via ``workflow.write_review``. Plumbing only; not a substitute
    for human review.

TWO INDEPENDENT GUARDS (both required)
    1. The run's detection artifact must be marked ``synthetic_only``.
    2. The run's protected-source hash (detection.source_sha256) must be listed
       in ``tests/fixtures/interviews/interviews_manifest.json``. A file that is
       not a byte-for-byte member of the registered synthetic corpus — e.g. a
       real transcript mistakenly dropped under tests/fixtures — is refused,
       because ``synthetic_only`` alone is just a CLI assertion.

BEHAVIOUR
    * Confirms only REPLACE_AND_REVIEW / GENERALIZE_AND_REVIEW findings.
    * Refuses (writes no review, exits non-zero) on any block-action finding
      (KINSHIP/JOB_TITLE/AGE/SMALL_PLACE/RARE_EVENT/NRP) — it never silently
      declares an indirect identifier a false positive.
    * Refuses on overlapping confirmed findings; those need the interactive
      ``aegisqda review`` so a human prunes the overlap.

USAGE
    .venv/bin/python scripts/auto_review_synthetic.py RUN_DIR \
        [--reviewer SYNTHETIC-AUTOREVIEW] [--signing-key KEY]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from aegisqda.config import PolicyAction
from aegisqda.safeio import load_json, validate_run_dir
from aegisqda.workflow import DETECTION_FILE, LEDGER_FILE, write_review

BLOCK_ACTIONS = {PolicyAction.BLOCK.value, PolicyAction.BLOCK_AND_REVIEW.value}
REPO = Path(__file__).resolve().parent.parent
DEFAULT_MANIFEST = REPO / "tests" / "fixtures" / "interviews" / "interviews_manifest.json"
CORPUS = DEFAULT_MANIFEST.parent


def registered_hashes() -> set[str]:
    """Return hashes only after validating the fixed manifest against its files."""
    data = json.loads(DEFAULT_MANIFEST.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema") != "aegisqda-synthetic-interview-corpus-v2":
        raise ValueError("unexpected corpus manifest schema")
    files = data.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError("corpus manifest has no files")
    corpus_root = CORPUS.resolve()
    hashes: set[str] = set()
    seen_paths: set[str] = set()
    for entry in files:
        if not isinstance(entry, dict):
            raise ValueError("corpus manifest file entry is invalid")
        relative = entry.get("path")
        declared_hash = entry.get("source_sha256")
        declared_bytes = entry.get("source_bytes")
        if not isinstance(relative, str) or relative in seen_paths:
            raise ValueError("corpus manifest path is invalid or duplicated")
        if (
            not isinstance(declared_hash, str)
            or len(declared_hash) != 64
            or any(char not in "0123456789abcdef" for char in declared_hash)
            or not isinstance(declared_bytes, int)
            or declared_bytes < 0
        ):
            raise ValueError("corpus manifest hash or size is invalid")
        source = (CORPUS / relative).resolve()
        if not source.is_relative_to(corpus_root) or not source.is_file():
            raise ValueError("corpus manifest path escapes or is missing")
        raw = source.read_bytes()
        if len(raw) != declared_bytes or hashlib.sha256(raw).hexdigest() != declared_hash:
            raise ValueError("corpus manifest does not match the registered source bytes")
        seen_paths.add(relative)
        hashes.add(declared_hash)
    return hashes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="synthetic-only auto review bound to the corpus")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--reviewer", default="SYNTHETIC-AUTOREVIEW")
    parser.add_argument("--signing-key", type=Path, default=None)
    args = parser.parse_args(argv)

    run_dir = validate_run_dir(args.run_dir)
    detection = load_json(run_dir / DETECTION_FILE)

    if detection.get("synthetic_only") is not True:
        print("REFUSED: run is not marked synthetic_only", file=sys.stderr)
        return 2

    try:
        allow = registered_hashes()
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        print(f"REFUSED: fixed corpus allowlist is invalid ({exc})", file=sys.stderr)
        return 2
    source_hash = detection.get("source_sha256")
    if not isinstance(source_hash, str) or source_hash not in allow:
        print("REFUSED: source is not a registered member of the synthetic corpus "
              f"(source_sha256={source_hash}). Auto-review is bound to "
              f"{DEFAULT_MANIFEST}; use interactive `aegisqda review` for anything else.",
              file=sys.stderr)
        return 2

    ledger = load_json(run_dir / LEDGER_FILE)
    findings = ledger.get("findings")
    if not isinstance(findings, list):
        print("REFUSED: detection ledger is invalid", file=sys.stderr)
        return 2

    decisions: list[dict[str, str]] = []
    spans: list[tuple[int, int, str, str]] = []
    blocked: list[tuple[str, str]] = []
    for finding in findings:
        action = str(finding.get("action"))
        fid = str(finding.get("finding_id"))
        entity = str(finding.get("entity_type"))
        if action == PolicyAction.REPLACE_AND_REVIEW.value:
            decisions.append({"finding_id": fid, "decision": "CONFIRMED"})
            spans.append((int(finding["start"]), int(finding["end"]), entity, fid))
        elif action == PolicyAction.GENERALIZE_AND_REVIEW.value:
            decisions.append({"finding_id": fid, "decision": "GENERALIZE_CONFIRMED"})
            spans.append((int(finding["start"]), int(finding["end"]), entity, fid))
        elif action in BLOCK_ACTIONS:
            blocked.append((entity, fid))
        else:
            blocked.append((entity + f"(unknown action {action})", fid))

    if blocked:
        print("BLOCKED_BY_DESIGN: block-action identifiers require a human decision:", file=sys.stderr)
        for entity, fid in blocked:
            print(f"    {fid}  {entity}", file=sys.stderr)
        print("No review written. Use the interactive `aegisqda review`.", file=sys.stderr)
        return 3

    spans.sort()
    for left, right in zip(spans, spans[1:]):
        if right[0] < left[1]:
            print("OVERLAP: two confirmed findings overlap; a human must prune one:", file=sys.stderr)
            print(f"    {left[3]} {left[2]} [{left[0]}:{left[1]}]", file=sys.stderr)
            print(f"    {right[3]} {right[2]} [{right[0]}:{right[1]}]", file=sys.stderr)
            print("No review written. Use the interactive `aegisqda review`.", file=sys.stderr)
            return 3

    path = write_review(run_dir, args.reviewer, decisions, [], signing_key=args.signing_key)
    print("REVIEW_ACCEPTED")
    print(f"review={path}")
    print(f"confirmed={len(decisions)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
