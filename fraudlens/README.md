# FraudLens — Agentic Fraud Investigation on TigerGraph

**HHGOA × TigerGraph sponsor challenge.** FraudLens investigates a fraud alert the way a
junior fraud analyst would: it gathers connected evidence from a TigerGraph graph, scores
known fraud patterns, calibrates a fraud probability against 5,565 labeled historical cases,
asks for more evidence when the policy requires it, recommends the next best action under the
bank's fraud policy (R1–R10), writes the finished case back into the graph as memory for the
next investigation, and exports the three required deliverables per case (case record, SAR
when the policy calls for one, next best actions with approval routes).

## Results

- **20/20 answer files valid** (schema, ID-existence, policy-routing, SAR-gate, agreement checks).
- **20/20 investigation cases written into TigerGraph** (`AgentCase` vertices + evidence edges).
- **Fraud-probability calibrator**: holdout AUC **0.975** on 1,392 time-held-out labeled cases,
  calibrated (Platt) on the labeled closed-case history and shifted to the exam prior.
- **Pattern detector**: **77.4%** agreement with the bank's own labels across 4,665 confirmed-fraud
  cases (thresholds locked on the labeled history, never on the exam cases).
- **Verdict balance**: 11 fraud / 9 legitimate across the 20 exam cases — consistent with the
  task's warning that *half the cases are legitimate* and that an agent that blocks everything
  scores badly.

## One-command run

```bash
# 1. Python env (3.12)
uv venv .venv && uv pip install -p .venv/Scripts/python.exe pandas pyarrow pyTigerGraph python-dotenv scikit-learn requests

# 2. Configure (already contains live defaults for this workspace; override via env)
cp .env.example .env

# 3. Build the graph (schema + load + queries) — idempotent, resumable
.venv/Scripts/python.exe pipeline/create_schema.py
.venv/Scripts/python.exe pipeline/build_load_files.py
.venv/Scripts/python.exe pipeline/load_graph.py
.venv/Scripts/python.exe pipeline/install_queries.py

# 4. Investigate all 20 benchmark cases -> cases/*.json
.venv/Scripts/python.exe runner.py

# 5. Validate the submission
.venv/Scripts/python.exe validator.py
```

## Architecture

```
CLI runner (state machine per case)
  TRIGGERED → CONTEXT_RETRIEVED → EVIDENCE_GATHERED → PATTERNS_ASSESSED → MEMORY_RETRIEVED
    → NBA_INITIAL → EVIDENCE_REQUESTED → EVIDENCE_RECEIVED → NBA_FINAL → CASE_WRITTEN → ANSWER_EXPORTED
        │                                   │
        │ TigerGraph installed queries       │ deterministic decision core
        │ (evidence, typed JSON)             │ (calibrator + pattern rules + policy R1–R10)
        ▼
TigerGraph Savanna — FraudGraph
  9 vertex types · 15 edge types (with reverse edges) · vector attributes (cosine, 384-d)
  590,742 transactions · 14,318 cards · 13,553 customers · 9,706 device profiles · 5,565 closed cases
```

The LLM is deliberately **not** in the decision path. Every fact in an answer file is produced
by a GSQL query or a deterministic rule; every action cites a policy rule number; the calibrator
is trained only on the labeled July–October history and never sees exam outcomes.

## The card_id rule (reverse-engineered, validated 100%)

`transactions.csv` has no `card_id`, but every case references cards like `C12382-K1`. We
derived and validated (4,665/4,665 flagged txns + 14,955/14,955 case-listed transactions,
including the 900 cleared cases) the rule:

> card identity = `(card1, card4, card6)`; **K** = the 1-based rank of that identity among the
> customer's cards sorted ascending; `card_id = customer_id + "-K" + K`.

## Agent ↔ TigerGraph

The agent speaks to the graph exclusively through **10 installed GSQL queries** (SYNTAX v3,
GQL path patterns) — the same surface the TigerGraph MCP server exposes as tools:

`get_transaction_context` · `get_card_window` · `get_customer_history` ·
`get_device_neighborhood` · `get_region_activity` · `get_shared_entity_network` ·
`get_email_crosslinks` · `find_similar_cases` · `upsert_agent_case` · `get_agent_case`

MCP configuration for interactive use is in the user-level ZCode config (`tigergraph` server:
`uvx tigergraph-mcp` with `TG_HOST`/`TG_SECRET`).

## Decision core

| Component | What it does | Trained/validated on |
|---|---|---|
| `agent/decision.py::Calibrator` | 16-feature logistic model → Platt calibration → exam-prior shift (0.5) + temperature 1.5 | 4,173 labeled cases; holdout AUC 0.975 |
| `agent/decision.py::detect_pattern` | precedence rules over burst/device/region signals | 77.4% on 4,665 confirmed-fraud cases |
| `agent/decision.py::next_best_actions` | R1–R10 + approval routing (auto/L1/L2), ordered actions with rule citations | policy §2–§3 tables, unit-checked by validator |
| `agent/decision.py::should_file_sar` | FILE_REPORT gate: exposure > $1,000 ∨ shared link ∨ undocumented | 397 filed SARs in history: exposure>$1,000 → filed 100% |

## Evidence-request simulation (policy §5)

Customer/analyst responses are not provided by the task. FraudLens simulates them and records
the assumption verbatim in `evidence_requests[].assumed_response`. Two principles:

1. **Customer-report triggers**: the report itself is the denial; for disputed charges matching
   the cardholder's own recurring pattern (same amount + product, ≥3 occurrences over ≥30 days)
   the agent takes policy **R7** (disputed-but-legitimate): verify, warn, close legitimate.
2. **Risk-score triggers**: the assumed response follows the branch supported by the calibrated
   probability and the nearest similar closed cases from the graph's case memory.

## Repository layout

```
pipeline/   schema, card-id derivation, load-frame builder, loader, query installer
gsql/       schema.gsql + 10 evidence queries (SYNTAX v3)
agent/      evidence layer, inference features, decision core
eval/       labeled feature builder + training/eval (AUC, pattern accuracy, SAR gate)
cases/      the 20 submission files
validator.py   submission format + policy agreement checks
docs/       demo script, technical blog, data dictionary
```

## Notes

- Missing strings are stored as `"_NA_"` in the graph (pyTigerGraph upsert constraint).
- `SentinelGraph` (empty seed graph) was left untouched; all work lives in `FraudGraph`.
- Secrets live in `.env` / the ZCode user config — never committed.
