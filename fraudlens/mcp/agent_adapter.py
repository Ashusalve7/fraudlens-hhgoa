"""Drop-in synchronous evidence adapter for the existing agent runner.

The current ``runner.py`` expects a small Evidence-shaped object.  This adapter
keeps that API but routes every graph operation through the local MCP stdio
boundary.  The in-process mode is intentionally explicit and intended only for
focused tests.
"""
from __future__ import annotations

import atexit
from typing import Any

from mcp.client import InProcessMCPClient, StdioMCPClient


class Evidence:
    """MCP-backed compatibility facade for ``agent.evidence.Evidence``."""

    def __init__(
        self,
        *,
        mode: str = "mcp",
        backend: Any | None = None,
        case_store: str | None = None,
    ) -> None:
        self.calls: list[dict[str, Any]] = []
        self.mode = mode
        if mode == "mcp":
            self.client = StdioMCPClient()
        elif mode == "inprocess-test":
            if backend is None:
                raise ValueError("mode='inprocess-test' requires an explicit local backend")
            self.client = InProcessMCPClient(backend)
        else:
            raise ValueError("mode must be 'mcp' or explicit 'inprocess-test'")
        atexit.register(self.close)

    def _call(self, tool: str, arguments: dict[str, Any]) -> Any:
        self.calls.append({"tool": tool, "arguments": arguments})
        return self.client.call_tool(tool, arguments)

    def txn_context(self, txn_id: str) -> dict[str, Any]:
        return self._call("transaction_context", {"txn_id": str(txn_id)})

    def card_window(self, card_id: str, start: str, end: str) -> list[dict[str, Any]]:
        return self._call("card_window", {
            "card_id": str(card_id), "start": str(start), "end": str(end),
        })["transactions"]

    def customer_history(self, customer_id: str, start: str, end: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        result = self._call("customer_history", {
            "customer_id": str(customer_id), "start": str(start), "end": str(end),
        })
        return result["cards"], result["transactions"]

    def device_neighborhood(self, device_id: str, start: str, end: str) -> dict[str, Any]:
        return self._call("device_neighborhood", {
            "device_id": str(device_id), "start": str(start), "end": str(end),
        })

    def region_activity(self, card_id: str, region_id: str, start: str, end: str) -> list[dict[str, Any]]:
        return self._call("region_activity", {
            "card_id": str(card_id), "region_id": str(region_id), "start": str(start), "end": str(end),
        })["transactions"]

    def similar_cases(self, pattern: str, exposure: float) -> list[dict[str, Any]]:
        return self._call("similar_cases", {"pattern": str(pattern), "exposure_usd": float(exposure)})["cases"]

    def write_agent_case(
        self,
        case_payload: dict[str, Any],
        txn_ids: list[str],
        card_ids: list[str],
        device_ids: list[str],
        prior_case_ids: list[str],
    ) -> str:
        result = self._call("case_write", {
            "case_payload": case_payload,
            "txn_ids": [str(value) for value in txn_ids],
            "card_ids": [str(value) for value in card_ids],
            "device_ids": [str(value) for value in device_ids],
            "prior_case_ids": [str(value) for value in prior_case_ids],
        })
        return str(result["case_id"])

    # New graph-tool surface; these methods are optional for the current runner.
    def graph_ring(self, txn_id: str, target_type: str | None = None, target_id: str | None = None) -> dict[str, Any]:
        return self._call("graph_ring", {
            "txn_id": str(txn_id), "target_type": target_type, "target_id": target_id,
        })

    def shared_neighbors(self, txn_id: str) -> dict[str, Any]:
        return self._call("shared_neighbors", {"txn_id": str(txn_id)})

    def policy_retrieval(self, query: str, **kwargs: Any) -> dict[str, Any]:
        return self._call("policy_retrieval", {"query": str(query), **kwargs})

    def read_agent_case(self, case_id: str) -> dict[str, Any]:
        return self._call("case_read", {"case_id": str(case_id)})

    def close(self) -> None:
        client = getattr(self, "client", None)
        if client is not None:
            close = getattr(client, "close", None)
            if close:
                close()
            self.client = None  # type: ignore[assignment]

    def __enter__(self) -> "Evidence":
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()
