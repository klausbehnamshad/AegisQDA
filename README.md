# AegisQDA

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.21854346.svg)](https://doi.org/10.5281/zenodo.21854346)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

AegisQDA is a local-only, fail-closed privacy gateway for the pinned DigQDA
snapshot. The implemented MVP accepts synthetic UTF-8 SRT/TXT, runs local
Presidio-backed custom recognizers, requires complete terminal review, applies
typed document-local surrogates, verifies structure and a second scan, and only
then permits the consumer-owned DigQDA adapter to run.

It does **not** claim universal anonymity. Its strongest result is the bounded
process statement `PRIVACY_RELEASED under policy ... after automatic checks and
human sign-off`. Any uncertainty remains blocking.

## Boundary

- no cloud service, remote API, telemetry, or remote inference;
- Ollama must be unauthenticated HTTP on an exclusively loopback host;
- any active HTTP/HTTPS/ALL proxy environment blocks before source reading;
- exact approved tags are `gemma3:4b` and `gemma4:e4b`; the default is exactly
  `gemma3:4b`, with no fallback;
- `vendor/digqda/` is read-only and verified against `UPSTREAM.lock.json`;
- source, review, release, and result artifacts use owner-only external run
  directories and must never enter Git or cloud-sync paths;
- real-data authorization is deliberately not enabled; a local signed-attestation
  interface is reserved in configuration for the later infrastructure binding.

## Local setup

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pip install --no-deps -e .
```

`requirements.lock` records the exact resolved environment. Installation never
authorizes a model download. AegisQDA does not download spaCy or Ollama models
at runtime.

## CLI

```bash
.venv/bin/aegisqda doctor
.venv/bin/aegisqda keygen-review /secure/local/path/reviewer.pem
.venv/bin/aegisqda scan tests/fixtures/en/sample.srt \
  --language en --case-id CASE-001 --synthetic
.venv/bin/aegisqda review /private/tmp/aegisqda-runs/CASE-001/run-... \
  --reviewer REVIEWER-001 --signing-key /secure/local/path/reviewer.pem
.venv/bin/aegisqda transform /private/tmp/aegisqda-runs/CASE-001/run-...
.venv/bin/aegisqda analyze /private/tmp/aegisqda-runs/CASE-001/run-...
```

`scan` and `run` intentionally return a non-zero `REVIEW_REQUIRED` state. The
terminal reviewer sees protected context locally and must resolve every finding;
there is no auto-approve CLI option. `analyze` revalidates every bound hash and
the current endpoint/model digest before it can invoke DigQDA.

## Current measured status (2026-07-17)

- local test suite on the trained-model host: 69 passing;
- curated rule-pack report: 15/15 annotated spans detected separately
  for de/fr/en/lb, with zero findings in the four safe controls;
- de/fr/en synthetic SRT release paths pass without cue, timing, or newline
  drift;
- Luxembourgish remains optional and blocked per run; it no longer blocks the
  global Doctor readiness result;
- `gemma3:4b` is the exact default and passed the signed AegisQDA downstream
  E2E without an override: DigQDA `PASS`, zero post-scan findings, about 21 s;
- `gemma4:e4b` remains an explicitly allowed, independently proven reference
  model;
- `gemma4:12b` is rejected for this host and structured contract: only 3/8
  smoke units were valid, five responses were empty, and runtime exceeded 20
  minutes. It is not in the runtime allowlist.

See [synthetic acceptance](docs/SYNTHETIC_ACCEPTANCE.md),
[compatibility evidence](docs/COMPATIBILITY_EVIDENCE.md), and the
[next-step runbook](docs/RUNBOOK_NEXT_STEPS.md).

## Citation

If you use AegisQDA, please cite the archived release:

> Behnam Shad, K. (2026). *AegisQDA — local-first, fail-closed privacy gateway for qualitative data* (v0.1.0). Zenodo. https://doi.org/10.5281/zenodo.21854346

The DOI above is the concept DOI: it always resolves to the most recent version.
Machine-readable metadata is in [`CITATION.cff`](CITATION.cff).

## License

MIT, see [`LICENSE`](LICENSE).
