"""Fraud-episode construction.

An episode is deliberately *not* a fixed time window.  The graph queries return
cards' histories, which means that a window normally contains a mixture of
ordinary and suspicious activity.  This module starts at the flagged transaction
and grows an episode only when a row has an anomaly signal appropriate to the
selected pattern.  It is pure Python so that it can be used by both the online
runner and offline evaluation.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta
from math import isfinite
from typing import Any

SMALL_AUTH_LIMIT = 5.0
TESTING_WINDOW = timedelta(hours=1)
TESTING_FOLLOW_UP = timedelta(hours=24)
PATTERN_WINDOW = timedelta(hours=48)
ATO_WINDOW = timedelta(hours=72)
OOR_WINDOW = timedelta(hours=72)


def parse_ts(value: Any) -> datetime | None:
    """Parse a source timestamp and normalize aware values to naive UTC.

    The sponsor files are naive UTC.  Normalizing ISO-8601 offsets here keeps
    cutoff comparisons deterministic instead of leaking ``aware``/``naive``
    comparison errors from graph adapters or tests.
    """
    if value is None or value == "" or value == "_NA_":
        return None
    if isinstance(value, datetime):
        parsed = value
    elif hasattr(value, "to_pydatetime"):
        try:
            result = value.to_pydatetime()
        except Exception:
            result = None
        if not isinstance(result, datetime):
            return None
        parsed = result
    else:
        text = str(value).strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d %H:%M:%S"):
                try:
                    parsed = datetime.strptime(text, fmt)
                    break
                except ValueError:
                    continue
            else:
                return None
    if parsed.tzinfo is not None:
        return parsed.astimezone(UTC).replace(tzinfo=None)
    return parsed


def _number(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if isfinite(result) else default


def txn_id(row: Mapping[str, Any]) -> str:
    for key in ("txn_id", "transaction_id", "TransactionID", "txnId", "id"):
        value = row.get(key)
        if value not in (None, "", "_NA_"):
            return str(value)
    return ""


def txn_ts(row: Mapping[str, Any]) -> datetime | None:
    for key in ("ts", "timestamp", "TransactionDT", "event_time", "opened_at"):
        parsed = parse_ts(row.get(key))
        if parsed is not None:
            return parsed
    return None


def txn_amount(row: Mapping[str, Any]) -> float:
    for key in ("amount", "TransactionAmt", "transaction_amount", "amt"):
        if key in row:
            return abs(_number(row.get(key)))
    return 0.0


def txn_channel(row: Mapping[str, Any]) -> str:
    value = str(row.get("channel") or row.get("Channel") or "").strip().lower()
    if value in {"in_person", "inperson", "card_present", "card-present", "present"}:
        return "in_person"
    if value in {"online", "remote", "ecommerce", "e-commerce"}:
        return "online"
    # ProductCD W is the sponsor's card-present marker when channel is absent.
    product = str(row.get("product_cd") or row.get("ProductCD") or "").strip().upper()
    return "in_person" if product == "W" else "online"


def txn_device_id(row: Mapping[str, Any]) -> str:
    for key in ("device_id", "deviceId", "device_profile_id", "device"):
        value = row.get(key)
        if value not in (None, "", "_NA_", "nan"):
            return str(value)
    # A device query uses ``id`` for the device vertex.  A transaction query
    # normally has txn_id, so this fallback is safe for the graph shape.
    value = row.get("id")
    if value not in (None, "", "_NA_", "nan") and str(value).startswith("DP-"):
        return str(value)
    return ""


def is_new_device(row: Mapping[str, Any]) -> bool:
    value = str(row.get("id_15") or row.get("id15") or "").strip().lower()
    return value == "new"


def is_proxy(row: Mapping[str, Any]) -> bool:
    value = str(row.get("id_23") or row.get("id23") or "").strip().upper()
    return any(token in value for token in ("ANONYMOUS", "HIDDEN", "PROXY"))


def _match_value_is_anomaly(value: Any) -> bool:
    if value in (None, "", "_NA_"):
        return False
    if isinstance(value, bool):
        return not value
    if isinstance(value, (int, float)):
        return value == 0
    text = str(value).strip().lower()
    if text in {"f", "false", "n", "no", "mismatch"}:
        return True
    try:
        return float(text) == 0.0
    except (TypeError, ValueError):
        return False


def is_match_anomaly(row: Mapping[str, Any]) -> bool:
    """Return whether an M1-M9 identity-match field is a mismatch.

    Vesta's source uses 0/1 while normalized graph fixtures often spell the
    values F/T.  A present *matching* flag is not an anomaly and must not turn
    an ordinary mixed-channel sequence into account takeover.
    """
    for index in range(1, 10):
        if _match_value_is_anomaly(row.get(f"M{index}")):
            return True
    flags = row.get("m_flags", row.get("M_flags", ""))
    for part in str(flags or "").split("|"):
        key, separator, value = part.partition("=")
        if (
            separator
            and key.strip().upper() in {f"M{i}" for i in range(1, 10)}
            and _match_value_is_anomaly(value)
        ):
            return True
    return False


def is_explicit_anomaly(row: Mapping[str, Any]) -> bool:
    for key in ("anomalous", "is_anomalous", "suspicious", "fraud_related", "is_fraud"):
        value = row.get(key)
        if value is True or str(value).strip().lower() in {"1", "true", "yes"}:
            return True
    return False


def _unique_rows(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Copy and de-duplicate rows while retaining chronological order."""
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source in rows:
        row = dict(source)
        rid = txn_id(row)
        # Rows without an ID cannot be safely attached to an episode.  The
        # caller adds the flagged row separately when necessary.
        key = rid or repr(sorted(row.items()))
        if key in seen:
            continue
        seen.add(key)
        result.append(row)
    result.sort(key=lambda r: (txn_ts(r) or datetime.max, txn_id(r)))
    return result


def rows_at_cutoff(
    rows: Iterable[Mapping[str, Any]],
    cutoff: datetime | str | None,
    *,
    flagged: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return rows visible at the investigation cutoff.

    Graph responses are treated as untrusted: even if a remote query accidentally
    returns a future row, it is removed here.  A flagged transaction is retained
    only when its own timestamp is at or before the cutoff.
    """
    limit = parse_ts(cutoff)
    if cutoff is not None and limit is None:
        return []
    result: list[dict[str, Any]] = []
    for row in rows:
        ts = txn_ts(row)
        if limit is not None and (ts is None or ts > limit):
            continue
        result.append(dict(row))
    if flagged is not None:
        fts = txn_ts(flagged)
        if limit is None or (fts is not None and fts <= limit):
            fid = txn_id(flagged)
            if fid and not any(txn_id(r) == fid for r in result):
                result.append(dict(flagged))
    return _unique_rows(result)


def _distance(ts: datetime | None, center: datetime | None) -> float:
    if ts is None or center is None:
        return float("inf")
    return abs((ts - center).total_seconds())


def _nearest_cluster(
    rows: list[dict[str, Any]],
    center: datetime,
    *,
    predicate,
    max_rows: int = 4,
    max_span: timedelta = timedelta(hours=48),
) -> list[dict[str, Any]]:
    """Choose a compact cluster around the flagged event.

    This helper is used only after a pattern/anomaly predicate has identified
    online activity.  It avoids the old behavior of returning every row in a
    broad +/- window.
    """
    candidates = [
        r for r in rows if predicate(r) and _distance(txn_ts(r), center) <= max_span.total_seconds()
    ]
    if not candidates:
        return []
    candidates.sort(key=lambda r: _distance(txn_ts(r), center))
    selected: list[dict[str, Any]] = []
    for row in candidates:
        if len(selected) >= max_rows:
            break
        # Keep a cluster compact.  A later row is accepted only if it is close
        # to something already selected; the first row is always the center.
        if selected and _distance(txn_ts(row), center) > max_span.total_seconds():
            continue
        selected.append(row)
    return _unique_rows(selected)


def _testing_episode(
    flagged: Mapping[str, Any],
    rows: list[dict[str, Any]],
    features: Mapping[str, Any],
) -> list[dict[str, Any]]:
    center = txn_ts(flagged)
    if center is None:
        return [dict(flagged)]
    ordered = sorted(rows, key=lambda r: (txn_ts(r) or datetime.max, txn_id(r)))
    small = [
        r
        for r in ordered
        if txn_channel(r) == "online"
        and txn_amount(r) < SMALL_AUTH_LIMIT
        and _distance(txn_ts(r), center) <= PATTERN_WINDOW.total_seconds()
    ]
    best: list[dict[str, Any]] = []
    best_score: tuple[int, float] | None = None
    for i, start in enumerate(small):
        cluster = [r for r in small[i:] if (txn_ts(r) - (txn_ts(start) or center)) <= TESTING_WINDOW]
        if len(cluster) < 3:
            continue
        last_small = max((txn_ts(r) or center for r in cluster), default=center)
        threshold = max(SMALL_AUTH_LIMIT, max(txn_amount(r) for r in cluster) * 1.25)
        follow = [
            r
            for r in ordered
            if txn_ts(r) is not None
            and last_small < txn_ts(r) <= last_small + TESTING_FOLLOW_UP
            and _distance(txn_ts(r), center) <= PATTERN_WINDOW.total_seconds()
            and txn_channel(r) == "online"
            and txn_amount(r) >= threshold
        ]
        if not follow:
            continue
        large = min(follow, key=lambda r: _distance(txn_ts(r), center))
        episode = _unique_rows(cluster + [large])
        ids = {txn_id(r) for r in episode}
        # Prefer a sequence containing the flagged transaction, then the one
        # closest to it.  The explicit feature is an escape hatch for a graph
        # response that has already identified the sequence.
        contains = 1 if txn_id(flagged) in ids else 0
        score = (-contains, _distance(txn_ts(large), center))
        if best_score is None or score < best_score:
            best, best_score = episode, score
    if best:
        return _unique_rows(best + [flagged])
    if bool(features.get("testing_sequence")):
        return [dict(flagged)]
    return [dict(flagged)]


def _online_episode(
    flagged: Mapping[str, Any],
    rows: list[dict[str, Any]],
    features: Mapping[str, Any],
    *,
    new_device: bool,
) -> list[dict[str, Any]]:
    center = txn_ts(flagged)
    if center is None:
        return [dict(flagged)]
    all_rows = [r for r in rows if txn_ts(r) is not None]
    online = [
        r
        for r in all_rows
        if txn_channel(r) == "online"
        and abs((txn_ts(r) or center) - center).total_seconds() <= PATTERN_WINDOW.total_seconds()
    ]
    if not online:
        return [dict(flagged)]
    product = str(flagged.get("product_cd") or flagged.get("ProductCD") or "")
    device = txn_device_id(flagged)
    burst_n = int(features.get("n_online_48h") or features.get("online_burst_48h") or len(online))
    burst = bool(features.get("online_burst_48h") or burst_n >= 2)

    def anomalous(row: Mapping[str, Any]) -> bool:
        if is_explicit_anomaly(row):
            return True
        if new_device and (is_new_device(row) or is_proxy(row) or (device and txn_device_id(row) == device)):
            return True
        if (
            product
            and str(row.get("product_cd") or row.get("ProductCD") or "") not in {"", product}
            and bool(features.get("product_new"))
        ):
            return True
        if bool(features.get("amt_ratio_30d") and _number(features.get("amt_ratio_30d")) >= 2.0):
            # A high amount ratio is evidence for the episode, but only when the
            # row is close enough to the trigger to be part of the same burst.
            return _distance(txn_ts(row), center) <= PATTERN_WINDOW.total_seconds()
        if bool(features.get("online_share_shift") and _number(features.get("online_share_shift")) >= 0.25):
            return _distance(txn_ts(row), center) <= PATTERN_WINDOW.total_seconds()
        return False

    suspicious = [r for r in online if txn_id(r) == txn_id(flagged) or anomalous(r)]
    # A 2-4 transaction burst is itself the sponsor's CNP anomaly.  Limit the
    # selection to a compact cluster; do not import an entire 48-hour history.
    if burst and len(suspicious) < 2:
        suspicious = _nearest_cluster(online, center, predicate=lambda r: True, max_rows=4)
    if not suspicious:
        suspicious = [dict(flagged)]
    return _unique_rows(suspicious + [flagged])


def _oor_episode(
    flagged: Mapping[str, Any],
    rows: list[dict[str, Any]],
    features: Mapping[str, Any],
) -> list[dict[str, Any]]:
    center = txn_ts(flagged)
    if center is None:
        return [dict(flagged)]
    region = str(flagged.get("addr1") or flagged.get("region") or "")
    same_region = [
        r
        for r in rows
        if txn_channel(r) == "in_person"
        and str(r.get("addr1") or r.get("region") or "") == region
        and _distance(txn_ts(r), center) <= OOR_WINDOW.total_seconds()
    ]
    # A multi-day new-region pattern with home activity is a trip, not a clone.
    if bool(features.get("trip_like")):
        return [dict(flagged)]
    if not same_region:
        return [dict(flagged)]
    # Only include rows in the anomalous region.  Home-region rows are never
    # silently added to the episode.
    selected = [r for r in same_region if is_explicit_anomaly(r) or txn_id(r) == txn_id(flagged)]
    if not selected:
        selected = [dict(flagged)]
    if len(selected) > 1 and bool(features.get("oor_clone")) is False:
        selected = [dict(flagged)]
    return _unique_rows(selected + [flagged])


def _ato_episode(
    flagged: Mapping[str, Any],
    rows: list[dict[str, Any]],
    features: Mapping[str, Any],
) -> list[dict[str, Any]]:
    center = txn_ts(flagged)
    if center is None:
        return [dict(flagged)]
    window = [r for r in rows if _distance(txn_ts(r), center) <= ATO_WINDOW.total_seconds()]
    channels = {txn_channel(r) for r in window}
    if not {"online", "in_person"}.issubset(channels):
        return [dict(flagged)]
    selected: list[dict[str, Any]] = []
    for row in window:
        is_identity_anomaly = is_new_device(row) or is_proxy(row) or is_match_anomaly(row)
        if txn_id(row) == txn_id(flagged) or is_explicit_anomaly(row) or is_identity_anomaly:
            selected.append(row)
    if len(selected) < 2:
        # Preserve the mixed-channel fact, but only add the closest row in the
        # other channel rather than an arbitrary time-window slice.
        other = "in_person" if txn_channel(flagged) == "online" else "online"
        nearest = sorted(
            [r for r in window if txn_channel(r) == other],
            key=lambda r: _distance(txn_ts(r), center),
        )
        if nearest:
            selected.append(nearest[0])
    return _unique_rows(selected + [flagged])


def _undocumented_episode(
    flagged: Mapping[str, Any],
    rows: list[dict[str, Any]],
    features: Mapping[str, Any],
) -> list[dict[str, Any]]:
    center = txn_ts(flagged)
    if center is None:
        return [dict(flagged)]
    selected = [
        r
        for r in rows
        if is_explicit_anomaly(r) and _distance(txn_ts(r), center) <= timedelta(days=7).total_seconds()
    ]
    # Some graph adapters mark coordinated rows with a shared-entity field.
    for row in rows:
        if (
            any(bool(row.get(k)) for k in ("coordinated", "connected_fraud", "same_ring"))
            and _distance(txn_ts(row), center) <= timedelta(days=7).total_seconds()
        ):
            selected.append(row)
    return _unique_rows(selected + [flagged])


def build_episode(
    flagged: Mapping[str, Any],
    rows: Iterable[Mapping[str, Any]],
    pattern: str = "none",
    features: Mapping[str, Any] | None = None,
    *,
    cutoff: datetime | str | None = None,
) -> list[dict[str, Any]]:
    """Build a bounded, de-duplicated fraud episode containing ``flagged``.

    ``pattern`` is the output of the production detector.  Unknown or missing
    patterns intentionally collapse to the flagged transaction rather than
    treating every nearby row as fraud.
    """
    f = dict(flagged)
    fts = txn_ts(f)
    limit = parse_ts(cutoff) if cutoff is not None else fts
    if cutoff is not None and limit is None:
        return []
    visible = rows_at_cutoff(rows, limit, flagged=f)
    if fts is not None and limit is not None and fts > limit:
        return []
    if pattern == "card_testing":
        return _testing_episode(f, visible, features or {})
    if pattern in {"card_not_present_fraud", "card_not_present_new_device"}:
        return _online_episode(f, visible, features or {}, new_device=pattern.endswith("new_device"))
    if pattern == "out_of_region_use":
        return _oor_episode(f, visible, features or {})
    if pattern == "account_takeover":
        return _ato_episode(f, visible, features or {})
    if pattern == "undocumented":
        return _undocumented_episode(f, visible, features or {})
    return [f]


def select_episode(
    flagged: Mapping[str, Any],
    rows: Iterable[Mapping[str, Any]],
    pattern: str = "none",
    features: Mapping[str, Any] | None = None,
    *,
    cutoff: datetime | str | None = None,
) -> list[dict[str, Any]]:
    """Compatibility/readability alias for :func:`build_episode`."""
    return build_episode(flagged, rows, pattern, features, cutoff=cutoff)


def episode_bounds(rows: Iterable[Mapping[str, Any]]) -> tuple[str, str, str]:
    """Return ``(first_txn_id, first_date, last_date)`` for a valid episode."""
    ordered = _unique_rows(rows)
    if not ordered:
        return "", "", ""
    first = min(ordered, key=lambda r: (txn_ts(r) or datetime.max, txn_id(r)))
    last = max(ordered, key=lambda r: (txn_ts(r) or datetime.min, txn_id(r)))
    fts, lts = txn_ts(first), txn_ts(last)
    return (
        txn_id(first),
        fts.strftime("%Y-%m-%d") if fts else "",
        lts.strftime("%Y-%m-%d") if lts else "",
    )


def episode_ids(rows: Iterable[Mapping[str, Any]]) -> list[str]:
    unique = _unique_rows(rows)
    return [txn_id(row) for row in unique if txn_id(row)]


__all__ = [
    "ATO_WINDOW",
    "OOR_WINDOW",
    "PATTERN_WINDOW",
    "SMALL_AUTH_LIMIT",
    "build_episode",
    "episode_bounds",
    "episode_ids",
    "is_match_anomaly",
    "is_new_device",
    "is_proxy",
    "parse_ts",
    "rows_at_cutoff",
    "select_episode",
    "txn_amount",
    "txn_channel",
    "txn_device_id",
    "txn_id",
    "txn_ts",
]
