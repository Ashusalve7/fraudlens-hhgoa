# Graph algorithm and GDS boundary

FraudLens uses two deliberately separated algorithm layers:

1. `fraudlens/graph_tools/algorithms.py` provides deterministic connected-component, breadth-first shortest-path, shared-neighbor, and degree-centrality calculations over the **bounded relation set returned by the installed graph queries**. The result carries `scope: returned_relation_set` and `truncated` so a two-hop investigation ring is never presented as a global community.
2. TigerGraph Graph Data Science (GDS) is optional. When the target workspace has the `GDBMS_ALGO` package, an operator may install packaged centrality/community algorithms and persist their result attributes. The application does not silently claim that a global GDS job ran when the package is unavailable.

## Evidence boundary

The production MCP service exposes named, validated operations rather than arbitrary GSQL. The current runtime algorithm path is the bounded graph ring plus the deterministic local algorithms. This keeps the agent reproducible on workspaces where GDS is not enabled and makes every algorithm edge traceable to an observed query result.

## Optional workspace inspection

From an authenticated environment, inspect package availability without changing data:

```powershell
uv run --project fraudlens python scripts/check_gds.py
```

If the package is present, use the TigerGraph GDS documentation for the workspace's version to run a bounded centrality or community job, then record its query/package/version and result artifact in the release notes. Do not substitute a global community result for a case cutoff in `AgentCase` evidence.

## Verified workspace run

The current workspace has the Enterprise `GDBMS_ALGO` package. The reproducible command is:

```powershell
uv run --project fraudlens python scripts/run_gds.py
```

It runs the documented directed normalized degree-centrality template over `DeviceProfile`/`FROM_DEVICE` and writes `fraudlens/pipeline/out/gds_degree_centrality.json` with the top 10 scores and provenance. This is a **global graph-quality signal**; it is not used as a case-level fraud finding or authorization input. The case path still uses cutoff-bounded observed relations.

The first exploratory invocation used the wrong reverse-edge orientation and returned zero scores; it was discarded. The checked-in artifact is from the corrected `rev_FROM_DEVICE` orientation and is the only GDS result eligible for release documentation.

- If GDS ran, publish the exact package query, graph element types, timestamp, and output hash.
- If it did not run, say so and describe the deterministic bounded algorithm result instead.
- Never convert a shared-device count into a fraud ring without independent corroborated evidence.
