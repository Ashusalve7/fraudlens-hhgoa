"""D-1b: Empirical analysis of the card_id K-index for multi-card customers."""
from __future__ import annotations

from pathlib import Path
from collections import defaultdict

import pandas as pd
import pyarrow.csv as pv

HERE = Path(__file__).resolve().parent
DATA = HERE.parent.parent / "HHGOA_IEEE"

SCAN_COLS = ["TransactionID", "TransactionDT", "ts", "customer_id", "card1", "card2", "card3"]

cc = pd.read_csv(DATA / "closed_cases_history.csv",
                 usecols=["case_id", "customer_id", "card_id", "first_fraud_txn_id", "connected_card_ids"])
refs = cc.dropna(subset=["customer_id", "card_id"]).copy()
refs["k_index"] = refs["card_id"].str.extract(r"-K(\d+)$").astype("Int64")
need_customers = set(refs["customer_id"])
need_txns = {int(x) for x in refs["first_fraud_txn_id"].dropna().astype("int64")}

rows = []
with pv.open_csv(DATA / "transactions.csv") as reader:
    for batch in reader:
        df = batch.select(SCAN_COLS).to_pandas()
        m = df["customer_id"].isin(need_customers)
        t = df["TransactionID"].isin(need_txns)
        sel = df[m | t]
        if len(sel):
            rows.append(sel)
hist = pd.concat(rows, ignore_index=True)
flagged = hist[hist["TransactionID"].isin(need_txns)].set_index("TransactionID")

# testable pairs: (customer, card1..3 of flagged txn, K)
ref_txn = refs.dropna(subset=["first_fraud_txn_id", "k_index"]).copy()
ref_txn["tid"] = ref_txn["first_fraud_txn_id"].astype("int64")
j = ref_txn.join(flagged[["card1", "card2", "card3", "ts", "TransactionDT"]], on="tid")
j = j.dropna(subset=["card1"])
j["card1"] = j["card1"].astype("Int64")
print(f"testable: {len(j)}")

# 1) single- vs multi-card customers
n_cards_per_cust = hist.groupby("customer_id")["card1"].nunique()
j["n_cards"] = j["customer_id"].map(n_cards_per_cust)
single = j[j["n_cards"] == 1]
multi = j[j["n_cards"] > 1]
print(f"single-card customers: {len(single)} cases, K1 share={ (single['k_index']==1).mean():.3f}")
print(f"multi-card customers:  {len(multi)} cases, K dist={multi['k_index'].value_counts().to_dict()}")

# 2) for multi-card: does smaller card1 -> smaller K? use customers with 2+ samples
g = multi.groupby("customer_id").filter(lambda x: x["card1"].nunique() > 1)
agree_num = disagree_num = 0
samples = 0
for cid, gg in g.groupby("customer_id"):
    piv = gg.groupby("k_index")["card1"].min()
    ks = sorted(piv.index.tolist())
    for a, b in zip(ks, ks[1:]):
        samples += 1
        if piv[a] < piv[b]:
            agree_num += 1
        else:
            disagree_num += 1
print(f"multi-card order-by-card1 pairs: agree={agree_num} disagree={disagree_num} of {samples}")

# 3) is customer_id <- card1 a function? does a card1 ever span customers?
span = j.groupby("card1")["customer_id"].nunique()
print(f"card1 values spanning >1 customer: {(span > 1).sum()} of {len(span)}")

# 4) same card1, different K within a customer?
dup = j.groupby(["customer_id", "card1"])["k_index"].nunique()
print(f"(customer,card1) with >1 K: {(dup > 1).sum()} of {len(dup)}")

# 5) K vs rank by card2 / card3 (multi-card customers with full info)
for col in ("card2", "card3"):
    jj = multi.dropna(subset=[col]).copy()
    jj[col] = jj[col].astype("Int64")
    hits = total = 0
    for cid, gg in jj.groupby("customer_id"):
        ranks = {c: r for r, c in enumerate(sorted(gg[col].unique().tolist()), 1)}
        for _, r in gg.iterrows():
            total += 1
            hits += int(ranks.get(r[col]) == r["k_index"])
    print(f"rank by sorted {col}: {hits}/{total}")

# 6) show a few multi-card customers with their data
print("\n--- sample multi-card customers ---")
for cid, gg in list(multi.groupby("customer_id"))[:8]:
    txns = hist[hist["customer_id"] == cid].sort_values("ts")
    print(f"\n{cid}: cases:")
    print(gg[["case_id", "card_id", "k_index", "card1", "card2", "card3"]].to_string(index=False))
    print(f"  card1 first-seen order: {txns.groupby('card1')['ts'].min().sort_values().index.tolist()}")
    print(f"  card1 sorted: {sorted(txns['card1'].unique().tolist())}")

# 7) connected_card_ids as extra ground truth
extra = []
for _, r in cc.dropna(subset=["connected_card_ids"]).iterrows():
    for c in str(r["connected_card_ids"]).split("|"):
        c = c.strip()
        if c and c.startswith(r["customer_id"]):
            extra.append((r["customer_id"], c))
        elif c and "-K" in c:
            extra.append((c.split("-K")[0], c))
print(f"\nconnected-card (customer,card_id) pairs: {len(extra)} (sample: {extra[:3]})")
