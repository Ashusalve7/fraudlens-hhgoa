from __future__ import annotations

from agent.sar import build_sar


def rows():
    return [
        {
            "txn_id": "T1",
            "ts": "2016-12-01 10:00:00",
            "amount": 400,
            "channel": "online",
            "addr1": "R1",
        },
        {
            "txn_id": "T2",
            "ts": "2016-12-03 11:00:00",
            "amount": 700,
            "channel": "online",
            "addr1": "R1",
        },
    ]


def render(file_flag=True, **kwargs):
    params = {
        "file_flag": file_flag,
        "reason": "3a: confirmed suspicious activity",
        "case": {"case_id": "HHG-001"},
        "customer_id": "C1",
        "card_id": "C1-K1",
        "affected": ["T1", "T2"],
        "exposure": 1100,
        "txn": rows()[0],
        "pattern": "card_not_present_fraud",
        "device": {},
        "episode_rows": rows(),
    }
    params.update(kwargs)
    return build_sar(**params)


def test_false_sar_is_exactly_empty_even_when_other_facts_exist():
    sar = render(
        False,
        reason="3a: case only",
        connected_fraud=True,
        customer_asked=True,
        evidence_requests=[{"assumed_response": "Customer confirmed."}],
    )
    assert sar == {
        "file": False,
        "reason": "3a: case only",
        "narrative": "",
        "subjects": [],
        "total_amount_usd": 0,
        "activity_dates": [],
    }


def test_true_sar_uses_only_affected_rows_and_actual_dates_and_total():
    extra = {
        "txn_id": "T-EXTRA",
        "ts": "2016-12-04 12:00:00",
        "amount": 9999,
        "channel": "online",
    }
    sar = render(episode_rows=[*rows(), extra])
    assert sar["file"] is True
    assert sar["total_amount_usd"] == 1100.0
    assert sar["activity_dates"] == ["2016-12-01", "2016-12-03"]
    assert "T-EXTRA" not in sar["narrative"]


def test_threshold_customer_and_shared_link_claims_are_conditional():
    low = render(
        affected=["T1"],
        exposure=400,
        episode_rows=rows(),
        customer_denied=True,
    )
    assert "$1,000 reporting threshold" not in low["narrative"]
    assert "case trigger explicitly reported" in low["narrative"]
    assert "No shared device" in low["narrative"]

    high = render(customer_asked=True, evidence_requests=[{"assumed_response": "No reply was simulated."}])
    assert "exceeds the policy's $1,000 reporting threshold" in high["narrative"]
    assert "evidence request recorded" in high["narrative"]
    assert "case trigger explicitly reported" not in high["narrative"]

    connected = render(
        affected=["T1"],
        exposure=400,
        connected_fraud=True,
        connected_fraud_cases=[{"case_id": "CC-1", "outcome": "confirmed_fraud"}],
        connected_cards=["C2-K1"],
        device={"device_id": "DP-1"},
    )
    assert "C2-K1" in connected["narrative"]
    assert "corroborated connected-card fraud" in connected["narrative"]
    assert "threshold" not in connected["narrative"].lower()
    assert "C2-K1" in connected["subjects"]


def test_corroboration_without_an_entity_does_not_invent_a_device_link():
    sar = render(
        affected=["T1"],
        exposure=400,
        connected_fraud=True,
        connected_fraud_cases=[{"case_id": "CC-1", "outcome": "confirmed_fraud"}],
        device={},
    )
    assert "links device profile" not in sar["narrative"]
    assert "corroborated connected-card fraud" in sar["narrative"]
    assert sar["subjects"] == ["C1", "C1-K1"]


def test_filed_sar_rejects_missing_dates_instead_of_inventing_them():
    row = rows()[0]
    row["ts"] = "not-a-time"
    try:
        render(affected=["T1"], txn=row, episode_rows=[row])
    except ValueError as exc:
        assert "timestamps" in str(exc)
    else:
        raise AssertionError("missing SAR dates must be rejected")
