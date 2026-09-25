# FraudLens five-minute video runbook

For a shorter, casual student-style take, use [`VIDEO_SCRIPT_4MIN_STUDENT.md`](VIDEO_SCRIPT_4MIN_STUDENT.md).

Do not record the final video until the 20 regenerated answers, graph-health report, semantic validator, and production dashboard all pass. The values in this runbook are copied from the final generated artifacts; recheck them if any case is regenerated.

## Recording setup

- Resolution: 1440×900 or 1920×1080, 16:9
- Browser zoom: 100%
- Recording frame rate: 30 fps minimum
- Close unrelated tabs, notifications, terminal secrets, `.env`, and cloud-admin pages
- Keep a local fallback build and screenshots in case Savanna is asleep
- Start and prewarm:
  - `/`
  - `/cases/HHG-014`
  - `/cases/HHG-002`
  - `/cases/HHG-003`
  - `/analytics`
- Use a clean browser profile or incognito window to avoid exposing history
- Narrate evidence, not hidden chain-of-thought

## 0:00–0:30 — Problem and promise

**On screen:** Benchmark queue and graph health.

**Voiceover:**

> Risk scores are a reason to investigate, not a verdict. Fraud analysts need a defensible next action when identity evidence is incomplete and connected activity may cross accounts. FraudLens is a controlled investigation agent built on TigerGraph: it gathers graph evidence, retrieves policy and case memory, follows the bank's approval policy, and records the decision.

**Do not say:** any verdict balance, SAR count, AUC, or accuracy number unless it is copied from the final generated artifacts.

## 0:30–1:30 — HHG-014 graph-native investigation

**Route:** `/cases/HHG-014`

**On screen:**

1. Trigger: analyst request, risk score `0.05`, New device, anonymous proxy.
2. Open the graph near the top of the case.
3. Show the actual time window, **255 returned nodes / 338 observed edges**, and explicit `+4 more` truncation.
4. Open the device-neighborhood evidence: **19 card IDs and 4 prior confirmed-fraud cases** before the cutoff.
5. Show the policy-grounded `CREATE_CASE`, `ESCALATE_TO_ANALYST`, and `FILE_REPORT` recommendation on the **L2** approval route.

**Voiceover:**

> This alert's source risk score was only 0.05, so a score-only system would miss it. TigerGraph traverses from the transaction to the shared device and then to the connected cards and prior case context. The bounded ring returned 255 nodes and 338 observed edges, and the pre-cutoff device neighborhood returned 19 cards plus four prior confirmed-fraud cases. That corroboration supports an undocumented coordinated-abuse pattern and routes the report to a human; it is not an autonomous filing or a claim that every shared device is a fraud ring.

## 1:30–2:20 — Evidence changes the action

**Route:** `/cases/HHG-002`

**On screen:**

1. Initial actions and policy reason.
2. Evidence-request panel labeled **Simulated evidence**.
3. Assumed response and exact action diff.
4. Final action and approval route.

**Voiceover:**

> Before the recorded response, the policy snapshot recommends verify, step-up authentication, and create-case at an initial probability of 0.53. The customer response is not available in this benchmark, so FraudLens simulates a confirmation and records that assumption explicitly. The final probability is 0.1225 and the final action is close-no-fraud, with the three initial actions removed. The dashboard records the change; it does not execute it.

## 2:20–3:00 — Policy, confidence, and approval

**On screen:** uncertainty panel and action panel.

**Voiceover:**

> The dashboard separates fraud likelihood from evidence confidence and decision readiness. A high likelihood is not automatic authorization. The deterministic policy engine selects actions from R1 through R10, preserves exact approval routes, and prevents the agent from executing L1 or L2 actions. HHG-006 demonstrates an L1 block recommendation; HHG-014 demonstrates an L2 report recommendation.

**Do not say:** “agent confidence” if the displayed metric is fraud probability.

## 3:00–3:40 — Graph case memory and SAR grounding

**On screen:** graph case ID, evidence/case timeline state, similar-case outcomes, SAR Draft.

**Voiceover:**

> The completed investigation is written back to TigerGraph with its evidence relationships, complete answer, and exact AG edges. HHG-014 retrieves three similar closed cases and records their influence; its report is labeled a draft and cites only structured facts. Its filing basis is corroborated connected-card fraud, not the $74.96 amount.

If RAG is implemented and verified, show one retrieved policy/analyst-note citation here. Otherwise do not claim GraphRAG.

## 3:40–4:20 — Reproducible engineering and honest evaluation

**On screen:** architecture slide or split screen with graph/query/test code.

**Voiceover:**

> The pipeline validates the 590,742-row dataset, derives card identities, verifies 634,292 graph vertices and 2,506,735 edges, executes MCP allow-listed tools, evaluates the exact production pattern registry, and validates all 20 answers semantically and by graph read-back. The final time-held-out AUC is 0.9822, the customer-disjoint diagnostic AUC is 0.9703, and exact agreement with noisy legacy pattern labels is 0.2349. Those are separate measurements; 20 of 20 answers pass both release validators.

## 4:20–4:50 — Innovation and controlled autonomy

**On screen:** uncertainty/request flow and approval state.

**Voiceover:**

> The differentiator is not a larger risk model. It is an uncertainty-aware investigator: it distinguishes missing evidence from contradictory evidence, requests the least-invasive useful evidence, routes high-impact actions to humans, and learns from graph-native case memory.

Do not claim night-watch mode or autonomous filing.

## 4:50–5:00 — Close

**Voiceover:**

> FraudLens does not replace the investigator. It makes the investigation connected, calibrated, policy-grounded, and auditable.

## Backup clips

Record these separately before the final take:

- benchmark queue and responsive mobile view;
- HHG-014 full graph with truncation indicator;
- policy/approval matrix;
- semantic validator passing 20/20;
- MCP graph read-back validator passing 20/20;
- graph-health panel with expected versus actual counts;
- test suite and frontend build;
- final architecture diagram.

## Recording failure plan

- If the cloud sleeps, show the pre-recorded graph clip and state that the live graph is restarting; do not fabricate counts.
- If a route is blank, use the backup clip and fix the defect after recording only if the submission policy permits a retake.
- If a metric is unavailable, omit it. Never speak an old README number.
- Keep a local copy of final answer files, model artifact, graph-health JSON, and screenshots beside the recording source.

## Video title and description

**Title:** `FraudLens: An Uncertainty-Aware TigerGraph Fraud Investigator | HHGOA 2026`

**Description:**

> FraudLens investigates suspicious transactions as connected graph cases rather than treating a risk score as a verdict. It uses TigerGraph evidence, allow-listed MCP tools, calibrated probability, bank policy R1–R10, simulated evidence requests, graph case memory, and semantic validation. Built for the Hacker House Goa 2026 TigerGraph challenge.
