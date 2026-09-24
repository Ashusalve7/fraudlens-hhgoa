"""Derive and validate the FraudLens card map.

The source transactions do not contain ``card_id``.  The validated rule is:

    identity = (card1, card4, card6), with missing values represented by _NA_
    K = one-based rank of identity in the customer's sorted identities
    card_id = <customer_id>-K<K>

This script is intentionally deterministic and fails before writing an
incomplete map.  It validates both the flagged transaction for every labeled
case and every transaction listed in every closed case.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd
import pyarrow.csv as pv

HERE = Path(__file__).resolve().parent
DATA = HERE.parent.parent / "HHGOA_IEEE"
OUT = HERE / "out"
OUT.mkdir(parents=True, exist_ok=True)
FIELDS = ["card1", "card4", "card6"]
MISSING = "_NA_"


def _normalise(series: pd.Series) -> pd.Series:
    """Use one canonical spelling for every card-identity component."""
    text = series.astype("string").str.strip()
    empty = text.isna() | text.str.lower().isin({"", "nan", "none", "<na>", "_na_"})
    return text.mask(empty, MISSING)


def _as_txn_ids(series: pd.Series) -> list[str]:
    values: list[str] = []
    for value in series.dropna():
        # Case transaction lists are pipe-delimited; normalize numeric-looking
        # CSV values without turning a list into one synthetic ID.
        for raw in str(value).split("|"):
            text = raw.strip()
            if not text or text.lower() in {"nan", "none"}:
                continue
            try:
                # IDs in this dataset are integer-like, but retain a nonnumeric
                # ID rather than coercing it to a float representation.
                if text.endswith(".0") and text[:-2].isdigit():
                    text = text[:-2]
                values.append(text)
            except Exception:
                continue
    return values


def _atomic_parquet(frame: pd.DataFrame, path: Path) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    frame.to_parquet(temporary, index=False)
    os.replace(temporary, path)


def _atomic_json(value: object, path: Path) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, default=str), encoding="utf-8")
    os.replace(temporary, path)


def load_transactions() -> pd.DataFrame:
    columns = ["TransactionID", "ts", "TransactionDT", "customer_id"] + FIELDS
    chunks: list[pd.DataFrame] = []
    with pv.open_csv(DATA / "transactions.csv") as reader:
        for batch in reader:
            chunks.append(batch.select(columns).to_pandas())
    if not chunks:
        raise RuntimeError("transactions.csv produced no batches")
    tx = pd.concat(chunks, ignore_index=True)
    if tx["TransactionID"].duplicated().any():
        raise ValueError("transactions.csv contains duplicate TransactionID values")
    tx["TransactionID"] = tx["TransactionID"].astype(str)
    tx["ts"] = pd.to_datetime(tx["ts"], errors="raise")
    for field in FIELDS:
        tx[field] = _normalise(tx[field])
    return tx


def build_map(tx: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    normalized = tx.copy()
    normalized["customer_id"] = normalized["customer_id"].astype(str).str.strip()
    if (normalized["customer_id"] == "").any():
        raise ValueError("transactions contain an empty customer_id")
    for field in FIELDS:
        normalized[field] = _normalise(normalized[field])
    identities = (
        normalized.groupby(["customer_id"] + FIELDS, sort=False, dropna=False)
        .agg(first_ts=("ts", "min"), n_txn=("ts", "size"))
        .reset_index()
        .sort_values(["customer_id"] + FIELDS, kind="stable")
    )
    identities["k"] = identities.groupby("customer_id", sort=False).cumcount() + 1
    identities["card_id"] = identities["customer_id"].astype(str) + "-K" + identities["k"].astype(str)
    if identities["card_id"].duplicated().any():
        raise ValueError("card_id collision in derived map")

    tx_map = normalized.merge(
        identities[["customer_id"] + FIELDS + ["card_id"]],
        on=["customer_id"] + FIELDS,
        how="left",
        validate="many_to_one",
    )
    if tx_map["card_id"].isna().any():
        raise ValueError(f"unmapped transactions: {int(tx_map['card_id'].isna().sum())}")
    if tx_map["TransactionID"].duplicated().any():
        raise ValueError("transaction-to-card map is not one-to-one")
    result = tx_map[["TransactionID", "customer_id", "card_id"] + FIELDS].copy()
    for column in ("TransactionID", "customer_id", "card_id", *FIELDS):
        result[column] = result[column].astype(str)
    result = result.sort_values("TransactionID", kind="stable").reset_index(drop=True)
    return identities, result


def validate_cases(tx_map: pd.DataFrame, identities: pd.DataFrame) -> dict[str, object]:
    cc = pd.read_csv(
        DATA / "closed_cases_history.csv",
        usecols=["case_id", "customer_id", "card_id", "first_fraud_txn_id", "txn_ids", "outcome"],
        low_memory=False,
    )
    if cc["case_id"].duplicated().any():
        raise ValueError("closed_cases_history.csv contains duplicate case_id values")
    by_txn = tx_map.set_index("TransactionID")["card_id"].to_dict()

    flagged_hits = flagged_total = 0
    for value in cc["first_fraud_txn_id"].dropna():
        for txn_id in _as_txn_ids(pd.Series([value])):
            flagged_total += 1
            if by_txn.get(txn_id) is not None:
                row = cc.loc[cc["first_fraud_txn_id"].astype("string") == str(value)]
                if len(row) and str(row.iloc[0]["card_id"]) == by_txn[txn_id]:
                    flagged_hits += 1

    listed_hits = listed_total = 0
    mismatched: list[dict[str, object]] = []
    for _, case in cc.iterrows():
        expected = str(case["card_id"])
        ids = _as_txn_ids(pd.Series([case.get("txn_ids", "")]))
        hits = 0
        for txn_id in ids:
            predicted = by_txn.get(txn_id)
            if predicted is not None:
                listed_total += 1
                if predicted == expected:
                    listed_hits += 1
                    hits += 1
        if ids and hits != sum(txn_id in by_txn for txn_id in ids):
            mismatched.append({
                "case_id": str(case["case_id"]),
                "expected_card_id": expected,
                "matched": hits,
                "listed": len(ids),
            })

    known_cards = set(identities["card_id"].astype(str))
    connected_bad = 0
    connected_total = 0
    for value in cc.get("connected_card_ids", pd.Series(dtype="string")).dropna():
        for card_id in str(value).split("|"):
            card_id = card_id.strip()
            if card_id and card_id != "nan":
                connected_total += 1
                connected_bad += int(card_id not in known_cards)

    report = {
        "rule": "card_id = customer_id + '-K' + rank of (card1,card4,card6) in customer's sorted identities",
        "identity_fields": FIELDS,
        "missing_value": MISSING,
        "n_transactions": int(len(tx_map)),
        "n_cards": int(len(identities)),
        "n_customers": int(identities["customer_id"].nunique()),
        "validation_flagged": {
            "hits": int(flagged_hits),
            "total": int(flagged_total),
            "acc": float(flagged_hits / flagged_total) if flagged_total else 0.0,
        },
        "validation_all_txns": {
            "hits": int(listed_hits),
            "total": int(listed_total),
            "acc": float(listed_hits / listed_total) if listed_total else 0.0,
            "bad_cases": len(mismatched),
            "mismatches": mismatched[:20],
        },
        "validation_connected_cards": {
            "known": int(connected_total - connected_bad),
            "total": int(connected_total),
            "unknown": int(connected_bad),
        },
    }
    if flagged_total and flagged_hits != flagged_total:
        raise ValueError(f"flagged card validation failed: {flagged_hits}/{flagged_total}")
    if listed_total and listed_hits != listed_total:
        raise ValueError(f"case transaction card validation failed: {listed_hits}/{listed_total}")
    if connected_bad:
        raise ValueError(f"unknown connected card IDs: {connected_bad}/{connected_total}")
    return report


def main() -> int:
    tx = load_transactions()
    identities, tx_map = build_map(tx)
    report = validate_cases(tx_map, identities)
    _atomic_parquet(tx_map, OUT / "txn_card_map.parquet")
    _atomic_parquet(identities, OUT / "card_map.parquet")
    _atomic_json(report, OUT / "card_rule_report.json")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
