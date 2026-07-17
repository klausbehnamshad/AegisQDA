# Tested model/backend compatibility

This file records observed DigQDA conformance runs. It is not a general model
quality ranking and does not establish suitability for a research project.
Every production use still requires human review and the consuming system's
data-protection and authorization controls.

## Current pilot target — verified 2026-07-17

| Field | Observed value |
|---|---|
| Model | `gemma4:e4b` |
| Quantization | `Q4_K_M` |
| Model digest | `c6eb396dbd5992bbe3f5cdb947e8bbc0ee413d7c17e2beaae69f5d569cf982eb` |
| Ollama server | 0.24.0, localhost |
| Python client | 0.6.2 |
| Runtime | temperature 0.0, top_p 0.9, num_ctx 8192, seed 42, num_predict 2048 |
| Prompt | v1.2, SHA-256 `72f1bc785a275264325b47202441823b597d61493ffb5e6ad1369264dd94344e` |
| Schema SHA-256 | `c09ddafc7b9db9ff8c8b4b76c62f29324e8c3aacd5ffe53c70bbb1229520ff84` |

The complete synthetic smoke passed: OPEN completed 4/4 units with validator
`PASS`, 7 exact evidence quotes and no invalid locators; STRICT completed 4/4
units with validator `PASS`, 2 exact evidence quotes and no invalid locators.
The complete semantic canary v1.1.0 independently passed 10/10 cases with zero
contract failures, semantic failures, review cases or scope violations; all ten
scoped model calls were bound to the canonical P0 scope hash. Its case manifest
SHA-256 was `384dd6fcf0f10cc14d870c3f25bba267393071929803741f2014ee157cb0e327`.
STRICT now covers both directions: genuine `CODEBOOK_APPLIED` hits and correct
refusals where no definition fits. Gemma 4 was
materially slower than the smaller Gemma 3 comparison on this host, so pilot
runs must remain bounded and supervised.

Reproduce the current default with:

```bash
./digqda doctor
PYTHON=.venv/bin/python bash 90_UTILITIES/smoke/run_smoke.sh
.venv/bin/python eval/run_semantic_canary.py
```

## Historical local synthetic smoke — 2026-07-16

| Field | Observed value |
|---|---|
| Host | Apple M3, 11.8 GiB Metal memory available to Ollama |
| Python | 3.13.9 |
| Ollama server | 0.24.0, localhost |
| Python client | 0.6.2 |
| Model | `gemma3:4b` |
| Quantization | `Q4_K_M` |
| Model digest | `a2af6cc3eb7fa8be8504abaf9b04e88f17a119ec3f04a3addf55f92841195f5a` |
| Runtime | temperature 0.0, top_p 0.9, num_ctx 8192, seed 42 |
| Source | bundled synthetic SRT, SHA-256 `16bea23fb7d0562d96efc4933cb145d907c5a6efe48bb9b4b4c8a2a1b9baf8fc` |
| Prompt SHA-256 | `357727b6ab7b5c8e53d6012a9db0193061e9846259f75c5606a57b2ab121ff12` |
| Schema SHA-256 | `c09ddafc7b9db9ff8c8b4b76c62f29324e8c3aacd5ffe53c70bbb1229520ff84` |
| Contract SHA-256 | `f14ef8d98cf1e7528350e04aab3f4ce06b8802f69c301bfad2ad9baa5866e820` |

### Results

| Mode | Runner | Validator | Evidence | Locators | Effective grammar SHA-256 |
|---|---|---|---|---|---|
| `OPEN_DESCRIPTIVE` | 4/4 `OK` | `PASS` | 8 exact, 0 fuzzy/not-found | 0 invalid / 12 | `de3ca60621ed5d3410c6fe1b9bc2bdbf51103aae078e1984b1b0a21d3f398eae` |
| `STRICT_CODEBOOK` | 4/4 `OK` | `PASS` | 5 exact, 0 fuzzy/not-found | 0 invalid / 9 | `c16a2315948753a3b515c0badcafa4e6c2a1ce48deb11b30c0806611026e417a` |

The STRICT run used the bundled two-entry synthetic codebook with SHA-256
`d2f79b2f0b49c594f0108311d1346cb5451f8cc26b09420310c364d2a9f465360d2cf`.
No invalid response remained in quarantine.

### Reproduction

```bash
ollama serve
MODEL=gemma3:4b bash 90_UTILITIES/smoke/run_smoke.sh
```

Only the bundled synthetic fixtures are authorized for this harness. A passing
smoke result proves local contract plumbing, structured-output compliance and
technical evidence binding for this exact model digest. It does not prove
semantic coding quality on unseen or protected data.

## Prompt 1.2 verification — 2026-07-17

Runtime for both observations: Ollama Python client 0.6.2, temperature 0.0,
top_p 0.9, num_ctx 8192, seed 42, and the new hard `num_predict=2048` bound.
Prompt SHA-256 is
`72f1bc785a275264325b47202441823b597d61493ffb5e6ad1369264dd94344e`;
schema SHA-256 is
`c09ddafc7b9db9ff8c8b4b76c62f29324e8c3aacd5ffe53c70bbb1229520ff84`.

| Model | Digest | Technical smoke | Semantic canary | Operating conclusion |
|---|---|---|---|---|
| `gemma4:e4b` (`Q4_K_M`) | `c6eb396dbd5992bbe3f5cdb947e8bbc0ee413d7c17e2beaae69f5d569cf982eb` | OPEN 4/4 `OK`, validator `PASS` (7 exact); STRICT 4/4 `OK`, validator `PASS` (2 exact) | 10/10 semantic pass, 0 contract failures, 0 review cases, 0 scope violations; STRICT includes applied-hit and correct-refusal probes | Current supervised pilot default; best combined result in the recorded checks, but materially slower on this host. |
| `gemma3:4b` (`Q4_K_M`) | `a2af6cc3eb7fa8be8504abaf9b04e88f17a119ec3f04a3addf55f92841195f5a` | OPEN 4/4 `OK`, validator `PASS` (7 exact); STRICT 4/4 `OK`, validator `PASS` (5 exact) | Focused regression: two forced STRICT hits, one ambiguity review, technical-chatter case passed | Retained only as an accidental comparison, not the intended pilot default; smoke PASS alone was semantically insufficient. |
| `qwen3:8b` (`Q4_K_M`) | `500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41` | STRICT 4/4 `OK` and `PASS`; OPEN 3/4 because the longest unit reached `num_predict` without parseable JSON (`NOT_JSON`) | 9/9 semantic pass, 0 contract failures, 0 scope violations | Stronger result on the small semantic probe, but not the default: longer units can hit the bounded generation limit and fail closed. |

The observations measure different risks and are deliberately retained. No
model is approved for unattended coding. The intended current target is the
exact locally installed Ollama tag `gemma4:e4b`; `gemma4:3fb` was not present
and was therefore not tested.
