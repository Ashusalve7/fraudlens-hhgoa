# FraudLens: teaching an investigator to distinguish evidence from a score

*Technical blog — HHGOA × TigerGraph sponsor challenge*

## The trap

The sponsor dataset contains 590,742 transactions, a `risk_score` on every row, and a warning that a score is an investigation trigger rather than a verdict. An agent that blocks every high-score alert confuses ranking with authorization. An agent that trusts a historical pattern label can also overstate what a graph neighborhood proves.

FraudLens is designed around that distinction.

## The investigation loop

For each case, the runner:

1. retrieves the flagged transaction and its observed card, customer, device, and region context;
2. bounds card, customer, device, and region evidence at `opened_at`;
3. retrieves policy chunks and ranked closed-case memory through the official MCP SDK;
4. builds a pattern-specific, deduplicated episode from observed anomalies;
5. ranks fraud likelihood with the exact serialized calibrator used offline;
6. applies deterministic R1–R10 policy and approval routes;
7. records an unavailable customer response as an explicit simulation, when policy requires one;
8. renders a SAR draft only from structured facts; and
9. writes the complete answer and evidence edges as an `AgentCase`, then reads them back for validation.

The model never authorizes a block, decline, or report. The policy engine never treats a retrieval score or a risk score as permission.

## The graph is an evidence boundary

TigerGraph stores transactions, customers, derived cards, observed device profiles, regions, email domains, historical closed cases, policy chunks, and investigation cases. The runtime accesses that graph through named MCP tools backed by installed, allow-listed GSQL queries.

The important boundary is temporal. A transaction after `opened_at` cannot enter the initial decision merely because a broad graph query returned it. Client-side filtering repeats the cutoff as a defensive measure, and the validator checks affected IDs, exposure, evidence windows, and SAR claims.

A shared device is not automatically a fraud ring. Generic profile reuse is recorded as a monitoring lead. Connected-fraud corroboration requires a compact cross-customer neighborhood, repeated anomaly evidence, and a prior confirmed case observed before the cutoff. This prevents thousands of ordinary users of a common browser profile from becoming one false component.

## What the model does—and does not—claim

The binary calibrator is trained on the labeled closed-case history and evaluated on a time-held-out split. Its final AUC, Brier score, customer-disjoint diagnostic, and calibration metadata are generated in `fraudlens/eval/out/model.json`.

Historical `pattern` labels are treated separately. Exact agreement with those labels is a diagnostic, not a second model-accuracy claim: the legacy labels contain broad assignments that do not necessarily meet the production evidence rule. The final release publishes the number with that caveat rather than hiding it.

Policy retrieval is grounded but not authoritative. `PolicyChunk` text is retrieved from TigerGraph and its provenance is recorded. The deterministic policy implementation remains the only action authority.

## Reproducibility as a feature

A demo is only useful if another team can inspect it. FraudLens therefore ships:

- deterministic card and device identity rules;
- locked Python and frontend dependencies;
- a staged case writer;
- strict JSON Schema and semantic validation;
- graph read-back validation of complete answers and evidence edges;
- graph-health counts and a safe load contract;
- a read-only React analyst workspace with honest loading, error, truncation, and simulation states; and
- a release manifest and safe submission packager.

## What the final video should claim

Use only regenerated values from the release artifacts. The video should demonstrate:

- a low-score graph alert whose evidence changes the recommendation;
- an explicit simulated evidence request and actual action diff;
- an approval route that a human controls;
- a graph case-memory relationship and grounded policy citation; and
- a SAR draft whose claims can be traced to structured evidence.

If optional TigerGraph GDS is not available in the workspace, say that the demo uses the deterministic bounded algorithm layer rather than claiming a global GDS run.

## Stack

TigerGraph Savanna · official Python MCP SDK · GSQL v3 · Python/pandas/scikit-learn · React/Vite · deterministic policy and SAR validation.
