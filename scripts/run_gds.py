#!/usr/bin/env python3
"""Run one documented, read-only TigerGraph GDS degree-centrality job."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "fraudlens"
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

DEFAULT_OUTPUT = ROOT / "fraudlens" / "pipeline" / "out" / "gds_degree_centrality.json"


def _json_result(raw: str) -> dict:
    marker = "------Running query------"
    candidate = raw[raw.find(marker) + len(marker) :] if marker in raw else raw
    start = candidate.find("{")
    if start < 0:
        raise ValueError("GDS response did not contain JSON")
    value, _ = json.JSONDecoder().raw_decode(candidate[start:])
    if not isinstance(value, dict):
        raise TypeError("GDS response was not an object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--top-k", type=int, default=10)
    args = parser.parse_args()
    if not 1 <= args.top_k <= 100:
        raise SystemExit("--top-k must be between 1 and 100")

    from pipeline.tg import get_conn

    command = (
        "USE GRAPH FraudGraph\n"
        "CALL GDBMS_ALGO.centrality.degree_cent("
        '["DeviceProfile"],["FROM_DEVICE"],["rev_FROM_DEVICE"],'
        f"true,true,{args.top_k},true,\"\",\"\",true)"
    )
    try:
        raw = str(get_conn().gsql(command))
        result = _json_result(raw)
        scores = result.get("results", [{}])[0].get("top_scores", [])
        if not isinstance(scores, list) or not scores:
            raise ValueError("GDS returned no top scores")
    except Exception as exc:  # noqa: BLE001 - provider boundary must degrade safely
        print(f"GDS unavailable: {type(exc).__name__}", file=sys.stderr)
        return 2

    report = {
        "algorithm": "GDBMS_ALGO.centrality.degree_cent",
        "vertex_type": "DeviceProfile",
        "edge_type": "FROM_DEVICE",
        "reverse_edge_type": "rev_FROM_DEVICE",
        "directed": True,
        "normalized": True,
        "top_k": args.top_k,
        "scores": [
            {"vertex_id": str(row.get("Vertex_ID", "")), "score": float(row.get("score", 0.0))}
            for row in scores
            if isinstance(row, dict)
        ],
        "scope": "global graph; not a case-cutoff result",
        "used_in_decision": False,
        "provenance": {
            "source": "TigerGraph packaged GDS query",
            "package": "GDBMS_ALGO.centrality",
            "query": "degree_cent",
            "ran_at": datetime.now(UTC).isoformat(),
        },
        "note": (
            "This global ranking is an offline graph-quality signal. Case decisions continue "
            "to use bounded observed evidence and deterministic policy."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
