# Deterministische Generalisierung (Optimierungswelle 1)

Die Regeln erhalten grobe analytische Information. Sie beweisen keine Anonymität:
auch Altersband, Jahr und Berufsfeld können in Kombination identifizierend sein.
Der vorhandene synthetische Freigabepfad braucht weiterhin Policy-Erlaubnis,
Human Review und zweiten Scan. Realdaten bleiben gesperrt; bewusstes Beibehalten
(`KEEP_AND_REVIEW`) wird durch diese Regeln nicht eingeführt.

`aegisqda.generalization.generalize(entity_type, value, language)` verarbeitet
genau einen vollständigen, einzeiligen, überprüften Finding-Wert. Es liefert
`GeneralizationResult(entity_type, text, rule_id)`. Nicht abgedeckte Werte stoppen
mit `ReviewRequired`; Fehlertexte enthalten keinen Originalwert. `lb` und andere
nicht freigegebene Sprachpakete stoppen mit `UnsupportedLanguage`.

| Entity | Regel-ID | Eingabe und Ausgabe |
|---|---|---|
| `AGE` | `AGE_TEN_YEAR_BANDS_TOPCODE_90_V1` | Exakte ganze Altersangabe mit `Jahr/Jahre alt`, `an/ans` oder `year/years old`; 0–120. Zehnjahresband: `37 Jahre alt` → `[AGE_BAND_30_39]`. Ab 90 → `[AGE_BAND_90_PLUS]`, um hohe Alter nicht weiter aufzuspalten. |
| `DATE_TIME` | `DATE_VALID_CALENDAR_YEAR_V1` | Vollständiges Kalenderdatum mit vierstelligem Jahr; Kalenderprüfung einschließlich Schaltjahren. ISO `YYYY-MM-DD`; de/fr: Tag–Monat–Jahr mit `.`, `/` oder `-`; en: Monat/Tag/Jahr mit `/` oder Tag.Monat.Jahr mit `.`. `29.02.2024` → `[YEAR_2024]`. |
| `KINSHIP` | `KINSHIP_FAMILY_CATEGORY_V1` | Geschlossene Liste Mutter/Vater/Schwester/Bruder, mère/père/soeur/sœur/frère, mother/father/sister/brother → `[FAMILY_RELATION]`. |
| `JOB_TITLE` | `JOB_CONTROLLED_SECTOR_V1` | Arzt/Ärztin, médecin, doctor → `[OCCUPATION_HEALTH]`; Lehrer/Lehrerin, enseignant/enseignante, teacher → `[OCCUPATION_EDUCATION]`. |

Die Listen akzeptieren Groß-/Kleinschreibung und Unicode-NFC. Explizit abgedeckte
de/fr/en-Wörter dürfen in anderssprachigen Passagen eines unterstützten
Transkripts vorkommen; daraus folgt keine allgemeine Code-Switching-Abdeckung.
Umliegende Leerzeichen werden entfernt, weitere Wörter nicht ausgeschnitten.

Ungefähre Alter, Bereiche, bloße Zahlen, zweistellige Jahre, ungültige Daten,
gemischte Datumsseparatoren, freie Berufsbezeichnungen und Titel mit Zusatz
stoppen. Es gibt weder Schätzung noch stillen Ersatz durch Originaltext.
`SMALL_PLACE` und `RARE_EVENT` bleiben außerhalb dieser Regeln und blockieren.

Der Workflow muss erzeugte Texte mit Regel-ID und exakter Zeichenposition
protokollieren. Nur dort darf er erwartete Generalisierungen im zweiten Scan
auflösen. Zusätzlich dürfen PERSON/LOCATION/ORGANIZATION-Modellhits vollständig
innerhalb eines solchen erzeugten Markers aufgelöst werden (etwa spaCy PERSON
für `[YEAR_2026]`). Die Freigabe rekonstruiert dazu Originalwert, Review-Entscheidung,
Regel und Ausgabetext bytegenau; fremde Marker oder grenzüberschreitende Hits
bleiben blockierend. `is_generalized_output` prüft ausschließlich das erlaubte Vokabular;
es erteilt allein keine Ausnahme. Schon im Original vorhandene ähnlich
aussehende Marker, andere Positionen, Überlappungen oder unbekannte Regeln
dürfen dadurch nicht aus dem Scan verschwinden.

Änderungen an Bandgrenzen oder Listen erhalten eine neue Regel-ID und neue
synthetische Regressionen. Die synthetische strikte Policy 0.2.0 aktiviert diese
Regeln für DATE_TIME, AGE, KINSHIP und JOB_TITLE nach explizitem Review. Das ist
keine Governance-Freigabe für Realdaten. Zusätzliche Kategorien brauchen neue
Regeln, Fixtures und eine explizite Policy-Änderung.
