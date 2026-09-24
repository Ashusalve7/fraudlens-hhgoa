"""Validated graph-tool service shared by MCP transports and local tests."""
from __future__ import annotations

import copy
import json
import math
import re
from datetime import UTC, date, datetime
from typing import Any

from graph_tools.backend import BackendError

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_TARGET_TYPES = {"Transaction", "Card", "DeviceProfile", "Customer", "ClosedCase"}


def _string_property(description: str, *, max_length: int = 128) -> dict[str, Any]:
    return {"type": "string", "minLength": 1, "maxLength": max_length, "description": description}


_TOOL_DEFINITIONS: dict[str, dict[str, Any]] = {
    "transaction_context": {
        "description": "Resolve one transaction to its observed card, customer, and device.",
        "schema": {
            "type": "object",
            "properties": {"txn_id": _string_property("Transaction primary ID.")},
            "required": ["txn_id"],
            "additionalProperties": False,
        },
    },
    "card_window": {
        "description": "Return transactions on one card in an explicit inclusive time window.",
        "schema": {
            "type": "object",
            "properties": {
                "card_id": _string_property("Card primary ID."),
                "start": _string_property("Inclusive ISO-8601 window start.", max_length=64),
                "end": _string_property("Inclusive ISO-8601 window end.", max_length=64),
            },
            "required": ["card_id", "start", "end"],
            "additionalProperties": False,
        },
    },
    "customer_history": {
        "description": "Return a customer's cards and transactions in an explicit time window.",
        "schema": {
            "type": "object",
            "properties": {
                "customer_id": _string_property("Customer primary ID."),
                "start": _string_property("Inclusive ISO-8601 window start.", max_length=64),
                "end": _string_property("Inclusive ISO-8601 window end.", max_length=64),
            },
            "required": ["customer_id", "start", "end"],
            "additionalProperties": False,
        },
    },
    "device_neighborhood": {
        "description": "Return time-filtered device transactions, cards, customers, and prior cases.",
        "schema": {
            "type": "object",
            "properties": {
                "device_id": _string_property("DeviceProfile primary ID."),
                "start": _string_property("Inclusive ISO-8601 activity start.", max_length=64),
                "end": _string_property("Inclusive ISO-8601 activity/cutoff end.", max_length=64),
            },
            "required": ["device_id", "start", "end"],
            "additionalProperties": False,
        },
    },
    "region_activity": {
        "description": "Return card transactions in one billing region and time window.",
        "schema": {
            "type": "object",
            "properties": {
                "card_id": _string_property("Card primary ID."),
                "region_id": _string_property("BillingRegion primary ID."),
                "start": _string_property("Inclusive ISO-8601 window start.", max_length=64),
                "end": _string_property("Inclusive ISO-8601 window end.", max_length=64),
            },
            "required": ["card_id", "region_id", "start", "end"],
            "additionalProperties": False,
        },
    },
    "graph_ring": {
        "description": "Run bounded component and optional shortest-path algorithms over a real graph ring.",
        "schema": {
            "type": "object",
            "properties": {
                "txn_id": _string_property("Seed transaction primary ID."),
                "target_type": {
                    "type": "string",
                    "enum": sorted(_TARGET_TYPES),
                    "description": "Optional shortest-path target node type.",
                },
                "target_id": _string_property("Optional shortest-path target node ID."),
            },
            "required": ["txn_id"],
            "additionalProperties": False,
        },
    },
    "shared_neighbors": {
        "description": "Return actual shared-device neighbors; the seed transaction is excluded.",
        "schema": {
            "type": "object",
            "properties": {"txn_id": _string_property("Seed transaction primary ID.")},
            "required": ["txn_id"],
            "additionalProperties": False,
        },
    },
    "similar_cases": {
        "description": "Retrieve confirmed closed cases by pattern and exposure proximity.",
        "schema": {
            "type": "object",
            "properties": {
                "pattern": _string_property("Exact closed-case pattern."),
                "exposure_usd": {
                    "type": "number",
                    "minimum": 0,
                    "description": "Nonnegative exposure used for nearest-case ordering.",
                },
            },
            "required": ["pattern"],
            "additionalProperties": False,
        },
    },
    "policy_retrieval": {
        "description": "Retrieve deterministic PolicyChunks and graph-filtered case memory.",
        "schema": {
            "type": "object",
            "properties": {
                "query": _string_property("Policy/pattern retrieval query.", max_length=2048),
                "pattern": _string_property("Optional exact pattern tag."),
                "txn_id": _string_property("Optional graph-filter transaction ID."),
                "card_id": _string_property("Optional graph-filter card ID."),
                "customer_id": _string_property("Optional graph-filter customer ID."),
                "device_id": _string_property("Optional graph-filter device ID."),
                "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 5},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    "case_write": {
        "description": "Write an AgentCase and explicit evidence edges; similarity scores are never invented.",
        "schema": {
            "type": "object",
            "properties": {
                "case_payload": {"type": "object", "description": "AgentCase fields, including case_id."},
                "txn_ids": {"type": "array", "items": {"type": "string"}, "maxItems": 5000},
                "card_ids": {"type": "array", "items": {"type": "string"}, "maxItems": 5000},
                "device_ids": {"type": "array", "items": {"type": "string"}, "maxItems": 5000},
                "prior_case_ids": {"type": "array", "items": {"type": "string"}, "maxItems": 5000},
                "prior_case_scores": {
                    "type": "object",
                    "additionalProperties": {"type": "number", "minimum": 0, "maximum": 1},
                    "description": "Explicit case-ID-to-score map; only these AG_SIMILAR edges are written.",
                },
            },
            "required": ["case_payload"],
            "additionalProperties": False,
        },
    },
    "case_read": {
        "description": "Read an AgentCase and its persisted evidence edges.",
        "schema": {
            "type": "object",
            "properties": {"case_id": _string_property("AgentCase primary ID.")},
            "required": ["case_id"],
            "additionalProperties": False,
        },
    },
}


class ToolService:
    """Narrow, allow-listed application service used by the MCP server."""

    def __init__(self, backend: Any) -> None:
        self.backend = backend

    @staticmethod
    def _text(value: Any, name: str, *, max_length: int = 128) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must be a non-empty string")
        result = value.strip()
        if len(result) > max_length:
            raise ValueError(f"{name} must be at most {max_length} characters")
        return result

    @staticmethod
    def _identifier(value: Any, name: str) -> str:
        result = ToolService._text(value, name)
        if not _ID.fullmatch(result):
            raise ValueError(f"{name} contains unsupported characters")
        return result

    @staticmethod
    def _datetime(value: Any, name: str) -> str:
        text = ToolService._text(value, name, max_length=64)
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            try:
                parsed = datetime.combine(date.fromisoformat(text), datetime.min.time())
            except ValueError as exc:
                raise ValueError(f"{name} must be an ISO-8601 date or datetime") from exc
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(UTC).replace(tzinfo=None)
        return parsed.strftime("%Y-%m-%d %H:%M:%S")

    @classmethod
    def _window(cls, start: Any, end: Any) -> tuple[str, str]:
        start_value = cls._datetime(start, "start")
        end_value = cls._datetime(end, "end")
        if start_value > end_value:
            raise ValueError("start must not be after end")
        return start_value, end_value

    @staticmethod
    def _limit(value: Any, default: int = 5, maximum: int = 50) -> int:
        if isinstance(value, bool):
            raise ValueError("limit must be an integer")
        try:
            result = int(default if value is None else value)
        except (TypeError, ValueError) as exc:
            raise ValueError("limit must be an integer") from exc
        if result < 1 or result > maximum:
            raise ValueError(f"limit must be between 1 and {maximum}")
        return result

    @staticmethod
    def _ids(value: Any, name: str) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError(f"{name} must be an array")
        if len(value) > 5000:
            raise ValueError(f"{name} may contain at most 5000 IDs")
        result: list[str] = []
        seen: set[str] = set()
        for item in value:
            identifier = ToolService._identifier(item, f"{name} item")
            if identifier not in seen:
                seen.add(identifier)
                result.append(identifier)
        return result

    @staticmethod
    def _exposure(value: Any) -> float:
        if isinstance(value, bool):
            raise ValueError("exposure_usd must be a finite nonnegative number")
        try:
            result = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("exposure_usd must be a finite nonnegative number") from exc
        if not math.isfinite(result) or result < 0:
            raise ValueError("exposure_usd must be a finite nonnegative number")
        return result

    @staticmethod
    def _similarity_score(value: Any) -> float:
        if isinstance(value, bool):
            raise ValueError("prior case scores must be finite numbers between 0 and 1")
        try:
            result = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("prior case scores must be finite numbers between 0 and 1") from exc
        if not math.isfinite(result) or not 0 <= result <= 1:
            raise ValueError("prior case scores must be finite numbers between 0 and 1")
        return result

    def transaction_context(self, txn_id: str) -> dict[str, Any]:
        return self.backend.transaction_context(self._identifier(txn_id, "txn_id"))

    def card_window(self, card_id: str, start: str, end: str) -> dict[str, Any]:
        card = self._identifier(card_id, "card_id")
        start_value, end_value = self._window(start, end)
        return {
            "card_id": card,
            "start": start_value,
            "end": end_value,
            "transactions": self.backend.card_window(card, start_value, end_value),
        }

    def customer_history(self, customer_id: str, start: str, end: str) -> dict[str, Any]:
        customer = self._identifier(customer_id, "customer_id")
        start_value, end_value = self._window(start, end)
        cards, transactions = self.backend.customer_history(customer, start_value, end_value)
        return {
            "customer_id": customer,
            "start": start_value,
            "end": end_value,
            "cards": cards,
            "transactions": transactions,
        }

    def device_neighborhood(self, device_id: str, start: str, end: str) -> dict[str, Any]:
        device = self._identifier(device_id, "device_id")
        start_value, end_value = self._window(start, end)
        result = self.backend.device_neighborhood(device, start_value, end_value)
        return {
            "device_id": device,
            "start": start_value,
            "end": end_value,
            **result,
        }

    def region_activity(self, card_id: str, region_id: str, start: str, end: str) -> dict[str, Any]:
        card = self._identifier(card_id, "card_id")
        region = self._identifier(region_id, "region_id")
        start_value, end_value = self._window(start, end)
        return {
            "card_id": card,
            "region_id": region,
            "start": start_value,
            "end": end_value,
            "transactions": self.backend.region_activity(
                card, region, start_value, end_value
            ),
        }

    def graph_ring(
        self,
        txn_id: str,
        target_type: str | None = None,
        target_id: str | None = None,
    ) -> dict[str, Any]:
        seed = self._identifier(txn_id, "txn_id")
        if (target_type is None) != (target_id is None):
            raise ValueError("target_type and target_id must be supplied together")
        if target_type is not None and target_type not in _TARGET_TYPES:
            raise ValueError(f"target_type must be one of {sorted(_TARGET_TYPES)}")
        target = self._identifier(target_id, "target_id") if target_id is not None else None
        result = self.backend.graph_component(seed, target_type, target)
        result["seed_transaction_id"] = seed
        return result

    def shared_neighbors(self, txn_id: str) -> dict[str, Any]:
        return self.backend.shared_neighbors(self._identifier(txn_id, "txn_id"))

    def similar_cases(self, pattern: str, exposure_usd: float = 0.0) -> dict[str, Any]:
        pattern_value = self._text(pattern, "pattern")
        exposure = self._exposure(exposure_usd)
        return {
            "pattern": pattern_value,
            "exposure_usd": exposure,
            "cases": self.backend.similar_cases(pattern_value, exposure),
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
        optional = {
            name: self._identifier(value, name)
            for name, value in {
                "txn_id": txn_id,
                "card_id": card_id,
                "customer_id": customer_id,
                "device_id": device_id,
            }.items()
            if value not in (None, "")
        }
        pattern_value = (
            self._text(pattern, "pattern") if pattern not in (None, "") else ""
        )
        return self.backend.policy_retrieval(
            self._text(query, "query", max_length=2048),
            pattern=pattern_value,
            limit=self._limit(limit),
            **optional,
        )

    def case_write(
        self,
        case_payload: dict[str, Any],
        txn_ids: list[str] | None = None,
        card_ids: list[str] | None = None,
        device_ids: list[str] | None = None,
        prior_case_ids: list[str] | None = None,
        prior_case_scores: dict[str, float] | None = None,
    ) -> dict[str, Any]:
        if not isinstance(case_payload, dict):
            raise ValueError("case_payload must be an object")
        self._identifier(case_payload.get("case_id"), "case_payload.case_id")
        if prior_case_scores is None:
            scores: dict[str, float] = {}
        elif isinstance(prior_case_scores, dict):
            scores = {
                self._identifier(key, "prior_case_scores key"): self._similarity_score(value)
                for key, value in prior_case_scores.items()
            }
        else:
            raise ValueError("prior_case_scores must be an object")
        return self.backend.write_case(
            case_payload,
            self._ids(txn_ids, "txn_ids"),
            self._ids(card_ids, "card_ids"),
            self._ids(device_ids, "device_ids"),
            self._ids(prior_case_ids, "prior_case_ids"),
            scores,
        )

    def case_read(self, case_id: str) -> dict[str, Any]:
        return self.backend.read_case(self._identifier(case_id, "case_id"))

    def tool_names(self) -> list[str]:
        return list(_TOOL_DEFINITIONS)

    def call(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        if name not in _TOOL_DEFINITIONS:
            raise KeyError(f"tool is not allow-listed: {name}")
        arguments = arguments or {}
        if not isinstance(arguments, dict):
            raise ValueError("tool arguments must be an object")
        unexpected = sorted(set(arguments) - set(_TOOL_DEFINITIONS[name]["schema"]["properties"]))
        if unexpected:
            raise ValueError(f"unexpected arguments for {name}: {unexpected}")
        method = getattr(self, name)
        try:
            return method(**arguments)
        except BackendError:
            raise
        except (TypeError, ValueError, KeyError) as exc:
            raise ValueError(str(exc)) from exc

    def describe(self) -> list[dict[str, Any]]:
        return [
            {
                "name": name,
                "description": definition["description"],
                "inputSchema": copy.deepcopy(definition["schema"]),
            }
            for name, definition in _TOOL_DEFINITIONS.items()
        ]


def encode_tool_error(message: str) -> str:
    return json.dumps({"error": message}, sort_keys=True)
