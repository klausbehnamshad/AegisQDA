# DigQDA — Semantic Canary (`eval/`)

A small, versioned, **synthetic** quality probe. Where the smoke test proves that
the pipeline *runs*, the canary shows *when to methodologically distrust its
results*. It separates three independent quality layers:

| Layer | Question | Source of truth |
|---|---|---|
| **Contract** | Is the output structurally legal? | P1 unit `status == OK` |
| **Evidence** | Are quotes/locators bound to the source? | validator `verdict == PASS` |
| **Semantic** | Is the coding decision methodologically defensible? | per-case expectations |

The whole point: **Contract + Evidence can both pass while Semantic fails** — a
result that is schema-valid, quote-exact and locator-correct, yet analytically
wrong (e.g. assigning a codebook code on lexical proximity alone).

> This is a **local, human-reviewed evidence artifact** — not a blocking gate and
> **not** part of the deterministic conformance suite. Only the bundled synthetic
> fixtures are authorized. Never point it at real data.

## Layout

```text
eval/
├── synthetic_cases/
│   ├── cases.json          # machine-readable expectations (robust boundaries)
│   ├── transcripts/        # tiny synthetic SRT fixtures
│   └── codebooks/          # mini codebooks for STRICT cases
├── run_semantic_canary.py  # P0 → scope-filter → P1 → V → semantic comparison
├── lint_cases.py           # model-free suite integrity check (CI-safe)
├── selftest_comparator.py  # model-free semantic boundary checks
├── selftest_scope.py       # shared production-scope fail-closed checks
└── README.md
```

## Scope filter (role map, not hardcoded `I`/`B`)

Speaker roles are resolved through a **per-case role map** (`{"I":"interviewer",
"B":"interviewee"}`), not hardcoded abbreviations. Units whose role is not in
`included_speaker_roles` are dropped **before** P1, so an interviewer question is
never sent to the model as an analysis task — it stays in the source only as
context. Default scope is interviewee-only. Run with `--no-scope` to reproduce
the ungated behaviour (in the real smoke run the model coded both interviewer
turns S01/S04 — that is the gap this filter closes).

The canary and production pilot import the same fail-closed implementation from
`90_UTILITIES/qda_scope.py`; there is no permissive evaluation copy. The pilot exposes it through
`./digqda pilot --role-map … --include-role …`. It additionally binds the scope
hash in P0 and the runner manifest and preserves the protected full segmentation
separately from the scoped P1 input.

The negation comparator uses conservative word-boundary patterns. It covers the
explicit forms declared by the suite without claiming exhaustive linguistic
recognition of forms such as `verneint`, `bestreitet` or `leugnet`.

## Running

Model-free plumbing check (no Ollama; validator `INVALID_INPUT` is expected):

```bash
python3 eval/lint_cases.py
python3 eval/selftest_comparator.py
python3 eval/selftest_scope.py
python3 eval/run_semantic_canary.py --dry-run
```

Real run against a local model (from the repo root, Ollama running):

```bash
python3 eval/run_semantic_canary.py --model gemma4:e4b
```

For a focused regression run, repeat `--case` as needed:

```bash
python3 eval/run_semantic_canary.py --model gemma4:e4b \
  --case case03_strict_no_code_fits --case case04_nothing_codable
```

Stability — pick what you measure:

```bash
# pipeline reproducibility (expect identical): same seed every repeat
python3 eval/run_semantic_canary.py --model gemma4:e4b --repeats 3 --fixed-seed
# decision robustness: vary the seed (seed+i) at a small temperature
python3 eval/run_semantic_canary.py --model gemma4:e4b --repeats 3 --temperature 0.3
```

Reproduce the scope gap:

```bash
python3 eval/run_semantic_canary.py --model gemma4:e4b --no-scope
```

## Output (`eval/out/`, git-ignored)

- `semantic_canary.json` — full per-case, per-repeat record.
- `semantic_canary.md` — human summary table + findings.
- `cases/<case_id>/` — per-case P0/P1/V artifacts for inspection.

Exit codes: `0` clean; `1` a hard finding (contract fail, semantic fail, or an
unexpected scope violation) on a real run; `2` the pipeline could not run.

## Requirements

Python 3.12/3.13 (repo standard), `jsonschema` + `rapidfuzz` (from
`requirements.txt`), and for real runs Ollama with a local model. The `--dry-run`
and `lint_cases.py` paths need no model.

## The cases (v1.1.0)

| # | Case | Mode | Probes |
|---|---|---|---|
| 1 | `case01_open_positive` | OPEN | positive anchor; no latent psychologising |
| 2 | `case02_scope_interviewer` | OPEN | scope filter excludes interviewer turn |
| 3 | `case03_strict_no_code_fits` | STRICT | `NO_CODE_FITS` instead of a forced hit |
| 3b | `case03b_strict_lexical_trap` | STRICT | definition > lexical match (isolated) |
| 4 | `case04_nothing_codable` | OPEN | `NOTHING_CODABLE` on non-content |
| 5 | `case05_negation` | OPEN | negation must survive |
| 6 | `case06_ambiguous` | STRICT | document ambiguity, no false-confident PASS |
| 7 | `case07_repeated_quote` | OPEN | evidence: correct per-unit locator |
| 8 | `case08_no_latent` | OPEN | no latent interpretation (Trauma/Isolation…) |
| 9 | `case09_strict_positive` | STRICT | hard `CODEBOOK_APPLIED` positive anchor |

German first by design. English/French cases can be added later without opening a
large multilingual benchmark.
