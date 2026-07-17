# AegisQDA project charter

## Objective

Build a completely local command-line privacy gateway which prepares qualitative
SRT/TXT material for the pinned DigQDA method pipeline. The first MVP is
synthetic-only, requires German, French and English, and reports Luxembourgish
as an explicitly blocked optional language until its NLP strategy is approved.

## Fixed decisions

- Project name: AegisQDA.
- Independent repository and history.
- DigQDA is a pinned, read-only upstream snapshot.
- Runtime has no cloud service and no remote API.
- Ollama is loopback-only.
- Local `gemma3:4b` is the default analysis target; no silent fallback.
- `gemma4:e4b` is an explicit verified reference, not an automatic fallback.
- `gemma4:12b` is rejected for this host and structured contract.
- Human review is mandatory before downstream analysis.
- Strict policy blocks on uncertainty.

## Honest assurance claim

AegisQDA must never print or document `anonymization guaranteed` merely because
Presidio returned no findings. Free-text de-identification cannot be proven
complete by one detector. The defensible guarantee is procedural and technical:
the application prevents downstream processing unless every configured detector,
structural invariant, provenance check and human sign-off has succeeded.

## Out of scope for MVP

- cloud PII services, Azure endpoints or any remote inference;
- PDF/DOCX/image ingestion;
- reversible or cross-project identity mappings;
- unattended batch release;
- processing real research material before synthetic evaluation thresholds and
  the internal DPO procedure are complete.
