"""Inference-time features shared by the runner and offline evaluation.

Every timestamp-sensitive feature is bounded by the case's ``opened_at`` when
one is supplied.  The function accepts the old Evidence-shaped arguments and
also tolerates the normalized row dictionaries used by unit tests.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from math import isfinite
from typing import Any, Iterable, Mapping

try:  # package import
    from .episodes import (
        is_new_device,
        is_proxy,
        parse_ts,
        rows_at_cutoff,
        txn_amount,
        txn_channel,
        txn_device_id,
        txn_id,
        txn_ts,
    )
except ImportError:  # runner.py adds agent/ to sys.path and imports top-level
    from episodes import (  # type: ignore
        is_new_device,
        is_proxy,
        parse_ts,
        rows_at_cutoff,
        txn_amount,
        txn_channel,
        txn_device_id,
        txn_id,
        txn_ts,
    )


def _dt(s: Any) -> datetime | None:
    return parse_ts(s)


def _float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if isfinite(result) else default


def _int(value: Any, default: int = 0) -> int:
    return int(_float(value, float(default)))


def _mean(values: Iterable[float], default: float = 0.0) -> float:
    values = list(values)
    return sum(values) / len(values) if values else default


def _mode(values: Iterable[str]) -> str:
    values = [v for v in values if v]
    return max(set(values), key=values.count) if values else ""


def _field(row: Mapping[str, Any], *keys: str, default: Any = "") -> Any:
    for key in keys:
        if key in row and row[key] not in (None, "", "_NA_"):
            return row[key]
    return default


def _within(ts: datetime | None, start: datetime, end: datetime) -> bool:
    return ts is not None and start <= ts <= end


def compute_features(
    ctx: Mapping[str, Any],
    card_rows: Iterable[Mapping[str, Any]],
    dev: Mapping[str, Any] | None = None,
    *,
    opened_at: datetime | str | None = None,
    cutoff: datetime | str | None = None,
) -> dict[str, Any]:
    """Compute the production feature row.

    The first sixteen keys are the serialized calibrator contract.  Additional
    keys are deterministic detector signals and are ignored by the calibrator
    unless a future model explicitly versions them in.
    """
    txn = dict((ctx or {}).get("txn") or {})
    if not txn:
        raise ValueError("transaction context is required")
    t0 = _dt(_field(txn, "ts", "timestamp", "TransactionDT"))
    if t0 is None:
        raise ValueError("flagged transaction has no valid timestamp")
    limit = _dt(opened_at if opened_at is not None else cutoff)
    if limit is None:
        limit = t0
    source_rows = [dict(r) for r in (card_rows or [])]
    visible = rows_at_cutoff(source_rows, limit)
    # The context is authoritative for the trigger.  A graph adapter can omit
    # it from a card-window response, so add it after applying the cutoff.
    if txn_id(txn) and not any(txn_id(r) == txn_id(txn) for r in visible):
        if t0 <= limit:
            visible.append(dict(txn))
    visible.sort(key=lambda r: (txn_ts(r) or datetime.max, txn_id(r)))

    near_start = t0 - timedelta(hours=24)
    near_end = min(t0 + timedelta(hours=24), limit)
    near = [r for r in visible if _within(txn_ts(r), near_start, near_end)]
    prior30_start = t0 - timedelta(days=30)
    hist30 = [r for r in visible if _within(txn_ts(r), prior30_start, t0) and txn_ts(r) != t0]
    hist60 = [r for r in visible if _within(txn_ts(r), t0 - timedelta(days=60), t0) and txn_ts(r) != t0]
    prior = [r for r in visible if txn_ts(r) is not None and txn_ts(r) < t0]
    w1h = [r for r in visible if _within(txn_ts(r), t0 - timedelta(hours=1), t0)]

    amount = txn_amount(txn)
    hist_amounts = [txn_amount(r) for r in hist30]
    hist_mean = _mean(hist_amounts, 0.0)
    amount_ratio = amount / hist_mean if hist_mean > 0 else 0.0
    product = str(_field(txn, "product_cd", "ProductCD", default=""))
    prior_products = {str(_field(r, "product_cd", "ProductCD", default="")) for r in hist30}
    product_new = int(bool(hist30) and product not in prior_products)

    small_auth = [
        r for r in w1h
        if txn_channel(r) == "online" and txn_amount(r) < 5.0
    ]
    near_online = [r for r in near if txn_channel(r) == "online"]
    new_share = _mean([1.0 if is_new_device(r) else 0.0 for r in near_online], 0.0)
    proxy_share = _mean([1.0 if is_proxy(r) else 0.0 for r in near_online], 0.0)
    flagged_new = int(is_new_device(txn))
    flagged_proxy = int(is_proxy(txn))

    dev = dict(dev or {})
    device_cards: set[str] = set()
    for row in dev.get("cards", []) or []:
        if isinstance(row, Mapping):
            value = _field(row, "card_id", "id", "v_id", default="")
        else:
            value = row
        if value not in (None, "", "_NA_"):
            device_cards.add(str(value))
    for row in dev.get("txns", []) or []:
        if isinstance(row, Mapping):
            value = _field(row, "card_id", "CardID", default="")
            if value not in (None, "", "_NA_"):
                device_cards.add(str(value))
    own_card = str(_field(txn, "card_id", "cardId", default=""))
    if not own_card:
        own_card = str(_field(ctx, "card_id", default=""))
    device_cards.discard(own_card)
    if not device_cards and dev.get("n_cards") is not None:
        device_cards = {f"reported-card-{i}" for i in range(max(_int(dev.get("n_cards")) - 1, 0))}
    device_customers: set[str] = set()
    for row in dev.get("customers", []) or []:
        if isinstance(row, Mapping):
            value = _field(row, "customer_id", "id", "v_id", default="")
        else:
            value = row
        if value not in (None, "", "_NA_"):
            device_customers.add(str(value))
    prior_cases = [dict(r) for r in (dev.get("prior_cases", []) or []) if isinstance(r, Mapping)]
    connected_fraud_cases = [
        r for r in prior_cases
        if str(_field(r, "outcome", default="")).lower() == "confirmed_fraud"
    ]
    connected_corroboration = bool(connected_fraud_cases and (len(device_cards) >= 1 or len(device_customers) >= 2))

    region = str(_field(txn, "addr1", "region", default=""))
    prior_regions = {str(_field(r, "addr1", "region", default="")) for r in hist60}
    prior_regions.discard("")
    region_new = int(bool(region) and bool(hist60) and region not in prior_regions)
    after72 = [
        r for r in visible
        if _within(txn_ts(r), t0, t0 + timedelta(hours=72))
        and str(_field(r, "addr1", "region", default="")) == region
    ]
    home_active = int(any(
        _within(txn_ts(r), t0 - timedelta(hours=72), min(t0 + timedelta(hours=72), limit))
        and str(_field(r, "addr1", "region", default="")) not in {"", region}
        for r in visible
    ))
    region_dates = {txn_ts(r).date() for r in visible if txn_ts(r) and str(_field(r, "addr1", "region", default="")) == region}
    region_days = (max(region_dates) - min(region_dates)).days + 1 if region_dates else 0
    trip_like = int(bool(home_active and region_days >= 3 and region_new))

    hist_online = _mean([1.0 if txn_channel(r) == "online" else 0.0 for r in hist30], 0.0)
    window_online = _mean([1.0 if txn_channel(r) == "online" else 0.0 for r in near], 0.0)
    online_shift = window_online - hist_online

    p_emails = [str(_field(r, "p_email", "P_emaildomain", default="")) for r in hist60]
    p_emails = [p for p in p_emails if p and p not in {"_NA_", "nan"}]
    current_email = str(_field(txn, "p_email", "P_emaildomain", default=""))
    email_mode = _mode(p_emails)
    email_changed = int(bool(current_email and current_email not in {"", "_NA_", "nan"} and current_email != email_mode))

    m_flags = str(_field(txn, "m_flags", "M_flags", default=""))
    m1 = ""
    for part in m_flags.split("|"):
        if part.startswith("M1="):
            m1 = part[3:]
    m1_not_t = int(bool(m1) and m1 != "T")

    n_online_48h = sum(
        1 for r in visible
        if txn_channel(r) == "online" and _within(txn_ts(r), t0 - timedelta(hours=48), min(t0 + timedelta(hours=48), limit))
    )
    online_identity_anomaly = bool(flagged_new or flagged_proxy or new_share > 0 or proxy_share > 0)
    mixed_channel = int(len({txn_channel(r) for r in near}) >= 2)
    identity_anomaly = int(
        online_identity_anomaly
        or m1_not_t
        or email_changed
        or any(str(_field(r, "m_flags", default="")) for r in near)
    )
    online_anomaly = int(
        n_online_48h >= 2
        and (amount_ratio >= 2.0 or product_new or online_shift >= 0.25 or online_identity_anomaly)
    )
    near_threshold = [
        r for r in visible
        if txn_channel(r) == "online" and 400.0 <= txn_amount(r) < 500.0
        and _within(txn_ts(r), t0 - timedelta(hours=1), min(t0 + timedelta(hours=1), limit))
    ]
    coordinated_signal = int(
        connected_corroboration
        and (len(device_cards) >= 2 or len(device_customers) >= 2)
    )

    result: dict[str, Any] = {
        # Required calibrator fields.
        "flagged_amount": amount,
        "flagged_online": int(txn_channel(txn) == "online"),
        "flagged_risk": _float(_field(txn, "risk_score", default=0.0)),
        "n_small_auth_1h": len(small_auth),
        "amt_ratio_30d": amount_ratio,
        "product_new": product_new,
        "new_dev_share_24h": new_share,
        "proxy_share_24h": proxy_share,
        "device_shared_cards_7d": len(device_cards),
        "region_new": region_new,
        "region_new_n_72h": len(after72),
        "home_active_72h": home_active,
        "online_share_shift": online_shift,
        "pemail_changed": email_changed,
        "m1_not_T": m1_not_t,
        "n_txn_24h": len(near),
        # Detector/evaluation signals.  They are deliberately explicit rather
        # than hidden in channel fallbacks.
        "new_device_flagged": flagged_new,
        "proxy_flagged": flagged_proxy,
        "n_online_48h": n_online_48h,
        "online_burst_48h": int(n_online_48h >= 2),
        "online_anomaly": online_anomaly,
        "near_threshold_burst_40m": int(len(near_threshold) >= 3),
        "mixed_channel": mixed_channel,
        "identity_anomaly": identity_anomaly,
        "ato_evidence": int(mixed_channel and identity_anomaly and (online_shift <= -0.25 or product_new or amount_ratio >= 2.0)),
        "region_days": region_days,
        "trip_like": trip_like,
        "oor_clone": int(region_new and home_active and not trip_like),
        "connected_fraud_cases": len(connected_fraud_cases),
        "connected_corroboration": int(connected_corroboration),
        "coordinated_signal": coordinated_signal,
        "cross_customer": int(len(device_customers) >= 2),
        "device_id": txn_device_id(txn) or str(_field(dev, "device_id", default="")),
    }
    # Ensure all numeric values are JSON/Parquet friendly.
    for key, value in list(result.items()):
        if isinstance(value, float) and not isfinite(value):
            result[key] = 0.0
    return result


def episode_features(
    episode_rows: Iterable[Mapping[str, Any]],
    card_rows: Iterable[Mapping[str, Any]],
    t0_ts: datetime | str,
) -> dict[str, Any]:
    """Return pattern-specific signals for a candidate episode."""
    t0 = _dt(t0_ts)
    episode = [dict(r) for r in episode_rows or []]
    rows = [dict(r) for r in card_rows or []]
    prior = [r for r in rows if t0 and txn_ts(r) and txn_ts(r) < t0]
    online = [r for r in episode if txn_channel(r) == "online"]
    small = [r for r in online if txn_amount(r) < 5.0]
    testing_sequence = False
    testing_large_amount = 0.0
    if t0:
        ordered = sorted((r for r in online if txn_ts(r)), key=txn_ts)
        for i, start in enumerate(small):
            start_ts = txn_ts(start)
            if start_ts is None:
                continue
            cluster = [r for r in small[i:] if txn_ts(r) and (txn_ts(r) - start_ts).total_seconds() <= 3600]
            if len(cluster) < 3:
                continue
            last = max(txn_ts(r) for r in cluster if txn_ts(r))
            threshold = max(5.0, max(txn_amount(r) for r in cluster) * 1.25)
            follow = [r for r in ordered if txn_ts(r) and last < txn_ts(r) <= last + timedelta(hours=24) and txn_amount(r) >= threshold]
            if follow:
                testing_sequence = True
                testing_large_amount = max(txn_amount(r) for r in follow)
                break
    regs = [str(_field(r, "addr1", "region", default="")) for r in episode]
    regs = [r for r in regs if r]
    prior_regs = [str(_field(r, "addr1", "region", default="")) for r in prior]
    prior_share = 0.0
    if regs and prior_regs:
        prior_share = sum(1 for r in prior_regs if r in set(regs)) / len(prior_regs)
    channels = {txn_channel(r) for r in episode}
    near_identity = any(is_new_device(r) or is_proxy(r) or str(_field(r, "m_flags", default="")) for r in episode)
    region = regs[0] if regs else ""
    region_rows = [r for r in rows if str(_field(r, "addr1", "region", default="")) == region]
    region_dates = {txn_ts(r).date() for r in region_rows if txn_ts(r)}
    days = (max(region_dates) - min(region_dates)).days + 1 if region_dates else 0
    home = any(str(_field(r, "addr1", "region", default="")) not in {"", region} for r in prior)
    device = txn_device_id(episode[0]) if episode else ""
    coordinated = any(
        any(bool(r.get(k)) for k in ("coordinated", "connected_fraud", "same_ring"))
        for r in episode
    )
    return {
        "prior_reg_share": float(prior_share),
        "ep_online": (len(online) / len(episode)) if episode else 0.0,
        "n_small_in_episode": len(small),
        "n_small_auth_1h": sum(1 for r in small if txn_ts(r) and t0 and abs((txn_ts(r) - t0).total_seconds()) <= 3600),
        "n_online_48h": len(online),
        "online_burst_48h": int(len(online) >= 2),
        "testing_sequence": testing_sequence,
        "testing_large_amount": testing_large_amount,
        "new_device_share": (sum(1 for r in online if is_new_device(r)) / len(online)) if online else 0.0,
        "proxy_share": (sum(1 for r in online if is_proxy(r)) / len(online)) if online else 0.0,
        "mixed_channel": int(len(channels) >= 2),
        "identity_anomaly": int(near_identity),
        "near_threshold_burst_40m": int(sum(1 for r in online if 400 <= txn_amount(r) < 500) >= 3),
        "region_days": days,
        "home_active": int(home),
        "trip_like": int(bool(home and days >= 3)),
        "coordinated": int(coordinated),
        "device_id": device,
    }


__all__ = ["compute_features", "episode_features"]
