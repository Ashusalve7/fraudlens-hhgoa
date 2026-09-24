"""Structured SAR rendering.

The renderer consumes the same episode and graph entities used by the decision
engine.  It never invents a threshold, customer response, device, or connected
card in order to make a narrative sound complete.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable, Mapping

try:
    from .episodes import parse_ts, txn_amount, txn_channel, txn_id, txn_ts
except ImportError:  # top-level import from runner
    from episodes import parse_ts, txn_amount, txn_channel, txn_id, txn_ts  # type: ignore


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
    rows = [dict(r) for r in (episode_rows or []) if isinstance(r, Mapping)]
    by_id = {txn_id(r): r for r in rows if txn_id(r)}
    for item in affected or []:
        if isinstance(item, Mapping):
            row = dict(item)
        else:
            rid = str(item)
            row = dict(by_id.get(rid, {"txn_id": rid}))
        rid = txn_id(row)
        if rid:
            by_id[rid] = row
    if txn and txn_id(txn) and txn_id(txn) not in by_id:
        by_id[txn_id(txn)] = dict(txn)
    result = list(by_id.values())
    result.sort(key=lambda r: (txn_ts(r) or datetime.max, txn_id(r)))
    return result


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


def _connected_cards(device: Any, connected_cards: Iterable[str] | None, own_card: str) -> list[str]:
    values: list[str] = []
    if connected_cards is not None:
        values.extend(str(v) for v in connected_cards if v)
    if isinstance(device, Mapping):
        values.extend(str(v) for v in (device.get("connected_card_ids") or []))
        for row in device.get("cards", []) or []:
            if isinstance(row, Mapping):
                value = row.get("card_id") or row.get("id")
            else:
                value = row
            if value:
                values.append(str(value))
    return [v for v in _unique(values) if v != own_card]


def _connected_devices(device: Any, connected_devices: Iterable[str] | None) -> list[str]:
    values: list[str] = []
    if connected_devices is not None:
        values.extend(str(v) for v in connected_devices if v)
    if isinstance(device, Mapping):
        value = device.get("device_id") or device.get("id")
        if value:
            values.append(str(value))
        values.extend(str(v) for v in (device.get("connected_device_profiles") or []))
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
    """Build a fact-preserving SAR object.

    ``shared_link``/device reuse is intentionally not treated as connected
    fraud.  The caller must pass ``connected_fraud`` or a non-empty
    ``connected_fraud_cases`` when that stronger fact is intended.
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
        rows = [dict(txn or {})]
    first = rows[0]
    last = rows[-1]
    first_ts = txn_ts(first)
    last_ts = txn_ts(last)
    first_date = first_ts.strftime("%Y-%m-%d") if first_ts else ""
    last_date = last_ts.strftime("%Y-%m-%d") if last_ts else first_date
    total = round(sum(txn_amount(row) for row in rows), 2)
    # Use the actual episode sum.  ``exposure`` remains a compatibility input,
    # but cannot make a narrative claim that the rows do not support.
    if not rows:
        total = round(abs(float(exposure or 0)), 2)
    first_amount = txn_amount(first)
    region = str(_field(first, "addr1", "region", default="") or "the recorded billing region")
    channel = txn_channel(first)
    device_ids = _connected_devices(device, connected_devices)
    card_ids = _connected_cards(device, connected_cards, str(card_id))
    fraud_cases = list(connected_fraud_cases or [])
    corroborated = bool(connected_fraud or fraud_cases)
    request_list = list(evidence_requests or [])
    asked = bool(customer_asked or request_list)
    denied = bool(customer_denied)

    subjects = _unique([customer_id, card_id, *device_ids, *card_ids])
    sentences: list[str] = []
    if first_date and last_date:
        sentences.append(
            f"Between {first_date} and {last_date}, customer {customer_id}'s card {card_id} showed "
            f"{len(rows)} transaction(s) totaling ${total:,.2f}."
        )
    else:
        sentences.append(
            f"Customer {customer_id}'s card {card_id} showed {len(rows)} transaction(s) totaling ${total:,.2f}."
        )
    sentences.append(
        f"The first affected transaction was {txn_id(first)} on {first_date or 'an unrecorded date'} "
        f"for ${first_amount:,.2f} through the {channel} channel in {region}."
    )

    pattern_text = {
        "card_testing": "small online authorizations followed by a larger purchase are consistent with card testing",
        "card_not_present_fraud": "online purchases were inconsistent with the cardholder's baseline",
        "card_not_present_new_device": "online purchases used a New or proxied device signal and were inconsistent with the baseline",
        "out_of_region_use": "card-present purchases occurred in a billing region not present in the prior card history",
        "account_takeover": "mixed-channel activity included identity or credential anomalies",
        "undocumented": "the activity did not match a documented typology and showed coordinated/repeated abuse",
    }.get(pattern, "the activity was classified from the recorded evidence")
    sentences.append(f"The pattern assessment is {pattern}: {pattern_text}.")

    if total > 1000:
        sentences.append(f"The episode total of ${total:,.2f} exceeds the policy's $1,000 reporting threshold.")
    else:
        sentences.append(f"The episode total was ${total:,.2f}; the filing basis is the corroborated activity described below, not the dollar threshold.")

    if corroborated:
        if card_ids:
            sentences.append(
                f"Graph evidence links device profile {', '.join(device_ids) or 'the recorded device'} to card(s) "
                f"{', '.join(card_ids)} with corroborated or confirmed fraud."
            )
        else:
            sentences.append(
                f"Graph evidence links device profile {', '.join(device_ids) or 'the recorded device'} to corroborated fraud."
            )
    elif coordinated:
        sentences.append("The pre-cutoff graph neighborhood shows repeated, coordinated abuse across customers.")
    else:
        sentences.append("The filing basis is the documented suspicious activity and the policy gate stated in the reason.")

    if asked:
        response_text = ""
        for request in request_list:
            if request.get("assumed_response"):
                response_text = str(request["assumed_response"])
                break
        if response_text:
            sentences.append(f"An evidence request recorded this scenario response: {response_text}")
        else:
            sentences.append("An evidence request was recorded, but no additional response text was asserted.")
    elif denied:
        sentences.append("The case trigger explicitly reported that the customer did not authorize the transaction; no later customer interview is asserted.")
    else:
        sentences.append("No customer response is asserted because this trigger did not contain one and no response request was made.")

    suspicious_reason = {
        "card_testing": "The ordered small-authorization sequence is the suspicious fact.",
        "card_not_present_fraud": "The online burst or baseline inconsistency is the suspicious fact.",
        "card_not_present_new_device": "The New/proxy device signal combined with inconsistent online activity is the suspicious fact.",
        "out_of_region_use": "The new-region card-present activity and retained home activity are the suspicious facts.",
        "account_takeover": "The channel and identity anomalies are the suspicious facts.",
        "undocumented": "The cross-customer corroboration is the suspicious fact.",
    }.get(pattern, "The recorded transaction sequence is the suspicious fact.")
    sentences.append(suspicious_reason)
    sentences.append("Affected transaction IDs: " + ", ".join(txn_id(r) for r in rows if txn_id(r)) + ".")

    # The sponsor requires a complete but concise narrative.  Keep the renderer
    # within its six-to-twelve sentence contract even for sparse fixtures.
    narrative = " ".join(sentences)
    return {
        "file": True,
        "reason": str(reason),
        "narrative": narrative,
        "subjects": subjects,
        "total_amount_usd": total,
        "activity_dates": [first_date, last_date],
    }


__all__ = ["build_sar"]
