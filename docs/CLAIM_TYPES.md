# Claim-Typen — maschinenlesbare Freigabeklassen

Ergänzung zu `GOVERNANCE_CONTRACT.md` §2. Dieses Dokument beschreibt die
drei positiven Zustände plus die zwei operativen Zustände so, dass eine
Auditorin oder ein externer Verifier ohne Codelektüre entscheiden kann,
was eine gegebene Envelope aussagt.

## Kanonische Werte

    PROCESS_RELEASED_REPLACED
    PROCESS_RELEASED_WITH_RETAINED_RISK
    BLOCKED
    REVIEW_UNAVAILABLE
    DOWNSTREAM_REVIEW_REQUIRED

Werte sind case-sensitive. Eine Envelope mit einem anderen Wert im Feld
`claim_type` gilt als nicht wohlgeformt und wird von der Verifikation
abgelehnt.

## Semantik

### `PROCESS_RELEASED_REPLACED`

Alle bestätigten Findings wurden entweder durch typisierte, sequentielle
Surrogate ersetzt oder durch echte Generalisierung transformiert. Kein
bestätigtes Finding wurde beibehalten. `retained_risk_rationale_sha256`
muss `null` sein; ein gebundener Rationale-Hash wäre ein Widerspruch zur
Aussage des Claims.

Nutzung: Prozessgeprüfte Ausgaben mit ersetzten oder generalisierten bestätigten
Findings. Dieser Claim beweist keine vollständige Erkennung und keine universelle
Anonymität. Im aktuellen synthetischen Workflow wird er noch nicht emittiert.

### `PROCESS_RELEASED_WITH_RETAINED_RISK`

Mindestens ein bestätigtes Finding wurde bewusst nicht ersetzt oder
generalisiert. Die Envelope trägt einen Rationale-Hash, der auf einen
separat gespeicherten, signierten Text zeigt. Der Text enthält:

* die Menge der betroffenen Findings (per finding_id),
* die kategoriale Begründung (etwa Erhalt analytischer Bedeutung von
  Kohortendaten, Erhalt von Berufsbezeichnungen für Berufsstudien),
* das Restrisikoprofil (Wiedererkennungswahrscheinlichkeit in Prognose,
  qualitative Einschätzung, Vergleich zu einem `REPLACED`-Alternativpfad),
* die Rolle, die die Restrisikoentscheidung getroffen hat (regelmäßig
  DPO oder PI), und ihren Schlüsselfingerprint.

Nutzung: Dokumente, für die eine analytisch entkernte Vollersetzung die
Fragestellung entwerten würde. Verwendung nur mit Policy, die diesen
Claim ausdrücklich zulässt.

### `BLOCKED`

Keine Freigabe. Der Run terminiert im äußeren Zustand `BLOCKED`. Die
Envelope trägt die Gründe (unresolved second pass, structural drift,
Trust-Store-Konflikt, Signaturfehler, Ausgabescan positiv, Policy
verbietet gewählten Claim). Ein `BLOCKED`-Ergebnis ist selbst ein
signiertes Artefakt.

### `REVIEW_UNAVAILABLE`

Reviewer oder Release Approver war zum Zeitpunkt nicht besetzt. Der Run
pausiert. Kein Notfallpfad. Wird beim nächsten aktiven Trust Store neu
angestoßen; die Envelope kann in dieser Zeit gültig geprüft werden.

### `DOWNSTREAM_REVIEW_REQUIRED`

Bestehender Endzustand nach erfolgreichem DigQDA-Lauf. Bleibt in PR1
unverändert; keine automatische Aufwertung zu `PROCESS_RELEASED_*`.

## Bindung

Jeder Claim ist an mindestens die Hashes in `GOVERNANCE_CONTRACT.md` §3
gebunden. Fehlt ein Hash oder passt einer davon zur Laufzeit nicht mehr,
schlägt die Verifikation fehl und der äußere Zustand geht auf `BLOCKED`.

## Mischclaim

Aggregiert eine Envelope mehrere findingbezogene Entscheidungen, gilt im
Kopf der schwächste Wert:

    BLOCKED
      < REVIEW_UNAVAILABLE
      < DOWNSTREAM_REVIEW_REQUIRED
      < PROCESS_RELEASED_WITH_RETAINED_RISK
      < PROCESS_RELEASED_REPLACED

Findings behalten ihren Einzelclaim; die Envelope-Aggregation ist keine
Verdeckung, sondern eine Aussage über den Gesamtstatus.

## Übergangsverbote

`BLOCKED` und `RESCINDED` sind terminale Zustände. `RELEASED` darf
ausschließlich in `RESCINDED` übergehen (Widerruf) und in keinen anderen
Zustand. Änderungen an einer freigegebenen Envelope sind nicht möglich;
eine korrigierte Freigabe ist eine neue Envelope, die die alte per
`previous_release_sha256` referenziert (PR4).
