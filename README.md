# FraudLens

FraudLens is an uncertainty-aware fraud-investigation workspace built for the Hacker House Goa 2026 TigerGraph challenge. It investigates a suspicious transaction as a bounded graph case, ranks fraud likelihood with a calibrated model, applies deterministic bank policy R1–R10, records simulated evidence requests honestly, and persists an auditable `AgentCase` through an allow-listed MCP boundary.

## Repository map

- [`fraudlens/`](fraudlens/) — Python engine, MCP server/client, graph pipeline, dashboard, cases, and technical documentation.
- [`fraudlens/README.md`](fraudlens/README.md) — setup, architecture, and final validated results.
- [`docs/VIDEO_PRODUCTION.md`](docs/VIDEO_PRODUCTION.md) — five-minute recording runbook.
- [`docs/RELEASE_CHECKLIST.md`](docs/RELEASE_CHECKLIST.md) — mandatory release gate.
- [`bunny_improvement.md`](bunny_improvement.md) — original project audit and remediation record.

## Safe local checks

```powershell
uv sync --project fraudlens --all-groups --frozen
uv run --project fraudlens python scripts/secret_scan.py
uv run --project fraudlens python scripts/check_dataset.py
uv run --project fraudlens pytest tests --cov=fraudlens --cov-fail-under=70
npm ci --prefix fraudlens/dashboard
npm run build --prefix fraudlens/dashboard
npm audit --prefix fraudlens/dashboard --audit-level=high
```

## Runtime boundaries

- The investigation runner uses the official MCP SDK over stdio; it does not expose arbitrary GSQL.
- Graph evidence is cutoff-bounded, provenance-bearing, and graph-ID validated.
- The model ranks likelihood. It never authorizes a block, decline, or report.
- Unknown device profiles are not treated as a shared device.
- Observed customer reports and simulated responses are distinct.
- `npm`/Python source, model, graph data, and final answers are reproducible from locked dependencies and documented commands.

## Security

Never commit `fraudlens/.env`, a TigerGraph secret, a cloud credential, or raw sponsor data. See [`SECURITY.md`](SECURITY.md) and [`docs/SECURITY_ROTATION.md`](docs/SECURITY_ROTATION.md). The currently exposed cloud/static credential must be rotated manually in the TigerGraph console before public release.
