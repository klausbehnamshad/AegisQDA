#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
QDA P0 — SEGMENTIERUNG (v0.1, DRAFT)

Deterministische Vor-Segmentierung fuer DigQDA.
KEIN Modell. P0 trifft KEINE analytischen Entscheidungen — es zerlegt die
Quelle nur an *beobachtbaren* Grenzen (Cue-Pausen bzw. Leerzeilen) in
handhabbare Kodierfenster mit exakt uebernommenen Locatoren. Die eigentliche
analytische Segmentierung (Zusammenfassen zu bedeutungsvollen Einheiten) bleibt
Sache von P1 / der Forscherin.

Unterstuetzte Quellen:
  .srt  -> Fenster aus aufeinanderfolgenden Cues (Timecode-Range je Fenster)
  .txt  -> Absaetze (durch Leerzeilen getrennt); Locator = Zeilen-/Zeichen-Range

Aufruf:
  python3 qda_segment.py --source interview.srt --out segments.json
  python3 qda_segment.py --source interview.txt --out segments.json
  python3 qda_segment.py --source i.srt --mode cue           # 1 Segment je Cue
  python3 qda_segment.py --source i.srt --max-gap-ms 1500 --max-chars 1000

Jedes Segment ist so gebaut, dass es einzeln in den P1-Prompt gepastet werden
kann. Die Locatoren sind spaeter mit qda_validate.py pruefbar.
"""

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import unicodedata


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


TIMECODE_RE = re.compile(r"(\d{2}):(\d{2}):(\d{2})[,\.](\d{3})")
# Sprecherlabel am Zeilenanfang, z.B. "B:", "I:", "IP2:", "Interviewer:".
SPEAKER_RE = re.compile(r"^\s*([A-Za-z0-9ÄÖÜäöüß_.\-]{1,15}):\s")


def detect_speaker(text):
    m = SPEAKER_RE.match(text or "")
    return m.group(1) if m else None


def resolve_speakers(texts):
    """Deterministische, nicht erschlossene Sprecherbindung.

    Nur Labels, die WÖRTLICH am Zeilenanfang stehen, werden übernommen.
    Kein Label -> 'not stated'. Uneinheitliche Labels -> 'multiple'.
    """
    found = [s for s in (detect_speaker(t) for t in texts) if s]
    uniq = sorted(set(found))
    if not uniq:
        return "not stated"
    if len(uniq) == 1:
        return uniq[0]
    return "multiple"


def tc_to_ms(h, m, s, ms):
    return ((int(h) * 60 + int(m)) * 60 + int(s)) * 1000 + int(ms)


def ms_to_tc(ms):
    h = ms // 3_600_000
    ms -= h * 3_600_000
    m = ms // 60_000
    ms -= m * 60_000
    s = ms // 1000
    ms -= s * 1000
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def parse_srt(raw, force_srt=False):
    """Strikte SRT-Analyse (P0-06).

    Rueckgabe: (cues, problems, srt_intended).
    - srt_intended = force_srt (Dateiendung .srt) ODER mindestens ein Block "-->".
    - Ist SRT beabsichtigt, muss JEDER nicht-leere Block genau eine gueltige
      Timecode-Zeile ergeben; start<=ende; eindeutige Indizes; monoton steigende
      Startzeiten. Jede Abweichung -> problems (kein stilles Verwerfen).
    """
    cues, problems = [], []
    blocks = [b for b in re.split(r"\n\s*\n", raw.strip()) if b.strip() != ""]
    # SRT-Absicht: Dateiendung .srt ODER Vorkommen von "-->" (P0-06: die deklarierte
    # Endung erzwingt strikte Validierung, damit ein kaputter Pfeil nicht als TXT durchrutscht).
    srt_intended = force_srt or any("-->" in b for b in blocks)
    if not srt_intended:
        return [], [], False

    seen_idx = set()
    last_start = -1
    for bnum, block in enumerate(blocks, 1):
        lines = [line for line in block.splitlines() if line.strip() != ""]
        tc_lines = [
            line
            for line in lines
            if "-->" in line and len(TIMECODE_RE.findall(line)) >= 2
        ]
        if len(tc_lines) != 1:
            problems.append(f"Block {bnum}: {'keine' if not tc_lines else 'mehrere'} gueltige Timecode-Zeile(n)")
            continue
        tcs = TIMECODE_RE.findall(tc_lines[0])
        start, end = tc_to_ms(*tcs[0]), tc_to_ms(*tcs[1])
        if start > end:
            problems.append(f"Block {bnum}: Start > Ende")
            continue
        idx = int(lines[0].strip()) if lines[0].strip().isdigit() else len(cues) + 1
        if idx in seen_idx:
            problems.append(f"Block {bnum}: doppelter Index {idx}")
            continue
        if start < last_start:
            problems.append(f"Block {bnum}: nicht monotone Startzeit")
            continue
        seen_idx.add(idx)
        last_start = start
        ti = lines.index(tc_lines[0])
        cues.append({"index": idx, "start_ms": start, "end_ms": end,
                     "text": " ".join(lines[ti + 1:]).strip()})
    return cues, problems, True


def segment_srt(cues, mode, max_gap_ms, max_chars):
    segments = []
    if not cues:
        return segments

    def flush(group):
        if not group:
            return
        uid = f"S{len(segments) + 1:02d}"
        text = " ".join(c["text"] for c in group).strip()
        segments.append({
            "unit_id": uid,
            "source_type": "srt",
            "source_range": f"{ms_to_tc(group[0]['start_ms'])} --> {ms_to_tc(group[-1]['end_ms'])}",
            "explicit_speaker": resolve_speakers([c["text"] for c in group]),
            "cue_indices": [c["index"] for c in group],
            "n_cues": len(group),
            "source_text": text,
        })

    if mode == "cue":
        for c in cues:
            flush([c])
        return segments

    # mode == "window": Grenze bei Pause > max_gap_ms ODER Zeichenbudget ueberschritten
    group = []
    for c in cues:
        if group:
            gap = c["start_ms"] - group[-1]["end_ms"]
            cur_len = sum(len(x["text"]) + 1 for x in group)
            if gap > max_gap_ms or cur_len + len(c["text"]) > max_chars:
                flush(group)
                group = []
        group.append(c)
    flush(group)
    return segments


def segment_txt(raw, max_chars):
    """Absatzweise (Leerzeilen-getrennt); Locator = Zeilen- und Zeichen-Range."""
    segments = []
    lines = raw.splitlines()
    # Char-Offset je Zeilenanfang (1-indexierte Zeilen).
    line_start_char = []
    pos = 0
    for ln in lines:
        line_start_char.append(pos)
        pos += len(ln) + 1  # +1 fuer den Zeilenumbruch

    # Absaetze als Bloecke nicht-leerer Zeilen.
    i = 0
    n = len(lines)
    while i < n:
        if lines[i].strip() == "":
            i += 1
            continue
        j = i
        while j < n and lines[j].strip() != "":
            j += 1
        block_lines = lines[i:j]
        text = " ".join(line.strip() for line in block_lines).strip()
        char_start = line_start_char[i]
        char_end = line_start_char[j - 1] + len(lines[j - 1])
        uid = f"S{len(segments) + 1:02d}"
        seg = {
            "unit_id": uid,
            "source_type": "txt",
            "source_range": f"L{i + 1}-L{j}",
            "explicit_speaker": resolve_speakers(block_lines),
            "line_start": i + 1,
            "line_end": j,
            "char_start": char_start,
            "char_end": char_end,
            "source_text": text,
        }
        if len(text) > max_chars:
            seg["warning"] = (f"Absatz laenger als max_chars ({len(text)}>{max_chars}); "
                              f"ggf. manuell teilen oder num_ctx erhoehen.")
        segments.append(seg)
        i = j
    return segments


def main():
    ap = argparse.ArgumentParser(description="QDA P0 — deterministische Segmentierung (SRT/TXT).")
    ap.add_argument("--source", required=True, help=".srt oder .txt")
    ap.add_argument("--out", help="Ziel-JSON (sonst stdout)")
    ap.add_argument(
        "--source-label",
        help="Optionales opakes Quellenlabel fuer Manifest/Reports (Pfad bleibt verborgen).",
    )
    ap.add_argument("--mode", choices=["window", "cue"], default="window",
                    help="SRT: window (Cues zu Fenstern) oder cue (1 Segment/Cue). Default window.")
    ap.add_argument("--max-gap-ms", type=int, default=2000,
                    help="SRT: Pause > diesem Wert beendet ein Fenster (Default 2000).")
    ap.add_argument("--max-chars", type=int, default=1200,
                    help="Weiches Zeichenbudget je Fenster/Absatz (Default 1200).")
    args = ap.parse_args()

    # Hash der ORIGINAL-Dateibytes (identisch zu qda_validate.py), erst DANACH
    # fuer die Verarbeitung normalisieren.
    with open(args.source, "rb") as f:
        raw_bytes = f.read()
    sha = hashlib.sha256(raw_bytes).hexdigest()
    raw = unicodedata.normalize("NFC", raw_bytes.decode("utf-8"))

    declared_srt = args.source.lower().endswith(".srt")
    cues, problems, srt_intended = parse_srt(raw, force_srt=declared_srt)
    if srt_intended:
        # Fail-closed (P0-06): keine still verworfenen Bloecke, kein Output.
        if problems:
            sys.stderr.write("ABBRUCH: SRT strukturell ungueltig — kein Output geschrieben.\n")
            for p in problems:
                sys.stderr.write(f"  - {p}\n")
            sys.exit(3)
        source_type = "srt"
        segments = segment_srt(cues, args.mode, args.max_gap_ms, args.max_chars)
    else:
        source_type = "txt"
        segments = segment_txt(raw, args.max_chars)

    source_label = args.source_label or os.path.basename(args.source)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", source_label):
        sys.stderr.write("ABBRUCH: --source-label ist kein pfadsicheres opakes Label.\n")
        sys.exit(2)

    out = {
        "meta": {
            "source": source_label,
            "source_type": source_type,
            "source_sha256": sha,
            "mode": args.mode if source_type == "srt" else "paragraph",
            "params": {"max_gap_ms": args.max_gap_ms, "max_chars": args.max_chars},
            "n_units": len(segments),
            "srt_blocks_parsed": len(cues) if source_type == "srt" else None,
            "note": "source_units sind mechanische Verarbeitungseinheiten, keine "
                    "analytischen Segmente. Analytische Segmentierung bleibt P1/Mensch.",
        },
        "source_units": segments,
    }
    text = json.dumps(out, ensure_ascii=False, indent=2)
    if args.out:
        atomic_write(args.out, text)
        sys.stderr.write(f"{len(segments)} source_units ({source_type}) -> {args.out}\n")
    else:
        print(text)


if __name__ == "__main__":
    main()
