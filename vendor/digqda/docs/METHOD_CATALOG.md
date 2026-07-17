# DigQDA Method Catalog

Eine methodisch getrennte Promptbibliothek für computergestützte qualitative
Datenanalyse. Die Bibliothek ist unabhängig von einer bestimmten Consumer-
Pipeline.

## Leitidee

Es gibt keinen universellen QDA-Superprompt. Jeder Lauf erhält genau einen
primären methodischen Auftrag. Weitere Perspektiven werden als getrennte Läufe
mit eigenen Voraussetzungen und Outputs durchgeführt.

`L1` und `L2` dienen nur als interne Ordnungsbegriffe:

- `L1` bezeichnet quellennahe Beschreibung und Kodierung.
- `L2` bezeichnet einen getrennten interpretativen Arbeitsschritt.

Diese Bezeichnungen sind keine eigenständigen Forschungsmethoden. Sie dürfen
nicht mit Mayring, Thematic Analysis oder Grounded Theory gleichgesetzt werden.

## Methodische Grundentscheidungen

### 1. Generische quellennahe Kodierung

Zweck: auditable Erstbeschreibung und kontrollierte Kodierentscheidungen, ohne
Anspruch auf eine vollständige spezifische Methodologie.

Der vorhandene Prompt gehört hierher. Er ist Mayring-kompatibel, aber noch kein
vollständiges Mayring-Verfahren, solange unter anderem Selektionskriterium,
Abstraktionsniveau, Kodiereinheit, Kontexteinheit, Auswertungseinheit und
Pilot-/Revisionsschleife nicht projektspezifisch definiert sind.

### 2. Qualitative Inhaltsanalyse nach Mayring

Mayring wird als regelgeleitetes, forschungsfragenbezogenes Verfahren geführt.
Kategoriezuweisung ist dabei selbst ein qualitativ-interpretativer Akt; Mayring
ist deshalb nicht einfach mit „oberflächlichem“ oder rein manifestem L1
gleichzusetzen.

Vorgesehene getrennte Verfahren:

- `QDA-MAY-INDUCTIVE-CATEGORY-FORMATION`
- `QDA-MAY-DEDUCTIVE-CATEGORY-ASSIGNMENT`
- `QDA-MAY-CONTROLLED-MIXED-PROCEDURE`
- `QDA-MAY-PILOT-REVISION`

Ein gemischtes Verfahren ist nur zulässig, wenn es vorab als solches definiert
wurde. Es entsteht nicht automatisch dadurch, dass ein Modell gelegentlich neue
Codes erfindet.

### 3. Thematic Analysis

Vor der Promptwahl muss die Variante benannt werden. Insbesondere darf Reflexive
Thematic Analysis nach Braun und Clarke nicht unbemerkt mit Codebook- oder
Coding-Reliability-Ansätzen vermischt werden. Reflexive TA ist rekursiv und
reflexiv; Themen werden als Muster geteilter Bedeutung um eine zentrale
organisierende Idee entwickelt, nicht bloß als Oberbegriffe über einem festen
Codebuch.

Vorgesehene Schubladen:

- `QDA-RTA-THEME-DEVELOPMENT`
- `QDA-RTA-REFLEXIVE-REVIEW`
- `QDA-CODEBOOK-TA` nur nach ausdrücklicher Wahl und eigener Methodendefinition

Die generische Bezeichnung `THEMATIC_L2` wird nicht als Methodenname verwendet.

### 4. Grounded Theory

Grounded Theory wird als Studienworkflow behandelt, nicht als tieferes Coding
eines einzelnen Interviews. Vor Beginn muss eine Variante festgelegt werden,
beispielsweise klassisch/Glaserian, Straussian oder constructivist/Charmaz. Diese
Varianten werden nicht stillschweigend vermischt.

Eine GT-Schublade setzt einen dokumentierten Projektzustand voraus und umfasst
je nach Variante unter anderem fortlaufenden Vergleich, Memoing, fokussierte oder
selektive Kategorienentwicklung, theoretisches Sampling und theoretische
Integration. Ein Modell kann Samplingfragen vorschlagen, aber weder selbst
theoretisch sampeln noch theoretische Sättigung feststellen.

Vorgesehene Arbeitsschritte:

- `QDA-GT-INITIAL-CODING`
- `QDA-GT-CONSTANT-COMPARISON`
- `QDA-GT-FOCUSED-OR-SELECTIVE-CODING`
- `QDA-GT-CATEGORY-RELATIONS`
- `QDA-GT-THEORETICAL-SAMPLING-MEMO`
- `QDA-GT-THEORETICAL-INTEGRATION`

Aus einzelnen Schritten darf nur `GT-inspired` oder der konkrete Arbeitsschritt
berichtet werden, nicht die Durchführung einer Grounded-Theory-Studie.

### 5. Oral History

Oral History bleibt eine eigenständige analytische Perspektive. Sie untersucht
nicht nur, was berichtet wird, sondern wie Vergangenheit retrospektiv geordnet,
bewertet und als gegenwärtige Erzählung hervorgebracht wird.

Vorgesehene Schubladen:

- `QDA-OH-NARRATIVE-STRUCTURE`
- `QDA-OH-MEMORY-AND-TEMPORALITY`
- `QDA-OH-POSITIONING-AGENCY-ATTRIBUTION`

Diese Läufe erzeugen narrative Memos und keine konkurrierenden Inhaltscodes. Bei
reinen SRT-Daten dürfen Prosodie, Pausen, Ton und nicht transkribierte Interaktion
nicht erschlossen werden.

### 6. Fallvergleich

Cross-Case-Analyse ist erst zulässig, wenn Fallgrenzen, Quellenumfang,
Forschungsfrage und Vergleichsdimensionen geklärt sind. Je nach Methode braucht
sie ein geprüftes gemeinsames Codebuch, Fallmemos oder ein vergleichbares
Themenset. Ein bloßes Zusammenführen von Modelloutputs genügt nicht.

Vorgesehene Schubladen:

- `QDA-XCASE-DESCRIPTIVE-MATRIX`
- `QDA-XCASE-THEME-COMPARISON`
- `QDA-XCASE-DEVIANT-CASE-ANALYSIS`

### 7. Technische Hilfen

Technische und administrative Aufgaben bleiben außerhalb der analytischen
Prompts:

- `QDA-UTIL-QUOTE-LOCATOR-VALIDATION`
- `QDA-UTIL-OUTPUT-CONVERSION`
- `QDA-UTIL-METADATA-SUGGESTIONS`
- `QDA-UTIL-SENSITIVITY-TRIAGE`

Ein Modellprompt kann exakte Zitate, Timecodes oder Zählungen verlangen, aber
nicht technisch garantieren. `VALIDATION` darf nur im Namen stehen, wenn ein
externer Vergleich mit der Originalquelle tatsächlich stattfindet.

## Entscheidungsweg

| Forschungsziel | Primäre Schublade | Zentrale Voraussetzung |
|---|---|---|
| Quellennahe Erstkodierung ohne Methodenclaim | Generic | Forschungsfrage und Materialumfang |
| Induktive Kategorien nach Mayring | Mayring inductive | Selektionskriterium, Abstraktionsniveau und Analyseeinheiten |
| Vorhandenes Kategoriensystem anwenden | Mayring deductive | geprüftes Codebuch mit Regeln und Ankerbeispielen |
| Muster geteilter Bedeutung entwickeln | Thematic Analysis | explizit gewählte TA-Variante und gesamter relevanter Datensatz |
| Erzählte Vergangenheit und Positionierung analysieren | Oral History | Originalpassagen; idealerweise reichhaltiges Transkript oder Audio |
| Prozessbezogene Theorie entwickeln | Grounded Theory | Studienworkflow, GT-Variante, fortlaufende Erhebung und Memoing |
| Fälle systematisch vergleichen | Cross Case | vergleichbare Fälle und harmonisierte analytische Grundlage |
| Zitate oder Timecodes prüfen | Utility validator | Originalquelle und technischer Vergleich |

## Standardkopf jeder Promptdatei

```text
PROMPT_ID:
VERSION:
STATUS: DRAFT | PILOTED | REVIEWED | RETIRED
METHOD_FAMILY:
METHOD_VARIANT:
ANALYTIC_OPERATION:
INTERNAL_LEVEL: L1 | L2 | NOT_APPLICABLE
OPTIONAL_SECONDARY_ANALYSIS:
MATERIAL_SCOPE:
ORIGINAL_SOURCE_REQUIRED:
CODEBOOK_REQUIRED:
PROJECT_STATE_REQUIRED:
ALLOWED_METHOD_CLAIM:
ALLOWED_OUTPUTS:
FORBIDDEN_OUTPUTS:
HUMAN_DECISIONS_REQUIRED:
TECHNICAL_VALIDATION: NONE | REQUIRED | COMPLETED
```

Der wichtigste Eintrag ist `ALLOWED_METHOD_CLAIM`. Er verhindert, dass ein
quellennaher Coding-Lauf später fälschlich als Mayring, Reflexive Thematic
Analysis oder Grounded Theory ausgegeben wird.

## Namenskonvention

```text
QDA-{METHOD}-{OPERATION}_{SCOPE}_v{MAJOR}.{MINOR}.md
```

Beispiele:

```text
QDA-GEN-CONTROLLED-CODING_INTERVIEW-EXCERPT_v1.1.md
QDA-MAY-INDUCTIVE-CATEGORY-FORMATION_CORPUS_v1.0.md
QDA-RTA-THEME-DEVELOPMENT_DATASET_v1.0.md
QDA-OH-MEMORY-TEMPORALITY_INTERVIEW_v1.0.md
```

Eine neue Major-Version verändert methodische Logik oder Outputvertrag. Eine
Minor-Version präzisiert Formulierungen, ohne den Methodenclaim zu verändern.

## Bibliotheksstruktur

```text
DigQDA/
├── README.md
├── 00_CORE/
├── 10_GENERIC/
├── 20_MAYRING_QCA/
├── 30_THEMATIC_ANALYSIS/
├── 40_GROUNDED_THEORY/
├── 50_ORAL_HISTORY/
├── 60_CROSS_CASE/
├── 90_UTILITIES/
└── 99_RETIRED/
```

Es werden nur fertige oder aktiv pilotierte Dateien angelegt. Geplante Prompts
stehen bis zur Ausarbeitung ausschließlich im Katalog dieses README.

## Empfohlene Ausbaufolge

1. Gemeinsamen epistemischen Kern als `QDA Constitution` extrahieren.
2. Mayring induktiv und deduktiv als zwei echte Spezialprompts entwickeln.
3. Technischen Zitat-/Locator-Validator getrennt definieren.
4. Oral-History-Memo als unabhängige Perspektive ergänzen.
5. Erst danach eine ausdrücklich gewählte Variante der Thematic Analysis bauen.
6. Grounded-Theory-Schubladen nur für ein tatsächlich iteratives GT-Projekt
   entwickeln.

## Quellenbasis

- Philipp Mayring, *Qualitative Content Analysis: Theoretical Foundation, Basic
  Procedures and Software Solution* (2014):
  https://qualitative-content-analysis.org/wp-content/uploads/Mayring2014QualitativeContentAnalysis.pdf
- Virginia Braun und Victoria Clarke, Reflexive Thematic Analysis – Prozess und
  methodische Hinweise: https://www.thematicanalysis.net/doing-reflexive-ta/
- Braun und Clarke, FAQ zur Unterscheidung von Theme und Topic Summary:
  https://www.thematicanalysis.net/faqs/
- Judith A. Holton, Überblick zum Coding-Prozess in klassischer Grounded Theory:
  https://groundedtheoryreview.com/wp-content/uploads/2012/06/GT-Review-vol-9-no-13.pdf

## Aktueller Bestand

| Datei | Status | Rolle / Methodenclaim |
|---|---|---|
| `10_GENERIC/p1_prompt.txt` | DRAFT | einzige kanonische, vollständig gehashte Runtime-Promptquelle, aktuell Prompt v1.2, mit OPEN-/CODEBOOK-Beispielen |
| `10_GENERIC/QDA-GEN-DESCRIPTIVE-CODING_SEGMENT_v1.1.md` | DRAFT | Methodenspezifikation für generische quellennahe Kodierung; kein Runtime-Fallback und kein spezifischer Methodenclaim |
| `10_GENERIC/p1_schema.json` | DRAFT | strenger Outputvertrag für P1 (additionalProperties:false, Enums, if/then) |
| `10_GENERIC/QDA-GEN-CONTROLLED-CODING_v1.1.md` | REVIEWED | Monolith; für die P1-Rolle abgelöst durch die dekomponierte Fassung oben |
| `00_CORE/QDA-CORE-RELIABILITY-LAYER_v0.1.md` | DRAFT | Pass-Pipeline, Runtime, Manifest, Validator/Renderer-Rollen |
| `90_UTILITIES/qda_segment.py` | DRAFT | P0: deterministische Segmentierung (SRT/TXT) |
| `90_UTILITIES/qda_validate.py` | DRAFT | Validator: Zitat-in-Einheit + Locator, fail-closed |
| `90_UTILITIES/qda_run_p1.py` | DRAFT | P1-Runner (Ollama), Modus erzwungen, fail-closed |
| `90_UTILITIES/tests/run_tests.py` | DRAFT | Conformance-Suite (117 Checks); `pip install -r requirements.txt` |
| `90_UTILITIES/smoke/run_smoke.sh` | DRAFT | synthetischer End-to-End-Pfad P0 (SRT+TXT) → P1 (OPEN+STRICT) → Validator |
| `eval/` | DRAFT | synthetische Semantic-Canary: Scope-, Entscheidungs- und Evidenzgrenzen; modellfreie Teile laufen in CI |
| `digqda` | DRAFT | einheitlicher Einstieg für Doctor-Check und isolierten P0 → P1 → Validator-Pilot |

Hinweis: Der Monolith trägt intern noch `TECHNICAL_VALIDATION: NONE`. Für die
dekomponierte P1-Linie gilt `TECHNICAL_VALIDATION: REQUIRED` — die Prüfung
erfolgt extern über `qda_validate.py`.
