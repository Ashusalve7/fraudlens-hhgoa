#!/usr/bin/env python3
"""Print a compact, human-readable summary of generated benchmark answers."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases-dir", type=Path, default=Path("fraudlens/cases"))
    parser.add_argument("--json", action="store_true", help="emit machine-readable rows")
    args = parser.parse_args()
    rows = []
    for path in sorted(args.cases_dir.glob("HHG-*.json")):
        answer = json.loads(path.read_text(encoding="utf-8"))
        case = answer["case"]
        actions = answer["next_best_actions"]["final"]
        rows.append(
            {
                "case_id": answer["case_id"],
                "verdict": case["verdict"],
                "probability": case["fraud_probability"],
                "pattern": case["pattern"],
                "exposure_usd": case["exposure_usd"],
                "sar": answer["sar"]["file"],
                "actions": [item["action"] for item in actions],
                "routes": sorted({item["route"] for item in actions}),
                "requests": len(answer["evidence_requests"]),
                "similar_cases": case["similar_prior_cases"],
                "affected": case["affected_txn_ids"],
                "tool_calls": answer["tool_calls"],
                "written_to_graph": case["written_to_graph"],
            }
        )
    if args.json:
        print(json.dumps(rows, indent=2))
        return 0
    for row in rows:
        print(
            f"{row['case_id']} {row['verdict']:10s} p={row['probability']:.4f} "
            f"pattern={row['pattern']:28s} exposure=${row['exposure_usd']:9,.2f} "
            f"sar={row['sar']!s:5s} tools={row['tool_calls']} "
            f"graph={row['written_to_graph']} actions={','.join(row['actions'])}"
        )
    print(f"cases={len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
