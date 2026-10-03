# PR1 Delta — Governance Contracts

Kein Bruch am bestehenden Freigabepfad. Der neue Vertrag existiert
parallel und wird von PR2 durchgeschaltet.

## Neu

    docs/GOVERNANCE_CONTRACT.md
    docs/CLAIM_TYPES.md
    docs/HANDOVER_PR2_PR4.md
    docs/PR1_DELTA.md
    governance/roles.example.yaml
    governance/model-manifest.example.yaml
    src/aegisqda/governance.py
    tests/test_governance.py

## Geändert

    src/aegisqda/config.py          — optionaler governance-Abschnitt (default_factory)
    config/aegisqda.local.yaml      — governance-Block mit strengsten Defaults

## Unverändert (bewusst)

    src/aegisqda/workflow.py
    src/aegisqda/privacy_gate.py
    src/aegisqda/review_signature.py
    src/aegisqda/detection.py
    src/aegisqda/digqda_adapter.py
    policies/strict.yaml
    Realdaten-Schalter authorization.real_data_enabled: false

## Verifikation

    33/33 neue Governance-Tests grün
    Ruff auf allen neuen und geänderten Dateien clean (bis auf
        vorbestehende Stil-Warnungen in config.py, die auch vor PR1 bestanden)
    Config-Schema backward-kompatibel (alte YAML ohne governance-Block
        lädt weiterhin mit sicheren Defaults)

Nicht ausgeführt in dieser Session:
    Vollständige 69-Test-Suite (benötigt presidio-analyzer und spaCy-
    Modelle, die im Cloud-Container nicht installiert sind). Da PR1 keine
    Zeilen im bestehenden Pfad ändert, wurde ein Regress damals nicht
    nachgewiesen oder ausgeschlossen. Zur Belastbarkeit sollte lokal
        pytest -q
    einmal grün laufen, bevor PR1 gemerged wird.

Aktualisierung 2026-10-03: Die ursprünglichen 102 Tests einschließlich Governance
bestanden vor Beginn der Erweiterung. Aktuelle Verifikation und Grenzen stehen
in [GENERAL_REVIEW_WAVE1.md](GENERAL_REVIEW_WAVE1.md). Die oben beschriebene
unveränderte PR1-Schnittstelle ist ein historischer Delta-Stand.

## API-Oberfläche (was PR2/3/4 nutzen werden)

    aegisqda.governance:
      Role, RoleAssignment
      ClaimType, weakest_claim, defined_claim_types, releasable_claim_types
      RunState, ALLOWED_TRANSITIONS, assert_transition
      ModelManifest, PolicyManifest
      ClaimEnvelope, CLAIM_ENVELOPE_SCHEMA
      SignerContext, enforce_four_eyes
      FOUR_EYES_INCOMPATIBLE_WITH_APPROVER

    aegisqda.config.GovernanceConfig:
      contract_version, trust_store_path,
      allow_retained_risk_claim, two_person_release_required

## Bewusste Grenzen dieses PRs

* Kein Trust Store auf Disk. Vertrag definiert, Persistenz und Signatur
  liegen in PR2.
* Kein Vier-Augen-Wiring in `workflow.transform_run`. Der Guard existiert
  und ist getestet, wird aber erst in PR2 aufgerufen.
* Kein Modell-Hash-Vergleich in `detection.py`. Datenklasse existiert,
  Berechnung liegt in PR4.
* Kein neuer Schema-v2-Emitter im Freigabepfad. Der Envelope-Typ ist
  definiert und getestet, wird aber erst in PR2 durch die neue
  `approve_release`-Funktion geschrieben.
