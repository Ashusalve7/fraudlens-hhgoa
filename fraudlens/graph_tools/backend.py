"""Backends for the narrow FraudLens graph tool surface.

``TigerGraphBackend`` is the production adapter and only calls installed,
allow-listed queries.  ``LocalParquetBackend`` is intentionally explicit: it
is a deterministic test fixture over the generated parquet artifacts, not a
silent fallback for a production TigerGraph failure.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

try:
    from pipeline.embeddings import EMBEDDING_DIM, embed_text
except ImportError:  # pragma: no cover - package import path
    from ..pipeline.embeddings import EMBEDDING_DIM, embed_text

from .algorithms import connected_component, shortest_path
from .retrieval import case_provenance, rank_policy_chunks, search_policy

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


def _rows(blocks: Any, key: str) -> list[dict[str, Any]]:
    """Normalize pyTigerGraph result blocks to flat dictionaries."""
    block_values = [blocks] if isinstance(blocks, dict) else blocks
    for block in block_values or []:
        if not isinstance(block, dict):
            continue
        values = block.get(key)
        if isinstance(values, dict):
            # Attribute projections may be returned as {attribute: [values]}.
            lengths = {len(value) for value in values.values() if isinstance(value, list)}
            if len(lengths) == 1:
                count = next(iter(lengths))
                values = [
                    {attribute: items[index] for attribute, items in values.items() if isinstance(items, list)}
                    for index in range(count)
                ]
            else:
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
                str(attribute).split(".", 1)[-1]: _safe(value)
                for attribute, value in attrs.items()
            }
            if "id" not in flat and row.get("v_id") is not None:
                flat["id"] = _as_id(row.get("v_id"))
            result.append(flat)
        return result
    return []


def _first(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    return rows[0] if rows else None


def _record(row: dict[str, Any], identifier: str | None = None) -> dict[str, Any]:
    result = dict(row)
    if identifier:
        if not result.get(identifier):
            result[identifier] = _as_id(result.get("id"))
        result.pop("id", None)
    return _safe(result)


def _row_identifier(row: dict[str, Any], identifier: str) -> str:
    return _as_id(row.get(identifier) or row.get("id"))


def _unique_ids(values: Any) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        identifier = _as_id(value).strip()
        if identifier and identifier not in seen:
            seen.add(identifier)
            result.append(identifier)
    return result


def _timestamp(value: Any, name: str) -> pd.Timestamp:
    try:
        result = pd.to_datetime(value, errors="raise")
    except (TypeError, ValueError) as exc:
        raise BackendError(f"{name} is not a valid datetime: {value!r}") from exc
    if result.tzinfo is not None:
        result = result.tz_convert("UTC").tz_localize(None)
    return result


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
            [_record(row, "txn_id") for row in (_rows(blocks, "T") or _rows(blocks, "T2"))],
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
                identifier = _row_identifier(row, id_field)
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
        ring1_card_ids = {
            _row_identifier(row, "card_id")
            for row in _rows(blocks, "Ring1Cards")
            if _row_identifier(row, "card_id")
        }
        ring1_device_ids = {
            _row_identifier(row, "device_id")
            for row in _rows(blocks, "Ring1Devices")
            if _row_identifier(row, "device_id")
        }
        case_card_ids = {
            _row_identifier(row, "case_id")
            for row in _rows(blocks, "CasesByCard")
            if _row_identifier(row, "case_id")
        }
        case_device_ids = {
            _row_identifier(row, "case_id")
            for row in _rows(blocks, "CasesByDevice")
            if _row_identifier(row, "case_id")
        }
        for node in nodes.values():
            if node["type"] == "Card" and node["id"] in ring1_card_ids:
                edge("Transaction", seed_id, "PAID_WITH", "Card", node["id"], relation="direct")
        device_ids = ring1_device_ids
        for device_id in device_ids:
            edge("Transaction", seed_id, "FROM_DEVICE", "DeviceProfile", device_id, relation="direct")
        for node in nodes.values():
            if node["type"] == "Transaction" and node["id"] != seed_id:
                # These are actual observed two-hop paths, not direct edges.
                for device_id in device_ids:
                    edge(
                        "Transaction",
                        node["id"],
                        "FROM_DEVICE",
                        "DeviceProfile",
                        device_id,
                        relation="observed_path",
                        via_seed=seed_id,
                    )
                for card_id in ring1_card_ids:
                    if any(
                        _row_identifier(row, "txn_id") == node["id"]
                        for row in _rows(blocks, "Ring2TxnsByCard")
                    ):
                        edge(
                            "Transaction",
                            node["id"],
                            "PAID_WITH",
                            "Card",
                            card_id,
                            relation="observed_path",
                            via_seed=seed_id,
                        )
            elif node["type"] == "Card" and node["id"] not in ring1_card_ids:
                edge(
                    "Transaction",
                    seed_id,
                    "SHARED_DEVICE_PATH",
                    "Card",
                    node["id"],
                    relation="observed_path",
                    via="shared-device",
                    schema_edge=False,
                )
            elif node["type"] == "DeviceProfile" and node["id"] not in device_ids:
                edge(
                    "Transaction",
                    seed_id,
                    "SHARED_CARD_PATH",
                    "DeviceProfile",
                    node["id"],
                    relation="observed_path",
                    via="shared-card",
                    schema_edge=False,
                )
            elif node["type"] == "Customer":
                for card_id in ring1_card_ids:
                    edge(
                        "Card",
                        card_id,
                        "OWNS_CARD",
                        "Customer",
                        node["id"],
                        relation="observed_path",
                        via_seed=seed_id,
                    )
            elif node["type"] == "ClosedCase":
                if node["id"] in case_card_ids:
                    for card_id in ring1_card_ids:
                        edge(
                            "Card",
                            card_id,
                            "CASE_CARD",
                            "ClosedCase",
                            node["id"],
                            relation="observed_path",
                            via_seed=seed_id,
                        )
                if node["id"] in case_device_ids:
                    for device_id in device_ids:
                        edge(
                            "DeviceProfile",
                            device_id,
                            "CASE_DEVICE",
                            "ClosedCase",
                            node["id"],
                            relation="observed_path",
                            via_seed=seed_id,
                        )
        nodes = sorted(nodes.values(), key=lambda node: (node["type"], node["id"]))
        edges = sorted(
            edges,
            key=lambda edge: (
                edge["source_type"],
                edge["source"],
                edge["type"],
                edge["target_type"],
                edge["target"],
            ),
        )
        return nodes, edges

    def graph_ring(self, txn_id: str) -> dict[str, Any]:
        blocks = self._run("get_graph_ring", {"in_txn_id": str(txn_id)})
        nodes, edges = self._ring_rows(blocks, str(txn_id))
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
        devices = _rows(blocks, "SharedDevices")
        return {
            "device_id": devices[0].get("device_id") if devices else None,
            "transactions": [
                _record(row, "txn_id")
                for row in _rows(blocks, "SharedTxns")
                if _row_identifier(row, "txn_id") != str(txn_id)
            ],
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
        limit = int(limit)
        if limit < 1 or limit > 50:
            raise BackendError("limit must be between 1 and 50")
        context = {
            key: value
            for key, value in {
                "txn_id": txn_id,
                "card_id": card_id,
                "customer_id": customer_id,
                "device_id": device_id,
            }.items()
            if value
        }
        policy_error: str | None = None
        try:
            policy_blocks = self._run("get_policy_chunks", {})
            policy_rows = [_record(row, "chunk_id") for row in _rows(policy_blocks, "P")]
            if not policy_rows:
                raise BackendError("get_policy_chunks returned no PolicyChunk rows")
            remote_frame = pd.DataFrame(policy_rows)
            policy_frame = remote_frame
            provenance_kind = "graph_policychunk_text"
            rich_path = DEFAULT_OUT / "policy_chunks.parquet"
            if rich_path.exists():
                rich = pd.read_parquet(rich_path)
                required_rich = {"chunk_id", "content_hash", "text"}
                if required_rich.issubset(rich.columns):
                    rich = rich.copy()
                    rich["chunk_id"] = rich["chunk_id"].astype(str)
                    rich["content_hash"] = rich["content_hash"].astype(str)
                    rich["text"] = rich["text"].astype(str)
                    graph_hashes = {
                        str(row["chunk_id"]): hashlib.sha256(
                            str(row["text"]).encode("utf-8")
                        ).hexdigest()
                        for row in remote_frame.to_dict(orient="records")
                    }
                    rich_index = rich.set_index("chunk_id", drop=False)
                    if all(
                        chunk_id in rich_index.index
                        and str(rich_index.at[chunk_id, "content_hash"]) == content_hash
                        for chunk_id, content_hash in graph_hashes.items()
                    ):
                        policy_frame = rich[
                            rich["chunk_id"].isin(graph_hashes)
                        ].reset_index(drop=True)
                        provenance_kind = "graph_policychunk_text+hash_verified_local_provenance"
            policy_vectors = (
                np.vstack([embed_text(text) for text in policy_frame["text"].astype(str)])
                if len(policy_frame)
                else np.zeros((0, EMBEDDING_DIM), dtype=np.float32)
            )
            policy = rank_policy_chunks(
                query,
                policy_frame,
                policy_vectors,
                pattern=pattern,
                graph_context=context,
                limit=limit,
                index_info={
                    "available": True,
                    "source": "TigerGraph:PolicyChunk",
                    "source_kind": provenance_kind,
                    "vector_source": "embedded_locally_from_hash_verified_graph_text",
                    "count": int(len(policy_frame)),
                    "remote": True,
                },
            )
        except BackendError as exc:
            policy_error = str(exc)
            policy = search_policy(
                query,
                pattern=pattern,
                graph_context=context,
                limit=limit,
                out_dir=DEFAULT_OUT,
            )
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
            if case.get("case_id"):
                unique.setdefault(str(case["case_id"]), case)
        return {
            "policies": policy["items"],
            "cases": list(unique.values())[: int(limit)],
            "graph_context": context,
            "provenance": {
                "policy": policy["retrieval"],
                "policy_graph_error": policy_error,
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
        prior_case_scores: dict[str, float] | None = None,
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
            replaced: dict[str, int] = {}
            delete_edges = getattr(self.conn, "delEdges", None)
            for edge_type, target_type, _raw_ids, _attrs in edge_specs:
                if callable(delete_edges):
                    result = delete_edges("AgentCase", case_id, edge_type, target_type)
                    replaced[edge_type] = sum(
                        int(value) for value in (result or {}).values() if str(value).isdigit()
                    )
            for edge_type, target_type, raw_ids, attrs in edge_specs:
                ids = _unique_ids(raw_ids)
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
            score_by_id: dict[str, float] = {}
            for key, value in (prior_case_scores or {}).items():
                identifier = _as_id(key).strip()
                if not identifier:
                    continue
                try:
                    score = float(value)
                except (TypeError, ValueError):
                    continue
                if math.isfinite(score):
                    score_by_id[identifier] = score
            prior_ids = [
                value
                for value in _unique_ids(prior_case_ids)
                if value in score_by_id
            ]
            if callable(delete_edges):
                result = delete_edges("AgentCase", case_id, "AG_SIMILAR", "ClosedCase")
                replaced["AG_SIMILAR"] = sum(
                    int(value) for value in (result or {}).values() if str(value).isdigit()
                )
            if prior_ids:
                edge_frame = pd.DataFrame({
                    "from": [case_id] * len(prior_ids),
                    "to": prior_ids,
                    "score": [score_by_id[value] for value in prior_ids],
                })
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
            "replaced_edge_rows": replaced,
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
            "txn_ids": _unique_ids(row.get("txn_id") for row in _rows(blocks, "Txns")),
            "card_ids": _unique_ids(row.get("card_id") for row in _rows(blocks, "Cards")),
            "device_ids": _unique_ids(row.get("device_id") for row in _rows(blocks, "Devices")),
            "prior_case_ids": _unique_ids(row.get("case_id") for row in _rows(blocks, "Priors")),
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

    def _frame(self, name: str, columns: list[str] | None = None) -> pd.DataFrame:
        if name not in self._cache:
            path = self.load_dir / f"{name}.parquet"
            if not path.exists():
                raise BackendError(f"local test fixture is missing {path}")
            # Cache the complete frame.  Selecting columns from a previously
            # cached subset made later graph operations depend on call order.
            self._cache[name] = pd.read_parquet(path)
        frame = self._cache[name]
        if columns:
            missing = sorted(set(columns) - set(frame.columns))
            if missing:
                raise BackendError(f"local fixture {name}.parquet is missing columns: {missing}")
            return frame[columns]
        return frame

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
        values = pd.to_datetime(frame["ts"], errors="coerce", utc=True).dt.tz_localize(None)
        start_ts, end_ts = _timestamp(start, "start"), _timestamp(end, "end")
        if start_ts > end_ts:
            raise BackendError("start must not be after end")
        return frame[(values >= start_ts) & (values <= end_ts)].sort_values("ts", kind="stable")

    def card_window(self, card_id: str, start: str, end: str) -> list[dict[str, Any]]:
        paid = self._frame("e_PAID_WITH")
        ids = set(paid.loc[paid["card_id"].astype(str) == str(card_id), "from"].astype(str))
        frame = self._frame("v_Transaction")
        return self._records(self._window(frame[frame["txn_id"].astype(str).isin(ids)], start, end))

    def customer_history(self, customer_id: str, start: str, end: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        owns = self._frame("e_OWNS_CARD")
        ids = set(
            owns.loc[
                owns["customer_id"].astype(str) == str(customer_id),
                "card_id",
            ].astype(str)
        )
        card_frame = self._frame("v_Card")
        cards = self._records(card_frame[card_frame["card_id"].astype(str).isin(ids)])
        paid = self._frame("e_PAID_WITH")
        txn_ids = set(paid.loc[paid["card_id"].astype(str).isin(ids), "from"].astype(str))
        txn_frame = self._frame("v_Transaction")
        txns = self._records(
            self._window(txn_frame[txn_frame["txn_id"].astype(str).isin(txn_ids)], start, end)
        )
        return cards, txns

    def device_neighborhood(self, device_id: str, start: str, end: str) -> dict[str, Any]:
        edge = self._frame("e_FROM_DEVICE")
        all_ids = set(
            edge.loc[edge["device_id"].astype(str) == str(device_id), "from"].astype(str)
        )
        txn_frame = self._frame("v_Transaction")
        txns = self._window(
            txn_frame[txn_frame["txn_id"].astype(str).isin(all_ids)], start, end
        )
        window_ids = set(txns["txn_id"].astype(str))
        paid = self._frame("e_PAID_WITH")
        cards = set(
            paid.loc[paid["from"].astype(str).isin(window_ids), "card_id"].astype(str)
        )
        owns = self._frame("e_OWNS_CARD")
        customers = set(
            owns.loc[owns["card_id"].astype(str).isin(cards), "customer_id"].astype(str)
        )
        cases = self._frame("e_CASE_DEVICE")
        case_ids = set(
            cases.loc[
                cases["device_id"].astype(str) == str(device_id),
                "case_id",
            ].astype(str)
        )
        prior = self._frame("v_ClosedCase")
        prior = prior[prior["case_id"].astype(str).isin(case_ids)].copy()
        if "opened_at" in prior:
            opened = pd.to_datetime(prior["opened_at"], errors="coerce", utc=True).dt.tz_localize(None)
            prior = prior[opened <= _timestamp(end, "end")]
            prior = prior.sort_values("opened_at", ascending=False, kind="stable").head(200)
        card_frame = self._frame("v_Card")
        customer_frame = self._frame("v_Customer")
        return {
            "txns": self._records(txns),
            "cards": self._records(
                card_frame[card_frame["card_id"].astype(str).isin(cards)]
            ),
            "customers": self._records(
                customer_frame[customer_frame["customer_id"].astype(str).isin(customers)]
            ),
            "prior_cases": self._records(prior),
            "provenance": self._info(
                "e_FROM_DEVICE + time-filtered linked frames + CASE_DEVICE prior memory"
            ),
        }

    def region_activity(self, card_id: str, region_id: str, start: str, end: str) -> list[dict[str, Any]]:
        rows = self.card_window(card_id, start, end)
        if not rows:
            return []
        billed = self._frame("e_BILLED_IN")
        txn_ids = set(
            billed.loc[
                billed["region_id"].astype(str) == str(region_id),
                "from",
            ].astype(str)
        )
        return [row for row in rows if str(row.get("txn_id", "")) in txn_ids]

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
            ("e_CASE_CONN_CARD", "ClosedCase", "case_id", "Card", "card_id", "CASE_CONN_CARD"),
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
            "Transaction": self._frame("v_Transaction"),
            "Card": self._frame("v_Card"),
            "DeviceProfile": self._frame("v_DeviceProfile"),
            "Customer": self._frame("v_Customer"),
            "ClosedCase": self._frame("v_ClosedCase"),
        }
        id_columns = {"Transaction": "txn_id", "Card": "card_id", "DeviceProfile": "device_id", "Customer": "customer_id", "ClosedCase": "case_id"}
        nodes: dict[str, dict[str, Any]] = {}
        for node_type, frame in node_frames.items():
            id_col = id_columns[node_type]
            for row in frame.to_dict(orient="records"):
                identifier = _as_id(row.get(id_col))
                node = _safe(row)
                node.update({"type": node_type, "id": identifier})
                nodes[f"{node_type}:{identifier}"] = node
        return edges, nodes

    def graph_ring(self, txn_id: str, max_nodes: int = 5000) -> dict[str, Any]:
        max_nodes = int(max_nodes)
        if max_nodes < 1 or max_nodes > 100_000:
            raise BackendError("max_nodes must be between 1 and 100000")
        all_edges, all_nodes = self._graph_edges()
        adjacency: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for edge in all_edges:
            left = f"{edge['source_type']}:{edge['source']}"
            right = f"{edge['target_type']}:{edge['target']}"
            if left in all_nodes and right in all_nodes:
                adjacency[left].append(edge)
                adjacency[right].append(edge)
        for key in adjacency:
            adjacency[key].sort(
                key=lambda edge: (
                    str(edge.get("type", "")),
                    str(edge.get("target_type", "")),
                    str(edge.get("target", "")),
                )
            )
        seed = f"Transaction:{txn_id}"
        if seed not in all_nodes:
            raise BackendError(f"seed transaction {txn_id} is not in local fixtures")
        visited = {seed}
        frontier = {seed}
        truncated = False
        for _ in range(2):
            candidates: set[str] = set()
            for key in sorted(frontier):
                for edge in adjacency.get(key, []):
                    left = f"{edge['source_type']}:{edge['source']}"
                    other = f"{edge['target_type']}:{edge['target']}" if left == key else left
                    if other and other in all_nodes and other not in visited:
                        candidates.add(other)
            if not candidates:
                break
            ordered = sorted(candidates)
            capacity = max_nodes - len(visited)
            if len(ordered) > capacity:
                ordered = ordered[:capacity]
                truncated = True
            visited.update(ordered)
            frontier = set(ordered)
            if truncated:
                break
        nodes = [all_nodes[key] for key in sorted(visited)]
        edges = [
            edge
            for edge in all_edges
            if f"{edge['source_type']}:{edge['source']}" in visited
            and f"{edge['target_type']}:{edge['target']}" in visited
        ]
        return {
            "algorithm": "bounded_graph_ring",
            "depth": 2,
            "truncated": truncated,
            "scope": "returned_relation_set",
            "nodes": nodes,
            "edges": edges,
            "seed": {"type": "Transaction", "id": str(txn_id)},
            "provenance": self._info("generated parquet relation set, undirected depth <= 2"),
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
            return {
                "device_id": None,
                "transactions": [],
                "cards": [],
                "customers": [],
                "provenance": self._info("no observed device edge"),
            }
        neighborhood = self.device_neighborhood(str(device_id), "1900-01-01", "2100-01-01")
        transactions = [
            row
            for row in neighborhood["txns"]
            if str(row.get("txn_id", "")) != str(txn_id)
        ]
        other_ids = {str(row["txn_id"]) for row in transactions}
        paid = self._frame("e_PAID_WITH")
        card_ids = set(
            paid.loc[paid["from"].astype(str).isin(other_ids), "card_id"].astype(str)
        )
        owns = self._frame("e_OWNS_CARD")
        customer_ids = set(
            owns.loc[owns["card_id"].astype(str).isin(card_ids), "customer_id"].astype(str)
        )
        card_frame = self._frame("v_Card")
        customer_frame = self._frame("v_Customer")
        return {
            "device_id": str(device_id),
            "transactions": transactions,
            "cards": self._records(
                card_frame[card_frame["card_id"].astype(str).isin(card_ids)]
            ),
            "customers": self._records(
                customer_frame[customer_frame["customer_id"].astype(str).isin(customer_ids)]
            ),
            "provenance": self._info("shared FROM_DEVICE neighbors; seed entity excluded"),
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
        limit = int(limit)
        if limit < 1 or limit > 50:
            raise BackendError("limit must be between 1 and 50")
        context = {
            key: value
            for key, value in {
                "txn_id": txn_id,
                "card_id": card_id,
                "customer_id": customer_id,
                "device_id": device_id,
            }.items()
            if value
        }
        policies = search_policy(
            query, pattern=pattern, graph_context=context, limit=limit, out_dir=self.out_dir
        )
        cases: list[dict[str, Any]] = []
        closed = self._frame("v_ClosedCase")
        if txn_id:
            edge = self._frame("e_CASE_TXN")
            ids = set(
                edge.loc[edge["txn_id"].astype(str) == str(txn_id), "case_id"].astype(str)
            )
            cases.extend(
                case_provenance(row, source=str(self.load_dir / "v_ClosedCase.parquet"))
                for row in self._records(
                    closed[closed["case_id"].astype(str).isin(ids)]
                )
            )
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
        unique = {
            str(case["case_id"]): case
            for case in sorted(cases, key=lambda item: item["case_id"])
            if case.get("case_id")
        }
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

    def write_case(
        self,
        case_payload: dict[str, Any],
        txn_ids: list[str],
        card_ids: list[str],
        device_ids: list[str],
        prior_case_ids: list[str],
        prior_case_scores: dict[str, float] | None = None,
    ) -> dict[str, Any]:
        if not isinstance(case_payload, dict) or not case_payload.get("case_id"):
            raise BackendError("case_payload.case_id is required")
        if self.case_store_path is None:
            raise BackendError("case_store_path is required for local case writes")
        case_id = str(case_payload["case_id"])
        store = self._read_store()
        store[case_id] = {
            "case": _safe(case_payload),
            "txn_ids": _unique_ids(txn_ids),
            "card_ids": _unique_ids(card_ids),
            "device_ids": _unique_ids(device_ids),
            "prior_case_ids": _unique_ids(prior_case_ids),
            "prior_case_scores": _safe(prior_case_scores or {}),
            "backend": self.backend_name,
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
    return TigerGraphBackend(get_conn(), os.environ.get("TG_GRAPHNAME", "FraudGraph"))
