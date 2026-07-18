# Grundlegende Reflexionen: Konsolidierung und Vertiefung Richtung QDA

Ein Strategie- und Denkpapier, kein Arbeitsauftrag. Es ordnet ein, wo AegisQDA
heute steht, was „Vertiefung Richtung QDA" methodisch bedeutet, und in welcher
Reihenfolge sich Konsolidierung und Erweiterung sinnvoll aufeinander aufbauen
lassen — ohne die Seele qualitativer Forschung und die harte, fail-closed
Haltung des Projekts zu verlieren.

## Standortbestimmung

AegisQDA ist heute kein QDA-Werkzeug, sondern der Türsteher davor: ein lokal
laufendes, fail-closed Privacy-Gateway, das qualitatives Material absichert,
bevor es den gepinnten DigQDA-Snapshot erreicht. Das ist eine bewusste und
richtige Schichtung — Datenschutz zuerst, Analyse danach. „Vertiefung Richtung
QDA" heißt deshalb nicht, das Gateway umzubauen, sondern die Kette vom Türsteher
zum durchgängigen, methodisch tragfähigen Analyse-Workflow zu verlängern. Das
Bemerkenswerte ist: Die Prinzipien, die das Gateway stark machen, sind exakt
die Prinzipien, die gute qualitative Analyse verlangt. Genau darin liegt die
Chance.

## Was QDA epistemisch verlangt — und warum das Projekt gut dazu passt

Qualitative Analyse ist Interpretation, nicht Extraktion. Kodieren heißt, Sinn
zuzuschreiben, nicht Entitäten zu ernten. Ihre Gütekriterien sind nicht
Genauigkeit im messtechnischen Sinn, sondern Glaubwürdigkeit, Nachvollziehbar-
keit (ein prüfbarer Entscheidungspfad), Bestätigbarkeit (Befunde sind an Daten
rückbindbar, nicht an die Vorlieben des Analysten) und – mit Vorsicht –
Übertragbarkeit. Ein Werkzeug, das diese Methodik ernst nimmt, muss die
Interpretationshoheit des Menschen stützen statt sie zu ersetzen, und es muss
jede Zuschreibung an ihre Herkunft binden.

Genau diese Haltung steckt schon im Code. Die Demut des Datenschutzteils — „wir
garantieren keine Anonymität, wir garantieren einen geprüften Prozess" — ist
dieselbe Demut, die die Analyse braucht: Ein Modell garantiert keine gültige
Interpretation, es liefert einen prüfbaren Vorschlag. Der DigQDA-Contract, der
`quotes_missing_evidence == 0` erzwingt und bei fehlender Evidenz nach
`NO_EVIDENCE` fällt, ist bereits fail-closed im epistemischen Sinn: bei
Unsicherheit markieren, nicht raten. Und die Provenance-Kette — kanonisches
JSON, SHA-256-Siegel, gebundener Modell-Digest, gepinnte Prompt-Version — ist
technisch nichts anderes als ein lückenloser Audit-Trail, also eines der
zentralen Gütekriterien qualitativer Forschung, nur konsequenter umgesetzt als
in den meisten etablierten Werkzeugen. Das ist ein echtes Alleinstellungsmerkmal:
**verifizierbare, lokale qualitative Analyse.**

## Konsolidierung zuerst: festigen, was trägt

Bevor Funktionen wachsen, sollte das Fundament belastbar werden. Drei Dinge
gehören direkt aus dem Readiness-Review hierher: eine interview-förmige
Recall-Suite mit annotierten Spans statt der 1–4-Zeilen-Fixtures (F3), eine
explizite, DPO-getragene Policy-Entscheidung für die indirekten Identifikatoren
`AGE`/`KINSHIP`/`JOB_TITLE`, die heute stillschweigend auf `BLOCK` fallen (F1),
und eine deterministische Auflösung der NER/Regex-Überlappungen, die sonst jeden
zweiten realen Transkript-Lauf im `transform` anhalten (F2). Das synthetische
Interview-Korpus, das jetzt vorliegt, ist das Sprungbrett dafür: es macht die
Pipeline zum ersten Mal auf interview-förmigem Text erlebbar und lässt sich
schrittweise zur annotierten Bewertungsgrundlage ausbauen.

Konsolidierung heißt aber auch, den vorhandenen Audit-Trail bewusst als
Forschungs-Ressource zu deklarieren, nicht nur als Sicherheitsmechanik. Wer
später fragt „woher kommt dieser Code, auf welcher Quelle, mit welchem Modell,
welcher Prompt-Version, von wem freigegeben?", soll die Antwort aus den
gesiegelten Manifesten lesen können. Diese Frage ist die methodische
Kernfrage der Nachvollziehbarkeit — und sie ist hier schon fast beantwortet.

## Erweiterung: vom deskriptiven Kodieren zur gestützten Analyse

Wichtige Korrektur zu einer ersten Fassung dieses Papiers: DigQDA kann heute
schon mehr als deskriptives Kodieren. Der Snapshot enthält neben
`QDA-GEN-DESCRIPTIVE-CODING` auch `QDA-GEN-CONTROLLED-CODING` samt Codebook-
Fixtures, also die Modi `STRICT_CODEBOOK` und `CONSTRAINED_EXTENSION`. Was fehlt,
ist nicht die Fähigkeit, sondern deren sichere Freigabe: der AegisQDA-Adapter ruft
DigQDA aktuell fest mit `--mode open` auf. Der erste konkrete Erweiterungsschritt
ist deshalb nicht, ein Codebook neu zu erfinden, sondern die **vorhandenen**
Codebook-Modi durch das Gateway zu exponieren — mit derselben Strenge wie beim
Rest: Modus und Codebook laufen als hash-gebundene, provenienz-tragende Eingaben
durch den Privacy-Gate-Contract, und der Mensch gibt frei.

Darauf aufbauend gehört das Codebook als eigenes, versioniertes und gehashtes
Objekt dazu: hierarchische Codes mit Definitionen, Ankerbeispielen und Änderungs-
historie. Ein Codebook ist in qualitativer Forschung kein Beiwerk, sondern das
Instrument, an dem sich Konsistenz und intersubjektive Prüfbarkeit entscheiden;
DigQDAs Codebook-Eingabe ist der natürliche Andockpunkt dafür. Parallel dazu
gehört das Memoing — analytische Notizen, an Segmente und Codes gebunden. Memos
sind das Herz reflexiver Analyse (Grounded Theory lebt davon); technisch sind sie
nur ein weiteres gesiegeltes, quell-gebundenes Artefakt, das in die bestehende
Architektur passt.

Der zweite Schritt überträgt das Review-Gate von der Anonymisierung auf die
Kodierung: DigQDA-Ausgaben werden nicht angewandt, sondern als Vorschlagsliste
vorgelegt, die der Forschende annimmt, ablehnt oder umformuliert — mit genau der
Verweigerung von Auto-Apply, die den Datenschutzteil auszeichnet. Jeder
angenommene Code trägt seine Provenienz. Das ist die direkte Antwort auf den
größten Fallstrick maschinengestützter QDA, den Automatisierungs-Bias: Vorschlag
ist nicht Wahrheit.

Der dritte Schritt ist Mehrkodierung und Reliabilität. Ein zweiter Kodierer –
Mensch oder Modell – erlaubt Übereinstimmungsmaße (Cohen's Kappa,
Krippendorffs Alpha) und, wichtiger noch, das Sichtbarmachen von Dissens. Der
entscheidende Grundsatz: Ein Modell ist ein zweiter, fehlbarer Kodierer, dessen
Vorschläge auditierbar sind — nie der Schiedsrichter und nie die Ground Truth.
Dissens ist kein Fehler, sondern analytisch wertvoll; er zeigt, wo Interpretation
umstritten ist.

Eine methodische Warnung gehört hier fest verankert: Kappa/Alpha passen **nicht**
zu jedem qualitativen Paradigma. In der reflexiven thematischen Analyse (Braun &
Clarke) ist erzwungene Intercoder-Reliabilität epistemologisch eher unpassend —
dort ist die situierte Interpretation des Forschenden Teil der Analyse, nicht ein
Messfehler, den man wegmitteln müsste. Reliabilitätsmetriken sollten deshalb
immer an eine **deklarierte Analysemethode** gebunden sein: Codebook-getriebene,
eher post-positivistische Ansätze rechtfertigen Übereinstimmungsmaße; reflexive
oder konstruktivistische Ansätze verlangen stattdessen Transparenz über
Positionalität, Entscheidungswege und Dissens. Ein Werkzeug, das Metriken
unabhängig von der Methode aufzwingt, verfehlt die Methodik — das Werkzeug muss
die Methode kennen, bevor es misst.

Der vierte Schritt sind die Quergriffe: Segmente nach Codes abrufen, Code-Ko-
Okkurrenzen und Fall-mal-Code-Matrizen bilden, Muster über Fälle hinweg
erkennen. Das ist der Übergang vom deskriptiven zum axialen und selektiven
Kodieren bzw. zu den späteren Phasen der thematischen Analyse — jeweils als
gestützter, nie automatisierter Schritt.

## Leitplanken, damit Vertiefung nicht zur Verflachung wird

Vier Prinzipien halten die Methode zusammen. Interpretationshoheit bleibt beim
Menschen: das Modell schlägt vor, der Mensch entscheidet und zeichnet. Nachvoll-
ziehbarkeit vor Bequemlichkeit: jeder Code kennt sein Wer/Was/Wann/Welche-
Version. Fail-closed auch epistemisch: bei Unsicherheit markieren statt raten,
so wie es der DigQDA-Contract heute schon vormacht. Und Reflexivität als fester
Bestandteil: Memos, Positionalität, Entscheidungsprotokoll gehören ins Werkzeug,
nicht in ein separates Notizheft. Die saubere Trennung, die das Gateway zwischen
Rohdaten und PII zieht, sollte ihre Entsprechung in einer sauberen Trennung
zwischen Rohdaten und Interpretation finden.

## Anschlussfähigkeit statt Insellösung

Ein Gedanke zur Interoperabilität: Der REFI-QDA-Standard (QDPX) erlaubt den
Austausch kodierter Projekte zwischen MAXQDA, ATLAS.ti, NVivo und anderen. Eine
lokale, auditierbare QDA, die nach QDPX exportieren kann, wäre an das bestehende
Ökosystem anschlussfähig, statt ein weiteres geschlossenes Format zu erzeugen —
und sie könnte ihr Unterscheidungsmerkmal, die verifizierbare Provenienz, in
diese Welt hineintragen.

## Ehrliche Spannungen

Zum Schluss die Reibungspunkte, die man nicht wegdefinieren sollte. LLM-„Codes"
sind nicht per se methodisch fundierte Codes; sie brauchen menschliche
Verankerung, sonst entsteht Konstrukt-Scheinvalidität. Über-Standardisierung
kann die induktive Offenheit töten, die qualitative Forschung ausmacht — die
Balance zwischen strukturierter Prüfbarkeit und interpretativer Offenheit ist
selbst eine Design-Entscheidung. Lokale Modelle wie `gemma3:4b` sind in ihrer
Kodierqualität begrenzt; das Werkzeug sollte diese Grenze anzeigen (Unsicherheit
ausweisen), nicht kaschieren. Und der Automatisierungs-Bias bleibt die größte
Gefahr: Das beste Gegenmittel ist genau die Haltung, die dieses Projekt schon
hat — Vorschlag statt Anwendung, Mensch mit letzter Signatur, alles auditierbar.

Die Vertiefung Richtung QDA ist damit weniger ein Bruch als eine konsequente
Fortschreibung: dieselbe Demut, dieselbe Provenienz, dieselbe Mensch-in-der-
Schleife-Strenge, die den Datenschutz trägt, nun auch für die Interpretation.
