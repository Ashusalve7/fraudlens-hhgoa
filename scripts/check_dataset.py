#!/usr/bin/env python3
"""Validate the sponsor dataset before graph or model construction."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import pyarrow.csv as pv

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA = ROOT / "HHGOA_IEEE"
EXPECTED = {
    "transactions.csv": 590_742,
    "identity.csv": 144_432,
    "closed_cases_history.csv": 5_565,
    "case_pack.csv": 20,
}


def csv_rows(path: Path) -> int:
    if path.stat().st_size < 20_000_000:
        with path.open(newline="", encoding="utf-8") as handle:
            return max(sum(1 for _ in csv.reader(handle)) - 1, 0)
    return pv.open_csv(path).read_all().num_rows


def load_csv_dicts(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--json", action="store_true", help="Emit machine-readable output")
    args = parser.parse_args()
    data = args.data_dir.resolve()
    report: dict[str, object] = {"data_dir": str(data), "files": {}, "errors": []}
    errors: list[str] = report["errors"]  # type: ignore[assignment]

    for name, expected in EXPECTED.items():
        path = data / name
        if not path.is_file():
            errors.append(f"missing file: {name}")
            continue
        try:
            rows = csv_rows(path)
        except Exception as exc:  # noqa: BLE001  # pragma: no cover - diagnostic path
            errors.append(f"cannot read {name}: {type(exc).__name__}: {exc}")
            continue
        report["files"][name] = {"rows": rows, "expected": expected, "ok": rows == expected}  # type: ignore[index]
        if rows != expected:
            errors.append(f"{name}: expected {expected:,} rows, found {rows:,}")

    if not errors:
        transactions = load_csv_dicts(data / "case_pack.csv")
        txn_table = pv.read_csv(
            data / "transactions.csv",
            read_options=pv.ReadOptions(use_threads=True),
            convert_options=pv.ConvertOptions(include_columns=["TransactionID"]),
        )
        txn_ids = {str(value) for value in txn_table.column("TransactionID").to_pylist()}
        missing = [row["case_id"] for row in transactions if str(row["flagged_txn_id"]) not in txn_ids]
        if missing:
            errors.append(f"case-pack flagged transactions missing from source: {missing}")
        report["case_pack_ids_unique"] = len({row["case_id"] for row in transactions}) == len(transactions)
        report["flagged_transactions_exist"] = not missing

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        for name, info in report["files"].items():  # type: ignore[union-attr]
            print(f"{name}: {info['rows']:,} rows ({'OK' if info['ok'] else 'MISMATCH'})")
        for error in errors:
            print(f"ERROR: {error}")
        if not errors:
            print("Dataset validation passed.")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
