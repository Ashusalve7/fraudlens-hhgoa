from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd
import pytest
from pipeline.build_load_files import _case_edges, _next_txn, device_profile_id
from pipeline.derive_card_ids_final import build_map
from pipeline.load_contract import LoadSpec, inspect_sources, validate_next_txn
from pipeline.load_graph import _string_graph_ids


def test_card_map_is_deterministic_and_normalizes_missing_identity() -> None:
    tx = pd.DataFrame(
        [
            {"TransactionID": "3", "customer_id": "C2", "card1": "2", "card4": "visa", "card6": "credit", "ts": "2020-01-03"},
            {"TransactionID": "1", "customer_id": "C1", "card1": "10", "card4": "visa", "card6": "credit", "ts": "2020-01-01"},
            {"TransactionID": "2", "customer_id": "C1", "card1": "2", "card4": None, "card6": "debit", "ts": "2020-01-02"},
            {"TransactionID": "4", "customer_id": "C1", "card1": "2", "card4": None, "card6": "debit", "ts": "2020-01-04"},
        ]
    )
    _, first = build_map(tx)
    _, shuffled = build_map(tx.iloc[::-1].reset_index(drop=True))
    assert first.equals(shuffled)
    assert first.set_index("TransactionID")["card_id"].to_dict() == {
        "1": "C1-K1",
        "2": "C1-K2",
        "3": "C2-K1",
        "4": "C1-K2",
    }
    assert pd.api.types.is_string_dtype(first["TransactionID"])
    assert first["card_id"].str.match(r"^C\d+-K\d+$").all()


def test_unknown_device_profiles_are_excluded_and_case_device_stays_observed() -> None:
    assert device_profile_id("", None, "nan", "_NA_") == ""
    assert device_profile_id("phone", "", "", "") == "DP-" + hashlib.md5(
        b"phone|||"
    ).hexdigest()[:12]

    cases = pd.DataFrame(
        [{"case_id": "CC-1", "txn_ids": "T-known|T-unknown", "card_id": "C1-K1", "connected_card_ids": ""}]
    )
    transactions = pd.DataFrame(
        [
            {"TransactionID": "T-known", "device_id": "DP-1"},
            {"TransactionID": "T-unknown", "device_id": ""},
        ]
    )
    _, _, _, case_device = _case_edges(cases, transactions, {"C1-K1"})
    assert case_device.to_dict(orient="records") == [{"case_id": "CC-1", "device_id": "DP-1"}]


def test_next_txn_and_loader_use_string_graph_ids() -> None:
    tx = pd.DataFrame(
        [
            {"TransactionID": 2, "card_id": "C1-K1", "ts": pd.Timestamp("2020-01-02")},
            {"TransactionID": 1, "card_id": "C1-K1", "ts": pd.Timestamp("2020-01-01")},
        ]
    )
    chain = _next_txn(tx)
    assert chain.to_dict(orient="records") == [
        {"txn_id": "1", "next_id": "2", "gap_seconds": 86400}
    ]
    assert all(pd.api.types.is_string_dtype(chain[column]) for column in ("txn_id", "next_id"))
    assert chain["gap_seconds"].dtype == "int64"

    spec = LoadSpec("e_TEST", "e", "TEST", "A", "B", ("from", "to"))
    normalized = _string_graph_ids(pd.DataFrame({"from": [1], "to": [2]}), spec)
    assert normalized.to_dict(orient="records") == [{"from": "1", "to": "2"}]
    with pytest.raises(RuntimeError, match="null or empty"):
        _string_graph_ids(pd.DataFrame({"from": [""], "to": [2]}), spec)


def test_graph_contract_contains_required_frames_and_query_projections() -> None:
    project = Path(__file__).resolve().parents[1] / "fraudlens"
    schema = (project / "gsql" / "schema.gsql").read_text(encoding="utf-8")
    queries = (project / "gsql" / "evidence_queries.gsql").read_text(encoding="utf-8")
    load_contract = (project / "pipeline" / "load_contract.py").read_text(encoding="utf-8")

    assert "CREATE VERTEX PolicyChunk" in schema
    assert "CREATE DIRECTED EDGE CASE_DEVICE" in schema
    assert 'LoadSpec("v_PolicyChunk"' in load_contract
    assert 'LoadSpec(\n        "e_CASE_DEVICE"' in load_contract
    assert "PRINT T[T.txn_id" in queries
    assert "T2 = SELECT t FROM (c:Customer" not in queries
    assert "PRINT Emails[Emails.domain]" in queries
    assert "REmailTxns" in queries
    assert "WHERE t.ts >= in_start AND t.ts <= in_end" in queries
    assert "WHERE cc.opened_at <= in_end" in queries
    assert "ORDER BY s.case_id ASC" in queries
    assert "S.answer_json" in queries


def test_local_load_contract_validates_case_device_policy_and_next_frames(graph_fixture) -> None:
    next_chain = validate_next_txn(graph_fixture.load_dir)
    assert next_chain["valid"] is True
    assert next_chain["checks"]["same_card"] is True
    assert next_chain["metrics"]["rows"] == 2

    report = inspect_sources(
        graph_fixture.load_dir,
        (
            LoadSpec("v_PolicyChunk", "v", "PolicyChunk", id_columns=("chunk_id",)),
            LoadSpec("e_CASE_DEVICE", "e", "CASE_DEVICE", "ClosedCase", "DeviceProfile", ("case_id", "device_id")),
        ),
        deep=False,
    )
    assert report["valid"] is True
    assert report["expected_vertex_counts"] == {"PolicyChunk": 2}
    assert report["expected_edge_counts"] == {"CASE_DEVICE": 2}
