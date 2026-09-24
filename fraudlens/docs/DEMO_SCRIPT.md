# FraudLens — five-minute demo script

Use this script only after the final release gate passes. The values below come from the regenerated `cases/`, `model.json`, and `graph_health.json`; recheck them if any artifact is regenerated, and never speak an old README number.

## 0:00–0:30 — The problem

> A risk score is a reason to investigate, not a verdict. FraudLens gathers connected evidence, shows uncertainty, follows the bank's approval policy, and records what it did—and what it assumed.

Show the investigation queue, the explicit read-only banner, and graph health.

## 0:30–1:30 — HHG-014: graph-native evidence

Open `/cases/HHG-014`.

1. Point out the trigger text, transaction `3478561`, risk score `0.05`, and the `opened_at` cutoff.
2. Open the graph. Show the real node/edge types, the bounded window, the `+4 more` truncation, and graph provenance.
3. Show the graph-algorithm result: **255 returned nodes and 338 observed edges**. Its scope is the returned relation set, not an unbounded global community.
4. Show the device-neighborhood result: **19 card IDs and 4 prior confirmed-fraud cases** in the pre-cutoff window.
5. Show the policy-grounded recommendation: `CREATE_CASE`, `ESCALATE_TO_ANALYST`, and `FILE_REPORT` on the **L2** approval route.

> The low source risk score did not decide this case. The bounded TigerGraph neighborhood supplied corroboration for an undocumented coordinated-abuse pattern, so deterministic policy routed the report to a human. This is not an autonomous filing or a claim that every shared-device neighborhood is a fraud ring.

## 1:30–2:20 — Evidence request and action diff

Open `/cases/HHG-002`, whose regenerated answer contains an actual initial/final action change.

- Initial policy snapshot: `VERIFY_WITH_CUSTOMER`, `STEP_UP_AUTH`, and `CREATE_CASE` at the recorded initial probability of `0.53`.
- Recorded request: customer validation after step 6.
- Final probability: `0.1225` after the explicitly simulated confirmation.
- Final action: `CLOSE_NO_FRAUD`; the final list removes the three initial actions.

> The customer response is unavailable in this benchmark. FraudLens records the response as a simulation, applies the declared likelihood-ratio update, and describes the actual action diff. It does not rewrite the probability to a hard-coded floor or execute the recommendation.

## 2:20–3:00 — Policy, probability, and uncertainty

Show:

- HHG-002's distinct fraud-likelihood, evidence-confidence, and decision-readiness values;
- HHG-006's `BLOCK_CARD` recommendation on the **L1** route and its human approval boundary;
- HHG-014's `FILE_REPORT` recommendation on the **L2** route;
- the retrieved `PolicyChunk` citation and provenance;
- R1–R10 action reasons and routes; and
- similar closed-case IDs, outcomes, and how confirmed prior fraud contributes an independent evidence item.

> The model ranks likelihood. Deterministic policy controls the action, and the dashboard never executes L1/L2 actions.

## 3:00–3:40 — Graph case memory and SAR grounding

Show the persisted `AgentCase` ID and its `AG_TXN`, `AG_CARD`, `AG_DEVICE`, and (when applicable) `AG_SIMILAR` edges. Then show HHG-014's structured SAR Draft.

> The graph stores the evidence relationships and the complete exported answer. The SAR panel is a draft; filing is not implied unless the policy output and evidence support it. HHG-014's filing basis is corroborated connected-card fraud, not its $74.96 amount.

If GraphRAG is shown, quote the retrieved policy chunk's title/anchor and say that retrieval grounds the analyst context but never authorizes an action.

## 3:40–4:20 — Reproducibility and evaluation

Show the architecture, locked dependencies, graph-health report, and test run. State these regenerated values:

- time-held-out fraud-likelihood AUC: **0.9822**;
- Platt Brier score: **0.0332**;
- post-prior-shift Brier score: **0.0558**;
- customer-disjoint diagnostic AUC: **0.9703**;
- exact production pattern agreement against legacy labels: **0.2349**, explicitly a noisy-label diagnostic;
- semantic cases: **20/20**; and
- graph read-back cases: **20/20**.

The static graph health contract is **634,292 vertices** and **2,506,735 edges**, with 20 managed `AgentCase` vertices.

> The probability model is evaluated separately from deterministic policy and from noisy historical pattern labels.

## 4:20–4:50 — Innovation and controlled autonomy

Show the evidence-request panel, case timeline empty-state behavior, similar-case outcomes, and approval state.

> The innovation is an uncertainty-aware investigator: it distinguishes missing evidence from contradictory evidence, requests the least-invasive useful evidence, routes high-impact actions to humans, and leaves an auditable case trail.

Do not claim night-watch mode, autonomous filing, or a global GDS result in this segment. The verified GDS artifact is documented separately as a global graph-quality signal, not a case authorization input.

## 4:50–5:00 — Close

> FraudLens does not replace the investigator. It makes the investigation connected, calibrated, policy-grounded, and auditable.

## Backup clips

Record separately: mobile queue, HHG-014 graph with truncation, policy/approval matrix, graph-health panel, semantic validator, graph read-back validator, test suite, and frontend build. If Savanna sleeps, use a prerecorded clip and state that the live graph is restarting; do not invent counts.
