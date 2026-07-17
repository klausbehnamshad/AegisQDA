# AegisQDA

Local-only, fail-closed privacy gateway for qualitative research material.
AegisQDA will detect and transform identifying information before a pinned
DigQDA snapshot may process a source.

## Non-negotiable boundary

- no cloud services;
- no remote APIs;
- no network model calls;
- Ollama may be contacted only on loopback;
- default analysis target: local `gemma4:12b`;
- German, French, Luxembourgish and English are in scope;
- no source is released to DigQDA until automatic checks **and** human review
  have passed;
- real sources, mappings, review artifacts and run outputs never enter Git.

No detector can mathematically guarantee that free text contains no identifying
information. AegisQDA therefore guarantees a strict process boundary: any
uncertainty, unsupported language, unresolved detection, structural drift or
missing sign-off blocks downstream processing.

## Repository state

This is a new repository with a new history. The inherited method toolkit is a
vendored, pinned snapshot under `vendor/digqda/`; its source commit and snapshot
manifest are recorded in `UPSTREAM.lock.json`. AegisQDA must never modify the
sibling DigQDA or DINOH workspaces.

Start the implementation in a fresh Codex context with
[`docs/MEGAPROMPT_NEXT_WINDOW.md`](docs/MEGAPROMPT_NEXT_WINDOW.md).

