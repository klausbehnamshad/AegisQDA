# Threat model

## Primary failures

- false-negative PII detection;
- indirect identification from combinations of place, job, age and rare event;
- over-redaction which destroys qualitative meaning;
- mapping leakage or cross-document linkability;
- source text in logs, exceptions, caches or quarantine;
- accidental cloud/API call or proxy routing;
- speaker/cue/line corruption before DigQDA;
- model hallucination reintroducing identifying information into outputs;
- unpinned upstream or model drift.

## Required controls

- deny-by-default local configuration;
- loopback endpoint validation and proxy-environment rejection;
- low-threshold detection followed by mandatory review;
- language-specific recognizers and synthetic recall suites;
- indirect-identifier review checklist;
- owner-only directories/files and no raw text in general logs;
- second-pass scan and post-DigQDA output scan;
- exact model tag/digest and exact upstream snapshot binding;
- no `PASS` on unsupported language, missing reviewer or unresolved finding.

## Residual risk

Human reviewers can miss indirect identifiers and language models/recognizers can
have blind spots. AegisQDA must report residual risk and the tested scope instead
of claiming universal anonymity.

The MVP combines a deliberately narrow custom rule pack with installed local
large spaCy NER packages for de/fr/en. Both are measured only on curated
synthetic fixtures; this does not establish open-world recall. Luxembourgish
has no approved local tokenizer/NER strategy and is blocked before source
reading. SHA-256 review
integrity alone is not an identity proof; optional Ed25519 reviews remain
self-signed until the public-key fingerprint is infrastructure-trusted. Local
administrators can modify protected files, exact-value hashes may be guessable for low-entropy identifiers, and a
reviewer can make a wrong false-positive decision. These limitations prohibit
real-data use and unattended release.

Post-DigQDA scanning covers text fields in the result and validation envelopes.
Bound source/evidence fields are scanned in the declared source language, while
DigQDA's generated analytical prose is scanned in the contract language German.
This routing is a bounded assumption and must be revisited if the pinned prompt
language changes. It does not establish that generated prose is safe to
publish. DigQDA results
therefore end in `DOWNSTREAM_REVIEW_REQUIRED`, never an external-release state.
