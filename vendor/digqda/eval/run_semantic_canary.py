#!/usr/bin/env python3
"""DigQDA Semantic Canary — synthetic quality probe.

Runs each synthetic case through the real DigQDA pipeline and separates THREE
independent quality layers:

    CONTRACT   — is the model output structurally legal? (P1 unit status == OK)
    EVIDENCE   — are quotes/locators bound to the source? (validator verdict PASS)
    SEMANTIC   — does the model make a methodologically defensible decision,
                 within the robust boundaries declared per case?

The point: CONTRACT + EVIDENCE can both pass while SEMANTIC fails — a result that
is technically perfect but analytically wrong. This harness makes that visible.

Scope is enforced deterministically via a per-case role map (not hardcoded I/B):
speaker roles that are not in `included_speaker_roles` are dropped BEFORE P1, so
an interviewer question is never sent to the model as an analysis task — it stays
in the source only as context. Use --no-scope to reproduce the ungated behaviour.

This is a local, human-reviewed evidence artifact — NOT a blocking gate and NOT
part of the deterministic conformance suite. Real runs require Ollama + a local
model. --dry-run exercises the plumbing without a model (validator INVALID_INPUT
is expected in that mode).

Only the bundled synthetic fixtures are authorized. Do not point this at real data.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

UTIL = Path(__file__).resolve().parent.parent / "90_UTILITIES"
sys.path.insert(0, str(UTIL))
from digqda_errors import WorkflowError  # noqa: E402
from qda_scope import apply_role_scope  # noqa: E402

NEGATION_PATTERNS = tuple(re.compile(pattern, re.IGNORECASE) for pattern in (
    r"\bnicht\b",
    r"\bkein(?:e|en|em|er|es)?\b",
    r"\bnie\b",
    r"\bohne\b",
    r"\bnichts\b",
    r"\bfehl(?:e|st|t|en|te|test|tet|ten|end(?:e|er|es|en|em)?)\b",
    r"\babwesen(?:d(?:e|er|es|en|em)?|heit)?\b",
    r"\bmangel(?:t|te|ten|nd(?:e|er|es|en|em)?)?\b",
))

MODE_LEGALITY = {
    "OPEN_DESCRIPTIVE": {"no_code_fits": False},
    "STRICT_CODEBOOK": {"no_code_fits": True},
    "CONSTRAINED_EXTENSION": {"no_code_fits": False},
}


# --------------------------------------------------------------------------- #
# small helpers
# --------------------------------------------------------------------------- #
def load_json(path: Path):
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def dump_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(obj, handle, ensure_ascii=False, indent=2)


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


def contains_any(haystack: str, needles) -> list[str]:
    low = (haystack or "").lower()
    return [n for n in needles if n and n.lower() in low]


def has_negation(text: str) -> bool:
    """Return a conservative word-boundary signal for explicit negation."""
    return any(pattern.search(text or "") for pattern in NEGATION_PATTERNS)


# --------------------------------------------------------------------------- #
# semantic comparator
# --------------------------------------------------------------------------- #
def evaluate_semantic(expect: dict, result: dict, source_has_negation: bool):
    """Return (verdict, violations, reviews) for one coded unit."""
    violations: list[str] = []
    reviews: list[str] = []

    decision = result.get("coding_decision")
    codes = result.get("descriptive_codes") or []
    labels = [c.get("code_label", "") for c in codes]
    statuses = [c.get("status", "") for c in codes]
    desc = result.get("concise_description", "") or ""
    nf = result.get("narrative_function")
    uncertainty = result.get("uncertainty") or []

    allowed = expect.get("allowed_decisions") or []
    if allowed and decision not in allowed:
        violations.append(f"decision {decision!r} not in {allowed}")

    for lbl in labels:
        hit = contains_any(lbl, expect.get("forbidden_code_labels") or [])
        if hit:
            violations.append(f"forbidden code_label ~ {hit} in {lbl!r}")

    forb_status = set(expect.get("forbidden_code_status") or [])
    bad_status = sorted(forb_status.intersection(statuses))
    if bad_status:
        violations.append(f"forbidden code status present: {bad_status}")

    missing_status = sorted(
        status for status in (expect.get("required_code_status") or [])
        if status not in statuses
    )
    if missing_status:
        violations.append(f"required code status missing: {missing_status}")

    max_codes = expect.get("max_codes")
    if max_codes is not None and len(codes) > max_codes:
        violations.append(f"too many codes: {len(codes)} > {max_codes}")

    for frag_hit in contains_any(desc, expect.get("forbidden_description_fragments") or []):
        violations.append(f"forbidden description fragment: {frag_hit!r}")

    if expect.get("negation_must_survive") and source_has_negation:
        if not has_negation(desc):
            violations.append("negation dropped from concise_description")

    # softer expectations -> REVIEW
    for req in expect.get("required_code_labels") or []:
        if not any(req.lower() in lbl.lower() for lbl in labels):
            reviews.append(f"required code_label missing ~ {req!r}")

    if expect.get("require_uncertainty") and not uncertainty:
        reviews.append("uncertainty[] expected but empty")

    if expect.get("require_uncertainty_or_ambiguous"):
        if not (uncertainty or "CODEBOOK_AMBIGUOUS" in statuses or decision == "NO_CODE_FITS"):
            reviews.append("neither documented uncertainty nor CODEBOOK_AMBIGUOUS")

    allowed_nf = expect.get("allowed_narrative_functions")
    if allowed_nf and nf not in allowed_nf:
        reviews.append(f"narrative_function {nf!r} not in {allowed_nf}")

    for req in contains_any_missing(desc, expect.get("required_description_fragments") or []):
        reviews.append(f"required description fragment missing: {req!r}")

    if violations:
        return "SEMANTIC_FAIL", violations, reviews
    if reviews:
        return "SEMANTIC_REVIEW", violations, reviews
    return "SEMANTIC_PASS", violations, reviews


def contains_any_missing(haystack: str, needles) -> list[str]:
    low = (haystack or "").lower()
    return [n for n in needles if n and n.lower() not in low]


def worst(verdicts) -> str:
    order = {"SEMANTIC_FAIL": 3, "SEMANTIC_REVIEW": 2, "SEMANTIC_PASS": 1, "SKIPPED_DRY": 0}
    if not verdicts:
        return "SKIPPED_DRY"
    return max(verdicts, key=lambda v: order.get(v, 0))


def unit_role(unit: dict, role_map: dict) -> str | None:
    return role_map.get(unit.get("explicit_speaker", ""))


# --------------------------------------------------------------------------- #
# one case
# --------------------------------------------------------------------------- #
def run_case(case: dict, ctx: dict) -> dict:
    cid = case["case_id"]
    mode = case["mode"]
    role_map = case.get("role_map", {})
    included = case.get("included_speaker_roles", ["interviewee"])
    expect = case.get("expect", {})
    target_role = (case.get("target") or {}).get("speaker_role", "interviewee")

    case_dir = ctx["out"] / "cases" / cid
    case_dir.mkdir(parents=True, exist_ok=True)

    transcript = ctx["transcripts"] / case["transcript"]
    codebook = ctx["codebooks"] / case["codebook"] if case.get("codebook") else None

    rec: dict = {
        "case_id": cid,
        "title": case.get("title"),
        "stresses": case.get("stresses"),
        "mode": mode,
        "human_review_note": case.get("human_review_note"),
        "errors": [],
    }

    # ---- P0 ----
    seg_full = case_dir / "seg_full.json"
    seg_full.unlink(missing_ok=True)
    p0 = run([ctx["py"], str(ctx["seg"]), "--source", str(transcript), "--out", str(seg_full)])
    if p0.returncode != 0 or not seg_full.exists():
        rec["errors"].append(f"P0 failed rc={p0.returncode}: {p0.stderr.strip()[:300]}")
        rec["contract"] = "CONTRACT_ERROR"
        return rec
    envelope = load_json(seg_full)

    # ---- scope filter ----
    if ctx["no_scope"]:
        scoped, kept, excluded = envelope, envelope.get("source_units", []), []
    else:
        try:
            scoped, excluded_ids = apply_role_scope(envelope, role_map, included)
        except WorkflowError as exc:
            rec["errors"].append(f"scope failed: {exc}")
            rec["contract"] = "CONTRACT_ERROR"
            rec["scope_violation"] = True
            return rec
        kept = scoped["source_units"]
        original_by_id = {unit.get("unit_id"): unit for unit in envelope.get("source_units", [])}
        excluded = []
        for unit_id in excluded_ids:
            unit = original_by_id.get(unit_id, {})
            speaker = unit.get("explicit_speaker", "")
            excluded.append({"unit_id": unit_id, "speaker": speaker,
                             "role": role_map.get(speaker)})
    seg_scoped = case_dir / "seg_scoped.json"
    dump_json(seg_scoped, scoped)
    rec["excluded_units"] = excluded
    target_unit_ids = [u.get("unit_id") for u in kept if unit_role(u, role_map) == target_role]
    # negation source signal for the target units
    src_neg = any(has_negation(u.get("source_text", ""))
                  for u in kept if u.get("unit_id") in target_unit_ids)
    rec["target_unit_ids"] = target_unit_ids

    if not kept:
        rec["errors"].append("no in-scope units after filtering; P1 skipped")
        rec["contract"] = "CONTRACT_NA"
        return rec

    # ---- repeats: P1 + V ----
    repeats = []
    for r in range(ctx["repeats"]):
        seed = ctx["seed"] if ctx["fixed_seed"] else ctx["seed"] + r
        p1_path = case_dir / f"p1_r{r}.json"
        p1_path.unlink(missing_ok=True)
        cmd = [ctx["py"], str(ctx["p1"]), "--units", str(seg_scoped),
               "--schema", str(ctx["schema"]), "--mode", mode,
               "--model", ctx["model"], "--seed", str(seed),
               "--temperature", str(ctx["temperature"]), "--top-p", str(ctx["top_p"]),
               "--num-ctx", str(ctx["num_ctx"]), "--out", str(p1_path)]
        if codebook is not None and mode in ("STRICT_CODEBOOK", "CONSTRAINED_EXTENSION"):
            cmd += ["--codebook", str(codebook)]
        if ctx["dry_run"]:
            cmd.append("--dry-run")
        p1 = run(cmd)
        if not p1_path.exists():
            repeats.append({"repeat": r, "error": f"P1 no output rc={p1.returncode}: {p1.stderr.strip()[:300]}"})
            continue
        p1_data = load_json(p1_path)
        manifest = p1_data.get("_qda_run", {})
        results = {res.get("unit_id"): res for res in p1_data.get("results", [])}
        dry = manifest.get("provenance_level") == "DRY_RUN"
        scoped_meta = scoped.get("meta", {})
        scope_sha = scoped_meta.get("scope_sha256")
        scope_bound = ctx["no_scope"] or (
            scoped_meta.get("scope_applied") is True
            and isinstance(scope_sha, str)
            and re.fullmatch(r"[0-9a-f]{64}", scope_sha) is not None
            and manifest.get("scope_sha256") == scope_sha
        )

        # validation
        v_path = case_dir / f"v_r{r}.json"
        vm_path = case_dir / f"v_r{r}.md"
        v_path.unlink(missing_ok=True)
        vm_path.unlink(missing_ok=True)
        vcmd = [ctx["py"], str(ctx["val"]), "--source", str(transcript),
                "--json", str(p1_path), "--out", str(v_path), "--report", str(vm_path),
                "--fuzzy-threshold", str(ctx["fuzzy"])]
        run(vcmd)  # rc 2 == INVALID_INPUT (expected in dry); we read the json regardless
        vres = load_json(v_path)["_qda_validation"]["result"] if v_path.exists() else {}

        # contract per target unit
        status_by_unit = {s.get("unit_id"): s.get("status") for s in manifest.get("statuses", [])}
        tgt_statuses = [status_by_unit.get(u) for u in target_unit_ids]
        if dry:
            contract = "DRY_OK" if (
                all(s == "DRY_RUN_OK" for s in tgt_statuses) and scope_bound
            ) else "DRY_FAIL"
        else:
            contract = "CONTRACT_PASS" if (
                all(s == "OK" for s in tgt_statuses) and scope_bound
            ) else "CONTRACT_FAIL"

        # scope: did any excluded unit get coded?
        coded_ids = set(results.keys())
        excluded_ids = {e["unit_id"] for e in excluded}
        scope_violation = bool(coded_ids.intersection(excluded_ids)) or not scope_bound

        # evidence
        if dry:
            evidence = "DRY_NA"
        else:
            verdict = vres.get("verdict")
            evidence = "EVIDENCE_PASS" if verdict == "PASS" else f"EVIDENCE_{verdict}"

        # semantic per target unit
        sem_verdicts, sem_details = [], []
        primary = None
        if dry:
            sem_overall = "SKIPPED_DRY"
        else:
            for uid in target_unit_ids:
                res = results.get(uid)
                if res is None:
                    sem_verdicts.append("SEMANTIC_FAIL")
                    sem_details.append({"unit": uid, "violations": ["no result for target unit"]})
                    continue
                v, viol, rev = evaluate_semantic(expect, res, src_neg)
                sem_verdicts.append(v)
                sem_details.append({"unit": uid, "verdict": v, "decision": res.get("coding_decision"),
                                    "labels": [c.get("code_label") for c in (res.get("descriptive_codes") or [])],
                                    "violations": viol, "reviews": rev})
                if primary is None:
                    primary = {"decision": res.get("coding_decision"),
                               "labels": sorted(c.get("code_label", "") for c in (res.get("descriptive_codes") or []))}
            sem_overall = worst(sem_verdicts)

        repeats.append({
            "repeat": r, "seed": seed, "dry": dry,
            "contract": contract, "evidence": evidence,
            "scope_violation": scope_violation, "scope_bound": scope_bound,
            "semantic": sem_overall,
            "semantic_detail": sem_details,
            "quotes_wrong_unit": vres.get("quotes_wrong_unit"),
            "quotes_exact": vres.get("quotes_exact"), "quotes_total": vres.get("quotes_total"),
            "primary": primary,
        })

    rec["repeats"] = repeats
    ok_repeats = [r for r in repeats if "error" not in r]
    if not ok_repeats:
        rec["contract"] = "CONTRACT_ERROR"
        rec["errors"].append("all repeats failed to produce P1 output")
        return rec

    first = ok_repeats[0]
    rec["dry"] = first["dry"]
    rec["contract"] = first["contract"]
    rec["evidence"] = first["evidence"]
    rec["semantic"] = worst([r["semantic"] for r in ok_repeats])
    rec["scope_violation"] = any(r["scope_violation"] for r in ok_repeats)
    rec["scope_expected_uncoded"] = (case.get("scope_expectation") or {}).get("uncoded_speaker_roles", [])

    # stability across real repeats
    if not first["dry"] and len(ok_repeats) > 1:
        decisions = {json.dumps(r["primary"]["decision"]) for r in ok_repeats if r.get("primary")}
        labels = {json.dumps(r["primary"]["labels"]) for r in ok_repeats if r.get("primary")}
        rec["stability"] = {"decision_stable": len(decisions) <= 1,
                            "labels_stable": len(labels) <= 1,
                            "n_repeats": len(ok_repeats)}
    else:
        rec["stability"] = None
    return rec


# --------------------------------------------------------------------------- #
# report
# --------------------------------------------------------------------------- #
def write_report(md_path: Path, suite: dict, records: list[dict], ctx: dict) -> None:
    lines = []
    lines.append(f"# {suite.get('suite_id')} — {suite.get('suite_version')}")
    lines.append("")
    mode_line = "DRY-RUN (plumbing only, no model)" if ctx["dry_run"] else f"model `{ctx['model']}`"
    lines.append(f"Run: {mode_line} · repeats {ctx['repeats']} · "
                 f"seed {ctx['seed']}{' (fixed)' if ctx['fixed_seed'] else ' (+i)'} · "
                 f"scope {'OFF' if ctx['no_scope'] else 'ON'}")
    lines.append("")
    agg = suite["_aggregate"]
    lines.append("> " + " · ".join(f"{k}={v}" for k, v in agg.items()))
    lines.append("")
    lines.append("| Case | Mode | Contract | Evidence | Semantic | Scope | Stability |")
    lines.append("|---|---|---|---|---|---|---|")
    for r in records:
        scope = "—"
        if not ctx["no_scope"] and r.get("scope_expected_uncoded"):
            scope = "OK" if not r.get("scope_violation") else "VIOLATION"
        elif r.get("scope_violation"):
            scope = "VIOLATION"
        stab = "—"
        if r.get("stability"):
            d = "dec✓" if r["stability"]["decision_stable"] else "dec✗"
            lab = "lab✓" if r["stability"]["labels_stable"] else "lab✗"
            stab = f"{d}/{lab}"
        lines.append(f"| {r['case_id']} | {r['mode']} | {r.get('contract','?')} | "
                     f"{r.get('evidence','?')} | {r.get('semantic','?')} | {scope} | {stab} |")
    lines.append("")
    # details for anything not clean
    flagged = [r for r in records if r.get("semantic") in ("SEMANTIC_FAIL", "SEMANTIC_REVIEW")
               or r.get("contract") not in ("CONTRACT_PASS", "DRY_OK")
               or r.get("scope_violation") or r.get("errors")]
    if flagged:
        lines.append("## Findings")
        lines.append("")
        for r in flagged:
            lines.append(f"### {r['case_id']} — {r.get('title')}")
            if r.get("errors"):
                lines.append(f"- errors: {r['errors']}")
            for rep in r.get("repeats", []):
                for d in rep.get("semantic_detail", []):
                    if d.get("violations") or d.get("reviews"):
                        lines.append(f"- r{rep['repeat']} {d.get('unit')}: decision={d.get('decision')} "
                                     f"labels={d.get('labels')}")
                        for v in d.get("violations", []):
                            lines.append(f"    - FAIL: {v}")
                        for v in d.get("reviews", []):
                            lines.append(f"    - REVIEW: {v}")
            lines.append(f"- note: {r.get('human_review_note')}")
            lines.append("")
    md_path.write_text("\n".join(lines), encoding="utf-8")


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main() -> int:
    here = Path(__file__).resolve().parent
    repo_default = here.parent
    ap = argparse.ArgumentParser(description="DigQDA Semantic Canary")
    ap.add_argument("--cases", default=str(here / "synthetic_cases" / "cases.json"))
    ap.add_argument("--case", dest="case_ids", action="append",
                    help="run only this case_id (repeatable)")
    ap.add_argument("--repo-root", default=str(repo_default))
    ap.add_argument("--out", default=str(here / "out"))
    ap.add_argument("--model", default="gemma4:e4b")
    ap.add_argument("--repeats", type=int, default=1)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--fixed-seed", action="store_true",
                    help="use the same seed for every repeat (measures pipeline reproducibility)")
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--top-p", type=float, default=0.9)
    ap.add_argument("--num-ctx", type=int, default=8192)
    ap.add_argument("--fuzzy-threshold", type=float, default=90.0)
    ap.add_argument("--dry-run", action="store_true", help="no model; exercise plumbing only")
    ap.add_argument("--no-scope", action="store_true", help="disable scope filter (reproduce the gap)")
    ap.add_argument("--python", default=sys.executable)
    args = ap.parse_args()

    repo = Path(args.repo_root).resolve()
    cases_path = Path(args.cases).resolve()
    suite = load_json(cases_path)
    cases_dir = cases_path.parent
    ctx = {
        "py": args.python,
        "seg": repo / "90_UTILITIES" / "qda_segment.py",
        "p1": repo / "90_UTILITIES" / "qda_run_p1.py",
        "val": repo / "90_UTILITIES" / "qda_validate.py",
        "schema": repo / "10_GENERIC" / "p1_schema.json",
        "transcripts": cases_dir / "transcripts",
        "codebooks": cases_dir / "codebooks",
        "out": Path(args.out).resolve(),
        "model": args.model, "repeats": max(1, args.repeats), "seed": args.seed,
        "fixed_seed": args.fixed_seed, "temperature": args.temperature, "top_p": args.top_p,
        "num_ctx": args.num_ctx, "fuzzy": args.fuzzy_threshold,
        "dry_run": args.dry_run, "no_scope": args.no_scope,
    }
    for key in ("seg", "p1", "val", "schema"):
        if not ctx[key].exists():
            print(f"ERROR: pipeline file not found: {ctx[key]}", file=sys.stderr)
            return 2

    all_cases = suite.get("cases", [])
    if args.case_ids:
        requested = set(args.case_ids)
        known = {case.get("case_id") for case in all_cases}
        unknown = sorted(requested - known)
        if unknown:
            print("ERROR: unknown case_id(s): " + ", ".join(unknown), file=sys.stderr)
            return 2
        selected_cases = [case for case in all_cases if case.get("case_id") in requested]
    else:
        selected_cases = all_cases
    records = [run_case(case, ctx) for case in selected_cases]

    agg = {"cases": len(records)}
    for key, vals in (("contract_fail", ("CONTRACT_FAIL", "CONTRACT_ERROR")),
                      ("semantic_fail", ("SEMANTIC_FAIL",)),
                      ("semantic_review", ("SEMANTIC_REVIEW",)),
                      ("semantic_pass", ("SEMANTIC_PASS",))):
        agg[key] = sum(1 for r in records
                       if r.get("contract") in vals or r.get("semantic") in vals)
    agg["scope_violation"] = sum(1 for r in records if r.get("scope_violation"))
    suite["_aggregate"] = agg
    suite["_run"] = {k: ctx[k] if k in ("model", "repeats", "seed", "fixed_seed",
                                        "dry_run", "no_scope") else str(ctx[k])
                     for k in ("model", "repeats", "seed", "fixed_seed", "dry_run", "no_scope")}
    suite["_records"] = records

    out = ctx["out"]
    dump_json(out / "semantic_canary.json", suite)
    write_report(out / "semantic_canary.md", suite, records, ctx)

    print(f"Semantic canary: {agg}")
    print(f"  -> {out/'semantic_canary.json'}")
    print(f"  -> {out/'semantic_canary.md'}")

    if ctx["dry_run"]:
        # plumbing mode: fail only if the pipeline could not run
        bad = sum(1 for r in records if r.get("contract") in ("CONTRACT_ERROR", "DRY_FAIL", "CONTRACT_NA"))
        return 0 if bad == 0 else 2
    hard = agg["contract_fail"] + agg["semantic_fail"] + agg["scope_violation"]
    return 1 if hard else 0


if __name__ == "__main__":
    raise SystemExit(main())
