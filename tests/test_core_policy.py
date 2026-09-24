from __future__ import annotations

import re

from agent.decision import (
    independent_evidence_count,
    next_best_actions,
    should_file_sar,
    stop_reason,
)


def names(actions):
    return [action["action"] for action in actions]


def assert_policy_citations(actions):
    assert actions
    for action in actions:
        assert re.match(r"^(?:R(?:10|[1-9])|3a|policy)\b", action["reason"])


def test_r1_verifies_a_single_weak_signal_before_any_block():
    actions = next_best_actions(
        0.60,
        75,
        "card_not_present_new_device",
        False,
        customer_denied=False,
        customer_confirmed=False,
        no_reply_24h=False,
        testing_cleared_over_100=False,
        n_independent=1,
    )
    assert "VERIFY_WITH_CUSTOMER" in names(actions)
    assert "BLOCK_CARD" not in names(actions)
    assert_policy_citations(actions)


def test_high_probability_without_independent_fraud_evidence_does_not_block():
    actions = next_best_actions(
        0.96,
        300,
        "card_not_present_new_device",
        True,
        customer_denied=False,
        customer_confirmed=False,
        no_reply_24h=False,
        testing_cleared_over_100=False,
        n_independent=2,
    )
    assert "BLOCK_CARD" not in names(actions)
    assert "VERIFY_WITH_CUSTOMER" in names(actions)
    assert_policy_citations(actions)


def test_r2_denial_blocks_and_only_meets_report_basis_when_supported():
    low = next_best_actions(
        0.5,
        100,
        "card_not_present_fraud",
        False,
        customer_denied=True,
        customer_confirmed=False,
        no_reply_24h=False,
        testing_cleared_over_100=False,
    )
    assert names(low) == ["BLOCK_CARD", "CREATE_CASE"]
    high = next_best_actions(
        0.5,
        1000.01,
        "card_not_present_fraud",
        False,
        customer_denied=True,
        customer_confirmed=False,
        no_reply_24h=False,
        testing_cleared_over_100=False,
    )
    assert "FILE_REPORT" in names(high)
    assert_policy_citations(high)


def test_r3_confirmation_closes_immediately():
    actions = next_best_actions(
        0.99,
        5000,
        "account_takeover",
        True,
        customer_denied=False,
        customer_confirmed=True,
        no_reply_24h=False,
        testing_cleared_over_100=False,
        multi_card_compromise=True,
    )
    assert names(actions) == ["CLOSE_NO_FRAUD"]
    assert_policy_citations(actions)


def test_r4_no_reply_and_r8_exposure_escalation():
    actions = next_best_actions(
        0.5,
        700,
        "none",
        False,
        customer_denied=False,
        customer_confirmed=False,
        no_reply_24h=True,
        testing_cleared_over_100=False,
    )
    assert names(actions) == ["MONITOR_CARD", "DECLINE_TRANSACTION", "ESCALATE_TO_ANALYST"]
    assert_policy_citations(actions)


def test_r5_distinguishes_pending_testing_from_a_cleared_large_purchase():
    pending = next_best_actions(
        0.2,
        10,
        "card_testing",
        False,
        customer_denied=False,
        customer_confirmed=False,
        no_reply_24h=False,
        testing_cleared_over_100=False,
    )
    cleared = next_best_actions(
        0.2,
        150,
        "card_testing",
        False,
        customer_denied=False,
        customer_confirmed=False,
        no_reply_24h=False,
        testing_cleared_over_100=True,
    )
    assert names(pending) == ["DECLINE_TRANSACTION", "STEP_UP_AUTH"]
    assert names(cleared) == ["BLOCK_CARD"]
    assert_policy_citations(pending + cleared)


def test_r6_requires_corroborated_connected_fraud_not_device_reuse_alone():
    device_reuse = next_best_actions(
        0.4,
        50,
        "none",
        True,
        customer_denied=False,
        customer_confirmed=False,
        no_reply_24h=False,
        testing_cleared_over_100=False,
        connected_fraud=False,
    )
    assert "FILE_REPORT" not in names(device_reuse)

    corroborated = next_best_actions(
        0.4,
        50,
        "none",
        True,
        customer_denied=False,
        customer_confirmed=False,
        no_reply_24h=False,
        testing_cleared_over_100=False,
        connected_fraud=True,
    )
    assert names(corroborated) == [
        "CREATE_CASE",
        "FILE_REPORT",
        "MONITOR_CONNECTED_CARDS",
    ]
    assert_policy_citations(corroborated)


def test_r7_precedes_denial_and_never_blocks():
    actions = next_best_actions(
        0.8,
        75,
        "none",
        False,
        customer_denied=True,
        customer_confirmed=False,
        no_reply_24h=False,
        testing_cleared_over_100=False,
        r7=True,
    )
    assert names(actions) == ["CREATE_CASE", "VERIFY_WITH_CUSTOMER", "WARN_CUSTOMER"]
    assert "BLOCK_CARD" not in names(actions)
    assert_policy_citations(actions)


def test_r8_conflicting_evidence_escalates_even_below_exposure_threshold():
    actions = next_best_actions(
        0.2,
        100,
        "none",
        False,
        customer_denied=False,
        customer_confirmed=False,
        no_reply_24h=False,
        testing_cleared_over_100=False,
        evidence_conflict=True,
    )
    assert names(actions) == ["ESCALATE_TO_ANALYST"]
    assert_policy_citations(actions)


def test_r9_preserves_undocumented_coordinated_pattern():
    actions = next_best_actions(
        0.4,
        100,
        "undocumented",
        True,
        customer_denied=False,
        customer_confirmed=False,
        no_reply_24h=False,
        testing_cleared_over_100=False,
        connected_fraud=True,
        coordinated=True,
    )
    assert names(actions) == ["CREATE_CASE", "FILE_REPORT", "ESCALATE_TO_ANALYST"]
    assert_policy_citations(actions)


def test_r10_blocks_all_cards_only_with_explicit_precondition():
    without_precondition = next_best_actions(
        0.9,
        100,
        "account_takeover",
        False,
        customer_denied=True,
        customer_confirmed=False,
        no_reply_24h=False,
        testing_cleared_over_100=False,
    )
    with_precondition = next_best_actions(
        0.9,
        100,
        "account_takeover",
        False,
        customer_denied=True,
        customer_confirmed=False,
        no_reply_24h=False,
        testing_cleared_over_100=False,
        multi_card_compromise=True,
    )
    assert "BLOCK_ALL_CARDS" not in names(without_precondition)
    assert "BLOCK_ALL_CARDS" in names(with_precondition)
    assert_policy_citations(with_precondition)


def test_independent_evidence_does_not_count_each_card_row_as_a_source():
    episode = [
        {"txn_id": "T1", "ts": "2016-12-01 10:00:00", "amount": 10},
        {"txn_id": "T2", "ts": "2016-12-01 10:01:00", "amount": 20},
    ]
    assert independent_evidence_count(episode_rows=episode) == 1
    assert (
        independent_evidence_count(
            episode_rows=episode,
            customer_denied=True,
            device_corroborated=True,
            similar_cases=[{"outcome": "confirmed_fraud"}],
        )
        == 4
    )


def test_sar_gate_and_stop_reason_require_independent_support():
    assert should_file_sar("fraud", 1000, "none", shared_link=True)[0] is False
    assert should_file_sar("fraud", 1000.01, "none")[0] is True
    assert should_file_sar("fraud", 100, "none", connected_fraud=True)[0] is True
    assert should_file_sar("uncertain", 3000, "none")[0] is False
    assert should_file_sar("uncertain", 3000, "none", strong_suspicion=True)[0] is True
    reason, settled = stop_reason(0.95, 1, False)
    assert not settled
    assert "independent" in reason
