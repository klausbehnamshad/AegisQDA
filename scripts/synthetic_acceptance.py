#!/usr/bin/env python3
"""Emit a source-free, model-free per-language acceptance report."""

from __future__ import annotations

import json
from pathlib import Path

from aegisqda.config import load_config, load_policy
from aegisqda.detection import scan_document
from aegisqda.formats.document import parse_document
from aegisqda.languages import PACKS

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"


def main() -> int:
    expected = json.loads((FIXTURES / "expected.json").read_text(encoding="utf-8"))
    policy = load_policy(load_config())
    report: dict[str, object] = {
        "schema": "aegisqda-synthetic-acceptance-v1",
        "scope": "curated synthetic fixtures only",
        "languages": {},
    }
    passed = True
    languages: dict[str, object] = report["languages"]  # type: ignore[assignment]
    for language in ("de", "fr", "lb", "en"):
        findings = scan_document(parse_document(FIXTURES / language / "risk.txt"), language, policy)
        risk_text = (FIXTURES / language / "risk.txt").read_text(encoding="utf-8")
        safe_findings = scan_document(
            parse_document(FIXTURES / language / "safe.txt"), language, policy
        )
        observed = {
            (finding.entity_type, risk_text[finding.start:finding.end])
            for finding in findings
        }
        seeded = {tuple(item) for item in expected["seeds"][language]}
        missing = sorted(seeded - observed)
        unexpected = sorted(observed - seeded)
        gate = "READY_FOR_SYNTHETIC_SCAN" if PACKS[language].release_ready else "BLOCKED_OPTIONAL"
        language_pass = (
            not missing
            and not unexpected
            and not safe_findings
            and gate == expected["language_gate"][language]
        )
        passed = passed and language_pass
        languages[language] = {
            "gate": gate,
            "seeded_spans": len(seeded),
            "detected_seeded_spans": len(seeded & observed),
            "missing_spans": missing,
            "unexpected_risk_findings": unexpected,
            "safe_control_false_positive_count": len(safe_findings),
            "fixture_result": "PASS" if language_pass else "FAIL",
        }
    report["result"] = "PASS" if passed else "FAIL"
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
