"""Build inference-identical labeled features for offline evaluation.

The historical feature table is reconstructed with the same functions used by
``agent.features`` and ``agent.decision``.  Every case is cut at its
``opened_at`` timestamp; a later transaction cannot become historical evidence
merely because it appears in the source table.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from typing import Any

# Allow ``python eval/build_features.py`` as well as ``import eval.build_features``.
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import numpy as np
import pandas as pd
import pyarrow.csv as pv

HERE = Path(__file__).resolve().parent
DATA = HERE.parent.parent / "HHGOA_IEEE"
OUT = HERE / "out"
OUT.mkdir(exist_ok=True)

try:
    from agent.decision import detect_pattern
    from agent.episodes import build_episode
    from agent.features import compute_features, episode_features
except ImportError:  # package context
    from agent.decision import detect_pattern  # type: ignore
    from agent.episodes import build_episode  # type: ignore
    from agent.features import compute_features, episode_features  # type: ignore

FEATURES = [
    "flagged_amount", "flagged_online", "flagged_risk", "n_small_auth_1h",
    "amt_ratio_30d", "product_new", "new_dev_share_24h", "proxy_share_24h",
    "device_shared_cards_7d", "region_new", "region_new_n_72h", "home_active_72h",
    "online_share_shift", "pemail_changed", "m1_not_T", "n_txn_24h",
]
TXN_COLS = ["TransactionID", "ts", "TransactionAmt", "ProductCD", "channel", "risk_score", "addr1", "addr2", "P_emaildomain", "M1"]


def device_profile_id(device_info: Any, os_: Any, browser: Any, screen: Any) -> str:
    key = "|".join(str(x) for x in (device_info, os_, browser, screen))
    return "DP-" + hashlib.md5(key.encode()).hexdigest()[:12]


def _as_datetime(value: Any) -> pd.Timestamp:
    return pd.Timestamp(value)


def _clean(value: Any) -> str:
    return "" if pd.isna(value) or str(value) in {"nan", "None"} else str(value)


def _load_transactions() -> pd.DataFrame:
    need = ["TransactionID", "ts", "TransactionAmt", "ProductCD", "channel", "risk_score", "addr1", "addr2", "P_emaildomain", "M1"]
    frames: list[pd.DataFrame] = []
    with pv.open_csv(DATA / "transactions.csv") as reader:
        for batch in reader:
            available = set(batch.schema.names)
            frames.append(batch.select([c for c in need if c in available]).to_pandas())
    tx = pd.concat(frames, ignore_index=True)
    del frames
    ident = pd.read_csv(
        DATA / "identity.csv",
        low_memory=False,
        usecols=["TransactionID", "id_15", "id_23", "DeviceInfo", "id_30", "id_31", "id_33"],
    )
    for col in ("id_15", "id_23", "DeviceInfo", "id_30", "id_31", "id_33"):
        ident[col] = ident[col].fillna("").astype(str).replace("nan", "")
    ident["device_id"] = [
        device_profile_id(a, b, c, d)
        for a, b, c, d in zip(ident["DeviceInfo"], ident["id_30"], ident["id_31"], ident["id_33"])
    ]
    tx = tx.merge(ident[["TransactionID", "id_15", "id_23", "device_id"]], on="TransactionID", how="left")
    card_map = pd.read_parquet(HERE.parent / "pipeline" / "out" / "txn_card_map.parquet")
    tx = tx.merge(card_map[["TransactionID", "card_id", "customer_id"]], on="TransactionID", how="inner")
    tx["ts"] = pd.to_datetime(tx["ts"], errors="coerce")
    tx["amount"] = pd.to_numeric(tx["TransactionAmt"], errors="coerce").fillna(0.0)
    tx["addr1"] = tx["addr1"].fillna("").astype(str).replace("nan", "")
    tx["id_15"] = tx["id_15"].fillna("").astype(str).replace("nan", "")
    tx["id_23"] = tx["id_23"].fillna("").astype(str).replace("nan", "")
    tx["device_id"] = tx["device_id"].fillna("").astype(str).replace("nan", "")
    tx = tx.sort_values(["card_id", "ts"], kind="stable").reset_index(drop=True)
    return tx


def _row_dict(row: pd.Series) -> dict[str, Any]:
    return {str(k): (None if pd.isna(v) else v) for k, v in row.to_dict().items()}


def build_feature_table() -> pd.DataFrame:
    tx = _load_transactions()
    groups = {str(card): group.reset_index(drop=True) for card, group in tx.groupby("card_id", sort=False)}
    device_groups = {
        str(device): group.reset_index(drop=True)
        for device, group in tx[tx["device_id"] != ""].groupby("device_id", sort=False)
    }
    history = pd.read_csv(DATA / "closed_cases_history.csv", low_memory=False)
    history["opened_at"] = pd.to_datetime(history["opened_at"], errors="coerce")
    history["device_ids"] = [
        tuple(sorted(set(tx.loc[tx["TransactionID"].isin([int(v) for v in str(t).split("|") if str(v).isdigit()]), "device_id"]) - {""}))
        for t in history["txn_ids"].fillna("")
    ]
    device_prior_cases: dict[str, list[dict[str, Any]]] = {}
    for _, case in history.iterrows():
        for device in case["device_ids"]:
            device_prior_cases.setdefault(str(device), []).append({
                "case_id": str(case["case_id"]),
                "outcome": str(case["outcome"]),
                "pattern": str(case["pattern"]),
                "opened_at": case["opened_at"],
            })
    for cases in device_prior_cases.values():
        cases.sort(key=lambda r: r["opened_at"])

    rows: list[dict[str, Any]] = []
    for _, case in history.iterrows():
        opened = case["opened_at"]
        if pd.isna(opened):
            continue
        ids = [int(v) for v in str(case["txn_ids"]).split("|") if str(v).strip().isdigit()]
        if not ids:
            continue
        card = groups.get(str(case["card_id"]))
        if card is None:
            continue
        flagged = card[card["TransactionID"].isin(ids)]
        if flagged.empty:
            continue
        t0 = flagged.iloc[0]["ts"]
        if pd.isna(t0) or t0 > opened:
            # A future flagged transaction cannot be evaluated retrospectively.
            continue
        t0_row = flagged.iloc[0]
        # The case's first listed transaction is the detector trigger, matching
        # the runner's flagged transaction contract.
        t0_id = int(t0_row["TransactionID"])
        card_rows = card[(card["ts"] >= t0 - pd.Timedelta(days=60)) & (card["ts"] <= opened)].copy()
        device_id = str(t0_row.get("device_id", "") or "")
        dev: dict[str, Any] = {"txns": [], "cards": [], "customers": [], "prior_cases": []}
        if device_id and device_id in device_groups:
            dg = device_groups[device_id]
            near = dg[(dg["ts"] >= t0 - pd.Timedelta(days=7)) & (dg["ts"] <= opened)]
            dev["txns"] = [_row_dict(r) for _, r in near.iterrows()]
            dev["cards"] = [{"card_id": str(v)} for v in sorted(near["card_id"].dropna().astype(str).unique())]
            dev["customers"] = [{"customer_id": str(v)} for v in sorted(near["customer_id"].dropna().astype(str).unique())]
            dev["prior_cases"] = [
                dict(r) for r in device_prior_cases.get(device_id, [])
                if pd.notna(r["opened_at"]) and r["opened_at"] <= opened and r["case_id"] != str(case["case_id"])
            ]
        ctx = {"txn": _row_dict(t0_row), "card": {"card_id": str(case["card_id"])}}
        feats = compute_features(ctx, [_row_dict(r) for _, r in card_rows.iterrows()], dev, opened_at=opened)
        preliminary = build_episode(ctx["txn"], [_row_dict(r) for _, r in card_rows.iterrows()], "none", feats, cutoff=opened)
        ep = episode_features(preliminary, [_row_dict(r) for _, r in card_rows.iterrows()], t0.to_pydatetime())
        for key in ("n_online_48h", "online_burst_48h", "testing_sequence", "testing_large_amount", "new_device_share", "proxy_share", "mixed_channel", "identity_anomaly", "near_threshold_burst_40m", "trip_like", "coordinated"):
            if key in ep:
                feats[key] = ep[key]
        # Device corroboration is an explicit production detector signal.
        confirmed_priors = [r for r in dev["prior_cases"] if str(r.get("outcome")) == "confirmed_fraud"]
        feats["connected_fraud_cases"] = len(confirmed_priors)
        feats["connected_corroboration"] = int(bool(confirmed_priors and len(dev["cards"]) > 1))
        feats["cross_customer"] = int(len(dev["customers"]) > 1)
        feats["coordinated_signal"] = int(feats["connected_corroboration"] and len(dev["cards"]) > 1)
        predicted, _why = detect_pattern(feats, ep)
        visible_ids = set(int(v) for v in card_rows["TransactionID"].dropna().astype(int))
        visible_episode = card_rows[card_rows["TransactionID"].isin(ids) & card_rows["TransactionID"].isin(visible_ids)]
        exposure = float(visible_episode["amount"].abs().sum())
        row: dict[str, Any] = {
            "case_id": str(case["case_id"]),
            "customer_id": str(case["customer_id"]),
            "card_id": str(case["card_id"]),
            "outcome": str(case["outcome"]),
            "pattern": str(case["pattern"]),
            "predicted_pattern": predicted,
            "pattern_rule_correct": int(predicted == str(case["pattern"])),
            "report_filed": str(case["report_filed"]).lower() == "yes",
            "opened_at": opened,
            "flagged_txn_id": t0_id,
            "n_episode": int(len(visible_episode)),
            "exposure": exposure,
            "ep_max": float(visible_episode["amount"].abs().max()) if len(visible_episode) else 0.0,
        }
        for key in FEATURES:
            row[key] = float(feats.get(key, 0.0)) if key not in {"flagged_online", "product_new", "region_new", "home_active_72h", "pemail_changed", "m1_not_T", "n_txn_24h", "n_small_auth_1h"} else int(feats.get(key, 0))
        for key in ("coordinated_signal", "cross_customer", "connected_corroboration", "connected_fraud_cases", "near_threshold_burst_40m"):
            row[key] = int(feats.get(key, 0))
        rows.append(row)
    return pd.DataFrame(rows)


def main() -> None:
    frame = build_feature_table()
    frame.to_parquet(OUT / "case_features.parquet", index=False)
    print(f"feature rows: {len(frame):,}")
    if len(frame):
        print(f"outcome: {frame['outcome'].value_counts().to_dict()}")
        print(f"pattern: {frame['pattern'].value_counts().to_dict()}")
        print(f"production pattern agreement: {frame['pattern_rule_correct'].mean():.4f}")


if __name__ == "__main__":
    main()
