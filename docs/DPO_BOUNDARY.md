# DPO-approved operating boundary to encode

The user states that the approved setting remains completely local. The exact
AegisQDA runtime allowlist is `gemma3:4b` plus the independently verified
`gemma4:e4b`; `gemma3:4b` is the default. `gemma4:12b` was rejected by the
structured-output smoke and is not an allowed runtime model. AegisQDA must
encode, not reinterpret, the authoritative internal DPO record.

Hard technical assumptions for the MVP:

- no cloud;
- no remote API;
- no source or derived text leaves the host;
- Ollama endpoint must resolve to loopback;
- exact model tags and digests are recorded;
- the configured model must be in the explicit local allowlist;
- additions to the allowlist require the internal governance record first;
- sources, mappings and outputs stay outside Git and cloud-sync directories.

This file is an engineering boundary, not legal advice and not a replacement for
the internal approval record.
