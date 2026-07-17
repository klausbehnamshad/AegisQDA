# DPO-approved operating boundary to encode

The user states that the approved setting remains completely local and that
local `gemma4:12b` is to be integrated alongside the already approved local
setting. AegisQDA must encode, not reinterpret, the authoritative internal DPO
record.

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

