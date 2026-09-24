"""FraudLens graph MCP server using the official Python MCP SDK.

The server exposes only named, validated operations over stdio.  Production
uses TigerGraph; ``local-test`` is an explicit offline parquet backend and
never falls back from a production graph failure.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Resolve the official SDK before importing any official mcp.server module;
# this repository intentionally also has an application package named mcp.
from mcp.sdk_compat import configure_official_sdk  # noqa: E402

configure_official_sdk(official_first=True)

from graph_tools.backend import LocalParquetBackend, make_production_backend  # noqa: E402
from mcp.service import ToolService  # noqa: E402


def _register_tools(server: Any, service: ToolService) -> None:
    """Register typed wrappers so FastMCP publishes real input/output schemas."""
    descriptions = {
        definition["name"]: definition["description"]
        for definition in service.describe()
    }

    def register(function: Any, name: str) -> None:
        server.tool(
            name=name,
            description=descriptions[name],
            structured_output=True,
        )(function)

    def transaction_context(txn_id: str) -> dict[str, Any]:
        return service.call("transaction_context", {"txn_id": txn_id})

    def card_window(card_id: str, start: str, end: str) -> dict[str, Any]:
        return service.call(
            "card_window", {"card_id": card_id, "start": start, "end": end}
        )

    def customer_history(customer_id: str, start: str, end: str) -> dict[str, Any]:
        return service.call(
            "customer_history",
            {"customer_id": customer_id, "start": start, "end": end},
        )

    def device_neighborhood(device_id: str, start: str, end: str) -> dict[str, Any]:
        return service.call(
            "device_neighborhood",
            {"device_id": device_id, "start": start, "end": end},
        )

    def region_activity(
        card_id: str, region_id: str, start: str, end: str
    ) -> dict[str, Any]:
        return service.call(
            "region_activity",
            {
                "card_id": card_id,
                "region_id": region_id,
                "start": start,
                "end": end,
            },
        )

    def graph_ring(
        txn_id: str, target_type: str | None = None, target_id: str | None = None
    ) -> dict[str, Any]:
        return service.call(
            "graph_ring",
            {"txn_id": txn_id, "target_type": target_type, "target_id": target_id},
        )

    def shared_neighbors(txn_id: str) -> dict[str, Any]:
        return service.call("shared_neighbors", {"txn_id": txn_id})

    def similar_cases(pattern: str, exposure_usd: float = 0.0) -> dict[str, Any]:
        return service.call(
            "similar_cases",
            {"pattern": pattern, "exposure_usd": exposure_usd},
        )

    def policy_retrieval(
        query: str,
        pattern: str = "",
        txn_id: str = "",
        card_id: str = "",
        customer_id: str = "",
        device_id: str = "",
        limit: int = 5,
    ) -> dict[str, Any]:
        return service.call(
            "policy_retrieval",
            {
                "query": query,
                "pattern": pattern,
                "txn_id": txn_id,
                "card_id": card_id,
                "customer_id": customer_id,
                "device_id": device_id,
                "limit": limit,
            },
        )

    def case_write(
        case_payload: dict[str, Any],
        txn_ids: list[str] | None = None,
        card_ids: list[str] | None = None,
        device_ids: list[str] | None = None,
        prior_case_ids: list[str] | None = None,
        prior_case_scores: dict[str, float] | None = None,
    ) -> dict[str, Any]:
        return service.call(
            "case_write",
            {
                "case_payload": case_payload,
                "txn_ids": txn_ids,
                "card_ids": card_ids,
                "device_ids": device_ids,
                "prior_case_ids": prior_case_ids,
                "prior_case_scores": prior_case_scores,
            },
        )

    def case_read(case_id: str) -> dict[str, Any]:
        return service.call("case_read", {"case_id": case_id})

    wrappers = (
        (transaction_context, "transaction_context"),
        (card_window, "card_window"),
        (customer_history, "customer_history"),
        (device_neighborhood, "device_neighborhood"),
        (region_activity, "region_activity"),
        (graph_ring, "graph_ring"),
        (shared_neighbors, "shared_neighbors"),
        (similar_cases, "similar_cases"),
        (policy_retrieval, "policy_retrieval"),
        (case_write, "case_write"),
        (case_read, "case_read"),
    )
    for function, name in wrappers:
        register(function, name)


def _make_fastmcp(service: ToolService) -> Any:
    """Build the official SDK FastMCP server."""
    from mcp.server.fastmcp import FastMCP

    server = FastMCP(
        "fraudlens-tigergraph",
        instructions=(
            "Allow-listed FraudLens graph evidence tools. Inputs are validated; "
            "no arbitrary GSQL, shell, or filesystem operation is exposed."
        ),
    )
    _register_tools(server, service)
    return server


def _build_backend(args: argparse.Namespace) -> Any:
    if args.backend == "local-test":
        if not args.allow_local_test_backend:
            raise SystemExit(
                "local-test backend is explicit: pass --allow-local-test-backend"
            )
        return LocalParquetBackend(
            load_dir=Path(args.load_dir),
            out_dir=Path(args.out_dir),
            case_store_path=Path(args.case_store) if args.case_store else None,
        )
    return make_production_backend()


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=("tigergraph", "local-test"), default="tigergraph")
    parser.add_argument("--allow-local-test-backend", action="store_true")
    parser.add_argument("--load-dir", help="Explicit local parquet load directory")
    parser.add_argument("--out-dir", help="Explicit local retrieval/artifact directory")
    parser.add_argument("--case-store", help="Explicit JSON store for local-test case writes")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.backend == "local-test" and not args.load_dir:
        raise SystemExit("local-test backend requires --load-dir")
    service = ToolService(_build_backend(args))
    print("FraudLens MCP: official Python SDK over stdio", file=sys.stderr)
    _make_fastmcp(service).run(transport="stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
