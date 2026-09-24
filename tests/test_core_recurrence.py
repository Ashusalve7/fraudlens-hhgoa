from __future__ import annotations

from agent.decision import is_monthly_recurring, recurring_charge_details


def test_recurrence_requires_two_prior_monthly_same_card_same_product_matches():
    current = {
        "txn_id": "T3",
        "ts": "2016-12-01 12:00:00",
        "amount": 49.0,
        "card_id": "C1-K2",
        "merchant_id": "M-9",
    }
    history = [
        {
            "txn_id": "T1",
            "ts": "2016-10-02T12:00:00Z",
            "amount": 49.01,
            "card_id": "C1-K2",
            "merchant_id": "M-9",
        },
        {
            "txn_id": "T2",
            "ts": "2016-11-01 12:00:00",
            "amount": 49.0,
            "card_id": "C1-K2",
            "merchant_id": "M-9",
        },
    ]
    details = recurring_charge_details(
        current,
        history,
        card_id="C1-K2",
        cutoff="2016-12-01 13:00:00",
    )
    assert details["is_monthly"] is True
    assert details["prior_count"] == 2
    assert details["gaps_days"] == [30.0, 30.0]
    assert is_monthly_recurring(current, history, card_id="C1-K2")


def test_recurrence_fails_closed_for_invalid_cutoff_or_trigger_timestamp():
    txn = {"amount": 10, "card_id": "C1-K1", "product_cd": "C", "ts": "not-a-time"}
    assert recurring_charge_details(txn, [], cutoff="2016-12-01")["is_monthly"] is False
    valid = {**txn, "ts": "2016-12-01"}
    assert recurring_charge_details(valid, [], cutoff="not-a-time")["is_monthly"] is False


def test_missing_merchant_marker_does_not_override_a_real_product_mismatch():
    current = {
        "txn_id": "T-N-MERCHANT",
        "ts": "2016-12-01",
        "amount": 10,
        "card_id": "C1-K1",
        "merchant_id": "_NA_",
        "product_cd": "C",
    }
    prior = [
        {**current, "txn_id": "PRIOR-1", "ts": "2016-10-02", "product_cd": "H"},
        {**current, "txn_id": "PRIOR-2", "ts": "2016-11-01", "product_cd": "H"},
    ]
    details = recurring_charge_details(current, prior, card_id="C1-K1")
    assert details["prior_count"] == 0
    assert details["is_monthly"] is False


def test_recurrence_rejects_wrong_card_wrong_product_bursts_and_future_rows():
    current = {
        "txn_id": "T4",
        "ts": "2016-12-01 12:00:00",
        "amount": 49.0,
        "card_id": "C1-K2",
        "product_cd": "C",
    }
    history = [
        {
            "txn_id": "A",
            "ts": "2016-11-30 12:00:00",
            "amount": 49,
            "card_id": "C2-K1",
            "product_cd": "C",
        },
        {
            "txn_id": "B",
            "ts": "2016-11-30 13:00:00",
            "amount": 49,
            "card_id": "C1-K2",
            "product_cd": "H",
        },
        {
            "txn_id": "C",
            "ts": "2016-12-01 11:00:00",
            "amount": 49,
            "card_id": "C1-K2",
            "product_cd": "C",
        },
        {
            "txn_id": "FUTURE",
            "ts": "2016-12-01 12:00:01",
            "amount": 49,
            "card_id": "C1-K2",
            "product_cd": "C",
        },
    ]
    details = recurring_charge_details(
        current,
        history,
        card_id="C1-K2",
        cutoff="2016-12-01 12:00:00",
    )
    assert details["is_monthly"] is False
    assert details["prior_count"] == 1
