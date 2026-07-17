# DigQDA — Smoke-Test-Kit

Dieses Kit prüft die lokale DigQDA-Kette mit ausschließlich synthetischen Daten:

```text
P0 SRT + P0 TXT → P1 OPEN + P1 STRICT → externe Validierung → Gesamtstatus
```

P0 verarbeitet beide mitgelieferten fiktiven Interviews. Die echten Modellläufe
verwenden anschließend das zeitcodierte SRT, damit neben der Zitattreue auch die
Locator- und Mehr-Cue-SPAN-Prüfung durchlaufen wird. Ungültige Modellantworten
werden bei diesem synthetischen Test kontrolliert in `out/quarantine/` abgelegt.

> Das Kit darf nicht durch den Austausch der Fixtures für echte Transkripte
> zweckentfremdet werden. Der Pilot mit Forschungsdaten beginnt erst nach dem
> Datenschutz-Betriebs-Runbook.

## 1. Vorbedingungen

Aus dem Repo-Wurzelverzeichnis:

```bash
python3 -m pip install -r requirements.txt
```

Für den echten Modellpfad muss Ollama laufen und das gewünschte Modell lokal
installiert sein:

```bash
ollama serve  # nur falls die Ollama-App nicht bereits läuft
ollama list
```

`ollama serve` bleibt im Vordergrund und wird deshalb gegebenenfalls in einem
eigenen Terminal gestartet.

## 2. Ausführen

Der modellfreie Plumbing-Test prüft die gesamte Orchestrierung. Dabei sind
`DRY_RUN_OK` im Runner und `INVALID_INPUT` im Validator die erwartete Kombination,
weil ein Dry-Run absichtlich keine Kodierungen erzeugt:

```bash
DRY=1 bash 90_UTILITIES/smoke/run_smoke.sh
```

Der echte synthetische Lauf verwendet den exakten Modell-Tag aus `ollama list`:

```bash
MODEL=gemma4:e4b bash 90_UTILITIES/smoke/run_smoke.sh
```

Mit `OUT=/privater/pfad` kann ein separater Artefaktordner gesetzt werden, etwa
damit ein `DRY=1`-Lauf den letzten echten Modellnachweis nicht überschreibt.

Falls der installierte Tag anders lautet, wird ausschließlich der Wert hinter
`MODEL=` ersetzt. Der Preflight lehnt einen unbekannten Tag vor dem ersten
Modellaufruf ab.

## 3. Verlässliche Exit-Semantik

Das Skript führt OPEN und STRICT auch dann beide aus, wenn eines der Szenarien
einen Modellbefund erzeugt. Erst danach wird ein Gesamtstatus ausgegeben:

| Exit | Gesamtstatus | Bedeutung |
|---:|---|---|
| `0` | `SMOKE_RESULT=PASS` | Beide Szenarien erfüllen die jeweilige Erwartung. |
| `1` | `SMOKE_RESULT=REVIEW_REQUIRED` | Mindestens ein echter Modelllauf oder Validator verlangt Prüfung. |
| `10–14` | Preflight-Abbruch | Abhängigkeit, Ollama-Server oder Modell-Tag fehlt. |
| `20–21` | P0-Abbruch | Eine synthetische Fixture segmentiert nicht deterministisch. |

Ein Shell-Exit 0 kann damit keinen intern fehlgeschlagenen Runner oder Validator
mehr verdecken.

## 4. Frische und nachvollziehbare Artefakte

Vor jedem Lauf entfernt das Skript ausschließlich seine bekannten synthetischen
Artefakte. Dadurch können alte Dateien keinen abgebrochenen neuen Lauf maskieren.
Der ignorierte Ordner `90_UTILITIES/smoke/out/` enthält anschließend:

| Datei | Inhalt |
|---|---|
| `SMOKE_SUMMARY.txt` | Exit-Codes, Manifeststatus und Gesamturteil |
| `segments_srt.json` | P0-SRT: vier Units, einschließlich Mehr-Cue-SPAN S02 |
| `segments_txt.json` | P0-TXT: fünf deterministische Units |
| `p1_open.json`, `p1_strict.json` | Modellgebundene P1-Ergebnisse und Provenance |
| `validation_*.json`, `validation_*.md` | Maschinen- und menschenlesbare Validierung |
| `quarantine/` | Nur bei ungültigen echten Modellantworten; synthetischer Inhalt |

Das SRT ist absichtlich PASS-fähig: S01 und S04 sind Interviewerfragen, S02 und
S03 enthalten kodierbare Aussagen. S02 umfasst mehrere SRT-Cues und prüft damit
die SPAN-Locator-Logik.

## 5. Ergebnis interpretieren

Der Idealfall ist in beiden echten Szenarien:

```text
runner exit 0 + validator exit 0 + verdict PASS
```

`REVIEW_REQUIRED` ist kein stiller Fehler. Es bedeutet beispielsweise, dass ein
Zitat nur fuzzy passt, nicht gefunden wurde, aus der falschen Unit stammt oder
ein Locator ungültig ist. Details stehen in `validation_open.md` und
`validation_strict.md`. `SCHEMA_INVALID`, `MODE_VIOLATION`, `NOT_JSON`,
`SKIPPED_OVER_BUDGET` oder `ERROR` stehen unitweise im jeweiligen P1-Manifest;
die zugehörige synthetische Rohantwort liegt, sofern vorhanden, in der
Quarantäne.

Für die gemeinsame Auswertung in Codex genügen:

- `out/SMOKE_SUMMARY.txt`
- `out/p1_open.json` und `out/validation_open.md`
- `out/p1_strict.json` und `out/validation_strict.md`
- bei Befunden zusätzlich `out/quarantine/`

## 6. Aufräumen

`out/` ist lokal per `.gitignore` ausgeschlossen und kann jederzeit vollständig
gelöscht werden. Es gehört nicht zum versionierten Smoke-Kit.
