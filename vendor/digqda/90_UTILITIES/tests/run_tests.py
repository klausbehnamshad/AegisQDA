#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Reproduzierbare Tests. Deckt die Senior-Review-P0 ab, jeweils rot-zuerst-fähig:
zero evidence (P0-01), unbound (P0-02), mode-SM (P0-03), claim nicht überschreibbar
(P0-04), overlap-Locator (P0-05), malformed SRT fail-closed (P0-06).

Aufruf: python3 run_tests.py    (Deps: rapidfuzz, jsonschema)
"""

import hashlib
import json
import os
import subprocess
import sys
import tempfile

from jsonschema import Draft202012Validator

HERE = os.path.dirname(os.path.abspath(__file__))
UTIL = os.path.dirname(HERE)
ROOT = os.path.dirname(UTIL)
GEN = os.path.join(os.path.dirname(UTIL), "10_GENERIC")
FIX = os.path.join(HERE, "fixtures")
PY = sys.executable
sys.path.insert(0, UTIL)
import qda_run_p1 as R  # noqa: E402
import digqda_cli as D  # noqa: E402

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}  {detail}")


def run(cmd):
    return subprocess.run([PY] + cmd, capture_output=True, text=True)


def seg(*extra):
    return json.loads(run([os.path.join(UTIL, "qda_segment.py"), "--source"] + list(extra)).stdout)


def validate(jsonf, *extra):
    r = run([os.path.join(UTIL, "qda_validate.py"), "--source", os.path.join(FIX, "interview.srt"),
             "--json", os.path.join(FIX, jsonf)] + list(extra))
    res = json.loads(r.stdout.split("--- Manifest-Fragment ---")[-1])["result"]
    return res, r.returncode


srt = os.path.join(FIX, "interview.srt")
txt = os.path.join(FIX, "interview.txt")

print("T1  P0-Segmenter SRT")
d = seg(srt, "--max-gap-ms", "50")
check("SRT split -> 3 units", d["meta"]["n_units"] == 3, d["meta"])
check("unit_ids S01..S03", [u["unit_id"] for u in d["source_units"]] == ["S01", "S02", "S03"])
d1 = seg(srt)
check("Default merged -> 1 unit", d1["meta"]["n_units"] == 1)

print("T2  P0-Segmenter TXT")
t = seg(txt)
check("TXT -> 4 units", t["meta"]["n_units"] == 4)
check("S02 Sprecher B", t["source_units"][1]["explicit_speaker"] == "B")

print("T3  Validator bound_srt")
res, rc = validate("bound_srt.json")
check("1 EXACT / 1 FUZZY / 1 NOT_FOUND",
      (res["quotes_exact"], res["quotes_fuzzy"], res["quotes_not_found"]) == (1, 1, 1), res)
check("Verdict REVIEW_REQUIRED", res["verdict"] == "REVIEW_REQUIRED")
check("Exit 1", rc == 1)

print("T4  Schema-Vertrag")
schema = json.load(open(os.path.join(GEN, "p1_schema.json"), encoding="utf-8"))
v = Draft202012Validator(schema)


def val(fn):
    with open(os.path.join(FIX, fn), encoding="utf-8") as f:
        return not list(v.iter_errors(json.load(f)))


check("gutes Beispiel valide", val("p1_good.json"))
check("Extra-Feld abgelehnt", not val("p1_bad_extra.json"))
check("fehlendes required abgelehnt", not val("p1_bad_missing.json"))
check("unbekannter Enum abgelehnt", not val("p1_bad_enum.json"))
check("CODES_ASSIGNED + leere Liste abgelehnt", not val("p1_bad_empty_codes.json"))
check("NOTHING_CODABLE + Codes abgelehnt", not val("p1_bad_nothing_with_codes.json"))
check("leere source_quote abgelehnt", not val("p1_bad_emptystr.json"))

print("T5  Runner --dry-run OK + Provenance")
units_file = os.path.join(HERE, "_tmp_units.json")
json.dump(d1, open(units_file, "w", encoding="utf-8"), ensure_ascii=False)
schema_file = os.path.join(GEN, "p1_schema.json")


def run_p1(*extra):
    r = run([os.path.join(UTIL, "qda_run_p1.py"), "--units", units_file,
             "--schema", schema_file, "--dry-run"] + list(extra))
    return (json.loads(r.stdout)["_qda_run"] if r.stdout.strip() else None), r.returncode


def rendered_prompt_example(prompt):
    payload = prompt.split("Ausgabe:\n", 1)[1].lstrip()
    example, _ = json.JSONDecoder().raw_decode(payload)
    return example


m, rc = run_p1("--num-ctx", "8192")
check("DRY_RUN_OK", m["statuses"][0]["status"] == "DRY_RUN_OK")
check("Exit 0", rc == 0)
check("Manifest: contract/schema/prompt/library/claim + Hashes",
      all(k in m for k in ("contract_version", "contract_sha256", "schema_sha256",
                           "grammar_sha256", "prompt_sha256", "library_version",
                           "allowed_method_claim")))
check("Ollama-Ausgabelimit ist im Runtime-Manifest gebunden",
      m["runtime"]["num_predict"] == 2048)

print("T6  Runner fail-closed bei Budget")
m2, rc2 = run_p1("--num-ctx", "300", "--reserve-output-tokens", "100")
check("SKIPPED_OVER_BUDGET", m2["statuses"][0]["status"] == "SKIPPED_OVER_BUDGET")
check("Exit 1", rc2 == 1)

print("T7  Beispiele aus kanonischem Prompt-Bundle schema-valide & quellentreu")
prompt_bundle, _ = R.load_prompt()
prompt_examples = R.extract_prompt_examples(prompt_bundle)
ex_open = json.loads(prompt_examples["OPEN_EXAMPLE"])
ex_cb = json.loads(prompt_examples["CODEBOOK_EXAMPLE"])
check("EXAMPLE_OPEN valide", not list(v.iter_errors(ex_open)))
check("CODEBOOK-Beispieltemplate valide", not list(v.iter_errors(ex_cb)))
tmp_ex = os.path.join(HERE, "_tmp_example.json")
json.dump(ex_open, open(tmp_ex, "w", encoding="utf-8"), ensure_ascii=False)
rr = run([os.path.join(UTIL, "qda_validate.py"), "--source", srt, "--json", tmp_ex, "--document-mode"])
res7 = json.loads(rr.stdout.split("--- Manifest-Fragment ---")[-1])["result"]
check("beide Beispiel-Zitate EXACT (document-mode)", res7["quotes_exact"] == 2, res7)
os.remove(tmp_ex)
rendered_ex_cb = R.build_prompt(
    prompt_bundle,
    "",
    "STRICT_CODEBOOK",
    ["Gartenarbeit", "positive Bewertung"],
    {
        "Gartenarbeit": "beschreibt konkrete Tätigkeiten im Garten",
        "positive Bewertung": "eine Erfahrung wird positiv bewertet",
    },
    {"unit_id": "S01", "source_text": "Test"},
)
rendered_ex_obj = rendered_prompt_example(rendered_ex_cb)
check(
    "CODEBOOK-Beispiel demonstriert einen legalen Nichttreffer",
    rendered_ex_obj["coding_decision"] == "NO_CODE_FITS"
    and rendered_ex_obj["descriptive_codes"] == []
    and R.validate_mode(rendered_ex_obj, "STRICT_CODEBOOK",
                        ["Gartenarbeit", "positive Bewertung"]) is None,
    rendered_ex_obj,
)
check(
    "CODEBOOK-Nichttrefferquelle ist im gerenderten Beispiel sichtbar",
    "keine der gebundenen Codebuchdefinitionen erfuellt" in rendered_ex_cb
    and "__BOUND_CODEBOOK" not in rendered_ex_cb,
)

print("T8  Binding: Fehlbindung -> WRONG_UNIT (P0-02-Kern)")
res8, rc8 = validate("mis_attribution.json")
check("WRONG_UNIT erkannt", res8["quotes_wrong_unit"] == 1, res8)
check("kein faelschliches EXACT / nicht PASS", res8["quotes_exact"] == 0 and res8["verdict"] != "PASS")
check("Exit 1", rc8 == 1)

print("T9  FUZZY-only -> REVIEW")
res9, rc9 = validate("fuzzy_only.json")
check("Verdict REVIEW_REQUIRED", res9["verdict"] == "REVIEW_REQUIRED")
check("Exit 1", rc9 == 1)

print("T10  validate_mode (P0-03 volle Statemachine)")
allowed = {"Familienbindung"}
CD = "CODES_ASSIGNED"
ind = {"coding_decision": CD, "descriptive_codes": [{"code_label": "frei", "status": "INDUCTIVE_CANDIDATE"}]}
cb = {"coding_decision": CD, "descriptive_codes": [{"code_label": "Familienbindung", "status": "CODEBOOK_APPLIED"}]}
fremd = {"coding_decision": CD, "descriptive_codes": [{"code_label": "X", "status": "CODEBOOK_APPLIED"}]}
ncf = {"coding_decision": "NO_CODE_FITS", "descriptive_codes": []}
mix = {"coding_decision": CD, "descriptive_codes": [
    {"code_label": "Familienbindung", "status": "CODEBOOK_APPLIED"},
    {"code_label": "neu", "status": "INDUCTIVE_CANDIDATE"}]}
two_ind = {"coding_decision": CD, "descriptive_codes": [
    {"code_label": "a", "status": "INDUCTIVE_CANDIDATE"}, {"code_label": "b", "status": "INDUCTIVE_CANDIDATE"}]}
check("STRICT lehnt induktiv ab", R.validate_mode(ind, "STRICT_CODEBOOK", allowed) is not None)
check("STRICT akzeptiert Codebuch-Code", R.validate_mode(cb, "STRICT_CODEBOOK", allowed) is None)
check("STRICT lehnt Nicht-Codebuch-Label ab", R.validate_mode(fremd, "STRICT_CODEBOOK", allowed) is not None)
check("OPEN lehnt Codebuch-Status ab", R.validate_mode(cb, "OPEN_DESCRIPTIVE", None) is not None)
check("OPEN lehnt NO_CODE_FITS ab", R.validate_mode(ncf, "OPEN_DESCRIPTIVE", None) is not None)
check("CONSTRAINED lehnt Mischen ab", R.validate_mode(mix, "CONSTRAINED_EXTENSION", allowed) is not None)
check("CONSTRAINED lehnt >1 induktiv ab", R.validate_mode(two_ind, "CONSTRAINED_EXTENSION", allowed) is not None)

print("T11  grammar_schema fuer Ollama")
g = R.grammar_schema(schema)
gs = json.dumps(g)
check("kein allOf/if/then", not any(k in g for k in ("allOf", "if", "then")))
check("kein minLength/minItems", "minLength" not in gs and "minItems" not in gs)
check("enum/additionalProperties bleiben", '"enum"' in gs and "additionalProperties" in gs)
strict_g = R.grammar_schema_for_mode(schema, "STRICT_CODEBOOK", ["Beta", "Alpha"])
strict_branches = strict_g["oneOf"]
strict_decisions = [b["properties"]["coding_decision"]["const"] for b in strict_branches]
strict_code_branch = next(
    b for b in strict_branches
    if b["properties"]["coding_decision"]["const"] == "CODES_ASSIGNED"
)
strict_code_props = strict_code_branch["properties"]["descriptive_codes"]["items"]["properties"]
check("STRICT-Grammatik erlaubt nur gebundene Codebuchlabels",
      strict_code_props["code_label"]["enum"] == ["Beta", "Alpha"]
      and strict_code_props["status"]["enum"]
      == ["CODEBOOK_APPLIED", "CODEBOOK_AMBIGUOUS"])
check("STRICT-Grammatik koppelt Decision und Code-Anzahl",
      strict_decisions == ["CODES_ASSIGNED", "NO_CODE_FITS", "NOTHING_CODABLE"]
      and strict_code_branch["properties"]["descriptive_codes"]["minItems"] == 1
      and all(b["properties"]["descriptive_codes"].get("maxItems") == 0
              for b in strict_branches if b is not strict_code_branch))
open_g = R.grammar_schema_for_mode(schema, "OPEN_DESCRIPTIVE")
open_branches = open_g["oneOf"]
open_decisions = [b["properties"]["coding_decision"]["const"] for b in open_branches]
open_code_branch = open_branches[0]
open_props = open_code_branch["properties"]
check("OPEN-Grammatik schliesst Codebuchstatus und NO_CODE_FITS strukturell aus",
      open_decisions == ["CODES_ASSIGNED", "NOTHING_CODABLE"]
      and open_props["descriptive_codes"]["items"]["properties"]["status"]["enum"]
      == ["INDUCTIVE_CANDIDATE"]
      and open_code_branch["properties"]["descriptive_codes"]["minItems"] == 1
      and open_branches[1]["properties"]["descriptive_codes"]["maxItems"] == 0)

print("T12  Hash-Konsistenz")
_, _ = validate("bound_srt.json")
rman = run([os.path.join(UTIL, "qda_validate.py"), "--source", srt, "--json", os.path.join(FIX, "bound_srt.json")])
man = json.loads(rman.stdout.split("--- Manifest-Fragment ---")[-1])
check("Segmenter- = Validator-Hash", seg(srt)["meta"]["source_sha256"] == man["source_sha256"])

print("T13  P0-01 zero evidence")
res_e, rc_e = validate("p1_bad_empty_codes.json")
check("CODES_ASSIGNED+leer -> INVALID_INPUT", res_e["verdict"] == "INVALID_INPUT", res_e)
check("Exit 2", rc_e == 2)
res_n, rc_n = validate("nothing_codable.json")
check("gebundenes NOTHING_CODABLE -> NO_EVIDENCE (nicht PASS)", res_n["verdict"] == "NO_EVIDENCE", res_n)
check("Exit 1 (kein Schein-PASS)", rc_n == 1)

print("T14  P0-02 unbound evidence")
res_u, rc_u = validate("unbound.json")
check("Zitat UNBOUND (Range unaufloesbar)", res_u["quotes_unbound"] == 1, res_u)
check("Verdict REVIEW (kein PASS)", res_u["verdict"] == "REVIEW_REQUIRED")
check("Exit 1", rc_u == 1)
res_pg, rc_pg = validate("p1_good.json")
check("ungebundenes Modelloutput ohne source_range -> INVALID_INPUT", res_pg["verdict"] == "INVALID_INPUT", res_pg)
check("Exit 2", rc_pg == 2)

print("T18  Gap1 fremde Payload (fake_quote) erreicht NICHT PASS")
res_f, rc_f = validate("foreign_payload.json")
check("fremde Struktur -> INVALID_INPUT", res_f["verdict"] == "INVALID_INPUT", res_f)
check("Exit 2", rc_f == 2)

print("T19  Gap2 Platzhalter-Evidenz ist fail-closed")
res_p, rc_p = validate("placeholder_evidence.json")
check("'not stated' -> MISSING_EVIDENCE", res_p["quotes_missing_evidence"] == 1, res_p)
check("trotz eines EXACT kein PASS", res_p["verdict"] == "REVIEW_REQUIRED")
check("Exit 1", rc_p == 1)

print("T20  Gap4 Mehr-Cue-Fenster ist gueltige SPAN -> PASS")
res_s, rc_s = validate("span_window.json")
check("Verdict PASS", res_s["verdict"] == "PASS", res_s)
check("keine ungueltigen Locatoren", res_s["locators_invalid"] == 0, res_s)
check("Exit 0", rc_s == 0)

print("T21  Gap3 .srt mit kaputtem Pfeil -> fail-closed (kein TXT-Fallback)")
r_ba = run([os.path.join(UTIL, "qda_segment.py"), "--source", os.path.join(FIX, "bad_arrow.srt")])
check("Exit != 0", r_ba.returncode != 0, f"rc={r_ba.returncode}")
check("kein Output-JSON", r_ba.stdout.strip() == "")

print("T22  unbound NOTHING_CODABLE -> INVALID_INPUT (nicht NO_EVIDENCE)")
res_un, rc_un = validate("unbound_nothing_codable.json")
check("Verdict INVALID_INPUT", res_un["verdict"] == "INVALID_INPUT", res_un)
check("Exit 2", rc_un == 2)

print("T15  P0-05 blosse Overlap ist ungueltig")
res_o, rc_o = validate("overlap_locator.json")
check("Locator ungueltig gezaehlt", res_o["locators_invalid"] >= 1, res_o)
check("Verdict REVIEW (kein PASS trotz EXACT-Zitat)", res_o["verdict"] == "REVIEW_REQUIRED")
check("Exit 1", rc_o == 1)

print("T16  P0-04 Methodenclaim nicht ueberschreibbar")
check("Claim = Contract-Konstante", m["allowed_method_claim"] == "GENERIC_SOURCE_NEAR_CONTROLLED_QDA_CODING")
r_claim = run([os.path.join(UTIL, "qda_run_p1.py"), "--units", units_file, "--schema", schema_file,
               "--dry-run", "--method-claim", "GROUNDED_THEORY_METHOD_CLAIM"])
check("--method-claim wird abgewiesen (kein Override)", r_claim.returncode != 0)

print("T17  P0-06 malformed SRT fail-closed")
r_bad = run([os.path.join(UTIL, "qda_segment.py"), "--source", os.path.join(FIX, "malformed.srt")])
check("Abbruch mit Exit != 0", r_bad.returncode != 0, f"rc={r_bad.returncode}")
check("kein Output-JSON auf stdout", r_bad.stdout.strip() == "")

print("T23  Phase2/P1-02 P0-Envelope-Validierung (fail-closed)")
r_env = run([os.path.join(UTIL, "qda_run_p1.py"), "--units", os.path.join(FIX, "p0_bad_envelope.json"),
             "--schema", schema_file, "--dry-run"])
check("ungueltiges P0-Envelope -> Exit 2", r_env.returncode == 2, f"rc={r_env.returncode}")

print("T24  Phase2/P1-03 kanonische Promptquelle")
m24, rc24 = run_p1("--num-ctx", "8192")
check("Prompt kommt aus der Datei", m24["prompt_source"] == "file", m24.get("prompt_source"))
_ptxt = open(os.path.join(GEN, "p1_prompt.txt"), encoding="utf-8").read()
check("prompt_sha256 == Hash des vollstaendigen p1_prompt.txt-Bundles",
      m24["prompt_sha256"] == hashlib.sha256(_ptxt.encode()).hexdigest())
check("keine eingebetteten Prompt-/Beispiel-Fallbacks im Runner",
      not any(hasattr(R, name) for name in ("_FALLBACK_PROMPT", "EXAMPLE_OPEN", "EXAMPLE_CODEBOOK")))
rendered_open = R.build_prompt(_ptxt, "", "OPEN_DESCRIPTIVE", None, {},
                               {"unit_id": "S01", "source_text": "Text"})
rendered_cb = R.build_prompt(_ptxt, "", "STRICT_CODEBOOK", {"Familienbindung"},
                             {"Familienbindung": "Definition"},
                             {"unit_id": "S01", "source_text": "Text"})
check("Modus rendert genau sein Beispiel",
      rendered_prompt_example(rendered_open)["coding_decision"] == "CODES_ASSIGNED"
      and rendered_prompt_example(rendered_open)["descriptive_codes"][0]["status"]
      == "INDUCTIVE_CANDIDATE"
      and rendered_prompt_example(rendered_cb)["coding_decision"] == "NO_CODE_FITS"
      and rendered_prompt_example(rendered_cb)["descriptive_codes"] == [])
check("gerenderter Prompt enthaelt keine Contract-Marker", "[[" not in rendered_open and "[[" not in rendered_cb)

print("T25  Phase2 P0-Envelope ist zwingend ein schema-validiertes Objekt")
r_list = run([os.path.join(UTIL, "qda_run_p1.py"), "--units", os.path.join(FIX, "p0_list_input.json"),
              "--schema", schema_file, "--dry-run"])
check("Legacy-Listeninput -> Exit 2", r_list.returncode == 2, f"rc={r_list.returncode}")
check("Listeninput erzeugt kein Manifest", r_list.stdout.strip() == "")

print("T26  Fehlendes P0-Schema ist fail-closed")
_old_p0_schema = R.P0_SCHEMA_PATH
R.P0_SCHEMA_PATH = os.path.join(FIX, "does-not-exist.schema.json")
try:
    try:
        R.load_p0(units_file)
        missing_schema_closed = False
    except R.ContractInputError:
        missing_schema_closed = True
finally:
    R.P0_SCHEMA_PATH = _old_p0_schema
check("fehlendes verbindliches Schema -> ContractInputError", missing_schema_closed)

print("T27  Fehlende kanonische Promptquelle ist fail-closed")
_old_prompt_path = R.PROMPT_PATH
R.PROMPT_PATH = os.path.join(FIX, "does-not-exist.prompt.txt")
try:
    try:
        R.load_prompt()
        missing_prompt_closed = False
    except R.ContractInputError:
        missing_prompt_closed = True
finally:
    R.PROMPT_PATH = _old_prompt_path
check("fehlende Promptdatei -> ContractInputError", missing_prompt_closed)

print("T28  P0-Envelope-Konsistenz wird geprueft")
bad_consistency = json.loads(json.dumps(d1))
bad_consistency["meta"]["n_units"] += 1
tmp_bad_consistency = os.path.join(HERE, "_tmp_bad_consistency.json")
json.dump(bad_consistency, open(tmp_bad_consistency, "w", encoding="utf-8"), ensure_ascii=False)
try:
    try:
        R.load_p0(tmp_bad_consistency)
        consistency_closed = False
    except R.ContractInputError:
        consistency_closed = True
finally:
    os.remove(tmp_bad_consistency)
check("meta.n_units-Mismatch -> ContractInputError", consistency_closed)

print("T29  Phase2/P1-04 vollstaendige Provenance")
m29, _ = run_p1("--num-ctx", "8192")
check("Manifest traegt run_id", isinstance(m29.get("run_id"), str) and len(m29["run_id"]) >= 16)
exp_in = R.canonical_json_sha256(d1["source_units"][0])
check("Unit-Status hasht das vollstaendige kanonische Unit-Objekt",
      m29["statuses"][0].get("unit_input_sha256") == exp_in)
exp_prompt = R.build_prompt(_ptxt, "", "OPEN_DESCRIPTIVE", None, {}, d1["source_units"][0])
check("Unit-Status hasht den effektiv gerenderten Prompt",
      m29["statuses"][0].get("rendered_prompt_sha256") == R.sha256_text(exp_prompt))
m29_rq, _ = run_p1("--research-question", "Welche Erfahrung wird beschrieben?")
check("Forschungsfrage wird ohne Klartext im Manifest gebunden",
      m29_rq.get("research_question_sha256") == R.sha256_text("Welche Erfahrung wird beschrieben?"))
m29b, _ = run_p1("--mode", "CONSTRAINED_EXTENSION", "--codebook", os.path.join(FIX, "codebook.json"))
exp_cb = hashlib.sha256(open(os.path.join(FIX, "codebook.json"), "rb").read()).hexdigest()
check("Manifest traegt codebook_sha256", m29b.get("codebook_sha256") == exp_cb)
check("run_id ist pro Lauf eindeutig", m29["run_id"] != m29b["run_id"])
check("Dry-run ist explizit nicht als modellgebundener Lauf markiert",
      m29.get("provenance_level") == "DRY_RUN" and m29.get("model_digest") is None)
labels, definitions = R.parse_codebook('[{"code_label":"Beta"},{"code_label":"Alpha"}]')
check("Codebuch-Reihenfolge ist deterministisch an die Datei gebunden",
      labels == ["Beta", "Alpha"] and R.codebook_block(labels, definitions) == "Beta; Alpha")
check("quarantine_raw ohne Ziel -> None (kein implizites Persistieren)",
      R.quarantine_raw(None, m29["run_id"], "S01", "roh") is None)

print("T30  Quarantaene ist opt-in, pfadbegrenzt und integritaetsgebunden")
with tempfile.TemporaryDirectory(dir=HERE) as quarantine_dir:
    qref = R.quarantine_raw(quarantine_dir, m29["run_id"],
                            "../../escape", "sensible Rohantwort", "NOT_JSON")
    qpath = os.path.realpath(os.path.join(quarantine_dir, qref["ref"]))
    qroot = os.path.realpath(quarantine_dir)
    check("malicious unit_id bleibt innerhalb des Quarantaene-Roots",
          os.path.commonpath((qroot, qpath)) == qroot)
    check("Dateiname enthaelt keine unit_id/Pfadsegmente",
          "escape" not in os.path.basename(qpath) and ".." not in qref["ref"])
    qpayload = json.load(open(qpath, encoding="utf-8"))
    check("Quarantaene bindet Status, Unit und Raw-Hash",
          qpayload["status"] == "NOT_JSON"
          and qpayload["unit_id"] == "../../escape"
          and qpayload["raw_response_sha256"] == R.sha256_text("sensible Rohantwort")
          and qref["raw_response_sha256"] == qpayload["raw_response_sha256"])

print("T31  Echte Modelllaeufe brauchen einen konkreten Digest")
class FakeOllama:
    @staticmethod
    def list():
        return {"models": [{"model": "model:test", "digest": "sha256:abc123"}]}

    @staticmethod
    def show(_model):
        return {"details": {"quantization_level": "Q4_K_M"}}


quant, digest = R.resolve_model_provenance(FakeOllama, "model:test")
check("Modell-Digest und Quantisierung werden gebunden",
      digest == "sha256:abc123" and quant == "Q4_K_M")

class MissingDigestOllama:
    @staticmethod
    def list():
        return {"models": [{"model": "model:test", "digest": None}]}


try:
    R.resolve_model_provenance(MissingDigestOllama, "model:test")
    missing_digest_closed = False
except R.ContractInputError:
    missing_digest_closed = True
check("fehlender Modell-Digest ist fail-closed", missing_digest_closed)

print("T32  P0 unit_id ist ein pfadsicherer opaker Identifier")
bad_unit_id = json.loads(json.dumps(d1))
bad_unit_id["source_units"][0]["unit_id"] = "../../escape"
tmp_bad_unit_id = os.path.join(HERE, "_tmp_bad_unit_id.json")
json.dump(bad_unit_id, open(tmp_bad_unit_id, "w", encoding="utf-8"), ensure_ascii=False)
try:
    try:
        R.load_p0(tmp_bad_unit_id)
        unsafe_unit_closed = False
    except R.ContractInputError:
        unsafe_unit_closed = True
finally:
    os.remove(tmp_bad_unit_id)
check("unit_id mit Pfadsegmenten wird am Envelope abgewiesen", unsafe_unit_closed)

print("T33  Smoothe Pilotkante: ein Einstieg, isolierte Laeufe, harte Guards")
with tempfile.TemporaryDirectory() as pilot_root:
    pilot_source = os.path.join(UTIL, "smoke", "fixtures", "interview_demo.srt")
    pilot_cmd = [
        os.path.join(ROOT, "digqda"), "pilot", "CASE-CI", pilot_source,
        "--dry-run", "--synthetic", "--out-root", pilot_root,
    ]
    first = run(pilot_cmd)
    second = run(pilot_cmd)
    case_dir = os.path.join(pilot_root, "CASE-CI")
    run_dirs = sorted(os.path.join(case_dir, name) for name in os.listdir(case_dir))
    latest = run_dirs[-1]
    seg_pilot = json.load(open(os.path.join(latest, "segments.json"), encoding="utf-8"))
    coding_pilot = json.load(open(os.path.join(latest, "coding.json"), encoding="utf-8"))
    validation_pilot = json.load(open(os.path.join(latest, "validation.json"), encoding="utf-8"))
    report_pilot = open(os.path.join(latest, "validation.md"), encoding="utf-8").read()
    all_paths = [latest] + [os.path.join(latest, name) for name in os.listdir(latest)]
    check("root CLI dry-run ist als Plumbing erfolgreich", first.returncode == 0, first.stderr)
    check("wiederholter Fall erzeugt neuen Lauf statt Ueberschreiben",
          second.returncode == 0 and len(run_dirs) == 2, run_dirs)
    check("Quelle ist in P0 und Report nur opak benannt",
          seg_pilot["meta"]["source"] == "CASE-CI.srt"
          and "interview_demo" not in report_pilot)
    check("Laufartefakte sind owner-only",
          all((os.stat(path).st_mode & 0o077) == 0 for path in all_paths))
    check("Dry-run Gate prueft bewusst das vollstaendige Nicht-Ergebnis",
          D.evaluate_gate(
              seg_pilot, coding_pilot, validation_pilot,
              runner_exit=0, validator_exit=2,
              requested_model="gemma4:e4b", requested_mode="OPEN_DESCRIPTIVE",
              research_question="", codebook_bytes=None,
              dry_run=True,
          )[0])
    tampered = json.loads(json.dumps(coding_pilot))
    tampered["_qda_run"]["prompt_source"] = "embedded"
    check("manipulierte Prompt-Provenance sperrt das Gate",
          not D.evaluate_gate(
              seg_pilot, tampered, validation_pilot,
              runner_exit=0, validator_exit=2,
              requested_model="gemma4:e4b", requested_mode="OPEN_DESCRIPTIVE",
              research_question="", codebook_bytes=None,
              dry_run=True,
          )[0])

with tempfile.TemporaryDirectory() as guard_root:
    guard_source = os.path.join(UTIL, "smoke", "fixtures", "interview_demo.srt")
    no_synth = run([
        os.path.join(ROOT, "digqda"), "pilot", "CASE-GUARD", guard_source,
        "--dry-run", "--out-root", guard_root,
    ])
    bad_out = run([
        os.path.join(ROOT, "digqda"), "pilot", "CASE-GUARD", guard_source,
        "--dry-run", "--synthetic", "--out-root", os.path.join(ROOT, "pilot-output"),
    ])
    bad_id = run([
        os.path.join(ROOT, "digqda"), "pilot", "../CASE", guard_source,
        "--dry-run", "--synthetic", "--out-root", guard_root,
    ])
    cloud_out = run([
        os.path.join(ROOT, "digqda"), "pilot", "CASE-GUARD", guard_source,
        "--dry-run", "--synthetic", "--out-root", "/tmp/Dropbox/DigQDA-Pilot",
    ])
    check("Repo-Quelle braucht explizite synthetische Freigabe", no_synth.returncode == 2)
    check("Output im Git-Repo wird hart abgewiesen", bad_out.returncode == 2)
    check("Fall-ID mit Pfadsegmenten wird hart abgewiesen", bad_id.returncode == 2)
    check("Cloud-Sync-Pfad wird hart abgewiesen", cloud_out.returncode == 2)

print("T34  Prompt-Beispielquelle und Beispiel-JSON bleiben konsistent (Anti-Drift)")
_pt34, _ = R.load_prompt()
_open_ex34 = json.loads(R.extract_prompt_examples(_pt34)["OPEN_EXAMPLE"])
_rendered34 = R.build_prompt(_pt34, "", "OPEN_DESCRIPTIVE", None, {},
                             {"unit_id": "S01", "source_text": "Text"})
_src34 = _rendered34.split("text:", 1)[1].split("Ausgabe:", 1)[0]
check("OPEN: Beispiel-Quelltext deckt jedes Beispiel-Zitat (kein Quelle/JSON-Drift)",
      all(c["source_quote"] in _src34 for c in _open_ex34["descriptive_codes"]), _src34)

print("T35  Prompt-Entscheidungsgates gegen semantische Canary-Fehler")
_strict35 = R.build_prompt(
    _pt34, "", "STRICT_CODEBOOK", ["Gartenarbeit"],
    {"Gartenarbeit": "konkrete Taetigkeiten im Garten"},
    {"unit_id": "S01", "source_text": "Vom Fenster sieht man den Garten."},
)
_open35 = R.build_prompt(
    _pt34, "", "OPEN_DESCRIPTIVE", None, {},
    {"unit_id": "S01", "source_text": "Ist das Mikrofon an?"},
)
check("STRICT: vollstaendige Definition hat Vorrang vor Wortnaehe",
      "VOLLSTAENDIGE DEFINITION" in _strict35
      and "Ein Labelwort im Text ist kein Treffer" in _strict35
      and "NO_CODE_FITS" in _strict35)
check("STRICT: Grenzfall verlangt Ambiguitaet plus uncertainty",
      "CODEBOOK_AMBIGUOUS plus" in _strict35 and "uncertainty" in _strict35)
check("STRICT: inhaltlicher Nichttreffer ist nicht NOTHING_CODABLE",
      "NO_CODE_FITS und nicht" in _strict35
      and "NOTHING_CODABLE ist nur fuer Einheiten ohne" in _strict35)
check("OPEN: Technik-/Organisationsgespraech ist NOTHING_CODABLE",
      "Technik-/Organisationsgespraech" in _open35
      and '"coding_decision": "NOTHING_CODABLE"' in _open35
      and '"descriptive_codes": []' in _open35)

print("T36  Pilot-Rollen-Scope ist explizit und fail-closed")
_scope_input = {
    "meta": {"source_type": "srt", "source_sha256": "a" * 64, "n_units": 2},
    "source_units": [
        {"unit_id": "S01", "explicit_speaker": "I", "source_text": "Frage"},
        {"unit_id": "S02", "explicit_speaker": "B", "source_text": "Antwort"},
    ],
}
_scoped36, _excluded36 = D.apply_role_scope(
    _scope_input, {"I": "interviewer", "B": "interviewee"}, ["interviewee"]
)
check("nur eingeschlossene Rollen gehen an P1",
      [u["unit_id"] for u in _scoped36["source_units"]] == ["S02"]
      and _excluded36 == ["S01"])
check("Scope-Konfiguration ist gehasht und Unitzahl aktualisiert",
      _scoped36["meta"]["n_units"] == 1
      and len(_scoped36["meta"]["scope_sha256"]) == 64
      and set(_scoped36["meta"]["scope_sha256"]) <= set("0123456789abcdef"))
try:
    D.apply_role_scope(_scope_input, {"B": "interviewee"}, ["interviewee"])
except D.WorkflowError:
    _unknown36 = True
else:
    _unknown36 = False
check("unbekannte Sprecher werden nicht still eingeschlossen", _unknown36)

os.remove(units_file)
print(f"\n{'='*48}\n  {PASS} PASS  /  {FAIL} FAIL\n{'='*48}")
sys.exit(0 if FAIL == 0 else 1)
