# Versionierte DOI über Zenodo (Anleitung / DRAFT)

Ziel: eine **Concept-DOI** (zeigt immer auf „das Projekt, alle Versionen") plus je
Release eine **versionierte DOI**. Genau der FAIR-Weg für Forschungssoftware.

## Voraussetzungen (vorher)

1. Öffentliches GitHub-Remote existiert (derzeit noch offen).
2. `LICENSE` gesetzt (siehe LICENSING.md — inkl. Rechteinhaber-Klärung).
3. `CITATION.cff` im Repo-Root (Template liegt bei).
4. Namensentscheidung getroffen + Kollisionsprüfung bestanden.

## Ablauf

1. Auf https://zenodo.org mit GitHub anmelden (ORCID-Login möglich).
2. Unter **Zenodo → Settings → GitHub** das Repo auf **On** schalten. Ab jetzt
   greift Zenodo jeden GitHub-**Release** ab.
3. Im Repo einen **Release** anlegen (Tag, z.B. `v0.2.0` — passend zur
   `library_version` im Run-Manifest).
4. Zenodo erzeugt automatisch:
   - eine **versionierte DOI** für genau diesen Release,
   - eine **Concept-DOI** (alle Versionen zusammen).
5. **Concept-DOI** zurück in `CITATION.cff` (Feld `doi:`) und als Badge in die
   README eintragen; committen (fließt in den nächsten Release ein).

## Kopplung an eure Versionierung

Damit ein Zitat reproduzierbar bleibt, sollte der Release-Tag mit den Werten im
**Run-Manifest** übereinstimmen (`library_version`) und der **Contract-/Schema-**
Stand mitdokumentiert sein (`contract_version`, `schema_sha256`). So verweist eine
DOI eindeutig auf einen prüfbaren Methoden- und Schema-Stand.

Reihenfolge insgesamt: Name → Lizenz(+Rechteinhaber) → `CITATION.cff` → Remote →
Release-Tag → Zenodo-DOI → DOI in `CITATION.cff` nachtragen.
