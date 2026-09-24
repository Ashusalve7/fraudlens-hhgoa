# HHGOA dataset and FraudLens graph dictionary

Authoritative source files remain in `HHGOA_IEEE/`. This file records the normalized fields used by the release pipeline; it does not reproduce raw sponsor data.

## Source files

| File | Expected rows | Join | Use |
|---|---:|---|---|
| `transactions.csv` | 590,742 | `TransactionID` | transaction, customer, channel, amount, risk score, region, match flags |
| `identity.csv` | 144,432 | `TransactionID` | online identity/device observations |
| `closed_cases_history.csv` | 5,565 | `case_id` | labeled July–October history and prior case outcomes |
| `case_pack.csv` | 20 | `case_id` | November–December benchmark alerts and trigger metadata |

Run `scripts/check_dataset.py` rather than trusting this table alone.

## Derived identities

| Field | Rule | Safety behavior |
|---|---|---|
| `card_id` | `customer_id + "-K" + rank((card1, card4, card6))` | validates all flagged and case-listed transactions; no unmatched IDs |
| `device_id` | `DP-` + MD5 of `DeviceInfo|id_30|id_31|id_33` | returns no vertex when all four profile components are missing |
| `txn_id` | string form of `TransactionID` | avoids scientific notation and float-like graph IDs |
| `next_id` | next chronological transaction on the same derived card | validates same-card, acyclic, non-negative integer gaps |

Unknown/empty device profiles are not allowed to connect unrelated customers. A device is a graph vertex only when at least one profile component is observed.

## Graph model

FraudGraph has 9 vertex types and 15 directed edge types:

- `Transaction`, `Customer`, `Card`, `DeviceProfile`, `EmailDomain`, `BillingRegion`, `ClosedCase`, `AgentCase`, `PolicyChunk`;
- `OWNS_CARD`, `PAID_WITH`, `FROM_DEVICE`, `P_EMAIL`, `R_EMAIL`, `BILLED_IN`, `NEXT_TXN`, `CASE_TXN`, `CASE_CARD`, `CASE_CONN_CARD`, `CASE_DEVICE`, `AG_TXN`, `AG_CARD`, `AG_DEVICE`, and `AG_SIMILAR`.

Static counts are derived from the load frames. The live release gate compares those expectations with `graph_health.json`; it does not assume a previously observed cloud count is still correct.

## Evidence windows

- Card context: 60 days before the trigger through `opened_at`.
- Customer context: bounded history through `opened_at`.
- Device context: seven days before `opened_at` through `opened_at`.
- Region context: bounded through `opened_at`.
- Episodes: only rows with pattern-specific anomaly evidence; no arbitrary ±window import.
- Dashboard convenience traversal: historical window ending at the transaction timestamp, not future activity.

Every graph-derived answer claim names a query/tool reference and the exact cutoff window. Unknown IDs, future rows, and orphan evidence fail semantic validation.

## Historical labels and model target

The binary model target is `outcome == confirmed_fraud` versus `cleared`. The model is evaluated on a chronological holdout and a customer-disjoint diagnostic. Legacy `pattern` labels are retained for retrieval/context and reported separately as a noisy-label agreement diagnostic; they are not silently treated as the model target or as permission to act.

## Policy and SAR fields

- `fraud_probability`: calibrated likelihood, not a verdict or authorization.
- `next_best_actions.initial/final`: deterministic recommendations with `auto`, `L1`, or `L2` routes.
- `evidence_requests`: only requests actually recorded; `assumed_response` is explicitly simulated unless supplied by the original trigger.
- `sar.file`: true only when the structured policy gate and `FILE_REPORT` action agree.
- `sar.narrative`: rendered from verified exposure, episode, response, and graph facts; unsupported claims are conditional or omitted.
- `AgentCase.answer_json`: complete exported answer, read back through MCP and compared with local output.

## Release metrics

Do not copy metrics from this document. Read the final generated artifacts:

- `fraudlens/eval/out/model.json`
- `fraudlens/eval/out/eval_report.txt`
- `fraudlens/pipeline/out/graph_health.json`
- `fraudlens/cases/*.json`
- `release_manifest.json`
