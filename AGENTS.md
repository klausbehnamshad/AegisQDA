# AegisQDA workspace rules

- Work only inside this repository.
- Never modify sibling DigQDA or any DINOH path.
- Treat `vendor/digqda/` as read-only pinned upstream.
- No cloud services, remote APIs, telemetry or remote inference.
- Runtime model access is loopback-only Ollama with an explicit allowlist.
- Use synthetic fixtures only until all privacy gates and human-review workflow
  are implemented and the user explicitly authorizes a governed real-data pilot.
- Fail closed on uncertainty; never claim universal anonymity.
- Never commit sources, mappings, review artifacts, runs, secrets or outputs.

