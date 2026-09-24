"""Build inference-identical labeled features for offline evaluation.

The historical feature table is reconstructed with the same functions used by
``agent.features`` and ``agent.decision``.  Every case is cut at its
``opened_at`` timestamp; a later transaction cannot become historical evidence
merely because it appears in the source table.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

# Allow ``python eval/build_features.py`` as well as ``import eval.build_features``.
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pandas as pd  # noqa: E402
import pyarrow.csv as pv  # noqa: E402

HERE = Path(__file__).resolve().parent
DATA = HERE.parent.parent / "HHGOA_IEEE"
OUT = HERE / "out"

try:
    from agent.decision import MODEL_FEATURES, detect_pattern
    from agent.features import compute_features, episode_features
except ImportError:  # package context
    from agent.decision import MODEL_FEATURES, detect_pattern  # type: ignore
    from agent.features import compute_features, episode_features  # type: ignore

from pipeline.build_load_files import device_profile_id  # noqa: E402

FEATURES = list(MODEL_FEATURES)
TXN_COLS = [
    "TransactionID",
    "ts",
    "TransactionAmt",
    "ProductCD",
    "channel",
    "risk_score",
    "addr1",
    "addr2",
    "P_emaildomain",
    *[f"M{index}" for index in range(1, 10)],
]


def _as_datetime(value: Any) -> pd.Timestamp:
    return pd.Timestamp(value)


def _clean(value: Any) -> str:
    return "" if pd.isna(value) or str(value) in {"nan", "None"} else str(value)


def _id_token(value: Any) -> str:
    text = str(value).strip()
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    return "" if text.lower() in {"", "nan", "none"} else text


def _load_transactions() -> pd.DataFrame:
    need = list(TXN_COLS)
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
        for a, b, c, d in zip(
            ident["DeviceInfo"], ident["id_30"], ident["id_31"], ident["id_33"], strict=True
        )
    ]
    tx = tx.merge(ident[["TransactionID", "id_15", "id_23", "device_id"]], on="TransactionID", how="left")
    card_map = pd.read_parquet(HERE.parent / "pipeline" / "out" / "txn_card_map.parquet")
    tx["TransactionID"] = tx["TransactionID"].astype(str)
    card_map["TransactionID"] = card_map["TransactionID"].astype(str)
    tx = tx.merge(card_map[["TransactionID", "card_id", "customer_id"]], on="TransactionID", how="inner")
    tx["ts"] = pd.to_datetime(tx["ts"], errors="coerce")
    tx["amount"] = pd.to_numeric(tx["TransactionAmt"], errors="coerce").fillna(0.0)
    for column in ("ProductCD", "channel", "addr1", "addr2", "P_emaildomain", "id_15", "id_23", "device_id"):
        tx[column] = tx[column].fillna("").astype(str).replace("nan", "")
    for index in range(1, 10):
        tx[f"M{index}"] = pd.to_numeric(tx[f"M{index}"], errors="coerce")
    tx["m_flags"] = tx[[f"M{index}" for index in range(1, 10)]].apply(
        lambda row: "|".join(
            f"M{index}={int(row[f'M{index}'])}" for index in range(1, 10) if pd.notna(row[f"M{index}"])
        ),
        axis=1,
    )
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
        tuple(
            sorted(
                set(
                    tx.loc[
                        tx["TransactionID"].isin(
                            [_id_token(v) for v in str(t).split("|") if _id_token(v)]
                        ),
                        "device_id",
                    ]
                )
                - {""}
            )
        )
        for t in history["txn_ids"].fillna("")
    ]
    device_prior_cases: dict[str, list[dict[str, Any]]] = {}
    for _, case in history.iterrows():
        for device in case["device_ids"]:
            device_prior_cases.setdefault(str(device), []).append(
                {
                    "case_id": str(case["case_id"]),
                    "outcome": str(case["outcome"]),
                    "pattern": str(case["pattern"]),
                    "opened_at": case["opened_at"],
                }
            )
    for cases in device_prior_cases.values():
        cases.sort(key=lambda r: r["opened_at"])

    rows: list[dict[str, Any]] = []
    for _, case in history.iterrows():
        opened = case["opened_at"]
        if pd.isna(opened):
            continue
        ids = [_id_token(v) for v in str(case["txn_ids"]).split("|") if _id_token(v)]
        if not ids:
            continue
        card = groups.get(str(case["card_id"]))
        if card is None:
            continue
        trigger_id = _id_token(case.get("first_fraud_txn_id"))
        t0_id = trigger_id if trigger_id in ids else ids[0]
        flagged = card[card["TransactionID"].astype(str) == t0_id]
        if flagged.empty:
            continue
        t0 = flagged.iloc[0]["ts"]
        if pd.isna(t0) or t0 > opened:
            # A future flagged transaction cannot be evaluated retrospectively.
            continue
        t0_row = flagged.iloc[0]
        card_rows = card[(card["ts"] >= t0 - pd.Timedelta(days=60)) & (card["ts"] <= opened)].copy()
        device_id = str(t0_row.get("device_id", "") or "")
        dev: dict[str, Any] = {"txns": [], "cards": [], "customers": [], "prior_cases": []}
        if device_id and device_id in device_groups:
            dg = device_groups[device_id]
            near = dg[(dg["ts"] >= t0 - pd.Timedelta(days=7)) & (dg["ts"] <= opened)]
            dev["txns"] = [_row_dict(r) for _, r in near.iterrows()]
            dev["n_cards"] = int(dg["card_id"].nunique())
            dev["cards"] = [
                {"card_id": str(v)} for v in sorted(near["card_id"].dropna().astype(str).unique())
            ]
            dev["customers"] = [
                {"customer_id": str(v)} for v in sorted(near["customer_id"].dropna().astype(str).unique())
            ]
            dev["prior_cases"] = [
                dict(r)
                for r in device_prior_cases.get(device_id, [])
                if pd.notna(r["opened_at"])
                and r["opened_at"] <= opened
                and r["case_id"] != str(case["case_id"])
            ]
        ctx = {
            "txn": _row_dict(t0_row),
            "card": {"card_id": str(case["card_id"])},
            "customer_id": str(case["customer_id"]),
        }
        card_dicts = [_row_dict(row) for _, row in card_rows.iterrows()]
        feats = compute_features(ctx, card_dicts, dev, opened_at=opened)
        ep = episode_features(card_dicts, card_dicts, t0.to_pydatetime(), cutoff=opened)
        for key in (
            "n_online_48h",
            "online_burst_48h",
            "testing_sequence",
            "testing_large_amount",
            "new_device_share",
            "proxy_share",
            "mixed_channel",
            "identity_anomaly",
            "near_threshold_burst_40m",
            "trip_like",
            "coordinated",
        ):
            if key in ep:
                feats[key] = ep[key]
        # Device corroboration is computed by the exact inference helper.  A
        # legacy confirmed case plus generic profile reuse is not enough.
        feats["connected_fraud_cases"] = int(feats.get("connected_fraud_cases", 0))
        feats["connected_corroboration"] = int(feats.get("connected_corroboration", 0))
        feats["cross_customer"] = int(feats.get("cross_customer", 0))
        feats["coordinated_signal"] = int(feats.get("coordinated_signal", 0))
        predicted, _why = detect_pattern(feats, ep)
        visible_ids = set(card_rows["TransactionID"].dropna().astype(str))
        visible_episode = card_rows[
            card_rows["TransactionID"].isin(ids) & card_rows["TransactionID"].isin(visible_ids)
        ]
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
            row[key] = (
                float(feats.get(key, 0.0))
                if key
                not in {
                    "flagged_online",
                    "product_new",
                    "region_new",
                    "home_active_72h",
                    "pemail_changed",
                    "m1_not_T",
                    "n_txn_24h",
                    "n_small_auth_1h",
                }
                else int(feats.get(key, 0))
            )
        for key in (
            "coordinated_signal",
            "cross_customer",
            "connected_corroboration",
            "connected_fraud_cases",
            "near_threshold_burst_40m",
        ):
            row[key] = int(feats.get(key, 0))
        rows.append(row)
    return pd.DataFrame(rows)


def main() -> None:
    frame = build_feature_table()
    OUT.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(OUT / "case_features.parquet", index=False)
    print(f"feature rows: {len(frame):,}")
    if len(frame):
        print(f"outcome: {frame['outcome'].value_counts().to_dict()}")
        print(f"pattern: {frame['pattern'].value_counts().to_dict()}")
        print(f"production pattern agreement: {frame['pattern_rule_correct'].mean():.4f}")


if __name__ == "__main__":
    main()
