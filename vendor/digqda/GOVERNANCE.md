# DigQDA Governance

DigQDA uses lightweight **method governance**, not data governance. It governs
contracts, prompts, schemas, validators, claims and releases. A consuming system
governs research data and authorized execution.

## Maintainer decisions

Maintainers approve:

- allowed method claims and forbidden overclaims;
- contract and schema changes;
- prompt examples and codebook-mode semantics;
- conformance fixtures and supported model/backend declarations;
- releases, deprecations and security fixes.

## Change classes

- **Patch:** implementation or wording correction without contract change.
- **Minor:** backward-compatible feature, prompt or schema addition.
- **Major:** incompatible contract, schema, acceptance or methods-claim change.

Contract, schema, prompt and package versions remain separately visible in run
manifests. Package SemVer must not conceal a breaking contract change.

## Required review

Every change to a prompt, schema, mode rule or validator requires:

1. a stated methodological reason;
2. a regression test that would fail before the change;
3. conformance-suite success;
4. review of allowed and forbidden method claims;
5. a changelog entry when user-visible behavior changes.

## Release gates

No public release may claim FAIR4RS conformance, model agnosticism, complete
method implementation or compliance exemption without separate evidence. Each
release must satisfy `docs/RELEASE_CHECKLIST.md`.
