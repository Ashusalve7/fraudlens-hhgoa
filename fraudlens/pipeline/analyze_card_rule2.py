"""D-1c: test card-identity key candidates (card1 / card1+2 / card1+2+3 / card2...) x orderings."""
from __future__ import annotations

from pathlib import Path
from itertools import product

import pandas as pd
import pyarrow.csv as pv

HERE = Path(__file__).resolve().parent
DATA = HERE.parent.parent / "HHGOA_IEEE"

cc = pd.read_csv(DATA / "closed_cases_history.csv",
                 usecols=["case_id", "customer_id", "card_id", "first_fraud_txn_id"])
refs = cc.dropna(subset=["customer_id", "card_id", "first_fraud_txn_id"]).copy()
refs["k_index"] = refs["card_id"].str.extract(r"-K(\d+)$").astype("Int64")
refs = refs.dropna(subset=["k_index"])
need_customers = set(refs["customer_id"])
need_txns = {int(x) for x in refs["first_fraud_txn_id"].astype("int64")}

cols = ["TransactionID", "TransactionDT", "ts", "customer_id", "card1", "card2", "card3", "card4", "card5", "card6"]
rows = []
with pv.open_csv(DATA / "transactions.csv") as reader:
    for batch in reader:
        df = batch.select(cols).to_pandas()
        sel = df[df["customer_id"].isin(need_customers) | df["TransactionID"].isin(need_txns)]
        if len(sel):
            rows.append(sel)
hist = pd.concat(rows, ignore_index=True)
hist["ts"] = pd.to_datetime(hist["ts"], errors="coerce")
flagged = hist[hist["TransactionID"].isin(need_txns)].set_index("TransactionID")

ref_txn = refs.copy()
ref_txn["tid"] = ref_txn["first_fraud_txn_id"].astype("int64")
j = ref_txn.join(flagged[["card1", "card2", "card3", "card4", "card5", "card6"]], on="tid")
print(f"testable: {len(j)}")

for c in ("card1", "card2", "card3"):
    j[c] = j[c].astype("Int64")
    hist[c] = hist[c].astype("Int64")

CANDIDATE_KEYS = {
    "card1": ["card1"],
    "card1+card2": ["card1", "card2"],
    "card1+card2+card3": ["card1", "card2", "card3"],
    "card2": ["card2"],
    "card1+card6": ["card1", "card6"],
}
ORDERINGS = ["first_ts", "sorted"]

def rank_map(hist: pd.DataFrame, key_cols: list[str], ordering: str) -> dict[tuple, int]:
    g = hist.dropna(subset=key_cols).groupby(["customer_id"] + key_cols, sort=False).agg(
        first_ts=("ts", "min")).reset_index()
    if ordering == "first_ts":
        g = g.sort_values(["customer_id", "first_ts"] + key_cols, kind="stable")
    else:
        g = g.sort_values(["customer_id"] + key_cols, kind="stable")
    g["k"] = g.groupby("customer_id").cumcount() + 1
    idx = set(zip(g["customer_id"], *[g[c] for c in key_cols]))
    return {tuple(r): k for r, k in zip(idx, g["k"])}, g

best = []
for (kname, kcols), o in product(CANDIDATE_KEYS.items(), ORDERINGS):
    rmap, gmap = rank_map(hist, kcols, o)
    hits = total = 0
    for _, r in j.iterrows():
        key = (r["customer_id"],) + tuple(r[c] for c in kcols)
        if any(pd.isna(x) for x in key):
            continue
        total += 1
        hits += int(rmap.get(key) == r["k_index"])
    acc = hits / total if total else 0
    best.append((acc, kname, o, hits, total))
    print(f"key={kname:20s} order={o:9s} -> {hits}/{total} = {acc:.4f}")

best.sort(reverse=True)
print(f"\nBEST: key={best[0][1]} order={best[0][2]} acc={best[0][0]:.4f}")

# inspect the 19 conflicts under the best key: are they resolved?
acc, kname, o, hits, total = best[0]
kcols = CANDIDATE_KEYS[kname]
rmap, gmap = rank_map(hist, kcols, o)
j["pred_k"] = [rmap.get((r["customer_id"],) + tuple(r[c] for c in kcols)) for _, r in j.iterrows()]
bad = j[j["pred_k"] != j["k_index"]]
print(f"misses under best rule: {len(bad)}")
if len(bad):
    print(bad[["case_id", "customer_id", "card_id", "k_index", "pred_k"] + kcols].head(15).to_string(index=False))
