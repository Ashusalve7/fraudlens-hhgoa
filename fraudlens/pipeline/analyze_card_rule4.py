"""D-1e: test 'card2 present -> K2 else K1' rule and inspect violations."""
from pathlib import Path

import pandas as pd
import pyarrow.csv as pv

DATA = Path(__file__).resolve().parent.parent.parent / "HHGOA_IEEE"

cc = pd.read_csv(DATA / "closed_cases_history.csv", usecols=["customer_id", "card_id", "first_fraud_txn_id"])
cc["k"] = cc["card_id"].str.extract(r"-K(\d+)$").astype("Int64")
refs = cc.dropna(subset=["first_fraud_txn_id", "k"]).copy()
need_txns = {int(x) for x in refs["first_fraud_txn_id"].astype("int64")}

cols = ["TransactionID", "customer_id", "card1", "card2", "card3", "card4", "card5", "card6"]
rows = []
with pv.open_csv(DATA / "transactions.csv") as reader:
    for b in reader:
        df = b.select(cols).to_pandas()
        sel = df[df["TransactionID"].isin(need_txns)]
        if len(sel):
            rows.append(sel)
fl = pd.concat(rows, ignore_index=True).set_index("TransactionID")

j = refs.copy()
j["tid"] = j["first_fraud_txn_id"].astype("int64")
j = j.merge(fl, left_on="tid", right_index=True, how="left", suffixes=("", "_t"))
j["card2_empty"] = j["card2"].isna() | (j["card2"] == "")
print("crosstab card2_empty x K:")
print(pd.crosstab(j["card2_empty"], j["k"]))

pred = (~j["card2_empty"]).astype(int) + 1
ok = pred == j["k"]
print(f"\nRULE 'card2 present -> K2 else K1': accuracy = {ok.mean():.4f} ({int(ok.sum())}/{len(j)})")

print("\nK3 cases:")
print(j[j["k"] == 3][["customer_id", "card_id", "card1", "card2", "card3", "card4", "card5", "card6"]].to_string(index=False))

v = j[~ok]
print(f"\nviolations: {len(v)}")
if len(v):
    print(v[["customer_id", "card_id", "k", "card1", "card2", "card3", "card4", "card6"]].head(12).to_string(index=False))
