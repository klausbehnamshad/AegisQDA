# General Review und Optimierungswelle 1

Stand: 2026-10-03. Geprüft wurde der lokale Arbeitsbaum einschließlich der
vorhandenen uncommitteten Governance-Verträge. Der beigefügte Review beschreibt
einen weiter fortgeschrittenen Stand; dessen externe Merge-/Release-Aussagen
wurden nicht über Remote-Dienste geprüft. Die fehlenden Code-Fixes wurden lokal
nachgebaut und gegen synthetische Regressionen geprüft.

Diese Welle autorisiert keinen Realdatenpilot und beweist keine universelle
Anonymität oder gültige Interpretation.

## Befunde und verbleibende Grenzen

| Punkt | Ergebnis | Verbleibende Grenze |
|---|---|---|
| P0 / umbrochene oder eingeklammerte Namen | Content-Projektion, eine PERSON-Nennung/ein Review/ein Platzhalter, dokumentlokale Koreferenz und strukturell gültige Restzeilen. Kein pauschales Ignorieren von Klammern. | Offener Namens-Recall bleibt unbewiesen. |
| Alte Detektoren v1/v2 | Review, Transform und Downstream sperren veraltete Snapshots. Lesender `audit`, einschließlich v1 ohne Surrogat-Ranges. | Auch LEGACY_NO_NEW_FINDINGS autorisiert nichts; neu scannen und reviewen. |
| F1/F7 indirekte Identifikatoren | Synthetische Policy 0.2.0: bestätigte Altersbänder, Kalenderjahre, Familienkategorie und geschlossene Berufsfelder. Unbekanntes, SMALL_PLACE und RARE_EVENT blockieren. | Grobe Kategorien können kombiniert identifizierend sein. Pilot-Policy braucht DPO/PI; kein KEEP-/Restrisiko-Release. |
| F2 Overlaps | PERSON-Hits einer Nennung werden konservativ vereinigt; andere Cross-Type-/partielle Overlaps verhindern uneindeutige Transformation. | Allgemeine einzeln signierte Suppressionsentscheidungen und Gruppenoberfläche fehlen. |
| F3/F6 Recall / Code-Switching | SHA-gebundene, exakt annotierte de/fr/en-Regressionsfälle mit Fremdnamen, E-Mails und Telefonnummern. | Kleine Fixture-Suite, keine Messung offenen Recalls. Eingebettetes lb ist nicht allgemein qualifiziert; deklarierte Sprache lb bleibt gesperrt. |
| F4 Outputsprache / Contract | Deutscher Analyseprompt und Contract-/Schema-/Grammar-Hashes exakt gebunden; Evidenz und Sprecher werden mit Quellsprache geprüft. Nur nachweislich erzeugte Marker werden ausgenommen. | Andere Prompt-/Codebook-Modi brauchen eigene vollständige Verträge. |
| Modelloutput-Fehlalarme | Maschinenvokabular nur an exakten Schema-Pfaden; Validator-Kopie auf Originalcoding zurückgeführt und hashgeprüft. Freie Texttreffer benötigen einzelne signierte menschliche Fehlalarmentscheidungen mit erneuter vollständiger Prüfung. | SELF_SIGNED_LOCAL ist keine institutionelle Reviewer-Autorisierung; bestätigte Identifikatoren und Unsicherheit bleiben blockierend. Methodische Prüfung und Veröffentlichungssperre bleiben bestehen. |
| F5 Reviewer-Trust | Konfigurierte Fingerprints werden für Signaturen durchgesetzt. Leere Allowlist erlaubt nur das ehrlich bezeichnete synthetische SELF_SIGNED_LOCAL-Niveau. Reale Detection wird auch mit gültiger Signatur gesperrt. | Rollenbasierter signierter Trust Store, Rotation und Widerruf fehlen. |
| F8 Fixture / Git | 22 Repository-Quellen byte-, sprach- und registry-hash-gebunden. Veränderte oder fremde Repo-Fixtures stoppen. Staged-Guard/Repo-Hook vorbereitet, sensible Outputs/Schlüssel ignoriert. | Externe synthetische Testquellen bleiben EXPLICIT_SYNTHETIC_ASSERTION. Vorhandene globale Hooks werden nicht überschrieben. |
| Neue Provenienzlücke | Vor Downstream vollständige bytegenaue Rekonstruktion aus Quelle, Review und Policy sowie erneuter zweiter Scan. Gültige Review-Signatur autorisiert keine andere resealed Ausgabe. | Ungekeyte synthetische Siegel schützen nicht vor komplettem Umschreiben durch den Dateieigentümer. |
| Neue False-Positive-Lücke | Ausnahme nur für den konkret reviewten, unveränderten Span mit Entity und Werthash. Anderer Kontext erbt sie nicht. | Menschliche Fehlentscheidung bleibt möglich. |
| Änderungen während Verarbeitung | Stabile JSON-Byte-Snapshots, keine doppelten Schlüssel, Quellfreigabe nach Modelllauf und vor Speicherung erneut geprüft. Outputreview prüft Ausgaben und Freigabe nochmals am Scanende. Änderungen erzeugen BLOCKED ohne Ergebnis oder reviewbaren Candidate. | Ungekeyte Artefakte sind weiterhin keine vertrauenswürdige Infrastruktur-Attestation. |
| Modell / Netzwerk | Exakte bereits qualifizierte Tag-/Digest-Paare; Literal-Loopback, keine Redirects, keine Proxy-/Auth-Umgebungsübernahme. Mehrdeutiges Modellinventar blockiert. | Keine automatischen Downloads oder neuen Modellfreigaben. |
| Governance-Datenklassen | Echte Zeitvergleiche, Hash-/Threshold-/Enum-Prüfungen, Envelope an tatsächliches PolicyManifest gebunden. Unimplementierte Governance-Schalter werden abgewiesen. | Verträge/Datenklassen sind keine ausgeführte Vier-Augen-Freigabe. PROCESS_RELEASED_* wird nicht emittiert. |

## DH-Ausbau

Der [lokale Research-Workbench](DH_WORKBENCH.md) bietet deklarierte Methoden,
hierarchische versionierte Code-Definitionen, menschliche Codings mit exakten
Evidenzspans, reflexive Memos, deduplizierte Häufigkeiten und tatsächliche
Span-Ko-Okkurrenzen. Freitext wird interaktiv statt als CLI-Argument abgefragt;
Summaries enthalten nur IDs und Zählungen. Keine Modellinterpretation wird
automatisch übernommen. Memos und Code-Definitionen bleiben geschützter Text.

Ereignisse werden von der Anwendung ohne Überschreiben angehängt. Die Hash-Kette
hat keinen externen Head-Anker und keine vertrauenswürdigen Signaturen:
vollständiges Umschreiben oder Entfernen eines Event-Tails ist nicht zuverlässig
erkennbar. Status: UNKEYED_SYNTHETIC_RESEARCH_ONLY / METHODOLOGICAL_REVIEW_REQUIRED.
Release-/Quellhashes werden einmal je Logprüfung gelesen; Ko-Okkurrenzen verwenden
eine aktive Spanmenge statt alle disjunkten Paare zu vergleichen. Hohe echte
Überlappungsdichte und vollständiges Loglesen bleiben Skalierungsgrenzen.

## Unkomplizierter Folgeausbau vom 2026-10-03

Aus dem Review sind weitere ausführbare Bausteine entstanden:

| Baustein | Erreichter Stand | Verbleibende Grenze |
|---|---|---|
| `review-plan RUN` | Quellenfreie Gruppen tatsächlicher atomarer Spanüberschneidungen, einschließlich transitiver Cross-Type-Gruppen. Angrenzende Spans oder bloß überlappende Bounding-Ranges bilden keine Gruppe. | Lesende Planung; keine automatische Suppression, keine Freigabe. |
| `verify RUN` | Lesender Offline-Verifier für aktuelle Privacy-/Research-/Downstream-Bindungen, Signaturen, Output-Ausnahmen und Versuchshistorie. Keine Ollama- oder Netzwerkaufrufe. | SYNTHETIC_VERIFIED ist keine institutionelle, externe oder reale Datenfreigabe. |
| `detector-inventory --language en` | Stabile Bytefingerprints installierter Modell-/Tokenizerassets, Recognizerkontrollen, Policy und Konfiguration. Änderungen während Inventur blockieren. | UNQUALIFIED_LOCAL_INVENTORY; keine Recall-Qualifikation oder freigegebene Asset-Allowlist. |
| Segment-Retrieval | Contentzeilen mit freigabegebundenen IDs, Positions-/Evidenzhashes, wörtliche interaktive Suche und ausdrücklich angeforderte geschützte Evidenzanzeige. | Contentspans sind keine automatisch festgelegten analytischen Segmente; Anzeigen bleiben geschützt. |
| Dissensansicht | Unterschiedliche Codesets expliziter Analysten auf derselben exakten Evidenz. | Fehlende Codings oder abweichende Segmentgrenzen gelten nicht als Dissens; keine Reliabilitätsaussage. |
| Mehrfall-Workspace | Owner-only Registrierungen mit Release-/Research-Prefix-Bindung, kompatibler Methodik und Codebedeutung; quellenfreie Fall×Code-Matrix. | Ungekeyt, kein externer Head-Anker; jeder Fall wird einzeln geprüft, kein atomarer Gesamtsnapshot. |

Die README beschreibt jetzt den DH-Arbeitsablauf von Privacy-Review bis Retrieval,
Coding, Memos und Fallvergleich. Die verwaiste, seit Juli unveränderte leere
`.git/index.lock` wurde nach zweimaliger Prüfung ohne offenen Prozesshandle
entfernt. Der bestehende Arbeitsbranch blieb erhalten. Bei dieser Prüfung
wurde keine Staging-, Commit- oder Push-Aktion ausgeführt.

Folgeausbau geprüft: **618 Tests erfolgreich**. Die vollständige Suite bestand
mit 616 Tests in der eingeschränkten Sandbox; zwei bestehende HTTP-Transporttests
wurden dort allein durch verweigertes `bind(127.0.0.1)` blockiert und anschließend
mit lokaler Berechtigung gezielt wiederholt: 2/2 bestanden. Ruff, Mypy (31 Dateien)
und `git diff --check` sauber. Neue API- und CLI-Prüfungen laufen mit synthetischen
Quellen; Offline-Verifier, Retrieval und Workspace benötigen keine Inferenz.
Staged-Guard: lesender Indexcheck PASSED, `checked_count=0`; keine Änderungen
gestaged. Der lokale EN-Detektorassetbaum wurde tatsächlich inventarisiert
(28 Dateien, 445142969 Bytes), ohne Netz-/Modellaufruf oder gespeicherten Export.
Inventar und Forschungsfunktionen erteilen weiterhin keine Pilotfreigabe.

## Nächste Welle / harte Pilot-Blocker

1. Signierter Trust Store, Register-Owner-Pinning, Serien-/Rollback-Schutz,
   unabhängige Reviewer-/Approver-Signaturen, Revocation und institutionelle
   Autorisierungsprüfung im jetzt vorhandenen synthetischen Offline-Verifier.
   Infrastruktur-Attestation bleibt eine eigene Gate-Anforderung.
2. Qualifikation und institutionelle Freigabe der jetzt inventarisierbaren
   spaCy-Modellbaum-/Tokenizer-/Recognizer-Manifeste, Registrierung
   auch externer synthetischer Quellen, breitere Sprach-/Entity-Suiten mit
   negativen Kontrollen und ausdrücklicher lb-Code-Switching-Policy.
3. Signierte Suppressionsentscheidungen auf den jetzt vorhandenen allgemeinen
   Overlap-Gruppen;
   methodische Übernahme oder Ablehnung einzelner Modellvorschläge. Bestehende DigQDA strict/extend
   Modi erst mit gebundenem Codebook, Forschungsfrage, Prompt und Grammar öffnen.
4. Zugängliche lokale grafische Oberfläche für die jetzt vorhandenen
   Mehrfall-, Retrieval-, Matrix- und Dissensfunktionen; Auswahl flexibler
   analytischer Segmente. Reliabilitätsmaße nur bei passender Methode.

Kommunikation: sachliche Beschreibung der geprüften Änderungen und ihrer
Grenzen; kein verbindliches Ein-Wochen-Antwortversprechen.
Release, öffentliche Advisory-Veröffentlichung und Ankündigungen sind nicht erfolgt.

## Reproduzierbare Prüfung

Lokale Prüfung vom 2026-10-03:

- Ausgangsstand: 102 Tests bestanden.
- Endstand: **436 Tests bestanden**; Ruff, Mypy (26 Quelldateien) und
  `git diff --check` sauber. Änderungen während Scan/Modelllauf, resealed
  Artefakte, doppelte JSON-Schlüssel, gefälschte Signaturen und Pfadausbrüche
  sind als Regressionen enthalten.
- Kuratierte Recognizer-Suite: 15/15 annotierte Spans je de/fr/en/lb,
  keine Treffer in sicheren Kontrollen. lb bleibt trotz dieser kleinen
  Regex-Suite BLOCKED_OPTIONAL.
- Interview-Fixtures: 9/9 geprüft; Privacy-Batch 9/9 erwartete Zustände,
  einschließlich drei absichtlich blockierter Fälle.
- Code-Switching: neun ausdrücklich annotierte Fremdspans in drei
  SHA-gebundenen Fällen erkannt; kein allgemeines Recall-Versprechen.
- Echter loopbackgebundener Gemma3-Lauf auf `en/qualification.srt`: Privacy-Gate,
  Audit CURRENT, DigQDA-Vertrag und Quote-Validator bestanden. Zwei Treffer im
  deutschen Code-Label „Identitätsangabe“ erhielten ausschließlich in diesem
  synthetischen Test simulierte signierte Fehlalarmentscheidungen. Finalisierung
  blieb DOWNSTREAM_REVIEW_REQUIRED; anschließend vier Research-Ereignisse und
  eine quellenfreie Summary geprüft. Laufzeit 49,7 s. Temporäre Schlüssel,
  Runs und Ausgaben danach entfernt. Dies ist keine menschliche Interpretations-
  oder reale Datenschutzfreigabe.
- Doctor READY mit beiden bereits qualifizierten exakten Modell-Digests;
  gepinnter Upstream unverändert.
- Staged-Guard: 78 Tests bestanden. Lesender Indexcheck PASSED mit
  `checked_count=0`; das bestätigt keine bereits gestagten Änderungen. Der
  vorbereitete Repo-Hook wurde nicht aktiviert und globale Hooks nicht verändert.

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check src scripts tests
.venv/bin/python -m mypy --check-untyped-defs src/aegisqda
.venv/bin/python scripts/synthetic_acceptance.py
.venv/bin/python scripts/verify_interviews.py
.venv/bin/aegisqda doctor
bash scripts/run_synthetic_interviews.sh --privacy-only
# Voller Loopback-Modelltest nur bei doctor READY:
bash scripts/run_synthetic_interviews.sh
```

Der volle Batch akzeptiert keine freien Output-Fehlalarme automatisch. Bei
POST_SCAN_FINDINGS bleibt er blockiert, bis die einzelnen Treffer im
[geschützten Outputreview](DH_WORKBENCH.md#blockierte-modellvorschläge-prüfen)
bewertet und erneut geprüft wurden.

Test-/Runartefakte bleiben geschützt außerhalb Git. `vendor/digqda/`, benachbarte
Projekte und DINOH bleiben unverändert. Ein Audit ist Diagnose, keine Freigabe.
