#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
QDA-UTIL-QUOTE-LOCATOR-VALIDATION  (v0.4, DRAFT)

Externer, deterministischer Validator. Modell schlaegt vor, Code verifiziert.

v0.4 schliesst weitere Adversarial-Luecken:
- Evidenz NUR aus dem kanonischen Pfad descriptive_codes[].source_quote; fremde
  Felder (z.B. fake_quote) sind keine Evidenz mehr, und Einheiten mit fremder
  Struktur -> INVALID_INPUT (strenge Unit-Form).
- Platzhalter-source_quote (z.B. "not stated") bei einem Code ist NICHT unsichtbar,
  sondern MISSING_EVIDENCE -> kein PASS (fail-closed).
- Mehr-Cue-Fenster (Standard-P0-Output) sind gueltige SPAN-Locatoren, nicht OVERLAP.
- Leeres Ergebnis ist nur bei GEBUNDENEM NOTHING_CODABLE/NO_CODE_FITS NO_EVIDENCE;
  unbindbar leer -> INVALID_INPUT.

Verdikte: PASS | REVIEW_REQUIRED | NO_EVIDENCE | INVALID_INPUT.
Exit: PASS=0, REVIEW_REQUIRED/NO_EVIDENCE=1, INVALID_INPUT=2.
Abhaengigkeit: rapidfuzz
"""

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import unicodedata
from datetime import datetime, timezone

try:
    from rapidfuzz import fuzz
except ImportError:
    sys.stderr.write("FEHLER: rapidfuzz fehlt. -> pip install rapidfuzz\n")
    sys.exit(2)

VALIDATOR_VERSION = "0.4"

UNIT_RANGE_KEYS = ("source_range", "source_range_unverified")
EMPTY_DECISIONS = {"NOTHING_CODABLE", "NO_CODE_FITS"}
VALID_DECISIONS = {"CODES_ASSIGNED", "NO_CODE_FITS", "NOTHING_CODABLE"}
VALID_LOC = {"EXACT", "WITHIN", "SPAN", "PRESENT"}
ALLOWED_CODE_KEYS = {"code_label", "definition", "status", "source_quote",
                     "quote_locator", "source_quote_match", "quote_locator_match"}
PLACEHOLDERS = {"", "not stated", "unclear", "none", "n/a", "na", "not applicable",
                "not requested", "none warranted", "locator unavailable",
                "speaker not identified", "keine", "nicht genannt", "unklar"}
TIMECODE_RE = re.compile(r"(\d{2}):(\d{2}):(\d{2})[,\.](\d{3})")


def normalize(text):
    text = unicodedata.normalize("NFC", text or "")
    text = text.replace(" ", " ")
    return re.sub(r"\s+", " ", text).strip()


def is_placeholder(v):
    return (not isinstance(v, str)) or (v.strip().lower() in PLACEHOLDERS)


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


def tc(h, m, s, ms):
    return ((int(h) * 60 + int(m)) * 60 + int(s)) * 1000 + int(ms)


def parse_srt(raw):
    cues = []
    for block in re.split(r"\n\s*\n", raw.strip()):
        lines = [line for line in block.splitlines() if line.strip() != ""]
        if not lines:
            continue
        for i, line in enumerate(lines):
            t = TIMECODE_RE.findall(line)
            if len(t) >= 2 and "-->" in line:
                idx = int(lines[0].strip()) if lines[0].strip().isdigit() else len(cues) + 1
                cues.append({"index": idx, "start_ms": tc(*t[0]), "end_ms": tc(*t[1]),
                             "text": " ".join(lines[i + 1:]).strip()})
                break
    return cues, len(cues) > 0


def unit_haystack(source_range, src):
    if not isinstance(source_range, str) or is_placeholder(source_range):
        return None
    if src["is_srt"]:
        t = TIMECODE_RE.findall(source_range)
        if len(t) < 2:
            return None
        lo, hi = tc(*t[0]), tc(*t[1])
        texts = [c["text"] for c in src["cues"]
                 if c["start_ms"] >= lo - 1 and c["end_ms"] <= hi + 1]
        return normalize(" ".join(texts)) if texts else None
    m = re.search(r"[Ll]\s*(\d+)\s*[-–]\s*[Ll]?\s*(\d+)", source_range) or \
        re.search(r"[Ll]\s*(\d+)", source_range)
    if m:
        a = int(m.group(1))
        b = int(m.group(2)) if m.lastindex >= 2 else a
        lines = src["lines"]
        if 1 <= a <= b <= len(lines):
            return normalize(" ".join(lines[a - 1:b]))
    return None


def check_quote(quote, unit_hay, doc_hay, threshold, document_mode):
    q = normalize(quote)
    if q == "":
        return {"result": "MISSING_EVIDENCE", "reason": "leeres Zitat"}
    if unit_hay is None:
        if not document_mode:
            return {"result": "UNBOUND", "reason": "keine gueltige Einheitsbindung"}
        hay = doc_hay
    else:
        hay = unit_hay
    if q in hay:
        return {"result": "EXACT", "score": 100.0}
    al = fuzz.partial_ratio_alignment(q, hay)
    score = round(al.score, 1) if al is not None else 0.0
    closest = hay[al.dest_start:al.dest_end].strip() if al is not None else ""
    if score >= threshold:
        return {"result": "FUZZY", "score": score, "closest_source": closest[:240]}
    if unit_hay is not None:
        if q in doc_hay:
            return {"result": "WRONG_UNIT", "score": 100.0,
                    "reason": "zeichengetreu, aber nicht in der behaupteten Einheit"}
        ald = fuzz.partial_ratio_alignment(q, doc_hay)
        if ald is not None and round(ald.score, 1) >= threshold:
            return {"result": "WRONG_UNIT", "score": round(ald.score, 1),
                    "closest_source": doc_hay[ald.dest_start:ald.dest_end].strip()[:240]}
    return {"result": "NOT_FOUND", "score": score, "closest_source": closest[:240]}


def check_locator(loc, src):
    if is_placeholder(loc):
        return {"result": "SKIPPED"}
    if not src["is_srt"]:
        m = re.search(r"[Ll]\s*(\d+)\s*[-–]\s*[Ll]?\s*(\d+)", loc) or re.search(r"[Ll]\s*(\d+)", loc)
        if m:
            a = int(m.group(1))
            b = int(m.group(2)) if m.lastindex >= 2 else a
            if 1 <= a <= b <= src["n_lines"]:
                return {"result": "PRESENT"}
            return {"result": "NOT_FOUND", "reason": f"Zeilen {a}-{b} ausserhalb"}
        return {"result": "NOT_FOUND", "reason": "kein pruefbarer TXT-Locator"}
    t = TIMECODE_RE.findall(loc)
    cues = src["cues"]
    if not t:
        m = re.search(r"\d+", loc)
        if m and any(c["index"] == int(m.group()) for c in cues):
            return {"result": "PRESENT", "match": "cue_index"}
        return {"result": "NOT_FOUND"}
    times = [tc(*x) for x in t]
    lo, hi = min(times), max(times)
    for c in cues:  # exakte Grenze eines einzelnen Cues
        if c["start_ms"] == lo and c["end_ms"] == hi:
            return {"result": "EXACT", "cue_index": c["index"]}
    for c in cues:  # vollstaendig innerhalb eines Cues
        if lo >= c["start_ms"] and hi <= c["end_ms"]:
            return {"result": "WITHIN", "cue_index": c["index"]}
    # SPAN: zusammenhaengendes Mehr-Cue-Fenster (Standard-P0-Output)
    if lo in {c["start_ms"] for c in cues} and hi in {c["end_ms"] for c in cues}:
        seq = sorted((c for c in cues if c["start_ms"] >= lo and c["end_ms"] <= hi),
                     key=lambda c: c["start_ms"])
        if seq and seq[0]["start_ms"] == lo and seq[-1]["end_ms"] == hi:
            return {"result": "SPAN", "cues": [c["index"] for c in seq]}
    for c in cues:  # bloss ueberlappend -> KEIN gueltiger Locator
        if lo <= c["end_ms"] and hi >= c["start_ms"]:
            return {"result": "OVERLAP", "cue_index": c["index"],
                    "reason": "Range nicht durch Cue(s) exakt gedeckt"}
    return {"result": "NOT_FOUND"}


def valid_unit_shape(u, document_mode):
    """Strenge P1-Bound-Result-Form (schliesst fremde Payloads aus)."""
    if not isinstance(u, dict):
        return False
    if not isinstance(u.get("descriptive_codes"), list):
        return False
    if u.get("coding_decision") not in VALID_DECISIONS:
        return False
    if not document_mode and not isinstance(u.get("source_range"), str):
        return False
    for k in u:  # keine fremden Evidenz-Felder auf Unit-Ebene
        if "quote" in k.lower():
            return False
    for c in u["descriptive_codes"]:
        if not isinstance(c, dict) or "source_quote" not in c:
            return False
        if any(k not in ALLOWED_CODE_KEYS for k in c):
            return False
    return True


def extract_units(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for k in ("results", "source_units", "data", "units"):
            if isinstance(data.get(k), list):
                return data[k]
        if any(key in data for key in ("descriptive_codes", "coding_decision", "unit_id")):
            return [data]
    return None


def collect_from_unit(unit, unit_hay, src, threshold, document_mode, findings):
    seg = unit.get("unit_id") or unit.get("segment_id")
    for rk in UNIT_RANGE_KEYS:
        if isinstance(unit.get(rk), str) and not is_placeholder(unit[rk]):
            res = check_locator(unit[rk], src)
            unit[rk + "_match"] = res
            if res["result"] != "SKIPPED":
                findings["locators"].append({"segment_id": seg, "value": unit[rk], **res})
            break
    for code in unit.get("descriptive_codes", []):
        if not isinstance(code, dict):
            continue
        sq = code.get("source_quote")
        if is_placeholder(sq):
            res = {"result": "MISSING_EVIDENCE", "reason": "Platzhalter/leeres source_quote"}
        else:
            res = check_quote(sq, unit_hay, src["doc_hay"], threshold, document_mode)
        code["source_quote_match"] = res
        findings["quotes"].append({"segment_id": seg, "code_label": code.get("code_label"),
                                   "value": sq, **res})
        ql = code.get("quote_locator")
        if isinstance(ql, str) and not is_placeholder(ql):
            lres = check_locator(ql, src)
            code["quote_locator_match"] = lres
            if lres["result"] != "SKIPPED":
                findings["locators"].append({"segment_id": seg, "value": ql, **lres})


def build_report(findings, meta, verdict, reason):
    q = findings["quotes"]
    cats = ("EXACT", "FUZZY", "WRONG_UNIT", "NOT_FOUND", "UNBOUND", "MISSING_EVIDENCE")
    counts = {k: sum(1 for x in q if x["result"] == k) for k in cats}
    loc = findings["locators"]
    loc_bad = [x for x in loc if x["result"] not in VALID_LOC and x["result"] != "SKIPPED"]
    L = [f"# QDA Quote-/Locator-Validierung — **{verdict}**\n", f"> {reason}\n",
         f"- Quelle: `{meta['source_name']}` (SRT: {meta['is_srt']}, Cues: {meta['n_cues']})",
         f"- Quelle-SHA256: `{meta['source_sha256'][:16]}…` · Validator v{VALIDATOR_VERSION}"
         f"{' · document-mode' if meta['document_mode'] else ''}\n", "## Zitate\n",
         "| Ergebnis | Anzahl |", "|---|---|"]
    for k in cats:
        L.append(f"| {k} | {counts[k]} |")
    L.append(f"| **gesamt** | **{len(q)}** |\n")
    for x in (x for x in q if x["result"] != "EXACT"):
        L.append(f"- **{x['result']}** · Einheit {x.get('segment_id','?')}: „{x['value']}\"")
    L.append(f"\n## Locatoren\n- geprueft: {len(loc)} · ungueltig (inkl. OVERLAP): {len(loc_bad)}")
    for x in loc_bad:
        L.append(f"  - {x['result']} · Einheit {x.get('segment_id','?')} · `{x['value']}`")
    return "\n".join(L), {"verdict": verdict, "reason": reason, "quotes_total": len(q),
                          **{f"quotes_{k.lower()}": counts[k] for k in cats},
                          "locators_total": len(loc), "locators_invalid": len(loc_bad)}


def main():
    ap = argparse.ArgumentParser(description="QDA Quote-/Locator-Validator (fail-closed).")
    ap.add_argument("--source", required=True)
    ap.add_argument(
        "--source-label",
        help="Optionales opakes Quellenlabel fuer Manifest/Reports (Pfad bleibt verborgen).",
    )
    ap.add_argument("--json", required=True)
    ap.add_argument("--out")
    ap.add_argument("--report")
    ap.add_argument("--fuzzy-threshold", type=float, default=90.0)
    ap.add_argument("--document-mode", action="store_true")
    args = ap.parse_args()

    with open(args.source, "rb") as f:
        raw_bytes = f.read()
    source_sha = hashlib.sha256(raw_bytes).hexdigest()
    source_raw = raw_bytes.decode("utf-8")
    with open(args.json, encoding="utf-8") as f:
        data = json.load(f)
    input_sha = hashlib.sha256(json.dumps(
        data, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")).hexdigest()

    cues, is_srt = parse_srt(source_raw)
    lines = source_raw.splitlines()
    doc_hay = normalize(" ".join(c["text"] for c in cues)) if is_srt else normalize(source_raw)
    src = {"cues": cues, "is_srt": is_srt, "lines": lines, "doc_hay": doc_hay,
           "n_lines": len(lines), "n_chars": len(source_raw)}
    source_label = args.source_label or os.path.basename(args.source)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", source_label):
        sys.stderr.write("ABBRUCH: --source-label ist kein pfadsicheres opakes Label.\n")
        sys.exit(2)
    meta = {"source_name": source_label, "source_sha256": source_sha,
            "is_srt": is_srt, "n_cues": len(cues), "threshold": args.fuzzy_threshold,
            "document_mode": args.document_mode,
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}

    units = extract_units(data)
    findings = {"quotes": [], "locators": []}
    verdict = reason = None

    if (units is None or len(units) == 0
            or not all(valid_unit_shape(u, args.document_mode) for u in units)):
        verdict, reason = "INVALID_INPUT", "Kein gueltiges gebundenes P1-Ergebnis (strenge Unit-Form verletzt)."
    else:
        bindings = []
        for unit in units:
            uh = None
            for rk in UNIT_RANGE_KEYS:
                if isinstance(unit.get(rk), str):
                    uh = unit_haystack(unit[rk], src)
                    break
            bindings.append(uh)
            collect_from_unit(unit, uh, src, args.fuzzy_threshold, args.document_mode, findings)

        q = findings["quotes"]
        loc_bad = [x for x in findings["locators"]
                   if x["result"] not in VALID_LOC and x["result"] != "SKIPPED"]
        if len(q) == 0:
            legit_empty = all(
                u.get("coding_decision") in EMPTY_DECISIONS and not u.get("descriptive_codes")
                and (args.document_mode or b is not None)
                for u, b in zip(units, bindings))
            if legit_empty:
                verdict, reason = "NO_EVIDENCE", "Gebundenes leeres Ergebnis; nichts zu verifizieren, menschliche Bestaetigung noetig."
            else:
                verdict, reason = "INVALID_INPUT", "Null Zitate ohne gebundenes leeres Ergebnis."
        else:
            all_exact = all(x["result"] == "EXACT" for x in q)
            verdict = "PASS" if (all_exact and not loc_bad) else "REVIEW_REQUIRED"
            reason = ("Jedes Zitat zeichengetreu in seiner Einheit belegt, Locatoren gueltig."
                      if verdict == "PASS" else
                      "Mind. ein Zitat FUZZY/WRONG_UNIT/NOT_FOUND/UNBOUND/MISSING_EVIDENCE oder Locator ungueltig.")

    report_md, summary = build_report(findings, meta, verdict, reason)
    manifest = {"validator_id": "QDA-UTIL-QUOTE-LOCATOR-VALIDATION",
                "validator_version": VALIDATOR_VERSION, "source_sha256": source_sha,
                "input_sha256": input_sha,
                "document_mode": args.document_mode, "timestamp": meta["timestamp"], "result": summary}
    if args.out:
        atomic_write(args.out, json.dumps({"_qda_validation": manifest, "data": data},
                                          ensure_ascii=False, indent=2))
    if args.report:
        atomic_write(args.report, report_md)
    print(report_md)
    print("\n--- Manifest-Fragment ---")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    sys.exit({"PASS": 0, "REVIEW_REQUIRED": 1, "NO_EVIDENCE": 1, "INVALID_INPUT": 2}[verdict])


if __name__ == "__main__":
    main()
