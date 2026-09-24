from __future__ import annotations

import asyncio

import pytest
from agent.evidence import Evidence as RuntimeEvidence
from graph_tools.backend import LocalParquetBackend
from mcp.agent_adapter import Evidence
from mcp.client import MCPClientError, StdioMCPClient
from mcp.server import _make_fastmcp
from mcp.service import ToolService


def _local_backend(graph_fixture) -> LocalParquetBackend:
    return LocalParquetBackend(
        load_dir=graph_fixture.load_dir,
        out_dir=graph_fixture.out_dir,
        case_store_path=graph_fixture.case_store,
    )


def test_tool_service_validates_windows_ids_and_allow_list(graph_fixture) -> None:
    service = ToolService(_local_backend(graph_fixture))
    assert len(service.describe()) == 11
    assert all(item["inputSchema"]["type"] == "object" for item in service.describe())

    result = service.call(
        "card_window",
        {
            "card_id": "CUST1-K1",
            "start": "2020-01-02",
            "end": "2020-01-02T23:59:59Z",
        },
    )
    assert result["start"] == "2020-01-02 00:00:00"
    assert result["end"] == "2020-01-02 23:59:59"
    assert [row["txn_id"] for row in result["transactions"]] == ["T1", "T2"]

    with pytest.raises(ValueError, match="start must not be after end"):
        service.call(
            "card_window",
            {"card_id": "CUST1-K1", "start": "2020-01-03", "end": "2020-01-02"},
        )
    with pytest.raises(ValueError, match="unexpected arguments"):
        service.call("transaction_context", {"txn_id": "T1", "raw_gsql": "MATCH (n) RETURN n"})
    with pytest.raises(KeyError, match="not allow-listed"):
        service.call("run_gsql", {})


def test_complete_allowlisted_service_and_validation_paths(graph_fixture) -> None:
    service = ToolService(_local_backend(graph_fixture))
    assert service.call("transaction_context", {"txn_id": "T1"})["txn"]["txn_id"] == "T1"
    customer = service.call(
        "customer_history",
        {
            "customer_id": "CUST1",
            "start": "2020-01-02",
            "end": "2020-01-02T23:59:59Z",
        },
    )
    assert customer["transactions"]
    assert service.call(
        "device_neighborhood",
        {"device_id": "DP-known", "start": "2020-01-02", "end": "2020-01-02T23:59:59Z"},
    )["cards"]
    assert service.call(
        "region_activity",
        {
            "card_id": "CUST1-K1",
            "region_id": "R1",
            "start": "2020-01-02",
            "end": "2020-01-02T23:59:59Z",
        },
    )["transactions"]
    assert service.call(
        "graph_ring",
        {"txn_id": "T1", "target_type": "Transaction", "target_id": "T3"},
    )["nodes"]
    assert service.call("shared_neighbors", {"txn_id": "T1"})["device_id"] == "DP-known"
    assert service.call(
        "similar_cases", {"pattern": "pattern_1", "exposure_usd": 25}
    )["cases"]
    assert service.call(
        "policy_retrieval",
        {"query": "new device", "pattern": "pattern_1", "txn_id": "T1", "limit": 2},
    )["policies"]
    written = service.call(
        "case_write",
        {
            "case_payload": {"case_id": "AG-SERVICE", "verdict": "fraud"},
            "txn_ids": ["T1"],
            "card_ids": ["CUST1-K1"],
            "device_ids": ["DP-known"],
            "prior_case_ids": ["CC-OLD"],
            "prior_case_scores": {"CC-OLD": 0.8},
        },
    )
    assert written["case_id"] == "AG-SERVICE"
    assert service.call("case_read", {"case_id": "AG-SERVICE"})["found"] is True

    invalid_calls = [
        (("transaction_context", {"txn_id": "../bad"}), "unsupported characters"),
        (("card_window", {"card_id": "CUST1-K1", "start": "bad", "end": "2020-01-01"}), "ISO-8601"),
        (("customer_history", {"customer_id": "CUST1", "start": "2020-01-02", "end": "2020-01-01"}), "must not be after"),
        (("device_neighborhood", {"device_id": "DP-known", "start": "2020-01-02", "end": "2020-01-01"}), "must not be after"),
        (("region_activity", {"card_id": "CUST1-K1", "region_id": "R1", "start": "2020-01-02", "end": "2020-01-01"}), "must not be after"),
        (("graph_ring", {"txn_id": "T1", "target_type": "Transaction"}), "must be supplied together"),
        (("graph_ring", {"txn_id": "T1", "target_type": "Unknown", "target_id": "X"}), "target_type"),
        (("shared_neighbors", {"txn_id": "bad/id"}), "unsupported characters"),
        (("similar_cases", {"pattern": "pattern_1", "exposure_usd": -1}), "nonnegative"),
        (("policy_retrieval", {"query": "x", "limit": 0}), "between 1 and 50"),
        (("policy_retrieval", {"query": "", "limit": 2}), "non-empty string"),
        (("case_write", {"case_payload": {"case_id": "AG-X"}, "txn_ids": "T1"}), "must be an array"),
        (("case_write", {"case_payload": {"case_id": "AG-X"}, "prior_case_scores": {"CC-OLD": 2}}), "between 0 and 1"),
        (("case_read", {"case_id": "bad/id"}), "unsupported characters"),
    ]
    for arguments, message in invalid_calls:
        with pytest.raises(ValueError, match=message):
            service.call(*arguments)


def test_fastmcp_publishes_official_typed_tool_schemas(graph_fixture) -> None:
    server = _make_fastmcp(ToolService(_local_backend(graph_fixture)))

    async def inspect() -> list[str]:
        return [(tool.name, sorted(tool.inputSchema.get("required", []))) for tool in await server.list_tools()]

    tools = dict(asyncio.run(inspect()))
    assert len(tools) == 11
    assert tools["card_window"] == ["card_id", "end", "start"]
    assert tools["case_write"] == ["case_payload"]
    assert tools["policy_retrieval"] == ["query"]


def test_official_sdk_client_smoke_uses_local_backend_only(graph_fixture, monkeypatch) -> None:
    monkeypatch.setenv("TG_HOST", "")
    monkeypatch.setenv("TG_SECRET", "")
    client = StdioMCPClient(
        backend="local-test",
        allow_local_test_backend=True,
        load_dir=graph_fixture.load_dir,
        out_dir=graph_fixture.out_dir,
        case_store=graph_fixture.case_store,
        timeout_seconds=30,
    )
    try:
        tools = {tool["name"] for tool in client.list_tools()}
        assert tools == set(ToolService(_local_backend(graph_fixture)).tool_names())
        context = client.call_tool("transaction_context", {"txn_id": "T1"})
        assert context["provenance"]["remote"] is False
        assert context["device"]["device_id"] == "DP-known"
        with pytest.raises(MCPClientError, match="failed"):
            client.call_tool("transaction_context", {"txn_id": "missing/id"})
    finally:
        client.close()


def test_agent_adapter_runs_over_official_local_sdk(graph_fixture) -> None:
    adapter = Evidence(
        mode="mcp",
        client_backend="local-test",
        allow_local_test_backend=True,
        load_dir=graph_fixture.load_dir,
        out_dir=graph_fixture.out_dir,
        case_store=graph_fixture.case_store,
        timeout_seconds=30,
    )
    try:
        adapter.begin_case("MCP-1")
        assert adapter.txn_context("T1")["txn"]["txn_id"] == "T1"
        assert adapter.calls[0]["tool"] == "transaction_context"
        assert adapter.calls[0]["status"] == "ok"
    finally:
        adapter.close()


def test_agent_adapter_exposes_every_allowlisted_operation(graph_fixture) -> None:
    adapter = Evidence(mode="inprocess-test", backend=_local_backend(graph_fixture))
    adapter.begin_case("AG-COMPLETE")
    assert adapter.customer_history("CUST1", "2020-01-02", "2020-01-02 23:59:59")
    assert adapter.device_neighborhood("DP-known", "2020-01-02", "2020-01-02 23:59:59")
    assert adapter.region_activity("CUST1-K1", "R1", "2020-01-02", "2020-01-02 23:59:59")
    assert adapter.similar_cases("pattern_1", 25.0)
    assert adapter.graph_ring("T1", "Transaction", "T3")
    assert adapter.shared_neighbors("T1")
    assert adapter.policy_retrieval("new device", pattern="pattern_1", txn_id="T1", limit=2)
    assert adapter.write_agent_case(
        {"case_id": "AG-ADAPTER", "verdict": "fraud"},
        ["T1"],
        ["CUST1-K1"],
        ["DP-known"],
        ["CC-OLD"],
        {"CC-OLD": 0.8},
    ) == "AG-ADAPTER"
    assert adapter.read_agent_case("AG-ADAPTER")["found"] is True
    assert adapter.tool_count == 9
    assert all(record["status"] == "ok" for record in adapter.calls)
    adapter.close()


def test_runtime_evidence_defaults_to_official_stdio_mcp() -> None:
    adapter = RuntimeEvidence()
    try:
        assert isinstance(adapter.client, StdioMCPClient)
        assert adapter.client._thread is None
    finally:
        adapter.close()


def test_agent_adapter_preserves_runner_ledger_contract(graph_fixture) -> None:
    adapter = Evidence(mode="inprocess-test", backend=_local_backend(graph_fixture))
    adapter.begin_case("CASE-1")
    context = adapter.txn_context("T1")
    adapter.card_window("CUST1-K1", "2020-01-02 00:00:00", "2020-01-02 23:59:59")
    assert context["card"]["card_id"] == "CUST1-K1"
    assert adapter.tool_count == 2
    assert [record["tool"] for record in adapter.calls] == [
        "transaction_context",
        "card_window",
    ]
    assert adapter.calls[1]["query"] == "get_card_window"
    assert adapter.calls[1]["params"]["in_start"] == "2020-01-02 00:00:00"
    assert adapter.calls[1]["decision"] == "allow"
    assert adapter.calls[1]["status"] == "ok"
    assert adapter.calls[1]["latency_ms"] >= 0
    adapter.begin_case("CASE-2")
    assert adapter.tool_count == 0
    adapter.close()
