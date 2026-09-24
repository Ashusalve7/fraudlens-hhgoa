from __future__ import annotations

import pytest

from agent.decision import PATTERN_ENUM, detect_pattern
from agent.features import compute_features, episode_features


def base_features(**updates):
    values = {
        "flagged_online": 0,
        "n_online_48h": 0,
        "region_new": 0,
        "home_active_72h": 0,
        "trip_like": 0,
        "oor_clone": 0,
        "mixed_channel": 0,
        "identity_anomaly": 0,
        "amt_ratio_30d": 0,
        "product_new": 0,
        "online_share_shift": 0,
        "coordinated_signal": 0,
        "connected_fraud": 0,
        "cross_customer": 0,
    }
    values.update(updates)
    return values


@pytest.mark.parametrize(
    ("features", "episode", "expected"),
    [
        (base_features(), {"testing_sequence": True}, "card_testing"),
        (
            base_features(flagged_online=1, n_online_48h=2, amt_ratio_30d=2.0),
            {},
            "card_not_present_fraud",
        ),
        (
            base_features(
                flagged_online=1,
                n_online_48h=2,
                amt_ratio_30d=2.0,
                new_device_flagged=1,
            ),
            {},
            "card_not_present_new_device",
        ),
        (
            base_features(region_new=1, home_active_72h=1, oor_clone=1),
            {},
            "out_of_region_use",
        ),
        (
            base_features(mixed_channel=1, identity_anomaly=1, ato_evidence=1),
            {},
            "account_takeover",
        ),
        (
            base_features(
                flagged_online=1,
                coordinated_signal=1,
                connected_fraud=1,
                cross_customer=1,
            ),
            {},
            "undocumented",
        ),
        (base_features(flagged_online=1, n_online_48h=1, online_anomaly=1), {}, "none"),
        (base_features(flagged_online=1, n_online_48h=20), {}, "none"),
        (
            base_features(region_new=1, home_active_72h=1, trip_like=1, oor_clone=0),
            {},
            "none",
        ),
    ],
)
def test_pattern_registry_selects_only_evidence_backed_branches(features, episode, expected):
    pattern, reason = detect_pattern(features, episode)
    assert pattern == expected
    assert pattern in PATTERN_ENUM
    assert reason.strip()


def test_card_testing_precedes_coordinated_ring_and_channel_fallbacks():
    features = base_features(
        flagged_online=1,
        coordinated_signal=1,
        connected_fraud=1,
        cross_customer=1,
    )
    assert detect_pattern(features, {"testing_sequence": True})[0] == "card_testing"


def test_compute_features_excludes_own_card_and_normal_identity_match():
    txn = {
        "txn_id": "T1",
        "ts": "2016-12-01 10:00:00",
        "amount": 100,
        "channel": "online",
        "card_id": "C1-K1",
        "M1": 1,
    }
    device = {
        "cards": [{"card_id": "C1-K1"}],
        "customers": [{"customer_id": "C1"}],
        "prior_cases": [],
    }
    result = compute_features(
        {"txn": txn, "card": {"card_id": "C1-K1"}},
        [txn],
        device,
        opened_at="2016-12-01 12:00:00",
    )
    assert result["device_shared_cards_7d"] == 0
    assert result["m1_not_T"] == 0
    assert result["identity_anomaly"] == 0


def test_numeric_float_identity_mismatch_is_supported():
    txn = {
        "txn_id": "T-M1",
        "ts": "2016-12-01 10:00:00",
        "amount": 100,
        "channel": "online",
        "M1": 0.0,
    }
    result = compute_features(
        {"txn": txn},
        [txn],
        {},
        opened_at="2016-12-01 12:00:00",
    )
    assert result["m1_not_T"] == 1
    assert result["identity_anomaly"] == 1


def test_episode_features_respect_48_hour_and_40_minute_boundaries():
    t0 = "2016-12-10 12:00:00"
    rows = [
        {"txn_id": "near1", "ts": "2016-12-10 11:20:00", "amount": 450, "channel": "online"},
        {"txn_id": "near2", "ts": "2016-12-10 11:30:00", "amount": 450, "channel": "online"},
        {"txn_id": "near3", "ts": "2016-12-10 11:40:00", "amount": 450, "channel": "online"},
        {"txn_id": "edge", "ts": "2016-12-10 12:40:00", "amount": 450, "channel": "online"},
        {"txn_id": "outside", "ts": "2016-12-12 12:00:01", "amount": 450, "channel": "online"},
    ]
    result = episode_features(rows, rows, t0, cutoff="2016-12-13 00:00:00")
    assert result["near_threshold_burst_40m"] == 1
    assert result["n_online_48h"] == 4
