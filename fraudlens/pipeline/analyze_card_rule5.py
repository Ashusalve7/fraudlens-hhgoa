"""D-1f: definitive card_id rule search over identity tuples x orderings,
using each customer's FULL transaction history (not just flagged txns)."""
from __future__ import annotations

from pathlib import Path
from itertools import product

import pandas as pd
import pyarrow.csv as pv

HERE = Path(__file__).resolve().parent
DATA = HERE.parent.parent / "HHGOA_IEEE"

cc = pd.read_csv(DATA / "closed_cases_history.csv", usecols=["customer_id", "card_id", "first_fraud_txn_id"])
cc["k"] = cc["card_id"].str.extract(r"-K(\d+)$").astype("Int64")
refs = cc.dropna(subset=["first_fraud_txn_id", "k"]).copy()
need_txns = {int(x) for x in refs["first_fraud_txn_id"].astype("int64")}
need_cust = set(refs["customer_id"])

FIELDS = ["card1", "card2", "card3", "card4", "card5", "card6"]
cols = ["TransactionID", "ts", "TransactionDT", "customer_id"] + FIELDS
chunks = []
with pv.open_csv(DATA / "transactions.csv") as reader:
    for b in reader:
        df = b.select(cols).to_pandas()
        sel = df[df["customer_id"].isin(need_cust) | df["TransactionID"].isin(need_txns)]
        if len(sel):
            chunks.append(sel)
hist = pd.concat(chunks, ignore_index=True)
hist["ts"] = pd.to_datetime(hist["ts"], errors="coerce")
for c in FIELDS:
    hist[c] = hist[c].astype(str).where(hist[c].notna() & (hist[c] != ""), "_NA_")

fl = hist[hist["TransactionID"].isin(need_txns)].set_index("TransactionID")
j = refs.copy()
j["tid"] = j["first_fraud_txn_id"].astype("int64")
j = j.merge(fl[FIELDS], left_on="tid", right_index=True, how="left")
print(f"testable: {len(j)}")

IDENTITIES = {
    "card1": ["card1"],
    "card1+4": ["card1", "card4"],
    "card1+4+5+6": ["card1", "card4", "card5", "card6"],
    "card1+2": ["card1", "card2"],
    "card1+2+3": ["card1", "card2", "card3"],
    "card1+4+6": ["card1", "card4", "card6"],
    "all6": FIELDS,
}

def ranks_for(keycols: list[str], order: str) -> dict[tuple, int]:
    g = hist.groupby(["customer_id"] + keycols, sort=False).agg(first_ts=("ts", "min")).reset_index()
    sort_cols = ["customer_id", "first_ts"] + keycols if order == "first_ts" else ["customer_id"] + keycols
    g = g.sort_values(sort_cols, kind="stable")
    g["k"] = g.groupby("customer_id").cumcount() + 1
    return {tuple(r): k for r, k in zip(zip(g["customer_id"], *[g[c] for c in keycols]), g["k"])}

results = []
for (iname, kcols), order in product(IDENTITIES.items(), ("first_ts", "sorted")):
    rmap = ranks_for(kcols, order)
    hits = 0
    for _, r in j.iterrows():
        hits += int(rmap.get((r["customer_id"],) + tuple(r[c] for c in kcols)) == r["k"])
    acc = hits / len(j)
    results.append((acc, iname, order, hits))
    print(f"identity={iname:14s} order={order:9s} -> {hits}/{len(j)} = {acc:.4f}")

results.sort(reverse=True)
print(f"\nBEST: identity={results[0][1]} order={results[0][2]} acc={results[0][0]:.4f}")

# how many identities does the average customer have under the best identity?
best_cols = IDENTITIES[results[0][1]]
g = hist.groupby(["customer_id"] + best_cols, sort=False).size().reset_index()
print("cards-per-customer distribution under best identity:")
print(g.groupby("customer_id").size().value_counts().sort_index().head(10).to_dict())
