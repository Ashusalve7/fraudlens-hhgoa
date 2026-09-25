"""Mock-backed contract tests for the dashboard FastAPI backend.

These tests intentionally use a fake graph adapter.  Importing the dashboard or
running the suite must not open a TigerGraph connection.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
FRAUDLENS_ROOT = ROOT / "fraudlens"
if str(FRAUDLENS_ROOT) not in sys.path:
    sys.path.insert(0, str(FRAUDLENS_ROOT))

import dashboard.app as dashboard


@pytest.fixture
def loopback_client() -> TestClient:
    """Return a client with a known local address and no shared graph state."""
    previous = dashboard._ev
    dashboard._ev = None
    dashboard.clear_dashboard_caches()
    with TestClient(
        dashboard.app,
        client=("127.0.0.1", 43100),
        raise_server_exceptions=False,
    ) as client:
        yield client
    dashboard.clear_dashboard_caches()
    dashboard._ev = previous


class FakeConnection:
    def __init__(
        self,
        *,
        counts: dict[str, Any] | None = None,
        edges: dict[str, Any] | None = None,
    ) -> None:
        self.counts = counts or {}
        self.edges = edges or {}
        self.vertex_calls: list[tuple[Any, ...]] = []
        self.edge_calls: list[tuple[Any, ...]] = []

    def getVertexCount(self, vertex_type: str, *args: Any) -> Any:
        self.vertex_calls.append((vertex_type, *args))
        return self.counts.get(vertex_type, 0)

    def getEdgeTypes(self, force: bool = True) -> list[str]:
        return list(dashboard.CORE_EDGE_TYPES)

    def getEdgeCount(self, edge_type: str, from_type: str, to_type: str) -> Any:
        self.edge_calls.append((edge_type, from_type, to_type))
        return self.edges.get(edge_type, 0)


class FakeEvidence:
    def __init__(self, conn: Any) -> None:
        self.conn = conn
        self.context_calls: list[str] = []
        self.neighborhood_calls: list[tuple[str, str, str]] = []

    def txn_context(self, txn_id: str) -> dict[str, Any]:
        self.context_calls.append(txn_id)
        return {
            "txn": {"txn_id": txn_id, "ts": "2020-01-15 12:00:00", "amount": 10.0},
            "device": {"device_id": "DP-test", "device_info": "test"},
        }

    def device_neighborhood(
        self, device_id: str, start: str, end: str
    ) -> dict[str, Any]:
        self.neighborhood_calls.append((device_id, start, end))
        return {
            "txns": [
                {
                    "txn_id": f"t{index}",
                    "ts": "2020-01-15",
                    "amount": index,
                    "id_15": "x",
                    "id_23": "y",
                }
                for index in range(12)
            ],
            "cards": [{"card_id": f"card-{index}"} for index in range(120)],
            "prior_cases": [{"case_id": f"CC-{index}"} for index in range(120)],
        }


def _remote_client() -> TestClient:
    return TestClient(
        dashboard.app,
        client=("203.0.113.10", 43101),
        raise_server_exceptions=False,
    )


def test_split_deployment_origins_are_explicit_and_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "FRAUDLENS_ALLOWED_ORIGINS",
        "https://fraudlens-hhgoa.pages.dev, https://fraudlens.example/,",
    )
    assert dashboard._configured_origins() == [
        "https://fraudlens-hhgoa.pages.dev",
        "https://fraudlens.example",
    ]
    monkeypatch.delenv("FRAUDLENS_ALLOWED_ORIGINS")
    monkeypatch.delenv("DASHBOARD_ALLOWED_ORIGINS", raising=False)
    assert dashboard._configured_origins() == []


def test_case_ids_are_strict_and_traversal_attempts_do_not_disclose_files(
    loopback_client: TestClient,
) -> None:
    valid = loopback_client.get("/api/cases/HHG-001")
    assert valid.status_code == 200
    assert valid.json()["case_id"] == "HHG-001"

    hostile_ids = [
        "../fraudlens/eval/out/model.json",
        "%2e%2e%2ffraudlens%2feval%2fout%2fmodel.json",
        r"..%5cfraudlens%5ceval%5cout%5cmodel.json",
        r"C:%5cfraudlens%5ceval%5cout%5cmodel.json",
        "HHG-001.json",
        "hhg-001",
        "HHG-01",
        "HHG-0001",
        "HHG-001%00",
    ]
    for case_id in hostile_ids:
        response = loopback_client.get(f"/api/cases/{case_id}")
        assert response.status_code in {400, 404}, case_id
        assert "scaler_mean" not in response.text
        assert "features" not in response.text

    for case_id in ("../x", r"..\x", "C:\\x", "HHG-001.json", "hhg-001"):
        with pytest.raises(dashboard.HTTPException) as error:
            dashboard._safe_case_path(case_id)
        assert error.value.status_code == 404
        assert error.value.detail == "case not found"


def test_case_queue_and_detail_keep_frontend_response_shape(
    loopback_client: TestClient,
) -> None:
    queue = loopback_client.get("/api/cases")
    assert queue.status_code == 200
    assert isinstance(queue.json(), list)
    assert queue.json()
    first = queue.json()[0]
    assert {
        "case_id",
        "verdict",
        "status",
        "pattern",
        "fraud_probability",
        "exposure_usd",
        "sar",
        "affected_count",
        "tool_calls",
        "latency_s",
        "states",
    } <= set(first)

    detail = loopback_client.get("/api/cases/HHG-001").json()
    assert detail["case_id"] == "HHG-001"
    assert isinstance(detail["case"], dict)
    assert isinstance(detail["sar"], dict)
    assert "flagged_txn_id" in detail


def test_ring_window_and_transaction_identifier_are_bounded(
    loopback_client: TestClient,
) -> None:
    evidence = FakeEvidence(FakeConnection())
    dashboard._ev = evidence

    for query in (
        "window_days=0",
        "window_days=366",
        "window_days=999999999999999999999999",
    ):
        response = loopback_client.get(f"/api/graph/ring/123?{query}")
        assert response.status_code == 422
        assert evidence.context_calls == []

    response = loopback_client.get("/api/graph/ring/txn-123?window_days=45")
    assert response.status_code == 200
    body = response.json()
    assert body["txn_id"] == "txn-123"
    assert body["n_txns"] == 12
    assert len(body["sample"]) == dashboard.MAX_RING_SAMPLE
    assert len(body["cards"]) == dashboard.MAX_RING_CARDS
    assert len(body["prior_cases"]) == dashboard.MAX_RING_PRIOR_CASES
    assert len(evidence.neighborhood_calls) == 1
    device_id, start, end = evidence.neighborhood_calls[0]
    assert device_id == "DP-test"
    assert start == "2019-12-01 12:00:00"
    assert end == "2020-01-15 12:00:00"

    for txn_id in ("../secret", r"..%5csecret", "txn/secret", "a" * 129, ""):
        response = loopback_client.get(f"/api/graph/ring/{txn_id}")
        assert response.status_code in {404, 422}


def test_graph_stats_cache_uses_fingerprint_and_invalidates_on_version_change(
    loopback_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = FakeConnection(
        counts={
            vertex_type: index
            for index, vertex_type in enumerate(dashboard.VERTEX_TYPES)
        }
    )
    dashboard._ev = SimpleNamespace(conn=conn)
    dashboard.clear_dashboard_caches()

    first = loopback_client.get("/api/graph/stats")
    second = loopback_client.get("/api/graph/stats")
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert len(conn.vertex_calls) == len(dashboard.VERTEX_TYPES)

    monkeypatch.setenv("FRAUDLENS_CACHE_VERSION", "test-version-2")
    third = loopback_client.get("/api/graph/stats")
    assert third.status_code == 200
    assert len(conn.vertex_calls) == 2 * len(dashboard.VERTEX_TYPES)

    replacement = FakeConnection(
        counts={vertex_type: 1 for vertex_type in dashboard.VERTEX_TYPES}
    )
    dashboard._ev = SimpleNamespace(conn=replacement)
    fourth = loopback_client.get("/api/graph/stats")
    assert fourth.status_code == 200
    assert len(replacement.vertex_calls) == len(dashboard.VERTEX_TYPES)


def test_graph_sleep_and_unexpected_errors_are_provider_neutral(
    loopback_client: TestClient,
) -> None:
    class SleepingConnection:
        def getVertexCount(self, *_args: Any) -> int:
            raise RuntimeError("workspace asleep: password=do-not-leak")

    dashboard._ev = SimpleNamespace(conn=SleepingConnection())
    response = loopback_client.get("/api/graph/stats")
    assert response.status_code == 503
    assert response.json()["detail"] == "graph service is temporarily unavailable"
    assert "password" not in response.text
    assert "do-not-leak" not in response.text

    def explode(_case_id: str) -> dict[str, Any]:
        raise RuntimeError("internal path C:\\private\\secret.json")

    original = dashboard._read_case
    dashboard._read_case = explode  # type: ignore[assignment]
    try:
        response = loopback_client.get("/api/cases/HHG-001")
    finally:
        dashboard._read_case = original
    assert response.status_code == 500
    assert response.json() == {"detail": "internal server error"}
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "no-store"
    assert "private" not in response.text


def test_health_reports_counts_and_degrades_without_graph(
    loopback_client: TestClient,
) -> None:
    conn = FakeConnection(
        counts={
            vertex_type: index + 1
            for index, vertex_type in enumerate(dashboard.VERTEX_TYPES)
        },
        edges={
            edge_type: index + 2
            for index, edge_type in enumerate(dashboard.CORE_EDGE_TYPES)
        },
    )
    dashboard._ev = SimpleNamespace(conn=conn)
    response = loopback_client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["ready"] is True
    assert body["counts"] == body["graph"]["counts"]
    assert body["edge_counts"] == body["graph"]["edge_counts"]
    assert body["counts"]["Transaction"] == 1
    assert body["edge_counts"]["OWNS_CARD"] == 2
    assert body["graph"]["core_edges"]["missing"] == []

    class SleepingConnection:
        def getEdgeTypes(self, *_args: Any) -> list[str]:
            raise RuntimeError("workspace asleep: private host")

    dashboard._ev = SimpleNamespace(conn=SleepingConnection())
    response = loopback_client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "unavailable"
    assert body["ready"] is False
    assert body["graph"]["connected"] is False
    assert "private host" not in response.text


def test_explanation_cache_tracks_case_pack_model_and_adapter_fingerprints(
    loopback_client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cases_dir = tmp_path / "cases"
    cases_dir.mkdir()
    case_path = cases_dir / "HHG-001.json"
    pack_path = tmp_path / "case_pack.csv"
    model_path = tmp_path / "model.json"
    case_path.write_text(
        json.dumps({"case_id": "HHG-001", "case": {"fraud_probability": 0.5}}),
        encoding="utf-8",
    )
    pack_path.write_text(
        "case_id,flagged_txn_id,card_id,customer_id\nHHG-001,t1,c1,customer-1\n",
        encoding="utf-8",
    )
    model_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(dashboard, "CASES_DIR", cases_dir)
    monkeypatch.setattr(dashboard, "CASE_PACK_PATH", pack_path)
    monkeypatch.setattr(dashboard, "MODEL_PATH", model_path)

    calls: list[str] = []

    def build(
        case_id: str, _answer: dict[str, Any], _case: dict[str, str]
    ) -> dict[str, Any]:
        calls.append(case_id)
        return {
            "model": {},
            "probability": 0.5,
            "pattern": "test",
            "contributions": [],
            "n_evidence": 0,
            "similar_prior_cases": [],
            "graph": {},
            "device_cards": 0,
        }

    monkeypatch.setattr(dashboard, "_build_explanation", build)
    dashboard._ev = SimpleNamespace(conn=object())

    first = loopback_client.get("/api/explain/HHG-001")
    second = loopback_client.get("/api/explain/HHG-001")
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert calls == ["HHG-001"]

    case_path.write_text(
        json.dumps({"case_id": "HHG-001", "case": {"fraud_probability": 0.6}}),
        encoding="utf-8",
    )
    assert loopback_client.get("/api/explain/HHG-001").status_code == 200
    assert calls == ["HHG-001", "HHG-001"]

    pack_path.write_text(
        "case_id,flagged_txn_id,card_id,customer_id\nHHG-001,t2,c1,customer-1\n",
        encoding="utf-8",
    )
    assert loopback_client.get("/api/explain/HHG-001").status_code == 200
    assert calls == ["HHG-001", "HHG-001", "HHG-001"]

    monkeypatch.setenv("FRAUDLENS_CACHE_VERSION", "explanation-new")
    assert loopback_client.get("/api/explain/HHG-001").status_code == 200
    assert calls == ["HHG-001", "HHG-001", "HHG-001", "HHG-001"]


def test_real_explanation_builder_handles_cutoff_temperature_and_calibrator() -> None:
    class ExplanationEvidence:
        conn = object()

        def txn_context(self, _txn_id: str) -> dict[str, Any]:
            txn = {
                "txn_id": "T-1",
                "ts": "2020-01-15 10:00:00",
                "amount": 125.0,
                "channel": "online",
                "product_cd": "C",
                "risk_score": 0.8,
                "card_id": "C-1-K1",
                "addr1": "R1",
            }
            return {
                "txn": txn,
                "card": {"card_id": "C-1-K1"},
                "customer_id": "C-1",
                "device": {"device_id": "DP-1", "device_info": "browser"},
            }

        def card_window(self, _card_id: str, _start: str, _end: str) -> list[dict[str, Any]]:
            return [self.txn_context("T-1")["txn"]]

        def device_neighborhood(self, _device_id: str, _start: str, _end: str) -> dict[str, Any]:
            return {
                "txns": [self.txn_context("T-1")["txn"]],
                "cards": [{"card_id": "C-1-K1"}],
                "customers": [{"customer_id": "C-1"}],
                "prior_cases": [],
            }

    previous = dashboard._ev
    dashboard._ev = ExplanationEvidence()
    try:
        result = dashboard._build_explanation(
            "HHG-001",
            {
                "case": {
                    "fraud_probability": 0.81,
                    "pattern": "card_not_present_fraud",
                    "evidence": [],
                    "similar_prior_cases": [],
                }
            },
            {
                "case_id": "HHG-001",
                "opened_at": "2020-01-15 12:00:00",
                "flagged_txn_id": "T-1",
                "card_id": "C-1-K1",
                "customer_id": "C-1",
            },
        )
    finally:
        dashboard._ev = previous
    assert result["base_model_probability"] is not None
    assert 0 <= result["base_model_probability"] <= 1
    assert "pre-response" in result["probability_basis"]
    assert result["model"]["temperature"] == 1.5


def test_token_is_optional_for_loopback_and_required_for_remote_api(
    loopback_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FRAUDLENS_API_TOKEN", "test-secret")
    assert loopback_client.get("/api/cases").status_code == 200
    assert loopback_client.get("/").status_code == 200

    with _remote_client() as remote:
        assert remote.get("/").status_code == 200
        unauthorized = remote.get("/api/cases")
        assert unauthorized.status_code == 401
        assert unauthorized.json() == {"detail": "authentication required"}
        assert unauthorized.headers["www-authenticate"] == "Bearer"

        assert (
            remote.get("/api/cases", headers={"X-API-Key": "wrong"}).status_code == 401
        )
        assert (
            remote.get(
                "/api/cases", headers={"Authorization": "Bearer test-secret"}
            ).status_code
            == 200
        )
        assert (
            remote.get(
                "/api/cases", headers={"X-FraudLens-Token": "test-secret"}
            ).status_code
            == 200
        )
        assert (
            remote.get(
                "/api/cases",
                headers={"X-Forwarded-For": "127.0.0.1", "X-Real-IP": "127.0.0.1"},
            ).status_code
            == 401
        )


def test_dist_spa_assets_and_history_fallback(loopback_client: TestClient) -> None:
    root = loopback_client.get("/")
    assert root.status_code == 200
    assert "text/html" in root.headers["content-type"]
    assert root.headers["x-content-type-options"] == "nosniff"
    assert root.headers["cache-control"] == "no-cache"

    for route in ("/cases/HHG-001", "/analytics", "/does-not-exist"):
        response = loopback_client.get(route)
        assert response.status_code == 200
        assert response.text == root.text

    api_unknown = loopback_client.get("/api/does-not-exist")
    assert api_unknown.status_code == 404
    assert loopback_client.get("/api%252funknown").status_code == 404

    assets = sorted((dashboard.DIST_ASSETS).glob("*"))
    assert assets
    asset = loopback_client.get(f"/assets/{assets[0].name}")
    assert asset.status_code == 200
    assert asset.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert loopback_client.get("/assets/%2e%2e%2findex.html").status_code == 404

    robots = loopback_client.get("/robots.txt")
    assert robots.status_code == 200
    assert robots.text == "User-agent: *\nAllow: /\n"
    assert "text/plain" in robots.headers["content-type"]


def test_missing_or_escaping_dist_index_is_not_served(
    loopback_client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    outside = tmp_path / "outside.html"
    outside.write_text("private", encoding="utf-8")
    monkeypatch.setattr(dashboard, "DIST_DIR", dist)
    monkeypatch.setattr(dashboard, "DIST_INDEX", outside)
    with pytest.raises(dashboard.HTTPException) as error:
        dashboard._spa_response()
    assert error.value.status_code == 503
    assert error.value.detail == "dashboard build unavailable"
