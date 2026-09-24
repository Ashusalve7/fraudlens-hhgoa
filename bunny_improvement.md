# Bunny Improvement — FraudLens Grand-Finale Readiness Audit

**Audit date:** 25 September 2026  
**Project:** HHGOA × TigerGraph — FraudLens  
**Scope:** All project-owned Markdown, Python, GSQL, JSON case outputs, evaluation artifacts, pipeline files, dashboard source/build files, dependency manifests, and generated metadata. The large CSVs were profiled and queried programmatically. Vendored `node_modules` and `.venv` source was not treated as authored code; their manifests, installed versions, build behavior, and security implications were checked.

> **Remediation status update (25 September 2026):** the findings below are retained as the original audit record. The P0/P1 remediation, regenerated artifacts, graph read-back gate, dashboard build, and release checks are complete; see [§13](#13-final-remediation-status) for the current release state. Historical readiness scores and stale examples in this audit must not be read as current measurements.

---

## 1. Executive verdict

### The short version

**The idea is strong. The current scored submission is not safe to submit unchanged.**

| Measure | Current assessment |
|---|---:|
| Product concept / problem fit | **8.5/10** |
| Prototype and desktop demo quality | **7.5/10** |
| Current grand-finale submission readiness | **4.1/10 — 41/100** |
| Core decision-engine readiness | **3.5/10** |
| Security readiness | **1/10** |
| Clean-reproduction readiness | **3/10** |

The 41/100 is a **readiness estimate**, not a prediction of the hidden answer-key score. The project has a realistic path to become competitive, but a judge can currently disprove several central claims directly from the repository in under five minutes.

### Weighted sponsor-readiness estimate

| Judging surface | Weight | Current estimate | Main reason |
|---|---:|---:|---|
| Investigation accuracy | 25 | **10** | Strong graph foundation, but weak/unsupported pattern evaluation, simplistic episodes, binary overconfidence, and future-data leakage risk |
| Next-best action | 25 | **10** | Approval routes are mostly correct, but SAR gates/narratives, R2 citations, and before/after descriptions contain semantic errors |
| Agentic engineering | 15 | **7** | Explicit workflow and evidence requests exist, but the runtime bypasses MCP, the state machine is mostly sequential labels, and new case memory is write-only |
| Innovation | 15 | **6** | HHG-014 is a strong graph-native story, but no GDS algorithm, no GraphRAG, no unknown-pattern path, and no night-watch output |
| Demo, content, and completeness | 20 | **8** | Polished UI, blog, and demo script; no finished video/social post, broken default launch, stale build, and stale claims |
| **Total** | **100** | **41** | **Not yet submission-ready** |

### What is genuinely impressive

- The product framing is much better than a generic fraud chatbot: connected evidence, policy-grounded action, approval routing, uncertainty, and case memory are the right ideas.
- The core graph is real and large: 590,742 transactions, 13,553 customers, 14,318 cards, 9,706 device profiles, and 5,565 historical cases are currently live.
- The reverse-engineered card identity rule is excellent work and has recorded 100% validation across 4,665 flagged and 14,955 case-listed transactions.
- All 20 answer files exist, all cited dataset/case/card IDs checked during this audit were real, exposure sums were arithmetically correct, and `BLOCK_CARD` approval routing respected the $2,500 L1/L2 boundary.
- All 20 `AgentCase` records are currently retrievable from the live graph.
- The HHG-014 low-risk-score/shared-device story is the strongest possible five-minute demo if it is made graph-accurate and policy-correct.
- The desktop dashboard is polished, information-dense, and visually credible.
- The current source builds successfully, npm reports zero known vulnerabilities, and Lighthouse measured 94/100 for accessibility and 100/100 for best practices.
- No original Kaggle labels, hidden answer key, or explicit per-case answer override was found.

### What currently prevents qualification

1. A live-looking TigerGraph secret is hard-coded in source.
2. The dashboard has a confirmed path-traversal vulnerability that can read arbitrary JSON files.
3. The 20 scored files pass a weak structural validator but contain directly false or contradictory statements.
4. The documented 77.4% pattern-accuracy claim is not supported by the only recorded evaluation artifact, which reports 33.76% for different logic.
5. The actual runtime does not use TigerGraph MCP.
6. No GDS algorithm or working GraphRAG path is implemented.
7. Historical case edges and the transaction chain failed to load; new cases are written after assessment but are not used by later retrieval.
8. The clean-checkout path is broken and essential generated artifacts are ignored.
9. The checked-in frontend build is stale, and the documented FastAPI launch does not serve a working SPA.
10. The required demo video and social post are absent.

---

## 2. What was actually verified

### Successful checks

| Check | Result |
|---|---|
| Project validator | `ALL 20 ANSWER FILES VALID` |
| Live graph write check | 20 `AgentCase` vertices; all 20 `get_agent_case` queries returned records |
| Python syntax | 20 authored Python files parsed successfully |
| Frontend production build | Passed; approximately 593 KB JS / 18–19 KB CSS |
| npm dependency audit | 0 critical, high, moderate, or low known vulnerabilities |
| Browser smoke test | Current Vite source rendered case queue, HHG-014 detail, score explanation, graph view, and analytics without console errors |
| Lighthouse | Accessibility 94, Best Practices 100, SEO 60 |
| ID audit | No unrecognized IDs found in evidence entity lists, prior-case lists, SAR subjects, affected transactions, connected cards, or graph case IDs |
| Exposure audit | Every stated fraud exposure equals the sum of its listed transaction amounts |
| Approval audit | No `BLOCK_CARD` L1/L2 exposure-routing mismatch found |

### Important qualification

`ALL 20 ANSWER FILES VALID` means only that the custom validator's structural checks passed. It does **not** mean the SAR narratives, episode boundaries, pattern decisions, probabilities, evidence claims, or policy rationales are correct.

---

## 3. P0 blockers — fix before sharing or submitting anything

### P0-1 — Rotate the exposed TigerGraph credential immediately

`fraudlens/pipeline/tg.py:17-19` contains live-looking host and secret defaults. This contradicts:

- `fraudlens/.env.example:1-4`
- `fraudlens/README.md:121`

**Impact:** anyone receiving the folder, repository, archive, screen recording, or cloud shell may be able to read or modify the sponsor graph.

**Required fix:**

1. Rotate/revoke the current TigerGraph secret immediately.
2. Remove every real host/secret default from source.
3. Fail startup when `TG_HOST` or `TG_SECRET` is absent.
4. Search every distributed copy and future Git history for the old value.
5. Verify the old credential no longer works.
6. Never place the credential value in this report, a screenshot, a log, or a video.

**Acceptance test:** a secret scanner finds no real credential, and the application refuses to start without a local `.env`.

---

### P0-2 — Fix the dashboard path traversal before any deployment

`fraudlens/dashboard/app.py:71-76` directly builds a filesystem path from `case_id`:

```python
f = CASES_DIR / f"{case_id}.json"
```

The dashboard audit confirmed that URL-encoded Windows path separators can escape `CASES_DIR` and read other project JSON files.

**Required fix:**

- Accept only `^HHG-\d{3}$`.
- Resolve the candidate path.
- Verify the resolved parent remains exactly inside `CASES_DIR`.
- Return 400/404 for every other value.
- Do not return internal filesystem or TigerGraph exception text.
- Bound `window_days` in `/api/graph/ring/{txn}` to a small safe range.

**Acceptance tests:** encoded `..`, backslashes, slashes, absolute paths, and mixed-case traversal attempts all fail without file disclosure.

This is mandatory even for a local demo because it becomes severe the moment authentication or a public URL is added.

---

### P0-3 — The 20 answer files contain judge-visible factual contradictions

The current files produce:

- **13 fraud**
- **7 legitimate**
- **0 uncertain**
- **6 SAR drafts**

But `fraudlens/README.md:19-21` and `fraudlens/docs/DEMO_SCRIPT.md:41-45` claim **11 fraud / 9 legitimate**.

### All 6 SAR files have at least one material narrative defect

| Case | Defect |
|---|---|
| HHG-004 | Exposure is $384.43, but SAR says it exceeds $1,000; no evidence request exists, but narrative says the customer was asked and responded; dates should span Dec 28–30, not only Dec 29; first affected transaction is $92.86, not the claimed $128.33 |
| HHG-005 | Exposure is $100.07, but SAR says it exceeds $1,000 |
| HHG-006 | No evidence request exists, but narrative says the customer was asked/responded; first affected transaction is $478.95, not $482.12 |
| HHG-007 | No cards/devices are listed, but SAR invents a device link and “other compromised cards”; actual dates span Dec 3–6, not only Dec 5; first affected transaction is $221.93, not $111.92 |
| HHG-014 | Exposure is $74.96, but SAR says it exceeds $1,000; no evidence request exists, but narrative says the customer was asked/responded |
| HHG-016 | Exposure is $59.67, but SAR says it exceeds $1,000; no evidence request exists, but narrative says the customer was asked/responded |

The generic template is at `fraudlens/runner.py:412-434`. It always states a >$1,000 exposure, a graph link to other cards, and a customer validation response, regardless of the actual case facts.

### Six `what_changed` descriptions are materially false

The action sequence does not materially change in these cases:

- HHG-004: already `BLOCK_CARD | CREATE_CASE | FILE_REPORT | MONITOR_CONNECTED_CARDS` before evidence; text says it moved “from verify.”
- HHG-006: already block/case/report; text says probability moved `0.98 → 0.98` and the recommendation moved from verify.
- HHG-009: already block/case; text claims a report and a verify-to-block move.
- HHG-016: already block/case/report/monitor; text says it moved from verify.
- HHG-010: already `CLOSE_NO_FRAUD`; text says it moved to close and probability moved `0.00 → 0.00`.
- HHG-019: already `CLOSE_NO_FRAUD`; text says it moved to close and probability moved `0.01 → 0.01`.

Root cause: `fraudlens/runner.py:402-409` generates a story from `denied/confirmed` rather than comparing the actual initial and final action sets.

### Tool and request counters are batch-cumulative

`fraudlens/runner.py:437-449` reuses one `Evidence` object for all 20 cases, while `fraudlens/runner.py:325` exports its cumulative `len(ev.calls)`. The files therefore report `4, 8, 12, ... 94`; the values sum to 967 even though the logical read-plus-write work for the whole batch is approximately 94 calls. The brief defines `tool_calls` per case. `asked_after_step` is affected by the same shared counter.

### Some checked-in cases are incompatible with the current runner logic

HHG-010 and HHG-019 contain an evidence request and simulated confirmation even though their initial action is already `CLOSE_NO_FRAUD`. Under the current code, a validation request is made only when the initial risk alert probability is below 0.85, while an initial close requires probability at or below 0.15. This is a strong sign that the answer artifacts were generated across multiple code versions or are not reproducible from the current source.

### HHG-007 does not include the flagged transaction

Sponsor format requires every fraud episode to include the flagged transaction. HHG-007 lists eight affected transactions but omits flagged transaction `3514948`.

The validator only checks that listed IDs exist, not that the flagged transaction is present.

### The investigation is not consistently “as of” case opening

`fraudlens/runner.py:60-65` deliberately retrieves card context through `t0 + 72h` and device neighborhoods through `t0 + 7d`, even when the sponsor case has already been opened.

Independent checks against `case_pack.csv` found:

- 14 of 20 model card windows include at least one transaction after `opened_at`;
- 12 of 20 online device neighborhoods include future transactions, sometimes hundreds;
- HHG-004, HHG-007, and HHG-012 place future transactions into the affected fraud episode itself.

Examples include six post-opening transactions in HHG-004, three in HHG-007, one roughly 67 hours after the trigger in HHG-012, and 470 future device transactions visible to HHG-013's model window.

This is not the explicit original-Kaggle-label disqualification rule, but it is a serious time-travel/leakage risk and contradicts the project's own time-safe methodology. If retrospective post-alert analysis is intended, state and evaluate that explicitly; otherwise use `opened_at` as the hard cutoff.

### Required fix

- Treat a customer-report trigger as customer denial **before** computing the initial recommendation.
- Build initial/final action tuples and generate `what_changed` from their actual diff.
- Use `"nothing"` when the action sequence is materially identical.
- Never generate a threshold, customer-response, graph-link, or prior-outcome claim unless the corresponding fact is true.
- Compute SAR dates from all affected transactions.
- Use the actual first affected transaction and amount.
- Include the flagged transaction in every fraud episode.
- List every connected card/device that the recommendation claims to monitor, or explicitly say “top 10 of N” and do not imply completeness.

---

### P0-4 — The performance claims are not reproducible or trustworthy yet

### Pattern accuracy contradiction

The documentation claims **77.4%** pattern agreement:

- `fraudlens/README.md:17`
- `fraudlens/README.md:87-92`
- `fraudlens/docs/DATA_DICTIONARY.md:38-39`
- `fraudlens/docs/BLOG.md:55-60`
- `fraudlens/agent/decision.py:46-47`

The only recorded evaluation says:

- **33.76%** in `fraudlens/eval/out/eval_report.txt:7-16`
- **0.3376205788** in `fraudlens/eval/out/model.json:81-84`

Worse, the detector evaluated in `fraudlens/eval/train.py:76-87` is not the production detector in `fraudlens/agent/decision.py:46-56`. Therefore:

- 77.4% is currently unsubstantiated.
- 33.76% is not necessarily production accuracy either, because it evaluates different logic.
- Neither number can be used in the README/blog until the **exact production function** is evaluated and its confusion matrix is committed.

The recorded evaluator gets zero recall for the 16 historical card-testing cases and zero recall for the 9 undocumented cases. Production logic emits no undocumented result at all.

### AUC is real but does not prove final calibration

The time-split logistic model does have a recorded holdout AUC of 0.9752. That is a genuine strength. However:

- Train base rate is 0.819; holdout base rate is 0.896.
- The standardized `flagged_risk` coefficient is about -5.5 because this labeled population is enriched for high-score false positives; a prior shift does not turn that case-selection relationship into a universal transaction-fraud law.
- 76.7% of holdout cases have a customer seen in training.
- 75.9% of holdout cases have a card seen in training.
- The reported Brier score is measured before the manual exam-prior shift and temperature change.
- The production inference path does not apply the same clipping transform used during Platt fitting.
- Final probabilities are forced to at least 0.9 after a simulated denial and at most 0.1 after a simulated confirmation (`fraudlens/runner.py:234-240`).

Current outputs are almost perfectly bimodal:

- 13 probabilities are at least 0.85.
- 5 are exactly 0.10.
- 4 are exactly 0.90.
- 2 are near zero.
- None are in the uncertain 0.15–0.85 range.

That contradicts the blog’s claim that probabilities are spread across the range and makes “calibrated probability” an unsafe label.

### Clean training currently breaks the runner

`fraudlens/agent/decision.py:22-30` requires `train_base_rate`, but `fraudlens/eval/train.py:111-119` does not write it. The current model artifact contains a manually added field, so retraining from source removes it and breaks inference.

### Required fix

1. Make `eval/train.py` emit every field the calibrator consumes.
2. Import and evaluate the exact `decision.detect_pattern` function.
3. Add a customer-disjoint split in addition to the time split.
4. Evaluate calibration **after** prior correction and temperature scaling.
5. Stop hard-setting probabilities to 0.9/0.1 solely from a simulated answer.
6. Commit a small evaluation report and confusion matrix.
7. Replace 77.4% with the regenerated result, even if lower.

Do **not** force the output to exactly 10 fraud and 10 legitimate. Honest calibration matters more than matching a guessed class count.

---

### P0-5 — The required MCP integration is absent from the FraudLens runtime

The sponsor brief tells teams to connect TigerGraph MCP so the agent queries graph tools (`HHGOA_IEEE/README.md:24-27`).

The actual runtime imports a direct `TigerGraphConnection` and invokes `runInstalledQuery`:

- `fraudlens/agent/evidence.py:12-23`

The claim that this is “the same surface MCP exposes” is not equivalent to using MCP. A judge asking “show the MCP trace” will find direct pyTigerGraph calls instead.

Graph writes are even less aligned: `fraudlens/agent/evidence.py:78-107` bypasses the installed `upsert_agent_case` query and directly uses REST upserts.

**Required fix:**

- Put an actual MCP server/client boundary in the runtime path.
- Expose only the allow-listed investigation operations.
- Record MCP tool name, sanitized parameters, latency, result type, and authorization decision.
- Demonstrate one MCP call in the demo recording.
- Either make all graph reads/writes genuinely MCP-mediated or stop claiming that they are.

If MCP cannot be integrated in the remaining time, remove the compliance claim and accept the judging risk; do not imply it exists when it does not.

---

### P0-6 — The graph and case-memory claims are stronger than the loaded graph

A read-only live graph check on 25 September found:

### Loaded vertices

| Vertex type | Live count |
|---|---:|
| Transaction | 590,742 |
| Customer | 13,553 |
| Card | 14,318 |
| DeviceProfile | 9,706 |
| EmailDomain | 60 |
| BillingRegion | 332 |
| ClosedCase | 5,565 |
| AgentCase | 20 |
| PolicyChunk | **0** |

### Edge state

| Edge type | Live count |
|---|---:|
| OWNS_CARD | 14,318 |
| PAID_WITH | 590,742 |
| FROM_DEVICE | 144,432 |
| P_EMAIL | 496,262 |
| R_EMAIL | 137,453 |
| BILLED_IN | 525,003 |
| NEXT_TXN | **0** |
| CASE_TXN | **0** |
| CASE_CARD | **0** |
| CASE_CONN_CARD | **0** |
| CASE_DEVICE | **0** |
| AG_TXN | 172 |
| AG_CARD | 118 |
| AG_DEVICE | 11 |
| AG_SIMILAR | 87 |

The installed query list contains exactly the 10 custom queries. No GDS/community/PageRank/Jaccard algorithm query is installed.

### Consequences

- Historical closed cases are not connected to their transactions/cards/devices.
- Device-to-prior-case retrieval in `get_device_neighborhood` cannot work from historical case edges because all `CASE_DEVICE` edges are zero.
- The README/blog claim that closed investigations link to transactions, cards, and devices is not currently true in the live graph.
- The new `AgentCase` records are written only after assessment and are not queried by `find_similar_cases`, so later investigations do not inherit newly created cases.
- `answer_json` is stored as the literal string `"exported"`, not the full answer (`fraudlens/runner.py:281-295`).
- Every `AG_SIMILAR` edge receives a fabricated score of `1.0` (`fraudlens/agent/evidence.py:96-105`).
- `PolicyChunk` is empty, and no policy/regulatory vector retrieval exists.
- `NEXT_TXN` is declared but empty.

The local loader record confirms the incomplete state:

- `fraudlens/pipeline/out/load_log.json:67-70` marks `e_NEXT_TXN` failed.
- `fraudlens/pipeline/load_graph.py:78-106` exits on the first failure, so later historical case edges never load.
- `fraudlens/pipeline/load_graph.py:110-117` verifies vertices only, not edges.
- `fraudlens/pipeline/out/graph_counts.json:2-8` is stale and reports zero transactions/devices/closed cases despite the live graph now containing them.
- `CASE_DEVICE` is queried but not present in the load plan.
- `v_DeviceProfile.parquet` does not contain the schema’s `n_fraud_cases` field.

**Required fix:** complete and verify the graph, then regenerate a current health artifact containing both vertex and edge counts.

---

### P0-7 — The project does not run cleanly from a fresh checkout

The README’s one-command path is currently invalid.

### Broken dependencies/artifacts

- `fraudlens/.gitignore:2-3` ignores `pipeline/out/` and `eval/out/`.
- The runner requires ignored `eval/out/model.json` (`fraudlens/agent/decision.py:11,22-30`).
- The loader requires ignored `pipeline/out/txn_card_map.parquet`, but the README never runs the final card-ID derivation step.
- There is no `pyproject.toml`, `requirements.txt`, or `uv.lock`.
- FastAPI and Uvicorn are omitted from the documented install command.
- There is no dataset download/checksum/location guide.
- The instructions are Windows-specific despite the project using Python cross-platform scripts.
- No authored test/spec files exist.
- No CI exists.
- The workspace is not a Git repository.
- `node_modules` is not ignored.
- `pipeline/out` and `eval/out` are ignored even though parts of them are required runtime artifacts.
- The non-vendor project tree is about 804 MB; the raw transaction CSV alone is about 708 MB and cannot be committed normally to GitHub.

### Required fix

Create one reproducible path such as:

1. Install `uv` and sync a locked Python environment.
2. Validate/download the sponsor dataset outside Git.
3. Run final card-ID derivation.
4. Train and validate the model.
5. Build/load the graph.
6. Verify all expected vertex and edge counts.
7. Run all 20 investigations.
8. Run semantic validation.
9. Build and serve the dashboard.
10. Print one run manifest with versions, graph name, model hash, schema hash, and case-output hashes.

Commit the small trained model artifact if it is required at runtime, or train it as an explicit setup step. Do not ignore a file that the application cannot run without.

---

### P0-8 — Mandatory content and a reliable demo path are missing

Missing authored artifacts:

- No 3–5 minute demo video.
- No social post.
- No verified public demo URL.
- No optional night-watch output.
- No architecture image.
- No screenshots for the README/blog.
- No team attribution.
- No license.
- No deployment instructions.

The dashboard launch path is also unreliable:

- `fraudlens/dashboard/app.py:45-47` serves the Vite development `index.html`.
- That HTML points to `/src/main.jsx`.
- FastAPI does not mount Vite source, `dist`, or an SPA fallback.
- Direct/refreshed case routes return 404 under FastAPI.
- The checked-in `dist` predates the latest source and contains the older dark dashboard.
- A fresh source build produces different asset hashes.
- The documented FastAPI-only launch therefore cannot be the demo path.

The demo script also has two sections both labeled `3:00–3:40` (`fraudlens/docs/DEMO_SCRIPT.md:37-51`), pushing the sequence beyond five minutes.

**Required fix:** serve the current production `dist` from FastAPI with an SPA fallback, rebuild it, document one launch command, prewarm the routes, and record the final demo only after two clean rehearsals.

---

## 4. Case-by-case risk review

This table is a review priority, not a hidden answer key. “High” means the current file contains a visible contradiction or a decision that needs manual investigation before submission.

| Case | Current result | Risk | Main issue / required review |
|---|---|---|---|
| HHG-001 | Fraud, OOR, p=.9795, immediate block | **High** | Evidence does not show an unseen region, continued home activity, or customer denial. The project’s own build plan calls out the trip-vs-clone ambiguity. R2 is cited without denial. |
| HHG-002 | Fraud, CNP, verify → block | Medium | Good before/after shape, but final p is forced to .90 and `what_changed` says “report” although no `FILE_REPORT` is recommended. Similar cases do not influence the decision. |
| HHG-003 | Legitimate, R7 | Medium | Recurring evidence is plausible, but the code checks count + 30-day span, not genuinely monthly recurrence. Confirm the transaction belongs to the same card/customer history intended by R7. |
| HHG-004 | Fraud, new device, 8 txns, SAR | **Critical** | Future transactions enter the episode; no evidence request; false >$1,000 SAR text; false action change; wrong first amount/date range; device ID claim is actually a transaction ID. |
| HHG-005 | Fraud, new device, SAR | **Critical** | SAR falsely says exposure exceeded $1,000. Initial reason calls p=.81 “below 0.70.” A 112-card device is treated as a fraud link without connected-card outcomes. |
| HHG-006 | Fraud, new device, 4 txns, SAR | **Critical** | Customer-report denial is treated correctly as initial evidence in concept, but no request is recorded while narrative says “asked/responded.” First transaction amount in SAR is wrong. Device has 543 cards but monitoring is omitted due an arbitrary threshold. |
| HHG-007 | Fraud, ATO, 8 txns, $10,797, SAR | **Critical** | Flagged transaction is missing. All episode rows are card-present; no mixed-channel/device/match anomaly supports ATO. Denial of one $111 transaction is used to label eight other purchases fraudulent. SAR invents graph links, dates, and amount facts. |
| HHG-008 | Legitimate, R7 | Medium | Plausible recurring case; enforce actual monthly cadence and ensure the same card—not merely customer history—is used. |
| HHG-009 | Fraud, CNP | **Critical** | Customer denial is already in the trigger, yet output claims verify-to-block change. Device has 1,013 cards; only 10 are listed. Narrative says a report despite no report action. |
| HHG-010 | Legitimate, p=.0046, auto-close | **Critical** | Evidence request/simulated confirmation contradicts an initial auto-close. A $1,000 new-device transaction receives almost zero probability with no independent evidence explanation. Retrieved cases are confirmed-fraud cases, but text says they resemble cleared alerts. |
| HHG-011 | Legitimate, R7 | Medium | Same monthly-recurrence weakness. New-device context is not reconciled explicitly with the legitimate conclusion. |
| HHG-012 | Fraud, OOR, 2 txns, immediate block | **High** | Includes a transaction about 67 hours after the trigger while evidence claims ±24 hours. No evidence demonstrates new region plus continued normal home activity. R2 is cited without denial. |
| HHG-013 | Fraud, CNP, verify → block | Medium | Action change is conceptually useful, but final p is forced to .90 and `what_changed` mentions a report that is absent. Shared-device count is not tied to connected fraud. |
| HHG-014 | Fraud, new device, 52-card ring, SAR | **Critical** | Strong graph trigger, weak classification. The internal plan describes this as a shared-device ring/R6-R9 hunt, yet output forces a documented CNP-new-device label. SAR falsely says >$1,000 and customer response. Evidence names a transaction as the device profile. |
| HHG-015 | Legitimate, verify → close | Medium | Better action evolution, but simulated confirmation says memory resembles cleared cases while `find_similar_cases` only returns confirmed fraud. Final p is forced to .10. |
| HHG-016 | Fraud, new device, SAR | **Critical** | Customer denial is already present; no request is recorded. False >$1,000 SAR claim and false action-change narrative. Shared-device link lacks connected fraud confirmation. |
| HHG-017 | Fraud, CNP, 3 txns, immediate block | **High** | Hidden proxy and repeated near-$100 purchases are useful, but p=.963 causes immediate block without a controlled evidence request. Pattern logic is not a formal card-testing detector. |
| HHG-018 | Legitimate, R7 | Medium | Recurring explanation may be valid, but 65 repeats do not prove monthly cadence. This case also has anomalously high recorded latency (12.88s). |
| HHG-019 | Legitimate, p=.0119, auto-close | **Critical** | Initial and final are both close; text says it moved to close. High-score/new-device facts are dismissed without independent evidence. Retrieved confirmed-fraud cases are described as cleared-alert memory. |
| HHG-020 | Fraud, new device, immediate block | **High** | One New online transaction becomes p=.969 and an immediate block. R2 is cited without customer denial. This is exactly the kind of overconfident single-signal action the product claims to avoid. |

---

## 5. Technical assessment by aspect

## 5.1 Problem framing and product strategy — 8.5/10

### Strengths

- Clear analyst user and fraud-operations use case.
- Strong promise: a defensible action, not another score.
- Correctly separates internal case from regulatory report.
- Approval-aware recommendations are a credible differentiator.
- HHG-014 demonstrates why a graph can reveal something a flat alert score misses.

### Weakness

The implementation no longer matches the original product promise. The strongest idea was **uncertainty-aware next-best action**, but the current agent produces almost entirely binary outcomes, uses hard probability floors/ceilings, and does not show evidence confidence or decision readiness.

**Improvement:** make uncertainty a first-class object with:

- fraud likelihood;
- evidence completeness;
- contradictions;
- decision readiness;
- information value of the next evidence request;
- least-invasive action first.

---

## 5.2 Data engineering and graph foundation — 6/10

### Strengths

- Correct source row scale and graph counts for core entities.
- Stable card mapping with complete recorded validation.
- Useful transaction/identity/device/region normalization.
- Reasonable loader chunking and upsert-based design.
- Typed evidence layer is better than passing arbitrary rows to a model.

### Weaknesses

- Loader stopped at `NEXT_TXN`; historical case edges never loaded.
- No final edge-count verification.
- `CASE_DEVICE` absent.
- `PolicyChunk` absent.
- Device fraud-count attribute absent.
- Generated model/card-map/health artifacts are inconsistently ignored.
- No schema/data version manifest.
- No checksums.
- No clean data bootstrap.
- Exploratory card-rule scripts clutter the public project.

**Improvement:** make graph creation finish-or-fail, verify expected counts, and write a machine-readable `graph_health.json` with every vertex and edge.

---

## 5.3 TigerGraph depth and sponsor differentiation — 4.5/10

### Strengths

- The graph is not a cosmetic wrapper around random UI data.
- The live device traversal behind HHG-014 is a genuine two-hop graph question.
- 590k transactions and the device/card/region model are substantial.
- Ten installed GSQL queries are available.

### Weaknesses

- No GDS algorithm is installed or used.
- No community detection, PageRank/centrality, shortest path, similarity, or link prediction result affects a decision.
- No actual MCP trace.
- No GraphRAG.
- Historical case graph is disconnected.
- Similar-case retrieval is a weak pattern/outcome/exposure filter, not semantic or entity-overlap similarity.
- The closed-case query accepts exposure but ignores it in GSQL and first selects the lowest 200 exposures, biasing “nearest” results downward.

### Improvement

For HHG-014, run one real connected-components or community algorithm over a device–card–customer graph and tie the output to R6/R9:

- component size;
- number of connected customers;
- prior confirmed cases;
- shortest path from trigger to a prior fraud case;
- how the result changed the action.

One truthful algorithm tied to a decision is worth more than three algorithm names in a slide.

---

## 5.4 Machine learning and calibration — 4.5/10

### Strengths

- Small, explainable logistic model.
- Time-ordered split.
- AUC 0.9752 is a strong recorded discrimination result.
- Feature values and directional effects are inspectable.
- No original Kaggle outcomes or hidden labels were found.

### Weaknesses

- Unsupported 77.4% claim.
- Recorded pattern evaluator differs from production.
- Train/holdout base-rate drift.
- High customer/card overlap in holdout.
- Calibration metric is measured before production prior/temperature changes.
- Manual prior and temperature tuning lack a defensible validation protocol.
- Hard simulation overrides destroy final calibration.
- Output distribution is bimodal rather than spread.
- No confidence interval or reliability diagram committed.
- Clean training output is incompatible with runtime.

**Improvement:** report AUC, Brier, ECE/reliability, confusion matrix, customer-disjoint AUC, and temporal AUC separately. Do not call the final score calibrated until it is calibrated after the final transformation.

---

## 5.5 Pattern detection and investigation accuracy — 3.5/10

The production detector is mostly a channel heuristic:

- online + high count → card testing;
- online + new-device share → new-device CNP;
- any other online → CNP;
- in-person + low prior region → OOR;
- everything else in-person → ATO.

This misses the benchmark’s definitions:

- Card testing is not ≥40 transactions in 24 hours; it is at least three tiny online authorizations in one hour followed by a larger purchase.
- CNP should require online inconsistency/burst evidence, not online channel alone.
- OOR must distinguish a clone from a legitimate trip using normal home activity and duration.
- ATO requires mixed-channel/device/match anomalies pointing to credentials, not merely card-present spending.
- There is no `undocumented`/unknown branch.
- There is no contradictory-evidence path.
- No produced answer is `uncertain`.

**Improvement:** implement a rule registry per sponsor definition, with explicit required/supporting/contradictory signals, and an `undocumented` path. Evaluate the exact production registry on labeled cases, including a legitimate-class accuracy metric.

---

## 5.6 Agentic engineering and MCP — 4.5/10

### Strengths

- Explicit per-case workflow labels.
- Typed evidence access.
- Controlled evidence requests are recorded when used.
- Approval routing is deterministic.
- Cases are persisted to TigerGraph.
- No LLM is allowed to invent decision facts.

### Weaknesses

- The “state machine” is mostly a sequential function appending state names.
- No guarded transition object, retry policy, timeout, tool budget, checkpoint, or error state.
- Runtime bypasses MCP.
- No LLM, so `tokens` is always 0.
- Similar cases do not influence the decision; they mainly inflate the evidence count and stop condition.
- Evidence-response selection is circular: model probability chooses denial/confirmation, then the answer forces the probability to .9/.1.
- `n_independent` counts the presence of a transaction row, device ID, and similar IDs rather than genuinely independent evidence.
- `stop_reason()` returns a successful stop for every branch, including the fallback “further steps unlikely” message, so there is no genuine continue/escalate path driven by tool budget or unresolved uncertainty.
- No action, approval, evidence-request, or timeline entities are persisted in the graph.
- New cases are not retrievable by later cases.
- Several installed queries are presentation assets rather than active tools: the runner does not call the region, shared-network, or email-crosslink queries.
- `Evidence.customer_history()` reads a result block named `T2`, while the installed query prints `T`, so that wrapper would return no transaction history if used.

**Improvement:** use a typed state object and transition table, a per-case tool ledger, actual MCP tools, and persisted Evidence/Action/Approval/Timeline records. An LLM may be used only for schema-validated explanation or an unknown-pattern hypothesis; it should not choose facts or actions.

---

## 5.7 Policy, SAR, and next-best action — 3.5/10

### What works

- Action names are mostly exact enum values.
- `auto`, `L1`, and `L2` routes are generally correct.
- Exposure-based `BLOCK_CARD` routing is correct.
- R3 and R7 appear in appropriate places.
- SAR `file` agrees with final `FILE_REPORT` structurally.

### What fails

- High-probability blocks cite R2 without customer denial.
- Shared device usage is treated as shared fraud without checking any connected-card outcome.
- The R6 SAR gate conflicts with the historical 4.8% shared-device filing rate.
- R5 testing logic does not implement the sponsor’s small-auth sequence.
- R9 unknown/coordinated abuse is not implemented.
- R4 timeout behavior is present in code but not meaningfully exercised.
- R7 does not verify monthly cadence.
- Episode expansion marks every transaction in a time window fraudulent without anomaly filtering.
- SAR narratives contain generic false facts.
- The current 6/20 SAR rate is a 30% draft rate versus a 7.1% historical filing rate; some shared-origin cases may qualify, but four current narratives rely on a threshold they do not meet.

**Improvement:** separate:

1. factual pattern evidence;
2. policy preconditions;
3. action generation;
4. narrative rendering.

The renderer must never add a fact that the evidence object does not contain.

---

## 5.8 Answer files and validator — 4/10

### Strengths

- All 20 files exist and parse.
- Required top-level structure is mostly present.
- IDs, exposure sums, and block approval thresholds are strong.
- SAR sentence-count checks work.

### Weaknesses

The validator in `fraudlens/validator.py:37-149` does not check:

- exact JSON types/no extra fields;
- flagged transaction included in a fraud episode;
- unique affected IDs;
- episode evidence consistency;
- evidence claim truth;
- evidence entity ID validity;
- SAR subject validity;
- graph case existence per file;
- SAR exposure/date/amount/narrative consistency;
- customer-request consistency;
- policy preconditions;
- block exposure routing;
- true initial/final action difference;
- per-case tool-call delta;
- future transactions after `opened_at`;
- production detector accuracy;
- graph edge completeness.

**Improvement:** replace the structural smoke test with a semantic validator and at least 30–50 focused tests.

---

## 5.9 Dashboard and user experience — desktop 8/10, release 4/10

### Strengths

- Coherent, polished operations-console visual design on desktop.
- Useful case queue, analytics, score explanation, policy actions, and graph context.
- Real API/graph data rather than hardcoded mock cards.
- Good focus-visible and reduced-motion CSS.
- Native buttons/links for most interactions.
- No obvious React injection sink.
- Good component decomposition.
- Current source production build passes.

### Release blockers

- Path traversal.
- No working documented launch path.
- Stale `dist`.
- No SPA fallback.
- Fixed 240px sidebar breaks mobile/tablet.
- At 390px, the current source overflows badly; the graph becomes unusably narrow.
- The active graph truncates 52 connected cards to four with no “48 more” indicator.
- Three prior-case edges originate from a missing case node.
- Graph layout overlaps and card labels do not fit their nodes.
- The graph is static rather than interactive.
- No GDS result is shown.
- The strongest graph is below the fold because score explanation opens by default.
- No evidence timeline/audit trail.
- No uncertainty/contradiction panel.
- No evidence-request simulation controls.
- No approval/rejection/escalation controls.
- No report export.
- “Agent confidence” is actually fraud probability.
- Evidence confidence and decision readiness are missing.
- “SARs filed” should be “SAR drafts recommended.”
- Similar cases are IDs without outcomes or influence.
- API errors are often rendered as empty states or misleading fallback values.
- Status always says “Agent systems operational,” even if graph stats fail.
- Duplicate `/api/cases`, `/api/graph/stats`, and `/api/explain` calls are common.
- Cold graph-stat calls take roughly 3–7 seconds; explain calls about 3.8 seconds.
- No auth if exposed beyond localhost.
- Internal TigerGraph errors are returned to clients.
- Production JS is around 593 KB and triggers Vite’s large-chunk warning.

**Improvement:** make the dashboard a truthful evidence workspace, not a results gallery. Prioritize graph legibility, timeline, uncertainty, and request/approval flow over more charts.

---

## 5.10 Documentation and narrative — 5.5/10

### Strengths

- README is concise and understandable.
- Blog has a good narrative voice and useful technical discoveries.
- Demo script has a strong five-minute shape.
- Data dictionary correctly highlights the card mapping rule and key feature semantics.

### Weaknesses

- README/blog/data dictionary repeat unsupported 77.4%.
- README/demo claim 11/9; current outputs are 13/7.
- Demo uses HHG-001 behavior that the current file does not exhibit.
- Demo has overlapping time slots.
- Blog says new case memory makes later investigations smarter; current retrieval does not.
- Blog says graph is more than a checkbox while no GDS algorithm is shown.
- “Secrets never committed” is false.
- “One-command run” is false from a clean checkout.
- The root folder contains AI-authored planning documents and an outdated “Start NOW” plan, which makes the project look unfinished.
- No architecture image, team names, demo links, screenshots, license, or changelog.

**Improvement:** update docs only from regenerated artifacts. Create a claim ledger so every number in README/blog/UI points to a committed result file or live query.

---

## 5.11 Security, privacy, and operational safety — 1/10 before remediation

### Critical

- Hard-coded live-looking TigerGraph secret.
- Path traversal / arbitrary JSON read.

### Important if publicly deployed

- No authentication or authorization.
- Graph mutation/read endpoints exposed through the dashboard API.
- Internal graph errors leaked to clients.
- Unbounded graph traversal window.
- Static “operational” indicators can be false.
- No CSP/security headers/rate limiting.

### Acceptable for a local anonymized demo

- No real PII was found; the sponsor states the data is anonymized.
- npm audit is clean.
- Major frontend dependencies are locked.
- Current React code avoids obvious unsafe HTML injection.

**Improvement:** rotate the secret, fix traversal, bind services to loopback by default, add auth before any public URL, validate all parameters, and return generic errors.

---

## 5.12 Reproducibility, testing, and repository hygiene — 3/10

- No Git repository.
- No Python lockfile.
- No tests.
- No CI.
- No lint/type-check configuration.
- No one-command demo script.
- No graph health gate.
- No model/schema/data manifest.
- No Dockerfile or deployment configuration.
- `node_modules` is not ignored.
- Required generated files are ignored.
- Raw 708 MB CSV creates a GitHub packaging problem.
- Exploratory scripts are mixed with production pipeline code.
- Build output and source are out of sync.

**Improvement:** a clean repository and automated acceptance suite are more valuable now than another UI page.

---

## 6. Claim verification table

| Claim | Current truth | Action |
|---|---|---|
| “20/20 answer files valid” | Structurally true, semantically false in several cases | Replace with “20/20 schema-valid” only after semantic validator passes |
| “20/20 written to graph” | True for `AgentCase`; historical case edges are absent | Keep, but do not imply full memory/timeline persistence |
| “Holdout AUC 0.975” | Recorded and credible for that model/split | Keep with split/base-rate/overlap caveats |
| “Pattern detector 77.4%” | Unsupported; only recorded evaluator says 33.76% and uses different logic | Delete until exact production detector is reevaluated |
| “11 fraud / 9 legitimate” | Stale; current files are 13/7 | Regenerate docs after final case review |
| “Graph has vector attributes” | Schema declares them | Keep only as schema fact |
| “GraphRAG/case-note retrieval” | Not implemented | Remove or implement |
| “MCP-connected runtime” | Not implemented in FraudLens | Remove or implement |
| “Graph access only through installed GSQL” | Reads mostly yes; writes and dashboard stats are direct | Reword or make true |
| “One-command run” | False from clean checkout | Fix and rehearse |
| “Secrets are never committed” | False | Remove secret, rotate, then restore claim |
| “Later investigations inherit new case memory” | False; retrieval searches historical `ClosedCase` only | Implement or remove |
| “SARs filed” | These are recommendations/drafts | Change UI wording |
| “Agent confidence” | This is fraud probability | Relabel or implement separate confidence |
| “Answers valid” dashboard badge | Misleading given semantic errors | Hide until stronger validator passes |

---

## 7. Prioritized rescue plan

# P0 — submission safety and scored-output correctness

## 1. Security containment — 30–60 minutes

- Rotate the TigerGraph secret.
- Remove hardcoded credentials.
- Fix `case_id` traversal.
- Add parameter bounds and generic API errors.
- Do not publish a zip, repository, video, or cloud URL before this is complete.

## 2. Freeze and manually review the 20 cases — 2–3 hours

Review in this order:

1. HHG-004
2. HHG-005
3. HHG-006
4. HHG-007
5. HHG-009
6. HHG-010
7. HHG-012
8. HHG-014
9. HHG-016
10. HHG-019
11. HHG-001, HHG-017, HHG-020
12. Remaining R7 cases

For each case, write down:

- exact trigger evidence available at `opened_at`;
- independent evidence sources;
- episode transaction rule;
- documented or unknown pattern;
- probability before/after simulated evidence;
- policy rule and approval route;
- whether connected cards have actual fraud evidence;
- exact SAR reason, dates, amounts, and subjects.

## 3. Fix the decision/export engine — 2–4 hours

- Reset or delta-count tool calls per case.
- Make `asked_after_step` local to the case.
- Interpret customer-report denial before initial action.
- Generate `what_changed` from actual action diffs.
- Use `opened_at` as the investigation cutoff unless retrospective use is explicitly allowed.
- Filter episode transactions by anomaly/pattern evidence, not merely time proximity.
- Always include the flagged transaction in a fraud episode.
- Remove hard p=.9/p=.1 overrides from the calibrated score; if a scenario override is needed, store it separately from probability.
- Implement a real unknown-pattern path.
- Generate SARs from structured facts, not a generic paragraph.

## 4. Replace the validator — 1–2 hours

Add checks for every issue listed in section 5.8. The validator should fail on:

- HHG-007’s current missing flagged transaction;
- HHG-004’s current false threshold/date/action-change claims;
- any future transaction after case opening;
- any false SAR sentence;
- any non-monotonic cumulative tool count.

## 5. Make one clean run work — 2–4 hours

- Add `pyproject.toml` and `uv.lock`.
- Add one `setup`/`demo` command.
- Correct model serialization.
- Commit or deterministically regenerate required small artifacts.
- Document dataset location/checksum.
- Complete graph load and verify edges.

## 6. Repair and record the demo — 1–2 hours

- Serve current `dist` from FastAPI with SPA fallback.
- Rebuild `dist`.
- Remove misleading labels.
- Prewarm `/`, `/cases/HHG-014`, and `/analytics`.
- Record two clean rehearsals.
- Produce the required video and social post.

# P1 — needed to be genuinely competitive

## 7. Make TigerGraph central rather than decorative

- Implement actual MCP-mediated tool calls.
- Finish and verify `NEXT_TXN`, `CASE_TXN`, `CASE_CARD`, `CASE_CONN_CARD`, and `CASE_DEVICE`.
- Make new `AgentCase` records retrievable by later investigations.
- Persist actual answer/evidence/action/timeline data.
- Run one GDS algorithm whose result changes a decision.
- Use HHG-014 as the proof.

## 8. Rebuild pattern and calibration evaluation

- Evaluate exact production code.
- Add a documented `undocumented` path.
- Implement true R5 card-testing logic.
- Add OOR trip-vs-clone logic.
- Add ATO anomaly requirements.
- Add customer-disjoint evaluation.
- Evaluate post-shift calibration.
- Commit the confusion matrix and reliability data.
- Remove 77.4% unless regenerated.

## 9. Add a small but real GraphRAG path

At minimum:

- load policy R1–R10 and the five pattern definitions into `PolicyChunk`;
- embed a bounded set of historical analyst notes;
- graph-filter by pattern/action/entity;
- retrieve policy/note context;
- cite the exact source in evidence;
- show one retrieval in the demo.

Do not add a large multi-agent system before this smaller grounding path works.

## 10. Convert the dashboard into the intended workspace

Priority order:

1. Working launch and current build.
2. Legible full graph with “N more” nodes.
3. Timeline and evidence requests.
4. Separate fraud likelihood, evidence confidence, and decision readiness.
5. SAR draft/export.
6. Approval/reject/escalate/simulate controls.
7. Request caching and API error states.
8. Mobile layout.
9. Route-level code splitting.

# P2 — only after the core is correct

- Night-watch innovation track.
- LLM-generated but schema-validated explanations.
- Counterfactual “what evidence would change this?” panel.
- Public authenticated deployment.
- Additional graph algorithms.
- More charts.

Do not build these while the current 20 answers contain false statements.

---

## 8. Six-hour minimum rescue plan

If time is extremely limited, do only this:

### Hour 0–1: Security and launch

- Rotate/remove secret.
- Fix path traversal.
- Serve current `dist` with SPA fallback.
- Rebuild `dist`.

### Hour 1–3: Scored-output correctness

- Fix tool-call deltas.
- Fix `what_changed`.
- Fix all SAR narratives/dates/amounts.
- Include flagged transaction.
- Apply `opened_at` cutoff.
- Manually review the 11 critical/high cases.

### Hour 3–4: Validation

- Add semantic checks.
- Ensure 20/20 pass for the right reasons.
- Remove unsupported 77.4% and stale 11/9 claims.

### Hour 4–5: Demo truthfulness

- Use HHG-014 graph and HHG-002 action evolution.
- Avoid HHG-004 until fixed.
- Change “SARs filed” to “SAR drafts recommended.”
- Change “Agent confidence” to “Fraud probability.”
- Prewarm all routes.

### Hour 5–6: Submission package

- Record the 3–5 minute video.
- Write the social post.
- Add links to README.
- Do a clean hard-refresh smoke test.

This will not complete every stretch goal, but it will remove the easiest ways for a judge to reject the project.

---

## 9. Full 24-hour competitive plan

| Time | Parallel track A: correctness | Parallel track B: differentiation | Parallel track C: submission |
|---|---|---|---|
| 0–4h | Secret, traversal, episode/action/SAR fixes | Finish graph edges | Lock repository and clean setup |
| 4–8h | Semantic validator + manual review | Actual MCP trace | Rebuild dashboard and prewarm demo |
| 8–12h | Pattern/calibration correction | One GDS algorithm on HHG-014 | Update README/blog/evaluation report |
| 12–16h | Case-memory write/read correction | Small policy/case GraphRAG | Dashboard timeline/uncertainty panel |
| 16–20h | Full clean rerun and independent review | Fix only issues found | Record final video rehearsal |
| 20–22h | Verify all hashes/counts/routes | Final demo polish | Publish blog/video/social links |
| 22–24h | Freeze submission; no feature work | Buffer for cloud failure | Final team review and archive |

If the graph workspace or MCP fails during recording, have a pre-recorded video and cached local evidence bundle ready.

---

## 10. Definition of done before submission

### Security

- [ ] Old TigerGraph secret revoked.
- [ ] No real credentials in source, logs, notebook, archive, or video.
- [ ] Path traversal tests pass.
- [ ] Services bind to loopback or have auth.
- [ ] API parameters are bounded and validated.

### Scored outputs

- [ ] Exactly 20 case files from the final run.
- [ ] Every fraud episode includes the flagged transaction.
- [ ] No affected transaction is after `opened_at`, unless retrospective mode is explicitly supported and consistently evaluated.
- [ ] Exposure sums match exactly.
- [ ] Every evidence claim is true and traceable.
- [ ] Similar cases have outcomes and a stated influence, or are not claimed as decision evidence.
- [ ] `what_changed` is `"nothing"` exactly when actions do not materially change.
- [ ] Every SAR threshold claim is true.
- [ ] SAR dates, first transaction, amount, subjects, device/card links, and response assumptions are factual.
- [ ] SAR filing is justified by actual policy evidence, not mere device reuse.
- [ ] No high-impact action is recommended solely because the model crossed a hard threshold.
- [ ] Unknown and uncertain cases are representable.

### Evaluation

- [ ] Exact production detector evaluated.
- [ ] Confusion matrix committed.
- [ ] 77.4% removed or reproduced.
- [ ] Temporal and customer-disjoint metrics reported.
- [ ] Post-transform calibration reported.
- [ ] Model serialization is deterministic and complete.

### TigerGraph

- [ ] Actual MCP trace recorded.
- [ ] All expected vertex counts pass.
- [ ] All expected edge counts pass.
- [ ] `NEXT_TXN` nonzero and valid.
- [ ] Historical case edges nonzero.
- [ ] `CASE_DEVICE` generated and loaded.
- [ ] `PolicyChunk` populated if RAG is claimed.
- [ ] New cases are retrievable by later cases.
- [ ] Full answer/evidence/action/timeline persisted where claimed.
- [ ] At least one GDS result changes a decision.

### Dashboard

- [ ] One documented launch command.
- [ ] Current `dist` matches source.
- [ ] `/`, case routes, and analytics survive hard refresh.
- [ ] No mobile horizontal overflow.
- [ ] Graph shows all relevant context or explicit truncation.
- [ ] No orphan graph edges.
- [ ] Timeline, uncertainty, evidence requests, and SAR draft wording are present.
- [ ] “Fraud probability,” “evidence confidence,” and “decision readiness” are distinct.
- [ ] No false live/operational/valid indicators.

### Submission

- [ ] Git repository with clean history.
- [ ] Python and Node dependencies locked.
- [ ] Dataset acquisition/checksum documented.
- [ ] Tests and CI run.
- [ ] License and team attribution added.
- [ ] Blog claims match final artifacts.
- [ ] 3–5 minute video recorded twice.
- [ ] Social post written and links tested.
- [ ] Public URL/auth or explicit local demo instructions provided.

---

## 11. Recommended five-minute demo after fixes

### 0:00–0:30 — Problem

> “Risk scores are a reason to look, not a verdict. We built a controlled fraud investigator that gathers connected TigerGraph evidence, represents uncertainty, follows the bank’s action policy, and records an auditable case.”

Show the benchmark page with truthful, regenerated numbers.

### 0:30–1:30 — HHG-014 graph-native investigation

- Open `/cases/HHG-014`.
- Show the low risk score, New device, anonymous proxy.
- Show the real 52-card/60-transaction neighborhood.
- Show the GDS component result and prior fraud path.
- Explain why this is a coordinated/undocumented ring or why the documented CNP label is correct.

### 1:30–2:20 — Evidence changes action

Use **HHG-002**, not HHG-004:

- Initial: verify + step-up.
- Clearly labeled simulated denial.
- Final: block + case with L1 route.
- Show the actual action diff and probability treatment.

### 2:20–3:00 — Policy and approval

- Show exact R1/R2 citation.
- Show agent recommendation versus human authorization.
- Show why no autonomous high-impact action is taken.

### 3:00–3:40 — Graph case memory

- Show `AgentCase` and actual evidence/action/timeline records.
- Retrieve a genuinely similar historical or prior generated case.
- Show the outcome and exact influence on the recommendation.

### 3:40–4:20 — Honest evaluation

Show:

- exact production pattern accuracy/confusion matrix;
- temporal AUC;
- customer-disjoint AUC;
- calibration after prior shift;
- 20/20 semantic validation;
- graph vertex/edge health.

### 4:20–5:00 — Close

> “FraudLens does not replace the investigator. It makes the investigation graph-grounded, uncertainty-aware, policy-exact, and auditable.”

---

## 12. Final recommendation (historical audit snapshot)

### Do not submit the original snapshot.

The strongest reason is not a missing stretch feature. It is that the original repository allowed a judge to verify these contradictions:

- “77.4%” versus 33.76% in the only evaluation artifact;
- “11/9” versus 13/7 in the original cases;
- “$74.96 exposure exceeded $1,000” in a SAR;
- “moved from verify” when the initial action was already block;
- “secrets never committed” while a live-looking secret was in source;
- “case memory” while historical case edges were zero and new cases were not retrieved;
- “one-command run” while required artifacts were ignored and training output broke inference; and
- “MCP-connected” while runtime code directly used pyTigerGraph.

Those findings are preserved above as the reason for the remediation work. They are not claims about the regenerated snapshot.

---

## 13. Final remediation status

### Verified release artifacts

- The final 20-case pack passes `fraudlens/validator.py` locally and through MCP graph read-back: **20/20 valid** for both gates.
- The final graph-health contract is **healthy**: **634,292 vertices** and **2,506,735 edges**, with zero static count or orphan failures and 20 managed `AgentCase` vertices.
- The final serialized model reports holdout AUC **0.9822**, Platt Brier **0.0332**, post-shift Brier **0.0558**, customer-disjoint AUC **0.9703**, and exact production pattern agreement **0.2349**. The last value is explicitly a noisy-label diagnostic, not model accuracy.
- The corrected global GDS degree-centrality artifact is recorded as provenance-only and is not used as case evidence or authorization input.
- The frontend production build succeeds, Lighthouse reports accessibility **100**, best practices **100**, and SEO **100** on the queue, HHG-014, and analytics routes; the backend/static suites pass, Ruff passes, and npm reports zero known vulnerabilities.

### Safety and truthfulness corrections

- Credentials are read only from environment variables or ignored `fraudlens/.env`; source fails closed without them, and the secret scan passes.
- Runtime investigation access is through the official MCP SDK over stdio with named tools; arbitrary GSQL and shell access are not exposed.
- Investigations use `opened_at` as the evidence cutoff, preserve observed customer reports separately from simulated responses, exclude wholly unknown device profiles, and require structured corroboration before treating connected activity as fraud.
- The model ranks likelihood; deterministic policy controls actions and approval routes. SAR drafts use structured facts only.
- Stale claims and broken build assets were removed from the active documentation and production bundle. Exploratory analysis scripts and disposable local caches are kept outside the release repository in `Unnecssarythings/`; raw sponsor data and local dependencies remain ignored rather than being silently deleted.

### Remaining manual release action

The previously exposed cloud/static TigerGraph credential still authenticates and **must be rotated manually in the TigerGraph/Savanna console** before public distribution. The old database alias was revoked, but that does not rotate a cloud-console credential. The user should also record the final video and social links after reviewing the updated runbook. No remote push is performed automatically.
