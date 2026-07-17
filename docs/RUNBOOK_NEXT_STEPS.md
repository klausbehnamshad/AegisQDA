# Next-step runbook

Current operational gate: **synthetic-only / real data blocked**.

1. Keep sources and all run artifacts on an encrypted, access-controlled,
   non-cloud-synced local volume outside Git.
2. Run `aegisqda doctor`; optional-language warnings do not block de/fr/en.
3. Use the exact default `gemma3:4b` digest. `gemma4:e4b` may be requested only
   explicitly; never substitute it silently. Do not restore or use rejected
   `gemma4:12b` for DigQDA.
4. Keep Luxembourgish optional and per-run blocked until its wider suite passes.
5. Provision an external Ed25519 review key with `keygen-review`; before real
   data, bind its public-key fingerprint to the infrastructure trust store and
   define key custody, revocation, and audit retention.
6. Fill the internal operational/DPO procedure, including legal authorization,
   roles, storage, retention, deletion, incident response, and output release.
7. Re-run all tests and the four-language report after any recognizer, threshold,
   policy, model, or upstream change.
8. Only then implement consumption of the local signed infrastructure
   attestation. Real-data enablement remains hard-coded false in this MVP.

Even after those steps, a privacy release is a process result for a defined
policy and tested scope, not a mathematical guarantee of anonymity.
