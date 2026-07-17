# Architecture

```text
protected local source
        |
        v
P-2 format + language preflight --------- BLOCK on uncertainty
        |
        v
P-1 Presidio + custom recognizers ------- detection ledger (protected)
        |
        v
P-0 human detection review -------------- signed release decision
        |
        v
T-1 in-memory typed surrogate transform - mapping destroyed after document
        |
        v
V-1 second-pass PII scan ---------------- BLOCK on unresolved finding
        |
        v
V-2 SRT/TXT structural equivalence ------ BLOCK on cue/line drift
        |
        v
privacy release envelope
        |
        v
pinned vendor/digqda pilot -------------- local Ollama only
```

## Trust boundaries

1. Original and detection ledger stay in an external owner-only run directory.
2. The repository contains only synthetic fixtures.
3. The transient original-to-surrogate map is memory-only in strict mode.
4. DigQDA receives only the released transformed source and an opaque case ID.
5. DigQDA outputs remain sensitive and are scanned again before external use.

## Locator preservation

- SRT cue numbers and time ranges must remain byte-equivalent.
- TXT newline count and unit boundaries must remain stable.
- Replacements may change character length but may not create or remove lines.
- DigQDA quote validation binds against the transformed source, never silently
  against the protected original.

## Provenance

The privacy release envelope must bind hashes for the protected input, released
source, policy, Presidio version, NLP models, recognizers, language, thresholds,
review decision and pinned DigQDA snapshot. It must contain no clear-text PII.

