# Security Policy

## Reporting a vulnerability

Do not open a public issue containing credentials, customer data, exploit payloads, or access to the live TigerGraph workspace. Report security problems privately to the team organizers.

## Credential handling

- TigerGraph credentials are read only from `TG_HOST`, `TG_SECRET`, and `TG_GRAPHNAME` environment variables or a local, ignored `.env` file.
- Never place a real workspace URL, username, password, secret, API token, MCP token, or cloud credential in source, notebooks, screenshots, logs, videos, or committed `.env` files.
- Rotate a TigerGraph secret immediately after it has appeared in any source-controlled or shared file.
- The dashboard binds to loopback by default. Configure `FRAUDLENS_API_TOKEN` and terminate TLS before exposing it beyond a trusted local machine.
- The MCP boundary exposes only named evidence and case-memory tools. It does not expose arbitrary GSQL, shell, filesystem, or secret-reading operations. Treat `case_write` as a controlled application write and review its audit ledger.

## Data handling

The sponsor dataset is anonymized, but case and graph identifiers must still be treated as sensitive research data. Do not redistribute the raw CSV files without following the sponsor's terms.
