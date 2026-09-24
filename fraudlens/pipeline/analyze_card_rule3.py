"""D-1d: Decisive experiment — for customers with both K1 and K2 cases, diff the
flagged transactions' card fields to find what separates K1 from K2."""
from __future__ import annotations

from pathlib import Path
from collections import Counter

import pandas as pd
import pyarrow.csv as pv

HERE = Path(__file__).resolve().parent
DATA = HERE.parent.parent / "HHGOA_IEEE"

cc = pd.read_csv(DATA / "closed_cases_history.csv",
                 usecols=["case_id", "customer_id", "card_id", "first_fraud_txn_id"])
cc["k"] = cc["card_id"].str.extract(r"-K(\d+)$").astype("Int64")
print("overall K distribution (all 5565 cases):", cc["k"].value_counts().sort_index().to_dict())

refs = cc.dropna(subset=["first_fraud_txn_id", "k"]).copy()
need_txns = {int(x) for x in refs["first_fraud_txn_id"].astype("int64")}
need_customers = set(refs["customer_id"])

CARD_COLS = ["card1", "card2", "card3", "card4", "card5", "card6"]
cols = ["TransactionID", "ts", "customer_id"] + CARD_COLS
rows = []
with pv.open_csv(DATA / "transactions.csv") as reader:
    for batch in reader:
        df = batch.select(cols).to_pandas()
        sel = df[df["TransactionID"].isin(need_txns)]
        if len(sel):
            rows.append(sel)
fl = pd.concat(rows, ignore_index=True).set_index("TransactionID")
for c in ("card1", "card2", "card3", "card5"):
    fl[c] = pd.to_numeric(fl[c], errors="coerce").astype("Int64")

j = refs.join(fl[CARD_COLS], on="first_fraud_txn_id")
j["first_fraud_txn_id"] = j["first_fraud_txn_id"].astype("int64")

# customers with both K1 and K2 cases
both = j.groupby("customer_id")["k"].nunique()
both_custs = both[both > 1].index.tolist()
print(f"\ncustomers with both K1 and K2 cases: {len(both_custs)}")
sub = j[j["customer_id"].isin(both_custs)]
for cid, gg in list(sub.groupby("customer_id"))[:10]:
    print(f"\n{cid}:")
    print(gg[["case_id", "card_id", "k"] + CARD_COLS].to_string(index=False))

# hypothesis scoring: K = rank of card2 among customer's distinct card2 values,
# where the customer's card UNIVERSE includes phantom cards? Test simpler:
# among single-card1 customers, what separates K1 from K2? any field value pattern?
single = j.groupby("customer_id")["card1"].transform("nunique").eq(1)
s = j[single]
print(f"\nsingle-card1 customers: {len(s)}, K1={int((s['k']==1).sum())}, K2={int((s['k']==2).sum())}, K3+={int((s['k']>=3).sum())}")
for c in CARD_COLS:
    if s[c].dtype != "Int64":
        s = s.copy(); s[c] = s[c].astype("Int64")
    k1 = set(s[s["k"] == 1][c].dropna().unique().tolist())
    k2 = set(s[s["k"] == 2][c].dropna().unique().tolist())
    overlap = k1 & k2
    print(f"  {c}: K1 uniq={len(k1)}, K2 uniq={len(k2)}, overlap={len(overlap)} {'<-- DISCRIMINATES' if not overlap and len(k1)>0 else ''}")
