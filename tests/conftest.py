from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

PROJECT = Path(__file__).resolve().parents[1] / "fraudlens"
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))


@pytest.fixture
def graph_fixture(tmp_path: Path) -> SimpleNamespace:
    """Create a complete local graph fixture; no remote connection is used."""
    root = tmp_path / "graph_artifacts"
    load = root / "load"
    load.mkdir(parents=True)

    frames = {
        "v_Transaction": pd.DataFrame(
            [
                {
                    "txn_id": "T1",
                    "ts": "2020-01-02 09:00:00",
                    "amount": 10.0,
                    "product_cd": "W",
                    "channel": "online",
                    "risk_score": 0.2,
                    "card1": "111",
                    "addr1": "R1",
                    "id_15": "Found",
                    "id_23": "NotProxy",
                    "device_type": "New",
                },
                {
                    "txn_id": "T2",
                    "ts": "2020-01-02 09:30:00",
                    "amount": 20.0,
                    "product_cd": "W",
                    "channel": "online",
                    "risk_score": 0.3,
                    "card1": "111",
                    "addr1": "R1",
                    "id_15": "Found",
                    "id_23": "NotProxy",
                    "device_type": "New",
                },
                {
                    "txn_id": "T3",
                    "ts": "2020-01-02 10:00:00",
                    "amount": 30.0,
                    "product_cd": "C",
                    "channel": "online",
                    "risk_score": 0.8,
                    "card1": "222",
                    "addr1": "R2",
                    "id_15": "New",
                    "id_23": "Proxy",
                    "device_type": "New",
                },
                {
                    "txn_id": "T4",
                    "ts": "2020-01-03 10:00:00",
                    "amount": 40.0,
                    "product_cd": "W",
                    "channel": "in_person",
                    "risk_score": 0.1,
                    "card1": "333",
                    "addr1": "R1",
                    "id_15": "",
                    "id_23": "",
                    "device_type": "Unknown",
                },
                {
                    "txn_id": "T5",
                    "ts": "2020-01-04 10:00:00",
                    "amount": 50.0,
                    "product_cd": "W",
                    "channel": "online",
                    "risk_score": 0.4,
                    "card1": "111",
                    "addr1": "R1",
                    "id_15": "Found",
                    "id_23": "NotProxy",
                    "device_type": "Found",
                },
            ]
        ),
        "v_Card": pd.DataFrame(
            [
                {"card_id": "CUST1-K1", "network": "visa", "card_type": "credit", "n_txn": 3},
                {"card_id": "CUST2-K1", "network": "mastercard", "card_type": "debit", "n_txn": 1},
                {"card_id": "CUST3-K1", "network": "visa", "card_type": "credit", "n_txn": 1},
            ]
        ),
        "v_Customer": pd.DataFrame(
            [
                {"customer_id": "CUST1", "n_cards": 1, "n_txn": 3},
                {"customer_id": "CUST2", "n_cards": 1, "n_txn": 1},
                {"customer_id": "CUST3", "n_cards": 1, "n_txn": 1},
            ]
        ),
        "v_DeviceProfile": pd.DataFrame(
            [
                {
                    "device_id": "DP-known",
                    "device_info": "phone",
                    "os": "Android",
                    "browser": "Chrome",
                    "screen": "mobile",
                    "n_cards": 2,
                    "n_txn": 3,
                    "n_fraud_cases": 1,
                }
            ]
        ),
        "v_ClosedCase": pd.DataFrame(
            [
                {
                    "case_id": "CC-OLD",
                    "customer_id": "CUST1",
                    "card_id": "CUST1-K1",
                    "outcome": "confirmed_fraud",
                    "pattern": "pattern_1",
                    "opened_at": "2019-12-20 00:00:00",
                    "closed_at": "2019-12-21 00:00:00",
                    "n_txns": 1,
                    "exposure_usd": 10.0,
                    "report_filed": True,
                    "actions": "BLOCK_CARD",
                    "notes": "confirmed shared device fraud",
                },
                {
                    "case_id": "CC-FUTURE",
                    "customer_id": "CUST2",
                    "card_id": "CUST2-K1",
                    "outcome": "confirmed_fraud",
                    "pattern": "pattern_1",
                    "opened_at": "2020-01-10 00:00:00",
                    "closed_at": "2020-01-11 00:00:00",
                    "n_txns": 1,
                    "exposure_usd": 30.0,
                    "report_filed": False,
                    "actions": "CREATE_CASE",
                    "notes": "must not leak after cutoff",
                },
            ]
        ),
        "v_PolicyChunk": pd.DataFrame(
            [
                {
                    "chunk_id": "PC-NEW",
                    "kind": "pattern",
                    "title": "New device",
                    "text": "new device online fraud",
                },
                {"chunk_id": "PC-BLOCK", "kind": "policy", "title": "R1", "text": "verify before block"},
            ]
        ),
        "e_PAID_WITH": pd.DataFrame(
            [
                {"from": "T1", "card_id": "CUST1-K1"},
                {"from": "T2", "card_id": "CUST1-K1"},
                {"from": "T3", "card_id": "CUST2-K1"},
                {"from": "T4", "card_id": "CUST3-K1"},
                {"from": "T5", "card_id": "CUST1-K1"},
            ]
        ),
        "e_FROM_DEVICE": pd.DataFrame(
            [
                {"from": "T1", "device_id": "DP-known"},
                {"from": "T3", "device_id": "DP-known"},
                {"from": "T5", "device_id": "DP-known"},
            ]
        ),
        "e_BILLED_IN": pd.DataFrame(
            [
                {"from": "T1", "region_id": "R1"},
                {"from": "T2", "region_id": "R1"},
                {"from": "T3", "region_id": "R2"},
                {"from": "T4", "region_id": "R1"},
                {"from": "T5", "region_id": "R1"},
            ]
        ),
        "e_OWNS_CARD": pd.DataFrame(
            [
                {"customer_id": "CUST1", "card_id": "CUST1-K1"},
                {"customer_id": "CUST2", "card_id": "CUST2-K1"},
                {"customer_id": "CUST3", "card_id": "CUST3-K1"},
            ]
        ),
        "e_CASE_TXN": pd.DataFrame([{"case_id": "CC-OLD", "txn_id": "T1"}]),
        "e_CASE_CARD": pd.DataFrame([{"case_id": "CC-OLD", "card_id": "CUST1-K1"}]),
        "e_CASE_CONN_CARD": pd.DataFrame([{"case_id": "CC-OLD", "card_id": "CUST2-K1"}]),
        "e_CASE_DEVICE": pd.DataFrame(
            [
                {"case_id": "CC-OLD", "device_id": "DP-known"},
                {"case_id": "CC-FUTURE", "device_id": "DP-known"},
            ]
        ),
        "e_NEXT_TXN": pd.DataFrame(
            [
                {"txn_id": "T1", "next_id": "T2", "gap_seconds": 1800},
                {"txn_id": "T2", "next_id": "T5", "gap_seconds": 174600},
            ]
        ),
    }
    for name, frame in frames.items():
        frame.to_parquet(load / f"{name}.parquet", index=False)

    policy = frames["v_PolicyChunk"].copy()
    policy["source_path"] = "fixture/README.md"
    policy["source_section"] = "fixture"
    policy["source_anchor"] = "fixture"
    policy["content_hash"] = "fixture-hash"
    policy["policy_rule"] = "R1"
    policy["patterns"] = ["pattern_1", ""]
    policy.to_parquet(root / "policy_chunks.parquet", index=False)
    pd.DataFrame(
        [
            {"TransactionID": "T1", "card_id": "CUST1-K1"},
            {"TransactionID": "T2", "card_id": "CUST1-K1"},
            {"TransactionID": "T5", "card_id": "CUST1-K1"},
        ]
    ).to_parquet(root / "txn_card_map.parquet", index=False)

    return SimpleNamespace(
        root=root,
        load_dir=load,
        out_dir=root,
        case_store=root / "cases.json",
    )


@pytest.fixture
def production_model() -> dict:
    """Minimal valid artifact using the exact 16-feature runtime contract."""
    from agent.decision import MODEL_FEATURES

    return {
        "features": list(MODEL_FEATURES),
        "scaler_mean": [0.0] * len(MODEL_FEATURES),
        "scaler_scale": [1.0] * len(MODEL_FEATURES),
        "coef": [0.0] * len(MODEL_FEATURES),
        "intercept": 0.0,
        "platt": {"mean": 0.0, "std": 1.0, "w": 1.0, "b": 0.0, "low": -10.0, "high": 10.0},
        "train_base_rate": 0.8,
        "exam_base_rate": 0.5,
        "temperature": 1.5,
        "response_likelihood": {"denied": 8.0, "confirmed": 0.125, "no_response": 1.0},
    }


@pytest.fixture
def validation_context():
    from validator import ValidationContext

    return ValidationContext(
        case_rows={
            "HHG-001": {
                "case_id": "HHG-001",
                "opened_at": "2016-12-01 12:00:00",
                "trigger_type": "risk_score",
                "flagged_txn_id": "T-1",
                "card_id": "C-1-K1",
                "customer_id": "C-1",
            }
        },
        txn_meta={
            "T-1": {
                "txn_id": "T-1",
                "ts": "2016-12-01 10:00:00",
                "amount": 75.0,
                "card_id": "C-1-K1",
            }
        },
        card_ids={"C-1-K1"},
        customer_ids={"C-1"},
        device_ids={"DP-1"},
        closed_case_ids={"CC-1"},
    )


@pytest.fixture
def valid_answer() -> dict:
    return {
        "case_id": "HHG-001",
        "case": {
            "status": "escalated",
            "verdict": "uncertain",
            "fraud_probability": 0.5,
            "pattern": "none",
            "pattern_description": "",
            "affected_txn_ids": [],
            "first_suspicious_txn_id": "",
            "connected_card_ids": [],
            "connected_device_profiles": [],
            "exposure_usd": 0,
            "evidence": [
                {
                    "claim": "Transaction T-1 was retrieved as the investigation trigger.",
                    "source": "graph",
                    "ref": "query:get_transaction_context(txn_id=T-1)",
                    "entity_ids": ["T-1"],
                }
            ],
            "similar_prior_cases": [],
            "summary": "The trigger was retrieved. The available evidence does not settle the alert.",
            "written_to_graph": False,
            "graph_case_id": "",
        },
        "evidence_requests": [],
        "next_best_actions": {
            "initial": [
                {
                    "action": "VERIFY_WITH_CUSTOMER",
                    "route": "auto",
                    "reason": "R1: verify before blocking on the current signal",
                }
            ],
            "final": [
                {
                    "action": "VERIFY_WITH_CUSTOMER",
                    "route": "auto",
                    "reason": "R1: verify before blocking on the current signal",
                }
            ],
            "what_changed": "nothing",
        },
        "sar": {
            "file": False,
            "reason": "3a: no confirmed or strongly suspected report basis",
            "narrative": "",
            "subjects": [],
            "total_amount_usd": 0,
            "activity_dates": [],
        },
        "stop_reason": "The remaining uncertainty requires a human decision.",
        "tool_calls": 0,
        "tokens": 0,
        "latency_s": 0,
    }


class StaticCalibrator:
    def __init__(self, probability: float = 0.5) -> None:
        self.probability = probability

    def score(self, _features):
        return self.probability, self.probability

    def update_for_response(self, probability: float, response: str) -> float:
        if response == "denied":
            return 0.9
        if response == "confirmed":
            return 0.1
        return probability


class CoreFakeEvidence:
    """Deterministic case-local evidence adapter; it never opens a graph."""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.query_log: list[dict] = []
        self.case_id: str | None = None
        self.written_payloads: list[dict] = []

    def begin_case(self, case_id: str) -> None:
        self.case_id = case_id
        self.calls = []
        self.query_log = []
        self.written_payloads = []

    def _record(self, name: str, **params) -> None:
        record = {"query": name, "params": params}
        self.calls.append(record)
        self.query_log.append(record)

    def txn_context(self, txn_id: str) -> dict:
        self._record("get_transaction_context", in_txn_id=txn_id)
        return {
            "txn": {
                "txn_id": txn_id,
                "ts": "2016-12-01 10:00:00",
                "amount": 100.0,
                "card_id": "C-1-K1",
                "channel": "online",
                "product_cd": "C",
                "risk_score": 0.5,
                "addr1": "R1",
                "device_id": "DP-1",
                "id_15": "New",
            },
            "card": {"card_id": "C-1-K1"},
            "customer_id": "C-1",
            "device": {"device_id": "DP-1"},
        }

    @staticmethod
    def _rows(flagged_id: str) -> list[dict]:
        return [
            {
                "txn_id": "T-BASE",
                "ts": "2016-12-01 09:50:00",
                "amount": 2.0,
                "card_id": "C-1-K1",
                "channel": "online",
                "product_cd": "C",
                "addr1": "R1",
            },
            {
                "txn_id": flagged_id,
                "ts": "2016-12-01 10:00:00",
                "amount": 100.0,
                "card_id": "C-1-K1",
                "channel": "online",
                "product_cd": "C",
                "addr1": "R1",
                "device_id": "DP-1",
                "id_15": "New",
            },
        ]

    def graph_ring(self, txn_id: str) -> dict:
        self._record("get_graph_ring", in_txn_id=txn_id)
        return {
            "nodes": [
                {"type": "Transaction", "id": txn_id},
                {"type": "Card", "id": "C-1-K1"},
                {"type": "DeviceProfile", "id": "DP-1"},
            ],
            "edges": [
                {"source": txn_id, "target": "C-1-K1", "type": "PAID_WITH"},
                {"source": txn_id, "target": "DP-1", "type": "FROM_DEVICE"},
            ],
        }

    def card_window(self, _card_id: str, _start: str, _end: str) -> list[dict]:
        self._record("get_card_window")
        return self._rows("T-2")

    def customer_history(self, _customer_id: str, _start: str, _end: str):
        self._record("get_customer_history")
        return [{"card_id": "C-1-K1"}], self._rows("T-2")

    def device_neighborhood(self, device_id: str, _start: str, _end: str) -> dict:
        self._record("get_device_neighborhood", in_device_id=device_id)
        return {
            "device_id": device_id,
            "txns": [],
            "cards": [{"card_id": "C-1-K1"}],
            "customers": [{"customer_id": "C-1"}],
            "prior_cases": [],
        }

    def region_activity(self, _card_id: str, _region: str, _start: str, _end: str) -> list[dict]:
        self._record("get_region_activity")
        return []

    def policy_retrieval(self, _query: str, **_kwargs) -> dict:
        self._record("policy_retrieval")
        return {
            "policies": [
                {
                    "chunk_id": "PC-TEST",
                    "kind": "policy",
                    "title": "Test policy",
                    "text": "R1 verification policy",
                    "score": 0.9,
                    "provenance": {"policy_rule": "R1"},
                }
            ],
            "cases": [],
            "provenance": {"policy": {"remote": True, "source": "TigerGraph:PolicyChunk"}},
        }

    def similar_cases(self, _pattern: str, _exposure: float) -> list[dict]:
        self._record("find_similar_cases")
        return []

    def write_agent_case(self, payload: dict, *_args, **kwargs) -> str:
        self._record("write_agent_case", case_id=payload["case_id"])
        self.written_payloads.append({"payload": deepcopy(payload), "kwargs": deepcopy(kwargs)})
        return str(payload["case_id"])


@pytest.fixture
def core_fake_evidence() -> CoreFakeEvidence:
    return CoreFakeEvidence()


@pytest.fixture
def static_calibrator() -> StaticCalibrator:
    return StaticCalibrator()


@pytest.fixture
def runner_case() -> dict:
    return {
        "case_id": "HHG-001",
        "opened_at": "2016-12-01 12:00:00",
        "trigger_type": "risk_score",
        "trigger_text": "Review transaction T-2.",
        "flagged_txn_id": "T-2",
        "card_id": "C-1-K1",
        "customer_id": "C-1",
        "risk_score": "0.5",
    }
