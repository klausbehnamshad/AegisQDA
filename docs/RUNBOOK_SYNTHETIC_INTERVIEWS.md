# Runbook — running synthetic interviews end to end

Operational gate: **synthetic-only / real data blocked** (unchanged). This drives
the bundled synthetic interview corpus through `scan → review → transform →
analyze`. It changes no policy and grants no real-data path. Everything runs
locally; only `analyze` needs a loopback Ollama with `gemma3:4b`.

## 0. Prerequisites and merge gate

This corpus depends on three verified changes in `src/aegisqda/`: (1) NER label
normalisation in `detection.LocalNlpEngine.process_text`; (2) conservative
precedence for fully-contained structured/contextual findings plus transcript
role markers in `detection.scan_document`; (3) the exact-range, surrogate-aware
second pass in `workflow.transform_run`. See the P0 entry in
`docs/READINESS_REVIEW.md`.

Before treating any "clean → released" result as real, run the **merge gate** on a
host with the spaCy models installed:

```bash
.venv/bin/python -m pytest -q             # expect the complete suite to pass
.venv/bin/python scripts/synthetic_acceptance.py   # expect de/fr/en PASS
.venv/bin/python scripts/verify_interviews.py      # exit 0 with models present
```

`verify_interviews.py` exits non-zero (GATED) when the models are absent rather
than printing green; `--regex-only` explicitly accepts a regex-only run. It is an
annotation checker / declared-value leak oracle against the manifest's exact
`(type, start, end)` spans and file hashes — not a release-path validator; the
state machine is covered by `pytest`.

Confirm the boundary is ready (optional-language `lb` warnings do not block
de/fr/en):

```bash
.venv/bin/aegisqda doctor          # want "gate": "READY"
```

## 1. What the corpus contains

Per language `de/fr/en`, under `tests/fixtures/interviews/<lang>/`:
`expert_clean.srt` (all `REPLACE`/`GENERALIZE` identifiers; intended to release),
`participant_blockdemo.txt` (indirect identifiers; fail-closed by design), and
`safe_control.txt` (no identifiers; releases with zero surrogates).
`interviews_manifest.json` (v2) carries exact spans and per-file SHA-256.

## 2. The honest path — one interview, human review

Mirrors real use: a human resolves every finding.

```bash
.venv/bin/aegisqda scan tests/fixtures/interviews/de/expert_clean.srt \
  --language de --case-id SYNTH-DE-CLEAN --synthetic
# -> REVIEW_REQUIRED ; run_dir=/private/tmp/aegisqda-runs/SYNTH-DE-CLEAN/run-XXXXXX

RUN=/private/tmp/aegisqda-runs/SYNTH-DE-CLEAN/run-XXXXXX
.venv/bin/aegisqda review "$RUN" --reviewer REVIEWER-001
.venv/bin/aegisqda transform "$RUN"   # -> PRIVACY_RELEASED
.venv/bin/aegisqda analyze  "$RUN"    # -> DOWNSTREAM_REVIEW_REQUIRED
```

For the block-demo, `review` offers only `[f]`/`[a]` on the indirect identifiers;
the correct action is abort. For the safe control, `review` shows no findings.

Optional local signing: `keygen-review /secure/reviewer.pem` once, then
`review … --signing-key /secure/reviewer.pem`. (Note: the signature currently
proves self-consistency only; the trust-store allowlist is not yet enforced — see
F5 in the readiness review. Not a real-data path.)

## 3. The batch path — fail-closed smoke over all nine files

For plumbing checks (not a substitute for human review). The runner asserts the
expected terminal state per kind and exits non-zero on any deviation; it dies
immediately if the venv or `aegisqda` is missing (it never exits 0 silently). A
**full** run requires doctor READY so `analyze` actually runs — it dies otherwise:

```bash
bash scripts/run_synthetic_interviews.sh                 # full run: doctor required
bash scripts/run_synthetic_interviews.sh --privacy-only  # smoke scan→review→transform only
```

Expected: `clean`/`safe` reach `DOWNSTREAM_REVIEW_REQUIRED` on a full run (or
`PRIVACY_RELEASED` with analyze deliberately skipped under `--privacy-only`);
`block` stops at review with `BLOCKED_BY_DESIGN`. The review step uses
`scripts/auto_review_synthetic.py`, guarded by two conditions: the run must be
`synthetic_only`, **and** the source SHA-256 must be registered in the repo-bound
`interviews_manifest.json`. The helper validates the fixed manifest against the
actual corpus bytes and exposes no caller-supplied allowlist override, so a real
transcript mistakenly placed under `tests/fixtures/` is refused. It confirms only
`REPLACE`/`GENERALIZE` findings and refuses any
block-action finding rather than silently dropping it.

Override as needed: `VENV=.venv MODEL=gemma3:4b RUN_ROOT=/private/tmp/aegisqda-runs
bash scripts/run_synthetic_interviews.sh`. Use `MODEL=gemma4:e4b` only to exercise
the explicitly-allowed reference model; never `gemma4:12b`.

## 4. Where things live, and cleanup

Run artifacts are owner-only (`0700`/`0600`) under `RUN_ROOT`
(default `/private/tmp/aegisqda-runs`), outside Git. `analyze` refuses to
overwrite a completed run; start a fresh `scan` to re-run. `rm -rf` a run
directory to discard it.

## 5. Two behaviours worth knowing before you scale up

- **Same-type NER overlaps can still block `transform`.** spaCy false positives
  over structured spans (e-mail/IBAN/URL/…) are now suppressed, and surrogate
  re-ingestion in the second pass is handled. But when the spaCy model and a
  name-template rule both flag a PERSON/LOCATION/ORGANIZATION with different
  bounds, that overlap is still surfaced and, if both are confirmed, `transform`
  stops. Resolve by marking the redundant span a false positive in `review`. This
  is the open F2 calibration — do not "fix" it with blanket auto-suppression.
- **Indirect identifiers are fail-closed by default.** `AGE`, `KINSHIP` and
  `JOB_TITLE` have no `REPLACE`/`GENERALIZE` action in `policies/strict.yaml`, so
  they fall to the policy default `BLOCK`. Any transcript mentioning family,
  occupation or age blocks until a human rules on each. F1 in the readiness review
  proposes the policy decision (generalisation for `AGE`; an explicit, logged
  keep-with-weaker-claim only where truly non-identifying).
