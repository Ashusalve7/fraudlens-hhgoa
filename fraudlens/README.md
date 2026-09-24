# FraudLens — Agentic Fraud Investigation on TigerGraph

**HHGOA × TigerGraph sponsor challenge.** FraudLens investigates a suspicious transaction as a bounded, connected case rather than treating a risk score as a verdict. It gathers graph evidence through an allow-listed MCP boundary, retrieves policy and closed-case context, ranks fraud likelihood with a calibrated model, applies deterministic bank policy R1–R10, records simulated evidence requests as simulations, and persists a complete `AgentCase` answer with its evidence edges.

The current case files are release artifacts only after the commands in the [release checklist](../docs/RELEASE_CHECKLIST.md) pass. Do not submit an older `cases/` directory or an old model report.

## What is implemented

- **Cutoff-correct investigations:** every card, customer, device, region, and policy retrieval ends at the case's `opened_at` timestamp. Client-side filtering protects against a graph response that accidentally includes future rows.
- **MCP-mediated graph access:** the official Python MCP SDK runs over stdio. The service publishes 11 named, schema-validated tools and no arbitrary-GSQL, shell, or filesystem tool.
- **Graph-native evidence:** 14 installed GSQL v3 queries cover transaction context, bounded windows, device neighborhoods, rings, shared neighbors, case memory, policy chunks, and AgentCase read/write.
- **Deterministic decision policy:** the model supplies `fraud_probability`; `agent/decision.py` controls actions, approval routes, evidence sufficiency, stop reasons, and SAR gates.
- **Honest memory:** retrieved `ClosedCase` outcomes contribute an independent-evidence item when confirmed fraud is present. New `AgentCase` writes are retrievable with their complete answers and exact `AG_*` edges; retrieval is validated through MCP.
- **Grounded GraphRAG:** `PolicyChunk` text is retrieved from TigerGraph, hash-verified against the local provenance artifact, and cited in evidence. Retrieval never authorizes an action.
- **Safe graph algorithms:** bounded connected components, shortest paths, shared neighbors, and degree centrality run over observed relation sets with explicit scope/truncation metadata. The verified optional TigerGraph GDS degree-centrality artifact is documented in [`docs/GDS.md`](../docs/GDS.md) and [`docs/LIVE_GRAPH_REPORT.md`](../docs/LIVE_GRAPH_REPORT.md).
- **Atomic, semantic outputs:** staged case files are schema- and graph-readback-validated before they replace the release files.

## Reproduce from the repository root

### 1. Install locked dependencies

```powershell
uv sync --project fraudlens --all-groups --frozen
npm ci --prefix fraudlens/dashboard
```

### 2. Configure credentials outside source control

```powershell
Copy-Item fraudlens/.env.example fraudlens/.env
```

Set `TG_HOST`, `TG_SECRET`, and `TG_GRAPHNAME` in the ignored file or process environment. The code fails closed when credentials are missing. See [`docs/SECURITY_ROTATION.md`](../docs/SECURITY_ROTATION.md) for the required cloud-console rotation of any previously exposed credential.

### 3. Validate and build graph artifacts

```powershell
uv run --project fraudlens python scripts/secret_scan.py
uv run --project fraudlens python scripts/check_dataset.py
uv run --project fraudlens python fraudlens/pipeline/derive_card_ids_final.py
uv run --project fraudlens python fraudlens/pipeline/build_load_files.py
uv run --project fraudlens python fraudlens/pipeline/load_graph.py --no-remote
```

The builder fails before writing an incomplete load plan. It excludes wholly unknown device profiles, creates `CASE_DEVICE` and `PolicyChunk` frames, and writes string graph IDs.

### 4. Apply the live schema and queries

Review the graph name and credential scope first. Then run:

```powershell
uv run --project fraudlens python fraudlens/pipeline/create_schema.py --skip-jobs
uv run --project fraudlens python fraudlens/pipeline/install_queries.py
```

`--skip-jobs` avoids silently changing optional vector attributes. The load contract and graph-health report still verify the required static graph. Use the operations guide before any live upsert.

### 5. Retrain and evaluate the exact production feature path

```powershell
uv run --project fraudlens python fraudlens/eval/build_features.py
uv run --project fraudlens python fraudlens/eval/train.py
```

Read final metrics from `fraudlens/eval/out/model.json` and `eval_report.txt`. Pattern-label agreement is explicitly a diagnostic against noisy historical labels; it is not the binary fraud model's accuracy and is never used as a policy threshold.

### 6. Generate and validate all 20 cases

```powershell
uv run --project fraudlens python fraudlens/runner.py
uv run --project fraudlens python fraudlens/validator.py
uv run --project fraudlens python fraudlens/validator.py --check-graph
```

The runner stages every answer, validates the local schema/semantics, reads every new `AgentCase` back through MCP, and commits the case files only after those checks pass. A failed graph write is represented as `written_to_graph: false`; it is never represented as persisted.

### 7. Build and serve the analyst workspace

```powershell
npm run build --prefix fraudlens/dashboard
uv run --project fraudlens uvicorn dashboard.app:app --app-dir fraudlens --host 127.0.0.1 --port 8000
```

Open `/`, `/cases/HHG-014`, and `/analytics`. The dashboard is read-only decision support. It displays bounded graph traversal, evidence/uncertainty separation, approval routes, recorded simulations, similar-case provenance, and a labeled SAR draft.

## Architecture

```text
case_pack.csv
      │
      ▼
MCP stdio client ── 11 allow-listed tools ──► TigerGraph MCP server
      │                                           │
      │                                           ├─ 14 installed GSQL v3 queries
      │                                           ├─ PolicyChunk + ClosedCase provenance
      │                                           └─ AgentCase read/write with exact edges
      ▼
cutoff-aware evidence + episode builder
      │
      ├─ calibrated fraud likelihood (model ranks; never authorizes)
      ├─ evidence-backed pattern registry
      ├─ deterministic R1–R10 policy and approval routes
      ├─ closed-case memory / evidence requests / SAR facts
      ▼
strict answer JSON + graph read-back validation + dashboard
```

The graph contract has 9 vertex types and 15 directed edge types. Static source expectations are derived from the validated load frames; live observed counts are recorded in `fraudlens/pipeline/out/graph_health.json` and must match before release.

## Card identity derivation

`transactions.csv` has no `card_id`. FraudLens derives the deterministic identity:

```text
(card1, card4, card6) → sorted rank K within customer_id
card_id = customer_id + "-K" + K
```

The derivation validates every flagged transaction and every transaction listed in the 5,565 historical cases. Missing components are represented as `_NA_`; unknown source IDs are never silently dropped.

## Repository layout

```text
fraudlens/
  agent/       cutoff/evidence/feature/decision/SAR logic
  eval/        inference-identical feature build and calibration
  graph_tools/ bounded graph algorithms and backends
  gsql/        schema and installed evidence queries
  mcp/         official SDK server, client, service, and adapter
  pipeline/    card map, load frames, loader, schema/query utilities
  dashboard/   FastAPI API and React analyst workspace
  cases/       generated benchmark answer artifacts
  validator.py strict schema, semantic, and graph-readback checks
docs/          operations, security, release, demo, video, and GDS notes
scripts/       dataset, secret, manifest, and safe packaging checks
```

## Security and release truthfulness

- Never print or commit `TG_SECRET`, cloud credentials, `.env`, raw sponsor data, or local dependencies.
- Run `scripts/secret_scan.py` before packaging and after every documentation change.
- Do not publish old AUC, pattern-agreement, verdict-balance, graph-health, or SAR numbers. Copy final values from regenerated artifacts.
- Keep the manual cloud credential rotation open until it is completed in the TigerGraph console.

## License and notices

MIT License: [`LICENSE`](../LICENSE). Dependency and data attribution: [`THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md).
