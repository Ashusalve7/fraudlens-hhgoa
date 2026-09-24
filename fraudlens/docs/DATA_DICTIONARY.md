# HHGOA Dataset — Data Dictionary (FraudLens working notes)

Authoritative source: `HHGOA_IEEE/README.md` (sponsor). This file records what our
pipeline assumes and adds.

## Files

| File | Rows | Join | Notes |
|---|---:|---|---|
| `transactions.csv` | 590,742 | `TransactionID` | 393 original Vesta columns + `customer_id`, `ts`, `channel`, `risk_score` |
| `identity.csv` | 144,432 | `TransactionID` | online txns only; device/connection record |
| `closed_cases_history.csv` | 5,565 | `case_id` | 4,665 confirmed_fraud / 900 cleared; Jul–Oct |
| `case_pack.csv` | 20 | `case_id` | the exam: Nov–Dec alerts with trigger + flagged txn |

## Derived

| Field | Rule | Validation |
|---|---|---|
| `card_id` | `customer_id + "-K" + rank((card1, card4, card6) sorted)` | 4,665/4,665 flagged + 14,955/14,955 case txns = **100%** |
| `device_id` | `DP-` + md5(DeviceInfo \| id_30 \| id_31 \| id_33)[:12] | profile = DeviceInfo + OS + browser + screen (sponsor definition) |

## Semantics we rely on

- `risk_score` ∈ [0,1]: an input, never a verdict. Among *investigated* (closed) cases it is
  anti-correlated with fraud (cleared cases are the model's false positives).
- `channel`: `in_person` = ProductCD `W` (no identity record); `online` = all others.
- `addr1` = billing region code; `addr2` = country (87 = home).
- `id_15`: `New`/`Found` device for the account. `id_23`: proxy flag (transparent/anonymous/hidden).
- Closed-case `pattern` ∈ {5 documented, `undocumented`, `none`}; `report_filed` is the SAR gate.
- Missing strings are stored as `"_NA_"` in FraudGraph (pyTigerGraph upsert constraint).

## Labeled-history statistics (used by the decision core)

- Outcomes: 4,665 fraud / 900 cleared (83.8% / 16.2%).
- Pattern mix (fraud): CNP 1,404 · ATO 1,205 · CNP-new-device 1,076 · OOR 955 · testing 16 · undocumented 9.
- SAR filed: 397/5,565 (7.1%) — **100%** of filed cases had exposure > $1,000 or an
  undocumented pattern; shared-device alone almost never filed (4.8%).
- Pattern-rule accuracy: **77.4%** (thresholds: testing velocity ≥40/24h; new-device share
  ≥0.25; region-prior-share <0.25 separates OOR from ATO).
- Calibrator: 16 features, logistic + Platt, holdout (last 25% by `opened_at`) AUC **0.9752**.
