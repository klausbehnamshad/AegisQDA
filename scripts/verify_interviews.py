#!/usr/bin/env python3
"""Annotation checker + declared-value leak oracle for the interview corpus.

Runs the REAL AegisQDA detector (`scan_document`) and checks, per file, that it
finds every required manifest `(type, start, end)` annotation. This is a
leak oracle for the *declared* test values plus a same-detector pass; it is NOT a
proof of open-world recall (an unannotated blind spot can pass both), and it is
NOT a release-path validator — the scan→review→transform→release state machine is
covered by the pytest suite (see tests/test_ner_integration.py and
tests/test_workflow.py), which exercises the real `transform_run`. This tool only
answers: "does the real detector produce every required declared finding?"

Checks per file:
  * SHA-256 matches the manifest (else the annotations are stale);
  * every declared seeded-regex identifier is detected at its exact (type, span);
  * clean files carry no block-action finding;
  * when the spaCy models are installed, every declared NER identifier is detected
    at its exact (type, span) — a miss is a reported residual-risk leak;
  * safe controls produce zero findings.

Exit status: 0 only if all files pass. Missing NER models produce a non-zero
GATED status by default (declared NER cannot be checked); pass --regex-only to
accept a regex-only run and exit 0 when the rest passes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Iterator

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "src"
if SRC.is_dir() and str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import importlib.util  # noqa: E402

from aegisqda.config import PolicyAction, load_config, load_policy  # noqa: E402
from aegisqda.detection import scan_document  # noqa: E402
from aegisqda.formats.document import parse_document  # noqa: E402
from aegisqda.languages import PACKS  # noqa: E402

CORPUS = REPO / "tests" / "fixtures" / "interviews"
BLOCK_ACTIONS = {PolicyAction.BLOCK.value, PolicyAction.BLOCK_AND_REVIEW.value}


def ner_active(language: str) -> bool:
    model = PACKS[language].optional_ner_model
    return bool(model and importlib.util.find_spec(model))


def annotated(entry: dict[str, Any], field: str) -> Iterator[tuple[str, int, int, str]]:
    """Yield (type, start, end, value) for each declared span."""
    for item in entry.get(field, []):
        for start, end in item["spans"]:
            yield item["type"], start, end, item["value"]


def check_file(entry: dict[str, Any], policy: Any) -> tuple[list[str], bool]:
    path = CORPUS / str(entry["path"])
    problems: list[str] = []
    gated = False

    raw = path.read_bytes()
    if len(raw) != entry["source_bytes"]:
        problems.append("byte size does not match the manifest")
    if hashlib.sha256(raw).hexdigest() != entry["source_sha256"]:
        problems.append("SHA-256 does not match the manifest (annotations are stale)")
        return problems, gated  # spans are meaningless if the bytes changed

    doc = parse_document(path)
    for field in ("seeded_regex", "ner_expected_best_effort"):
        for item in entry[field]:
            expected_spans = [tuple(span) for span in item["spans"]]
            actual_spans = [
                (index, index + len(item["value"]))
                for index in range(len(doc.text))
                if doc.text.startswith(item["value"], index)
            ]
            if item["occurrences"] != len(expected_spans) or expected_spans != actual_spans:
                problems.append(
                    f"stale annotation for {item['type']}={item['value']!r}: "
                    f"declared={expected_spans}, actual={actual_spans}"
                )
    findings = scan_document(doc, entry["language"], policy)
    detected = {(f.entity_type, f.start, f.end) for f in findings}
    kind = entry["kind"]
    active = ner_active(entry["language"])

    for etype, start, end, value in annotated(entry, "seeded_regex"):
        if (etype, start, end) not in detected:
            problems.append(f"missing {etype} at [{start}:{end}] {value!r}")

    if kind == "clean":
        blocking = sorted({f.entity_type for f in findings if f.action in BLOCK_ACTIONS})
        if blocking:
            problems.append(f"clean file has block-action findings: {blocking}")
        for etype, start, end, value in annotated(entry, "ner_expected_best_effort"):
            if not active:
                gated = True
            elif (etype, start, end) not in detected:
                problems.append(f"NER leak: {etype} at [{start}:{end}] {value!r} not detected")

    if kind == "block" and not any(f.action in BLOCK_ACTIONS for f in findings):
        problems.append("block fixture produced no block-action finding")

    if kind == "safe" and findings:
        problems.append(f"safe control produced findings: "
                        f"{sorted((f.entity_type, doc.text[f.start:f.end]) for f in findings)}")

    return problems, gated


def validate_manifest(data: object) -> list[dict[str, Any]]:
    if not isinstance(data, dict) or data.get("schema") != "aegisqda-synthetic-interview-corpus-v2":
        raise ValueError("unexpected manifest schema")
    files = data.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError("manifest has no file entries")
    corpus_root = CORPUS.resolve()
    validated: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    for raw_entry in files:
        if not isinstance(raw_entry, dict):
            raise ValueError("manifest file entry is not an object")
        path = raw_entry.get("path")
        if not isinstance(path, str) or path in seen_paths:
            raise ValueError("manifest path is invalid or duplicated")
        source = (CORPUS / path).resolve()
        if not source.is_relative_to(corpus_root) or not source.is_file():
            raise ValueError("manifest path escapes the corpus or is missing")
        if raw_entry.get("language") not in {"de", "fr", "en"}:
            raise ValueError("manifest language is invalid")
        if raw_entry.get("kind") not in {"clean", "block", "safe"}:
            raise ValueError("manifest kind is invalid")
        if raw_entry.get("format") not in {"srt", "txt"} or source.suffix != "." + str(
            raw_entry["format"]
        ):
            raise ValueError("manifest format does not match the source")
        declared_hash = raw_entry.get("source_sha256")
        if (
            not isinstance(declared_hash, str)
            or len(declared_hash) != 64
            or any(char not in "0123456789abcdef" for char in declared_hash)
            or not isinstance(raw_entry.get("source_bytes"), int)
        ):
            raise ValueError("manifest source hash or size is invalid")
        for field in ("seeded_regex", "ner_expected_best_effort"):
            annotations = raw_entry.get(field)
            if not isinstance(annotations, list):
                raise ValueError(f"manifest {field} is invalid")
            for item in annotations:
                if (
                    not isinstance(item, dict)
                    or not isinstance(item.get("type"), str)
                    or not isinstance(item.get("value"), str)
                    or not isinstance(item.get("spans"), list)
                    or not isinstance(item.get("occurrences"), int)
                    or any(
                        not isinstance(span, list)
                        or len(span) != 2
                        or not isinstance(span[0], int)
                        or not isinstance(span[1], int)
                        or not 0 <= span[0] < span[1]
                        for span in item.get("spans", [])
                    )
                ):
                    raise ValueError(f"manifest {field} annotation is invalid")
        seen_paths.add(path)
        validated.append(raw_entry)
    return validated


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="corpus annotation checker / leak oracle")
    parser.add_argument("--regex-only", action="store_true",
                        help="accept a run without the spaCy NER models and exit 0 if the rest passes")
    args = parser.parse_args(argv)

    policy = load_policy(load_config())
    try:
        manifest_data = json.loads(
            (CORPUS / "interviews_manifest.json").read_text(encoding="utf-8")
        )
        entries = validate_manifest(manifest_data)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        print(f"RESULT: FAIL — invalid corpus manifest ({exc})", file=sys.stderr)
        return 1
    any_fail = any_gated = False
    for entry in entries:
        problems, gated = check_file(entry, policy)
        any_fail = any_fail or bool(problems)
        any_gated = any_gated or gated
        status = "FAIL" if problems else ("GATED" if gated else "PASS")
        print(f"{status:5s} {entry['path']}")
        for p in problems:
            print(f"       - {p}")

    if any_fail:
        print("\nRESULT: FAIL")
        return 1
    if any_gated and not args.regex_only:
        print("\nRESULT: GATED — spaCy NER models absent; declared NER not checked. "
              "Install the models, or pass --regex-only to accept a regex-only run.")
        return 2
    print("\nRESULT: PASS" + (" (regex-only)" if any_gated else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
