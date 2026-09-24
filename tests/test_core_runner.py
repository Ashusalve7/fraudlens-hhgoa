from __future__ import annotations

import json
from copy import deepcopy

from runner import (
    action_diff,
    build_evidence,
    investigate,
    normalize_answer,
    select_cases,
)
from validator import ValidationContext, schema_problems, validate_answer


def test_investigation_output_integrates_the_strict_json_schema(
    core_fake_evidence, static_calibrator, runner_case
):
    answer = investigate(core_fake_evidence, static_calibrator, runner_case)
    assert schema_problems(answer) == []
    assert answer["case"]["written_to_graph"] is True
    assert answer["case"]["graph_case_id"] == "AG-HHG-001"
    persisted = core_fake_evidence.written_payloads[0]["payload"]["answer_json"]
    assert json.loads(persisted) == answer
    assert any(
        item["ref"].startswith("mcp:policy_retrieval/")
        or item["ref"].startswith("mcp:policy_retrieval(")
        for item in answer["case"]["evidence"]
    )


def test_investigation_output_passes_strict_semantic_validation(
    core_fake_evidence, static_calibrator, runner_case
):
    answer = investigate(core_fake_evidence, static_calibrator, runner_case)
    context = ValidationContext(
        case_rows={runner_case["case_id"]: runner_case},
        txn_meta={
            "T-BASE": {
                "txn_id": "T-BASE",
                "ts": "2016-12-01 09:50:00",
                "amount": 2.0,
                "card_id": "C-1-K1",
            },
            "T-2": {
                "txn_id": "T-2",
                "ts": "2016-12-01 10:00:00",
                "amount": 100.0,
                "card_id": "C-1-K1",
            },
        },
        card_ids={"C-1-K1"},
        customer_ids={"C-1"},
        device_ids={"DP-1"},
    )
    assert validate_answer(answer, runner_case, context, expected_tool_calls=9) == []


def test_tool_ledger_and_request_step_are_case_local(core_fake_evidence, static_calibrator, runner_case):
    first = investigate(core_fake_evidence, static_calibrator, runner_case)
    second_case = {**runner_case, "case_id": "HHG-002", "flagged_txn_id": "T-3"}
    second = investigate(core_fake_evidence, static_calibrator, second_case)

    assert first["tool_calls"] == second["tool_calls"] == 9
    assert first["evidence_requests"][0]["asked_after_step"] == 8
    assert second["evidence_requests"][0]["asked_after_step"] == 8
    assert all(
        0 <= request["asked_after_step"] <= first["tool_calls"] for request in first["evidence_requests"]
    )
    assert all(
        0 <= request["asked_after_step"] <= second["tool_calls"] for request in second["evidence_requests"]
    )


def test_full_pack_and_subset_answers_normalize_identically(
    core_fake_evidence, static_calibrator, runner_case
):
    second_case = {**runner_case, "case_id": "HHG-002", "flagged_txn_id": "T-3"}
    full_first = investigate(core_fake_evidence, static_calibrator, runner_case)
    investigate(core_fake_evidence, static_calibrator, second_case)

    subset_evidence = type(core_fake_evidence)()
    subset_first = investigate(subset_evidence, static_calibrator, runner_case)

    original_latency = full_first["latency_s"]
    normalized_full = normalize_answer(full_first)
    normalized_subset = normalize_answer(subset_first)
    assert normalized_full == normalized_subset
    assert normalized_full["latency_s"] == 0.0
    assert full_first["latency_s"] == original_latency


def test_case_selection_preserves_canonical_pack_order():
    rows = [{"case_id": "HHG-001"}, {"case_id": "HHG-002"}, {"case_id": "HHG-003"}]
    selected = select_cases(rows, ["HHG-003", "HHG-001"])
    assert [row["case_id"] for row in selected] == ["HHG-001", "HHG-003"]


def test_customer_report_is_initial_denial_and_does_not_invent_a_later_request(
    core_fake_evidence, static_calibrator, runner_case
):
    case = {
        **runner_case,
        "trigger_type": "customer_report",
        "trigger_text": "Customer says the purchase was unauthorized.",
    }
    answer = investigate(core_fake_evidence, static_calibrator, case)
    assert answer["evidence_requests"] == []
    assert answer["case"]["verdict"] == "fraud"
    assert answer["case"]["fraud_probability"] == 0.9
    assert answer["next_best_actions"]["initial"] == answer["next_best_actions"]["final"]
    assert answer["next_best_actions"]["what_changed"] == "nothing"


def test_monthly_customer_dispute_takes_r7_without_blocking(
    core_fake_evidence, static_calibrator, runner_case
):
    rows = [
        {
            "txn_id": "T-R7-1",
            "ts": "2016-10-02 10:00:00",
            "amount": 49.0,
            "card_id": "C-1-K1",
            "channel": "online",
            "product_cd": "C",
        },
        {
            "txn_id": "T-R7-2",
            "ts": "2016-11-01 10:00:00",
            "amount": 49.0,
            "card_id": "C-1-K1",
            "channel": "online",
            "product_cd": "C",
        },
        {
            "txn_id": "T-2",
            "ts": "2016-12-01 10:00:00",
            "amount": 49.0,
            "card_id": "C-1-K1",
            "channel": "online",
            "product_cd": "C",
            "device_id": "DP-1",
        },
    ]

    def txn_context(txn_id):
        core_fake_evidence._record("get_transaction_context", in_txn_id=txn_id)
        return {
            "txn": {**rows[-1], "txn_id": txn_id},
            "card": {"card_id": "C-1-K1"},
            "device": {"device_id": "DP-1"},
        }

    core_fake_evidence.txn_context = txn_context
    core_fake_evidence.card_window = lambda *_args: core_fake_evidence._record("get_card_window") or rows
    core_fake_evidence.customer_history = lambda *_args: (
        core_fake_evidence._record("get_customer_history") or ([{"card_id": "C-1-K1"}], rows)
    )
    case = {**runner_case, "trigger_type": "customer_report"}
    answer = investigate(core_fake_evidence, static_calibrator, case)
    assert answer["case"]["verdict"] == "legitimate"
    assert answer["case"]["pattern"] == "none"
    assert "BLOCK_CARD" not in {action["action"] for action in answer["next_best_actions"]["final"]}
    assert answer["next_best_actions"]["final"][0]["action"] == "CLOSE_NO_FRAUD"


def test_build_evidence_enforces_the_opened_at_cutoff(runner_case):
    txn = {"txn_id": "T-2", "ts": "2016-12-01 10:00:00", "amount": 100, "channel": "online"}
    rows = [
        txn,
        {"txn_id": "T-FUTURE", "ts": "2016-12-01 12:00:01", "amount": 999, "channel": "online"},
    ]
    evidence = build_evidence(
        runner_case,
        txn,
        {},
        rows,
        "none",
        "",
        {},
        [],
        [],
        cutoff="2016-12-01 12:00:00",
    )
    assert all("T-FUTURE" not in item["claim"] for item in evidence)
    assert all("T-FUTURE" not in item["entity_ids"] for item in evidence)


def test_action_diff_reports_routes_and_order_changes():
    initial = deepcopy(
        [
            {"action": "VERIFY_WITH_CUSTOMER", "route": "auto", "reason": "R1: x"},
            {"action": "STEP_UP_AUTH", "route": "auto", "reason": "R1: y"},
        ]
    )
    final = deepcopy(
        [
            {"action": "STEP_UP_AUTH", "route": "auto", "reason": "R1: y"},
            {"action": "VERIFY_WITH_CUSTOMER", "route": "L1", "reason": "R1: x"},
        ]
    )
    diff = action_diff(initial, final)
    assert diff["added"] == []
    assert diff["removed"] == []
    assert any("route" in item for item in diff["changed"])
    assert any("order" in item for item in diff["changed"])
