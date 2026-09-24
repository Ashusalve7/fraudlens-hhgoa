# Live graph verification report

Generated from the final clean load-artifact contract and verify-only health pass against `FraudGraph`.

## Health

- Status: **healthy**
- Source load contract: `fraudlens.load-plan/v2`
- Source files inspected: **19/19**
- Static vertex rows: **634,292 expected / 634,292 observed**
- Static edge rows: **2,506,735 expected / 2,506,735 observed**
- `NEXT_TXN`: **576,424** rows; same-card, chronological, acyclic, one-in/one-out checks all pass.
- Unknown device profiles: **excluded**; observed `FROM_DEVICE` edges = **140,784**.
- `CASE_DEVICE`: **5,137** edges, zero orphan endpoints.
- `PolicyChunk`: **17** vertices.
- Managed `AgentCase` vertices: **20** after final regeneration; all 20 complete answers and exact `AG_TXN`/`AG_CARD`/`AG_DEVICE`/`AG_SIMILAR` relationships pass MCP read-back validation.

Exact live counts are in `fraudlens/pipeline/out/graph_health.json` and are not copied from an old README. The regenerated case pack passes both the local semantic validator and the MCP graph read-back validator for **20/20** answers.

## Query/MCP verification

- All **14** GSQL evidence queries compiled and installed successfully.
- The official Python MCP SDK starts over stdio and returns typed results.
- Production smoke returned transaction context and a bounded 36-node graph ring for a known transaction.
- Policy retrieval returned remote `TigerGraph:PolicyChunk` results with provenance after the static load.

## Model/evaluation snapshot

The final serialized calibrator reports:

- time-held-out fraud-likelihood AUC: **0.9822**;
- Platt Brier: **0.0332**;
- post-prior-shift Brier: **0.0558**;
- customer-disjoint diagnostic AUC: **0.9703**;
- exact production pattern agreement against noisy legacy labels: **0.2349**.

The last number is deliberately labeled a diagnostic. It is not the binary fraud model's accuracy and is not used to authorize an action. These values are also serialized in `fraudlens/eval/out/model.json`.

## GDS

The Enterprise `GDBMS_ALGO` package is available. The reproducible degree-centrality run is recorded in `fraudlens/pipeline/out/gds_degree_centrality.json` using:

- vertex type: `DeviceProfile`
- edge type: `FROM_DEVICE`
- reverse edge type: `rev_FROM_DEVICE`
- normalized directed degree
- top 10 output

This is a **global graph-quality signal**, not a case-cutoff result and not an action authorization input. The investigation path uses bounded observed relations plus deterministic policy.

## Manual security action

The synthetic unknown device and its 3,648 incoming `FROM_DEVICE` edges were removed. The previously exposed cloud/static credential still requires manual rotation in the TigerGraph console; see `docs/SECURITY_ROTATION.md`.
