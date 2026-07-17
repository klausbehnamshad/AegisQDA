# AegisQDA compatibility evidence — 2026-07-17

## Local runtime

- CPython 3.13.3;
- Presidio Analyzer/Anonymizer 2.2.363;
- spaCy 3.8.13 with local `de_core_news_lg`, `fr_core_news_lg`, and
  `en_core_web_lg` 3.8.0 packages plus AegisQDA's deterministic recognizers;
- Pydantic 2.13.4, PyYAML 6.0.3;
- Ollama Python client 0.6.2;
- exact complete environment: `requirements.lock`.

The de/fr/en large spaCy packages are installed locally and load without any
runtime network access. Luxembourgish has no approved NER package and remains
blocked per run. `doctor` observed the configured endpoint
as loopback-only and verified the pinned DigQDA snapshot hash
`f36e0654ce3d959bf1a142572afc6b065ba93eca20816f9da04ac85160f307f0`.

## Models

| Approved exact tag | Local observation | Digest |
|---|---|---|
| `gemma3:4b` (default) | installed; DigQDA smoke OPEN 4/4 and STRICT 4/4; signed AegisQDA E2E `PASS` | `a2af6cc3eb7fa8be8504abaf9b04e88f17a119ec3f04a3addf55f92841195f5a` |
| `gemma4:e4b` | installed; downstream E2E passed | `c6eb396dbd5992bbe3f5cdb947e8bbc0ee413d7c17e2beaae69f5d569cf982eb` |

There is no fallback from the default. Installation and successful DigQDA
qualification are separate evidence gates. `gemma3:4b` was selected over
`mistral:7b` because the pinned DigQDA evidence already contains a complete
two-mode structured smoke for Gemma 3, while no equivalent Mistral result is
recorded.

### Rejected model

`gemma4:12b`, digest
`4eb23ef187e2c5462566d6a1d3bbbc2f1346d0b4327cbb66d58fffbcc9b2b05c`:
OPEN produced 1/4 valid units; STRICT produced 2/4 and validator
`NO_EVIDENCE`; overall only 3/8 units were valid, five structured responses
were empty, and the run took more than 20 minutes on this host. Result:
`SMOKE_RESULT=REVIEW_REQUIRED`. It is rejected, absent from the AegisQDA
allowlist, and must not be treated as pending qualification.

## Verification

- `pytest`: 55 passed;
- Ruff: pass;
- mypy: pass;
- upstream bootstrap integrity: pass;
- four-language curated acceptance: pass with Luxembourgish blocked;
- pinned DigQDA conformance: 117 pass / 0 fail;
- default-model synthetic downstream E2E: `DOWNSTREAM_REVIEW_REQUIRED` with
  `gemma3:4b`, exact digest
  `a2af6cc3eb7fa8be8504abaf9b04e88f17a119ec3f04a3addf55f92841195f5a`,
  DigQDA validator `PASS`, bound transformed-source hash, zero post-output scan
  findings, and about 21 seconds wall time;
- reference-model synthetic downstream E2E: the same terminal state with
  `gemma4:e4b`, exact digest
  `c6eb396dbd5992bbe3f5cdb947e8bbc0ee413d7c17e2beaae69f5d569cf982eb`.

Both downstream E2Es used only `tests/fixtures/en/qualification.srt`. The
default run used the opaque review identity `SYNTHETIC-HARNESS-GEMMA3` and no
model override. This is plumbing evidence, not a human research decision or
semantic-quality claim. No vendored file was modified.
