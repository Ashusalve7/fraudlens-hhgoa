# FraudLens — Demo Script (3–5 minutes)

## 0:00–0:30 — The problem
> "Risk scores are a reason to look, never a verdict. In this benchmark, most high-score
> alerts turn out to be legitimate — and some fraud scores near zero. We built the
> investigator, not another score: an agent that gathers connected evidence from TigerGraph,
> works under the bank's fraud policy, and knows when to stop."

## 0:30–1:30 — Graph evidence (HHG-014)
Open `cases/HHG-014.json` next to the console. The trigger: an analyst flagged transaction
3478561 — **risk score 0.05**. Show the evidence trail:
- `get_transaction_context` returns the txn on device profile `DP-c72bd41105eb`
  (SM-G935F, Android 7.0, Chrome 62) — flagged **New** for the account, behind an
  **anonymous proxy**.
- `get_device_neighborhood` shows that profile was used by **52 cards** in the window.
- `find_similar_cases` retrieves closed cases with the same signature as memory.

> "No flat table makes this obvious. This is a two-hop graph question."

## 1:30–2:15 — Uncertainty, calibration, and the policy
Show `HHG-001` (in-person purchase in a rarely used billing region, risk 0.61):
- Calibrated probability comes from a model **trained on the bank's own 5,565 closed cases**
  (holdout AUC 0.975), shifted to the exam prior — honest numbers, not vibes.
- The policy engine routes by rule: probability under 0.70 on weak signals →
  **R1: verify before you block**. High-impact actions route to L1/L2 humans; the agent
  executes only `auto` actions.

## 2:15–3:00 — Evidence changes the action
Show `HHG-004` (customer report, no recurring pattern): the agent asks the customer to
validate (simulated per policy §5, assumption recorded). The customer denies → probability
jumps → final actions become `BLOCK_CARD` (L1), `CREATE_CASE`, `FILE_REPORT` (L2),
`MONITOR_CONNECTED_CARDS`. `what_changed` narrates exactly why.

Then `HHG-003`: the disputed $49 charge matches the cardholder's own recurring pattern →
policy **R7** — verify, warn, close legitimate. No block.

## 3:00–3:40 — Case memory
Show the graph: 20 `AgentCase` vertices with evidence edges to transactions, cards, devices,
and the prior cases that informed each decision. The next investigation inherits this memory.

## 3:00–3:40 — Analytics + Graph Studio
Open the dashboard **Analytics** tab: verdict donut (11 fraud / 9 legitimate — matching the
README's stated balance), probability distribution across the full range (calibration, not
0/1 guessing), detected-pattern bars, exposure and SAR totals. Then switch to Graph Studio:
**Design Schema** (the full 9-vertex/15-edge model) and **Explore Graph** on the ring device.

## 3:40–4:30 — Engineering
Architecture slide: Savanna graph (590k transactions, 15 edge types), 10 installed GSQL
queries (SYNTAX v3), TigerGraph MCP tool surface, deterministic policy engine, calibration
trained and validated offline (AUC 0.975; pattern rules 77.4% against the bank's labels;
SAR gate learned from the 397 filed reports). 20/20 answer files pass the format validator.

## 4:30–5:00 — Close
> "The agent doesn't replace the investigator. It makes the investigation faster, connected,
> calibrated, policy-grounded, and auditable — and every recommendation cites the rule it
> follows."
