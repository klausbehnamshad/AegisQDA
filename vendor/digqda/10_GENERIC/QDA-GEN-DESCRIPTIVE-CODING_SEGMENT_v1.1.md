# QDA-GEN-DESCRIPTIVE-CODING (SOURCE UNIT) v1.1 — DRAFT

> Runtime-Hinweis: Die einzige kanonische Ausfuehrungsquelle ist
> `10_GENERIC/p1_prompt.txt`, aktuell Prompt-Version 1.2. Der Copy-paste-Block in
> diesem v1.1-Methodendokument bleibt historische Spezifikation und darf nicht
> als Runtime-Fallback verwendet werden.

```text
PROMPT_ID: QDA-GEN-DESCRIPTIVE-CODING
VERSION: 1.1
STATUS: DRAFT
METHOD_FAMILY: GENERIC_QDA
METHOD_VARIANT: SOURCE_NEAR_CONTROLLED_CODING
ANALYTIC_OPERATION: DESCRIPTIVE_CODING_SINGLE_SOURCE_UNIT   (P1)
INTERNAL_LEVEL: L1
OPTIONAL_SECONDARY_ANALYSIS: NONE   (L2 ist ein getrennter Pass, P3)
MATERIAL_SCOPE: ONE_SOURCE_UNIT_PER_CALL
ORIGINAL_SOURCE_REQUIRED: YES
CODEBOOK_REQUIRED: DEPENDS_ON_SELECTED_CODING_MODE
PROJECT_STATE_REQUIRED: NO
ALLOWED_METHOD_CLAIM: GENERIC_SOURCE_NEAR_CONTROLLED_QDA_CODING
ALLOWED_OUTPUTS: ONE_JSON_OBJECT_PER_UNIT (nach p1_schema.json)
FORBIDDEN_OUTPUTS: MAYRING_CLAIM, REFLEXIVE_TA_CLAIM, GROUNDED_THEORY_CLAIM,
VERIFIED_QUOTE_CLAIM, INTERVIEW_LEVEL_CLAIM, THEMES, LATENT_INTERPRETATION
HUMAN_DECISIONS_REQUIRED: CODE_ACCEPTANCE, CODE_MERGING, SOURCE_VERIFICATION
TECHNICAL_VALIDATION: REQUIRED (extern via 90_UTILITIES/qda_validate.py)
SUPERSEDES: v1.0-DRAFT (nie pilotiert) — Outputvertrag geändert
```

```text
CHANGELOG ggü. v1.0-DRAFT
- Hauptregel korrigiert: nur source_quote ist zeichengetreu; code_label/definition
  dürfen knapp paraphrasieren, aber nichts hinzufügen.
- Worked Example korrigiert (kein "Bildungsmaßnahme" für "Töpferkurs").
- Schlanker Modelloutput: unit_id, source_range, explicit_speaker, quote_locator
  und level2 werden NICHT mehr vom Modell erzeugt — der Orchestrator bindet sie.
- Neues Feld coding_decision; kein Pseudo-Code "kein Codebuch-Code passt" mehr.
- Strenges Schema (p1_schema.json): additionalProperties:false, Enums, Längen.
- TECHNICAL_VALIDATION: NONE -> REQUIRED.
- P0-Einheit heißt source_unit, nicht "Segment".
```

```text
RECOMMENDED_RUNTIME:
  temperature: 0.0
  top_p: 0.9
  num_ctx: 8192          # setzt das Budget; verhindert Abschneidung NICHT von
                         #   allein. qda_run_p1.py prüft Prompt+Unit VOR dem Call
                         #   gegen num_ctx und überspringt/warnt bei Überschreitung.
  seed: 42               # verbessert die Wiederholbarkeit, GARANTIERT sie nicht
                         #   (kein Modell/Backend ist bitgenau deterministisch).
  format: <p1_schema.json ALS OBJEKT>   # nicht als Dateipfad an die API geben
```

## Outputvertrag (Modell erzeugt NUR das)

Genau ein JSON-Objekt nach `10_GENERIC/p1_schema.json`:

```json
{
  "concise_description": "...",
  "narrative_function": "EVALUATION",
  "coding_decision": "CODES_ASSIGNED",
  "descriptive_codes": [
    {"code_label": "...", "definition": "...",
     "status": "INDUCTIVE_CANDIDATE", "source_quote": "... zeichengetreu ..."}
  ],
  "uncertainty": []
}
```

Was das Modell **nicht** mehr ausgibt (der Orchestrator bindet es aus P0 ans
Ergebnis): `unit_id`, `source_range`, `explicit_speaker`, `quote_locator`. Damit
sind erfundene Timecodes strukturell ausgeschlossen — der Locator kommt aus P0,
nicht aus dem Modell.

Konsistenzregel (prüft der Runner, nicht das Schema):
`CODES_ASSIGNED` ⇒ `descriptive_codes` nicht leer; `NO_CODE_FITS` /
`NOTHING_CODABLE` ⇒ `descriptive_codes` leer.

## Copy-paste prompt

```text
Du bist eine sorgfältige qualitative Forscherin. Kodiere GENAU EINE Quelleinheit
(source unit) quellennah auf Ebene 1 (Beschreibung). Nutze nur den Text der Einheit.

WICHTIGSTE REGEL (gilt vor allen anderen):
Kodiere ausschließlich manifest belegte Sachverhalte. Nur die source_quote muss
zeichengetreu kopiert werden. code_label und definition dürfen knapp
paraphrasieren, aber KEINE zusätzliche Information und KEINE latente Bedeutung
einführen. Was nicht dasteht, wird nicht ergänzt.

EINSTELLUNGEN
- Forschungsfrage: [EINFÜGEN oder: explorative Analyse]
- Coding-Modus: [GENAU EINEN WÄHLEN]
    STRICT_CODEBOOK       — nur Codes aus dem Codebuch; keine neuen.
    CONSTRAINED_EXTENSION — erst Codebuch prüfen; nur wenn kein Code passt, EINEN
                            neuen INDUCTIVE_CANDIDATE bilden.
    OPEN_DESCRIPTIVE      — kein Codebuch; quellennahe INDUCTIVE_CANDIDATE bilden.
- Codebuch: [EINFÜGEN oder: keins]   (nur die relevanten Codes, nicht seitenweise)
- Ausgabesprache: Deutsch (Zitate immer in Originalsprache belassen)

REGELN
1. Bleib am manifesten Inhalt: benenne, was beschrieben, getan, erlebt,
   berichtet, verglichen, bewertet oder erinnert wird.
2. Führe nichts Verstecktes ein: keine latente Bedeutung, keine Psyche, keine
   Identität/Resilienz/Trauma/Macht — außer der Text benennt es ausdrücklich.
3. Ein code_label paraphrasiert knapp; es darf keinen Ort, keine Kategorie und
   keinen Begriff einführen, der nicht im Text steht. (Beispiel: aus "Töpferkurs"
   wird NICHT "Bildungsmaßnahme".)
4. Kopiere pro Code eine kurze source_quote ZEICHENGETREU aus der Einheit.
5. Ton, Pause, Ironie, Emotion, Prosodie NICHT erschließen — ein Transkript ist
   nicht das Audio-Ereignis.
6. Lieber KEIN Code als ein vager, abstrakter oder doppelter. Jeder Code braucht
   einen konkreten Textbeleg in dieser Einheit.
7. Nur diese Einheit. Keine Aussage über das ganze Interview.
8. coding_decision setzen:
     CODES_ASSIGNED   — mindestens ein Code vergeben.
     NO_CODE_FITS     — nur STRICT_CODEBOOK: relevanter Inhalt, aber kein
                        Codebuch-Code passt -> descriptive_codes: [].
     NOTHING_CODABLE  — kein analytisch relevanter manifester Inhalt (Gruß,
                        Technik-Geplauder) -> descriptive_codes: [].
9. uncertainty ist eine Liste kurzer Punkte; wenn nichts unklar ist: [].

MODUS-DETAILS
- STRICT_CODEBOOK: passt ein Codebuch-Code klar -> status "CODEBOOK_APPLIED".
  Ist die GRENZE eines echten Codebuch-Codes unklar (er könnte passen) ->
  status "CODEBOOK_AMBIGUOUS". Passt gar kein Codebuch-Code -> KEIN Code,
  descriptive_codes [], coding_decision "NO_CODE_FITS". Erfinde nie einen Code.
- CONSTRAINED_EXTENSION / OPEN_DESCRIPTIVE: neue Codes -> status
  "INDUCTIVE_CANDIDATE" (ein Vorschlag, kein kanonischer Code).

AUSGABE
Gib AUSSCHLIESSLICH ein einziges JSON-Objekt nach dem Schema zurück. Kein Text
davor/danach, kein Markdown. Erzeuge NICHT die Felder unit_id, source_range,
explicit_speaker oder quote_locator — die bindet der Orchestrator.

BEISPIEL (Eingabe → korrekte Ausgabe)
Quelleinheit:
  unit_id: S03
  text: "Meine Vasen sind am Ende richtig schön geworden, das hat mich sehr gefreut."
Ausgabe:
{
  "concise_description": "Die eigenen Vasen sind am Ende gelungen; eine Freude wird ausdrücklich benannt.",
  "narrative_function": "EVALUATION",
  "coding_decision": "CODES_ASSIGNED",
  "descriptive_codes": [
    {"code_label": "gelungene Vasen",
     "definition": "die eigenen Vasen werden als am Ende gelungen beschrieben",
     "status": "INDUCTIVE_CANDIDATE",
     "source_quote": "Meine Vasen sind am Ende richtig schön geworden"},
    {"code_label": "benannte Freude",
     "definition": "eine Freude wird ausdrücklich benannt",
     "status": "INDUCTIVE_CANDIDATE",
     "source_quote": "das hat mich sehr gefreut"}
  ],
  "uncertainty": []
}

ZUR ERINNERUNG: nur die source_quote zeichengetreu, nichts Neues einführen, genau
ein JSON-Objekt nach Schema.

QUELLEINHEIT
unit_id: [AUS P0]
text:
[SOURCE-UNIT-TEXT AUS qda_segment.py EINFÜGEN]
```

## Aufruf

Nicht `ollama run --format <datei>` (ein Dateipfad ist nicht das Schema-Objekt).
Belastbar über den Runner `90_UTILITIES/qda_run_p1.py`, der das Schema als Objekt
lädt, `ollama.chat(format=schema, options={...})` aufruft, die Antwort per
`jsonschema` re-validiert (wie die Ollama-Doku empfiehlt), das Kontextbudget vorab
prüft und die P0-Felder ans Ergebnis bindet. Danach: `qda_validate.py`, dann
(geplant) `qda_render.py`.

## Nutzungshinweise

- Erstlauf: `OPEN_DESCRIPTIVE`, Codebuch "keins". Alle Codes bleiben
  `INDUCTIVE_CANDIDATE`, bis du sie prüfst.
- Codebuch klein halten (nur relevante Codes je Lauf) — ein kompletter
  Codebuchtext frisst das Kontextbudget und den atomaren Vorteil auf. Der Runner
  erzwingt einen Größen-Cap.
- Instruktionssprache DE vs. EN ist ein offener Parameter für die Eval-Harness.
- Zitattreue garantiert der Prompt NICHT technisch — das tut `qda_validate.py`.
