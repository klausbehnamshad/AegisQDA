# Übergabe PR2–PR4

Lokaler Stand: PR1-Verträge liegen im Arbeitsbaum; ein Merge-Status ist hier
nicht belegt. Teile der PR3/PR4-Härtung sind in
[Optimierungswelle 1](GENERAL_REVIEW_WAVE1.md) umgesetzt. Das Modul `aegisqda.governance` liefert die
Verträge; die Freigabepfade sind unverändert. Realdaten bleiben hart
gesperrt. Dieser Text sagt, wo PR2/3/4 andocken, welche APIs schon
verfügbar sind und welche fehlen.

## Was PR1 fertig geliefert hat

* `docs/GOVERNANCE_CONTRACT.md` v0.1.0 mit Rollen, Vier-Augen-Regel,
  Trust-Store-Kette, Claim-Bindung, DigQDA-Grenze.
* `docs/CLAIM_TYPES.md` mit den maschinenlesbaren Freigabeklassen.
* `src/aegisqda/governance.py`:
  * `Role`, `RoleAssignment` (mit `is_active_at`)
  * `ClaimType` inkl. Stärkeordnung, `weakest_claim`
  * `RunState` und `ALLOWED_TRANSITIONS`, `assert_transition`
  * `ModelManifest`, `PolicyManifest` mit deterministischem `fingerprint()`
  * `ClaimEnvelope` und `CLAIM_ENVELOPE_SCHEMA = "aegisqda-privacy-release-v2"`
  * `SignerContext`, `enforce_four_eyes`
* `config.py`: neuer optionaler `governance`-Abschnitt (backward-kompatibel,
  strengste sichere Defaults, Trust Store noch nicht konsumiert).
* `governance/roles.example.yaml` und `governance/model-manifest.example.yaml`
  als Skelette; keine echten Fingerprints, nichts Reales.
* 33 neue Tests, alle grün. Bestehende 69-Test-Suite unberührt.

Der bestehende Pfad `workflow.transform_run` → `privacy_gate.validate_release`
und Schema `aegisqda-privacy-release-v1` bleiben unverändert. PR2 stellt
die neue Envelope daneben, nicht darunter.

## PR2 — Trusted Two-Person Release

Ziel: Trust Store, Rollenprüfung, zwei Signaturen (Reviewer + Release
Approver), Vier-Augen-Guard, AP9 als Einzeltests, Rollback-Schutz.

Andockpunkte:

* Neues Modul `src/aegisqda/trust_store.py` mit:
  * `TrustStore` Dataclass, Felder aus `governance/roles.example.yaml`
  * `load_trust_store(path: Path) -> TrustStore` mit Signaturverifikation
    des Trust Stores (Register-Owner-Schlüssel), `previous_sha256`-Kette,
    Rollback-Ablehnung.
  * `resolve_role(store, key_fingerprint, timestamp) -> Role | None` — nur
    ACTIVE-Grants innerhalb der Validitätsfenster.
* Erweiterung `review_signature.verify_review_signature`:
  neue Signatur `verify_and_authorize(review, trust_store, timestamp) -> Role`
  — prüft Selbstkonsistenz PLUS Trust-Store-Zugehörigkeit. Die bestehende
  Funktion bleibt (Rückwärtskompatibilität für die synthetische Bahn) und
  wird per Deprecation-Kommentar markiert.
* Neues Artefakt `release-approval.json` (Schema
  `aegisqda-release-approval-v1`):
  * bindet `review_sha256`, `detection_sha256`, `ledger_sha256`,
    `transformed_sha256`, `second_pass_sha256`, `policy_manifest_sha256`,
    `model_manifest_sha256`;
  * signiert vom Release-Approver-Schlüssel;
  * `key_id_sha256` und `role` (aus Trust Store aufgelöst).
* Neuer Workflow-Schritt `approve_release(run_dir)` zwischen
  `transform_run` und `validate_release`. Erst wenn eine gültige
  `release-approval.json` vorliegt, darf die neue v2-Envelope entstehen.
* Guard-Punkt: **einziger** Aufruf von `governance.enforce_four_eyes`
  sitzt in `approve_release`; verboten überall sonst.

AP9 als Einzeltests (nicht Sammeltest):

    tests/test_trust_store_signature_missing.py
    tests/test_trust_store_signature_expired.py
    tests/test_trust_store_signature_cryptographically_invalid.py
    tests/test_trust_store_key_not_trusted.py
    tests/test_trust_store_key_revoked.py
    tests/test_trust_store_same_key_both_roles.py
    tests/test_trust_store_serial_rollback_rejected.py

Zeitstempel: gehören in den signierten Payload. Assurance-Feld
`LOCAL_SYSTEM_TIME` bleibt ehrlich; monotone Ereignisnummer und
Trust-Store-Seriennummer werden zusätzlich gebunden.

## PR3 — Finding Semantics

Ziel: echte Generalisierung, Overlap-Gruppen mit einzeln signierten
Suppressionen, Mischclaim-Logik, `KEEP_AND_REVIEW` gebunden an
retained-risk-Rationale.

Andockpunkte:

* Neuer PolicyAction-Wert `KEEP_AND_REVIEW` (in `config.PolicyAction`) und
  neuer entitätspezifischer Generalisierer:
  * `AGE` → deterministische Altersbanden (bevorzugte Bandbreite: 10-Jahre,
    dokumentiert in `docs/GENERALIZATION_RULES.md`).
  * `DATE_TIME` → Jahr, Monat oder relative Zeit, Regel im selben Doc.
  * `KINSHIP` → grobe Kategorie `[FAMILY_RELATION]`.
  * `JOB_TITLE` → kontrollierte Oberkategorie (Liste in policy YAML).
  * `SMALL_PLACE`, `RARE_EVENT` bleiben `BLOCK_AND_REVIEW`.
* Overlap-Gruppen: Detection-Ledger bekommt neues Feld
  `overlap_group_id`. Suppression-Vorschläge werden im Review-Artefakt
  einzeln signiert:
  ```yaml
  suppressions:
    - suppressed_finding_id: F-0042
      surviving_finding_id: F-0041
      source_sha256: ...
      ledger_sha256: ...
      policy_hash: ...
      reason_code: EXACT_TYPE_MATCH_ENCLOSED
      signed_at: 2026-08-11T09:00:00Z
      signature: ...
  ```
  Batch-Signatur ist verboten; ein Test in `tests/test_suppression_binding.py`
  fixiert das.
* Mischclaim: `governance.weakest_claim` wird in
  `workflow._build_claim_envelope` aufgerufen (der neuen Funktion in PR2).
  Ein Run mit mindestens einem `KEEP_AND_REVIEW`-Finding trägt im
  Envelope-Header `PROCESS_RELEASED_WITH_RETAINED_RISK`.
* `ClaimEnvelope.validate` fordert bereits die
  `retained_risk_rationale_sha256`-Bindung; PR3 liefert die Rationale-
  Datei-Struktur (`docs/RETAINED_RISK_RATIONALE.md`).

## PR4 — Operational Assurance

Ziel: Modell-Manifest wirklich gebunden, Fixture-Manifest gebunden,
Code-Switching-Suite, Revocation Registry, Downstream Notice, externer
Verifier.

Andockpunkte:

* `src/aegisqda/model_manifest.py`:
  * `compute_model_manifest(language) -> ModelManifest` — liest den
    tatsächlich geladenen spaCy-Modellbaum, berechnet die vier Sub-Hashes
    stabil und gleicht gegen `governance/model-manifest.<lang>.yaml` ab.
    Bei Abweichung: `IntegrityError`, Run geht auf `BLOCKED`.
  * `detection.detector_versions()` erweitert um `model_manifest_sha256`.
* DigQDA-Allowlist von "Tag erlaubt" auf "exaktes Paar `(Tag, Digest)`":
  `digqda_adapter._resolve_digest` prüft heute den Digest, aber die
  Allowlist `models.dpo_approved_local_allowlist` enthält nur Tags. Neuer
  Schema-Eintrag `models.dpo_approved_local_pairs: [{tag: gemma3:4b, digest: sha256:...}]`.
* Fixture-Manifest-Bindung: `synthetic_only` NICHT mehr aus CLI-Flag
  ableiten. `workflow.scan_source` schlägt für Quellen ohne Eintrag in
  `tests/fixtures/expected.json` fehl, es sei denn die neue
  `authorization.registered_synthetic_manifest_sha256` erlaubt sie.
* Code-Switching-Suite unter `tests/fixtures/interviews/childlux/`
  mit expliziten Gate-Regeln (Miss eines gesetzten direkten Identifikators
  blockiert die Suite; Null Recall in einer Entity-/Sprach-Kategorie
  blockiert unabhängig von der Fallzahl).
* Revocation Registry als append-only JSON-Lines-Datei
  `RESCINDED_RELEASES.jsonl` außerhalb des Repos. `validate_release`
  prüft die Registry ZUERST; ein widerrufener Release liefert
  `DownstreamBlocked("release was rescinded")` mit dem passenden Ereignis.
* Externer Verifier `scripts/verify_release_bundle.py`:
  * darf `ollama`, `presidio`, `aegisqda` NICHT importieren
  * prüft kanonisches JSON, Hash-Kette, Signaturen (nur `cryptography`),
    Trust Store, Rollen, Policy-/Modell-Bindung, Claim-Konsistenz,
    Revocation.
  * eigene minimale Test-Suite `tests/test_external_verifier.py`.

## Verifikationsplan pro PR

* PR2: 69 + 33 + 7 AP9 + neue Approval-Tests. Ruff, mypy grün. Kein
  Regress in synthetischer Akzeptanz.
* PR3: dazu Overlap- und Generalisierungstests; annotierte
  Interview-Suite 9/9 bleibt bestehen; neue Suppression-Signatur-Tests.
* PR4: Modell-Manifest-Regression pro Sprachpaket, Code-Switching-Suite
  bestanden, Verifier-Round-Trip auf einem export-Bundle. Realdatensperre
  weiterhin hart.

## Was auf keinen Fall passieren darf

* `PROCESS_RELEASED_*` ohne beide Signaturen (Reviewer + Approver).
* Änderung an einer bestehenden Freigabe. Widerruf ist ein NEUES Ereignis.
* Aufweichung der Realdatensperre ohne dokumentierte, per Trust Store
  freigegebene lokale Infrastructure Attestation.
* Silent Fallback in Modell-Bindung, Fixture-Bindung, DigQDA-Digest.
* DigQDA-`PASS` → `PROCESS_RELEASED_*`. Bleibt
  `DOWNSTREAM_REVIEW_REQUIRED`.
