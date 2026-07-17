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

