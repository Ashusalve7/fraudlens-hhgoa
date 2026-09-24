# FraudLens five-minute video runbook

Do not record the final video until the 20 regenerated answers, graph-health report, semantic validator, and production dashboard all pass. Use this runbook for structure, but replace every bracketed value with the final generated result.

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

**Do not say:** any verdict balance, SAR count, AUC, or accuracy number until it is copied from the final generated artifacts.

## 0:30–1:30 — HHG-014 graph-native investigation

**Route:** `/cases/HHG-014`

**On screen:**

1. Trigger: analyst request, low risk score, New device, anonymous proxy.
2. Open the graph near the top of the case.
3. Show actual time window, transaction/card counts, and explicit `+N more` nodes.
4. Open the graph-algorithm evidence card.
5. Show the policy-grounded decision.

**Voiceover:**

> This alert scored only [risk score], so a score-only system would miss it. The transaction used a New device behind an anonymous proxy. TigerGraph traverses from the transaction to the shared device, then to the connected cards and prior case context. The connected-component/shared-neighbor result gives [algorithm fact], which changes the recommendation from ordinary verification to [final action/reason].

If the final review supports the undocumented ring, name the coordinated pattern and its evidence. Do not force a documented label for the demo.

## 1:30–2:20 — Evidence changes the action

**Route:** `/cases/HHG-002`

**On screen:**

1. Initial actions and policy reason.
2. Evidence-request panel labeled **Simulated evidence**.
3. Assumed response and exact action diff.
4. Final action and approval route.

**Voiceover:**

> Before new evidence, the model recommends [initial actions] under policy R1. The customer response is not available in this benchmark, so FraudLens simulates one and records that assumption explicitly. The independent response changes the assessment to [final actions]. The card block is only recommended; it routes to L1 rather than executing autonomously.

Use HHG-002 only if its final regenerated output actually changes actions. Otherwise choose another verified before/after case.

## 2:20–3:00 — Policy, confidence, and approval

**On screen:** uncertainty panel and action panel.

**Voiceover:**

> The dashboard separates fraud likelihood from evidence confidence and decision readiness. A high likelihood is not treated as automatic authorization. The deterministic policy engine selects actions from R1 through R10, preserves exact approval routes, and prevents the agent from executing L1 or L2 actions.

**Do not say:** “agent confidence” if the displayed metric is fraud probability.

## 3:00–3:40 — Graph case memory and SAR grounding

**On screen:** graph case ID, evidence/case timeline, similar case outcomes, SAR Draft.

**Voiceover:**

> The completed investigation is written back to TigerGraph with its evidence relationships, actions, approval state, and structured case summary. [Similar case] has outcome [outcome] and similarity [fact], which [did/did not] influence this decision. The report is labeled a draft and cites only facts present in the evidence bundle.

If RAG is implemented and verified, show one retrieved policy/analyst-note citation here. Otherwise do not claim GraphRAG.

## 3:40–4:20 — Reproducible engineering and honest evaluation

**On screen:** architecture slide or split screen with graph/query/test code.

**Voiceover:**

> The pipeline validates the 590,742-row dataset, derives card identities, verifies the graph schema and edge counts, executes MCP allow-listed tools, evaluates the exact production pattern registry, and validates all 20 answer files semantically. The final time-held-out AUC is [value], exact pattern accuracy is [value], and [N/20] answers pass the release gate.

Only show values generated after the final clean run.

## 4:20–4:50 — Innovation and controlled autonomy

**On screen:** uncertainty/request flow or optional night-watch output.

**Voiceover:**

> The differentiator is not a larger risk model. It is an uncertainty-aware investigator: it distinguishes missing evidence from contradictory evidence, requests the least-invasive useful evidence, routes high-impact actions to humans, and learns from graph-native case memory.

If night-watch is not implemented and verified, omit it.

## 4:50–5:00 — Close

**Voiceover:**

> FraudLens does not replace the investigator. It makes the investigation connected, calibrated, policy-grounded, and auditable.

## Backup clips

Record these separately before the final take:

- benchmark queue and responsive mobile view;
- HHG-014 full graph with truncation indicator;
- policy/approval matrix;
- semantic validator passing 20/20;
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
