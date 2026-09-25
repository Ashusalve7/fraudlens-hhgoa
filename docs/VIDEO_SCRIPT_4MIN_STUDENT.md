# FraudLens — 4-minute student demo script

**Style:** casual, slightly conversational, light Hinglish, like a student explaining a project to a friend. Do not sound like a sales presentation. Keep the screen and voice roughly in sync.

**Total:** 4:00
**Routes:** `/`, `/cases/HHG-014`, `/cases/HHG-002`, `/analytics`
**Important:** Keep `.env`, terminal secrets, cloud-admin pages, and the raw CSV files off screen.

---

## 0:00–0:20 — Quick introduction

**On screen:** Open `/`. Show the case queue and the graph summary.

**Say:**

> Hi, I’m presenting FraudLens, my Hacker House Goa TigerGraph project. The main idea is simple: a risk score is a reason to investigate, not a verdict. I built an investigator that checks connected evidence, follows fixed bank policy, and shows what it knows and what it still doesn’t.

---

## 0:20–0:45 — What is inside the project?

**On screen:** Show the queue, then briefly show the project structure or architecture slide.

**Say:**

> The dataset has 590,742 transactions and 5,565 historical cases. FraudLens derives card IDs, loads them into TigerGraph, and uses the official MCP SDK over stdio. The agent gets 11 named tools backed by 14 GSQL queries, not arbitrary GSQL. Every investigation stops at `opened_at`, so future transactions cannot leak in.

---

## 0:45–1:30 — Main demo: HHG-014

**Route:** `/cases/HHG-014`

**On screen:**

1. Show the trigger and the source risk score: `0.05`.
2. Show transaction `3478561`, amount `$74.96`, and the cutoff time.
3. Open the graph view and show the truncation message.
4. Show the bounded algorithm result: **255 nodes and 338 observed edges**.
5. Show the device-neighborhood evidence: **19 card IDs and 4 prior confirmed-fraud cases**.
6. Point to the final actions: `CREATE_CASE`, `ESCALATE_TO_ANALYST`, and `FILE_REPORT` on **L2** approval.

**Say:**

> This is HHG-014. The source risk score is only 0.05, so a score-only system would probably miss it. The graph shows the transaction, unusual device, 19 connected cards, and four earlier confirmed-fraud cases before this case opened. The bounded result is 255 nodes and 338 observed edges; that is not the whole TigerGraph. The evidence supports an undocumented coordinated-abuse pattern, so policy recommends `CREATE_CASE`, `ESCALATE_TO_ANALYST`, and `FILE_REPORT` on L2. `FILE_REPORT` is a recommendation, not an executed filing.

---

## 1:30–2:00 — Evidence request and action change

**Route:** `/cases/HHG-002`

**On screen:**

1. Show the initial actions: verify, step-up authentication, and create case.
2. Point to the **Simulated Evidence** label.
3. Show the assumed customer confirmation.
4. Show the final `CLOSE_NO_FRAUD` action and the changed recommendation.

**Say:**

> Now HHG-002 shows what happens when evidence is missing. The system first recommends verification and step-up authentication. There is no real customer response in the benchmark, so FraudLens labels the assumed confirmation as simulated. After that recorded assumption, the recommendation changes to close-no-fraud. So the loop is: gather evidence, ask for the least-invasive useful evidence, record the assumption, and recalculate. It is not hard-coding an answer.

---

## 2:00–2:30 — Policy, approvals, and memory

**On screen:** Show the policy-grounded actions, approval route, similar-case section, and graph-case reference.

**Say:**

> The model only gives fraud likelihood. It cannot block a card or file a report. Deterministic R1–R10 policy controls actions, and L1/L2 routes stay human-approved. Policy chunks are retrieved for context, but never authorize an action. Similar cases are retrieved with outcomes and an explanation of their influence. I did not want random case IDs to pretend to be memory, so read-back validation checks the stored answer and evidence edges.

---

## 2:30–3:00 — SAR and uncertainty

**On screen:** Go back to HHG-014. Show the SAR Draft, subjects, connected cards, and the “draft / filing unconfirmed” label.

**Say:**

> SAR text is generated only from structured facts. In HHG-014, the draft rests on corroborated connected-card fraud, not the $74.96 amount. It is clearly marked as a draft, not a filed report. Generic device reuse is only a monitoring lead, and unknown devices are excluded. A stronger claim needs compact cross-customer evidence, repeated anomalies, and a prior confirmed case before the cutoff. For me, that honesty is more useful than fake confidence.

---

## 3:00–3:30 — Honest evaluation and engineering

**Route:** `/analytics`

**On screen:** Show analytics, then the test/validation output in a split screen or prepared terminal clip.

**Say:**

> The final pack has 20 cases: 11 fraud, 5 legitimate, 4 uncertain, and 2 SAR drafts. The live graph check is 634,292 vertices and 2,506,735 edges. The time-held-out AUC is 0.9822, Brier is 0.0332, and the customer-disjoint diagnostic AUC is 0.9703. Pattern agreement is 0.2349, explicitly a noisy-label diagnostic. All 20 pass both validators; there are 121 passing tests, 71.89% coverage, zero npm vulnerabilities, and Lighthouse scores of 100.

---

## 3:30–4:00 — Innovation and close

**On screen:** Show the HHG-014 graph again, then the queue. End on the dashboard home screen.

**Say:**

> The innovation is combining a calibrated score, bounded graph evidence, policy-controlled actions, honest uncertainty, graph memory, and a read-only analyst workspace. I kept GDS as a global quality signal, not case authorization. FraudLens does not replace the investigator; it helps them see the evidence and choose the next safe action. Thanks for watching.

---

## Presenter checklist — do not skip these points

- Risk score is a trigger, not a verdict.
- 590,742 transactions, 5,565 historical cases, 20 benchmark cases.
- MCP is an allow-listed boundary, not arbitrary GSQL.
- `opened_at` is the evidence cutoff.
- HHG-014: source score `0.05`, 255 nodes, 338 edges, 19 cards, 4 prior confirmed-fraud cases.
- Generic device reuse is not automatically a fraud ring.
- Model likelihood and deterministic policy are separate.
- Simulated evidence is visibly labeled.
- L1/L2 actions require human approval.
- SAR is a draft and filing is not confirmed.
- Similar-case memory has read-back validation.
- GDS output is not used as a case authorization input.
- Final metrics and 20/20 validator results are truthful.
- End with the human-in-the-loop message.

## Recording tips

- Speak slightly faster during the numbers, then pause for the screen to load.
- Use a simple line: “This is a recommendation, not an execution.”
- If the graph is sleeping, show the prepared HHG-014 graph clip and say that the live graph is reconnecting. Do not make up counts.
- Do not show the raw sponsor data or any credential.
- Record one clean take and one backup take. Keep the same wording so editing is easy.
