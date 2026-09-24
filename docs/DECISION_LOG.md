# FraudLens engineering decisions

## ADR-001 — The model does not decide policy actions

A calibrated statistical model may rank fraud likelihood, but it cannot authorize a block, file a report, or override the bank policy. The deterministic policy engine owns actions and approval routes.

## ADR-002 — Investigations are evaluated as of `opened_at`

The initial decision may use only graph evidence available when the case was opened. Later transactions may be discussed as a delayed retrospective review, but they cannot silently enter the initial benchmark decision or training features.

## ADR-003 — Observed trigger evidence is distinct from simulation

A customer-report trigger such as “I never made this purchase” is observed denial evidence. Any later reply, step-up result, or analyst response is a simulation until a real integration exists. Simulations are stored with their assumption and never described as observed facts.

## ADR-004 — Probability and policy thresholds remain separate

The model emits `fraud_probability`. A denial/classification may inform the final assessment, but hard `.1`/`.9` policy floors are not written into that field. Any decision override is represented separately and explained.

## ADR-005 — TigerGraph is an MCP-mediated tool boundary

The investigation runtime accesses graph operations through named, allow-listed MCP tools. Direct pyTigerGraph remains an administrative dependency for schema, load, health checks, and test fixtures—not an unrestricted agent write surface.

## ADR-006 — Graph evidence is bounded and provenance-bearing

Queries return counts, top-K entities, time windows, query parameters, and provenance. They do not flood the model or dashboard with unbounded raw neighborhoods. Every graph-derived claim names the query and entities that support it.

## ADR-007 — Unknown device profiles do not connect customers

A transaction with no identity profile remains an online transaction with missing identity evidence. It does not create a shared “unknown device” vertex that connects thousands of unrelated cards.

## ADR-008 — Similar cases must influence or explain memory

A case-memory result is useful only when its outcome and similarity dimensions are visible and either influence the recommendation or explain why it did not. IDs alone are not case memory.

## ADR-009 — SAR text is generated from structured facts

The report builder may state an exposure threshold, shared origin, customer response, or coordinated pattern only when the corresponding structured fact is true. Generic regulatory prose must never invent threshold or graph evidence.

## ADR-010 — The dashboard is an analyst workspace

The UI prioritizes evidence, uncertainty, policy, approvals, and auditability over decorative charts. “Fraud likelihood,” “evidence confidence,” and “decision readiness” are distinct concepts and must be labeled independently.

## ADR-011 — Historical pattern labels are noisy guidance, not ground truth

The calibrated model is trained for binary fraud likelihood (`confirmed_fraud` versus `cleared`). Exact agreement with legacy `closed_cases_history.pattern` is reported as a diagnostic, not presented as model accuracy. Several historical labels assign broad fraud patterns to ordinary or established activity; the production detector intentionally requires anomaly and corroboration evidence before taking an operational branch.

## ADR-012 — Policy retrieval is grounded, not authoritative

TigerGraph `PolicyChunk` retrieval supplies ranked policy text and provenance for each investigation. The deterministic R1–R10 implementation remains the only action authority; a retrieval score can never authorize a block, report, or route.

## ADR-013 — AgentCase writes are replaceable and auditable

A case write stores the complete exported answer, replaces prior `AG_*` edges for that case, and records explicit similarity scores only for retrieved prior cases. A failed write is reported as `written_to_graph: false`; the local answer is never presented as remotely persisted.
