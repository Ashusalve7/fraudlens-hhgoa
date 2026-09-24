# FraudLens release checklist

A release is blocked if any required item is unchecked.

**Current automated status (25 September 2026):** the regenerated 20-case pack passes local semantic and MCP graph read-back validation; graph health is healthy; Python tests, Ruff, frontend build, npm audit, and browser/Lighthouse checks pass. The remaining external actions are manual cloud credential rotation, final video/social links, and the final Git push.

## Source and credentials

- [ ] `scripts/secret_scan.py` passes.
- [ ] No live TigerGraph credential exists in source, notebooks, logs, screenshots, or archives.
- [ ] The old exposed cloud/static credential is rejected from a new process.
- [ ] `fraudlens/.env` is ignored and absent from the release archive.
- [ ] `TG_HOST`, `TG_SECRET`, and `TG_GRAPHNAME` fail closed when missing.

## Reproducibility

- [ ] `uv sync --project fraudlens --all-groups --frozen` succeeds.
- [ ] `npm ci --prefix fraudlens/dashboard` succeeds.
- [ ] Dataset validation passes with the expected four row counts.
- [ ] Card derivation passes every known transaction without silently dropping bad references.
- [ ] Model training writes a model that the runtime can consume without manual edits.
- [ ] `release_manifest.json` records final code, model, schema, query, graph-health, answer, and data hashes.

## Graph

- [ ] Every expected vertex count matches.
- [ ] Every expected edge count matches.
- [ ] `NEXT_TXN`, `CASE_TXN`, `CASE_CARD`, `CASE_CONN_CARD`, and `CASE_DEVICE` are nonzero as expected.
- [ ] Unknown/empty devices do not form a giant false shared-device component.
- [ ] Device card/customer results obey the requested time window.
- [ ] Every installed query compiles and passes positive, empty, boundary, and missing-ID contract tests.
- [ ] `validator.py --check-graph` reads all 20 AgentCases and matches stored answers plus AG_TXN/AG_CARD/AG_DEVICE/AG_SIMILAR edges.
- [ ] MCP tool traces are recorded in case audit data.
- [ ] At least one graph algorithm result is visible and materially affects a recommendation.
- [ ] Optional GDS package availability and the exact `gds_degree_centrality.json` provenance are recorded; global GDS output is not misrepresented as cutoff evidence.
- [ ] GraphRAG returns a policy or case-note citation with provenance.
- [ ] Similar closed-case memory is visible and its independent-evidence contribution is explicit; newly generated AgentCases are retrievable with complete answers and exact outgoing edges.

## Investigation engine

- [ ] Evidence cutoff is `opened_at` unless a documented delayed-investigation contract says otherwise.
- [ ] Offline and graph-derived features match for every model feature.
- [ ] The exact production pattern registry is evaluated; no separate demo evaluator exists.
- [ ] Card testing, new-device CNP, CNP, OOR/trip, ATO, recurring R7, and undocumented paths are tested.
- [ ] Probability transformation is numerically stable and evaluated after prior/temperature adjustment.
- [ ] Model probability and policy threshold overrides are not conflated.
- [ ] Per-case tool calls are independent of full-pack/subset run order.
- [ ] Full-pack and single-case normalized outputs are identical.

## Answer semantics

- [ ] Exactly 20 final files pass the strict JSON Schema with no extra answer fields.
- [ ] Every fraud episode includes the flagged transaction.
- [ ] Affected transaction IDs are unique, real, on the expected card, and no later than the cutoff.
- [ ] Exposure is the sum of absolute affected amounts.
- [ ] `first_suspicious_txn_id` belongs to the episode and is chronologically defensible.
- [ ] Evidence claims match actual query results, parameters, windows, and IDs.
- [ ] Similar cases state outcome and actual influence, or are not presented as decision evidence.
- [ ] Initial/final action differences match `what_changed` exactly.
- [ ] Customer/analyst assumptions are labeled as simulations unless present in the original trigger.
- [ ] Every action has a policy-valid reason and correct approval route.
- [ ] `BLOCK_CARD` routes use the $2,500 exposure boundary.
- [ ] SAR filing agrees with `FILE_REPORT` and requires actual policy evidence.
- [ ] SAR totals, dates, first transaction, subjects, links, and narrative claims all recompute from evidence.
- [ ] No legitimate case has affected transactions, exposure, or a SAR draft.
- [ ] Graph case vertices and outgoing edges exactly match each final answer.

## User interface

- [ ] Production `dashboard/dist/` is rebuilt from current source.
- [ ] FastAPI serves `/`, `/cases/HHG-014`, `/analytics`, and hard refreshes.
- [ ] Path traversal and malformed identifier tests pass.
- [ ] Mobile and tablet layouts have no horizontal overflow.
- [ ] Keyboard-only navigation, focus visibility, skip link, landmarks, and reduced motion work.
- [ ] Queue filters/search work and expose real status/age/trigger context.
- [ ] Loading, error, retry, empty, and workspace-asleep states are truthful.
- [ ] Graph shows actual time window, truncation, and all relevant edge endpoints.
- [ ] “Fraud probability,” “evidence confidence,” and “decision readiness” are distinct.
- [ ] Evidence requests, timeline, approval state, and SAR draft/export are visible.
- [ ] Dashboard analytics and documentation use regenerated case counts.

## Quality

- [ ] `ruff check fraudlens scripts` passes.
- [ ] `pytest tests --cov=fraudlens` passes with the configured 70% coverage floor.
- [ ] Frontend production build passes without warnings that affect demo reliability.
- [ ] `npm audit --audit-level=high` passes.
- [ ] No authored test is skipped to make the suite green.

## Submission content

- [ ] README setup and architecture match the final code.
- [ ] Technical blog contains only regenerated, reproducible metrics.
- [ ] Demo script totals no more than five minutes.
- [ ] Final demo is recorded twice from a clean start.
- [ ] Social post links to the working blog and demo and tags `@TigerGraphDB`.
- [ ] License, attribution, team names, screenshots, and contact/link details are present.
- [ ] Raw sponsor data and local dependencies are excluded from the public repository/archive.
- [ ] Final commit is pushed to the submission repository.
