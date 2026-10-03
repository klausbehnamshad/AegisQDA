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
pinned vendor/digqda pilot -------------- local Ollama only; think=false bound
        |
        v
post-output identifier scan ------------- methodological review still required
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
- A mention that crosses a line break (for example a name wrapped inside a
  two-line SRT cue) is reviewed as one mention and replaced by one surrogate on
  its first line. The surrogate is keyed by the whole mention, so `Maria` +
  `Gonzalez` on two lines and `Maria Gonzalez` on one line share it. The rest of
  the mention is removed from the following line; when that would leave the
  line empty, it becomes the continuation mark `[…]` so the structure holds.
- DigQDA quote validation binds against the transformed source, never silently
  against the protected original.

## Provenance

The privacy release envelope must bind hashes for the protected input, released
source, policy, Presidio version, NLP models, recognizers, language, thresholds,
review decision and pinned DigQDA snapshot. It must contain no clear-text PII.

## Implemented artifact state machine

```text
scan -> REVIEW_REQUIRED -> accepted review -> transform
     -> second-pass PASS + structure PASS -> PRIVACY_RELEASED
     -> exact model/digest + upstream revalidation -> DOWNSTREAM_REVIEW_REQUIRED
```

Artifacts use canonical JSON and SHA-256 integrity fields. Reviews may also use
an external Ed25519 key; the current self-contained public key proves possession
but becomes an identity proof only after its fingerprint is bound to the later
infrastructure trust store. There is no reversible identity map: the exact
value-to-surrogate dictionary exists only during `transform` and is cleared
before the release envelope is written.

The consumer-owned adapter injects a narrowly scoped, hash-bound Python
runtime shim which sets Ollama `think=false`. This leaves the pinned DigQDA
snapshot untouched and prevents reasoning-capable Gemma models from exhausting
the JSON output budget in a separate thinking channel. The setting and shim
hash are recorded in successful adapter manifests and blocked-attempt
envelopes.
