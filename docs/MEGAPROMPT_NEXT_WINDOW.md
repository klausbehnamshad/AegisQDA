# Megaprompt — build the AegisQDA local CLI MVP

Copy everything below into a fresh Codex context whose workspace is
`/Users/klaus.behnamshad/Projects/AegisQDA`.

---

You are the primary implementation agent for **AegisQDA**. Work only inside:

`/Users/klaus.behnamshad/Projects/AegisQDA`

Do not modify, stage, commit or write into sibling repositories, especially:

- `/Users/klaus.behnamshad/Projects/DigQDA`
- any DINOH repository or directory

## Mission

Build the first fully local, command-line AegisQDA MVP. It is a strict privacy
gateway placed before the pinned DigQDA snapshot. It accepts only synthetic
SRT/TXT during development, detects direct and configured indirect identifiers,
creates typed sequential surrogates, requires human review, performs a second
scan and structural validation, and invokes DigQDA only after a signed privacy
release gate.

Do the work; do not merely write another plan. Inspect the repository first,
read all files under `docs/`, `config/`, `policies/`, `UPSTREAM.lock.json`, and
the relevant interfaces under `vendor/digqda/`. Preserve the new AegisQDA Git
history and treat `vendor/digqda/` as read-only.

## Non-negotiable runtime boundary

1. **No cloud. No remote API. No remote inference.**
2. Presidio Analyzer and Anonymizer run in-process and locally.
3. Ollama may be contacted only through an explicitly validated loopback URL.
4. Reject non-loopback hosts, proxy environment variables and remote endpoint
   configuration before reading a source.
5. Never silently download models at runtime.
6. Never silently fall back to another language or model.
7. Default downstream analysis model: exact local tag `gemma4:12b`.
8. Also recognize `gemma4:e4b` only because it is explicitly present in the
   current local allowlist. Do not add models without a config/governance change.
9. Bind the exact Ollama model digest in every accepted downstream run.
10. Do not use Azure PII, OpenAI, hosted Presidio, telemetry or any web service.

If `gemma4:12b` is not installed, `aegisqda doctor` must fail with an actionable
message. Do not pull it without explicit user authorization because the model is
large and changes host state.

## Honest privacy claim

The user wants anonymization to be "knallhart". Implement that as a hard,
fail-closed release process. Never claim that Presidio or any software can
mathematically guarantee anonymity of arbitrary free text. The program may say:

`PRIVACY_RELEASED under policy X after automatic checks and human sign-off`

It may not say:

`anonymization guaranteed`

Any unsupported language, unresolved entity, ambiguous indirect identifier,
missing recognizer/model, missing sign-off, structural drift, second-pass hit,
unexpected endpoint or provenance mismatch must block with a non-zero exit and
must prevent DigQDA invocation.

## Required languages

- German (`de`)
- French (`fr`)
- Luxembourgish (`lb`)
- English (`en`)

No language fallback. Configure local NLP engines and recognizers separately.
German/French/English may use verified local spaCy or Stanza models. Treat
Luxembourgish as unsupported until an explicit local tokenizer/NER strategy plus
custom recognizers passes its own synthetic suite. A declared-but-unready
language blocks; it does not degrade to German or multilingual guessing.

## Required CLI

Implement a stable `aegisqda` entry point with:

### `aegisqda doctor`

- validates Python dependencies and local NLP model availability;
- verifies Presidio imports and versions;
- validates policy/config schemas;
- verifies that runtime settings contain no cloud/API endpoint;
- rejects active proxy environment variables unless explicitly proven irrelevant
  to a loopback-only subprocess environment;
- checks Ollama only at loopback;
- lists exact installed/approved model tags without source text;
- verifies `gemma4:12b` and records its digest if installed;
- verifies the pinned DigQDA snapshot and lock;
- never downloads or changes host state.

### `aegisqda scan SOURCE --language {de,fr,lb,en} --case-id OPAQUE_ID`

- accepts only local `.srt`/`.txt` outside Git and cloud-sync paths;
- creates a fresh owner-only external run directory;
- detects configured direct identifiers and custom indirect-risk patterns;
- writes a protected detection ledger without clear text in general logs;
- emits `REVIEW_REQUIRED`, never a privacy release;
- supports only synthetic sources until an explicit `--authorized-real-data`
  gate exists and the internal operational procedure is filled.

### `aegisqda review RUN_DIR`

- local terminal review only for MVP;
- shows protected context deliberately and never sends it elsewhere;
- reviewer can confirm, reject or add detections;
- unresolved or skipped findings block;
- writes reviewer, timestamp, policy hash and decision into a protected signed
  review artifact. A simple local keyed signature may be designed later; for MVP
  use an integrity hash plus explicit reviewer identity and document limitations.

### `aegisqda transform RUN_DIR`

- consumes only an accepted review artifact;
- applies typed sequential replacements such as `[PERSON_001]`;
- maintains co-reference only within one document;
- keeps the original-to-surrogate map in memory and discards it after writing;
- writes no reversible mapping in strict mode;
- preserves SRT cues/time ranges and TXT newline/unit structure;
- performs a second scan and blocks on unresolved findings;
- produces a privacy release envelope with hashes and no clear-text PII.

### `aegisqda analyze RUN_DIR [--model exact-tag]`

- requires a valid privacy release envelope;
- revalidates all hashes, policy, reviewer and local-only endpoint;
- passes only the transformed source and opaque ID to the pinned DigQDA CLI;
- model must be in the explicit allowlist and installed exactly;
- never passes the original or detection ledger to DigQDA;
- captures DigQDA provenance and validates model digest/scope binding;
- scans DigQDA outputs again before any external release designation.

### `aegisqda run SOURCE ...`

May orchestrate the above stages but must stop at human review; it must never
auto-approve a source.

## Implementation shape

Use `src/aegisqda/` with small modules, for example:

- `cli.py`
- `config.py`
- `errors.py`
- `safeio.py`
- `local_boundary.py`
- `formats/srt.py`, `formats/text.py`
- `languages.py`
- `recognizers/`
- `detection.py`
- `review.py`
- `transform.py`
- `privacy_gate.py`
- `digqda_adapter.py`
- `manifests.py`

Use atomic writes, fresh non-overwriting run directories, mode `0700` for
directories and `0600` for files, no symlinks, path-confinement checks, opaque
IDs and no raw source in normal logs/exceptions.

Do not modify files under `vendor/digqda/`. Integrate through its documented CLI
and contracts. If an upstream change seems necessary, stop and describe it;
never patch the sibling or vendored copy silently.

## Presidio design

- Use `presidio-analyzer` and `presidio-anonymizer` locally.
- Bind package versions, NLP model identifiers, recognizers, thresholds and
  policy hash in the detection manifest.
- Add custom recognizers for project identifiers and language-specific patterns.
- Keep low thresholds to prioritize recall; false positives go to human review.
- Do not call Azure AI Language or any external detector.
- Implement a policy registry which defaults unknown entity types to `BLOCK`.
- Second-pass analysis is necessary but not sufficient; reviewer sign-off remains
  mandatory.

## Tests before any real material

Build model-free tests using only `tests/fixtures/` and add many more synthetic
cases. Required categories per language:

- direct PERSON/ORG/LOCATION;
- phone/email/URL/IBAN/IP;
- dates, ages, jobs and kinship;
- small-place plus rare-event combinations;
- spelling variation, punctuation and code-switching;
- repeated entities for within-document co-reference;
- safe controls to measure destructive over-redaction;
- malformed SRT/TXT;
- unknown speaker/language;
- cloud path, symlink, repo path and traversal attacks;
- proxy/remote endpoint attempts;
- stale/tampered review and release manifests;
- clear-text leakage into logs, filenames and manifests;
- attempted DigQDA invocation before release.

Acceptance for the curated fixtures:

- 100% of seeded direct identifiers detected;
- every seeded ambiguous/unsupported case blocks;
- no seeded clear-text identifier remains after release;
- zero SRT cue/time-range or TXT newline drift;
- no downstream invocation before human sign-off;
- no remote endpoint accepted;
- separate reports for de/fr/lb/en;
- false positives reported explicitly, never hidden by tuning.

## Work sequence

1. Run `python3 scripts/bootstrap_check.py` and inspect Git status.
2. Create `.venv`, install only declared local Python dependencies after user
   approval if network access is required, and record exact resolved versions.
3. Implement config schemas, errors, safe I/O and local-boundary doctor first.
4. Implement format-preserving SRT/TXT parsing and structural fingerprints.
5. Implement detection and language registry with synthetic tests.
6. Implement mandatory review state machine.
7. Implement transform, second scan and privacy release envelope.
8. Implement the read-only DigQDA adapter and local model allowlist/digest checks.
9. Run Ruff, mypy, pytest, bootstrap check and all vendored DigQDA conformance
   tests that do not mutate the snapshot.
10. Run a local synthetic E2E. Do not use real data.
11. If `gemma4:12b` is absent, report the exact blocker and ask before pulling.
12. Update README, architecture, threat model, compatibility evidence and the
    next-step runbook with measured results only.

## Stop conditions

Stop and ask the user rather than guessing if:

- the authoritative DPO model allowlist differs from the two configured tags;
- a Luxembourgish local NLP model/recognizer choice materially changes scope;
- installing/downloading a large model or dependency is required;
- a design would store a reversible identity map;
- real data is requested before synthetic acceptance;
- a cloud/API dependency appears necessary;
- any task would modify DigQDA or DINOH.

## Completion standard for this context

Do not call the MVP complete merely because Presidio runs. Completion requires:

- working CLI stages and hard state transitions;
- model-free adversarial tests;
- four-language synthetic reports, with unsupported Luxembourgish blocked until
  genuinely supported;
- local-only doctor;
- format preservation;
- review-required workflow;
- second-pass and privacy release manifest;
- DigQDA adapter that cannot run early;
- precise documentation of residual risk;
- clean Git diff and no research data in the repository.

Lead every progress report with the actual gate state. Keep all work inside
AegisQDA. No cloud, no API, no silent fallback, no false anonymity guarantee.

---

