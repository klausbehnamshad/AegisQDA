# Security and privacy policy

AegisQDA is a privacy gateway for qualitative research data. A defect that lets
identifying text reach a privacy release is the most serious kind of bug this
project can have, and we handle it as a security issue.

## What to report

- any path by which identifying text reaches `PRIVACY_RELEASED` without being
  shown to the reviewer (missed or discarded findings, skipped spans, parser
  gaps);
- any way around the local boundary: remote calls, proxies, cloud-sync paths,
  model or upstream drift that is not detected;
- any way to bypass or forge the review, release or integrity checks.

## How to report

Use GitHub's private vulnerability reporting for this repository (Security tab,
"Report a vulnerability"). Please do not open a public issue for a suspected
privacy defect.

**Never send real transcripts, recordings or personal data**, not even an
excerpt. Describe the problem with a synthetic example, as in the files under
`tests/fixtures/`. If a defect only shows up with real material, describe its
shape (format, line breaks, language, entity type) instead of the content.

## Supported versions

Only the latest 0.1.x release receives fixes. AegisQDA 0.1.x is a synthetic-only
MVP: real-data processing is disabled in code.

## How we handle a confirmed defect

1. Reproduce it with synthetic data and the pinned models, and fix it so that
   uncertainty blocks rather than passes.
2. Revoke the affected recognizer pack in code. Runs scanned with it stop with a
   message naming the advisory, and `aegisqda audit` reports which existing runs
   are affected without printing any source text.
3. Add regression tests that fail on the affected version.

## How we communicate it

AegisQDA is research software in the Digital Humanities and qualitative social
research. Its users are researchers, research software engineers and the data
protection officers who approve their workflows. Our communication follows the
same rule as the tool: state what was checked, never claim more.

- **One public advisory per defect** in [`docs/advisories/`](docs/advisories/),
  in English with German and French summaries (the tool's languages). Each
  advisory says what happened, which versions are affected, who is exposed, how
  to check (`aegisqda audit`) and what to do. It does not promise anonymity, and
  it does not play the defect down.
- **The same text** goes into a GitHub Security Advisory, the changelog and the
  release notes, and the README links to it while the advisory is recent.
- **The scholarly record stays accurate.** A fixed version is archived as a new
  Zenodo version under the concept DOI, and the description of an affected
  version points to the advisory.
- **The community hears it where it reads.** A short, factual note goes to the
  Digital Humanities and research software channels the project announces on,
  with a link to the advisory. Where the defect is a pattern other
  de-identification tools could share, the advisory includes a section on it so
  other projects can check their own pipelines.
- **Timing.** Because 0.1.x only accepts synthetic material, we publish the
  advisory together with the fix. If a report shows that real data was exposed
  at a particular site, we first coordinate privately with the reporter and that
  site's data protection officer, then publish.

We aim to acknowledge a report within one week.
