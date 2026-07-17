#!/usr/bin/env python3
"""Model-free checks for the production scope function used by the canary."""

from __future__ import annotations

import sys
from pathlib import Path

UTIL = Path(__file__).resolve().parent.parent / "90_UTILITIES"
sys.path.insert(0, str(UTIL))

from digqda_errors import WorkflowError  # noqa: E402
from qda_scope import apply_role_scope  # noqa: E402


ENVELOPE = {
    "meta": {"source_type": "srt", "source_sha256": "a" * 64, "n_units": 2},
    "source_units": [
        {"unit_id": "S01", "explicit_speaker": "I", "source_text": "Frage"},
        {"unit_id": "S02", "explicit_speaker": "B", "source_text": "Antwort"},
    ],
}

results: list[bool] = []


def check(name: str, condition: bool) -> None:
    results.append(condition)
    print(f"[{'ok' if condition else 'XX'}] {name}")


scoped, excluded = apply_role_scope(
    ENVELOPE, {"I": "interviewer", "B": "interviewee"}, ["interviewee"]
)
check("shared scope keeps only included role",
      [unit["unit_id"] for unit in scoped["source_units"]] == ["S02"])
check("shared scope records exclusions", excluded == ["S01"])
check("shared scope writes canonical provenance",
      scoped["meta"].get("scope_applied") is True
      and len(scoped["meta"].get("scope_sha256", "")) == 64)

try:
    apply_role_scope(ENVELOPE, {"B": "interviewee"}, ["interviewee"])
except WorkflowError:
    unknown_closed = True
else:
    unknown_closed = False
check("unmapped speaker fails closed", unknown_closed)

try:
    apply_role_scope(ENVELOPE, {"I": "interviewer", "B": "interviewee"}, ["moderator"])
except WorkflowError:
    empty_closed = True
else:
    empty_closed = False
check("all-excluded scope fails closed", empty_closed)

passed = sum(results)
print(f"\nscope selftest: {passed}/{len(results)} passed")
raise SystemExit(0 if passed == len(results) else 1)
