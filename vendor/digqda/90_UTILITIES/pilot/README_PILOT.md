# DigQDA — flüssiger Pilotworkflow

Der Pilot hat genau einen sichtbaren Einstieg. Die methodische Arbeit bleibt im
Vordergrund; Pfadschutz, neue Laufordner, Provenance und technische Gates laufen
automatisch im Hintergrund.

## 1. Einmal vorbereiten

Aus dem Repo-Wurzelverzeichnis:

```bash
python3 -m pip install -r requirements.txt
./digqda doctor
```

`doctor` prüft Contract-Dateien, Python-Abhängigkeiten, Ollama und den exakten
lokalen Modell-Tag. Es verändert keine Forschungsdaten.

## 2. Mechanik ohne Modell prüfen

Dieser Aufruf verwendet ausschließlich die gebündelte synthetische Fixture:

```bash
./digqda pilot CASE-DEMO 90_UTILITIES/smoke/fixtures/interview_demo.srt \
  --dry-run --synthetic --out-root /tmp/DigQDA-Demo
```

`Plumbing bereit` ist hier Erfolg: Der Runner erzeugt absichtlich keine Codes,
und der Validator weist dieses Nicht-Ergebnis erwartungsgemäß ab. Der Test
beweist den Datenfluss, nicht die Modellqualität.

## 3. Einen echten Pilot starten

```bash
./digqda pilot CASE-001 /sicherer/pfad/interview.srt
```

Defaults: `OPEN_DESCRIPTIVE`, `gemma4:e4b`, Laufwurzel `~/DigQDA-Pilot`.
Für den ersten Pilot ist OPEN ohne Codebuch empfohlen; die Codes bleiben
Vorschläge bis zur methodischen Prüfung.

Bei Interviews wird der analysierte Sprecher-Scope explizit über eine lokale
fallbezogene Rollenmap gesetzt, zum Beispiel `roles.json`:

```json
{"I": "interviewer", "B": "interviewee"}
```

```bash
./digqda pilot CASE-001 /sicherer/pfad/interview.srt \
  --role-map /sicherer/pfad/roles.json --include-role interviewee
```

Mit aktivem Scope segmentiert SRT cue-weise, weist jedes Sprecherlabel über die
Map zu und bricht bei fehlenden/gemischten Labels ab. `segments_full.json` hält
den geschützten P0-Kontext; nur die gefilterten `segments.json` gehen an P1.

Die methodisch relevanten Varianten sind direkt am selben Einstieg verfügbar:

```bash
./digqda pilot CASE-001 /sicherer/pfad/interview.srt \
  --mode strict --codebook /sicherer/pfad/codebook.json \
  --research-question "Welche Erfahrungen werden beschrieben?"
```

Wichtige Optionen:

| Option | Zweck |
|---|---|
| `--mode` | `open`, `strict` oder `constrained` |
| `--codebook` | erforderlich für STRICT/CONSTRAINED; in OPEN nicht zulässig |
| `--research-question` | Forschungsfrage; im Manifest nur als Hash gebunden |
| `--model` | exakter lokaler Ollama-Tag |
| `--role-map` / `--include-role` | fallbezogener Sprecher-Scope vor P1 |
| `--out-root` | geschützte Laufwurzel außerhalb des Git-Repos |
| `--diagnostic-quarantine` | ungültige Rohantworten nur für gezielte Diagnose sichern |

## 4. Was automatisch geschieht

Jeder Aufruf erhält einen neuen, nicht überschreibbaren Laufordner:

```text
~/DigQDA-Pilot/CASE-001/20260716T…Z/
  segments.json
  segments_full.json        # nur bei aktivem Rollen-Scope
  coding.json
  validation.json
  validation.md
  run.log
  REVIEW.md
```

- Quelle und Output in Repo- oder Cloud-Sync-Pfaden werden hart abgewiesen.
- Der echte Dateiname wird an P0 und Validator durch `CASE-001.srt` ersetzt.
- Ordner sind `0700`, Dateien `0600`; alte Artefakte können keinen Lauf maskieren.
- Quarantäne ist standardmäßig aus und pro Lauf isoliert.
- Das Gate prüft Unit-, Quellen-, Prompt-, Schema-, Contract-, Codebuch- und
  Modellbindung sowie Runner- und Validatorstatus.
- `run.log` enthält nur technische Metadaten, keine Zitate oder Quellpfade.

Die Laufwurzel außerhalb des Repos ist **keine zweite Softwarekopie**. DigQDA
bleibt ausschließlich in diesem Repository; dort liegen nur geschützte
Laufdaten, die grundsätzlich nicht in Git gehören.

## 5. Ergebnis ohne Stolpersteine lesen

- `Technisch bestanden`: Die vollständige maschinelle Kette ist grün. Danach
  `REVIEW.md` öffnen und Codes sowie alle gebundenen Zitate methodisch prüfen.
- `Pilot gesperrt`: Kein Teilergebnis weiterverwenden. Der Befehl nennt den
  lokalen Diagnosebericht und liefert einen Fehler-Exit.

Technisches PASS ersetzt nicht die analytische Entscheidung. Die einzige
bewusst sichtbare Schranke ist deshalb die methodische Freigabe in `REVIEW.md`.
Der Hintergrund dazu steht in `docs/DATA_PROTECTION_RUNBOOK.md`; er muss nicht
bei jedem Lauf erneut durchgearbeitet werden.

Bei gemeinsamer technischer Fehlersuche an echten Daten nur Kennzahlen aus
`run.log` teilen, keine Zitate, Quelltexte oder Output-JSONs. Für Detaildiagnosen
synthetische Minimalbeispiele verwenden.
