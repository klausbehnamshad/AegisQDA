# AEGIS-2026-001: communication kit

Public plan and ready-to-use texts for announcing
[AEGIS-2026-001](AEGIS-2026-001.md). It applies the communication rules in
[`SECURITY.md`](../../SECURITY.md). Placeholders: `<RELEASE-URL>`,
`<ADVISORY-URL>` (the GitHub Security Advisory, or this repository's advisory
file until it exists) and `<VERSION-DOI>` (the Zenodo DOI of 0.1.1).

## Audiences

| Audience | What they need | Where they read |
|---|---|---|
| People who installed or evaluated AegisQDA | Am I affected, how do I check, what do I do | GitHub release and advisory, Zenodo, direct message |
| Data protection officers who reviewed a workflow with it | Scope, exposure, what was changed | Direct message with the advisory |
| DH and research software community | A factual note and a reusable lesson | Mailing lists, Fediverse/Bluesky, a blog post |
| Readers of work that cites AegisQDA | Which version is sound | Zenodo record, changelog |

Candidate channels: the GitHub release and security advisory, the Zenodo record,
the Humanist Discussion Group, the DHd association's mailing list and blog, the
de-RSE community, the DHd working group on research software engineering, and
data services for qualitative research data. Use the channels where the 0.1.0
release was announced first.

## Key messages

1. **What happened:** a detector bug let names that wrap across lines, sit in
   square brackets, or are split by rare Unicode line separators pass the
   privacy release unreviewed.
2. **Who is affected:** AegisQDA 0.1.x only accepts material declared synthetic.
   If you processed only synthetic material, no personal data was exposed.
3. **What to do:** update to 0.1.1 and run `aegisqda audit`; it tells you, run
   by run, whether anything needs action.
4. **What others can learn:** de-identification pipelines that filter or replace
   NER findings line by line can lose entities that cross a line break. Our
   synthetic test cases are reusable.

Do not write "anonymized", "no risk" or "fully fixed". Do not speculate about
real-data use or about who might have made a mistake. Name the version, the
check and the action.

## Sequence

| When | Step |
|---|---|
| Day 0 | Merge the fix, set the version to 0.1.1 (`pyproject.toml`, `src/aegisqda/__init__.py`, `CITATION.cff`, `.zenodo.json`), tag `v0.1.1`, publish the GitHub release |
| Day 0 | Publish the GitHub Security Advisory (text below); enable private vulnerability reporting |
| Day 0 | Check that Zenodo archived 0.1.1; add the note below to the 0.1.0 record |
| Day 0–1 | Direct messages to known users and data protection contacts |
| Day 1 | Mailing lists and short posts |
| Day 30 | Update the advisory with anything learned since; publish the lessons-learned post |
| Day 90 | Shorten the README notice to a link in the changelog |

## GitHub Security Advisory

- **Title:** Identifiers split by a line break or set in square brackets could pass the privacy release
- **Ecosystem / package:** other / aegisqda
- **Affected versions:** `<= 0.1.0`
- **Patched versions:** `0.1.1`
- **Severity:** moderate. The defect defeats the privacy release for common
  transcript layouts, but there is no remote attack path, and 0.1.x only accepts
  material declared synthetic.
- **Description:** the text of [AEGIS-2026-001](AEGIS-2026-001.md) from
  "Summary" to "What to do".

## GitHub release notes (0.1.1)

```markdown
**Privacy fix: please update.** This release fixes advisory AEGIS-2026-001: up
to 0.1.0, names that cross a line break (for example a name wrapped inside a
two-line SRT cue), values in square brackets and text split by rare Unicode line
separators could pass the privacy release unreviewed.

After updating, run `aegisqda audit <run-root>` to check existing runs. It is
read-only and prints no source text. Runs scanned with an affected version can
no longer be reviewed, transformed or analyzed; scan the source again.

AegisQDA 0.1.x only accepts material declared synthetic. If you processed only
synthetic material, no personal data was exposed.

Also in this release: one placeholder per mention across line breaks, adding a
missed detection by its exact text during review, clearer limits for very long
or BOM-prefixed sources, better detection of cloud-sync folders.

Details: <ADVISORY-URL> · Changelog: CHANGELOG.md
```

## Zenodo

**Description of 0.1.1:**

> Privacy fix release. Fixes advisory AEGIS-2026-001 (identifiers split by a
> line break, set in square brackets or separated by Unicode line separators
> could pass the privacy release in versions up to 0.1.0). Adds a read-only run
> audit. AegisQDA 0.1.x is a synthetic-only MVP. Advisory: <ADVISORY-URL>

**Note to add to the 0.1.0 record:**

> Superseded: this version is affected by privacy advisory AEGIS-2026-001. Use
> 0.1.1 or later (<VERSION-DOI>). Advisory: <ADVISORY-URL>

## Mailing list (English)

```text
Subject: AegisQDA 0.1.1: privacy fix for line-wrapped and bracketed names (AEGIS-2026-001)

AegisQDA is a local, fail-closed privacy gateway that prepares interview
transcripts (SRT/TXT) for qualitative analysis.

Up to version 0.1.0, its detector discarded names that cross a line break, such
as a name wrapped inside a two-line subtitle cue, as well as values in square
brackets and text split by rare Unicode line separators. These passages were
neither shown to the reviewer nor replaced, and were released in clear text.

Who is affected: AegisQDA 0.1.x only accepts material declared synthetic. If
you processed only synthetic material, no personal data was exposed.

What to do: update to 0.1.1 and run `aegisqda audit <run-root>`. It reads your
existing runs, prints no source text, and tells you for each run whether
anything needs action.

For anyone building de-identification pipelines: if your tool runs NER over a
whole transcript but filters or replaces findings line by line, check whether
entities that cross a line break survive. Our synthetic test cases are in the
repository.

Advisory: <ADVISORY-URL>
Release: <RELEASE-URL>
```

## Mailingliste (Deutsch)

```text
Betreff: AegisQDA 0.1.1: Datenschutz-Fix für umbrochene und eingeklammerte Namen (AEGIS-2026-001)

AegisQDA ist ein lokales Werkzeug, das Interviewtranskripte (SRT/TXT) vor der
qualitativen Analyse pseudonymisiert und im Zweifel blockiert.

Bis einschließlich Version 0.1.0 hat der Detektor Namen verworfen, die über
einen Zeilenumbruch gehen, etwa wenn ein Name in einem zweizeiligen Untertitel
umbricht, außerdem Werte in eckigen Klammern und Text, der durch seltene
Unicode-Zeilentrenner getrennt ist. Diese Stellen wurden weder zur Prüfung
angezeigt noch ersetzt und im Klartext freigegeben.

Wer ist betroffen? AegisQDA 0.1.x verarbeitet nur Material, das als
synthetisch deklariert ist. Wer nur synthetisches Material verarbeitet hat, hat
keine personenbezogenen Daten offengelegt.

Was tun? Auf 0.1.1 aktualisieren und `aegisqda audit <Lauf-Verzeichnis>`
ausführen. Der Befehl liest die vorhandenen Läufe, gibt keinen Quelltext aus und
sagt für jeden Lauf, ob etwas zu tun ist.

Für alle, die selbst Pseudonymisierungs-Pipelines bauen: Wenn euer Werkzeug
Named-Entity-Recognition über das ganze Transkript laufen lässt, die Treffer
aber zeilenweise filtert oder ersetzt, prüft, ob Namen über einen Zeilenumbruch
hinweg erhalten bleiben. Unsere synthetischen Testfälle liegen im Repository.

Advisory: <ADVISORY-URL>
Release: <RELEASE-URL>
```

## Short posts

**English (Bluesky, under 300 characters with link):**

> AegisQDA 0.1.1 fixes a privacy bug: names wrapped across a subtitle line
> break or set in [brackets] could pass the release. Synthetic-only use exposed
> no personal data. Update, then run `aegisqda audit`. <ADVISORY-URL>

**Deutsch (Mastodon):**

> AegisQDA 0.1.1 behebt einen Datenschutzfehler: Bis 0.1.0 konnten Namen, die in
> einem Untertitel über einen Zeilenumbruch gehen oder in [eckigen Klammern]
> stehen, ungeprüft freigegeben werden. Wer nur synthetisches Material genutzt
> hat, hat keine personenbezogenen Daten offengelegt. Bitte aktualisieren und
> `aegisqda audit` ausführen. Für alle mit eigener Pseudonymisierung:
> Zeilenumbrüche testen! <ADVISORY-URL> #DigitalHumanities #RSE #DSGVO

## Direct message to users and data protection contacts (Deutsch)

```text
Betreff: AegisQDA: Datenschutz-Advisory AEGIS-2026-001 und Update 0.1.1

Guten Tag,

Sie haben AegisQDA eingesetzt oder geprüft. Ich möchte Sie direkt über einen
Fehler informieren, den wir behoben haben.

Bis einschließlich Version 0.1.0 konnten Namen, die über einen Zeilenumbruch
gehen, Werte in eckigen Klammern und Text mit seltenen Unicode-Zeilentrennern
ungeprüft in die Freigabe gelangen. Version 0.1.1 behebt das; frühere Läufe
werden gesperrt, und `aegisqda audit` zeigt, welche Läufe betroffen sind.

AegisQDA 0.1.x verarbeitet nur als synthetisch deklariertes Material. Falls in
Ihrem Umfeld dennoch echte Daten verarbeitet wurden, behandeln Sie bitte alle
Freigaben einer betroffenen Version als nicht pseudonymisiert und sprechen Sie
mich gern an; ich unterstütze bei der Prüfung.

Details: <ADVISORY-URL>

Mit freundlichen Grüßen
```

## FAQ

**Was the tool "not anonymous" before?** AegisQDA never claimed anonymity. Its
strongest statement is a process release under a defined policy after automatic
checks and human sign-off. This defect meant that the automatic part missed
three patterns, and the human reviewer was not shown them.

**Do I have to notify anyone?** Not if you processed only synthetic material,
which is all 0.1.x accepts. If real data was processed, involve your data
protection officer; the advisory and the audit output (which contains no source
text) are designed to be shared with them.

**Why are my old runs blocked?** Their detection was made by an affected
recognizer pack. Continuing them would carry the defect forward, so they stop
with a message naming the advisory. Scan the source again.

**Does the fix change my results?** A name that wraps across lines now gets one
placeholder on its first line, the same as the name elsewhere in the document.
Released text from 0.1.1 can therefore differ from 0.1.0 output for the same
source.

## Lessons-learned post (outline, Day 30)

1. The pattern: NER over the full text, filtering or replacement per line.
2. Why subtitle and transcript formats make it common: cue wrapping, hard
   wrapping, OCR line breaks.
3. Why a second scan did not help: it used the same detector, so it confirmed
   the blind spot.
4. What we changed: split spans instead of dropping them, one placeholder per
   mention, revoked detector versions in code, a read-only audit.
5. A small synthetic test set others can run against their own tool.
