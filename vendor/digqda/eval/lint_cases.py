#!/usr/bin/env python3
"""Model-free integrity check for the Semantic Canary case suite.

Validates that cases.json is internally consistent and legal against the DigQDA
contract BEFORE any model is called. Safe to run in CI: it never touches Ollama.

Checks per case:
  - required fields present; unique case_id
  - mode is one of the three legal modes
  - allowed_decisions are legal for the mode (NO_CODE_FITS only in STRICT_CODEBOOK)
  - referenced transcript and codebook files exist
  - STRICT/CONSTRAINED carry a codebook; OPEN does not
  - list-typed expectation fields really are lists
  - included_speaker_roles non-empty; target role is covered by the role map
"""

from __future__ import annotations

import json
from pathlib import Path

LEGAL_MODES = {"OPEN_DESCRIPTIVE", "STRICT_CODEBOOK", "CONSTRAINED_EXTENSION"}
LEGAL_DECISIONS = {"CODES_ASSIGNED", "NO_CODE_FITS", "NOTHING_CODABLE"}
LEGAL_CODE_STATUS = {"CODEBOOK_APPLIED", "CODEBOOK_AMBIGUOUS", "INDUCTIVE_CANDIDATE"}
MODE_CODE_STATUS = {
    "OPEN_DESCRIPTIVE": {"INDUCTIVE_CANDIDATE"},
    "STRICT_CODEBOOK": {"CODEBOOK_APPLIED", "CODEBOOK_AMBIGUOUS"},
    "CONSTRAINED_EXTENSION": {
        "CODEBOOK_APPLIED", "CODEBOOK_AMBIGUOUS", "INDUCTIVE_CANDIDATE",
    },
}
NO_CODE_FITS_MODES = {"STRICT_CODEBOOK"}
LIST_FIELDS = ("allowed_decisions", "required_code_labels", "forbidden_code_labels",
               "required_code_status", "forbidden_code_status", "required_description_fragments",
               "forbidden_description_fragments")


def main() -> int:
    here = Path(__file__).resolve().parent
    cases_path = here / "synthetic_cases" / "cases.json"
    transcripts = here / "synthetic_cases" / "transcripts"
    codebooks = here / "synthetic_cases" / "codebooks"

    errors: list[str] = []
    warnings: list[str] = []

    try:
        suite = json.loads(cases_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: cannot parse {cases_path}: {exc}")
        return 1

    seen = set()
    cases = suite.get("cases", [])
    for i, case in enumerate(cases):
        cid = case.get("case_id", f"<index {i}>")
        if cid in seen:
            errors.append(f"{cid}: duplicate case_id")
        seen.add(cid)

        for field in ("case_id", "mode", "transcript", "expect", "role_map",
                      "included_speaker_roles", "target"):
            if field not in case:
                errors.append(f"{cid}: missing field {field!r}")

        mode = case.get("mode")
        if mode not in LEGAL_MODES:
            errors.append(f"{cid}: illegal mode {mode!r}")

        expect = case.get("expect", {})
        for field in LIST_FIELDS:
            if field in expect and not isinstance(expect[field], list):
                errors.append(f"{cid}: expect.{field} must be a list")

        for dec in expect.get("allowed_decisions", []):
            if dec not in LEGAL_DECISIONS:
                errors.append(f"{cid}: illegal decision {dec!r}")
            if dec == "NO_CODE_FITS" and mode not in NO_CODE_FITS_MODES:
                errors.append(f"{cid}: NO_CODE_FITS is only legal in STRICT_CODEBOOK, not {mode}")

        for field in ("required_code_status", "forbidden_code_status"):
            for status in expect.get(field, []):
                if status not in LEGAL_CODE_STATUS:
                    errors.append(f"{cid}: illegal {field} value {status!r}")
                if field == "required_code_status" and status not in MODE_CODE_STATUS.get(mode, set()):
                    errors.append(f"{cid}: {status} is not legal in mode {mode}")

        tpath = transcripts / case.get("transcript", "")
        if not tpath.exists():
            errors.append(f"{cid}: transcript not found: {tpath.name}")

        cb = case.get("codebook")
        if cb:
            if not (codebooks / cb).exists():
                errors.append(f"{cid}: codebook not found: {cb}")
            if mode == "OPEN_DESCRIPTIVE":
                warnings.append(f"{cid}: OPEN_DESCRIPTIVE ignores a codebook (harmless)")
        elif mode in ("STRICT_CODEBOOK", "CONSTRAINED_EXTENSION"):
            errors.append(f"{cid}: {mode} requires a codebook but none is set")

        roles = case.get("included_speaker_roles", [])
        if not roles:
            errors.append(f"{cid}: included_speaker_roles is empty")
        role_map = case.get("role_map", {})
        target_role = (case.get("target") or {}).get("speaker_role")
        if target_role and target_role not in role_map.values():
            warnings.append(f"{cid}: target role {target_role!r} not present in role_map values")

    for w in warnings:
        print(f"WARN: {w}")
    for e in errors:
        print(f"FAIL: {e}")
    print(f"\nlint: {len(cases)} cases, {len(errors)} errors, {len(warnings)} warnings")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
