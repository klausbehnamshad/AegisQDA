# DigQDA

**Digital QDA — AI-assisted, evidence-bound qualitative data analysis with local models**

DigQDA is an independent, versioned method-contract toolkit for evidence-bound
qualitative analysis with local language models. It is upstream research
software: governed applications may consume its contracts, prompts, schemas and
reference validators, but DigQDA has no dependency on any consuming system.

> Status: pre-release (`0.4-draft`). DigQDA is not itself a research
> infrastructure and does not claim to implement a complete named qualitative
> methodology.

## What DigQDA provides

- versioned method contracts and allowed-method-claim boundaries;
- source-near coding prompts with machine-readable JSON schemas;
- deterministic source-unit segmentation and quote/locator validation;
- a local Ollama reference runner with fail-closed conformance checks;
- a consumer-neutral integration contract and conformance suite.

## Boundary

DigQDA publishes software and contains no research data. When executed on a
transcript, however, it **does process that input and its derived quotations**.
The consuming application therefore remains responsible for authorization,
data access, storage, logging, retention and release. Outputs must be treated as
potentially sensitive.

The normative edge is defined in
[`contracts/DigQDA-INTEGRATION-CONTRACT_v0.1.md`](contracts/DigQDA-INTEGRATION-CONTRACT_v0.1.md).

```text
governed consumer
  authorizes and selects one bounded source unit
            |
            v
DigQDA method contract + reference implementation
  returns a proposal and validation manifest
            |
            v
governed consumer
  binds protected provenance, stores, reviews and releases
```

A permissible production run requires both conditions:

```text
governance authorization AND valid method contract
```

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
python3 90_UTILITIES/tests/run_tests.py
./digqda doctor
```

The Ollama dependency is required only for real model calls. Dry runs and most
contract checks do not require a running model service.

### Supervised pilot workflow

The method-first pilot path has one stable entry point. It creates a fresh,
owner-only run directory, hides the source filename behind an opaque case ID,
runs P0 → P1 → external validation and evaluates the complete provenance gate:

```bash
./digqda pilot CASE-001 /secure/path/interview.srt
```

For interviewee-only analysis, bind the transcript's explicit speaker labels to
roles and filter before P1: `--role-map /secure/path/roles.json --include-role
interviewee`. Unmapped or mixed speaker units fail closed.

The default is `OPEN_DESCRIPTIVE` with local `gemma4:e4b`; mode, codebook,
research question and model remain explicit method choices. Runtime artifacts
go to `~/DigQDA-Pilot` by default and never into the Git repository. See
[`90_UTILITIES/pilot/README_PILOT.md`](90_UTILITIES/pilot/README_PILOT.md).

### Synthetic end-to-end smoke test

The bundled smoke harness joins the reference stages into one fail-closed local
path. It exercises P0 for SRT and TXT, then runs OPEN and STRICT P1 coding plus
external validation against the synthetic SRT fixture:

```bash
DRY=1 bash 90_UTILITIES/smoke/run_smoke.sh
ollama list
MODEL=<exact-installed-gemma-tag> bash 90_UTILITIES/smoke/run_smoke.sh
```

The real-model command accepts only an installed exact Ollama tag. Generated
artifacts stay under the ignored `90_UTILITIES/smoke/out/` directory. See
[`90_UTILITIES/smoke/README_SMOKE.md`](90_UTILITIES/smoke/README_SMOKE.md) for
the exit-code and review contract. Do not substitute real transcripts for the
synthetic fixtures.

The current pilot target is
[`gemma4:e4b` via Ollama](docs/MODEL_COMPATIBILITY.md). Compatibility evidence
is model-specific and records technical smoke and semantic canary results
separately; neither result removes human review.
Tested model/backend combinations are limited to those recorded in
`docs/MODEL_COMPATIBILITY.md`; other local models are unverified, and DigQDA does
not claim model agnosticism.

### Invalid-response quarantine

Raw invalid model responses are never persisted by default. For an explicitly
governed pilot diagnosis, pass `--diagnostic-quarantine`; files are isolated in
that run's protected external directory under hash-derived names. Low-level
runner integrations can use `--quarantine-dir`. The contents can still contain
sensitive source material and require the same access, retention and deletion
controls as other research data.

## Repository map

- `contracts/` — normative consumer boundary;
- `00_CORE/` — reliability design and method-independent principles;
- `10_GENERIC/` — generic coding prompts and schemas;
- `90_UTILITIES/` — reference CLIs and conformance tests;
- `digqda` — stable local entry point for environment checks and pilot runs;
- `docs/METHOD_CATALOG.md` — broader method-family catalog inherited from the
  prototype and retained as design context;
- `GOVERNANCE.md` — lightweight method governance and release policy.

## Independence

DigQDA must not import consumer code, name consumer-specific entities in its
contracts, or decide whether a data subject, project or source is authorized.
Consumers integrate through adapters and pin the exact contract, schema and
DigQDA versions they have validated.

## Publication status

This repository is not yet ready for a public release. A public `v0.4.0` is
blocked until maintainers confirm the final project/repository name,
authorship/ORCID and repository metadata, validate the release in clean
environments, and archive the versioned release. See
[`docs/RELEASE_CHECKLIST.md`](docs/RELEASE_CHECKLIST.md).
