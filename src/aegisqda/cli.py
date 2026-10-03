"""Stable command-line entry point for the local fail-closed gateway."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .digqda_adapter import analyze_run
from .doctor import doctor_report
from .errors import AegisError
from .output_review import _terminal_text, finalize_output_review, interactive_output_review
from .review_signature import create_review_key
from .workflow import interactive_review, scan_source, transform_run
from .workbench import (
    METHODS, apply_code, declare_method, define_code, research_summary, write_memo,
)

DEFAULT_RUN_ROOT = Path("/private/tmp/aegisqda-runs")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aegisqda",
        description="Local synthetic DH research workbench with human-gated privacy and pinned DigQDA",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="read-only local boundary and dependency checks")
    inventory = sub.add_parser("detector-inventory", help="fingerprint installed local detector assets; no qualification claim")
    inventory.add_argument("--language", required=True, choices=("de", "fr", "en", "lb"))
    verify = sub.add_parser("verify", help="read-only offline verification of a protected synthetic run")
    verify.add_argument("run_dir", type=Path)
    for name in ("scan", "run"):
        command = sub.add_parser(name, help="scan a synthetic source and stop for review")
        command.add_argument("source", type=Path)
        command.add_argument("--language", required=True, choices=("de", "fr", "lb", "en"))
        command.add_argument("--case-id", required=True)
        command.add_argument("--run-root", type=Path, default=DEFAULT_RUN_ROOT)
        command.add_argument(
            "--synthetic",
            action="store_true",
            help="required synthetic-data assertion; real-data authorization is not implemented",
        )
    review = sub.add_parser("review", help="perform protected local terminal review")
    review.add_argument("run_dir", type=Path)
    review.add_argument("--reviewer", required=True, help="opaque reviewer ID")
    review.add_argument("--signing-key", type=Path, help="owner-only external Ed25519 private key")
    transform = sub.add_parser("transform", help="transform only after accepted review")
    transform.add_argument("run_dir", type=Path)
    analyze = sub.add_parser("analyze", help="invoke pinned DigQDA only after privacy release")
    analyze.add_argument("run_dir", type=Path)
    analyze.add_argument("--model")
    output_review = sub.add_parser("review-output", help="signed protected review of blocked synthetic model output")
    output_review.add_argument("run_dir", type=Path)
    output_review.add_argument("--attempt-id", required=True)
    output_review.add_argument("--reviewer", required=True, help="opaque reviewer ID")
    output_review.add_argument("--signing-key", required=True, type=Path)
    finalize = sub.add_parser("finalize-output-review", help="revalidate exact signed output decisions; retain methodological review")
    finalize.add_argument("run_dir", type=Path)
    finalize.add_argument("--attempt-id", required=True)
    keygen = sub.add_parser("keygen-review", help="create an external local Ed25519 review key")
    keygen.add_argument("path", type=Path)
    audit = sub.add_parser("audit", help="read-only audit of current or legacy protected runs")
    audit.add_argument("run_dir", type=Path)
    plan = sub.add_parser("review-plan", help="show source-free overlapping finding groups before human review")
    plan.add_argument("run_dir", type=Path)
    for name, help_text in (
        ("qda-segments", "list evidence segment IDs, positions and hashes without text"),
        ("qda-search", "search source segments with a protected interactive query"),
        ("qda-evidence", "display one protected source-bound segment locally"),
        ("qda-dissent", "show explicit analyst differences on identical evidence spans"),
    ):
        command = sub.add_parser(name, help=help_text)
        command.add_argument("run_dir", type=Path)
        if name == "qda-evidence":
            command.add_argument("--segment-id", required=True)
    workspace_init = sub.add_parser("qda-workspace-init", help="create an external protected synthetic multi-case workspace")
    workspace_init.add_argument("workspace", type=Path)
    workspace_add = sub.add_parser("qda-workspace-add", help="register a released synthetic case with an immutable release binding")
    workspace_add.add_argument("workspace", type=Path)
    workspace_add.add_argument("run_dir", type=Path)
    workspace_add.add_argument("--case-id", required=True)
    matrix = sub.add_parser("qda-matrix", help="show source-free case-by-code counts from compatible research cases")
    matrix.add_argument("workspace", type=Path)
    for name, help_text in (
        ("qda-init", "declare the research method for a synthetic released run"),
        ("qda-codebook", "define a versioned hierarchical code locally"),
        ("qda-code", "record a human coding decision bound to source evidence"),
        ("qda-memo", "record a protected source-bound reflexive memo"),
        ("qda-summary", "show source-free coding counts and overlap co-occurrences"),
    ):
        command = sub.add_parser(name, help=help_text)
        command.add_argument("run_dir", type=Path)
        if name != "qda-summary":
            command.add_argument("--analyst", required=True, help="opaque analyst ID")
        if name == "qda-init":
            command.add_argument("--method", required=True, choices=sorted(METHODS))
        if name in {"qda-codebook", "qda-code"}:
            command.add_argument("--code-id", required=True)
        if name == "qda-codebook":
            command.add_argument("--parent-id")
        if name in {"qda-code", "qda-memo"}:
            command.add_argument("--start", required=True, type=int)
            command.add_argument("--end", required=True, type=int)
        if name == "qda-memo":
            command.add_argument("--code-id")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "doctor":
            report, ready = doctor_report()
            print(json.dumps(report, indent=2, sort_keys=True))
            return 0 if ready else 2
        if args.command == "detector-inventory":
            from .detector_inventory import detector_inventory

            print(json.dumps(detector_inventory(args.language), indent=2, sort_keys=True))
            return 0
        if args.command == "verify":
            from .offline_verifier import verify_run

            report = verify_run(args.run_dir)
            print(json.dumps(report, indent=2, sort_keys=True))
            return 0 if report.get("status") == "SYNTHETIC_VERIFIED" else 2
        if args.command == "audit":
            from .audit import audit_run

            report = audit_run(args.run_dir)
            print(json.dumps(report, indent=2, sort_keys=True))
            return 0 if report.get("status") == "CURRENT" else 2
        if args.command == "review-plan":
            from .review_plan import review_plan

            print(json.dumps(review_plan(args.run_dir), indent=2, sort_keys=True))
            return 0
        if args.command in {"qda-workspace-init", "qda-workspace-add", "qda-matrix"}:
            from .research_workspace import add_case, create_workspace, workspace_summary

            if args.command == "qda-workspace-init":
                create_workspace(args.workspace)
                print("UNKEYED_SYNTHETIC_WORKSPACE_CREATED")
            elif args.command == "qda-workspace-add":
                path = add_case(args.workspace, args.run_dir, args.case_id)
                print(f"CASE_REGISTERED event={path.name}")
            else:
                print(json.dumps(workspace_summary(args.workspace), indent=2, sort_keys=True))
            return 0
        if args.command in {"qda-segments", "qda-search", "qda-evidence", "qda-dissent"}:
            from .workbench_queries import analyst_dissent, list_segments, read_segment, search_segments

            if args.command == "qda-evidence":
                text = read_segment(args.run_dir, args.segment_id)
                print("PROTECTED LOCAL EVIDENCE — no external privacy release")
                print(_terminal_text(text[:8000]))
                if len(text) > 8000:
                    print("DISPLAY_TRUNCATED after 8000 characters")
                return 0
            if args.command == "qda-segments":
                report = list_segments(args.run_dir)
            elif args.command == "qda-search":
                report = search_segments(args.run_dir, input("Protected local search query: "))
            else:
                report = analyst_dissent(args.run_dir)
            print(json.dumps(report, indent=2, sort_keys=True))
            return 0
        if args.command.startswith("qda-"):
            if args.command == "qda-summary":
                print(json.dumps(research_summary(args.run_dir), indent=2, sort_keys=True))
                return 0
            if args.command == "qda-init":
                path = declare_method(args.run_dir, args.analyst, args.method)
            else:
                print("PROTECTED LOCAL RESEARCH — text stays in the protected run directory")
                if args.command == "qda-codebook":
                    path = define_code(
                        args.run_dir, args.analyst, args.code_id,
                        input("code label: "), input("code definition: "), args.parent_id,
                    )
                elif args.command == "qda-code":
                    path = apply_code(
                        args.run_dir, args.analyst, args.code_id, args.start, args.end,
                        input("coding rationale: "),
                    )
                else:
                    path = write_memo(
                        args.run_dir, args.analyst, args.start, args.end,
                        input("reflexive memo: "), args.code_id,
                    )
            print("METHODOLOGICAL_REVIEW_REQUIRED")
            print(f"event={path.name}")
            return 0
        if args.command in {"scan", "run"}:
            run_dir = scan_source(
                args.source,
                language=args.language,
                case_id=args.case_id,
                run_root=args.run_root,
                synthetic=args.synthetic,
            )
            print("REVIEW_REQUIRED")
            print(f"run_dir={run_dir}")
            return 3
        if args.command == "review":
            path = interactive_review(args.run_dir, args.reviewer, args.signing_key)
            print("REVIEW_ACCEPTED")
            print(f"review={path}")
            return 0
        if args.command == "transform":
            path = transform_run(args.run_dir)
            print("PRIVACY_RELEASED")
            print(f"release={path}")
            return 0
        if args.command == "analyze":
            path = analyze_run(args.run_dir, args.model)
            print("DOWNSTREAM_REVIEW_REQUIRED")
            print(f"manifest={path}")
            return 0
        if args.command == "review-output":
            path = interactive_output_review(args.run_dir, args.attempt_id, args.reviewer, args.signing_key)
            print("OUTPUT_REVIEW_ACCEPTED")
            print(f"review={path}")
            return 0
        if args.command == "finalize-output-review":
            path = finalize_output_review(args.run_dir, args.attempt_id)
            print("DOWNSTREAM_REVIEW_REQUIRED")
            print(f"manifest={path}")
            return 0
        if args.command == "keygen-review":
            private, public, key_id = create_review_key(args.path)
            print("REVIEW_KEY_CREATED")
            print(f"private={private}")
            print(f"public={public}")
            print(f"key_id_sha256={key_id}")
            return 0
    except AegisError as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return exc.exit_code
    except (OSError, ValueError, RuntimeError, EOFError):
        print("BLOCKED: unexpected local processing failure (details suppressed)", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
