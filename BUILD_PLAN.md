# FraudLens — HHGOA × TigerGraph Grand-Finale Build Plan

**Version 2.0 — data-grounded, execution-ready (supersedes the generic Manus plan)**
**Date:** 24 September 2026 · **Workspace:** `Task 4` · **Graph:** TigerGraph Savanna (MCP already connected ✅)

---

## 0. What we already have (head start)

| Asset | Status |
|---|---|
| TigerGraph Savanna workspace | ✅ Live (`tg-cc0afa64-1afa-43c0-b16d-d90e6bfca74c...i.tgcloud.io`) |
| TigerGraph MCP → ZCode | ✅ Connected, secret verified, 69 tools available |
| Dataset | ✅ In `HHGOA_IEEE/` — verified row counts & columns |
| Graph in workspace | `SentinelGraph` exists (inspect before reuse; likely create fresh `FraudGraph`) |
| Sponsor README | ✅ Fully parsed — answer format, policy R1–R10, 5 patterns |

**Nothing remains blocked on setup. Day zero is done. Build starts now.**

---

## 1. How the game is scored (strategy root)

Reported judging weights: **Investigation accuracy 25% · Next-best-action 25% · Agentic engineering 15% · Innovation 15%** (~20% remaining: demo, blog, social, completeness).

→ **50% of the score is the 20 answer files.** Everything else exists to make those 20 files correct, policy-exact, and graph-grounded.

### The five scoring surfaces and our edge on each

1. **Verdict + pattern accuracy** → we have 5,565 *labeled* closed cases (Jul–Oct). We build and **offline-validate** detectors against known truth before ever touching the exam cases.
2. **Calibration of `fraud_probability`** → scored for honesty. We calibrate on history, not vibes. README: *"Half the cases are legitimate"* → expect ≈10/20 legit; never output 0.9 reflexively.
3. **Next-best-action correctness** → policy R1–R10 are a **deterministic decision table**. We implement it as code (not LLM discretion), so every action cites a rule number by construction.
4. **Agentic engineering** → MCP-mediated graph tools + explicit investigation state machine + evidence requests that visibly change the recommendation.
5. **Innovation** → the README's *optional* track: agent self-monitors Nov–Dec risk scores and investigates beyond the 20 cases (separate folder). We do this as a stretch — it's explicitly credited toward Innovation.

---

## 2. Reconnaissance findings (facts, not guesses)

These came from profiling the actual files today:

### Closed-case history = our labeled training set
- 5,565 cases: **4,665 confirmed fraud / 900 cleared** (16% cleared).
- Pattern mix among confirmed fraud:

| Pattern | Count | Share |
|---|---:|---:|
| `card_not_present_fraud` | 1,404 | 30% |
| `account_takeover` | 1,205 | 26% |
| `card_not_present_new_device` | 1,076 | 23% |
| `out_of_region_use` | 955 | 20% |
| `card_testing` | 16 | 0.3% |
| `undocumented` | 9 | 0.2% |

- **SARs were filed in only 397/5,565 cases (7%)** → "case only" is the norm; `FILE_REPORT` needs its gate learned from history (§7.4).
- `analyst_notes` is rich free text → prime GraphRAG corpus + source of the undocumented-pattern vocabulary.

### Exam-case triage (from `case_pack.csv`)
- 11 `risk_score` triggers (0.52–0.90), 8 `customer_report` ("I never made this purchase"), 1 `analyst_request` (HHG-014).
- **HHG-014 verified in data:** flagged txn `3478561` ($74.96, online, `risk_score` **0.05** — near zero!) on a device marked **`New`**, behind **`IP_PROXY:ANONYMOUS`**, Android/Chrome (`SM-G935F`). Proof of the README's warning: *some fraud scores near zero*. This case is a shared-device ring hunt (R6/R9).
- **HHG-001 verified:** in-person (`ProductCD W`, no identity record), region 444 vs home 87 → out-of-region candidate *or* legitimate trip (policy: several days in one region = trip, not clone).
- Customer reports split between genuine fraud (R2 path) and **recurring-charge false disputes** (R7 path: same merchant, same amount, monthly) — the discriminator is the customer's own history graph.

### Critical data-engineering discovery (missed by the old plan)
`transactions.csv` has **no `card_id` column** — only `customer_id`. But every case references cards like `C12382-K1`. **Task D-1 (§5.1): reverse-engineer the `customer_id → card_id` mapping** using `closed_cases_history.csv` (it has *both* `card_id` and `txn_ids`). Without this, we cannot join exam cases to transactions. Validate the derived rule on all 5,565 closed cases until 100% match.

---

## 3. Architecture (simplified from the Manus plan — fewer moving parts, same story)

```text
┌────────────────────────────────────────────────────────┐
│  CLI Runner (primary)      Analyst Dashboard (stretch)  │
│  runs 20 cases, writes cases/*.json                     │
└────────────────────────┬───────────────────────────────┘
                         │
┌────────────────────────▼───────────────────────────────┐
│  Investigation Agent  (Python state machine)            │
│  TRIGGER → CONTEXT → PATTERN → CALIBRATE → DECIDE       │
│           → (EVIDENCE REQ → simulate) → RE-DECIDE       │
│           → WRITE CASE TO GRAPH → ANSWER FILE           │
│  • Policy Engine: R1–R10 as deterministic code          │
│  • LLM: synthesis, SAR narrative, unknown-pattern prose │
│    (LLM never invents graph facts; it consumes typed    │
│     evidence JSON produced by GSQL)                     │
└──────┬──────────────────────────────┬──────────────────┘
       │ TigerGraph MCP (allow-list)   │
┌──────▼──────────────────────────────▼──────────────────┐
│  TigerGraph Savanna — FraudGraph                        │
│  entities + edges + closed-case memory + vectors        │
│  10 installed GSQL queries + GDS algorithms             │
└─────────────────────────────────────────────────────────┘
```

**Deliberate simplifications vs. the Manus plan:**
- **CLI-first, dashboard later.** The 20 answer files don't need a UI. Build the dashboard only in the final third, driven entirely by real case data (demo value).
- **LangGraph optional.** A plain Python state machine with explicit states is easier to debug and demo. Use LangGraph only if we adopt checkpointing. Judges score the *behavior* (states, gates, tool mediation), not the framework.
- **One repo, one command:** `python -m frauddens run --all` regenerates all 20 answers reproducibly.

---

## 4. Graph schema (GSQL DDL — concrete)

> Vertex-first, then edges (Savanna loading rule). Keep raw V-columns *out* of the graph except a curated subset that detectors actually use; store the rest as a per-transaction `feature_json` blob for provenance.

```sql
CREATE VERTEX Transaction (PRIMARY_ID txn_id STRING, ts DATETIME, amount FLOAT,
    product_cd STRING, channel STRING, risk_score FLOAT, card1 INT, addr1 STRING, addr2 STRING,
    p_email STRING, r_email STRING, m_flags STRING, dist1 FLOAT,
    c_counts STRING, d_deltas STRING, v_subset STRING, feature_json STRING) WITH primary_id_as_attribute="true"

CREATE VERTEX Customer   (PRIMARY_ID customer_id STRING, first_ts DATETIME, last_ts DATETIME,
    n_cards INT, n_txn INT, home_region STRING)
CREATE VERTEX Card       (PRIMARY_ID card_id STRING, first_ts DATETIME, last_ts DATETIME,
    n_txn INT, network STRING, card_type STRING)
CREATE VERTEX DeviceProfile (PRIMARY_ID device_id STRING, device_info STRING, os STRING,
    browser STRING, screen STRING, n_cards INT, n_customers INT, n_fraud_cases INT)
CREATE VERTEX EmailDomain  (PRIMARY_ID domain STRING, n_customers INT, is_free BOOL)
CREATE VERTEX BillingRegion(PRIMARY_ID region_id STRING, n_customers INT)
CREATE VERTEX Merchant/ProductCD (PRIMARY_ID code STRING, n_txn INT)   -- ProductCD as product node
CREATE VERTEX ClosedCase (PRIMARY_ID case_id STRING, outcome STRING, pattern STRING,
    opened_at DATETIME, closed_at DATETIME, exposure_usd FLOAT, n_txns INT,
    report_filed BOOL, actions STRING, notes STRING, notes_embedding VECTOR(BFLOAT, 768))  -- if TigerVector enabled
CREATE VERTEX AgentCase  (PRIMARY_ID case_id STRING, verdict STRING, pattern STRING,
    fraud_prob FLOAT, exposure_usd FLOAT, status STRING, created_at DATETIME, answer_json STRING)
CREATE VERTEX PolicyChunk(PRIMARY_ID chunk_id STRING, kind STRING /*rule|pattern|sar-guide*/,
    title STRING, text STRING, embedding VECTOR(BFLOAT, 768))

CREATE EDGE OWNS_Card        (FROM Customer, TO Card, since DATETIME)
CREATE EDGE PAID_WITH        (FROM Transaction, TO Card)
CREATE EDGE FROM_DEVICE      (FROM Transaction, TO DeviceProfile)
CREATE EDGE P_EMAIL_DOMAIN   (FROM Transaction, TO EmailDomain)
CREATE EDGE R_EMAIL_DOMAIN   (FROM Transaction, TO EmailDomain)
CREATE EDGE BILLED_IN        (FROM Transaction, TO BillingRegion)
CREATE EDGE FOR_PRODUCT      (FROM Transaction, ProductCD)
CREATE EDGE NEXT_TXN         (FROM Transaction, TO Transaction, gap_seconds INT)  -- per-card time order
CREATE EDGE CASE_INVOLVES    (FROM ClosedCase, TO Transaction)
CREATE EDGE CASE_ON_CARD     (FROM ClosedCase, TO Card)
CREATE EDGE CASE_CONNECTED   (FROM ClosedCase, TO Card)
CREATE EDGE CASE_DEVICE      (FROM ClosedCase, TO DeviceProfile)
CREATE EDGE AC_INVOLVES      (FROM AgentCase, TO Transaction)
CREATE EDGE AC_ON_CARD       (FROM AgentCase, TO Card)
CREATE EDGE AC_DEVICE        (FROM AgentCase, TO DeviceProfile)
CREATE EDGE AC_SIMILAR_TO    (FROM AgentCase, TO ClosedCase, score FLOAT)
```

Sizes: ~591k Transaction, ~144k DeviceProfile (max), ~13.5k Customer, ~5.6k ClosedCase — comfortably within a Savanna workspace. Add reverse edges where traversal needs both directions (`WITH REVERSE_EDGE="yes"` on PAID_WITH, FROM_DEVICE, OWNS_Card).

---

## 5. Data pipeline

### 5.1 Task D-1 (do FIRST): reverse-engineer `card_id`
1. From `closed_cases_history.csv`, take each (`customer_id`, `txn_ids`) → look up rows in `transactions.csv` → collect the `card1` (and card1–card6 combo) each card_id maps to.
2. Hypothesis: `card_id = customer_id + "-K" + rank` where rank = order of first appearance (by `ts`) of each distinct `card1` within the customer.
3. Validate across **all 5,565 closed cases**. If mismatches, iterate (rank by `card1` value, by first `TransactionDT`, etc.) until 100%.
4. Freeze `derive_card_id()` + unit test. **Blocker for everything else.**

### 5.2 Loader (Python + pyTigerGraph or MCP loading tools)
1. **Profile** → null rates, cardinalities, time range (sanity: Jul 2 – Dec 31 2016).
2. **Normalize:** typed columns; `addr1` → region id; DeviceProfile id = hash of `(DeviceInfo, id_30, id_31, id_33)` (README defines profile as DeviceInfo+OS+browser+screen); missingness flags.
3. **Emit per-type load files:** `vertices_*.csv`, `edges_*.csv` (vertices before edges).
4. **Load into Savanna** via loading jobs; run `get_graph_health()` counts vs. source counts.
5. **NEXT_TXN chain:** per card ordered by `ts`, gap in seconds — powers card-testing & burst detection.
6. **Freeze snapshot:** record schema version + load counts in `graph_meta` for reproducibility.

### 5.3 What NOT to put in the graph
All 339 V-columns stay in `feature_json`/source CSVs. Curate into typed attributes only what detectors use (e.g., `id_15` New/Found, `id_23` proxy, `M1–M9` match flags, `dist1`, `C1–C14`, `D1–D15`). State this choice in the blog — it shows engineering judgment.

---

## 6. GSQL query set (install & test before the agent exists)

| # | Query | Purpose (evidence for) |
|---|---|---|
| 1 | `get_transaction_context(txn_id, lookback_days)` | trigger snapshot: amount, channel, risk, card, device, region, emails |
| 2 | `get_card_window(card_id, hours)` | card-testing sequence (≥3 sub-$5 online auths then larger) — R5 |
| 3 | `get_customer_history(customer_id, window)` | recurring-charge detection (same product/amount/monthly) — R7; behavioral baseline |
| 4 | `get_device_neighborhood(device_id, window)` | cross-card device sharing → rings — R6/R9 |
| 5 | `get_region_activity(card_id, region_id)` | out-of-region vs. trip (days-of-activity in one region) — patterns 4 |
| 6 | `get_shared_entity_network(entity_id, depth)` | 2–3 hop connected cards/customers via device, region, email |
| 7 | `get_email_crosslinks(domain/email)` | R_email ↔ P_email reuse across customers |
| 8 | `find_similar_cases(features…)` | case memory retrieval (structured match + optional vector top-k) |
| 9 | `write_agent_case(payload)` / `append_evidence` | persist case to graph (`written_to_graph: true`, `graph_case_id`) |
| 10 | `get_case_timeline(case_id)` | demo + audit |

**GDS algorithms to use visibly (3 families minimum):**
- **Connected components / community** on the device–card–region graph → ring discovery (HHG-014!).
- **PageRank/degree centrality** on DeviceProfile/EmailDomain/BillingRegion → "unusually influential shared infrastructure".
- **Jaccard similarity** (or shared-neighbor counts) between the trigger's neighborhood and closed-fraud neighborhoods → pattern corroboration.

Each query returns the **typed evidence contract**: `{evidence_type, entity_ids, metric, value, time_window, query_name, explanation_template}` → the LLM consumes this, never raw dumps.

---

## 7. The decision core (this is where 50% of the score lives)

### 7.1 Fraud-probability estimator — trained on labeled history
Graph features per case (velocity, device newness, proxy, region novelty, amount-vs-baseline, email mismatches, shared-entity fraud counts, similar-case outcomes…) → **logistic regression with calibration (Platt/isotonic)**, trained on the 4,665 fraud / 900 cleared closed cases (time-safe: Jul–Oct only). Output = `fraud_probability`. Report offline AUC + calibration curve in the blog. *This single artifact turns "guessed probability" into "calibrated probability" — directly scored.*

### 7.2 Pattern classifier — validated offline
- Rule-based detectors for the 5 known patterns (§6 queries).
- Fallback: k-NN over closed-case embeddings/structured features; if best match is weak → `undocumented` + `pattern_description` (LLM-written, evidence-cited).
- **Offline metric:** pattern-classification accuracy on the 5,565 labeled cases. Iterate until strong. (card_testing has only 16 examples — encode the README definition tightly rather than learning it.)

### 7.3 Policy engine — R1–R10 as pure code
```python
def next_best_actions(assessment) -> list[ActionRec]:
    # deterministic; every ActionRec carries {action, route, reason: "R<n>: ..."}
```
- Route table straight from policy §2 (auto/L1/L2 by action + exposure).
- Ordering: "what happens first".
- `initial` = f(assessment before evidence). `final` = f(assessment after simulated response). `what_changed` = diff explanation.

### 7.4 FILE_REPORT gate — learned from the 397 filed SARs
Features: exposure > $1,000 · shared device/region/other-card link · connected-card fraud · coordinated/undocumented · customer denial. Fit on history; encode as rule + validation. (History rate 7% ⇒ default is *no* report.)

### 7.5 Evidence-request simulation (policy §5)
Responses aren't provided — we simulate and record assumptions. **Principled rule:** choose the response predicted by our calibrated model's verdict branch (the more probable branch), citing the nearest similar closed case as the basis of the assumption. Record verbatim in `evidence_requests[].assumed_response`. If model is near the decision boundary (0.35–0.65), simulate the branch that *tests the decision* (e.g., denial when we lean fraud) — that maximizes `what_changed` credibility without gaming.

### 7.6 Stop conditions (policy §6)
Code them exactly: p ≥ 0.85 or ≤ 0.15 **with ≥2 independent evidence sources**; verification settles it; further evidence wouldn't change the action. Always write `stop_reason`.

---

## 8. Agent loop (agentic-engineering 15%)

States: `TRIGGERED → CONTEXT_RETRIEVED → PATTERNS_ASSESSED → CALIBRATED → NBA_INITIAL → EVIDENCE_REQUESTED → EVIDENCE_RECEIVED → NBA_FINAL → CASE_WRITTEN → ANSWER_EXPORTED`.

- All graph access through **MCP tools, allow-listed**: `tg_get_transaction_context`, `tg_get_card_window`, `tg_get_device_neighborhood`, `tg_find_similar_cases`, `tg_write_agent_case`, `tg_append_evidence` (+ GDS wrappers). No raw GSQL to the LLM.
- LLM roles only: pick next tool given state, synthesize `summary`, write `pattern_description` for undocumented, draft SAR narrative (FinCEN who/what/when/where/how/why), explain `what_changed`.
- Budgets: max tool calls/case, max tokens/case — recorded in the answer (`tool_calls`, `tokens`, `latency_s` are required fields!).

### Mock evidence APIs
`mock_customer_validation`, `mock_step_up_auth`, `mock_analyst_info` — return simulated responses per §7.5. Clearly labeled simulated in UI/outputs.

---

## 9. GraphRAG (keep it honest)

- Corpus: Fraud Policy R1–R10 + action/route tables · 5 pattern definitions · SAR narrative guidance (FinCEN) · 5,565 closed-case `analyst_notes` (chunked).
- Two-stage retrieval: **graph filter first** (candidate cases by entity overlap / pattern / outcome), then **vector top-k**, then **provenance expansion** (case → its txns/cards/devices). Citations land in `evidence[]` (`source: "graph"|"document"`, `ref` = query name or doc section).
- If TigerVector (4.2+) is on the workspace → vectors live on vertices, searched via GSQL. Else: local embeddings + GSQL-filtered candidates (graph still does the filtering — story intact).

---

## 10. Answer-file harness (the actual submission)

```
fraudlens/
├─ README.md  .env.example  Dockerfile(optional)
├─ data/            → symlinks to HHGOA_IEEE (not committed if too big; document)
├─ pipeline/        → D-1 card_id, profiling, loaders, schema.gsql
├─ gsql/            → 10 queries + install script
├─ agent/           → state machine, policy_engine.py, calibrator.py, simulator.py
├─ eval/            → offline metrics on closed cases (AUC, pattern acc, SAR gate, calibration)
├─ runner.py        → `python runner.py --all` → cases/*.json + summary.md
├─ validator.py     → schema-validate every answer file (see checklist)
├─ cases/           → 20 JSON outputs  ← THE SUBMISSION
├─ extra_investigations/   → optional innovation track outputs
└─ docs/            → architecture diagram, blog draft, demo script
```

**validator.py enforces per-case (missing field = zero for that part):**
- [ ] All top-level fields present; `case_id` matches pack.
- [ ] `pattern` ∈ enum; `pattern_description` non-empty iff `undocumented`.
- [ ] Legitimate verdict ⇒ `affected_txn_ids`=[], `exposure_usd`=0, `sar.file`=false.
- [ ] Every id in `affected/connected/first_suspicious/entity_ids/subjects` **exists in dataset** (made-up IDs = zero).
- [ ] `sar.file` ⇔ `FILE_REPORT` ∈ final actions (must agree).
- [ ] Every action ∈ policy enum; route matches policy §2 table; reason cites "R#".
- [ ] `evidence_requests` entries have `type/asked_after_step/assumed_response`.
- [ ] `written_to_graph: true` + real `graph_case_id` (verify via GSQL).
- [ ] `final` ≠ `initial` ⇒ `what_changed` ≠ "nothing" (and vice versa).
- [ ] `fraud_probability` ∈ [0,1]; SAR 6–12 sentences when filed; activity_dates format.

Run validator in CI-style loop until 20/20 green.

---

## 11. Innovation track (stretch, +15%)

**"Night-watch" mode:** sweep Nov 1–Dec 31 transactions, compute per-txn calibrated risk from graph features, pick top alerts *not* in the case pack, run the same investigation loop, write to `extra_investigations/`. Deliverable framing: *the agent found the ring before the model did* — e.g., anonymous-proxy device clusters like HHG-014's. Cheap to build once the runner exists; strong demo moment.

---

## 12. Build sequence & timeline (7-day; compress to 3 by parallelizing with ZCode)

| Day | Track | Exit condition |
|---|---|---|
| **1** | D-1 card_id mapping; schema DDL; profile data | card rule 100% on 5,565 cases; schema created on Savanna |
| **2** | Loaders run full data; queries 1–6 installed & tested | counts match; HHG-014 device neighborhood returns cross-card links |
| **3** | Detectors + calibrator trained on history; offline eval | AUC + pattern accuracy reported; R1–R10 policy engine unit-tested |
| **4** | Agent loop via MCP; case writing; queries 7–10 | one full case runs end-to-end → valid `HHG-xxx.json` passes validator |
| **5** | Run all 20; manual review each; SAR drafting; GraphRAG retrieval wired | 20/20 validator-green; every case reviewed & justified |
| **6** | Dashboard (case queue + graph view + timeline); innovation track | demo path stable on real data |
| **7** | Blog, demo video (3–5 min, script §13), social post, repo polish | submission checklist §14 fully ticked |

**Solo/small-team note:** ZCode is already wired to the graph via MCP — pipeline, GSQL, policy engine, and harness are all executable in-session. Human effort concentrates on: reviewing the 20 case decisions (judgment), recording the demo, writing the blog in your voice.

---

## 13. Demo script (3–5 min, mapped to judging)

1. **0:00–0:30 Problem:** "Risk scores are a reason to look, never a verdict. Half of these alerts are legitimate. We built the investigator, not another score."
2. **0:30–1:30 Graph evidence:** open HHG-014 (the 0.05-risk-score one) — show device neighborhood query surfacing cross-card anonymous-proxy ring. "No flat table makes this obvious."
3. **1:30–2:15 Uncertainty & policy:** show calibrated probability, R1 verify-before-block, approval routing L1/L2 — recommendation is `VERIFY_WITH_CUSTOMER`, not a reflexive block.
4. **2:15–3:00 Evidence changes the action:** simulate customer denial → probability jumps → final actions `BLOCK_CARD`+`CREATE_CASE`+`FILE_REPORT` with `what_changed` narrated.
5. **3:00–3:40 Case memory:** show `AgentCase` written into the graph, similar-prior-case retrieval informing the call; SAR narrative stands alone (who/what/when/where/how/why).
6. **3:40–4:30 Engineering:** architecture slide — Savanna, GSQL/GDS (components/PageRank/Jaccard), MCP allow-list, policy engine, calibration results on 5,565 labeled cases. Benchmark stat across 20 cases.
7. **4:30–5:00 Close:** "The agent doesn't replace the investigator — it makes the investigation connected, calibrated, policy-grounded, and auditable."

---

## 14. Final submission checklist

**Answers** — 20 files in `cases/`, validator-green, each reviewed by a human · SARs only where gated (expect ~1–4 of 20) · `written_to_graph: true` verified by query.
**Repo** — one-command run · `.env.example` (secret already lives only in local ZCode config — never commit) · data dictionary · schema diagram · GSQL sources · MCP setup doc · eval harness + results table.
**Content** — technical blog (what/how/TigerGraph usage/agent design/calibration evidence/lessons) · 3–5 min video · social post linking blog+demo, tagging `@TigerGraphDB`.
**Optional** — `extra_investigations/` from night-watch mode.

---

## 15. Risk register (top 6)

| Risk | Mitigation |
|---|---|
| card_id mapping wrong → all joins broken | D-1 first, 100% validation gate on 5,565 cases |
| Overconfident probabilities → calibration score loss | Platt/isotonic on history; sanity-check "half legit" prior |
| SAR over-filing (only 7% of history filed) | learned gate + explicit "most cases never need a report" default |
| LLM hallucinated evidence | typed evidence contracts from GSQL; validator enforces dataset-real IDs |
| Savanna quota/auto-stop interrupts | batch loads, script everything, verify workspace state before runs |
| UI eats the schedule | CLI-first; dashboard only after 20/20 green |

---

## 16. Start NOW (today's session)

1. Inspect `SentinelGraph` → create `FraudGraph` with §4 DDL.
2. Solve D-1 (card_id rule) — *the critical path*.
3. Load a 10k-txn slice; run query 1 & 4 on HHG-014's transaction; see the ring.

*Everything above is executable from this workspace with the MCP connection already in place. Say "go" and we start with step 1.*
