from __future__ import annotations

from agent.episodes import build_episode, episode_bounds, episode_ids, rows_at_cutoff


def txn(txn_id: str, ts: str, amount: float, channel: str = "online", **extra):
    return {
        "txn_id": txn_id,
        "ts": ts,
        "amount": amount,
        "channel": channel,
        "card_id": "C1-K1",
        **extra,
    }


def test_cutoff_is_inclusive_and_rejects_aware_naive_mix():
    rows = [
        txn("before", "2016-12-01T11:59:59Z", 1),
        txn("edge", "2016-12-01 12:00:00", 2),
        txn("future", "2016-12-01 12:00:00.000001", 3),
        txn("unknown", "not-a-time", 4),
    ]
    visible = rows_at_cutoff(rows, "2016-12-01T12:00:00Z")
    assert episode_ids(visible) == ["before", "edge"]


def test_invalid_cutoff_fails_closed():
    assert rows_at_cutoff([txn("T1", "2016-12-01", 1)], "not-a-time") == []
    assert (
        build_episode(
            txn("T1", "2016-12-01", 1),
            [],
            "card_not_present_fraud",
            {},
            cutoff="not-a-time",
        )
        == []
    )


def test_flagged_after_cutoff_cannot_create_an_episode():
    flagged = txn("future-trigger", "2016-12-02 10:00:00", 50)
    assert build_episode(flagged, [flagged], "card_not_present_fraud", {}, cutoff="2016-12-01") == []


def test_card_testing_uses_one_hour_and_24_hour_boundaries_without_ordinary_rows():
    flagged = txn("large", "2016-12-01 11:30:00", 20)
    rows = [
        txn("small-1", "2016-12-01 10:00:00", 1),
        txn("small-2", "2016-12-01 10:30:00", 2),
        txn("small-3", "2016-12-01 10:59:00", 3),
        flagged,
        txn("ordinary", "2016-12-01 13:30:00", 50),
    ]
    episode = build_episode(
        flagged,
        rows,
        "card_testing",
        {"testing_sequence": True},
        cutoff="2016-12-01 14:00:00",
    )
    assert episode_ids(episode) == ["small-1", "small-2", "small-3", "large"]
    assert episode_bounds(episode) == (
        "small-1",
        "2016-12-01",
        "2016-12-01",
    )


def test_card_testing_does_not_attach_an_unrelated_distant_sequence():
    flagged = txn("trigger", "2016-12-03 12:00:00", 20)
    rows = [
        flagged,
        txn("old-small-1", "2016-12-01 11:00:00", 1),
        txn("old-small-2", "2016-12-01 11:30:00", 2),
        txn("old-small-3", "2016-12-01 12:00:00", 3),
        txn("old-large", "2016-12-01 13:00:00", 20),
    ]
    episode = build_episode(
        flagged,
        rows,
        "card_testing",
        {"testing_sequence": True},
        cutoff="2016-12-03 13:00:00",
    )
    assert episode_ids(episode) == ["trigger"]


def test_cnp_episode_excludes_rows_beyond_48_hours():
    flagged = txn("flagged", "2016-12-10 12:00:00", 100, id_15="New", device_id="DP-1")
    rows = [
        txn("inside", "2016-12-12 11:59:59", 90, id_15="New", device_id="DP-1"),
        flagged,
        txn("outside", "2016-12-12 12:00:01", 90, id_15="New", device_id="DP-1"),
    ]
    episode = build_episode(
        flagged,
        rows,
        "card_not_present_new_device",
        {"n_online_48h": 2, "online_burst_48h": True},
        cutoff="2016-12-13",
    )
    assert episode_ids(episode) == ["flagged", "inside"]


def test_out_of_region_episode_never_pulls_home_activity():
    flagged = txn("flagged", "2016-12-10 12:00:00", 100, channel="in_person", addr1="R2")
    rows = [
        flagged,
        txn("same-region", "2016-12-10 13:00:00", 50, channel="in_person", addr1="R2", anomalous=True),
        txn("home", "2016-12-10 14:00:00", 50, channel="in_person", addr1="R1", anomalous=True),
    ]
    episode = build_episode(
        flagged,
        rows,
        "out_of_region_use",
        {"oor_clone": 1, "trip_like": 0},
        cutoff="2016-12-11",
    )
    assert episode_ids(episode) == ["flagged", "same-region"]
