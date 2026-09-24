"""Evidence-shaped adapter that routes graph operations through MCP."""
from __future__ import annotations

import atexit
import time
from collections.abc import Mapping
from contextlib import suppress
from pathlib import Path
from typing import Any

from mcp.client import InProcessMCPClient, StdioMCPClient

_QUERY_NAMES = {
    "transaction_context": "get_transaction_context",
    "card_window": "get_card_window",
    "customer_history": "get_customer_history",
    "device_neighborhood": "get_device_neighborhood",
    "region_activity": "get_region_activity",
    "graph_ring": "get_graph_ring",
    "shared_neighbors": "get_shared_neighbors",
    "similar_cases": "find_similar_cases",
    "policy_retrieval": "policy_retrieval",
    "case_write": "write_agent_case+edges",
    "case_read": "get_agent_case",
}


def _sanitize(value: Any, *, depth: int = 0) -> Any:
    """Bound audit-log size while retaining short factual parameters."""
    if depth >= 4:
        return "<nested>"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value if len(value) <= 256 else value[:253] + "..."
    if isinstance(value, Mapping):
        return {
            str(key): _sanitize(item, depth=depth + 1)
            for index, (key, item) in enumerate(value.items())
            if index < 50
        }
    if isinstance(value, (list, tuple, set)):
        return [_sanitize(item, depth=depth + 1) for item in list(value)[:50]]
    return f"<{type(value).__name__}>"


def _query_params(tool: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
    if tool in {"transaction_context", "shared_neighbors", "graph_ring"}:
        return {"in_txn_id": str(arguments.get("txn_id", ""))}
    if tool in {"card_window", "customer_history", "device_neighborhood"}:
        prefix = {
            "card_window": "in_card_id",
            "customer_history": "in_customer_id",
            "device_neighborhood": "in_device_id",
        }[tool]
        return {
            prefix: str(arguments.get(prefix.removeprefix("in_"), "")),
            "in_start": str(arguments.get("start", "")),
            "in_end": str(arguments.get("end", "")),
        }
    if tool == "region_activity":
        return {
            "in_card_id": str(arguments.get("card_id", "")),
            "in_region_id": str(arguments.get("region_id", "")),
            "in_start": str(arguments.get("start", "")),
            "in_end": str(arguments.get("end", "")),
        }
    if tool == "similar_cases":
        return {
            "in_pattern": str(arguments.get("pattern", "")),
            "in_exposure_usd": arguments.get("exposure_usd", 0),
        }
    if tool == "case_write":
        payload = arguments.get("case_payload")
        case_id = payload.get("case_id", "") if isinstance(payload, Mapping) else ""
        return {"case_id": str(case_id)}
    if tool == "case_read":
        return {"in_case_id": str(arguments.get("case_id", ""))}
    if tool == "policy_retrieval":
        return {
            key: value
            for key, value in {
                "in_txn_id": arguments.get("txn_id", ""),
                "in_card_id": arguments.get("card_id", ""),
                "in_customer_id": arguments.get("customer_id", ""),
                "in_device_id": arguments.get("device_id", ""),
                "in_pattern": arguments.get("pattern", ""),
            }.items()
            if value
        }
    return {}


class Evidence:
    """Drop-in synchronous evidence facade backed by allow-listed MCP tools."""

    def __init__(
        self,
        *,
        mode: str = "mcp",
        backend: Any | None = None,
        case_store: str | Path | None = None,
        load_dir: str | Path | None = None,
        out_dir: str | Path | None = None,
        server_path: str | Path | None = None,
        client_backend: str = "tigergraph",
        allow_local_test_backend: bool = False,
        timeout_seconds: float = 15.0,
    ) -> None:
        self.calls: list[dict[str, Any]] = []
        self.query_log: list[dict[str, Any]] = []
        self.case_id: str | None = None
        self.mode = mode
        if mode == "mcp":
            self.client: Any = StdioMCPClient(
                server_path=Path(server_path) if server_path else None,
                backend=client_backend,
                case_store=Path(case_store) if case_store else None,
                load_dir=Path(load_dir) if load_dir else None,
                out_dir=Path(out_dir) if out_dir else None,
                allow_local_test_backend=allow_local_test_backend,
                timeout_seconds=timeout_seconds,
            )
        elif mode == "inprocess-test":
            if backend is None:
                raise ValueError("mode='inprocess-test' requires an explicit local/mock backend")
            self.client = InProcessMCPClient(backend)
        else:
            raise ValueError("mode must be 'mcp' or explicit 'inprocess-test'")
        atexit.register(self.close)

    @property
    def tool_count(self) -> int:
        return len(self.calls)

    @property
    def call_count(self) -> int:
        return len(self.calls)

    def begin_case(self, case_id: str) -> Evidence:
        self.case_id = str(case_id)
        self.calls = []
        self.query_log = []
        return self

    start_case = begin_case
    reset_case = begin_case

    def _call(self, tool: str, arguments: dict[str, Any]) -> Any:
        client = getattr(self, "client", None)
        if client is None:
            raise RuntimeError("Evidence MCP client is closed")
        clean_arguments = _sanitize(arguments)
        record: dict[str, Any] = {
            "case_id": self.case_id,
            "tool": tool,
            "query": _QUERY_NAMES.get(tool, tool),
            "params": _query_params(tool, arguments),
            "arguments": clean_arguments,
            "authorization": "allow-listed MCP operation",
            "decision": "allow",
        }
        started = time.perf_counter()
        try:
            value = client.call_tool(tool, arguments)
        except Exception as exc:
            record.update(
                {
                    "status": "error",
                    "latency_ms": round((time.perf_counter() - started) * 1000, 3),
                    "result_type": type(exc).__name__,
                    "error": str(exc)[:256],
                }
            )
            self.calls.append(record)
            self.query_log.append(dict(record))
            raise
        record.update(
            {
                "status": "ok",
                "latency_ms": round((time.perf_counter() - started) * 1000, 3),
                "result_type": type(value).__name__,
            }
        )
        self.calls.append(record)
        self.query_log.append(dict(record))
        return value

    def txn_context(self, txn_id: str) -> dict[str, Any]:
        return self._call("transaction_context", {"txn_id": str(txn_id)})

    def card_window(self, card_id: str, start: str, end: str) -> list[dict[str, Any]]:
        result = self._call(
            "card_window",
            {"card_id": str(card_id), "start": str(start), "end": str(end)},
        )
        return list(result["transactions"])

    def customer_history(
        self, customer_id: str, start: str, end: str
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        result = self._call(
            "customer_history",
            {"customer_id": str(customer_id), "start": str(start), "end": str(end)},
        )
        return list(result["cards"]), list(result["transactions"])

    def device_neighborhood(self, device_id: str, start: str, end: str) -> dict[str, Any]:
        return self._call(
            "device_neighborhood",
            {"device_id": str(device_id), "start": str(start), "end": str(end)},
        )

    def region_activity(
        self, card_id: str, region_id: str, start: str, end: str
    ) -> list[dict[str, Any]]:
        result = self._call(
            "region_activity",
            {
                "card_id": str(card_id),
                "region_id": str(region_id),
                "start": str(start),
                "end": str(end),
            },
        )
        return list(result["transactions"])

    def similar_cases(self, pattern: str, exposure: float) -> list[dict[str, Any]]:
        result = self._call(
            "similar_cases",
            {"pattern": str(pattern), "exposure_usd": float(exposure)},
        )
        return list(result["cases"])

    def write_agent_case(
        self,
        case_payload: dict[str, Any],
        txn_ids: list[str],
        card_ids: list[str],
        device_ids: list[str],
        prior_case_ids: list[str],
        prior_case_scores: Mapping[str, float] | None = None,
    ) -> str:
        result = self._call(
            "case_write",
            {
                "case_payload": case_payload,
                "txn_ids": [str(value) for value in txn_ids],
                "card_ids": [str(value) for value in card_ids],
                "device_ids": [str(value) for value in device_ids],
                "prior_case_ids": [str(value) for value in prior_case_ids],
                "prior_case_scores": dict(prior_case_scores or {}),
            },
        )
        return str(result["case_id"])

    def graph_ring(
        self,
        txn_id: str,
        target_type: str | None = None,
        target_id: str | None = None,
    ) -> dict[str, Any]:
        return self._call(
            "graph_ring",
            {"txn_id": str(txn_id), "target_type": target_type, "target_id": target_id},
        )

    def shared_neighbors(self, txn_id: str) -> dict[str, Any]:
        return self._call("shared_neighbors", {"txn_id": str(txn_id)})

    def policy_retrieval(self, query: str, **kwargs: Any) -> dict[str, Any]:
        return self._call("policy_retrieval", {"query": str(query), **kwargs})

    def read_agent_case(self, case_id: str) -> dict[str, Any]:
        return self._call("case_read", {"case_id": str(case_id)})

    def close(self) -> None:
        client = getattr(self, "client", None)
        if client is None:
            return
        with suppress(Exception):  # interpreter shutdown can make unregister unavailable
            atexit.unregister(self.close)
        close = getattr(client, "close", None)
        if callable(close):
            close()
        self.client = None

    def __enter__(self) -> Evidence:
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()


MCPEvidence = Evidence


def create_evidence(**kwargs: Any) -> Evidence:
    """Factory for dependency injection by ``agent/evidence.py``."""
    return Evidence(**kwargs)


__all__ = ["Evidence", "MCPEvidence", "create_evidence"]
