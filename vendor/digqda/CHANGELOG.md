# Changelog

All notable changes will be documented here.

## Unreleased — DigQDA extraction

- corrected the intended local target and all runtime defaults from the
  mistakenly used `gemma3:4b` comparison to the installed `gemma4:e4b`; the
  Gemma 4 digest-bound verification passed the complete OPEN/STRICT smoke and
  all 10/10 semantic canary cases; `./digqda` now automatically re-executes with
  the repository `.venv` when present, so the documented command works without
  prior environment activation;
- added a synthetic semantic canary with role-map scope filtering and explicit
  contract/evidence/semantic verdicts; its model-free lint, comparator self-test
  and dry-run plumbing path are now CI checks; per-stage outputs are cleared
  before execution so a failed subprocess cannot be mistaken for a stale result;
- hardened runtime prompt v1.2 after an accidental `gemma3:4b` comparison exposed forced
  STRICT codebook hits, coding of technical chatter and false-confident boundary
  handling; definitions now outrank lexical overlap, technical/organizational
  chatter maps to `NOTHING_CODABLE`, and plausible codebook boundaries require
  `CODEBOOK_AMBIGUOUS` plus documented uncertainty; mode examples now also show
  legal no-code decisions instead of teaching that every unit needs a code;
- coupled `coding_decision` and `descriptive_codes` cardinality in the
  Ollama-facing mode grammar with explicit `oneOf` branches, while retaining
  independent full Draft 2020-12 validation after every model response;
- promoted role-map scope filtering into `./digqda pilot`: scoped SRT runs use
  cue units, preserve a protected full P0 envelope, send only explicitly
  included roles to P1 and fail closed on unmapped/mixed speakers; the runner
  manifest and pilot gate bind the canonical scope hash;
- extended the semantic comparator's negation check to nominal absence forms
  such as `fehlend`, avoiding a false failure when negation is paraphrased but
  semantically preserved; word-boundary matching prevents substring false
  positives such as `weiterempfehlen`;
- replaced the canary's permissive scope copy with the same shared fail-closed
  implementation used by the production pilot and made its `scope_sha256`
  binding part of every scoped canary contract result;
- added a hard STRICT positive canary requiring `CODES_ASSIGNED` plus
  `CODEBOOK_APPLIED`, complementing the no-fit and lexical-trap refusals;
- bound the runner's reserved output budget to Ollama `num_predict` (default
  2048) and recorded it in runtime provenance, preventing unbounded local model
  generation on longer source units;
- established DigQDA as an independent upstream method-contract toolkit;
- added Integration Contract v0.1 and lightweight method governance;
- separated the public software artifact from consumer data-governance duties;
- added quiet validator output for governed adapters;
- retained the hardened QDA prototype as the initial reference implementation.
- closed adversarial trust-boundary gaps for foreign payloads, missing evidence,
  malformed SRT input and valid multi-cue spans;
- made the versioned P0 object envelope mandatory and fail-closed against its
  required JSON Schema, including basic cross-field consistency checks;
- moved the complete P1 prompt template and both mode examples into one
  canonical, fully hashed prompt bundle with no embedded fallback.
- completed run provenance with unique run IDs, canonical unit-input and
  rendered-prompt hashes, research-question/codebook hashes, deterministic
  codebook rendering and mandatory model-digest binding for real runs;
- added opt-in, path-confined raw-response quarantine artifacts with hashed
  filenames and integrity references; the repository-local `quarantine/`
  directory is ignored to prevent accidental staging of sensitive outputs;
- added a fail-closed synthetic smoke harness spanning P0 SRT/TXT, real P1 OPEN
  and STRICT calls, external validation, diagnostic quarantine and aggregate
  exit semantics without stale-output reuse;
- made repo-wide Ruff linting and the model-free end-to-end smoke path CI gates,
  and removed the legacy lint violations;
- specialized the Ollama output grammar by coding mode, including an exact
  STRICT code-label enum derived from the bound codebook, and recorded the
  effective `grammar_sha256` in run provenance;
- recorded model-specific synthetic OPEN+STRICT compatibility runs for local
  `gemma4:e4b` and the earlier `gemma3:4b` comparison via Ollama.
- added the single `./digqda` workflow entry point with environment doctor,
  opaque source labels, fresh owner-only run directories and a complete
  fail-closed pilot gate; pilot quarantine is now explicitly opt-in;
- added end-to-end regressions for repeat-run isolation, permissions, source
  pseudonymization, hard repo-path guards and provenance tampering.
