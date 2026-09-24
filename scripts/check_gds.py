#!/usr/bin/env python3
"""Check optional TigerGraph GDS package availability without mutating the graph."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "fraudlens"
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="write a small JSON availability report")
    args = parser.parse_args()

    from pipeline.tg import get_conn

    try:
        response = get_conn().gsql("SHOW PACKAGE GDBMS_ALGO")
    except Exception as exc:  # noqa: BLE001 - provider boundary must degrade safely
        report = {
            "available": False,
            "package": "GDBMS_ALGO",
            "error_type": type(exc).__name__,
            "error": "optional GDS package check unavailable",
            "note": "The deterministic bounded graph algorithm layer remains the release fallback.",
        }
        print(json.dumps(report, indent=2))
        if args.output:
            args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        return 2

    rendered = str(response)
    available = "GDBMS_ALGO" in rendered and "error" not in rendered.lower()
    report = {
        "available": available,
        "package": "GDBMS_ALGO",
        "response_received": True,
        "note": (
            "Package presence is not an algorithm result; record the exact packaged query "
            "and output hash before claiming a GDS run."
        ),
    }
    print(json.dumps(report, indent=2))
    if args.output:
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0 if available else 2


if __name__ == "__main__":
    raise SystemExit(main())
