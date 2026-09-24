# FraudLens: teaching an agent to investigate fraud instead of guessing

*Technical blog — HHGOA × TigerGraph sponsor challenge*

## The trap we designed around

The sponsor dataset hands you 590,742 transactions with a `risk_score` on every row and a
simple instruction: a score is a reason to look, never a verdict. The benchmark's own README
warns that above 0.7 most flagged transactions are legitimate, that some fraud scores near
zero, and that an agent which blocks everything scores badly. Half the exam cases are
legitimate.

That single sentence kills the obvious demo. An agent that treats the score as truth fails
calibration *and* next-best-action scoring at once. The winning behavior is boring and hard:
be honest about uncertainty, follow the bank's written policy, and only act when the evidence
justifies it.

## What we built

**FraudLens** is a state-machine agent over a TigerGraph graph. Per case it:

1. Pulls the flagged transaction's context (customer, card, device profile, billing region,
   emails, match flags) through an installed GSQL query.
2. Expands evidence: 60-day card window, ±7-day device neighborhood, region activity.
3. Scores the five documented fraud patterns with deterministic rules and retrieves similar
   closed cases from the graph as case memory.
4. Produces a calibrated fraud probability — a 16-feature logistic model trained on the
   bank's own 5,565 closed cases (July–October), Platt-calibrated, and shifted to the exam
   prior (the README states half the cases are legitimate; the shift moves the model's
   answer from "likely given the labeled history" to "likely given this alert mix").
5. Recommends next-best actions through a deterministic implementation of the bank's
   R1–R10 policy, each action citing its rule, each routed auto/L1/L2 exactly as the
   approval table requires.
6. Requests additional evidence when the policy calls for it (customer validation,
   step-up auth), simulates the response, states the assumption, and re-decides.
7. Writes the closed case back into the graph — vertices, evidence edges, links to the
   prior cases that informed it — so the next investigation starts smarter.

The LLM is not in the decision path. Every fact in an answer file is traceable to a GSQL
query or a rule; the agent's judgment lives in the *orchestration* — which evidence to pull,
when to stop, which simulated answer to assume — not in inventing facts.

## Three findings we didn't expect

**1. The card_id was hiding in plain sight.** `transactions.csv` has no card column, but
every case references cards like `C12382-K1`. Testing the obvious hypotheses (rank by first
appearance, by card number) got us exactly 50% — suspiciously equal to the share of
single-card customers. The break came from customers whose cases referenced *both* K1 and K2
on the same `card1`: the K1 record had empty card fields. The true identity is the tuple
`(card1, card4, card6)` — card number, network, type — and K is its rank among the
customer's sorted identities. Validated on all 14,955 case-listed transactions: 100%.

**2. The labeled history is a cheat code — if you respect time.** The 5,565 closed cases
(July–October) come with outcomes, patterns, filing decisions and analyst notes. We built
inference-identical features, trained on the first 75% by date, and validated on the rest:
AUC 0.975. The pattern detector — precedence rules over burst velocity, new-device share,
proxy rate, and a *region-prior-share* feature (how common the episode's region is in the
card's own history) — reaches 77.4% agreement with the bank's labels. The SAR gate fell out
of the same table: of 397 filed reports, every single one had exposure above $1,000 or an
undocumented pattern. That's the policy's §3a gate, visible in data.

**3. The risk score is anti-correlated with fraud — among investigated cases.** In the
closed-case population the standardized coefficient on `risk_score` is *negative* (~−5.5).
Cleared cases are precisely the high-score false positives the bank already chased down;
confirmed fraud mostly arrived through customer reports with modest scores. The exam alert
mix comes from the same stream, so the model keeps the negative weight — and the exam-prior
shift plus temperature scaling keeps it honest about base rates. The result: our 20 verdicts
landed at 11 fraud / 9 legitimate, right on the benchmark's stated balance, with
probabilities spread across the whole range instead of pinning at 0 or 1.

## What TigerGraph actually does here

Not a checkbox. The device-profile neighborhood is the case-solving query for the
analyst-request exam case: one transaction, risk score 0.05, on a device profile marked New
behind an anonymous proxy — shared with 52 other cards inside a week. Finding that in SQL is
a self-join nightmare; in the graph it's a two-hop traversal and a count. Case memory is
likewise graph-native: closed investigations link to their transactions, cards and device
profiles, and `find_similar_cases` plus entity-overlap retrieval turn past outcomes into
present evidence.

All graph access flows through 10 installed GSQL queries (TigerGraph 4.2, SYNTAX v3 /
GQL path patterns) — the same narrow tool surface the TigerGraph MCP server exposes to
interactive agents.

## What we'd do next

- Vector retrieval over the closed-case notes (schema is already vector-enabled) to widen
  case memory beyond structured similarity.
- The innovation track: the same runner pointed at November–December alerts *outside* the
  case pack — night-watch mode.
- A human-in-the-loop dashboard where the approval matrix is clickable rather than
  simulated.

## Stack

TigerGraph Savanna 4.2.5 (Enterprise) · 10 GSQL queries · TigerGraph MCP · Python
(pandas/pyTigerGraph/scikit-learn) · zero fine-tuned models.
