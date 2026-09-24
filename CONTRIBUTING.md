# Contributing to FraudLens

## Setup

```bash
uv sync --project fraudlens --all-groups
npm ci --prefix fraudlens/dashboard
cp fraudlens/.env.example fraudlens/.env
```

Populate `fraudlens/.env` locally with a dedicated TigerGraph runtime secret. Never commit `.env`, a workspace secret, or a screenshot containing one.

## Required checks

```bash
uv run --project fraudlens python scripts/secret_scan.py
uv run --project fraudlens python scripts/check_dataset.py
uv run --project fraudlens ruff check fraudlens scripts
uv run --project fraudlens pytest fraudlens/tests
npm run build --prefix fraudlens/dashboard
npm audit --prefix fraudlens/dashboard --audit-level=high
```

## Change rules

- Graph schema/query changes require contract tests and a regenerated graph-health report.
- Pattern, probability, policy, episode, or SAR changes require focused unit tests plus a full 20-case semantic validation.
- Customer/analyst responses are simulations and must remain explicitly labeled as assumptions.
- High-impact actions are recommendations only; approval routes must remain machine-enforced.
- UI changes must preserve keyboard access, mobile layout, honest empty/error states, and the distinction between fraud likelihood, evidence confidence, and decision readiness.
- Update metrics in documentation from generated artifacts only. Do not hand-maintain unsupported performance claims.

## Pull requests

Use small reviewable changes, include verification evidence, and never include the raw sponsor dataset, local environments, dependency directories, or credentials.
