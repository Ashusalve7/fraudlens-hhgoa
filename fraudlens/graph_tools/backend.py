"""Backends for the narrow FraudLens graph tool surface.

``TigerGraphBackend`` is the production adapter and only calls installed,
allow-listed queries.  ``LocalParquetBackend`` is intentionally explicit: it
is a deterministic test fixture over the generated parquet artifacts, not a
silent fallback for a production TigerGraph failure.
"""
from __future__ import annotations

import json
import os
import tempfile
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

try:
    from pipeline.embeddings import EMBEDDING_MODEL
except ImportError:  # pragma: no cover
    from ..pipeline.embeddings import EMBEDDING_MODEL

from .algorithms import connected_component, shortest_path, shared_neighbors
from .retrieval import case_provenance, search_policy

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LOAD = ROOT / "pipeline" / "out" / "load"
DEFAULT_OUT = ROOT / "pipeline" / "out"


class BackendError(RuntimeError):
    """An unavailable or invalid graph operation."""


def _safe(value: Any) -> Any:
    """Convert pandas/numpy values to JSON-safe values without secrets."""
    if value is None:
        return None
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if np.isnan(value) else float(value)
    if isinstance(value, (np.ndarray,)):
        return [_safe(item) for item in value.tolist()]
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat(sep=" ")
    if isinstance(value, dict):
        return {str(key): _safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_safe(item) for item in value]
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, float) and np.isnan(value):
        return None
    return value


def _as_id(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _normalise_datetime(value: Any) -> str:
    if value is None or str(value) == "":
        return "1970-01-01 00:00:00"
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return str(value).replace("T", " ")[:19]


def _rows(blocks: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    """Normalize pyTigerGraph result blocks to flat dictionaries."""
    for block in blocks or []:
        values = block.get(key) if isinstance(block, dict) else None
        if isinstance(values, dict):
            values = list(values.values())
        if not isinstance(values, list):
            continue
        result: list[dict[str, Any]] = []
        for row in values:
            if not isinstance(row, dict):
                continue
            attrs = row.get("attributes", row)
            if not isinstance(attrs, dict):
                attrs = {}
            flat = {
                str(key).split(".", 1)[-1] if str(key).startswith(f"{key}.") else str(attribute).split(".", 1)[-1]: _safe(value)
                for attribute, value in attrs.items()
            }
            # v_id is the most reliable ID, but some TigerGraph responses put
            # the primary ID only in attributes.
            if "id" not in flat and row.get("v_id") is not None:
                flat["id"] = _as_id(row.get("v_id"))
            result.append(flat)
        return result
    return []


def _first(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    return rows[0] if rows else None


def _record(row: dict[str, Any], identifier: str | None = None) -> dict[str, Any]:
    result = dict(row)
    if identifier and identifier not in result:
        result[identifier] = result.get("id", "")
    return _safe(result)


class TigerGraphBackend:
    """Production backend backed by a connected pyTigerGraph instance."""

    backend_name = "tigergraph"

    def __init__(self, conn: Any, graph_name: str = "FraudGraph") -> None:
        self.conn = conn
        self.graph_name = graph_name

    def _run(self, name: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        try:
            result = self.conn.runInstalledQuery(name, params or {})
        except Exception as exc:
            raise BackendError(f"installed query {name} failed: {exc}") from exc
        if not isinstance(result, list):
            raise BackendError(f"installed query {name} returned a non-list response")
        return result

    @staticmethod
    def _provenance(query: str, **extra: Any) -> dict[str, Any]:
        return {"backend": "TigerGraph", "query": query, **extra}

    def transaction_context(self, txn_id: str) -> dict[str, Any]:
        blocks = self._run("get_transaction_context", {"in_txn_id": str(txn_id)})
        txns = _rows(blocks, "S")
        cards = _rows(blocks, "Cards")
        customers = _rows(blocks, "Custs")
        devices = _rows(blocks, "Devices")
        return {
            "txn": _record(txns[0], "txn_id") if txns else None,
            "card": _record(cards[0], "card_id") if cards else None,
            "customer_id": customers[0].get("customer_id") if customers else None,
            "device": _record(devices[0], "device_id") if devices else None,
            "provenance": self._provenance("get_transaction_context", txn_id=str(txn_id)),
        }

    def card_window(self, card_id: str, start: str, end: str) -> list[dict[str, Any]]:
        blocks = self._run("get_card_window", {
            "in_card_id": str(card_id), "in_start": str(start), "in_end": str(end),
        })
        return [_record(row, "txn_id") for row in _rows(blocks, "T")]

    def customer_history(self, customer_id: str, start: str, end: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        blocks = self._run("get_customer_history", {
            "in_customer_id": str(customer_id), "in_start": str(start), "in_end": str(end),
        })
        return (
            [_record(row, "card_id") for row in _rows(blocks, "Cards")],
            [_record(row, "txn_id") for row in _rows(blocks, "T2")],
        )

    def device_neighborhood(self, device_id: str, start: str, end: str) -> dict[str, Any]:
        blocks = self._run("get_device_neighborhood", {
            "in_device_id": str(device_id), "in_start": str(start), "in_end": str(end),
        })
        return {
            "txns": [_record(row, "txn_id") for row in _rows(blocks, "T")],
            "cards": [_record(row, "card_id") for row in _rows(blocks, "Cards")],
            "customers": [_record(row, "customer_id") for row in _rows(blocks, "Custs")],
            "prior_cases": [_record(row, "case_id") for row in _rows(blocks, "Cases")],
            "provenance": self._provenance("get_device_neighborhood", device_id=str(device_id)),
        }

    def region_activity(self, card_id: str, region_id: str, start: str, end: str) -> list[dict[str, Any]]:
        blocks = self._run("get_region_activity", {
            "in_card_id": str(card_id), "in_region_id": str(region_id),
            "in_start": str(start), "in_end": str(end),
        })
        return [_record(row, "txn_id") for row in _rows(blocks, "T")]

    def similar_cases(self, pattern: str, exposure: float) -> list[dict[str, Any]]:
        # The installed query intentionally has a bounded pattern lookup; the
        # exact exposure ordering is applied locally without inventing rows.
        query_pattern = str(pattern or "none")
        blocks = self._run("find_similar_cases", {
            "in_pattern": query_pattern, "in_exposure_usd": float(exposure or 0),
        })
        rows = [case_provenance(row, source="TigerGraph:ClosedCase") for row in _rows(blocks, "S")]
        rows.sort(key=lambda row: abs(float(row.get("exposure_usd", 0)) - float(exposure or 0)))
        return rows

    def _ring_rows(self, blocks: list[dict[str, Any]], txn_id: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        specs = (
            ("SeedTxns", "Transaction", "txn_id"),
            ("Ring1Cards", "Card", "card_id"),
            ("Ring1Devices", "DeviceProfile", "device_id"),
            ("Ring1Customers", "Customer", "customer_id"),
            ("Ring2TxnsByDevice", "Transaction", "txn_id"),
            ("Ring2CardsByDevice", "Card", "card_id"),
            ("Ring2DevicesByCard", "DeviceProfile", "device_id"),
            ("Ring2TxnsByCard", "Transaction", "txn_id"),
            ("Ring2CustomersByCard", "Customer", "customer_id"),
            ("CasesByCard", "ClosedCase", "case_id"),
            ("CasesByDevice", "ClosedCase", "case_id"),
        )
        nodes: dict[str, dict[str, Any]] = {}

        def add(key: str, node_type: str, identifier: str, attrs: dict[str, Any]) -> None:
            node = {"type": node_type, "id": identifier, **attrs}
            nodes[f"{node_type}:{identifier}"] = node

        for key, node_type, id_field in specs:
            for row in _rows(blocks, key):
                identifier = _as_id(row.get(id_field) or row.get("id"))
                if identifier:
                    add(key, node_type, identifier, {k: v for k, v in row.items() if k not in {"id", id_field}})
        # The seed is the transaction whose ID was requested, not an arbitrary
        # first transaction in a result block.
        seed_nodes = [node for node in nodes.values() if node["type"] == "Transaction"]
        edges: list[dict[str, Any]] = []

        def edge(source_type: str, source: str, edge_type: str, target_type: str, target: str, **extra: Any) -> None:
            edges.append({
                "source_type": source_type, "source": source, "type": edge_type,
                "target_type": target_type, "target": target, **extra,
            })

        seed = next((node for node in seed_nodes if node["id"] == str(txn_id)), None)
        if seed is None and seed_nodes:
            # A malformed response must not silently relabel another
            # transaction as the requested seed.
            return list(nodes.values()), edges
        if seed is None:
            return list(nodes.values()), edges
        seed_id = seed["id"]
        for node in nodes.values():
            if node["type"] == "Card" and node["id"] in {
                str(row.get("id")) for row in _rows(blocks, "Ring1Cards")
            }:
                edge("Transaction", seed_id, "PAID_WITH", "Card", node["id"], relation="direct")
        device_ids = {
            _as_id(row.get("id")) for row in _rows(blocks, "Ring1Devices")
        }
        for device_id in device_ids:
            edge("Transaction", seed_id, "FROM_DEVICE", "DeviceProfile", device_id, relation="direct")
        for node in nodes.values():
            if node["type"] == "Transaction" and node["id"] != seed_id:
                # These are actual observed two-hop paths, not direct edges.
                for device_id in device_ids:
                    edge("Transaction", node["id"], "FROM_DEVICE", "DeviceProfile", device_id,
                         relation="observed_path", via_seed=seed_id)
                edge("Transaction", seed_id, "NEXT_TXN_OBSERVED", "Transaction", node["id"],
                     relation="observed_path", via="shared-device-or-card")
            elif node["type"] == "Card" and node["id"] not in {
                _as_id(row.get("id")) for row in _rows(blocks, "Ring1Cards")
            }:
                edge("Transaction", seed_id, "PAID_WITH_OBSERVED", "Card", node["id"],
                     relation="observed_path", via="shared-device")
            elif node["type"] == "DeviceProfile" and node["id"] not in device_ids:
                edge("Transaction", seed_id, "FROM_DEVICE_OBSERVED", "DeviceProfile", node["id"],
                     relation="observed_path", via="shared-card")
            elif node["type"] == "Customer":
                edge("Transaction", seed_id, "CUSTOMER_OBSERVED", "Customer", node["id"],
                     relation="observed_path", via="card-ownership")
            elif node["type"] == "ClosedCase":
                edge("Transaction", seed_id, "CASE_OBSERVED", "ClosedCase", node["id"],
                     relation="observed_path", via="card-or-device-case-link")
        return list(nodes.values()), edges

    def graph_ring(self, txn_id: str) -> dict[str, Any]:
        blocks = self._run("get_graph_ring", {"in_txn_id": str(txn_id)})
        nodes, edges = self._ring_rows(blocks, str(txn_id))
        seed_key = f"Transaction:{txn_id}"
        if not any(node.get("type") == "Transaction" and node.get("id") == str(txn_id) for node in nodes):
            raise BackendError(f"seed transaction {txn_id} was not returned by get_graph_ring")
        return {
            "algorithm": "bounded_graph_ring",
            "depth": 2,
            "truncated": True,
            "scope": "returned_relation_set",
            "nodes": nodes,
            "edges": edges,
            "seed": {"type": "Transaction", "id": str(txn_id)},
            "provenance": self._provenance("get_graph_ring", txn_id=str(txn_id), bounded_depth=2),
        }

    def graph_component(self, txn_id: str, target_type: str | None = None, target_id: str | None = None) -> dict[str, Any]:
        ring = self.graph_ring(txn_id)
        component = connected_component(ring["nodes"], ring["edges"], "Transaction", txn_id)
        component["truncated"] = bool(ring.get("truncated"))
        component["scope"] = ring.get("scope")
        component["ring_provenance"] = ring.get("provenance")
        if target_type and target_id:
            component["shortest_path"] = shortest_path(
                ring["nodes"], ring["edges"], "Transaction", txn_id, target_type, target_id
            )
        return component

    def shared_neighbors(self, txn_id: str) -> dict[str, Any]:
        blocks = self._run("get_shared_neighbors", {"in_txn_id": str(txn_id)})
        return {
            "transactions": [_record(row, "txn_id") for row in _rows(blocks, "SharedTxns")],
            "cards": [_record(row, "card_id") for row in _rows(blocks, "SharedCards")],
            "customers": [_record(row, "customer_id") for row in _rows(blocks, "SharedCustomers")],
            "provenance": self._provenance("get_shared_neighbors", txn_id=str(txn_id)),
        }

    def policy_retrieval(
        self,
        query: str,
        *,
        pattern: str = "",
        txn_id: str = "",
        card_id: str = "",
        customer_id: str = "",
        device_id: str = "",
        limit: int = 5,
    ) -> dict[str, Any]:
        context = {key: value for key, value in {
            "txn_id": txn_id, "card_id": card_id, "customer_id": customer_id, "device_id": device_id,
        }.items() if value}
        policy = search_policy(query, pattern=pattern, graph_context=context, limit=limit, out_dir=DEFAULT_OUT)
        cases: list[dict[str, Any]] = []
        case_error = None
        if txn_id or pattern:
            try:
                blocks = self._run("get_case_memory", {
                    "in_txn_id": str(txn_id), "in_pattern": str(pattern), "in_limit": int(limit),
                })
                for key in ("PatternCases", "CardCases", "DeviceCases"):
                    cases.extend(case_provenance(row, source=f"TigerGraph:{key}") for row in _rows(blocks, key))
            except BackendError as exc:
                case_error = str(exc)
        unique: dict[str, dict[str, Any]] = {}
        for case in sorted(cases, key=lambda item: item["case_id"]):
            unique.setdefault(case["case_id"], case)
        return {
            "policies": policy["items"],
            "cases": list(unique.values())[: int(limit)],
            "graph_context": context,
            "provenance": {
                "policy": policy["retrieval"],
                "cases": {"backend": "TigerGraph", "query": "get_case_memory", "error": case_error},
            },
        }

    def write_case(
        self,
        case_payload: dict[str, Any],
        txn_ids: list[str],
        card_ids: list[str],
        device_ids: list[str],
        prior_case_ids: list[str],
    ) -> dict[str, Any]:
        if not isinstance(case_payload, dict) or not case_payload.get("case_id"):
            raise BackendError("case_payload.case_id is required")
        payload = case_payload.get("case") if isinstance(case_payload.get("case"), dict) else case_payload
        case_id = str(case_payload.get("case_id") or payload.get("case_id"))
        answer = case_payload.get("answer", payload.get("answer_json", case_payload))
        if not isinstance(answer, str):
            answer = json.dumps(_safe(answer), sort_keys=True)
        vertex = {
            "case_id": case_id,
            "verdict": str(payload.get("verdict", "")),
            "pattern": str(payload.get("pattern", "")),
            "pattern_description": str(payload.get("pattern_description", "")),
            "fraud_probability": float(payload.get("fraud_probability", 0) or 0),
            "exposure_usd": float(payload.get("exposure_usd", 0) or 0),
            "status": str(payload.get("status", "")),
            "opened_at": _normalise_datetime(payload.get("opened_at")),
            "stop_reason": str(payload.get("stop_reason", "")),
            "summary": str(payload.get("summary", "")),
            "answer_json": answer,
        }
        frame = pd.DataFrame([vertex])
        try:
            self.conn.upsertVertexDataFrame(frame, "AgentCase", v_id="case_id")
            edge_specs = [
                ("AG_TXN", "Transaction", txn_ids, {}),
                ("AG_CARD", "Card", card_ids, {}),
                ("AG_DEVICE", "DeviceProfile", device_ids, {}),
            ]
            written: dict[str, int] = {}
            for edge_type, target_type, ids, attrs in edge_specs:
                ids = [str(value) for value in ids if str(value)]
                if not ids:
                    continue
                edge_frame = pd.DataFrame({"from": [case_id] * len(ids), "to": ids})
                if attrs:
                    for key in attrs:
                        edge_frame[key] = [attrs[key]] * len(ids)
                accepted = self.conn.upsertEdgeDataFrame(
                    edge_frame, "AgentCase", edge_type, target_type,
                    from_id="from", to_id="to", attributes={key: key for key in attrs},
                    vertexMustExist=True,
                )
                written[edge_type] = int(accepted or 0)
            prior_ids = [str(value) for value in prior_case_ids if str(value)]
            if prior_ids:
                edge_frame = pd.DataFrame({"from": [case_id] * len(prior_ids), "to": prior_ids, "score": [1.0] * len(prior_ids)})
                written["AG_SIMILAR"] = int(self.conn.upsertEdgeDataFrame(
                    edge_frame, "AgentCase", "AG_SIMILAR", "ClosedCase",
                    from_id="from", to_id="to", attributes={"score": "score"}, vertexMustExist=True,
                ) or 0)
        except Exception as exc:
            raise BackendError(f"case write failed for {case_id}: {exc}") from exc
        return {
            "case_id": case_id,
            "written_to_graph": True,
            "edge_rows": written,
            "provenance": {"backend": "TigerGraph", "vertex_type": "AgentCase"},
        }

    def read_case(self, case_id: str) -> dict[str, Any]:
        blocks = self._run("get_agent_case", {"in_case_id": str(case_id)})
        case = _first(_rows(blocks, "S"))
        if not case:
            return {"case_id": str(case_id), "found": False, "provenance": {"backend": "TigerGraph", "query": "get_agent_case"}}
        answer_json = case.get("answer_json", "")
        try:
            answer = json.loads(answer_json) if isinstance(answer_json, str) and answer_json else None
        except json.JSONDecodeError:
            answer = None
        return {
            "case_id": str(case_id),
            "found": True,
            "case": {key: _safe(value) for key, value in case.items()},
            "answer": answer,
            "txn_ids": [row.get("txn_id") for row in _rows(blocks, "Txns")],
            "card_ids": [row.get("card_id") for row in _rows(blocks, "Cards")],
            "device_ids": [row.get("device_id") for row in _rows(blocks, "Devices")],
            "prior_case_ids": [row.get("case_id") for row in _rows(blocks, "Priors")],
            "provenance": {"backend": "TigerGraph", "query": "get_agent_case"},
        }


class LocalParquetBackend:
    """Explicit deterministic backend for tests and offline demonstrations."""

    backend_name = "local-parquet-test"

    def __init__(
        self,
        load_dir: Path = DEFAULT_LOAD,
        out_dir: Path = DEFAULT_OUT,
        case_store_path: Path | None = None,
    ) -> None:
        self.load_dir = Path(load_dir)
        self.out_dir = Path(out_dir)
        self.case_store_path = Path(case_store_path) if case_store_path else None
        self._cache: dict[str, pd.DataFrame] = {}
        if self.case_store_path is None:
            raise BackendError(
                "LocalParquetBackend is test-only; pass case_store_path explicitly for case writes"
            )

    def _frame(self, name: str, columns: list[str] | None = None) -> pd.DataFrame:
        if name not in self._cache:
            path = self.load_dir / f"{name}.parquet"
            if not path.exists():
                raise BackendError(f"local test fixture is missing {path}")
            # Cache the complete frame.  Selecting columns from a previously
            # cached subset made later graph operations depend on call order.
            self._cache[name] = pd.read_parquet(path)
        frame = self._cache[name]
        return frame[columns] if columns else frame

    @staticmethod
    def _row(frame: pd.DataFrame, **filters: Any) -> dict[str, Any] | None:
        mask = pd.Series(True, index=frame.index)
        for column, value in filters.items():
            mask &= frame[column].astype(str) == str(value)
        selected = frame[mask]
        return _safe(selected.iloc[0].to_dict()) if len(selected) else None

    @staticmethod
    def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
        return [_safe(record) for record in frame.to_dict(orient="records")]

    def _info(self, source: str) -> dict[str, Any]:
        return {"backend": self.backend_name, "source": source, "remote": False}

    def transaction_context(self, txn_id: str) -> dict[str, Any]:
        txn = self._row(self._frame("v_Transaction"), txn_id=str(txn_id))
        card_id = str(txn.get("card_id", "")) if txn and "card_id" in txn else ""
        # v_Transaction intentionally does not duplicate card_id; resolve it
        # from the edge frame so the offline result matches the graph contract.
        paid = self._frame("e_PAID_WITH")
        edge = self._row(paid, **{"from": str(txn_id)})
        card_id = str(edge.get("card_id", "")) if edge else ""
        card = self._row(self._frame("v_Card"), card_id=card_id) if card_id else None
        device = None
        customer = None
        device_edge = self._row(self._frame("e_FROM_DEVICE"), **{"from": str(txn_id)})
        if device_edge:
            device = self._row(self._frame("v_DeviceProfile"), device_id=str(device_edge["device_id"]))
        if card_id:
            owns = self._row(self._frame("e_OWNS_CARD"), card_id=card_id)
            if owns:
                customer = self._row(self._frame("v_Customer"), customer_id=str(owns["customer_id"]))
        return {
            "txn": txn,
            "card": card,
            "customer_id": customer.get("customer_id") if customer else None,
            "device": device,
            "provenance": self._info("v_Transaction + e_PAID_WITH/e_FROM_DEVICE/e_OWNS_CARD"),
        }

    def _window(self, frame: pd.DataFrame, start: str, end: str) -> pd.DataFrame:
        values = pd.to_datetime(frame["ts"], errors="coerce")
        start_ts, end_ts = pd.to_datetime(start), pd.to_datetime(end)
        return frame[(values >= start_ts) & (values <= end_ts)].sort_values("ts", kind="stable")

    def card_window(self, card_id: str, start: str, end: str) -> list[dict[str, Any]]:
        ids = set(self._frame("e_PAID_WITH").query("card_id == @card_id")["from"].astype(str))
        frame = self._frame("v_Transaction")
        return self._records(self._window(frame[frame["txn_id"].astype(str).isin(ids)], start, end))

    def customer_history(self, customer_id: str, start: str, end: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        owns = self._frame("e_OWNS_CARD")
        cards = self._records(self._frame("v_Card")[self._frame("v_Card")["card_id"].isin(owns.loc[owns["customer_id"].astype(str) == str(customer_id), "card_id"].astype(str))])
        ids = set(owns.loc[owns["customer_id"].astype(str) == str(customer_id), "card_id"].astype(str))
        paid = self._frame("e_PAID_WITH")
        txn_ids = set(paid.loc[paid["card_id"].astype(str).isin(ids), "from"].astype(str))
        txns = self._records(self._window(self._frame("v_Transaction")[self._frame("v_Transaction")["txn_id"].astype(str).isin(txn_ids)], start, end))
        return cards, txns

    def device_neighborhood(self, device_id: str, start: str, end: str) -> dict[str, Any]:
        edge = self._frame("e_FROM_DEVICE")
        ids = set(edge.loc[edge["device_id"].astype(str) == str(device_id), "from"].astype(str))
        txns = self._window(self._frame("v_Transaction")[self._frame("v_Transaction")["txn_id"].astype(str).isin(ids)], start, end)
        paid = self._frame("e_PAID_WITH")
        cards = set(paid.loc[paid["from"].astype(str).isin(ids), "card_id"].astype(str))
        owns = self._frame("e_OWNS_CARD")
        customers = set(owns.loc[owns["card_id"].astype(str).isin(cards), "customer_id"].astype(str))
        cases = self._frame("e_CASE_DEVICE")
        prior = self._frame("v_ClosedCase")
        prior = prior[prior["case_id"].astype(str).isin(cases.loc[cases["device_id"].astype(str) == str(device_id), "case_id"].astype(str))]
        return {
            "txns": self._records(txns), "cards": self._records(self._frame("v_Card")[self._frame("v_Card")["card_id"].astype(str).isin(cards)]),
            "customers": self._records(self._frame("v_Customer")[self._frame("v_Customer")["customer_id"].astype(str).isin(customers)]),
            "prior_cases": self._records(prior), "provenance": self._info("e_FROM_DEVICE + linked graph frames"),
        }

    def region_activity(self, card_id: str, region_id: str, start: str, end: str) -> list[dict[str, Any]]:
        rows = self.card_window(card_id, start, end)
        return [row for row in rows if str(row.get("addr1", "")) == str(region_id)]

    def similar_cases(self, pattern: str, exposure: float) -> list[dict[str, Any]]:
        frame = self._frame("v_ClosedCase")
        frame = frame[(frame["pattern"].astype(str) == str(pattern)) & (frame["outcome"].astype(str) == "confirmed_fraud")]
        rows = [case_provenance(row, source=str(self.load_dir / "v_ClosedCase.parquet")) for row in self._records(frame)]
        rows.sort(key=lambda row: abs(float(row.get("exposure_usd", 0)) - float(exposure or 0)))
        return rows

    def _graph_edges(self) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
        edge_specs = (
            ("e_PAID_WITH", "Transaction", "from", "Card", "card_id", "PAID_WITH"),
            ("e_FROM_DEVICE", "Transaction", "from", "DeviceProfile", "device_id", "FROM_DEVICE"),
            ("e_OWNS_CARD", "Customer", "customer_id", "Card", "card_id", "OWNS_CARD"),
            ("e_CASE_TXN", "ClosedCase", "case_id", "Transaction", "txn_id", "CASE_TXN"),
            ("e_CASE_CARD", "ClosedCase", "case_id", "Card", "card_id", "CASE_CARD"),
            ("e_CASE_DEVICE", "ClosedCase", "case_id", "DeviceProfile", "device_id", "CASE_DEVICE"),
        )
        edges: list[dict[str, Any]] = []
        for name, source_type, source_col, target_type, target_col, edge_type in edge_specs:
            frame = self._frame(name, [source_col, target_col])
            for row in frame.to_dict(orient="records"):
                edges.append({
                    "source_type": source_type, "source": _as_id(row.get(source_col)),
                    "type": edge_type, "target_type": target_type, "target": _as_id(row.get(target_col)),
                    "relation": "direct",
                })
        node_frames = {
            "Transaction": self._frame("v_Transaction", ["txn_id"]),
            "Card": self._frame("v_Card", ["card_id"]),
            "DeviceProfile": self._frame("v_DeviceProfile", ["device_id"]),
            "Customer": self._frame("v_Customer", ["customer_id"]),
            "ClosedCase": self._frame("v_ClosedCase", ["case_id"]),
        }
        id_columns = {"Transaction": "txn_id", "Card": "card_id", "DeviceProfile": "device_id", "Customer": "customer_id", "ClosedCase": "case_id"}
        nodes: dict[str, dict[str, Any]] = {}
        for node_type, frame in node_frames.items():
            id_col = id_columns[node_type]
            for row in frame.to_dict(orient="records"):
                identifier = _as_id(row.get(id_col))
                nodes[f"{node_type}:{identifier}"] = {"type": node_type, "id": identifier}
        return edges, nodes

    def graph_ring(self, txn_id: str, max_nodes: int = 5000) -> dict[str, Any]:
        all_edges, all_nodes = self._graph_edges()
        adjacency: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for edge in all_edges:
            left = f"{edge['source_type']}:{edge['source']}"
            right = f"{edge['target_type']}:{edge['target']}"
            adjacency[left].append(edge)
            adjacency[right].append(edge)
        seed = f"Transaction:{txn_id}"
        if seed not in all_nodes:
            raise BackendError(f"seed transaction {txn_id} is not in local fixtures")
        visited = {seed}
        frontier = {seed}
        truncated = False
        for _ in range(2):
            next_frontier: set[str] = set()
            for key in sorted(frontier):
                for edge in adjacency.get(key, []):
                    other = f"{edge['target_type']}:{edge['target']}" if edge["source_type"] + ":" + edge["source"] == key else f"{edge['source_type']}:{edge['source']}"
                    if other not in visited:
                        visited.add(other)
                        next_frontier.add(other)
                        if len(visited) >= max_nodes:
                            truncated = True
                            break
                if truncated:
                    break
            frontier = next_frontier
            if truncated:
                break
        nodes = [all_nodes[key] for key in sorted(visited) if key in all_nodes]
        edges = [
            edge for edge in all_edges
            if f"{edge['source_type']}:{edge['source']}" in visited and f"{edge['target_type']}:{edge['target']}" in visited
        ]
        return {
            "algorithm": "bounded_graph_ring", "depth": 2, "truncated": truncated,
            "scope": "returned_relation_set", "nodes": nodes, "edges": edges,
            "seed": {"type": "Transaction", "id": str(txn_id)},
            "provenance": self._info("full generated parquet relation set, depth <= 2"),
        }

    def graph_component(self, txn_id: str, target_type: str | None = None, target_id: str | None = None) -> dict[str, Any]:
        ring = self.graph_ring(txn_id)
        result = connected_component(ring["nodes"], ring["edges"], "Transaction", txn_id)
        result["truncated"] = ring["truncated"]
        result["scope"] = ring["scope"]
        if target_type and target_id:
            result["shortest_path"] = shortest_path(ring["nodes"], ring["edges"], "Transaction", txn_id, target_type, target_id)
        return result

    def shared_neighbors(self, txn_id: str) -> dict[str, Any]:
        context = self.transaction_context(txn_id)
        device_id = (context.get("device") or {}).get("device_id")
        if not device_id:
            return {"transactions": [], "cards": [], "customers": [], "provenance": self._info("no device edge")}
        neighborhood = self.device_neighborhood(str(device_id), "1900-01-01", "2100-01-01")
        return {
            "transactions": neighborhood["txns"], "cards": neighborhood["cards"],
            "customers": neighborhood["customers"],
            "provenance": self._info("shared FROM_DEVICE neighbors"),
        }

    def policy_retrieval(
        self,
        query: str,
        *,
        pattern: str = "",
        txn_id: str = "",
        card_id: str = "",
        customer_id: str = "",
        device_id: str = "",
        limit: int = 5,
    ) -> dict[str, Any]:
        context = {key: value for key, value in {"txn_id": txn_id, "card_id": card_id, "customer_id": customer_id, "device_id": device_id}.items() if value}
        policies = search_policy(query, pattern=pattern, graph_context=context, limit=limit, out_dir=self.out_dir)
        cases: list[dict[str, Any]] = []
        closed = self._frame("v_ClosedCase")
        if pattern:
            cases.extend(case_provenance(row, source=str(self.load_dir / "v_ClosedCase.parquet")) for row in self._records(closed[closed["pattern"].astype(str) == str(pattern)]))
        if card_id:
            edge = self._frame("e_CASE_CARD")
            ids = set(edge.loc[edge["card_id"].astype(str) == str(card_id), "case_id"].astype(str))
            cases.extend(case_provenance(row, source=str(self.load_dir / "v_ClosedCase.parquet")) for row in self._records(closed[closed["case_id"].astype(str).isin(ids)]))
        if device_id:
            edge = self._frame("e_CASE_DEVICE")
            ids = set(edge.loc[edge["device_id"].astype(str) == str(device_id), "case_id"].astype(str))
            cases.extend(case_provenance(row, source=str(self.load_dir / "v_ClosedCase.parquet")) for row in self._records(closed[closed["case_id"].astype(str).isin(ids)]))
        unique = {str(case["case_id"]): case for case in sorted(cases, key=lambda item: item["case_id"])}
        return {
            "policies": policies["items"], "cases": list(unique.values())[: int(limit)],
            "graph_context": context,
            "provenance": {
                "policy": policies["retrieval"],
                "cases": {"backend": self.backend_name, "source": str(self.load_dir / "v_ClosedCase.parquet"), "remote": False},
            },
        }

    def _read_store(self) -> dict[str, Any]:
        if not self.case_store_path or not self.case_store_path.exists():
            return {}
        try:
            value = json.loads(self.case_store_path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, json.JSONDecodeError) as exc:
            raise BackendError(f"local test case store is invalid: {exc}") from exc

    def _write_store(self, value: dict[str, Any]) -> None:
        assert self.case_store_path is not None
        self.case_store_path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix="fraudlens-case-", suffix=".json", dir=self.case_store_path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(value, handle, indent=2, sort_keys=True, default=str)
            os.replace(temporary, self.case_store_path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def write_case(self, case_payload: dict[str, Any], txn_ids: list[str], card_ids: list[str], device_ids: list[str], prior_case_ids: list[str]) -> dict[str, Any]:
        if not isinstance(case_payload, dict) or not case_payload.get("case_id"):
            raise BackendError("case_payload.case_id is required")
        case_id = str(case_payload["case_id"])
        store = self._read_store()
        store[case_id] = {
            "case": _safe(case_payload), "txn_ids": [str(value) for value in txn_ids],
            "card_ids": [str(value) for value in card_ids], "device_ids": [str(value) for value in device_ids],
            "prior_case_ids": [str(value) for value in prior_case_ids], "backend": self.backend_name,
        }
        self._write_store(store)
        return {"case_id": case_id, "written_to_graph": False, "test_store": str(self.case_store_path), "edge_rows": {}, "provenance": {"backend": self.backend_name, "remote": False}}

    def read_case(self, case_id: str) -> dict[str, Any]:
        value = self._read_store().get(str(case_id))
        if value is None:
            return {"case_id": str(case_id), "found": False, "provenance": {"backend": self.backend_name, "remote": False}}
        return {"case_id": str(case_id), "found": True, **value, "provenance": {"backend": self.backend_name, "remote": False}}


def make_production_backend() -> TigerGraphBackend:
    """Create the production backend; never silently falls back to parquet."""
    try:
        from pipeline.tg import get_conn
    except ImportError:  # pragma: no cover
        from ..pipeline.tg import get_conn
    import os
    return TigerGraphBackend(get_conn(), os.environ.get("TG_GRAPHNAME", "FraudGraph"))
