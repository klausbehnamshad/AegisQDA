#!/usr/bin/env python3
"""Model-free unit tests for the semantic comparator. CI-safe (no Ollama).

Feeds hand-crafted P1 unit outputs (good and bad) through evaluate_semantic()
against the REAL per-case expectations in cases.json, and asserts the verdict.
This covers the novel logic that --dry-run cannot (dry-run produces no codings).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from run_semantic_canary import evaluate_semantic, has_negation  # noqa: E402

SUITE = json.loads((HERE / "synthetic_cases" / "cases.json").read_text(encoding="utf-8"))
EXPECT = {c["case_id"]: c["expect"] for c in SUITE["cases"]}

results = []


def code(label, status, quote="q"):
    return {"code_label": label, "definition": "d", "status": status, "source_quote": quote}


def check(name, cid, result, neg, want):
    verdict, viol, rev = evaluate_semantic(EXPECT[cid], result, neg)
    ok = verdict == want
    results.append(ok)
    tag = "ok" if ok else "XX"
    extra = "" if ok else f"   viol={viol} rev={rev}"
    print(f"[{tag}] {name}: got {verdict}, want {want}{extra}")


def check_signal(name, got, want):
    ok = got == want
    results.append(ok)
    tag = "ok" if ok else "XX"
    print(f"[{tag}] {name}: got {got}, want {want}")


# --- case01: OPEN positive, must be inductive, no latent ---
check("01 clean", "case01_open_positive",
      {"coding_decision": "CODES_ASSIGNED",
       "descriptive_codes": [code("eigenes Brot gebacken", "INDUCTIVE_CANDIDATE"),
                             code("Stolz benannt", "INDUCTIVE_CANDIDATE")],
       "concise_description": "hat Brot gebacken und war stolz", "narrative_function": "EVALUATION",
       "uncertainty": []}, False, "SEMANTIC_PASS")

# --- case03b: lexical trap, must be NO_CODE_FITS ---
check("03b correct-refusal", "case03b_strict_lexical_trap",
      {"coding_decision": "NO_CODE_FITS", "descriptive_codes": [],
       "concise_description": "Blick auf den Garten", "narrative_function": "GENERAL_STATEMENT",
       "uncertainty": []}, False, "SEMANTIC_PASS")
check("03b lexical-trap-hit", "case03b_strict_lexical_trap",
      {"coding_decision": "CODES_ASSIGNED",
       "descriptive_codes": [code("Gartenarbeit", "CODEBOOK_APPLIED")],
       "concise_description": "Gartenarbeit am Fenster", "narrative_function": "EVENT_REPORT",
       "uncertainty": []}, False, "SEMANTIC_FAIL")

# --- case04: NOTHING_CODABLE ---
check("04 clean", "case04_nothing_codable",
      {"coding_decision": "NOTHING_CODABLE", "descriptive_codes": [],
       "concise_description": "Mikrofonfrage", "narrative_function": "OTHER", "uncertainty": []},
      False, "SEMANTIC_PASS")
check("04 over-coded", "case04_nothing_codable",
      {"coding_decision": "CODES_ASSIGNED", "descriptive_codes": [code("Technikproblem", "INDUCTIVE_CANDIDATE")],
       "concise_description": "Technik", "narrative_function": "OTHER", "uncertainty": []},
      False, "SEMANTIC_FAIL")

# --- case05: negation must survive ---
check("05 preserved", "case05_negation",
      {"coding_decision": "CODES_ASSIGNED", "descriptive_codes": [code("fehlende Erleichterung", "INDUCTIVE_CANDIDATE")],
       "concise_description": "war damals nicht erleichtert", "narrative_function": "EVALUATION",
      "uncertainty": []}, True, "SEMANTIC_PASS")
check("05 nominal-negation", "case05_negation",
      {"coding_decision": "CODES_ASSIGNED",
       "descriptive_codes": [code("keine Erleichterung", "INDUCTIVE_CANDIDATE")],
       "concise_description": "Projektende mit fehlender Erleichterung",
       "narrative_function": "EVALUATION", "uncertainty": []},
      True, "SEMANTIC_PASS")
check("05 flipped", "case05_negation",
      {"coding_decision": "CODES_ASSIGNED", "descriptive_codes": [code("Erleichterung", "INDUCTIVE_CANDIDATE")],
       "concise_description": "war erleichtert", "narrative_function": "EVALUATION", "uncertainty": []},
      True, "SEMANTIC_FAIL")
check_signal("05 signal nominal-negation", has_negation("fehlende Erleichterung"), True)
check_signal("05 signal explicit-negation", has_negation("war nicht erleichtert"), True)
check_signal("05 no substring false-positive", has_negation("würde es weiterempfehlen"), False)

# --- case06: ambiguity documented, not false-confident ---
check("06 ambiguous-status", "case06_ambiguous",
      {"coding_decision": "CODES_ASSIGNED", "descriptive_codes": [code("Ehrenamt", "CODEBOOK_AMBIGUOUS")],
       "concise_description": "hilft manchmal mit", "narrative_function": "EVENT_REPORT", "uncertainty": []},
      False, "SEMANTIC_PASS")
check("06 false-confident", "case06_ambiguous",
      {"coding_decision": "CODES_ASSIGNED", "descriptive_codes": [code("Ehrenamt", "CODEBOOK_APPLIED")],
       "concise_description": "hilft manchmal mit", "narrative_function": "EVENT_REPORT", "uncertainty": []},
      False, "SEMANTIC_REVIEW")

# --- case08: no latent interpretation ---
check("08 descriptive", "case08_no_latent",
      {"coding_decision": "CODES_ASSIGNED", "descriptive_codes": [code("Fernbleiben von Treffen", "INDUCTIVE_CANDIDATE")],
       "concise_description": "geht nicht mehr zu den Treffen", "narrative_function": "EVENT_REPORT",
       "uncertainty": []}, False, "SEMANTIC_PASS")
check("08 psychologising", "case08_no_latent",
      {"coding_decision": "CODES_ASSIGNED", "descriptive_codes": [code("soziale Isolation", "INDUCTIVE_CANDIDATE")],
       "concise_description": "Zeichen von Rückzug", "narrative_function": "EXPLANATION_JUSTIFICATION",
       "uncertainty": []}, False, "SEMANTIC_FAIL")

# --- case09: STRICT positive must apply a bound code, not over-refuse ---
check("09 applied", "case09_strict_positive",
      {"coding_decision": "CODES_ASSIGNED",
       "descriptive_codes": [code("Gartenarbeit", "CODEBOOK_APPLIED")],
       "concise_description": "Beete angelegt und gegossen",
       "narrative_function": "EVENT_REPORT", "uncertainty": []},
      False, "SEMANTIC_PASS")
check("09 over-refused", "case09_strict_positive",
      {"coding_decision": "NO_CODE_FITS", "descriptive_codes": [],
       "concise_description": "Beete angelegt und gegossen",
       "narrative_function": "EVENT_REPORT", "uncertainty": []},
      False, "SEMANTIC_FAIL")
check("09 ambiguous-on-clear-hit", "case09_strict_positive",
      {"coding_decision": "CODES_ASSIGNED",
       "descriptive_codes": [code("Gartenarbeit", "CODEBOOK_AMBIGUOUS")],
       "concise_description": "Beete angelegt und gegossen",
       "narrative_function": "EVENT_REPORT", "uncertainty": ["unklar"]},
      False, "SEMANTIC_FAIL")

passed = sum(results)
print(f"\ncomparator selftest: {passed}/{len(results)} passed")
sys.exit(0 if passed == len(results) else 1)
