# TigerGraph Agentic Fraud Investigation for HHGOA

## Comprehensive qualification-oriented build plan

**Prepared for:** the student team building for the HHGOA TigerGraph sponsor challenge  
**Author:** Manus AI  
**Date:** 24 September 2026

## Executive recommendation

Build **FraudLens**, a controlled agentic investigation workspace that turns a suspicious transaction into a defensible case decision. The product should not present itself as a generic fraud chatbot. It should behave like a junior fraud investigator operating under a policy and approval matrix.

The winning demo loop is:

> **Trigger → assemble graph evidence → detect patterns → retrieve policy and similar cases → assess risk and uncertainty → request approved evidence if needed → recommend a next-best action → record the case → explain the decision.**

TigerGraph must be visible in every important step. Savanna should be the source of truth for entities, relationships, case records, graph-derived features, and relevant vector retrieval. GSQL and TigerGraph graph algorithms should produce deterministic evidence. TigerGraph MCP should expose narrowly scoped tools to the agent. The large language model should orchestrate, synthesize, ask for approved evidence, and explain; it should not invent graph facts or replace the graph analytics.

This design directly maps to the sponsor brief and its judging weights: investigation accuracy and next-best action are each 25%, followed by agentic engineering and innovation at 15% each. The project therefore needs a high-quality investigation engine before it needs a visually elaborate dashboard.

## 1. What the challenge actually requires

The sponsor brief requires an agent that can start from a fraud signal, customer report, or analyst request; gather transaction, identity, device, behavioral, prior-case, and external evidence; identify likely fraud patterns; create and progress a case; maintain case memory; request additional evidence through controlled actions; recommend or simulate actions; obey permissions and approvals; stop when enough evidence exists; and explain its reasoning. The required submission also includes output for 20 benchmark cases, a graph-written case record, a suspicious activity report when policy requires it, a before-and-after next-best-action record, a 3–5 minute demo, a technical blog, and a social post.

The supplied dataset is a modified IEEE-CIS/Vesta fraud dataset containing approximately 590,000 card-not-present transactions, roughly 13,500 customers, transaction and identity/device information, transaction risk scores, closed investigations from the first four months, a bank fraud policy, five known fraud patterns, and 20 benchmark cases from the final two months. The brief explicitly says there is no `Is Fraud` flag in the working input, not every pattern is documented, and the README inside the dataset is authoritative for file names, columns, answer format, and case semantics. Therefore, the team must treat the 20 cases as an evaluation set, not as training labels to leak into the agent.

## 2. Product concept: FraudLens

### 2.1 Product promise

**FraudLens gives an analyst a defensible answer to three questions:**

1. What happened, and which connected entities make it suspicious?
2. What is still uncertain, and what is the least costly approved evidence that would reduce that uncertainty?
3. What should happen next, who can approve it, and why?

### 2.2 Primary user

The primary user is a fraud analyst reviewing a queue of suspicious transactions. A secondary user is an investigator or supervisor who reviews escalations and approves high-impact actions. The interface should therefore prioritize case evidence, chronology, confidence, policy citations, and action routing rather than an open-ended chat transcript.

### 2.3 Differentiating idea: uncertainty-aware next-best action

Most fraud demos stop after assigning a risk score. FraudLens should explicitly separate:

- **Fraud likelihood:** how strongly the evidence supports a suspicious interpretation.
- **Evidence confidence:** how complete and reliable the available evidence is.
- **Decision readiness:** whether the evidence is sufficient for a defensible action under policy.
- **Action cost and reversibility:** whether the recommendation is a low-impact monitoring step or a high-impact block/freeze/escalation.

This enables a compelling behavior: a medium-risk transaction with weak identity evidence may trigger step-up authentication, while a high-risk transaction connected to a known bad device cluster may trigger block, account monitoring, case escalation, and a suspicious activity report. The agent must update its recommendation after mock evidence arrives.

## 3. Scope the MVP around the judging criteria

### Must-have MVP

The first complete version should support one investigation type end to end: suspicious card-not-present transaction investigation. It should include:

- A TigerGraph Savanna graph containing transaction, customer, account/card, device, identity, email, address, merchant/product, case, policy, fraud pattern, evidence, action, and approval entities.
- A reproducible data-loading pipeline from the sponsor dataset.
- At least six installed GSQL queries for neighborhood retrieval, temporal behavior, shared-entity detection, pattern scoring, similar-case retrieval, and case persistence.
- At least three graph algorithms or algorithm families used visibly in evidence generation: community detection, similarity or shared-neighbor analysis, centrality/PageRank, and optionally shortest-path/pathfinding. TigerGraph’s GDS library provides more than 50 ready-to-use GSQL algorithms across centrality, community, node embedding, pathfinding, similarity, and link prediction categories.[1]
- TigerGraph MCP connected to the agent with allow-listed tools rather than unrestricted database access. The official TigerGraph-MCP repository describes 34 tools covering schema, loading, graph access, query execution, and vector operations, and recommends LangGraph for complex stateful orchestration.[2]
- A deterministic investigation state machine implemented with LangGraph or an equivalent framework.
- Policy and fraud-pattern GraphRAG retrieval with citations to the policy passages or pattern records used.
- A case timeline that records every evidence item, finding, confidence update, recommendation, approval requirement, and action outcome.
- Two mock evidence actions, such as customer transaction validation and step-up authentication, with simulated responses that change the recommendation.
- Output files for all 20 benchmark cases in the exact format described by the dataset README.
- A polished analyst dashboard with a case queue, graph evidence view, timeline, uncertainty panel, recommended actions, approval route, and report export.

### Stretch features only after the MVP is stable

Add one or two of these only after all 20 cases run reproducibly:

- Similar resolved-case retrieval using vector embeddings stored on case vertices.
- Analyst feedback that records whether the recommendation was accepted, modified, or rejected.
- A counterfactual panel showing which evidence would change the decision.
- A policy conflict detector that flags when two retrieved policy passages appear inconsistent.
- A graph-based fraud-ring view that clusters related suspicious cases.
- A small offline evaluation dashboard comparing graph evidence, model output, and expected benchmark answers.

Do not spend early time on live bank integrations, real customer messaging, real account blocking, a custom fine-tuned model, or a broad multi-agent swarm. The brief permits simulated, stubbed, or mock APIs for customer messages, freezes, card blocks, refunds, CRM updates, and case closure.

## 4. TigerGraph-first reference architecture

```text
┌──────────────────────┐
│ Analyst dashboard     │
│ Case queue + timeline │
└──────────┬───────────┘
           │ REST/WebSocket
┌──────────▼───────────┐
│ FraudLens API         │
│ Auth, case facade,    │
│ audit, export         │
└──────────┬───────────┘
           │ invokes state graph
┌──────────▼──────────────────────────┐
│ Investigation state machine          │
│ trigger → retrieve → assess →        │
│ evidence request → decide → record   │
└──────┬───────────────┬───────────────┘
       │               │
       │ TigerGraph MCP│ LLM provider
       │ allow-listed  │ reasoning only
       │ tools         │
┌──────▼───────────────┐
│ TigerGraph Savanna    │
│ graph + vectors       │
│ GSQL queries          │
│ GDS algorithms        │
│ case memory           │
└──────┬───────────────┘
       │
┌──────▼───────────────┐
│ Source and policy data │
│ transactions, identity│
│ policy, patterns, cases│
└────────────────────────┘
```

Savanna is a managed cloud-native database built on the TigerGraph engine. Its documented workflow is to create a read/write workspace, design a schema, load vertices before edges, install GSQL queries, and verify data with graph exploration.[3] TigerGraph’s documentation also exposes GSQL, graph data science, hybrid graph-plus-vector search, pyTigerGraph, REST, and GraphQL capabilities.[4]

### Recommended application stack

| Layer | Recommendation | Reason |
|---|---|---|
| Cloud graph | TigerGraph Savanna | Meets the sponsor requirement and gives a clear platform story. Enable auto-stop and auto-start as required by the brief. |
| Graph schema and analytics | GSQL plus TigerGraph GDS | Deterministic evidence and visible sponsor technology usage. |
| Agent boundary | Official TigerGraph-MCP | Required by the brief; keeps graph operations tool-mediated and auditable. |
| Orchestration | LangGraph | Good fit for state, conditional routing, human approval, and tool calls. |
| API | Python FastAPI | Simple integration layer for dashboard, agent, exports, and mock action APIs. |
| UI | React or Next.js | Fast analyst dashboard development with graph visualization and timeline components. |
| LLM | Team-selected hosted model | Use for tool selection, synthesis, uncertainty explanation, and report generation. Keep prompts and model configuration replaceable. |
| Embeddings | One stable embedding model | Use only for policy chunks and resolved case summaries; do not embed every raw transaction initially. |
| Deployment | Local app plus Savanna, or a simple public demo host | The judges must be able to run or watch a stable demo. |

## 5. Graph data model

The graph should model the investigation domain rather than mirror every raw CSV column as a vertex. Keep raw transaction attributes on the `Transaction` vertex and promote repeated entities into vertices so that shared relationships become traversable.

### 5.1 Core vertices

| Vertex | Important attributes | Purpose |
|---|---|---|
| `Transaction` | transaction ID, relative time, amount, product code, risk score, email/address fields, missingness summary, raw feature hash | Primary investigation trigger and evidence anchor. |
| `Customer` | customer ID, segment, aggregate counts, prior case count | Customer behavior and case history. |
| `Account` or `Card` | anonymized card identifiers, first/last seen, velocity features | Payment instrument behavior. |
| `Device` | device ID/info, device type, transaction count, customer count, fraud-case count | Shared device and device reuse signals. |
| `Identity` | identity attributes, completeness score, first/last seen | Identity consistency and missing-data reasoning. |
| `EmailDomain` | domain, customer count, risk summary | Email reuse and mismatch evidence. |
| `Address` | anonymized address keys, customer count, geography proxies | Address reuse and mismatch evidence. |
| `Merchant` or `Product` | product code and aggregate behavior | Product and merchant behavior. |
| `FraudCase` | case ID, status, risk, confidence, pattern, timestamps, outcome | Case memory and progression. |
| `Evidence` | evidence ID, type, source, value summary, confidence, timestamp | Auditable findings. |
| `FraudPattern` | name, description, required signals, policy severity | Pattern knowledge. |
| `PolicyDocument` and `PolicyChunk` | title, section, text, embedding, action rules | GraphRAG grounding. |
| `Action` | action type, reversibility, risk, status, approval state | Recommendation and execution record. |
| `Approval` | role, decision, timestamp, reason | Permission and human-in-the-loop record. |

### 5.2 Core edges

Use directed edges with reverse edges where investigation traversals need both directions. Important relationships include:

- `Customer -MADE-> Transaction`
- `Transaction -USES_CARD-> Card`
- `Transaction -FROM_DEVICE-> Device`
- `Transaction -HAS_IDENTITY-> Identity`
- `Transaction -USES_EMAIL-> EmailDomain`
- `Transaction -USES_ADDRESS-> Address`
- `Transaction -FOR_PRODUCT-> Product`
- `Transaction -TRIGGERED_CASE-> FraudCase`
- `FraudCase -HAS_EVIDENCE-> Evidence`
- `Evidence -ABOUT-> Transaction/Customer/Device`
- `FraudCase -MATCHES_PATTERN-> FraudPattern`
- `FraudCase -CITES_POLICY-> PolicyChunk`
- `FraudCase -RECOMMENDS-> Action`
- `Action -REQUIRES_APPROVAL-> Approval`
- `FraudCase -SIMILAR_TO-> FraudCase`
- `FraudCase -RESULTED_IN-> Outcome`

The edge itself should hold useful facts where appropriate, such as timestamp, amount, source, confidence, or relationship score. TigerGraph’s Savanna guidance emphasizes that edges represent verbs and can carry attributes such as timestamp or amount; it also recommends loading vertices before their referencing edges.[3]

### 5.3 Privacy and reproducibility

The dataset is anonymized, but treat all identifiers as sensitive. Do not expose raw values in the UI if a stable masked identifier is sufficient. Store a `display_id` and a deterministic hash for joins. Keep the original field names in a data dictionary so that judges can trace the implementation to the dataset.

## 6. Evidence and analytics design

The graph must do the factual work. Every evidence card in the UI should include a source type, a graph path or query name, the returned values, a time window, and a confidence qualifier.

### 6.1 The evidence bundle

For each trigger transaction, create an `InvestigationContext` containing:

- Trigger transaction and original risk score.
- Customer and account history in 1-day, 7-day, and 30-day windows.
- Device, identity, email, and address reuse counts.
- Connected customers and transactions within two or three hops.
- Temporal burst and velocity indicators.
- Neighbor risk and prior-case outcomes.
- Pattern scores from deterministic rules.
- Similar resolved cases, when available.
- Relevant policy and fraud-pattern passages.
- Missing-data and contradiction flags.

Return a compact JSON evidence contract from each GSQL tool. Do not pass an unbounded subgraph to the LLM.

### 6.2 Initial GSQL query set

Implement and test these queries before building the agent:

1. `get_transaction_context(transaction_id, lookback_days, max_neighbors)`
2. `get_customer_velocity(customer_id, time_window)`
3. `get_shared_entity_network(transaction_id, depth, entity_types)`
4. `get_device_or_identity_reuse(entity_id)`
5. `get_temporal_burst_features(customer_id, device_id, time_window)`
6. `score_known_patterns(transaction_id)`
7. `find_similar_resolved_cases(pattern, risk_band, embedding)`
8. `write_case_record(case_payload)`
9. `append_case_evidence(case_id, evidence_payload)`
10. `record_action_and_approval(action_payload)`
11. `get_case_timeline(case_id)`
12. `get_graph_health()` for the demo and debugging.

Every query should return typed fields such as `evidence_id`, `evidence_type`, `entity_id`, `metric`, `value`, `time_window`, `query_name`, and `explanation_template`. This prevents the LLM from having to infer what a raw field means.

### 6.3 Graph algorithms to show judges

Use algorithms where they answer a clear investigation question:

- **Community detection:** identify a suspicious component of customers, devices, cards, and addresses that share infrastructure.
- **Similarity/shared-neighbor scoring:** show whether a new transaction resembles prior suspicious entities or cases.
- **Centrality or PageRank:** surface a device, email, or address that is unusually influential across many accounts or transactions.
- **Shortest path/pathfinding:** explain the relationship between the trigger and a known bad case or suspicious cluster.
- **Node embeddings:** optional stretch feature for similar-case retrieval or cluster visualization.

Do not include algorithms merely to list features. In the demo, say what each result changed in the investigation.

### 6.4 Deterministic pattern detectors

The sponsor brief contains five known patterns, but their exact definitions are inside the dataset. After reading the README and policy, implement a configuration-driven pattern registry rather than hardcoding assumptions. For each pattern, store:

- `pattern_id` and official name.
- Required and supporting signals.
- Time windows.
- Minimum thresholds.
- Severity contribution.
- Evidence query names.
- Policy references.
- Whether it supports blocking, monitoring, step-up authentication, escalation, or SAR recommendation.

Also implement a generic `unknown_pattern` path. The brief warns that not every pattern present in the data is documented. The agent should say “unclassified connected-risk pattern” when the evidence is suspicious but does not fit a documented typology; it should not force a false label.

## 7. GraphRAG and case memory

### 7.1 What to put into GraphRAG

Use GraphRAG for two classes of context:

1. **Policy knowledge:** bank fraud policy, procedures, approval rules, reporting criteria, and the five documented patterns.
2. **Case memory:** concise summaries of closed investigations containing trigger profile, decisive evidence, uncertainty, action, approval path, and final outcome.

The LLM should receive retrieved passages together with graph relationships and metadata. A raw vector match without graph provenance is not enough for an investigation decision.

TigerGraph’s current documentation describes graph-plus-vector search in which vectors are attached to vertices and searched through GSQL, with top-k, exact, approximate, and hybrid graph-plus-vector operations. The documented implementation uses distributed vector storage, automatic HNSW indexing, and supports cosine, L2, and inner-product metrics.[5]

### 7.2 Retrieval policy

Use a two-stage retrieval strategy:

- **Stage 1: graph filter.** Restrict candidate policy chunks or cases by pattern, action type, risk band, entity overlap, time period, or case status.
- **Stage 2: vector ranking.** Rank the filtered candidates by semantic similarity to the investigation summary.
- **Stage 3: provenance expansion.** Traverse from the selected policy/case vertex to its source document, pattern, action, and outcome before passing context to the model.

The retrieval result should include `source_id`, `title`, `section`, `text`, `similarity_score`, `graph_filter_reason`, and `source_url_or_file`.

### 7.3 Memory write-back

At case closure, write a structured memory record, not just a transcript. Store:

- Trigger and entities.
- Pattern(s) considered and selected.
- Evidence that changed the decision.
- Evidence requested and response.
- Initial and final risk/confidence.
- Recommended and approved actions.
- Outcome and analyst override.
- A short normalized summary for future retrieval.

This satisfies the brief’s requirement to use prior case outcomes and analyst decisions to inform future recommendations.

## 8. Agent design and controls

### 8.1 Use a state machine, not an unconstrained loop

Recommended states:

1. `TRIGGERED`
2. `CASE_OPENED`
3. `CONTEXT_RETRIEVED`
4. `PATTERNS_ASSESSED`
5. `UNCERTAINTY_ASSESSED`
6. `EVIDENCE_REQUEST_PROPOSED`
7. `EVIDENCE_RECEIVED`
8. `ACTION_RECOMMENDED`
9. `APPROVAL_PENDING`
10. `ACTION_SIMULATED`
11. `CASE_UPDATED`
12. `CLOSED` or `ESCALATED`

Each transition should have a structured input and output. The agent can choose among tools, but the state machine controls which tools are legal at each state.

### 8.2 Tool allow-list

Expose tools with narrow names and contracts:

- `tg_get_transaction_context`
- `tg_get_connected_entities`
- `tg_run_pattern_scoring`
- `tg_run_graph_algorithm`
- `tg_retrieve_policy_context`
- `tg_retrieve_similar_cases`
- `tg_create_case`
- `tg_append_evidence`
- `mock_request_customer_validation`
- `mock_request_step_up_auth`
- `tg_record_recommendation`
- `tg_record_approval`
- `mock_execute_action`
- `tg_close_case`

The agent should never receive arbitrary GSQL or unrestricted write access in the demo. TigerGraph-MCP supports graph, vector, and database tools, but your application should wrap or restrict them to the tools needed by the workflow.[2]

### 8.3 Permissions matrix

| Action | Agent may recommend | Agent may execute automatically | Human approval |
|---|---:|---:|---:|
| Create a case | Yes | Yes | No |
| Add evidence and findings | Yes | Yes | No |
| Request customer validation | Yes | Simulated yes | Optional |
| Request step-up authentication | Yes | Simulated yes | Optional |
| Monitor account | Yes | Simulated yes | No or low-risk approval |
| Warn customer | Yes | Simulated only | Analyst approval |
| Block transaction | Yes | No | Required |
| Freeze or block account | Yes | No | Supervisor required |
| Refund customer | Yes | No | Financial approval required |
| File SAR/STR recommendation | Yes | No | Compliance approval required |
| Close case as cleared | Yes | No | Analyst approval |

The UI should make this matrix visible. It is a strong agentic-engineering signal because it shows that the system does not confuse a recommendation with an authorized action.

### 8.4 Stop conditions

Stop investigation when one of these conditions is met:

- A high-confidence documented pattern is supported by independent evidence sources and policy permits a clear action.
- A low-risk explanation is supported by sufficient evidence and no material contradiction remains.
- Additional evidence would not change the action or would cost more than its expected value.
- The case requires a human or compliance decision outside the agent’s permissions.
- The investigation reaches a maximum tool-call or time budget.

The agent must state the stop reason in the case record.

## 9. Decision policy and next-best action

Use a policy-driven decision object rather than asking the LLM to freely choose an action. The model may propose a decision, but a deterministic policy evaluator validates it.

```json
{
  "case_id": "CASE-0001",
  "risk_band": "high",
  "fraud_likelihood": 0.86,
  "evidence_confidence": 0.78,
  "decision_readiness": "ready_for_approval",
  "patterns": [
    {"id": "P-02", "confidence": 0.84, "evidence_ids": ["E-1", "E-4"]}
  ],
  "uncertainties": [
    "Identity record is incomplete",
    "Customer validation not yet received"
  ],
  "next_best_action": {
    "type": "step_up_authentication_and_hold",
    "reason": "High risk with an unresolved identity contradiction",
    "approval_route": "fraud_analyst",
    "reversible": true
  },
  "alternative_actions": [
    {"type": "monitor_account", "when": "customer validates transaction"},
    {"type": "block_transaction", "when": "validation fails or expires"}
  ],
  "stop_reason": "Enough evidence for a controlled hold; final block requires approval"
}
```

### Recommended action policy

- **Low risk, strong benign explanation:** allow and close or monitor.
- **Medium risk, material uncertainty:** request the least invasive additional evidence, usually customer validation or step-up authentication.
- **High risk, independent graph corroboration:** hold/block the transaction in simulation, open or escalate a case, and route approval.
- **Cross-account or shared-device network:** monitor or restrict connected accounts and escalate the case.
- **Evidence of suspicious activity under policy:** generate a draft SAR/STR recommendation with required fields and compliance approval route; do not claim to file a real report.
- **Conflicting evidence:** preserve both sides, reduce confidence, and escalate instead of forcing a definitive action.

## 10. Dataset and benchmark plan

### 10.1 First step: dataset reconnaissance

Before coding the graph loader, the team must read the sponsor-provided README and create a `DATA_DICTIONARY.md` containing each file, column, type, join key, time semantics, missingness meaning, and case output requirement. The original IEEE-CIS materials confirm that the public dataset is split into transaction and identity files joined by `TransactionID`, and that not all transactions have identity information.[6] The HHGOA version adds cases, policy, patterns, and a 20-case benchmark, so the sponsor README takes precedence over the public competition format.

### 10.2 Time-safe split

Use the first four months for graph construction, pattern discovery, closed-case memory, threshold tuning, and local validation. Treat the final two months and the 20 benchmark cases as holdout evaluation. Do not use benchmark outcomes, hidden labels, or future events in the graph context supplied to the agent.

### 10.3 Data pipeline stages

1. **Profile:** file sizes, schemas, row counts, null rates, cardinalities, duplicate keys, time range.
2. **Normalize:** stable IDs, type conversion, missingness flags, relative timestamps, masked display values.
3. **Join:** transaction and identity records by `TransactionID` while retaining “identity unavailable” as evidence.
4. **Aggregate:** customer, device, address, email, card, and product counts over time windows.
5. **Create graph-load files:** one file per vertex family and edge family.
6. **Load into Savanna:** vertices first, then edges, then vector attributes.
7. **Validate:** counts, sample traversals, edge direction, date ranges, and query outputs.
8. **Freeze a benchmark snapshot:** record graph version, code commit, configuration, and prompt version.

### 10.4 Evaluation metrics

Track metrics that correspond to the judging criteria:

- Pattern identification accuracy across the 20 cases.
- Correctness and usefulness of the next-best action before and after additional evidence.
- Whether the case record contains all required fields.
- Evidence precision: proportion of cited evidence that is relevant and traceable.
- Policy grounding: proportion of action decisions with a valid policy citation.
- Approval correctness: whether high-impact actions are routed to a human.
- Calibration: whether confidence is lower when evidence is incomplete or contradictory.
- Tool reliability: successful completion rate and latency per case.
- Reproducibility: same input and configuration produce the same structured case output.

Create a small `evaluation.py` harness that compares normalized outputs, not prose string equality. Keep a human review sheet for evidence relevance and explanation quality.

## 11. User interface plan

### 11.1 Case queue

Show case ID, trigger type, risk band, confidence, pattern candidate, current status, age, and approval state. Include a “why this entered the queue” label such as risk signal, customer report, or analyst request.

### 11.2 Investigation workspace

The main view should contain:

- A one-sentence case summary.
- Risk, evidence confidence, and decision readiness cards.
- Evidence timeline with source and graph path.
- Interactive graph showing the trigger, customer, device, account/card, identity, and connected entities.
- Pattern cards with supporting and contradictory signals.
- Policy and similar-case citations.
- Uncertainty panel listing missing or conflicting evidence.
- Next-best-action panel showing recommendation, alternatives, approval route, reversibility, and stop reason.
- Action buttons for “request validation,” “request step-up,” “approve,” “reject,” “escalate,” and “simulate action.”

### 11.3 Case audit trail

Every agent step should appear in a collapsed audit trail with timestamp, state, tool, input summary, output summary, and authorization decision. Do not show hidden chain-of-thought. Show concise evidence-based rationale instead: what was observed, which query returned it, and how it affected the decision.

## 12. Implementation sequence

### Phase 0 — team alignment and risk reduction

Create the repository, assign owners, download and verify the dataset, read the README, and write the data dictionary. Register for Savanna, create a read/write workspace, configure auto-stop and auto-start, and test a minimal vertex-edge graph. Verify the TigerGraph-MCP version requirement: the official repository currently states TigerGraph 4.1 or later and recommends 4.2 or later for TigerVector and advanced hybrid retrieval.[2]

**Exit condition:** each teammate can access the repository, the Savanna workspace is reachable, and a sample GSQL query returns a result.

### Phase 1 — graph foundation

Implement the normalized data pipeline, schema, vertex loaders, edge loaders, indexes, and graph validation script. Load a small slice first, then the full training/history period. Build the first three GSQL context queries and inspect their paths in Savanna.

**Exit condition:** graph counts and sample traversals are correct, and a transaction can be expanded into its customer, device, identity, and related-transaction neighborhood.

### Phase 2 — deterministic investigation engine

Implement pattern registry, temporal features, shared-entity features, graph algorithms, risk-band calculation, evidence contracts, and policy evaluator. Write unit tests for thresholds and edge cases, especially missing identity records and contradictory signals.

**Exit condition:** a Python test can invoke the graph queries for a known case and produce a complete evidence bundle without an LLM.

### Phase 3 — MCP and agent state machine

Install and configure TigerGraph-MCP. Build the allow-listed tool wrappers. Implement the LangGraph states, transitions, typed state object, retry policy, tool-call budget, stop conditions, and approval gate. Add structured JSON validation around every model response.

The official MCP LangGraph setup shows configuration through TigerGraph host credentials and a LangGraph example that can create schemas, load data, and run graph operations.[7] For your project, adapt that integration to the sponsor graph and narrow the tool surface to investigation operations.

**Exit condition:** a trigger can open a case, retrieve graph evidence, score patterns, and persist a case record without manual database work.

### Phase 4 — GraphRAG, case memory, and mock evidence

Load policy and pattern chunks, add embeddings, implement graph-filtered vector retrieval, and create resolved-case summaries. Implement mock validation and step-up APIs. Ensure the agent changes its recommendation after receiving evidence.

**Exit condition:** the same case visibly changes from “request evidence” to “approve monitored action” or “escalate/block recommendation” based on a simulated response.

### Phase 5 — UI and benchmark harness

Build the case queue and investigation workspace. Connect the timeline and graph view to the case API. Add output export in the required submission format. Run all 20 cases, capture latency and failures, and manually review every result.

**Exit condition:** all 20 benchmark outputs are generated, cases are written to TigerGraph, and no case depends on a hidden manual step.

### Phase 6 — hardening and submission assets

Freeze the architecture, remove brittle prompts, document environment variables, add a one-command local start, create a clean demo seed, and write the technical blog. Record the demo only after running it twice from a clean checkout. Prepare the social post and repository README.

**Exit condition:** a new teammate can run the demo from the README, the 3–5 minute recording is coherent, and the GitHub repository contains the required outputs and architecture explanation.

## 13. Team structure

For a four-person team:

- **Graph/data engineer:** data dictionary, normalization, schema, loaders, GSQL, graph algorithms, benchmark reproducibility.
- **Agent/orchestration engineer:** TigerGraph-MCP, LangGraph state machine, tool contracts, policy evaluator, approvals, retries.
- **Full-stack engineer:** API, case persistence facade, dashboard, graph visualization, audit trail, export.
- **Fraud/product lead:** policy interpretation, pattern registry, evaluation rubric, case review, demo narrative, blog, and submission packaging.

For a three-person team, merge full-stack and graph/data responsibilities, but keep the fraud/product lead independent enough to challenge unsupported explanations.

Use a shared definition of done: code merged, test added, graph query verified, UI evidence traceable, and documentation updated. Never allow “the model said so” as acceptance criteria.

## 14. Demo script for 3–5 minutes

### 0:00–0:25 — problem and promise

Show the queue and say: “Fraud analysts do not need another risk score. They need a defensible next action when evidence is incomplete. FraudLens uses TigerGraph to investigate connected entities, retrieves policy and case memory, and records an approval-aware decision.”

### 0:25–1:10 — trigger and graph evidence

Open one benchmark-style case from a risk signal. Show the transaction, connected device, account/card, identity, and related transactions. Run the shared-device or connected-component query. Highlight a graph path and a temporal burst. Mention the GSQL query name and algorithm result.

### 1:10–1:55 — uncertainty and GraphRAG

Show the pattern candidates and policy citations. Emphasize that the agent distinguishes likelihood from evidence completeness. Show an incomplete identity record or conflicting customer behavior. The agent recommends step-up authentication rather than immediately blocking.

### 1:55–2:40 — additional evidence and updated action

Click “request customer validation” or “request step-up authentication.” Show the mock response. Re-run the assessment. The recommendation changes, for example from “request evidence” to “monitor and allow,” or from “hold” to “escalate and block recommendation.” Show the approval route.

### 2:40–3:25 — case record and memory

Show the case timeline, evidence IDs, actions, approval state, report draft, and graph-written record. Retrieve a similar resolved case and show how its outcome informed the recommendation.

### 3:25–4:00 — engineering and close

Show the architecture briefly: Savanna graph, GSQL/GDS, TigerGraph MCP, GraphRAG, state machine, and UI. State the benchmark result across all 20 cases if available. Close with: “The agent does not replace the investigator. It makes the investigation faster, connected, policy-grounded, and auditable.”

## 15. Submission checklist

### Working agent

- [ ] Starts from a supported trigger.
- [ ] Opens or resumes a case.
- [ ] Calls TigerGraph through TigerGraph MCP.
- [ ] Uses GSQL and graph algorithms.
- [ ] Retrieves policy and/or prior-case context through GraphRAG.
- [ ] Handles missing and contradictory evidence.
- [ ] Requests additional evidence through controlled mock actions.
- [ ] Recommends a next-best action before and after evidence.
- [ ] Enforces approval requirements.
- [ ] Records the case and outcome in TigerGraph.
- [ ] Explains evidence, uncertainty, and action selection.

### Benchmark outputs

- [ ] All 20 cases run from a clean, documented command.
- [ ] Each output follows the dataset README format.
- [ ] Each case record is written to the graph.
- [ ] SAR/STR draft is generated when required by policy.
- [ ] Before-evidence and after-evidence recommendations are recorded.
- [ ] No benchmark labels or outcomes leak into the agent context.

### Repository and content

- [ ] README with architecture diagram and setup instructions.
- [ ] `.env.example` with no secrets.
- [ ] Data dictionary and schema diagram.
- [ ] GSQL query source and installation instructions.
- [ ] TigerGraph-MCP setup instructions.
- [ ] Evaluation harness and results table.
- [ ] 3–5 minute demo video.
- [ ] Technical blog with what was built, how TigerGraph was used, agent capabilities, lessons learned, and future improvements.
- [ ] X or LinkedIn post linking to the blog/demo and tagging `@TigerGraphDB`.

## 16. Main risks and mitigations

| Risk | Why it matters | Mitigation |
|---|---|---|
| Dataset is not understood early | Wrong joins or case semantics can invalidate every result. | Read README first; create data dictionary; freeze a small verified slice. |
| Overusing the LLM | Hallucinated evidence and inconsistent actions damage accuracy. | Graph-generated evidence contracts, typed outputs, policy evaluator, citations, and allow-listed tools. |
| Savanna setup delays | Cloud configuration and loading can consume hackathon time. | Build a tiny graph on day one; script schema and loading; keep a local fallback only for development, not as the sponsor story. |
| MCP integration mismatch | Version or credential issues can appear late. | Pin TigerGraph/MCP versions; test one query through MCP before building the full agent. |
| Vector retrieval distracts from graph | Generic semantic matches may be less useful than connected evidence. | Graph-filter candidates first; store provenance; use vectors for policy and case summaries, not raw transaction truth. |
| UI becomes the project | A beautiful dashboard cannot compensate for weak decisions. | Build a vertical slice early; make every visual component consume real graph outputs. |
| Benchmark overfitting | Tuning to 20 cases may not generalize. | Use time-safe splits and document thresholds; keep unknown-pattern path. |
| Unsafe action semantics | Judges may penalize an agent that appears to freeze accounts autonomously. | Clearly simulate actions; enforce approval matrix; record authorization state. |
| Too many features | The team ends with an unstable demo. | Freeze MVP scope; stretch features only after all 20 cases pass. |

## 17. Practical success criteria

The team should consider itself qualification-ready when an evaluator can independently see all of the following in under five minutes:

1. A suspicious transaction starts an investigation.
2. TigerGraph returns connected evidence that a flat table lookup would not make obvious.
3. A graph algorithm or GSQL pattern detector contributes to the finding.
4. The agent acknowledges uncertainty instead of guessing.
5. A controlled evidence request is made.
6. New evidence changes the recommended action.
7. The action is routed through an approval policy.
8. The case, evidence, report, and decision are persisted.
9. The explanation cites evidence and policy.
10. A prior case or pattern memory informs the recommendation.

No plan can guarantee selection because the final result depends on execution quality, benchmark performance, reliability, and the competing teams. This plan maximizes the controllable factors by prioritizing a complete, verifiable vertical slice over a broad but fragile feature set.

## 18. Immediate next 48 hours

**Day 1:** read the sponsor README, create the data dictionary, assign team roles, register Savanna, create the read/write workspace, enable auto-stop/auto-start, load a 1,000-row sample, and verify one GSQL neighborhood query.

**Day 2:** finalize the graph schema, load the first historical slice, implement `get_transaction_context`, `get_shared_entity_network`, and `score_known_patterns`, and test TigerGraph-MCP with one read tool and one write tool. End the second day with a five-minute internal demo of a graph-backed evidence bundle.

**Day 3:** implement the state machine and typed decision object. Do not add a polished UI until the CLI can run one complete investigation and persist a case.

## References

[1]: https://www.tigergraph.com/docs/graph-ml/3.10/intro/ "TigerGraph Graph Data Science Library"
[2]: https://github.com/TigerGraph-DevLabs/tigergraph-mcp "TigerGraph-MCP official repository"
[3]: https://www.tigergraph.com/docs/savanna/main/get-started/first-graph-ui "Build your graph in TigerGraph Savanna"
[4]: https://docs.tigergraph.com/home/ "TigerGraph Documentation"
[5]: https://www.tigergraph.com/docs/gsql-ref/current/vector/ "TigerGraph Vector Database Operations"
[6]: https://ieee-dataport.org/documents/ieee-cis-fraud-detection "IEEE-CIS Fraud Detection dataset description"
[7]: https://github.com/TigerGraph-DevLabs/tigergraph-mcp/blob/main/docs/langgraph_setup.md "Using TigerGraph-MCP Tools with LangGraph"
[8]: https://www.fatf-gafi.org/en/publications/Fatfrecommendations/Fatf-recommendations.html "The FATF Recommendations"
[9]: https://www.nist.gov/itl/ai-risk-management-framework "NIST AI Risk Management Framework"

## Source-grounding note

The product controls in this plan are design recommendations for a hackathon prototype, not legal or compliance advice. FATF describes an international framework that countries adapt to their own legal, administrative, and operational systems.[8] NIST describes the AI Risk Management Framework as voluntary guidance for managing AI risks and improving trustworthy AI.[9] The team should use the sponsor-provided bank policy as the controlling policy for benchmark decisions and label any SAR/STR output as a draft or simulation.

**Author:** Manus AI
