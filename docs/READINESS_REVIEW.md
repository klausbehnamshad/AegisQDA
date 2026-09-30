# Readiness review — before scaling from synthetic to real interviews

Date: 2026-07-18 (rev. 2). Scope: a code- and policy-level read of the MVP with
the goal of *running interviews* through the gateway, and of what must be settled
before any governed real-data pilot. Engineering review, not legal advice; it
does not authorise real data.

Rev. 2 supersedes rev. 1. Rev. 1 wrongly implied a working NER de-identification
path; a real run against the pinned Presidio version showed it was not working.
That defect is now P0 below, ranked above everything else, and is fixed with a
before/after proof.

## What is already strong

The runtime boundary is hard, not decorative: loopback is validated by resolving
the host and requiring every returned address to be loopback; proxy variables are
rejected before a source is read (verified live — the sandbox's own egress proxy
tripped the guard); the protected source is read through an `O_NOFOLLOW`
descriptor with a device/inode/size/mtime recheck; artifacts are written `0600`
via a non-overwriting hard-link atomic write. Provenance is bound end to end with
canonical JSON + SHA-256 seals, the exact Ollama model digest, and a hash-bound
`think=false` shim. The state machine cannot be short-circuited: `analyze`
re-validates the whole release envelope before calling DigQDA. The honest-claim
discipline — process release, never "anonymization guaranteed" — is carried into
the artifacts. That foundation is why the findings below are about *fitness for
real interviews*, not the core security model.

## P0 (was High, now FIXED with proof) — NER labels were never normalised, so names/orgs/places passed straight through, and the second-pass scan re-confirmed the release circularly

Root cause, confirmed against the pinned `presidio-analyzer==2.2.363`:
`SpacyRecognizer.analyze` in this version matches the **raw** spaCy label against
the recognizer's `supported_entities` and uses it verbatim as the result type;
it does **not** consult `CHECK_LABEL_GROUPS`. `detection.py` set
`supported_entities=["PERSON","ORGANIZATION","LOCATION"]`, but the de/fr models
emit `PER`/`LOC`/`ORG` and the en model emits `PERSON`/`GPE`/`LOC`/`ORG`. The
custom `LocalNlpEngine.process_text` handed Presidio `doc.ents` with those raw
labels and never mapped them. Net effect measured on the real library:

    before fix (real Presidio 2.2.363):
      de  -> PERSON/LOCATION/ORGANIZATION detected: NONE
      fr  -> NONE
      en  -> PERSON only; ORGANIZATION and LOCATION (GPE) dropped

Because the second-pass scan uses the same blind detector, it also missed the
survivors, so `transform` still produced `PRIVACY_RELEASED` with real names and
places intact — a circular green check.

Fix: normalise labels in the NLP engine before recognition
(`PER`/`PERSON`→`PERSON`, `LOC`/`GPE`→`LOCATION`, `ORG`→`ORGANIZATION`; unmapped
labels such as `MISC` are dropped).

Turning real NER on then surfaced two **integration regressions** that a clean
`entity_ruler` simulation had hidden and that the trained-model Mac exposed:

- *Surrogate re-ingestion.* The second-pass scan re-runs the detector on the
  transformed text, where spaCy now tags surrogate content like `PERSON_001` as a
  fresh PERSON, so `transform_run` blocked (de) or overlapped (fr). Fix, without a
  blanket bracket exemption (which could hide real bracketed content):
  `transform_run` records the exact character ranges of the surrogates it emitted
  and exempts second-pass findings that fall strictly *inside* one of them; a
  finding outside any surrogate still blocks. Validated model-free against the
  real `transform_run` (inside → releases, outside → blocks).
- *spaCy false positives over structured spans and transcript structure.* The
  real models labelled e-mails/IBAN fragments as LOCATION/ORGANIZATION and the
  French model labelled conventional `I:`/`P:` role markers as locations. The
  fix is deliberately narrow: a high-precision structured recognizer overrules
  only an NER span it fully contains; partial overlaps remain reviewable. Fixed
  context rules handle `groupe Novaform`, `centre culturel Ariston`, `based in
  Esch`, and equivalent German/English forms. Only the conventional line-leading
  `I:`/`P:` role markers are structural; arbitrary initials are not ignored.

Status on the trained-model host, 2026-07-18: **69 pytest tests pass**; the
existing four-language synthetic acceptance is PASS; the exact annotated
interview verifier is **9/9 PASS**; and the real privacy-only batch is **9/9**
with clean/safe files reaching `PRIVACY_RELEASED` and block fixtures stopping at
review. `ruff`, `mypy --check-untyped-defs`, and shell syntax are also green.
The complete downstream analysis batch was not run in this verification because
`doctor` reports the local Ollama inventory unavailable; that is an explicit
runtime blocker, not privacy-stage evidence. The model-free regression tests pin
normalisation, conservative precedence, transcript roles, and surrogate ranges
against future Presidio changes.

## F1 (High) — Indirect identifiers block release, and "keep" is not a free action

`policies/strict.yaml` defines no action for `AGE`, `KINSHIP` or `JOB_TITLE`, so
`Policy.action_for` returns the default `BLOCK`; the recognizers detect all three.
In review, a block action offers only false-positive `[f]` or abort `[a]`. So an
ordinary interview mentioning family, occupation or age blocks unless the
reviewer marks each true detection a "false positive" — which mislabels a correct
detection and pollutes any future precision/recall or audit metric.

Correcting rev. 1: a bare `KEEP_AND_REVIEW` that retains a true indirect
identifier and still prints `PRIVACY_RELEASED` is **not** an adequate fix on its
own — keeping a re-identifying token changes the residual-risk profile and would
need an explicit, logged residual-risk decision and a *different, weaker* release
claim than the one used when everything is surrogated. The preferred default is
genuine generalisation where it preserves analytic meaning (`AGE` → age band;
coarse dates → year), with `KEEP_AND_REVIEW` reserved for tokens that are truly
non-identifying in context and always carried with a distinct release claim and a
recorded rationale. `SMALL_PLACE`/`RARE_EVENT` stay block. This is the single most
important *policy* decision before running many interviews, and it belongs to the
DPO record, not to code defaults.

## F2 (Medium) — Overlaps can block transform; resolve them without over-suppressing

`transform_run` raises on any overlap among confirmed findings. The new
precedence rules remove only fully-contained, high-confidence duplicates. A
partial overlap remains a genuine ambiguity and must not vanish silently. Build
explicit overlap **groups**, resolve clearly-contained same-class duplicates with
a recorded suppression marker, and surface cross-type or partial overlap to the
human reviewer. Silent longest-span selection would trade the original P0 for a
quieter version of the same risk.

## F3 (Medium) — Open-world recall is unmeasured; the corpus is now the scaffold for measuring it

The "15/15 per language" figure is fixture-scoped and, for names/orgs/places, a
property of the spaCy models, not of AegisQDA. The delivered corpus is now an
**annotated acceptance suite**: `interviews_manifest.json` carries exact char
spans and per-file SHA-256, and `verify_interviews.py` verifies every required
typed span with the real detector. The release path and surrogate-aware second
pass are exercised separately by pytest and the batch runner. Next
steps: expand it with hard cases (code-switching, titles/initials, foreign names,
split-line mentions, indirect-identifier combinations) and track recall over time
alongside `scripts/synthetic_acceptance.py`. Treat red as information, not
failure.

Update 2026-09-30: split-line mentions were a real leak, not only a gap in the
suite. With the pinned de/fr/en models, NER returns a name wrapped inside an
SRT cue (`Anna\nSchneider`) as one entity; `scan_document` dropped every span
that did not fit into a single content line, so such names reached
`PRIVACY_RELEASED` unreviewed. The same happened to spans crossing U+2028 and
to bracketed values (`[Jane Example]`), which a blanket bracket skip in the
detector hid. Spans are now split into per-line pieces, only exact surrogate
shapes are skipped, other Unicode line separators are rejected at parse time,
and `recognizer_pack` is `aegis-custom-strict-v3`. Regression tests pin all
three cases.

## F4 (Medium) — Post-DigQDA output scan hard-codes the analytical-prose language

`digqda_adapter._scan_outputs` scans generated analytical prose as German and
only routes `source_text`/`source_quote` to the declared source language. This is
a reasonable assumption for the pinned German `QDA-GEN-DESCRIPTIVE-CODING` prompt
but is a silent coupling: if the prompt language changes, or analytical prose
reintroduces a French/English name, the post-scan can miss it. Bind the
analytical-prose language in the DigQDA contract manifest and read it here; add a
regression that fails if the pinned prompt language and this assumption diverge.

## F5 (Medium, gating for real data) — The review-key trust store is declared but never enforced

Confirmed by inspection: `authorization.trusted_review_key_ids` appears only in
the config schema (`config.py`) and is referenced nowhere in the logic.
`verify_review_signature` checks that the embedded signature validates against the
embedded public key — i.e. it proves self-consistency, not trust. So any
self-generated, internally-valid Ed25519 signature is accepted as "signed." Real
data is hard-disabled today, and `transform` only accepts an unsigned review
because `synthetic_only` is true, so nothing is currently exposed. But before a
pilot, the trust path must actually enforce the fingerprint allowlist: bind
`key_id_sha256` against `trusted_review_key_ids`, and define custody, rotation,
revocation and audit retention. This is on the critical path, not optional.

## F6 (Low/Medium) — Luxembourg context, Luxembourgish unsupported

The fixtures use `+352` numbers and `LU` IBANs (a Luxembourg study) while `lb` is
correctly blocked. The real exposure is not a declared-`lb` file — the gate
handles that — but Luxembourgish passages embedded in a `de`/`fr` transcript when
a participant code-switches; those tokens are scanned with the declared pack and
may be missed. Decide and document the policy for embedded `lb`, and include
code-switching cases in the F3 suite.

## F7 (Low) — "Generalize" currently discards analytic value

`GENERALIZE_AND_REVIEW` emits a typed placeholder indistinguishable in analytic
value from a plain replacement. For QDA, coarse temporal/age information often
carries meaning (sequence, cohort). True generalisation (year-only dates, age
bands) would preserve some utility while de-identifying — and it is the mechanism
F1 wants for `AGE`.

## F8 (Low) — Defence-in-depth against a real transcript under tests/fixtures

`scan` trusts in-repo sources only under `tests/fixtures/`, which is also where a
stray real transcript could be dropped. The synthetic auto-review helper is now
bound to the corpus SHA-256 allowlist (a foreign file is refused, verified), which
closes the automated path. Still worth adding: a pre-commit hook and a scan-time
warning when a `tests/fixtures` source is not in the manifest, and a re-check that
`.gitignore` covers run roots, `*.pem`, and any external corpus directory.

## Suggested order of work

P0 and its integration regressions are fixed and locally verified; land them
together with their regression tests. Then F1 (the
policy decision that otherwise blocks every real interview), then F2 (so batch
runs don't stall on avoidable overlaps), with F3 in parallel since the annotated
corpus already exists. F4–F8 are pre-pilot hardening and line up with
`RUNBOOK_NEXT_STEPS.md`. None of them should be closed by loosening a control.
