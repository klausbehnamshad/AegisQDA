"""Read-only adapter replacement for the pinned CLI's ``ollama list`` probe."""

from __future__ import annotations

import os
import sys
from typing import Sequence

# When invoked directly, the script directory resolves this consumer-owned
# module. The adapter's PYTHONPATH also installs it at interpreter startup.
from sitecustomize import _bound_list  # type: ignore[import-not-found]


def main(arguments: Sequence[str] | None = None) -> int:
    arguments = sys.argv[1:] if arguments is None else arguments
    if list(arguments) != ["list"]:
        print("AegisQDA inventory wrapper supports only the read-only list operation", file=sys.stderr)
        return 2
    try:
        _bound_list()
    except Exception:
        print("AegisQDA bound local model inventory is unavailable or invalid", file=sys.stderr)
        return 2
    # The upstream readiness parser only consumes the first column. Report
    # solely the selected, already digest-bound model, never arbitrary labels.
    print("NAME\tID\tSIZE\tMODIFIED")
    print(f"{os.environ['AEGISQDA_APPROVED_MODEL']}\t{os.environ['AEGISQDA_APPROVED_MODEL_DIGEST'][:12]}\tlocal\tlocal")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
