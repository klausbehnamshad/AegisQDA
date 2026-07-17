#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
QDA P1 RUNNER (v0.4, DRAFT) -- Referenzimplementierung der P1-Kante.

Phase-2-Increment 1+2 zusaetzlich zu den Trust-Boundary-Fixes:
- P1-02: Das P0-Envelope wird beim Laden gegen schemas/p0_units.schema.json
  validiert (jsonschema); ungueltiges Envelope -> fail-closed, kein AttributeError.
- P1-03: EINE kanonische Promptquelle. Der Prompt wird aus 10_GENERIC/p1_prompt.txt
  geladen; Template und Modusbeispiele liegen gemeinsam in dieser Datei und werden
  als ein Bundle gehasht. Fehlt die Datei oder ist das Bundle unvollstaendig, wird
  fail-closed abgebrochen.
- P1-04 (Increment 3): Provenance. Jeder Lauf traegt run_id, pro Unit Hashes des
  vollstaendigen Inputobjekts und des effektiv gerenderten Prompts, Forschungsfrage-
  und Codebuch-Hash sowie bei echten Laeufen einen verpflichtenden Modell-Digest.
  Ungueltige Rohantworten koennen opt-in pfadbegrenzt und integritaetsgebunden in
  eine Quarantaene geschrieben werden (--quarantine-dir).

Weiterhin: Modus-Statemachine (validate_mode), Methodenclaim aus Contract (nicht
per CLI), fail-closed, atomare Writes, grammatiktaugliches Ollama-Schema.

Deps: pip install ollama jsonschema   ·   --dry-run baut/prueft ohne Ollama.
"""

import argparse
import copy
import hashlib
import json
import math
import os
import re
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from importlib import metadata

try:
    from jsonschema import Draft202012Validator
    from jsonschema.exceptions import SchemaError
except ImportError:
    sys.stderr.write("FEHLER: jsonschema fehlt -> pip install jsonschema\n")
    sys.exit(2)

LIBRARY_VERSION = "0.4"
CONTRACT_VERSION = "0.1"
PROMPT_ID = "QDA-GEN-DESCRIPTIVE-CODING"
PROMPT_VERSION = "1.2"
ALLOWED_METHOD_CLAIM = {"QDA-GEN-DESCRIPTIVE-CODING": "GENERIC_SOURCE_NEAR_CONTROLLED_QDA_CODING"}

_HERE = os.path.dirname(os.path.abspath(__file__))
PROMPT_PATH = os.path.join(_HERE, "..", "10_GENERIC", "p1_prompt.txt")
P0_SCHEMA_PATH = os.path.join(_HERE, "..", "schemas", "p0_units.schema.json")

PROMPT_PLACEHOLDERS = (
    "[[RESEARCH_QUESTION]]", "[[CODING_MODE]]", "[[CODEBOOK]]",
    "[[EXAMPLE_SOURCE]]", "[[UNIT_ID]]", "[[UNIT_TEXT]]",
)
PROMPT_EXAMPLE_TAGS = ("OPEN_EXAMPLE", "CODEBOOK_EXAMPLE")
PROMPT_BLOCK_RE = re.compile(
    r"\[\[(OPEN_EXAMPLE|CODEBOOK_EXAMPLE)\]\](.*?)\[\[/\1\]\]", re.DOTALL
)


class ContractInputError(ValueError):
    """Deterministischer Fehler an einer lokalen Contract-/Input-Grenze."""


def extract_prompt_examples(template):
    return {match.group(1): match.group(2).strip()
            for match in PROMPT_BLOCK_RE.finditer(template)}


def validate_prompt_bundle(template):
    if not template.strip():
        raise ContractInputError("p1_prompt.txt ist leer")
    for placeholder in PROMPT_PLACEHOLDERS:
        if template.count(placeholder) != 1:
            raise ContractInputError(
                f"p1_prompt.txt braucht genau einmal {placeholder}"
            )
    examples = extract_prompt_examples(template)
    for tag in PROMPT_EXAMPLE_TAGS:
        if template.count(f"[[{tag}]]") != 1 or template.count(f"[[/{tag}]]") != 1:
            raise ContractInputError(
                f"p1_prompt.txt braucht genau einen vollstaendigen {tag}-Block"
            )
        try:
            example = json.loads(examples.get(tag, ""))
        except json.JSONDecodeError as exc:
            raise ContractInputError(
                f"{tag} in p1_prompt.txt ist kein gueltiges JSON: {exc}"
            ) from exc
        if not isinstance(example, dict):
            raise ContractInputError(f"{tag} in p1_prompt.txt muss ein JSON-Objekt sein")
    return examples


def load_prompt():
    try:
        with open(PROMPT_PATH, encoding="utf-8") as f:
            template = f.read()
    except OSError as exc:
        raise ContractInputError(
            f"kanonische Promptquelle nicht lesbar: {PROMPT_PATH}: {exc}"
        ) from exc
    validate_prompt_bundle(template)
    return template, "file"


def atomic_write(path, text):
    d = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def sha256_text(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def canonical_json_sha256(value):
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":"))
    return sha256_text(canonical)


def quarantine_raw(quarantine_dir, run_id, unit_id, raw, status="INVALID_RESPONSE"):
    """Persistiert eine ungueltige Rohantwort opt-in und pfadbegrenzt.

    Dateinamen werden ausschliesslich aus Hashes abgeleitet; weder run_id noch
    unit_id koennen den Zielpfad beeinflussen. Rueckgabe ist eine relative,
    nicht-sensitive Referenz plus Hash der Rohantwort.
    """
    if not quarantine_dir or raw is None:
        return None
    if not isinstance(raw, str):
        raise ContractInputError("Quarantaene-Rohantwort muss Text sein")
    try:
        os.makedirs(quarantine_dir, mode=0o700, exist_ok=True)
        root = os.path.realpath(os.path.abspath(quarantine_dir))
        run_component = "run-" + sha256_text(str(run_id))[:32]
        run_dir = os.path.join(root, run_component)
        os.makedirs(run_dir, mode=0o700, exist_ok=True)
        run_dir = os.path.realpath(run_dir)
        if os.path.commonpath((root, run_dir)) != root:
            raise ContractInputError("Quarantaene-Runordner liegt ausserhalb des Zielroots")
        unit_component = "unit-" + sha256_text(str(unit_id)) + ".json"
        path = os.path.realpath(os.path.join(run_dir, unit_component))
        if os.path.commonpath((root, path)) != root:
            raise ContractInputError("Quarantaene-Datei liegt ausserhalb des Zielroots")
        raw_sha = sha256_text(raw)
        payload = {
            "run_id": run_id,
            "unit_id": unit_id,
            "status": status,
            "raw_response_sha256": raw_sha,
            "raw_response": raw,
        }
        atomic_write(path, json.dumps(payload, ensure_ascii=False, indent=2))
    except OSError as exc:
        raise ContractInputError(f"Quarantaene konnte nicht geschrieben werden: {exc}") from exc
    return {"ref": os.path.relpath(path, root), "raw_response_sha256": raw_sha}


def codebook_block(allowed_labels, defs):
    if not allowed_labels:
        return "NICHT_VERWENDET (OPEN_DESCRIPTIVE)"
    return "; ".join(
        f"{label} = {defs.get(label, '')}".strip(" =")
        for label in allowed_labels
    )


def build_prompt(template, rq, mode, allowed_labels, defs, unit):
    selected = "OPEN_EXAMPLE" if mode == "OPEN_DESCRIPTIVE" else "CODEBOOK_EXAMPLE"
    if selected == "CODEBOOK_EXAMPLE":
        if not allowed_labels:
            raise ContractInputError(f"Modus {mode} braucht ein nicht-leeres Codebuch")
        example_source = (
            "Diese Aussage beschreibt einen anderen Sachverhalt, der keine der "
            "gebundenen Codebuchdefinitionen erfuellt."
        )
    else:
        example_source = (
            "Meine Vasen sind am Ende richtig schön geworden, das hat mich sehr gefreut."
        )

    def render_example(match):
        if match.group(1) != selected:
            return ""
        raw_example = match.group(2).strip()
        return raw_example

    prompt = PROMPT_BLOCK_RE.sub(render_example, template)
    prompt = (prompt
              .replace("[[RESEARCH_QUESTION]]", rq or "explorative Analyse")
              .replace("[[CODING_MODE]]", mode)
              .replace("[[CODEBOOK]]", codebook_block(allowed_labels, defs))
              .replace("[[EXAMPLE_SOURCE]]",
                       json.dumps(example_source, ensure_ascii=False))
              .replace("[[UNIT_ID]]", str(unit.get("unit_id", "?")))
              .replace("[[UNIT_TEXT]]", unit.get("source_text", "")))
    unresolved = sorted(set(re.findall(r"\[\[[A-Z_/]+\]\]", prompt)))
    if unresolved:
        raise ContractInputError(
            "nicht aufgeloeste Promptmarker: " + ", ".join(unresolved)
        )
    return prompt


def validate_mode(obj, mode, allowed_labels):
    dec = obj.get("coding_decision")
    codes = obj.get("descriptive_codes", [])
    statuses = [c.get("status") for c in codes]
    labels = [c.get("code_label") for c in codes]
    n_ind = statuses.count("INDUCTIVE_CANDIDATE")
    n_cb = sum(1 for s in statuses if s in ("CODEBOOK_APPLIED", "CODEBOOK_AMBIGUOUS"))
    if dec == "CODES_ASSIGNED" and not codes:
        return "CODES_ASSIGNED aber keine Codes"
    if dec in ("NO_CODE_FITS", "NOTHING_CODABLE") and codes:
        return f"{dec} aber Codes vorhanden"
    if mode == "OPEN_DESCRIPTIVE":
        if dec == "NO_CODE_FITS":
            return "OPEN: NO_CODE_FITS ist ein Codebuch-Konzept, hier unzulaessig"
        for s in statuses:
            if s != "INDUCTIVE_CANDIDATE":
                return f"OPEN: Status '{s}' ohne Codebuch unzulaessig"
    elif mode == "STRICT_CODEBOOK":
        for status, label in zip(statuses, labels):
            if status == "INDUCTIVE_CANDIDATE":
                return f"STRICT: induktiver Code '{label}' unzulaessig"
            if allowed_labels is not None and label not in allowed_labels:
                return f"STRICT: Code '{label}' nicht im Codebuch"
    elif mode == "CONSTRAINED_EXTENSION":
        if dec == "NO_CODE_FITS":
            return "CONSTRAINED: statt NO_CODE_FITS einen INDUCTIVE_CANDIDATE bilden"
        for status, label in zip(statuses, labels):
            if status in ("CODEBOOK_APPLIED", "CODEBOOK_AMBIGUOUS") \
                    and allowed_labels is not None and label not in allowed_labels:
                return f"CONSTRAINED: Codebuch-Code '{label}' nicht im Codebuch"
        if n_cb > 0 and n_ind > 0:
            return "CONSTRAINED: kein Mischen von Codebuch-Code und induktivem Code"
        if n_ind > 1:
            return f"CONSTRAINED: mehr als ein induktiver Code ({n_ind})"
    return None


def grammar_schema(schema):
    drop = {"minLength", "maxLength", "minItems", "maxItems", "allOf", "if",
            "then", "else", "$schema", "title"}
    if isinstance(schema, dict):
        return {k: grammar_schema(v) for k, v in schema.items() if k not in drop}
    if isinstance(schema, list):
        return [grammar_schema(x) for x in schema]
    return schema


def grammar_schema_for_mode(schema, mode, allowed_labels=None):
    """Verengt die Backend-Grammatik auf maschinell erzwingbare Modusregeln.

    Der volle, unveraenderte Vertrag wird nach der Modellantwort weiterhin mit
    jsonschema und validate_mode geprueft. Diese Ableitung verhindert lediglich,
    dass Ollama in OPEN unzulaessige Statuswerte bzw. in STRICT fremde
    Codebuchlabels ueberhaupt erzeugt.
    """
    grammar = grammar_schema(schema)
    properties = grammar["properties"]
    code_properties = properties["descriptive_codes"]["items"]["properties"]
    decision_schema = properties["coding_decision"]
    status_schema = code_properties["status"]

    if mode == "OPEN_DESCRIPTIVE":
        decision_schema["enum"] = ["CODES_ASSIGNED", "NOTHING_CODABLE"]
        status_schema["enum"] = ["INDUCTIVE_CANDIDATE"]
    elif mode == "STRICT_CODEBOOK":
        if not allowed_labels:
            raise ContractInputError("STRICT-Backend-Grammatik braucht Codebuchlabels")
        code_properties["code_label"]["enum"] = list(allowed_labels)
        status_schema["enum"] = ["CODEBOOK_APPLIED", "CODEBOOK_AMBIGUOUS"]
    elif mode == "CONSTRAINED_EXTENSION":
        decision_schema["enum"] = ["CODES_ASSIGNED", "NOTHING_CODABLE"]

    def decision_branch(decision, *, codes_required):
        branch = copy.deepcopy(grammar)
        branch_props = branch["properties"]
        branch_props["coding_decision"] = {"const": decision}
        codes_schema = branch_props["descriptive_codes"]
        if codes_required:
            codes_schema["minItems"] = 1
        else:
            codes_schema["maxItems"] = 0
        return branch

    decisions = ["CODES_ASSIGNED", "NOTHING_CODABLE"]
    if mode == "STRICT_CODEBOOK":
        decisions.insert(1, "NO_CODE_FITS")
    return {
        "oneOf": [
            decision_branch(decision, codes_required=decision == "CODES_ASSIGNED")
            for decision in decisions
        ]
    }


def bind_p0_fields(unit, model_obj):
    src_range = unit.get("source_range", "locator unavailable")
    codes = [{**c, "quote_locator": src_range} for c in model_obj.get("descriptive_codes", [])]
    return {"unit_id": unit.get("unit_id"), "source_type": unit.get("source_type"),
            "source_range": src_range, "explicit_speaker": unit.get("explicit_speaker", "not stated"),
            "concise_description": model_obj.get("concise_description"),
            "narrative_function": model_obj.get("narrative_function"),
            "coding_decision": model_obj.get("coding_decision"),
            "descriptive_codes": codes, "uncertainty": model_obj.get("uncertainty", [])}


def parse_codebook(raw):
    """Parst genau die gehashten Codebuchbytes in stabiler Dateireihenfolge."""
    try:
        cb = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ContractInputError(f"--codebook ist kein gueltiges JSON: {exc}") from exc
    if not isinstance(cb, list):
        raise ContractInputError("--codebook muss eine JSON-Liste sein")
    labels, defs, seen = [], {}, set()
    for pos, item in enumerate(cb, 1):
        if isinstance(item, str):
            label, definition = item, ""
        elif isinstance(item, dict):
            label, definition = item.get("code_label"), item.get("definition", "")
        else:
            raise ContractInputError(f"Codebuch-Eintrag {pos} ist weder String noch Objekt")
        if not isinstance(label, str) or not label.strip():
            raise ContractInputError(f"Codebuch-Eintrag {pos} hat kein nicht-leeres code_label")
        if not isinstance(definition, str):
            raise ContractInputError(f"Codebuch-Definition fuer '{label}' muss Text sein")
        if label in seen:
            raise ContractInputError(f"Codebuch enthaelt doppeltes Label '{label}'")
        seen.add(label)
        labels.append(label)
        defs[label] = definition
    return labels, defs


def resolve_model_provenance(ollama_module, model):
    """Bindet einen echten Lauf zwingend an den lokalen Modell-Digest."""
    try:
        models = ollama_module.list().get("models", [])
    except Exception as exc:  # Backendfehler werden an der Contract-Grenze vereinheitlicht
        raise ContractInputError(f"Ollama-Modellliste nicht lesbar: {exc}") from exc
    match = next((entry for entry in models
                  if entry.get("model") == model or entry.get("name") == model), None)
    digest = match.get("digest") if match is not None else None
    if not isinstance(digest, str) or not digest.strip():
        raise ContractInputError(
            f"Modell '{model}' ist nicht mit einem konkreten Ollama-Digest aufloesbar"
        )
    quantization = None
    try:
        details = ollama_module.show(model).get("details") or {}
        quantization = details.get("quantization_level")
    except Exception:  # Quantisierung ist Zusatzinfo; der Digest bleibt bindend.
        quantization = None
    return quantization, digest


def load_p0(path):
    """Laedt + validiert das P0-Envelope (fail-closed). Rueckgabe: (units, p0_meta)."""
    try:
        with open(path, encoding="utf-8") as f:
            p0 = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractInputError(f"P0-Envelope nicht lesbar/kein JSON: {exc}") from exc
    if not isinstance(p0, dict):
        raise ContractInputError(
            "P0-Input muss das versionierte Objekt-Envelope mit meta und source_units sein"
        )
    try:
        with open(P0_SCHEMA_PATH, encoding="utf-8") as f:
            p0_schema = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractInputError(
            f"verbindliches P0-Schema nicht lesbar/ungueltig: {P0_SCHEMA_PATH}: {exc}"
        ) from exc
    try:
        Draft202012Validator.check_schema(p0_schema)
    except SchemaError as exc:
        raise ContractInputError(f"p0_units.schema.json ist selbst ungueltig: {exc}") from exc
    errs = sorted(Draft202012Validator(p0_schema).iter_errors(p0),
                  key=lambda e: list(e.path))
    if errs:
        detail = "; ".join(e.message for e in errs[:5])
        raise ContractInputError(
            f"P0-Envelope verletzt p0_units.schema.json: {detail}"
        )

    units, meta = p0["source_units"], p0["meta"]
    if meta["n_units"] != len(units):
        raise ContractInputError(
            f"P0 meta.n_units={meta['n_units']} stimmt nicht mit source_units={len(units)} ueberein"
        )
    unit_ids = [unit["unit_id"] for unit in units]
    if len(unit_ids) != len(set(unit_ids)):
        raise ContractInputError("P0 source_units enthalten doppelte unit_id")
    if any(unit["source_type"] != meta["source_type"] for unit in units):
        raise ContractInputError("P0 source_type ist zwischen meta und source_units inkonsistent")
    return units, meta


def main():
    ap = argparse.ArgumentParser(description="QDA P1 Runner (fail-closed).")
    ap.add_argument("--units", required=True)
    ap.add_argument("--schema", required=True)
    ap.add_argument("--model", default="gemma4:e4b")
    ap.add_argument("--mode", default="OPEN_DESCRIPTIVE",
                    choices=["OPEN_DESCRIPTIVE", "CONSTRAINED_EXTENSION", "STRICT_CODEBOOK"])
    ap.add_argument("--research-question", default="")
    ap.add_argument("--codebook")
    ap.add_argument("--num-ctx", type=int, default=8192)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--top-p", type=float, default=0.9)
    ap.add_argument("--out")
    ap.add_argument("--max-codebook-chars", type=int, default=4000)
    ap.add_argument("--token-ratio", type=float, default=3.2)
    ap.add_argument(
        "--reserve-output-tokens", type=int, default=2048,
        help="Kontextreserve und harte Ollama-num_predict-Grenze (Default 2048)",
    )
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--quarantine-dir",
                    help="Opt-in: Zielordner fuer ungueltige Rohantworten (sonst nicht persistiert).")
    args = ap.parse_args()
    run_id = uuid.uuid4().hex

    claim = ALLOWED_METHOD_CLAIM[PROMPT_ID]
    try:
        units, p0_meta = load_p0(args.units)
        template, prompt_source = load_prompt()
    except ContractInputError as exc:
        sys.stderr.write(f"ABBRUCH: {exc}\n")
        sys.exit(2)
    if not units or not all(isinstance(u, dict) and u.get("source_text") for u in units):
        sys.stderr.write("ABBRUCH: P0-Units fehlen oder haben keinen source_text.\n")
        sys.exit(2)

    with open(args.schema, encoding="utf-8") as f:
        full_schema = json.load(f)

    allowed_labels, defs, codebook_sha = None, {}, None
    if args.codebook:
        try:
            with open(args.codebook, "rb") as f:
                raw_bytes = f.read()
            raw = raw_bytes.decode("utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            sys.stderr.write(f"ABBRUCH: --codebook nicht als UTF-8 lesbar: {exc}\n")
            sys.exit(2)
        if len(raw) > args.max_codebook_chars:
            sys.stderr.write(f"ABBRUCH: Codebuch zu gross ({len(raw)}).\n")
            sys.exit(2)
        codebook_sha = hashlib.sha256(raw_bytes).hexdigest()
        try:
            allowed_labels, defs = parse_codebook(raw)
        except ContractInputError as exc:
            sys.stderr.write(f"ABBRUCH: {exc}\n")
            sys.exit(2)
    if args.mode in ("STRICT_CODEBOOK", "CONSTRAINED_EXTENSION") and not allowed_labels:
        sys.stderr.write(f"ABBRUCH: Modus {args.mode} braucht --codebook (JSON).\n")
        sys.exit(2)

    try:
        grammar = grammar_schema_for_mode(full_schema, args.mode, allowed_labels)
    except ContractInputError as exc:
        sys.stderr.write(f"ABBRUCH: {exc}\n")
        sys.exit(2)
    grammar_sha = canonical_json_sha256(grammar)

    schema_sha = hashlib.sha256(json.dumps(full_schema, sort_keys=True).encode()).hexdigest()
    prompt_sha = hashlib.sha256(template.encode()).hexdigest()
    effective_research_question = args.research_question or "explorative Analyse"
    research_question_sha = sha256_text(effective_research_question)
    contract_sha = hashlib.sha256(json.dumps(
        {"prompt_id": PROMPT_ID, "prompt_version": PROMPT_VERSION,
         "schema_sha256": schema_sha, "prompt_sha256": prompt_sha,
         "method_claim": claim}, sort_keys=True).encode()).hexdigest()

    budget = args.num_ctx - args.reserve_output_tokens
    results, statuses = [], []
    validator = Draft202012Validator(full_schema)
    chat = None
    model_quant = model_digest = None
    try:
        backend_client_version = metadata.version("ollama")
    except metadata.PackageNotFoundError:
        backend_client_version = None
    if not args.dry_run:
        try:
            import ollama
            chat = ollama.chat
            try:
                model_quant, model_digest = resolve_model_provenance(ollama, args.model)
            except ContractInputError as exc:
                sys.stderr.write(f"ABBRUCH: {exc}\n")
                sys.exit(2)
        except ImportError:
            sys.stderr.write("FEHLER: ollama fehlt.\n")
            sys.exit(2)

    for unit in units:
        try:
            prompt = build_prompt(template, args.research_question, args.mode,
                                  allowed_labels, defs, unit)
        except ContractInputError as exc:
            sys.stderr.write(f"ABBRUCH: {exc}\n")
            sys.exit(2)
        tok = math.ceil(len(prompt) / args.token_ratio)
        st = {"unit_id": unit.get("unit_id"),
              "unit_input_sha256": canonical_json_sha256(unit),
              "rendered_prompt_sha256": sha256_text(prompt),
              "approx_prompt_tokens": tok, "budget": budget}
        if tok > budget:
            st["status"] = "SKIPPED_OVER_BUDGET"
            statuses.append(st)
            continue
        if args.dry_run:
            st["status"] = "DRY_RUN_OK"
            statuses.append(st)
            continue
        raw = None

        def _quar(status):  # ungueltige Rohantwort opt-in in Quarantaene
            try:
                ref = quarantine_raw(args.quarantine_dir, run_id,
                                     unit.get("unit_id"), raw, status)
            except ContractInputError as exc:
                sys.stderr.write(f"ABBRUCH: {exc}\n")
                sys.exit(2)
            if ref:
                st["quarantine"] = ref

        try:
            resp = chat(model=args.model, messages=[{"role": "user", "content": prompt}],
                        format=grammar,
                        options={"temperature": args.temperature, "top_p": args.top_p,
                                 "num_ctx": args.num_ctx, "seed": args.seed,
                                 "num_predict": args.reserve_output_tokens})
            raw = resp["message"]["content"]
            obj = json.loads(raw)
            errs = sorted(validator.iter_errors(obj), key=lambda e: list(e.path))
            if errs:
                st.update(status="SCHEMA_INVALID", errors=[e.message for e in errs[:5]])
                _quar("SCHEMA_INVALID")
                statuses.append(st)
                continue
            mv = validate_mode(obj, args.mode, allowed_labels)
            if mv:
                st.update(status="MODE_VIOLATION", reason=mv)
                _quar("MODE_VIOLATION")
                statuses.append(st)
                continue
            results.append(bind_p0_fields(unit, obj))
            st["status"] = "OK"
            statuses.append(st)
        except json.JSONDecodeError as e:
            st.update(status="NOT_JSON", reason=str(e))
            _quar("NOT_JSON")
            statuses.append(st)
        except Exception as e:  # noqa: BLE001
            st.update(status="ERROR", reason=str(e))
            statuses.append(st)

    ok = {"OK", "DRY_RUN_OK"}
    n_ok = sum(1 for s in statuses if s.get("status") in ok)
    all_ok = bool(units) and all(s.get("status") in ok for s in statuses)
    manifest = {
        "runner_id": "QDA-P1-RUNNER", "run_id": run_id, "library_version": LIBRARY_VERSION,
        "contract_version": CONTRACT_VERSION, "contract_sha256": contract_sha,
        "prompt_id": PROMPT_ID, "prompt_version": PROMPT_VERSION, "prompt_sha256": prompt_sha,
        "prompt_source": prompt_source, "schema_sha256": schema_sha,
        "grammar_sha256": grammar_sha, "allowed_method_claim": claim,
        "model": args.model, "model_quantization": model_quant, "model_digest": model_digest,
        "backend": "ollama", "backend_client_version": backend_client_version,
        "mode": args.mode, "codebook_size": (len(allowed_labels) if allowed_labels else 0),
        "codebook_sha256": codebook_sha,
        "research_question_sha256": research_question_sha,
        "provenance_level": "DRY_RUN" if args.dry_run else "MODEL_BOUND",
        "quarantine_enabled": bool(args.quarantine_dir),
        "runtime": {"temperature": args.temperature, "top_p": args.top_p,
                    "num_ctx": args.num_ctx, "seed": args.seed,
                    "num_predict": args.reserve_output_tokens},
        "source_sha256": p0_meta.get("source_sha256"),
        "scope_sha256": p0_meta.get("scope_sha256"),
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "n_units": len(units), "n_ok": n_ok, "statuses": statuses,
        "note": "seed+temp0 verbessern die Wiederholbarkeit, garantieren sie nicht.",
    }
    if args.out:
        atomic_write(args.out, json.dumps({"_qda_run": manifest, "results": results},
                                          ensure_ascii=False, indent=2))
    sys.stderr.write(f"units={len(units)} ok={n_ok} all_ok={all_ok} prompt={prompt_source}\n")
    if args.dry_run or not args.out:
        print(json.dumps({"_qda_run": manifest}, ensure_ascii=False, indent=2))
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
