# DigQDA — Betriebs-Runbook (Vorlage)

```text
DOC_ID: DigQDA-OPERATIONS-RUNBOOK
VERSION: 0.2 (DRAFT / TEMPLATE)
STATUS: VORLAGE — Slots ⟨…⟩ vor produktivem Einsatz ausfüllen
SCOPE: consumer-seitiger technischer Betrieb; lokales Ollama-Setting (macOS)
BEZUG: contracts/DigQDA-INTEGRATION-CONTRACT_v0.1.md · SECURITY.md
       · docs/MODEL_COMPATIBILITY.md
```

> Konsumenten-neutrale Vorlage: keine Instituts-/Projektnamen hartkodiert
> (`⟨Slots⟩`). Die ausgefüllte Fassung gehört in die interne Ablage des Instituts,
> nicht in dieses Upstream-Repo (Integration Contract §2).
> Diese Konfiguration wird einmal intern vervollständigt; Operator:innen müssen
> die Vorlage nicht vor jedem Lauf erneut bearbeiten.

---

## 0. Rechtlicher Rahmen — das Nötigste (hier abschließend)

Dieses Runbook operationalisiert eine **bestehende DPO-Genehmigung** für ein
lokales Verarbeitungssetting. Es ist eine **technische Betriebsanleitung, keine
Rechtsberatung.**

Alle rechtlichen Festlegungen liegen bei der **Verantwortlichen Stelle und
dem/der DPO** und stehen in der **internen Datenschutz-/Ethik-Akte** — nicht in
diesem technischen Dokument. Dazu zählen Rechtsgrundlage, besondere
Datenkategorien, DSFA-Pflicht, Aufbewahrungsfristen sowie Melde- und
Betroffenenrechte.

| In der internen Akte gepflegt | Verweis |
|---|---|
| Verantwortliche Stelle | ⟨…⟩ |
| DPO (Name/Kontakt) | ⟨…⟩ |
| Genehmigung (Aktenzeichen/Datum) | ⟨…⟩ |
| Rechtsgrundlage · Fristen · DSFA · Meldewege | ⟨interne Akte⟩ |

**Betriebsgrundsatz (gilt technisch im ganzen Dokument):** Lokale Ausführung ist
keine Anonymisierung. Quelltext und alle abgeleiteten Zitate bleiben
schützenswert und werden technisch wie Rohdaten behandelt.

*Ab hier ist das Runbook rein technisch.*

---

## 1. Genehmigte Konfiguration

Gilt ausschließlich für diese lokale Konfiguration. Jede Abweichung (anderer
Modell-Host, entfernter Endpunkt, Cloud-Dienst, anderes Gerät) fällt nicht unter
dieses Runbook.

| Merkmal | Wert |
|---|---|
| Projekt / Verfahren | ⟨…⟩ |
| Gerät | ⟨macOS-Gerät / Inventar-ID⟩, festplattenverschlüsselt |
| Ausführung | vollständig lokal; keine Cloud-, keine Fremd-API |
| Backend | lokales Ollama (`localhost`), ohne Netz-Egress |
| Modelle | lokal, aus dem Satz: Mistral / Qwen / Gemma |
| Datenarten | ⟨z. B. Interviewtranskripte SRT/TXT⟩ |

Modellwechsel (Mistral ↔ Qwen ↔ Gemma) bleibt im Rahmen; der konkrete
**Modell-Digest** wird pro Lauf im Manifest festgehalten (§9).

## 2. Rollen im Betrieb

- **Operator:in** ⟨…⟩ — führt Läufe gemäß diesem Runbook aus.
- **Reviewer:in** ⟨…⟩ — Human-in-the-loop-Freigaben (§5), Quell-Verifikation.
- **Interner Vorfallkontakt** ⟨Rolle/Kontakt⟩ — bei technischen Vorfällen (§11).

## 3. Datenfluss und Systemgrenze (Trust Boundary)

```text
 ⟨verschlüsselter Projektordner auf dem macOS-Gerät⟩
        │  Originalquelle (SRT/TXT)
        ▼
 ./digqda pilot         (ein sichtbarer Einstieg; isolierter Laufordner)
        │
        ▼
 P0  qda_segment.py     (Code, lokal; keine Modell-Entscheidung)
        │  source_units[] + Locatoren
        ▼
 P1  qda_run_p1.py  →  lokales Ollama  →  {Mistral|Qwen|Gemma}
        │  KEIN Netz-Egress · erzwungenes JSON-Schema · fail-closed
        ▼
 V   qda_validate.py    (Code, lokal; Zitat-/Locator-Abgleich gegen Quelle)
        │  PASS | REVIEW_REQUIRED | NO_EVIDENCE | INVALID_INPUT
        ▼
 Outputs (schützenswert) + Run-Manifest
        ▼
 Mensch: Prüfung, Quell-Verifikation, Freigabe (§5)
```

- Gesamte Verarbeitung läuft **lokal**; das Modell antwortet über `localhost`.
  Keine Übermittlung von Quelltext, Zitaten oder Ergebnissen an Dritte.
- **Egress kontrollieren:** sicherstellen, dass Ollama keine Telemetrie sendet;
  für die Verarbeitung möglichst **offline** arbeiten. ⟨Firewall-/Vorgehen: …⟩.

## 4. Datenminimierung am DigQDA-Rand

- **Opake `unit_id`:** nur pseudonyme, pfadsichere Identifikatoren an den Rand —
  keine Klarnamen, Projektnamen, Pfade oder Katalog-IDs.
- **Zuordnungsregister außerhalb von DigQDA:** Mapping `opake ID ↔ Person/
  Interview/Datei` in einem getrennten, verschlüsselten, zugriffsbeschränkten
  Register ⟨Ort/System⟩; nie in DigQDA-Eingaben oder -Manifeste.
- **Eine Einheit pro Modellaufruf:** kein Zusatzkontext, keine nicht
  erforderlichen Namen im `source_text`.
- **Forschungsfrage:** geht nur als Hash ins Manifest; keine
  personenbeziehbaren Details hineinschreiben.

## 5. Human-in-the-loop — verpflichtende Schritte

DigQDA schlägt vor; der Mensch entscheidet und verifiziert. Jeweils mit Sign-off
(wer/wann/was):

1. **Segmentierung annehmen** — P0 ist mechanisch; die analytische Bewertung ist
   menschlich.
2. **Code-Annahme** — `INDUCTIVE_CANDIDATE` bleibt Vorschlag bis zur Prüfung.
3. **Code-Konsolidierung / Merging.**
4. **Quell-Verifikation** — jedes Zitat/Locator gilt als *unverifiziert*, bis
   `qda_validate.py` `PASS` liefert **und** eine Person die Stellen gegen die
   Quelle prüft (Pilot: vollständig; später mindestens Stichprobe).
5. **Interpretive Annahme (L2)** — nur falls je aktiviert; getrennter Schritt.

Ohne diese Schritte wird kein Ergebnis als „verifiziert" behandelt oder geteilt.

## 6. Outputs, Artefakte, Quarantäne

- **Alle Outputs sind schützenswert.** `p1_*.json` enthält wörtliche Zitate;
  `validation_*` und Manifeste können Quellauszüge enthalten → gleiche
  Schutzklasse wie Rohdaten.
- **Explizite Schreibvorgänge:** Der Pilot schreibt je Aufruf in einen frischen,
  nicht überschreibbaren Laufordner außerhalb des Repos. Quarantäne bleibt
  opt-in (`--diagnostic-quarantine`, Hash-Dateinamen, Modus `0700`).
- **`quarantine/` und `smoke/out/` sind git-ignoriert** — verhindert
  versehentliches Committen, ersetzt aber nicht Verschlüsselung/Zugriff/Löschung.
- **Keine Roh-/Fuzzy-Zitate in allgemeine Logs.** Manifeste getrennt erfassen.
- **Hashes stützen Integrität, anonymisieren nicht** (`source_sha256`).

## 7. Speicherung, Verschlüsselung, Zugriff

- **At-rest:** ⟨FileVault / verschlüsseltes Volume⟩; Projektordner
  zugriffsbeschränkt auf ⟨berechtigte Personen⟩.
- **Kein Cloud-Sync** von Quellen/Outputs/Quarantäne (iCloud/Dropbox/OneDrive).
  ⟨Ausschluss bestätigen.⟩
- **Backups:** ⟨verschlüsselt, gleiche Schutzklasse⟩.
- **Git-Hygiene:** Repo enthält keine Forschungsdaten; `.gitignore` deckt
  `quarantine/`, `smoke/out/`, temporäre Dateien ab. Nie echte Transkripte/
  Outputs committen. Kein Remote konfiguriert → nichts wird gepusht.

## 8. Löschung und Aufbewahrung (Mechanik)

- Zwischenartefakte (`segments_*`, `p1_*`, `validation_*`, Quarantäne) so kurz
  wie möglich vorhalten; **Quarantäne zeitnah nach Diagnose löschen.**
- Sichere Löschung: ⟨Verfahren⟩.
- **Löschung einzelner Betroffener:** über das Zuordnungsregister (§4) die
  betroffenen `unit_id` bestimmen und inklusive abgeleiteter Outputs und
  Manifeste entfernen. ⟨Verfahren⟩.
- Aufbewahrungs*fristen*: siehe interne Akte (§0).

## 9. Provenance / Audit

Jeder Lauf schreibt ein Manifest als Audit-/Methoden-Nachweis:

- Vertrag/Artefakte: `run_id`, `library_version`, `contract_version`,
  `contract_sha256`, `prompt_sha256`, `schema_sha256`, `grammar_sha256`,
  `allowed_method_claim`.
- Modell: `model`, `model_digest`, `model_quantization`, `backend`,
  `backend_client_version`, Runtime (`temperature`, `top_p`, `num_ctx`, `seed`).
- Bindung: `source_sha256`, je Einheit `unit_input_sha256` und
  `rendered_prompt_sha256`, `research_question_sha256`, `codebook_sha256`.

Das Manifest speichert **Hashes, nicht die Texte**; die Zitate stehen in den
Output-JSONs und werden entsprechend geschützt (§6/§7). Manifeste getrennt
archivieren. **Determinismus-Caveat:** `seed`+`temperature 0` verbessern die
Wiederholbarkeit, garantieren sie nicht; Modellwechsel verändert Ergebnisse →
Modell **und** Digest stets mitführen (`docs/MODEL_COMPATIBILITY.md`).

## 10. Fail-closed-Akzeptanz

Ein Ergebnis nur akzeptieren, wenn **alle** Punkte zutreffen — sonst
Nicht-Ergebnis:

- [ ] Prozess-Exit `0`;
- [ ] jede Einheit `OK`;
- [ ] Voll-Schema- und Modus-Validierung bestanden;
- [ ] `qda_validate.py` liefert `PASS`;
- [ ] Manifest-Versionen entsprechen den gepinnten Versionen;
- [ ] realer Lauf trägt `model_digest`, `unit_input_sha256`,
      `rendered_prompt_sha256` je akzeptierter Einheit;
- [ ] Human-in-the-loop-Schritte (§5) erfüllt und dokumentiert.

## 11. Vorfall — technische Sofortmaßnahmen

- Bei Verdacht (Leak, Fehlkonfiguration, versehentlicher Cloud-Sync, unbefugter
  Zugriff, Geräteverlust): Verarbeitung stoppen, Gerät/Ordner sichern.
- Umfang dokumentieren (betroffene `unit_id` via Register, Zeit, Sofortmaßnahme).
- **⟨Eskalationskontakt⟩ unverzüglich informieren** (weitere Schritte: §0).
- **Keine echten Daten** in Fehlerberichte/Support (`SECURITY.md`) — synthetische
  Minimalbeispiele.

## 12. Freigabe

- Vor Weitergabe/Publikation: **Quell-Verifikation (§5)** und Prüfung, ob ein
  Zitat (auch indirekt) auf eine Person rückführbar ist.
- `verifiziert` vs. `unverifiziert` konsequent kennzeichnen; nichts als
  „verifiziert" ausgeben ohne externen Quellabgleich.

## 13. Betriebs-Checklisten

Die wiederkehrenden technischen Prüfungen sind im Einstieg automatisiert:

```bash
./digqda doctor
./digqda pilot CASE-001 /sicherer/pfad/interview.srt
```

Nur die methodische Quell- und Codeprüfung in `REVIEW.md` bleibt bewusst manuell.

**Vor jedem Lauf:** genehmigte Konfiguration (macOS, lokales Ollama, Modell ∈
{Mistral, Qwen, Gemma}) · Gerät verschlüsselt · Arbeitsordner nicht
cloud-synchronisiert · opake `unit_id` · Output-Ordner zugriffsbeschränkt ·
`num_ctx = 8192` · Ollama ohne Egress.

**Nach jedem Lauf:** Exit `0` und alle Einheiten `OK` · Validator `PASS` ·
Human-Review + Quell-Verifikation signiert · Manifest getrennt archiviert ·
sensible Artefakte verschlüsselt · Quarantäne gelöscht · keine Zitate in
Logs/Temp.

**Erst-Pilot (zusätzlich):** genau **ein** Transkript · Reviewer prüft **alle**
gebundenen Zitate manuell gegen die Quelle · Ergebnis + Manifest gemeinsam
durchsprechen, bevor ein zweites Transkript folgt.

## 14. Referenzen

- `contracts/DigQDA-INTEGRATION-CONTRACT_v0.1.md` — Consumer-Grenze
- `SECURITY.md` — sensible Daten / Meldung
- `docs/MODEL_COMPATIBILITY.md` — getestete Modell/Backend-Kombinationen
- `00_CORE/QDA-CORE-RELIABILITY-LAYER_v0.1.md` — Pass-Pipeline, Manifest, Validator
- `90_UTILITIES/pilot/README_PILOT.md` — Ablauf des überwachten Pilotlaufs
