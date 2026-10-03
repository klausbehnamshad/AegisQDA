# Lokaler DH-Research-Workbench

Der Workbench benötigt einen gültig freigegebenen synthetischen Run. Vor jeder
Aktion wird die Privacy-Freigabe mit Transformation und zweitem Scan geprüft.
Er ruft keine Modelle auf und übernimmt keine Modellcodes automatisch.

```bash
AEGIS=.venv/bin/aegisqda
# RUN ist ein geschütztes vorhandenes Laufverzeichnis außerhalb Git.
$AEGIS qda-init "$RUN" --analyst ANALYST-001 --method CODEBOOK
$AEGIS qda-codebook "$RUN" --analyst ANALYST-001 --code-id CODE-LEARNING-V1
# Label und Definition werden lokal interaktiv abgefragt.
$AEGIS qda-codebook "$RUN" --analyst ANALYST-001 --code-id CODE-COLLECTIVE-V1 \
  --parent-id CODE-LEARNING-V1
$AEGIS qda-code "$RUN" --analyst ANALYST-001 --code-id CODE-COLLECTIVE-V1 \
  --start 40 --end 64
# Zeichenpositionen im transformierten Text; Ende exklusiv.
# Span muss vollständig in einer Contentzeile liegen; SRT-Header sind verboten.
# Menschliche Begründung wird interaktiv abgefragt.
$AEGIS qda-memo "$RUN" --analyst ANALYST-001 --start 40 --end 64 \
  --code-id CODE-COLLECTIVE-V1
$AEGIS qda-summary "$RUN"
```

Weitere Methoden: REFLEXIVE_THEMATIC und GROUNDED_THEORY. Die Methodendeklaration
ist nach dem ersten Ereignis festgelegt. Eine neue Code-Definition benötigt eine
neue ID; Elterncodes müssen vorher existieren. Codings und Memos binden ihre
exakte transformierte Evidenz über Hash und Span.

Die Summary zählt unterschiedliche `(Code, Start, Ende)`-Belege. Mehrere
Analysten auf demselben Span verdoppeln Häufigkeiten nicht; ihre einzelnen
Entscheidungen bleiben erhalten. Ko-Okkurrenz zählt überlappende Spanpaare
verschiedener Codes; angrenzende Spans überlappen nicht. Diese Zählungen sind
keine Validitäts-, Kausalitäts- oder Intercoder-Reliabilitätsaussage.

Dateien: `RUN/research/event-NNNNNN.json`, owner-only, durch die Anwendung ohne
Überschreiben angehängt. Definitionen, Begründungen und Memos sind geschützter
Freitext und können neue Identifikatoren enthalten. Sie haben keine externe
Privacy-Freigabe. Die Summary enthält deshalb nur IDs und Zählungen.

UNKEYED_SYNTHETIC_RESEARCH_ONLY bedeutet: keine trusted Analystensignatur, keine
externe Zeitquelle, kein externer Log-Head. Vollständiges Umschreiben oder Entfernen
eines Event-Tails durch den Dateieigentümer ist nicht zuverlässig erkennbar.
Status bleibt METHODOLOGICAL_REVIEW_REQUIRED.

## Retrieval, Dissens und Mehrfallvergleich

```bash
$AEGIS qda-segments "$RUN"
$AEGIS qda-search "$RUN"
# Query interaktiv; Ergebnisse nennen Segment-IDs/Positionen/Hashes ohne Zitate.
$AEGIS qda-evidence "$RUN" --segment-id SEG-...
# Explizite geschützte Textansicht; IDs aus qda-segments übernehmen.
$AEGIS qda-dissent "$RUN"

WORKSPACE=/private/tmp/aegisqda-workspace-demo
$AEGIS qda-workspace-init "$WORKSPACE"
$AEGIS qda-workspace-add "$WORKSPACE" "$RUN" --case-id CASE-001
$AEGIS qda-workspace-add "$WORKSPACE" "$RUN_2" --case-id CASE-002
$AEGIS qda-matrix "$WORKSPACE"
$AEGIS verify "$RUN"
```

Segmente sind konkrete Contentzeilen, keine automatisch festgelegten analytischen
Einheiten. Segment-IDs binden Freigabe, Quelle und exakte Position. Suche ist
wörtlich und case-insensitive; sie ruft keine Modelle auf. Die Evidenzanzeige
escaped Terminal-Steuerzeichen und begrenzt sehr lange Anzeigen auf 8000 Zeichen.

Dissens vergleicht unterschiedliche Codesets von mindestens zwei ausdrücklich
codierenden Analysten auf exakt demselben Span und Evidenzhash. Fehlende Codings,
anders gezogene Segmentgrenzen oder angrenzende Spans werden nicht als Dissens
gezählt. Keine automatische Reliabilitätsaussage.

Workspace-Registrierungen sind owner-only, außerhalb Git, unveränderlich durch
die Anwendung und an die konkrete Privacy-Freigabe sowie den bisherigen
Research-Event-Prefix gebunden. Neue legitime Codings/Memos sind möglich; alte
Prefixänderungen, Rebinding und Truncation blockieren. Eine gemeinsame Code-ID
benötigt dieselben Labels, Definitionen und Elterncodes. Unterschiedliche
Methodendeklarationen verhindern einen ungekennzeichneten Vergleich.

Die Matrix prüft jeden Fall neu und liefert IDs/Zählungen. Sie ist kein atomarer
Snapshot sämtlicher gleichzeitig bearbeiteter Fälle. Ungekeyte Siegel und ein
lokaler Log-Head verhindern kein vollständiges Umschreiben durch den Eigentümer.

`verify` prüft synthetische Privacy-, Research- und Downstream-Bindungen samt
vorhandener Signaturen ausschließlich lesend und offline. SYNTHETIC_VERIFIED
bedeutet keine externe, institutionelle oder reale Datenfreigabe. Noch blockierte
oder unvollständige Analysen bleiben BLOCKED; reine freigegebene Privacy-Runs
können mit ausdrücklich fehlenden späteren Phasen geprüft werden.

Vor dem Quellenreview kann `review-plan RUN` tatsächliche Overlap-Gruppen zeigen.
Die Planung hebt keine Policy-Sperre auf. `detector-inventory --language en`
fingerprintet installierte Tokenizer-/Modellassets und aktuelle Kontrolldateien;
UNQUALIFIED_LOCAL_INVENTORY enthält keine Recall-Qualifikation oder Modellfreigabe.

## Blockierte Modellvorschläge prüfen

`analyze` prüft auch alle erzeugten Texte. Bekannte Maschinenfelder werden nur
an ihren exakten Schema-Pfaden und bei gültiger Provenienz ausgenommen. Ein
Treffer in freier Prosa bleibt blockierend; er bekommt keine globale Token-Ausnahme.

Bei `POST_SCAN_FINDINGS` nennt die CLI eine opake Attempt-ID. Im geschützten
Terminal kann jeder konkrete Treffer als Fehlalarm begründet oder die Prüfung
abgebrochen werden:

```bash
$AEGIS review-output "$RUN" --attempt-id "$ATTEMPT" --reviewer REVIEWER-001 \
  --signing-key /secure/local/path/reviewer.pem
$AEGIS finalize-output-review "$RUN" --attempt-id "$ATTEMPT"
```

Eine Signatur ist hier erforderlich. SELF_SIGNED_LOCAL bestätigt nur lokale
Schlüsselkontrolle; konfigurierte Reviewer-Fingerprints werden durchgesetzt.
Die Prüfung bindet exakte Ausgabedateien, Privacy-Freigabe, Modell-Digest,
Detektoren und Laufzeitkontrollen. Die Finalisierung prüft diese Bindungen und
alle Treffer erneut. Identifizierende oder unsichere Ausgabe darf nicht behalten
werden: abbrechen und einen neuen Modelllauf erzeugen. Die ursprüngliche
BLOCKED-Historie bleibt erhalten; der Ergebnisstatus ist weiterhin
DOWNSTREAM_REVIEW_REQUIRED. Keine automatische Übernahme in das Codebook und
keine externe Veröffentlichung.
