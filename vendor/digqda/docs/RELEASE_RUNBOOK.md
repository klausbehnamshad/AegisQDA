# Release runbook — v0.4.0 (ORCID · Zenodo DOI · ORBilu)

This is the turnkey path to a citable public release. The build is done; what
remains are identity-bound account steps that only the maintainer can perform.
Do the steps in order — the Zenodo↔GitHub toggle must be set **before** the
GitHub release, or that release will not be archived.

## Preconditions (done)

- Repository public, tests green (117/117), CI runs Ruff + tests, semantic
  canary lint/selftests/dry-run and dry-smoke on
  clean Python 3.12/3.13.
- Name checked — no exact collision on PyPI/GitHub/Zenodo.
- `CITATION.cff` (repository URL set; ORCID/DOI slots ready), `.zenodo.json`,
  `docs/INSTALL.md`, `SECURITY.md`, README audited.

## Step 1 — ORCID (~2 min)

1. Register at <https://orcid.org/register> (free) → obtain an iD like
   `0000-0002-1825-0097`.
2. Put it into **`CITATION.cff`** (uncomment the `orcid:` line under the author)
   and into **`.zenodo.json`** (add it to the creator):
   ```json
   "creators": [ { "name": "Behnamshad, Klaus", "orcid": "0000-0002-1825-0097" } ]
   ```

## Step 2 — Connect Zenodo to GitHub (before releasing)

1. Sign in to <https://zenodo.org> (you can log in with GitHub or ORCID).
2. Go to **Zenodo → your profile → GitHub** (or <https://zenodo.org/account/settings/github/>).
3. Flip the switch **ON** for `klausbehnamshad/DigQDA`.
   *(Only releases created after the switch is on are archived.)*

## Step 3 — Finalise release metadata (one small commit)

In `CITATION.cff`, set the release facts:
```yaml
version: "0.4.0"
date-released: "YYYY-MM-DD"   # beim tatsaechlichen Release setzen
```
Confirm `.zenodo.json` carries the ORCID from Step 1. Commit and push.

## Step 4 — Tag and release on GitHub → DOI is minted

```bash
git tag -a v0.4.0 -m "DigQDA v0.4.0"
git push origin v0.4.0
```
Then on GitHub: **Releases → Draft a new release → choose tag `v0.4.0`**, title
`DigQDA v0.4.0`, paste the notes below, **Publish**. Zenodo detects the release
and mints two DOIs: a **version DOI** (this release) and a **concept DOI** (all
versions — the one to cite generally).

Suggested release notes:
```text
DigQDA v0.4.0 — first archived pre-release.

- P0 deterministic segmentation (SRT/TXT); P1 local coding via Ollama with a
  forced JSON schema and mode-specialised grammar; external quote/locator
  validation; fail-closed semantics and full run provenance.
- Stable `digqda` entry point (doctor, pilot); synthetic smoke harness; 117/117
  conformance checks; semantic canary v1.1.0 with 10/10 local Gemma 4 passes;
  CI on Python 3.12/3.13.
- Consumer-neutral Integration Contract; method-claim boundaries.
Software only; contains no research data.
```

## Step 5 — Record the DOI and push

Copy the **concept DOI** from Zenodo and add it to `CITATION.cff`:
```yaml
doi: "10.5281/zenodo.XXXXXXX"
```
Optionally add a DOI badge to the README. Commit and push. Then flip the README
"Publication status" note to released.

## Step 6 — Deposit / register in ORBilu (Uni Luxembourg)

*(Assumes ORBilu, <https://orbilu.uni.lu>. If you meant a different institutional
repository, the fields are analogous.)*

1. Sign in to <https://orbilu.uni.lu> with your uni.lu credentials.
2. New deposit → type **software** (or the closest available research-output
   type).
3. Fill: title (as in `CITATION.cff`), author (you + ORCID), year, the **Zenodo
   concept DOI**, the GitHub URL as the resource location, MIT licence,
   keywords, and the abstract from `CITATION.cff`.
4. Set open access and submit for library validation.

## Who does what

- **Automated / already done:** name check, metadata files, `.zenodo.json`,
  install & versioning docs, README audit, conformance in clean CI.
- **Only you (identity/accounts):** ORCID registration; Zenodo login + toggle;
  creating the GitHub release/tag; ORBilu deposit (uni.lu SSO).

After Steps 1–6 the remaining `RELEASE_CHECKLIST.md` items (authorship/ORCID,
security contact, tag+archive, DOI) are all satisfied.
