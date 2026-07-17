# Installation, supported versions, and versioning policy

## Requirements

- **Python:** 3.12 or 3.13 (the versions exercised by CI). Earlier 3.x may work
  but is unverified.
- **Python packages** (`requirements.txt`): `rapidfuzz` (≥3,<4), `jsonschema`
  (≥4.18,<5), `ollama` (≥0.3,<1).
- **Ollama** with a local model (default: `gemma4:e4b`) is required **only** for real
  model calls. Dry runs, the conformance suite, and most contract checks do not
  need a running model service.

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
```

## Verify

```bash
python3 90_UTILITIES/tests/run_tests.py     # expect: all checks PASS
./digqda doctor                             # environment check
DRY=1 bash 90_UTILITIES/smoke/run_smoke.sh  # model-free end-to-end plumbing
```

For a real local run, install Ollama, pull a model, and use the exact installed
tag (`ollama list`). Tested model/backend combinations are recorded in
[`docs/MODEL_COMPATIBILITY.md`](MODEL_COMPATIBILITY.md); other local models are
unverified.

## Supported versions

Until the first tagged release, treat the tree as `0.4.x`-draft. Once a SemVer
release is tagged, the latest minor line is the supported line; older lines are
unsupported unless stated otherwise.

## Versioning and migration policy

DigQDA follows Semantic Versioning for the package. Independently, the run
manifest carries separate **contract**, **schema**, **prompt** and **library**
versions, so a package bump never conceals a breaking edge change (see
`GOVERNANCE.md`). Change classes:

- **Patch** — implementation or wording fix, no contract/schema/edge change.
- **Minor** — backward-compatible feature, prompt or schema addition.
- **Major** — incompatible contract, schema, acceptance-semantics or
  method-claim change.

Consumers should pin the exact `contract_version`, `schema_sha256`,
`prompt_version` and `library_version` they have validated, as required by the
Integration Contract (`contracts/DigQDA-INTEGRATION-CONTRACT_v0.1.md`).
