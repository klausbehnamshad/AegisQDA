# DigQDA — Pilot-Checkliste (überwachter Lauf)

*Eine Seite für den Tag des Piloten. Ausführlicher Workflow: `README_PILOT.md`.
Datenschutz-Hintergrund: `docs/DATA_PROTECTION_RUNBOOK.md`.*

## Was dieser Lauf liefert — und was nicht

DigQDA liefert **evidenzgebundene, zitatverankerte Code-Vorschläge** plus eine
`REVIEW.md` zur methodischen Freigabe. Jede Aussage hängt an einer zeichengetreuen
Quellenstelle + Locator und ist maschinell geprüft. Das ist **Interpretations-
*unterstützung*, kein Ersatz** für die Deutung der PI: das Modell schlägt Struktur
vor, die Forscherin interpretiert. Genau darin liegt der Mehrwert gegenüber freier
Modell-Deutung — nachvollziehbar, quellenbelegt, prüfbar statt bloß plausibel.

## Vorbereitung (einmalig)

- [ ] `python3 -m pip install -r requirements.txt`
- [ ] `./digqda doctor` → Contract, Deps, Ollama, exakter Modell-Tag ok
- [ ] Transkript liegt **außerhalb** des Repos und außerhalb von Cloud-Sync (sonst harter Guard-Abbruch)
- [ ] `roles.json` aus den **echten** Sprecherlabels des Transkripts erstellt
      (Vorlage `roles.example.json` an die tatsächlichen Labels anpassen — vorher ins Transkript schauen)

## Mechanik ohne Modell (jederzeit gefahrlos)

```bash
./digqda pilot CASE-DEMO 90_UTILITIES/smoke/fixtures/interview_demo.srt \
  --dry-run --synthetic --out-root /tmp/DigQDA-Demo
```

`Plumbing bereit` = Erfolg (Dry-Run erzeugt bewusst keine Codes; der Validator
weist dieses Nicht-Ergebnis erwartungsgemäß ab).

## Erster echter Pilot (OPEN empfohlen)

```bash
./digqda pilot CASE-001 /sicherer/pfad/CASE-001.srt \
  --role-map /sicherer/pfad/roles.json --include-role interviewee
```

OPEN ohne Codebuch für den ersten Lauf: induktive, quellennahe Vorschläge, alle
`INDUCTIVE_CANDIDATE`. STRICT/CONSTRAINED erst, wenn ein geprüftes Codebuch vorliegt.

## GO — nur weiterverwenden, wenn ALLE zutreffen

- [ ] Kommandostatus `Technisch bestanden`
- [ ] Validator-Verdikt `PASS`
- [ ] ausschließlich Unit-Status `OK` (kein `NOT_JSON`, `SCHEMA_INVALID`, `MODE_VIOLATION`)
- [ ] Modell + Digest stimmen mit der Erwartung überein
- [ ] `scope_sha256` gesetzt und zwischen P0 (`segments_full.json`) und P1-Manifest identisch
- [ ] in `REVIEW.md`: **jedes** Zitat manuell gegen die Quelle geprüft (zeichengetreu, richtige Unit)

## STOP — sofort abbrechen, kein Teilergebnis verwenden

- [ ] `Pilot gesperrt` / Fehler-Exit
- [ ] `NOT_JSON` bei einer Unit → **nicht** reflexartig `num_predict` erhöhen; zuerst die
      betroffene Unit ansehen und Units verkleinern
- [ ] unbekanntes oder gemischtes Sprecherlabel (Scope bricht ab) → `roles.json` korrigieren
- [ ] Scope-Hash P0 ≠ P1
- [ ] fehlende Evidenz, nicht zeichengetreues Zitat, oder latente Deutung (Trauma/Motiv/Psyche) im Output

## Nach dem Lauf

- [ ] `REVIEW.md` ist die einzige bewusste Schranke — erst nach methodischer Freigabe weiterverwenden
- [ ] Technische Fehlersuche mit mir: nur Kennzahlen aus `run.log` teilen — **keine** Zitate,
      Quelltexte oder Output-JSONs. Für Detaildiagnosen synthetische Minimalbeispiele.
