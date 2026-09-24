from __future__ import annotations

import json

import numpy as np
import pandas as pd
from graph_tools.backend import LocalParquetBackend, TigerGraphBackend
from graph_tools.retrieval import _load_vector_pairs, case_provenance, search_policy
from pipeline.embeddings import embed_text


def test_local_backend_applies_cutoffs_and_excludes_unknown_device(graph_fixture) -> None:
    backend = LocalParquetBackend(
        load_dir=graph_fixture.load_dir,
        out_dir=graph_fixture.out_dir,
        case_store_path=graph_fixture.case_store,
    )
    context = backend.transaction_context("T1")
    assert context["card"]["card_id"] == "CUST1-K1"
    assert context["device"]["device_id"] == "DP-known"
    assert context["provenance"]["remote"] is False

    unknown = backend.transaction_context("T4")
    assert unknown["device"] is None
    assert "T4" not in set(backend._frame("e_FROM_DEVICE")["from"].astype(str))

    rows = backend.card_window(
        "CUST1-K1", "2020-01-02 08:00:00", "2020-01-02 23:59:59"
    )
    assert [row["txn_id"] for row in rows] == ["T1", "T2"]
    assert [row["txn_id"] for row in backend.region_activity(
        "CUST1-K1", "R1", "2020-01-02 08:00:00", "2020-01-02 23:59:59"
    )] == ["T1", "T2"]

    device = backend.device_neighborhood(
        "DP-known", "2020-01-02 08:00:00", "2020-01-02 12:00:00"
    )
    assert [row["txn_id"] for row in device["txns"]] == ["T1", "T3"]
    assert {row["card_id"] for row in device["cards"]} == {"CUST1-K1", "CUST2-K1"}
    assert [row["case_id"] for row in device["prior_cases"]] == ["CC-OLD"]

    shared = backend.shared_neighbors("T1")
    assert shared["device_id"] == "DP-known"
    assert "T1" not in {row["txn_id"] for row in shared["transactions"]}
    assert "T3" in {row["txn_id"] for row in shared["transactions"]}


def test_local_graph_algorithms_retrieval_and_case_store(graph_fixture) -> None:
    backend = LocalParquetBackend(
        load_dir=graph_fixture.load_dir,
        out_dir=graph_fixture.out_dir,
        case_store_path=graph_fixture.case_store,
    )
    component = backend.graph_component("T1", "ClosedCase", "CC-OLD")
    assert component["shortest_path"]["reachable"] is True
    assert component["node_type_counts"]["Transaction"] >= 3
    assert component["scope"] == "returned_relation_set"

    cases = backend.similar_cases("pattern_1", 28.0)
    assert [row["case_id"] for row in cases] == ["CC-FUTURE", "CC-OLD"]

    retrieval = backend.policy_retrieval(
        "What should an analyst do for a new device?",
        pattern="pattern_1",
        txn_id="T1",
        limit=2,
    )
    assert retrieval["policies"][0]["chunk_id"] == "PC-NEW"
    assert "CC-OLD" in {row["case_id"] for row in retrieval["cases"]}
    assert retrieval["provenance"]["policy"]["remote"] is False

    written = backend.write_case(
        {"case_id": "AG-1", "verdict": "fraud", "fraud_probability": 0.9},
        ["T1", "T1"],
        ["CUST1-K1"],
        ["DP-known"],
        ["CC-OLD", "CC-OLD"],
        {"CC-OLD": 0.75},
    )
    assert written["written_to_graph"] is False
    stored = json.loads(graph_fixture.case_store.read_text(encoding="utf-8"))
    assert stored["AG-1"]["txn_ids"] == ["T1"]
    assert stored["AG-1"]["prior_case_scores"] == {"CC-OLD": 0.75}
    assert backend.read_case("AG-1")["case"]["case_id"] == "AG-1"


def test_policy_vector_artifact_aligns_by_chunk_id(graph_fixture) -> None:
    frame = pd.read_parquet(graph_fixture.load_dir / "v_PolicyChunk.parquet")
    ids = frame["chunk_id"].astype(str).tolist()[::-1]
    vectors = np.vstack([embed_text(frame.loc[frame["chunk_id"] == value, "text"].iloc[0]) for value in ids])
    path = graph_fixture.out_dir / "reordered.npz"
    np.savez_compressed(path, chunk_ids=np.asarray(ids), vectors=vectors)

    ordered_vectors, positions, model, source = _load_vector_pairs(path, frame)
    assert model == "fraudlens-signed-hashing-v1"
    assert source == "policy_embeddings.npz"
    assert [frame.iloc[index]["chunk_id"] for index in positions] == ids
    assert np.allclose(ordered_vectors, vectors)

    first = search_policy(
        "new device online", out_dir=graph_fixture.out_dir, pattern="pattern_1", limit=2
    )
    second = search_policy(
        "new device online", out_dir=graph_fixture.out_dir, pattern="pattern_1", limit=2
    )
    assert first == second


def test_case_provenance_is_json_safe() -> None:
    result = case_provenance(
        {
            "case_id": "CC-1",
            "exposure_usd": float("nan"),
            "report_filed": "yes",
            "opened_at": "2020-01-01 00:00:00",
        }
    )
    assert result["exposure_usd"] == 0.0
    assert result["report_filed"] is True
    assert result["opened_at"] == "2020-01-01 00:00:00"


class FakeTigerConnection:
    def __init__(self) -> None:
        self.vertex_frames: list[pd.DataFrame] = []
        self.edge_frames: list[tuple[str, str, str, pd.DataFrame]] = []
        self.deleted_edges: list[tuple[str, str, str, str]] = []

    def runInstalledQuery(self, name: str, params: dict):
        if name == "get_customer_history":
            return [{"T": [{"v_id": "T1", "attributes": {"txn_id": "T1", "ts": "2020-01-01"}}]}]
        if name == "get_policy_chunks":
            return [{"P": [{"v_id": "PC-1", "attributes": {"chunk_id": "PC-1", "kind": "policy", "title": "R1", "text": "verify"}}]}]
        if name == "get_graph_ring":
            return [
                {"SeedTxns": [{"v_id": "T1", "attributes": {"txn_id": "T1"}}]},
                {"Ring1Cards": [{"v_id": "C1", "attributes": {"card_id": "C1"}}]},
                {"Ring1Devices": [{"v_id": "D1", "attributes": {"device_id": "D1"}}]},
                {"Ring2TxnsByDevice": [{"v_id": "T2", "attributes": {"txn_id": "T2"}}]},
            ]
        return []

    def upsertVertexDataFrame(self, frame, vertex_type, v_id):
        self.vertex_frames.append(frame.copy())
        return len(frame)

    def upsertEdgeDataFrame(self, frame, source, edge_type, target, **kwargs):
        self.edge_frames.append((edge_type, source, target, frame.copy()))
        return len(frame)

    def delEdges(self, source, source_id, edge_type, target):
        self.deleted_edges.append((source, source_id, edge_type, target))
        return {edge_type: 1}


def test_tiger_adapter_uses_correct_projection_and_no_fabricated_similarity() -> None:
    conn = FakeTigerConnection()
    backend = TigerGraphBackend(conn)
    _, transactions = backend.customer_history(
        "CUST1", "2020-01-01 00:00:00", "2020-01-02 00:00:00"
    )
    assert transactions == [{"txn_id": "T1", "ts": "2020-01-01"}]

    result = backend.policy_retrieval("verify", limit=1)
    assert result["policies"][0]["chunk_id"] == "PC-1"
    assert result["provenance"]["policy"]["remote"] is True

    ring = backend.graph_component("T1", "Transaction", "T2")
    assert ring["size"] == 4
    assert [node["id"] for node in ring["shortest_path"]["path"]] == ["T1", "D1", "T2"]

    replaced = backend.write_case(
        {"case_id": "AG-1", "fraud_probability": 0.8},
        ["T1"],
        ["C1"],
        ["D1"],
        ["CC-1"],
    )
    assert replaced["replaced_edge_rows"]["AG_TXN"] == 1
    assert len(conn.deleted_edges) == 4
    assert not any(edge[0] == "AG_SIMILAR" for edge in conn.edge_frames)
    backend.write_case(
        {"case_id": "AG-2", "fraud_probability": 0.8},
        [],
        [],
        [],
        ["CC-1"],
        {"CC-1": 0.6},
    )
    similar = next(frame for edge_type, _, _, frame in conn.edge_frames if edge_type == "AG_SIMILAR")
    assert similar["score"].tolist() == [0.6]
