# Synthetic interview corpus — red-expected de-identification suite

Interview-shaped, synthetic material for exercising the AegisQDA gateway end to
end (`scan → review → transform → analyze`) and for **measuring** how completely
identifiers are removed. This is an acceptance/measurement corpus, not a
green-by-construction happy path: on any given host, expected identifiers may
still leak (for example when NER recall is imperfect), and the verifier reports
exactly which. It is neither an anonymity claim nor a recall claim — see
`docs/THREAT_MODEL.md`.

## Synthetic disclosure (precise)

No real person and no real personal data. E-mail/URL use RFC 2606 reserved
domains (`*.invalid`, `*.example`); IP addresses are RFC 5737 TEST-NET; IBANs are
structurally-valid `LU` patterns with **invalid check digits**; phone numbers are
documentation-style `+352 621 xxx xxx` and are **not** verified as unassigned.
Place names (Esch, Dudelange/Düdelingen) are **real** Luxembourg municipalities
used only as a neutral geographic setting; they carry no linkage to any real
individual. Person and organisation names are invented. This is deliberately
narrower than "fully fictional": an earlier draft overclaimed that.

## Layout (per language de / fr / en)

- `expert_clean.srt` — a stakeholder interview whose identifiers are all
  `REPLACE`/`GENERALIZE`: name/org/city via the spaCy models, and e-mail, URL,
  phone, IBAN, IP, date, project ID via the regex pack. Intended to run to
  `PRIVACY_RELEASED` and on to `analyze`.
- `participant_blockdemo.txt` — seeded with **indirect** identifiers (kinship,
  occupation, age, small place, rare event). These are block actions, so release
  is fail-closed: it demonstrates the indirect-identifier guard, not a fault.
- `safe_control.txt` — no identifiers; should release with zero surrogates
  (over-redaction guard).

`interviews_manifest.json` (schema v2) lists, per file, the exact character
**spans** and per-file **SHA-256**, the seeded regex identifiers, and the
best-effort NER expectations used for recall measurement.

## Requires three verified detector changes

PERSON/ORGANIZATION/LOCATION handling depends on three changes in `src/aegisqda/`
that are covered model-free and verified against the installed trained models:
(1) NER label normalisation (`detection.LocalNlpEngine.process_text`); (2)
conservative precedence when a high-precision structured/context rule fully
contains a spaCy PERSON/LOCATION/ORGANIZATION span
(`detection.scan_document`); (3) the surrogate-aware second pass
(`workflow.transform_run`). Without (1), the de/fr models emit `PER`/`LOC`/`ORG`,
Presidio 2.2.x drops them, and names/places pass through uncaught. Without (2)/(3),
turning NER on breaks the release path (spaCy mislabels e-mails/IBANs; the second
pass re-ingests surrogates). See `docs/READINESS_REVIEW.md` for the measured gates.

## Verifying with the REAL detector

`scripts/verify_interviews.py` imports the installed `aegisqda`, runs the actual
`scan_document`, and checks every required finding against this manifest's exact
`(type, start, end)` spans and per-file SHA-256. It is an annotation checker /
declared-value leak oracle — not a release-path validator (the state machine is
covered by `pytest`). Without the spaCy models it exits **non-zero (GATED)** so it
cannot pass silently; `--regex-only` explicitly accepts a regex-only run.

```bash
.venv/bin/python -m pytest -q                        # complete release-path suite
.venv/bin/python scripts/synthetic_acceptance.py     # curated recall (de/fr/en PASS)
.venv/bin/python scripts/verify_interviews.py        # annotations (exit 0 with models)
```

## Where to put these to run them

`aegisqda scan` rejects in-repo sources except under `tests/fixtures/`, and
rejects cloud-synced paths. These files live under `tests/fixtures/interviews/`,
which `scan` accepts. The batch auto-review helper is additionally bound to the
per-file SHA-256 in this manifest, so a non-registered file dropped under
`tests/fixtures/` is refused automatic review. To keep a working corpus out of
Git history, copy this folder to a local, non-cloud volume and scan from there.
