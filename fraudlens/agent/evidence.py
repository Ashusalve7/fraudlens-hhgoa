"""Evidence access with a per-case tool ledger.

The production graph remains behind this small adapter.  The adapter is also
constructor-injectable, which keeps the decision core testable without a live
TigerGraph connection.
"""

from __future__ import annotations

import copy
import sys
from collections.abc import Mapping
from datetime import datetime
from math import isfinite
from pathlib import Path
from typing import Any


def _connection():
    # Import lazily so importing the decision module never opens a graph
    # connection merely to run unit tests.
    pipeline = str(Path(__file__).resolve().parent.parent / "pipeline")
    if pipeline not in sys.path:
        sys.path.insert(0, pipeline)
    from tg import get_conn  # type: ignore

    return get_conn()


class Evidence:
    """Typed graph facade and case-local call recorder."""

    def __init__(self, conn: Any | None = None, *, lazy: bool = True) -> None:
        self.conn = conn
        if self.conn is None and not lazy:
            self.conn = _connection()
        self.calls: list[dict[str, Any]] = []
        self.case_id: str | None = None
        self.query_log: list[dict[str, Any]] = []

    def begin_case(self, case_id: str) -> Evidence:
        """Start a fresh audit ledger; counts never carry across cases."""
        self.case_id = str(case_id)
        self.calls = []
        self.query_log = []
        return self

    # Older integrations used start_case/reset; retain the useful aliases.
    start_case = begin_case
    reset_case = begin_case

    @property
    def tool_count(self) -> int:
        return len(self.calls)

    @property
    def call_count(self) -> int:
        return len(self.calls)

    def _ensure_conn(self) -> Any:
        if self.conn is None:
            self.conn = _connection()
        return self.conn

    def _run(self, name: str, params: Mapping[str, Any]) -> list[dict[str, Any]]:
        clean_params = copy.deepcopy(dict(params))
        result = self._ensure_conn().runInstalledQuery(name, clean_params)
        self.calls.append({"query": name, "params": clean_params})
        self.query_log.append({"query": name, "params": clean_params, "result": result})
        return result

    @staticmethod
    def _rows(blocks: Any, key: str) -> list[dict[str, Any]]:
        """Normalize TigerGraph result blocks and simple test fixtures."""
        if not isinstance(blocks, list):
            return []
        for block in blocks:
            if not isinstance(block, Mapping):
                continue
            values = block.get(key)
            if not isinstance(values, list):
                continue
            rows: list[dict[str, Any]] = []
            for raw in values:
                if not isinstance(raw, Mapping):
                    continue
                attrs = raw.get("attributes", raw)
                if not isinstance(attrs, Mapping):
                    attrs = {}
                row: dict[str, Any] = {}
                for attr_key, value in attrs.items():
                    name = str(attr_key)
                    for prefix in (f"{key}.", "S.", "T.", "T2.", "Cards.", "Custs.", "Devices.", "Cases."):
                        if name.startswith(prefix):
                            name = name[len(prefix) :]
                            break
                    row[name] = value
                vertex_id = raw.get("v_id", raw.get("id"))
                if vertex_id not in (None, ""):
                    row.setdefault("id", vertex_id)
                rows.append(row)
            return rows
        return []

    def txn_context(self, txn_id: str) -> dict[str, Any]:
        blocks = self._run("get_transaction_context", {"in_txn_id": str(txn_id)})
        txns = self._rows(blocks, "S")
        cards = self._rows(blocks, "Cards")
        customers = self._rows(blocks, "Custs")
        devices = self._rows(blocks, "Devices")
        txn = txns[0] if txns else None
        if txn is not None:
            txn.setdefault("txn_id", str(txn_id))
        return {
            "txn": txn,
            "card": cards[0] if cards else None,
            "customer_id": customers[0].get("customer_id") if customers else None,
            "device": devices[0] if devices else None,
        }

    def card_window(self, card_id: str, start: str | datetime, end: str | datetime) -> list[dict[str, Any]]:
        blocks = self._run(
            "get_card_window",
            {"in_card_id": str(card_id), "in_start": str(start), "in_end": str(end)},
        )
        return self._rows(blocks, "T")

    def customer_history(
        self,
        customer_id: str,
        start: str | datetime,
        end: str | datetime,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        blocks = self._run(
            "get_customer_history",
            {"in_customer_id": str(customer_id), "in_start": str(start), "in_end": str(end)},
        )
        cards = self._rows(blocks, "Cards")
        # The installed query names this block T.  T2 is retained as a fallback
        # for older graph deployments and test doubles.
        transactions = self._rows(blocks, "T") or self._rows(blocks, "T2")
        return cards, transactions

    def device_neighborhood(
        self,
        device_id: str,
        start: str | datetime,
        end: str | datetime,
    ) -> dict[str, list[dict[str, Any]]]:
        blocks = self._run(
            "get_device_neighborhood",
            {"in_device_id": str(device_id), "in_start": str(start), "in_end": str(end)},
        )
        return {
            "txns": self._rows(blocks, "T"),
            "cards": self._rows(blocks, "Cards"),
            "customers": self._rows(blocks, "Custs"),
            "prior_cases": self._rows(blocks, "Cases"),
            "device_id": str(device_id),
        }

    def region_activity(
        self,
        card_id: str,
        region_id: str,
        start: str | datetime,
        end: str | datetime,
    ) -> list[dict[str, Any]]:
        blocks = self._run(
            "get_region_activity",
            {
                "in_card_id": str(card_id),
                "in_region_id": str(region_id),
                "in_start": str(start),
                "in_end": str(end),
            },
        )
        return self._rows(blocks, "T")

    def similar_cases(self, pattern: str, exposure: float) -> list[dict[str, Any]]:
        blocks = self._run(
            "find_similar_cases",
            {"in_pattern": str(pattern), "in_exposure_usd": float(exposure)},
        )
        rows = self._rows(blocks, "S")

        def distance(row: Mapping[str, Any]) -> float:
            try:
                value = float(row.get("exposure_usd", 0) or 0)
            except (TypeError, ValueError):
                return float("inf")
            return abs(value - float(exposure or 0)) if isfinite(value) else float("inf")

        rows.sort(key=distance)
        return rows

    def write_agent_case(
        self,
        case_payload: Mapping[str, Any],
        txn_ids: list[str],
        card_ids: list[str],
        device_ids: list[str],
        prior_case_ids: list[str],
    ) -> str:
        """Persist an agent case and its evidence edges, recording one tool call."""
        conn = self._ensure_conn()
        try:
            import pandas as pd
        except ImportError as exc:  # pragma: no cover - production environment has pandas
            raise RuntimeError("pandas is required for graph persistence") from exc
        payload = dict(case_payload)
        case_id = str(payload["case_id"])
        conn.upsertVertexDataFrame(pd.DataFrame([payload]), "AgentCase", v_id="case_id")
        frames: list[tuple[str, Any, str, str, dict[str, str]]] = []
        if txn_ids:
            frames.append(
                (
                    "AG_TXN",
                    pd.DataFrame({"from": [case_id] * len(txn_ids), "to": txn_ids}),
                    "Transaction",
                    "",
                    {},
                )
            )
        if card_ids:
            frames.append(
                ("AG_CARD", pd.DataFrame({"from": [case_id] * len(card_ids), "to": card_ids}), "Card", "", {})
            )
        if device_ids:
            frames.append(
                (
                    "AG_DEVICE",
                    pd.DataFrame({"from": [case_id] * len(device_ids), "to": device_ids}),
                    "DeviceProfile",
                    "",
                    {},
                )
            )
        for prior in prior_case_ids:
            frames.append(
                (
                    "AG_SIMILAR",
                    pd.DataFrame({"from": [case_id], "to": [prior], "score": [1.0]}),
                    "ClosedCase",
                    "score",
                    {"score": "score"},
                )
            )
        for etype, frame, target, _attribute_name, attributes in frames:
            conn.upsertEdgeDataFrame(
                frame,
                "AgentCase",
                etype,
                target,
                from_id="from",
                to_id="to",
                attributes=attributes,
            )
        self.calls.append({"query": "write_agent_case+edges", "params": {"case_id": case_id}})
        self.query_log.append(
            {"query": "write_agent_case+edges", "params": {"case_id": case_id}, "result": case_id}
        )
        return case_id


__all__ = ["Evidence"]
