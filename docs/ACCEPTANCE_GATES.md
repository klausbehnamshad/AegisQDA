# Acceptance gates

## Privacy release: all required

- declared language is supported and its recognizer pack is loaded;
- detector run completed with bound configuration/model versions;
- every detection is resolved by policy and reviewer;
- no unresolved second-pass finding remains;
- no prohibited indirect identifier remains after human review;
- SRT/TXT structural equivalence passes;
- source and release hashes are recorded without clear-text PII;
- reviewer identity, timestamp and policy version are bound;
- runtime endpoint evidence is loopback-only;
- no proxy/cloud/API configuration is active.

Any failed or missing item produces `BLOCKED`, a non-zero exit and no DigQDA
invocation.

## Synthetic MVP targets

- 100% detection of every seeded direct identifier in the curated fixtures;
- 100% block rate for seeded unsupported/ambiguous cases;
- zero cue/time-range/line-count drift;
- zero clear-text seeded identifier in released sources and general logs;
- explicit false-positive reporting; precision is reviewed but never traded for
  recall silently;
- de/fr/en have independent required reports; optional lb has an independent
  report and remains fail-closed.

These are fixture-scoped acceptance targets, not a universal anonymity claim.
