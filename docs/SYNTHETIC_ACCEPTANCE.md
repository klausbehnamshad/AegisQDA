# Synthetic acceptance evidence — 2026-07-17

Scope: bundled synthetic fixtures only. This report is not evidence of recall
on unseen free text and is not an anonymity claim.

Command:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/synthetic_acceptance.py
```

| Language | Language gate | Annotated spans | Detected | Safe-control findings | Result |
|---|---|---:|---:|---:|---|
| de | `READY_FOR_SYNTHETIC_SCAN` | 15 | 15 | 0 | PASS |
| fr | `READY_FOR_SYNTHETIC_SCAN` | 15 | 15 | 0 | PASS |
| en | `READY_FOR_SYNTHETIC_SCAN` | 15 | 15 | 0 | PASS |
| lb | `BLOCKED_OPTIONAL` | 15 | 15 | 0 | PASS (optional block correctly enforced) |

The annotated spans cover PERSON, ORGANIZATION, LOCATION, email, URL, phone,
IBAN, IP address, date, age, kinship, job, rare event, small place, and project
identifier. The tests also cover malformed SRT/TXT, mixed newlines, repeated
entity co-reference, review completeness, stale/tampered artifacts, symlinks,
repository/cloud paths, remote endpoint and proxy attempts, clear-text manifest
leakage, and attempted downstream invocation before release.

Measured release E2E for de/fr/en preserved SRT cue numbers and byte-identical
timing lines and introduced no newline drift. Luxembourgish was not released:
rule recall does not substitute for an approved tokenizer/NER design and its
own broader validation suite.

The complete local adapter path was exercised without a model override using
the exact default `gemma3:4b` against `en/qualification.srt`: signed
privacy-release revalidation, exact digest binding, hash-bound `think=false`,
pinned DigQDA validation, language-routed post-output scanning, and zero
findings all passed in about 21 seconds. The terminal state was correctly
`DOWNSTREAM_REVIEW_REQUIRED`, not external release. The explicitly allowed
reference `gemma4:e4b` independently passed the same AegisQDA path.

False positives are not hidden: the four safe controls produced zero findings
for this exact fixture set. That number is reported, not generalized.
