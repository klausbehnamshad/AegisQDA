# QDA Reliability Layer v0.1 (DRAFT)

```text
DOC_ID: QDA-CORE-RELIABILITY-LAYER
VERSION: 0.1
STATUS: DRAFT
SCOPE: infrastruktur, methodenunabhängig
GILT_FÜR: alle analytischen Schubladen (10_GENERIC … 60_CROSS_CASE)
ZIELMODELLE: gemma4:e4b, mistral:7b, qwen3:8b (lokal via Ollama)
LEITSATZ: Das Modell schlägt vor. Der Code verifiziert. Ein atomarer Task pro Call.
```

Dieses Dokument beschreibt keine Methode. Es beschreibt die technische Schicht,
die dafür sorgt, dass die methodischen Prompts der Bibliothek auf kleinen lokalen
Modellen **zuverlässig, prüfbar und reproduzierbar** laufen. Der Reliability Layer
ist orthogonal zur `ALLOWED_METHOD_CLAIM`-Logik: er ändert keine Methodenclaims,
er sichert nur ihre technische Durchführung.

## 0. Warum überhaupt

Der bestehende `QDA-GEN-CONTROLLED-CODING` v1.1 ist epistemisch vollständig,
aber er verlangt von *einem* Modellaufruf: 13 Non-negotiables + 5 Analyseschritte
+ eine 10-Spalten-Tabelle + 10 Output-Sektionen. Ein 4B–8B-Modell hält das nicht
zuverlässig: es droppt hintere Regeln, zerlegt breite Tabellen, paraphrasiert
Zitate und springt ins Abstrakte. Der Prompt läuft gegen den Strich des Modells.

Die Antwort ist nicht, den Prompt zu verwässern, sondern die Arbeit so zu
**zerlegen**, dass jeder Call klein genug ist, um korrekt zu bleiben — und die
Ansprüche, die ein Prompt technisch nicht garantieren kann (Zitattreue,
Timecodes, Zählungen), an **externen Code** abzugeben.

## 1. Pass-Pipeline (map–reduce statt Monolith)

Ein Lauf wird in atomare Pässe zerlegt. Jeder Pass ist ein eigener Modellaufruf
(oder Code) mit minimalem Kontext. Das ist die konsequente Fortsetzung des
README-Prinzips „ein Task pro Lauf" um eine Ebene nach unten.

```text
P0  SEGMENTIERUNG        (Code, nicht Modell — qda_segment.py)
      SRT      → Cue-Fenster (Pausen-Gap + Zeichenbudget) + Timecodes exakt
      TXT      → Absätze; Locator = Zeilen-/Zeichen-Range
      Output:  source_units[] = {unit_id, source_range, explicit_speaker, source_text}
      (mechanische Verarbeitungseinheiten, KEINE analytischen Segmente)

P1  DESKRIPTIVE KODIERUNG  (Modell, ein Call PRO source_unit — qda_run_p1.py)
      Input:   genau eine Einheit + Settings (RQ, coding_mode, codebook)
      Output:  ein SCHLANKES JSON-Objekt (p1_schema.json); der Orchestrator bindet
               unit_id/source_range/explicit_speaker/quote_locator aus P0 dazu.
      → erfundene Timecodes strukturell unmöglich (Locator kommt aus P0)

P2  CODE-KONSOLIDIERUNG    (Modell ODER Code + menschliche Entscheidung)
      Input:   die Code-Liste aus allen P1-Objekten (nur Labels + Definitionen)
      Output:  Merge-/Dedupe-VORSCHLÄGE — der Mensch entscheidet
      → das Modell sieht hier keine Rohtexte mehr, nur Codes

P3  L2-INTERPRETATION       (Modell, optional, nur wenn ENABLED)
      Input:   konsolidierte Codes + zugehörige (verifizierte) Belege
      Output:  interpretive_candidates[] nach eigenem Schema
      → strikt getrennter, späterer Lauf

V   VALIDIERUNG             (Code, siehe 90_UTILITIES/qda_validate.py)
      läuft nach P1 (und P3), bevor irgendetwas gerendert wird

R   RENDERING               (Code, qda_render.py — geplant)
      JSON aller Pässe → der bestehende 10-Sektionen-Report aus v1.1
      → dein Report-Format bleibt, das Modell muss es nicht mehr bauen
```

Mapping auf die Schubladen: `10_GENERIC` nutzt P0→P1(→P2→P3). `20_MAYRING`
deduktiv ist P1 im `STRICT_CODEBOOK`-Modus. `20_MAYRING` induktiv ist
P1(`OPEN_DESCRIPTIVE`)→P2, wobei die 10–50%-Revisionsschleife **außerhalb** des
Modells orchestriert wird — das Modell macht nur den Schritt in der Schleife,
nie die Schleife.

## 2. JSON statt breiter Tabelle

Kernproblem gelöst: kleine Modelle erzeugen breite Markdown-Tabellen unzuverlässig.
Lösung: das Modell füllt ein **erzwungenes JSON-Schema** (Ollama `format`), Code
rendert daraus die Tabelle. Die Felder entsprechen 1:1 den Spalten aus v1.1 §2,
es geht also keine methodische Information verloren.

P1-Schema — das Modell erzeugt NUR den schlanken Kern (`10_GENERIC/p1_schema.json`).
`unit_id`, `source_range`, `explicit_speaker`, `quote_locator` bindet der
Orchestrator aus P0 nachträglich; `level2` gehört nach P3, nicht hierher.

```json
{
  "concise_description": "…",
  "narrative_function": "EVALUATION",
  "coding_decision": "CODES_ASSIGNED",
  "descriptive_codes": [
    {
      "code_label": "…",
      "definition": "…",
      "status": "INDUCTIVE_CANDIDATE",
      "source_quote": "… zeichengetreu kopiert …"
    }
  ],
  "uncertainty": []
}
```

Regeln bleiben im Prompt, aber **kürzer und positiv** formuliert (kleine Modelle
folgen Positiv-Imperativen besser als langen Negationslisten): „Kodiere nur, was
wörtlich im Segment steht" statt „Kodiere keine latente Bedeutung". Eine kurze
Hard-No-Liste bleibt; das Wichtigste steht **vorn und hinten** (Primacy/Recency).
Genau **ein** deutsches Mini-Beispiel (2 Zeilen → korrektes JSON) im Prompt ist
bei 4B vermutlich der größte Einzel-Qualitätssprung und verhindert Code-Switching.

## 3. RECOMMENDED_RUNTIME (neuer Header-Block)

Jeder Prompt bekommt zusätzlich zu seinem Steckbrief einen Runtime-Block. Zwei
Einträge fressen sonst still Daten:

```text
RECOMMENDED_RUNTIME:
  temperature: 0.0        # quellennahes Coding braucht keine Kreativität
  top_p: 0.9
  num_ctx: 8192           # !! WICHTIG: Ollama-Default ist modellabhängig oft nur
                          #    2048/4096 → längere Segmente/Interviews werden
                          #    STILL abgeschnitten. Für eine evidenzgebundene
                          #    Methode ist das ein unsichtbarer Datenverlust.
  seed: 42                # verbessert Wiederholbarkeit (mit temp 0), garantiert
                          #    sie aber NICHT bitgenau
  format: <p1_schema.json ALS OBJEKT>  # nicht als Dateipfad an die API
  repeat_penalty: 1.0
```

`num_ctx` ist der gefährlichste Default, weil der Fehler unsichtbar ist: das
Modell antwortet plausibel auf die *sichtbare* Hälfte des Segments. Der Runtime-
Block macht die Setzung zur Pflicht, nicht zur Option.

## 4. Run-Manifest (Reproduzierbarkeit / Zitierfähigkeit)

Jeder Lauf schreibt ein Manifest mit. Das macht Analysen reproduzierbar und in
einer Methodenteil-Fußnote zitierfähig — passend zu deinem Anspruch.

```text
run_manifest:
  run_id
  prompt_id / version / prompt_sha256 / schema_sha256 / grammar_sha256 / contract_sha256
  model_name + digest + quantisierung   (z.B. gemma4:e4b)
  runtime: temperature, top_p, num_ctx, seed
  source_sha256                         (Hash der Originalquelle)
  unit_input_sha256                     (kanonisches vollständiges Unit-Objekt)
  rendered_prompt_sha256                (effektiver Prompt je Unit)
  research_question_sha256 + codebook_sha256
  timestamp
  validator_version + validator_result  (siehe §5)
  allowed_method_claim                  (übernommen aus dem Steckbrief)
```

Der letzte Punkt schließt den Kreis zu deiner Governance: das Manifest trägt den
erlaubten Methodenclaim mit, und der Renderer (§6) weigert sich, einen
Methodennamen zu drucken, der nicht im Manifest steht.

## 5. Validator (Code, nicht Prosa) — schließt den UNVERIFIED-Loop

`90_UTILITIES/qda_validate.py`. Das ist der Baustein, der aus `MODEL_UNVERIFIED`
legitim `VERIFIED` macht. Er nimmt genau die Schwäche kleiner Modelle —
Zitate paraphrasieren, Timecodes erfinden — aus der Vertrauenskette.

Was er prüft:

- jedes `source_quote` gegen die Originalquelle: EXACT / FUZZY(score) / NOT_FOUND
  (Whitespace/Zeilenumbruch-tolerant, aber wort- und zeichengetreu; rapidfuzz)
- jeden Timecode/Locator gegen das SRT: existiert die Cue-Zeit? (sonst N/A bei
  Nicht-SRT-Material)
- augmentiert das JSON pro Item mit `quote_match` und `locator_match`
- gibt Kennzahlen aus: Exact-Rate, Fuzzy-Rate, Not-Found-Liste, Coverage

Was er ausdrücklich **nicht** kann und nicht behauptet: entscheiden, ob ein Code
*richtig* ist, ob eine Interpretation trägt, ob Segmentierung sinnvoll ist. Er
prüft mechanische Treue, nicht analytische Güte. `VALIDATION` steht damit
zu Recht im Namen — es findet ein externer Vergleich mit der Quelle statt.

## 6. Renderer (geplant, qda_render.py)

Nimmt die validierten JSON-Objekte und baut daraus deinen bestehenden
10-Sektionen-Report aus v1.1. Vorteil: das Report-Format überlebt unverändert,
aber das Modell muss es nicht mehr formatieren. Verifizierte Zitate bekommen im
Report ein anderes Label als unverifizierte („source_quote_verified" vs.
„source_quote_unverified"), was v1.1 als Prompt nie leisten konnte.

## 7. Entscheidungen

1. **Materialtyp** — ENTSCHIEDEN: SRT + TXT. P0 ist damit rein Code (kein
   Modell-Fallback nötig); Locatoren sind in beiden Formaten prüfbar.
2. **JSON-first vs. Markdown** — ENTSCHIEDEN: JSON-first (Modell → JSON →
   Validator → Renderer). Erst das ermöglicht Zitatprüfung und
   verifiziert/unverifiziert-Labels.
3. **Pro-Modell-Profile** — OFFEN: klärt am ehrlichsten die Eval-Harness
   (empfohlenes Modell je Operation vs. modellagnostisch + nur Runtime-Varianten).
```

## Stand

Fertig und getestet (`90_UTILITIES/tests/run_tests.py`, 107 Checks; Stand v0.4):
- `qda_segment.py` (P0, SRT+TXT), `qda_validate.py` (V, SRT+TXT),
  `qda_run_p1.py` (Runner mit Budget-Check), `p1_schema.json` (strenger Vertrag),
  `p1_prompt.txt` (einzige kanonische Runtime-Promptquelle) und
  `QDA-GEN-DESCRIPTIVE-CODING_SEGMENT_v1.1.md` (Methodenspezifikation).

Der Einstieg `./digqda pilot` verbindet diese Kanten in frischen,
zugriffsbeschränkten Laufordnern und bewertet ein vollständiges Provenance-Gate.

Nächste Bausteine:
- `qda_render.py` (JSON → 10-Sektionen-Report, verifiziert/unverifiziert-Labels)
- `20_MAYRING` deduktiv als erster echter Spezialprompt (P1 / STRICT_CODEBOOK)
- Eval-Harness (u.a. Instruktionssprache DE vs. EN, Pro-Modell-Profile)
