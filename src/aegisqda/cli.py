"""Stable command-line entry point for the local fail-closed gateway."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .digqda_adapter import analyze_run
from .doctor import doctor_report
from .errors import AegisError
from .review_signature import create_review_key
from .workflow import interactive_review, scan_source, transform_run

DEFAULT_RUN_ROOT = Path("/private/tmp/aegisqda-runs")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aegisqda",
        description="Local-only, human-gated privacy gateway for pinned DigQDA",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="read-only local boundary and dependency checks")
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
    keygen = sub.add_parser("keygen-review", help="create an external local Ed25519 review key")
    keygen.add_argument("path", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "doctor":
            report, ready = doctor_report()
            print(json.dumps(report, indent=2, sort_keys=True))
            return 0 if ready else 2
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
    except (OSError, ValueError, RuntimeError):
        print("BLOCKED: unexpected local processing failure (details suppressed)", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
