"""Tool service shared by the stdio server and explicit test client."""
from __future__ import annotations

import json
from typing import Any, Callable

from graph_tools.backend import BackendError


class ToolService:
    """Validated allow-list of graph operations exposed over MCP."""

    def __init__(self, backend: Any) -> None:
        self.backend = backend

    @staticmethod
    def _text(value: Any, name: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must be a non-empty string")
        return value.strip()

    @staticmethod
    def _limit(value: Any, default: int = 100) -> int:
        result = int(default if value is None else value)
        if result < 1 or result > 5000:
            raise ValueError("limit must be between 1 and 5000")
        return result

    def transaction_context(self, txn_id: str) -> dict[str, Any]:
        return self.backend.transaction_context(self._text(txn_id, "txn_id"))

    def card_window(self, card_id: str, start: str, end: str) -> dict[str, Any]:
        return {
            "card_id": self._text(card_id, "card_id"),
            "start": self._text(start, "start"),
            "end": self._text(end, "end"),
            "transactions": self.backend.card_window(
                self._text(card_id, "card_id"), self._text(start, "start"), self._text(end, "end")
            ),
        }

    def customer_history(self, customer_id: str, start: str, end: str) -> dict[str, Any]:
        cards, transactions = self.backend.customer_history(
            self._text(customer_id, "customer_id"), self._text(start, "start"), self._text(end, "end")
        )
        return {"customer_id": customer_id, "cards": cards, "transactions": transactions}

    def device_neighborhood(self, device_id: str, start: str, end: str) -> dict[str, Any]:
        return self.backend.device_neighborhood(
            self._text(device_id, "device_id"), self._text(start, "start"), self._text(end, "end")
        )

    def region_activity(self, card_id: str, region_id: str, start: str, end: str) -> dict[str, Any]:
        return {
            "card_id": self._text(card_id, "card_id"),
            "region_id": self._text(region_id, "region_id"),
            "transactions": self.backend.region_activity(
                self._text(card_id, "card_id"), self._text(region_id, "region_id"),
                self._text(start, "start"), self._text(end, "end"),
            ),
        }

    def graph_ring(
        self,
        txn_id: str,
        target_type: str | None = None,
        target_id: str | None = None,
    ) -> dict[str, Any]:
        txn_id = self._text(txn_id, "txn_id")
        result = self.backend.graph_component(
            txn_id,
            self._text(target_type, "target_type") if target_type else None,
            self._text(target_id, "target_id") if target_id else None,
        )
        result["seed_transaction_id"] = txn_id
        return result

    def shared_neighbors(self, txn_id: str) -> dict[str, Any]:
        return self.backend.shared_neighbors(self._text(txn_id, "txn_id"))

    def similar_cases(self, pattern: str, exposure_usd: float = 0.0) -> dict[str, Any]:
        return {
            "pattern": self._text(pattern, "pattern"),
            "cases": self.backend.similar_cases(self._text(pattern, "pattern"), float(exposure_usd)),
        }

    def policy_retrieval(
        self,
        query: str,
        pattern: str = "",
        txn_id: str = "",
        card_id: str = "",
        customer_id: str = "",
        device_id: str = "",
        limit: int = 5,
    ) -> dict[str, Any]:
        return self.backend.policy_retrieval(
            self._text(query, "query"), pattern=str(pattern or ""), txn_id=str(txn_id or ""),
            card_id=str(card_id or ""), customer_id=str(customer_id or ""), device_id=str(device_id or ""),
            limit=self._limit(limit, 5),
        )

    def case_write(
        self,
        case_payload: dict[str, Any],
        txn_ids: list[str] | None = None,
        card_ids: list[str] | None = None,
        device_ids: list[str] | None = None,
        prior_case_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        if not isinstance(case_payload, dict):
            raise ValueError("case_payload must be an object")
        return self.backend.write_case(
            case_payload,
            [str(value) for value in (txn_ids or [])],
            [str(value) for value in (card_ids or [])],
            [str(value) for value in (device_ids or [])],
            [str(value) for value in (prior_case_ids or [])],
        )

    def case_read(self, case_id: str) -> dict[str, Any]:
        return self.backend.read_case(self._text(case_id, "case_id"))

    def tool_names(self) -> list[str]:
        return [
            "transaction_context", "card_window", "customer_history", "device_neighborhood",
            "region_activity", "graph_ring", "shared_neighbors", "similar_cases",
            "policy_retrieval", "case_write", "case_read",
        ]

    def call(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        if name not in self.tool_names():
            raise KeyError(f"tool is not allow-listed: {name}")
        arguments = arguments or {}
        if not isinstance(arguments, dict):
            raise ValueError("tool arguments must be an object")
        method: Callable[..., Any] = getattr(self, name)
        try:
            return method(**arguments)
        except BackendError:
            raise
        except (TypeError, ValueError, KeyError) as exc:
            raise ValueError(str(exc)) from exc

    def describe(self) -> list[dict[str, Any]]:
        descriptions = {
            "transaction_context": "Resolve one transaction to its card, customer, and device.",
            "card_window": "Return transactions on one card in an explicit time window.",
            "customer_history": "Return a customer's cards and transactions in a time window.",
            "device_neighborhood": "Return transactions, cards, customers, and prior cases around one device.",
            "region_activity": "Return card transactions in a billing region and time window.",
            "graph_ring": "Return a bounded real graph ring, connected component, and optional shortest path.",
            "shared_neighbors": "Return actual shared-device neighbors for a transaction.",
            "similar_cases": "Retrieve confirmed closed cases by pattern and exposure proximity.",
            "policy_retrieval": "Retrieve deterministic local policy chunks and graph-filtered case memory with provenance.",
            "case_write": "Write an AgentCase plus evidence edges using the existing schema.",
            "case_read": "Read an AgentCase and its evidence edges.",
        }
        return [{"name": name, "description": descriptions[name], "inputSchema": {"type": "object"}} for name in self.tool_names()]


def encode_tool_error(message: str) -> str:
    return json.dumps({"error": message}, sort_keys=True)
