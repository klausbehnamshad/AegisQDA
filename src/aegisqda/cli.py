"""Fail-closed bootstrap CLI; the MVP stages are intentionally not implemented yet."""

from __future__ import annotations

import argparse


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aegisqda",
        description="Local-only privacy gateway for the pinned DigQDA pipeline",
    )
    parser.add_argument(
        "command",
        choices=("doctor", "scan", "review", "transform", "analyze", "run"),
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    print(
        f"BLOCKED: AegisQDA bootstrap only; command {args.command!r} is not implemented. "
        "Continue with docs/MEGAPROMPT_NEXT_WINDOW.md."
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

