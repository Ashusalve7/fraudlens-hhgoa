from __future__ import annotations

import json
from copy import deepcopy

from validator import (
    schema_problems,
    validate_answer,
    validate_files,
    validate_graph_files,
)


def case_row():
    return {
        "case_id": "HHG-001",
        "opened_at": "2016-12-01 12:00:00",
        "trigger_type": "risk_score",
        "flagged_txn_id": "T-1",
        "card_id": "C-1-K1",
        "customer_id": "C-1",
    }


def test_valid_answer_has_no_schema_or_semantic_findings(valid_answer, validation_context):
    assert schema_problems(valid_answer) == []
    assert validate_answer(valid_answer, case_row(), validation_context) == []


def test_strict_validator_rejects_extra_fields_and_unknown_entities(valid_answer, validation_context):
    answer = deepcopy(valid_answer)
    answer["debug"] = True
    answer["case"]["evidence"].append(
        {
            "claim": "Customer denied the transaction.",
            "source": "customer",
            "ref": "evidence_request:1",
            "entity_ids": ["MADE-UP-ID"],
        }
    )
    problems = validate_answer(answer, case_row(), validation_context)
    assert any("Additional properties" in problem for problem in problems)
    assert any("extra top-level field 'debug'" in problem for problem in problems)
    assert any("unknown entity MADE-UP-ID" in problem for problem in problems)
    assert any("without a request" in problem for problem in problems)


def test_fraud_episode_must_include_flagged_and_respect_cutoff_and_card(valid_answer, validation_context):
    answer = deepcopy(valid_answer)
    answer["case"].update(
        {
            "status": "closed_fraud",
            "verdict": "fraud",
            "affected_txn_ids": ["T-1", "T-FUTURE"],
            "first_suspicious_txn_id": "T-1",
            "exposure_usd": 100.0,
        }
    )
    context = deepcopy(validation_context)
    context.txn_meta["T-FUTURE"] = {
        "txn_id": "T-FUTURE",
        "ts": "2016-12-01 12:00:01",
        "amount": 25.0,
        "card_id": "OTHER-K1",
    }
    problems = validate_answer(answer, case_row(), context)
    assert any("after opened_at" in problem for problem in problems)
    assert any("belongs to OTHER-K1" in problem for problem in problems)


def test_query_windows_and_customer_claims_are_semantically_checked(valid_answer, validation_context):
    answer = deepcopy(valid_answer)
    answer["case"]["evidence"].append(
        {
            "claim": "The card window was queried through the future cutoff.",
            "source": "graph",
            "ref": ("query:get_card_window(start=2016-11-01 00:00:00, end=2016-12-02 00:00:00)"),
            "entity_ids": ["T-1"],
        }
    )
    problems = validate_answer(answer, case_row(), validation_context)
    assert any("extends beyond opened_at" in problem for problem in problems)


def test_invalid_numeric_fields_do_not_crash_the_validator(valid_answer, validation_context):
    answer = deepcopy(valid_answer)
    answer["case"]["fraud_probability"] = "not-a-number"
    answer["case"]["exposure_usd"] = "not-a-number"
    problems = validate_answer(answer, case_row(), validation_context)
    assert any("fraud_probability" in problem for problem in problems)
    assert any("exposure_usd" in problem for problem in problems)


def test_simulated_denial_authorizes_r2_without_claiming_a_customer_request_was_previously_made(
    valid_answer, validation_context
):
    answer = deepcopy(valid_answer)
    answer["case"].update(
        {
            "status": "closed_fraud",
            "verdict": "fraud",
            "affected_txn_ids": ["T-1"],
            "first_suspicious_txn_id": "T-1",
            "exposure_usd": 75,
        }
    )
    answer["case"]["evidence"].append(
        {
            "claim": "Customer states they did not authorize the transaction.",
            "source": "customer",
            "ref": "evidence_request:1",
            "entity_ids": [],
        }
    )
    answer["evidence_requests"] = [
        {
            "type": "customer_validation",
            "asked_after_step": 0,
            "assumed_response": "Simulated response: the customer did not authorize the transaction.",
        }
    ]
    answer["next_best_actions"]["final"] = [
        {"action": "BLOCK_CARD", "route": "L1", "reason": "R2: customer denied"},
        {"action": "CREATE_CASE", "route": "auto", "reason": "R2: retain evidence"},
    ]
    answer["next_best_actions"]["what_changed"] = "The final recommendation added BLOCK_CARD."
    assert validate_answer(answer, case_row(), validation_context) == []


def test_tool_count_is_checked_per_case(valid_answer, validation_context):
    answer = deepcopy(valid_answer)
    answer["tool_calls"] = 9
    problems = validate_answer(
        answer,
        case_row(),
        validation_context,
        expected_tool_calls=4,
    )
    assert any("does not match per-case count 4" in problem for problem in problems)


def test_action_policy_citations_routes_and_diff_are_strict(valid_answer, validation_context):
    answer = deepcopy(valid_answer)
    answer["next_best_actions"]["initial"][0]["reason"] = "R99: invented rule"
    answer["next_best_actions"]["final"][0]["route"] = "L1"
    answer["next_best_actions"]["what_changed"] = "nothing"
    problems = validate_answer(answer, case_row(), validation_context)
    assert any("R1-R10" in problem for problem in problems)
    assert any("must use auto" in problem for problem in problems)
    assert any("actions changed" in problem for problem in problems)


def test_sar_schema_conditions_match_false_and_true_shapes(valid_answer):
    answer = deepcopy(valid_answer)
    answer["sar"]["narrative"] = "This should be empty."
    assert schema_problems(answer)

    answer["sar"].update(
        {
            "file": True,
            "narrative": "A valid-looking narrative that is intentionally long enough for schema validation. "
            "It names no extra fact and has enough words to pass only the structural schema layer.",
            "subjects": ["C-1"],
            "total_amount_usd": 10,
            "activity_dates": ["2016-12-01", "2016-12-01"],
        }
    )
    assert schema_problems(answer) == []


def test_validate_files_applies_case_specific_expected_counts(tmp_path, valid_answer, validation_context):
    (tmp_path / "HHG-001.json").write_text(json.dumps(valid_answer), encoding="utf-8")
    findings = validate_files(
        [case_row()],
        tmp_path,
        validation_context,
        expected_tool_calls={"HHG-001": 3},
    )
    assert any("does not match per-case count 3" in problem for problem in findings["HHG-001"])


def test_unwritten_case_requires_empty_graph_id(valid_answer, validation_context):
    answer = deepcopy(valid_answer)
    answer["case"]["graph_case_id"] = "AG-HHG-001"
    problems = validate_answer(answer, case_row(), validation_context)
    assert any("unwritten case" in problem for problem in problems)


def test_graph_validator_compares_stored_answer_and_evidence_edges(
    tmp_path, valid_answer
):
    answer = deepcopy(valid_answer)
    answer["case"]["written_to_graph"] = True
    answer["case"]["graph_case_id"] = "AG-HHG-001"
    (tmp_path / "HHG-001.json").write_text(json.dumps(answer), encoding="utf-8")

    class Reader:
        def read_agent_case(self, case_id):
            assert case_id == "AG-HHG-001"
            return {
                "case_id": case_id,
                "found": True,
                "answer": answer,
                "txn_ids": [],
                "card_ids": ["C-1-K1"],
                "device_ids": [],
                "prior_case_ids": [],
            }

    assert validate_graph_files([case_row()], tmp_path, Reader()) == {
        "HHG-001": []
    }
