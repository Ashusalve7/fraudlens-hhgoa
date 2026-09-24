"""Structured, fact-preserving SAR rendering."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

try:
    from .episodes import txn_amount, txn_channel, txn_id, txn_ts
except ImportError:  # top-level import from runner.py
    from episodes import txn_amount, txn_channel, txn_id, txn_ts  # type: ignore


def _field(row: Mapping[str, Any], *keys: str, default: Any = "") -> Any:
    for key in keys:
        if key in row and row[key] not in (None, "", "_NA_"):
            return row[key]
    return default


def _as_rows(
    affected: Iterable[Any],
    episode_rows: Iterable[Mapping[str, Any]] | None,
    txn: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    """Resolve exactly the affected IDs; never expand a SAR to the full episode."""
    episode = [dict(row) for row in (episode_rows or []) if isinstance(row, Mapping)]
    by_id = {txn_id(row): row for row in episode if txn_id(row)}
    affected_items = list(affected or [])
    if affected_items:
        resolved: dict[str, dict[str, Any]] = {}
        for item in affected_items:
            if isinstance(item, Mapping):
                row = dict(item)
            else:
                row_id = str(item)
                row = dict(by_id.get(row_id, {"txn_id": row_id}))
            row_id = txn_id(row)
            if row_id:
                resolved[row_id] = row
        return sorted(
            resolved.values(),
            key=lambda row: (txn_ts(row) or datetime.max, txn_id(row)),
        )

    if txn and txn_id(txn):
        return [dict(txn)]
    return episode


def _unique(values: Iterable[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in (None, ""):
            continue
        text = str(value)
        if text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _connected_cards(
    device: Any,
    connected_cards: Iterable[str] | None,
    own_card: str,
    *,
    corroborated: bool,
) -> list[str]:
    values = [str(value) for value in (connected_cards or []) if value]
    if corroborated and isinstance(device, Mapping):
        values.extend(str(value) for value in (device.get("connected_card_ids") or []))
        for row in device.get("cards", []) or []:
            value = _field(row, "card_id", "id", default="") if isinstance(row, Mapping) else row
            if value:
                values.append(str(value))
    return [value for value in _unique(values) if value != own_card]


def _device_ids(device: Any, connected_devices: Iterable[str] | None) -> list[str]:
    values = [str(value) for value in (connected_devices or []) if value]
    if isinstance(device, Mapping):
        value = _field(device, "device_id", "id", default="")
        if value:
            values.append(str(value))
        values.extend(str(value) for value in (device.get("connected_device_profiles") or []))
    return _unique(values)


def build_sar(
    file_flag: bool,
    reason: str,
    case: Mapping[str, Any],
    customer_id: str,
    card_id: str,
    affected: Iterable[Any],
    exposure: float,
    txn: Mapping[str, Any],
    pattern: str,
    device: Any,
    *,
    episode_rows: Iterable[Mapping[str, Any]] | None = None,
    connected_cards: Iterable[str] | None = None,
    connected_devices: Iterable[str] | None = None,
    connected_fraud_cases: Iterable[Any] | None = None,
    connected_fraud: bool = False,
    coordinated: bool = False,
    customer_asked: bool = False,
    customer_denied: bool = False,
    evidence_requests: Iterable[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Render a SAR only from supplied episode and graph facts.

    A false filing decision always returns the sponsor's exact empty shape.
    For a true filing, missing dates or subjects are rejected rather than
    replaced with invented values.
    """
    if not file_flag:
        return {
            "file": False,
            "reason": str(reason),
            "narrative": "",
            "subjects": [],
            "total_amount_usd": 0,
            "activity_dates": [],
        }

    rows = _as_rows(affected, episode_rows, txn)
    if not rows:
        raise ValueError("a filed SAR requires at least one affected transaction")
    if any(not txn_id(row) for row in rows):
        raise ValueError("a filed SAR requires an ID for every affected transaction")
    first_ts = txn_ts(rows[0])
    last_ts = txn_ts(rows[-1])
    if first_ts is None or last_ts is None:
        raise ValueError("a filed SAR requires transaction timestamps")
    first_date = first_ts.strftime("%Y-%m-%d")
    last_date = last_ts.strftime("%Y-%m-%d")
    total = round(sum(txn_amount(row) for row in rows), 2)

    first = rows[0]
    first_amount = txn_amount(first)
    region = str(_field(first, "addr1", "region", default="") or "the recorded billing region")
    channel = txn_channel(first)
    fraud_cases = list(connected_fraud_cases or [])
    corroborated = bool(connected_fraud or fraud_cases)
    device_ids = _device_ids(device, connected_devices)
    card_ids = _connected_cards(device, connected_cards, str(card_id), corroborated=corroborated)
    subjects = _unique([customer_id, card_id, *device_ids, *card_ids])
    if not subjects:
        raise ValueError("a filed SAR requires at least one known subject ID")

    request_list = list(evidence_requests or [])
    asked = bool(customer_asked or request_list)
    pattern_text = {
        "card_testing": "small online authorizations followed by a larger purchase are consistent with card testing",
        "card_not_present_fraud": "online purchases were inconsistent with the cardholder's baseline",
        "card_not_present_new_device": "online purchases used a New or proxied device signal and deviated from the baseline",
        "out_of_region_use": "card-present purchases occurred in a billing region absent from prior card history",
        "account_takeover": "mixed-channel activity included identity or credential anomalies",
        "undocumented": "the activity did not match a documented typology and showed coordinated or repeated abuse",
    }.get(pattern, "the recorded activity was suspicious but did not match a documented typology")

    sentences = [
        f"Between {first_date} and {last_date}, customer {customer_id}'s card {card_id} showed "
        f"{len(rows)} suspicious transaction(s) totaling ${total:,.2f}.",
        f"The first affected transaction was {txn_id(first)} on {first_date} for "
        f"${first_amount:,.2f} through the {channel} channel in {region}.",
        f"The recorded pattern is {pattern}: {pattern_text}.",
    ]
    if total > 1000:
        sentences.append(
            f"The episode total of ${total:,.2f} exceeds the policy's $1,000 reporting threshold."
        )
    elif corroborated:
        sentences.append(
            "The filing rests on corroborated connected-card fraud rather than on the monetary amount."
        )
    elif coordinated:
        sentences.append(
            "The filing rests on corroborated coordinated or repeated abuse rather than on the monetary amount."
        )
    else:
        sentences.append(
            "The filing is based on the documented suspicious activity and the policy basis stated in the reason."
        )

    if card_ids and corroborated:
        sentences.append(
            f"Graph evidence links the recorded origin to connected card(s) {', '.join(card_ids)}, "
            "whose pre-cutoff cases corroborate fraud."
        )
    elif device_ids and corroborated:
        sentences.append(
            f"Graph evidence links device profile {', '.join(device_ids)} to corroborated fraud."
        )
    elif coordinated:
        sentences.append(
            "The pre-cutoff graph neighborhood shows repeated, coordinated abuse across the supported entities."
        )
    elif device_ids:
        sentences.append(
            f"Device profile {', '.join(device_ids)} is recorded for the transaction; device reuse alone is "
            "not asserted to be fraud."
        )
    else:
        sentences.append("No shared device, connected card, or cross-customer link is asserted.")

    if asked:
        response_text = next(
            (
                str(request.get("assumed_response"))
                for request in request_list
                if request.get("assumed_response")
            ),
            "",
        )
        if response_text:
            sentences.append(f"An evidence request recorded this assumed response: {response_text}")
        else:
            sentences.append("An evidence request was recorded, but no response text was asserted.")
    elif customer_denied:
        sentences.append(
            "The case trigger explicitly reported that the customer did not authorize the transaction; "
            "no later interview is asserted."
        )
    else:
        sentences.append("No customer response is asserted because none was supplied or requested.")

    suspicious_reason = {
        "card_testing": "The ordered small-authorization sequence is the suspicious fact.",
        "card_not_present_fraud": "The online burst or baseline inconsistency is the suspicious fact.",
        "card_not_present_new_device": "The device signal combined with inconsistent online activity is suspicious.",
        "out_of_region_use": "The new-region card-present activity and retained home activity are suspicious.",
        "account_takeover": "The channel and identity anomalies are the suspicious facts.",
        "undocumented": "The corroborated cross-customer pattern is the suspicious fact.",
    }.get(pattern, "The recorded transaction sequence is the suspicious fact.")
    sentences.append(suspicious_reason)
    sentences.append(
        "Affected transaction IDs: " + ", ".join(txn_id(row) for row in rows if txn_id(row)) + "."
    )

    return {
        "file": True,
        "reason": str(reason),
        "narrative": " ".join(sentences),
        "subjects": subjects,
        "total_amount_usd": total,
        "activity_dates": [first_date, last_date],
    }


__all__ = ["build_sar"]
