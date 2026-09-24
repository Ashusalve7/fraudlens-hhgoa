# Operations guide

## Runtime prerequisites

- Python 3.12
- [uv](https://docs.astral.sh/uv/)
- Node.js 22+
- npm 10+
- A sponsor-provided `HHGOA_IEEE/` directory
- A dedicated TigerGraph runtime credential

## One-time local setup

```bash
uv sync --project fraudlens --all-groups
npm ci --prefix fraudlens/dashboard
cp fraudlens/.env.example fraudlens/.env
```

Populate `fraudlens/.env`:

```dotenv
TG_HOST=https://<workspace-host>
TG_SECRET=<dedicated-runtime-secret>
TG_GRAPHNAME=FraudGraph
```

Never use a cloud-console administrator credential for the application. Prefer a dedicated TigerGraph user/secret with only the permissions needed for installed investigation queries and approved graph writes.

## Validate inputs

```bash
uv run --project fraudlens python scripts/check_dataset.py
uv run --project fraudlens python scripts/secret_scan.py
```

The dataset check must report:

- 590,742 transactions
- 144,432 identity records
- 5,565 closed cases
- 20 benchmark cases
- all benchmark transaction IDs present

## Build and verify the graph

Run the project pipeline in order and stop on any failed stage:

```bash
uv run --project fraudlens python fraudlens/pipeline/derive_card_ids_final.py
uv run --project fraudlens python fraudlens/pipeline/build_load_files.py
uv run --project fraudlens python fraudlens/pipeline/create_schema.py --skip-jobs
uv run --project fraudlens python fraudlens/pipeline/load_graph.py
uv run --project fraudlens python fraudlens/pipeline/install_queries.py
```

The graph-health report must include every declared vertex and edge, expected and actual counts, graph name, schema version, and load timestamp. A count is not healthy merely because the API responds. For a targeted resumable refresh, use `load_graph.py --only v_DeviceProfile,v_PolicyChunk,e_NEXT_TXN,e_CASE_TXN,e_CASE_CARD,e_CASE_CONN_CARD,e_CASE_DEVICE`; never treat a partial load as a release health pass.

## Train and evaluate

```bash
uv run --project fraudlens python fraudlens/eval/build_features.py
uv run --project fraudlens python fraudlens/eval/train.py
```

The generated model must be consumable without manual edits. Documentation metrics must be generated from the same production pattern registry used by the runner.

## Investigate and validate

```bash
uv run --project fraudlens python fraudlens/runner.py
uv run --project fraudlens python fraudlens/validator.py
uv run --project fraudlens python fraudlens/validator.py --check-graph
```

Validation must fail on temporal leakage, incorrect SAR facts, policy/action mismatches, graph/output divergence, fabricated IDs, or cumulative tool counts.

## Dashboard

```bash
npm run build --prefix fraudlens/dashboard
uv run --project fraudlens uvicorn dashboard.app:app --app-dir fraudlens --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`. The FastAPI service serves the production `dashboard/dist/` build and SPA routes.

## Release verification

```bash
uv run --project fraudlens ruff check fraudlens scripts
uv run --project fraudlens pytest tests --cov=fraudlens --cov-fail-under=70
npm run build --prefix fraudlens/dashboard
npm audit --prefix fraudlens/dashboard --audit-level=high
```

Record the final commit, model hash, schema/query hash, graph-health report, 20 answer hashes, and demo URL in the release checklist.
