# Governance-Vertrag AegisQDA

Version: v0.1.0 (PR1). Dieses Dokument ist der versionierte
Entscheidungsvertrag, an den sich Code, Betrieb und Freigabepraxis binden.
Änderungen erfolgen ausschließlich durch signierten Nachfolger; frühere
Versionen bleiben Teil der Kette (`previous_sha256`).

Der Vertrag definiert Rollen, Freigabearten (Claim-Typen), die
Zustandsmaschine einer Run-Envelope, die Bindung von Policy- und
Modell-Manifesten sowie die Vier-Augen-Regel. Der Vertrag setzt keine
Realdaten frei. Realdaten bleiben in dieser MVP-Phase hart gesperrt.

## 1. Rollen

Rollen sind Trennungsregeln, keine Personen. Eine Person kann mehrere
Rollen über die Zeit halten, aber auf demselben Run zum selben Signier-
Zeitpunkt nur eine. Rollen werden im Trust Store (PR2) an Schlüssel-Finger-
prints gebunden, nicht an Namen.

| Rolle | Kürzel | Aufgabe |
|---|---|---|
| Register Owner | REGISTER_OWNER | Verantwortet den signierten Trust Store, seine Rotation, die Kette `previous_sha256`. Keine Runs, keine Reviews, keine Freigaben. |
| DPO | DPO | Datenschutzbeauftragte:r. Verantwortet Policy-Manifest, Retained-Risk-Regeln, Aufbewahrung, Widerruf. Kann Reviewer sein, kann nicht selbst denselben Run freigeben. |
| PI | PI | Wissenschaftliche Projektleitung. Entscheidet über Scope, dokumentiert Zweckbindung, kann Reviewer sein, kann nicht selbst denselben Run freigeben. |
| Reviewer | REVIEWER | Führt die interaktive Detection-Review durch, signiert das Review-Artefakt. |
| Release Approver | RELEASE_APPROVER | Prüft das Review und die Envelope, signiert die Freigabe. Muss verschieden sein von Reviewer (Vier-Augen). |

### Stellvertretung und Offboarding

Für jede Rolle wird im Trust Store mindestens eine aktive Stellvertretung
geführt. Beim Offboarding wird der bisherige Schlüssel mit
`status=REVOKED` in die nächste Trust-Store-Version geschrieben; frühere
Freigaben unter dem widerrufenen Schlüssel bleiben gültig, sofern ihr
Signaturzeitpunkt vor dem Widerruf liegt und ihr Trust-Store-Seriennummer-
Feld auf die damals aktive Version zeigt. Neue Freigaben unter dem
widerrufenen Schlüssel schlagen fehl.

### REVIEW_UNAVAILABLE

Ist die Rolle REVIEWER oder RELEASE_APPROVER zum Zeitpunkt eines Runs im
Trust Store nicht besetzt (kein aktiver Schlüssel), tritt der Zustand
`REVIEW_UNAVAILABLE` ein. Es gibt keine Ausnahmefreigabe, kein
Notfallschlüssel, keine schwächere Signatur. Der Run pausiert bis eine
neue Trust-Store-Version die fehlende Rolle besetzt.

## 2. Freigabearten (Claim-Typen)

Freigabetexte sind maschinenlesbar. Der freie Text bleibt bestehen, ist
aber nicht mehr die Autoritätsquelle. Autoritativ sind ausschließlich die
drei folgenden Werte:

| Wert | Bedeutung |
|---|---|
| `PROCESS_RELEASED_REPLACED` | Alle bestätigten Identifikatoren wurden ersetzt oder wirklich generalisiert. Keine dokumentierte Restrisikoentscheidung notwendig. |
| `PROCESS_RELEASED_WITH_RETAINED_RISK` | Mindestens ein bestätigtes Finding wurde bewusst beibehalten. Erfordert eine separat gebundene Restrisikobegründung. |
| `BLOCKED` | Keine Freigabe. Der Run terminiert. |

Zwei operative Zustände sind zusätzlich definiert:

* `REVIEW_UNAVAILABLE` (siehe oben): Der Run pausiert.
* `DOWNSTREAM_REVIEW_REQUIRED`: Der bestehende Endzustand nach DigQDA-
  PASS. Wird von PR1 nicht verändert; DigQDA-`PASS` bleibt ausschließlich
  technische Downstream-Evidenz und wird nie automatisch zu einer externen
  Freigabe.

### Mischclaim-Regel

Aggregiert ein Manifest mehrere findingbezogene Entscheidungen, gilt im
Manifest-Kopf immer der schwächste enthaltene Claim (siehe
`governance.weakest_claim`). Die Einzelentscheidungen bleiben
findingbezogen und einzeln signiert nachvollziehbar. Ordnung nach Stärke:

    BLOCKED  <  REVIEW_UNAVAILABLE  <  DOWNSTREAM_REVIEW_REQUIRED  <
    PROCESS_RELEASED_WITH_RETAINED_RISK  <  PROCESS_RELEASED_REPLACED

`BLOCKED` und `REVIEW_UNAVAILABLE` sind gleich schwach; die Tie-Break-
Regel bevorzugt `BLOCKED`, damit ein Run, der irgendwo ein BLOCKED-
Finding enthält, dieses Ergebnis nach außen trägt.

## 3. Bindung eines Claims

Jeder Claim wird signiert an mindestens die folgenden Hashes gebunden:

* `source_sha256` — geschützte Originalquelle
* `detection_ledger_sha256` — vollständiger Detection-Ledger
* `review_decisions_sha256` — kanonische Serialisierung aller Review-
  Entscheidungen und Ergänzungen
* `policy_manifest_sha256` — Fingerprint des Policy-Manifests (siehe §4)
* `model_manifest_sha256` — Fingerprint des Modell-Manifests (siehe §4)
* `transformed_artifact_sha256` — freigegebenes transformiertes Artefakt
* `second_pass_sha256` — zweiter Scan-Durchlauf
* `claim_type` — einer der Werte aus §2
* `retained_risk_rationale_sha256` — Pflichtfeld genau für
  `PROCESS_RELEASED_WITH_RETAINED_RISK`; verboten für `PROCESS_RELEASED_REPLACED`

Zeitstempel sind Teil der signierten Nutzdaten. Ohne extern
vertrauenswürdige Zeitquelle weist die Envelope die Assurance
`LOCAL_SYSTEM_TIME` aus. Ein Vertrauens-Zeitstempel ersetzt nicht die
Trust-Store-Kette; er ergänzt sie.

## 4. Policy- und Modell-Manifeste

### Policy-Manifest

Die bestehende Bindung `policy_sha256` (Roh-YAML) bleibt erhalten und wird
ergänzt durch ein separates Policy-Manifest mit `policy_id`, `version`,
kanonisierter `entity_actions`-Karte und der erlaubten Menge an Claim-
Typen. Ein strenger Betriebsmodus verbietet
`PROCESS_RELEASED_WITH_RETAINED_RISK` per Policy; ein Interview-Modus
erlaubt sie. Der Fingerprint des Policy-Manifests wird an den Claim
gebunden.

### Modell-Manifest

Für jedes Sprachpaket wird ein signiertes Modell-Manifest geführt mit:

    language
    package_name
    package_version
    model_tree_sha256      (stabile Serialisierung des Modellverzeichnisses)
    meta_json_sha256
    tokenizer_config_sha256
    recognizer_pack_sha256
    threshold
    qualification_suite_sha256

Der Detektor liest zur Laufzeit den Fingerprint des tatsächlich geladenen
Modells und vergleicht ihn hart gegen das per Trust Store freigegebene
Manifest. Bei Abweichung: BLOCK, Claim `BLOCKED`. Ein Manifest ist nur
zusammen mit der Qualification Suite vertrauenswürdig, gegen die es
qualifiziert wurde.

Für den DigQDA-Pfad wird die Allowlist von "Tag erlaubt" auf "exaktes
Paar `(Tag, Digest)` erlaubt" umgestellt (Implementierung PR4).

## 5. Zustandsmaschine der Run-Envelope

Die grobkörnige äußere Zustandsmaschine ist:

    DETECTED
      -> UNDER_REVIEW | REVIEW_UNAVAILABLE | BLOCKED
    UNDER_REVIEW
      -> REVIEWED | BLOCKED | REVIEW_UNAVAILABLE
    REVIEW_UNAVAILABLE
      -> UNDER_REVIEW | BLOCKED
    REVIEWED
      -> PENDING_RELEASE_APPROVAL | BLOCKED
    PENDING_RELEASE_APPROVAL
      -> RELEASED | BLOCKED
    RELEASED
      -> RESCINDED
    BLOCKED
      -> (terminal)
    RESCINDED
      -> (terminal)

Der Übergang `RELEASED -> RESCINDED` wird durch die Revocation Registry
(PR4) ausgelöst. Ein widerrufener Release bleibt als append-only
Ereignis erhalten; kein Feld einer bestehenden Freigabe wird
überschrieben.

## 6. Vier-Augen-Regel

Bei jedem Übergang `PENDING_RELEASE_APPROVAL -> RELEASED` gilt:

* Der Signaturschlüssel des Reviewers und der Signaturschlüssel des
  Approvers dürfen nicht identisch sein.
* Die Rolle des Approvers muss `RELEASE_APPROVER` sein.
* Die Rolle des Reviewers muss `REVIEWER` sein.
* Rolle und Schlüssel-ID sind verschiedene Konzepte und müssen
  auseinandergehalten werden.

Der Guard sitzt an einer Stelle (`governance.enforce_four_eyes`) und ist
keine verstreute Ad-hoc-Prüfung.

## 7. DigQDA-Grenze

DigQDA ist Downstream und läuft ausschließlich lokal gegen die bereits
freigegebene, transformierte Quelle. Ein DigQDA-`PASS` bleibt technische
Downstream-Evidenz und erzeugt niemals automatisch einen Claim vom Typ
`PROCESS_RELEASED_*`. Der Endzustand nach DigQDA bleibt
`DOWNSTREAM_REVIEW_REQUIRED`.

## 8. Was PR1 nicht ändert

* Der bestehende Freigabepfad (`workflow.transform_run` →
  `privacy_gate.validate_release`) und das Schema
  `aegisqda-privacy-release-v1` bleiben unverändert. PR2 wired die neuen
  Verträge durch.
* Realdaten bleiben hart gesperrt (`real_data_enabled: false`).
* Der Trust Store existiert als Vertrag, aber noch nicht als Datei-Format;
  PR2 liefert die persistente Struktur inklusive `previous_sha256`-Kette.

## 9. Änderungen an diesem Dokument

Jede Änderung ist eine neue Version und trägt

    previous_sha256: <sha256 des vorigen Dokuments>

im Kopf-Metablock (Implementierung mit dem Freigabepfad in PR2). Der
Register Owner signiert die neue Version; der DPO gegen zeichnet. Bis PR2
wird dieser Absatz manuell im Git-Log nachvollzogen.
