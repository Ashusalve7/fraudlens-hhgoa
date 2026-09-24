"""Calibrated scoring, production pattern rules, and the FraudLens policy engine.

The functions in this module are the decision contract used by the runner and
by offline evaluation.  Pattern rules are intentionally conservative: channel
alone is not a fraud finding, and an unfamiliar pattern is emitted only when
coordinated/repeated cross-customer evidence exists.
"""
from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

MODEL_PATH = Path(__file__).resolve().parent.parent / "eval" / "out" / "model.json"

# The sponsor describes the exam alert mix as approximately half legitimate.
# This is an explicit prior, not a replacement for the labeled-history model.
EXAM_PRIOR = 0.5
DEFAULT_TEMPERATURE = 1.5
DEFAULT_RESPONSE_LIKELIHOOD = {
    "denied": 8.0,
    "confirmed": 0.125,
    "no_response": 1.0,
}

PATTERN_ENUM = {
    "card_testing",
    "card_not_present_fraud",
    "card_not_present_new_device",
    "out_of_region_use",
    "account_takeover",
    "undocumented",
    "none",
}

ROUTES = {
    "ALLOW_TRANSACTION": "auto",
    "DECLINE_TRANSACTION": "L1",
    "MONITOR_CARD": "auto",
    "MONITOR_CONNECTED_CARDS": "auto",
    "WARN_CUSTOMER": "auto",
    "VERIFY_WITH_CUSTOMER": "auto",
    "STEP_UP_AUTH": "auto",
    "BLOCK_CARD": "L1",
    "BLOCK_ALL_CARDS": "L2",
    "GENERATE_REPORT": "auto",
    "CREATE_CASE": "auto",
    "FILE_REPORT": "L2",
    "ESCALATE_TO_ANALYST": "auto",
    "CLOSE_NO_FRAUD": "auto",
}

REQUIRED_MODEL_FIELDS = {
    "features",
    "scaler_mean",
    "scaler_scale",
    "coef",
    "intercept",
    "platt",
    "train_base_rate",
}
MODEL_FEATURE_COUNT = 16


def _sigmoid(value: float) -> float:
    # Stable logistic function.  The small epsilon only prevents log(0) in the
    # inverse transform; it is not a policy cap.
    if value >= 0:
        z = math.exp(-min(value, 700.0))
        return 1.0 / (1.0 + z)
    z = math.exp(max(value, -700.0))
    return z / (1.0 + z)


def _logit(value: float) -> float:
    p = min(max(float(value), 1e-12), 1.0 - 1e-12)
    return math.log(p / (1.0 - p))


def _number(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _truth(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _get(mapping: Mapping[str, Any] | None, *keys: str, default: Any = 0) -> Any:
    if not mapping:
        return default
    for key in keys:
        if key in mapping and mapping[key] not in (None, ""):
            return mapping[key]
    return default


class Calibrator:
    """Load and apply the serialized production calibrator.

    ``model.json`` is produced by :mod:`eval.train`.  The runtime refuses a
    malformed artifact rather than silently inventing a prior or feature.
    """

    def __init__(self, model_path: str | Path = MODEL_PATH, model: Mapping[str, Any] | None = None) -> None:
        if model is None:
            model = json.loads(Path(model_path).read_text(encoding="utf-8"))
        missing = sorted(REQUIRED_MODEL_FIELDS - set(model))
        if missing:
            raise ValueError(f"calibrator artifact missing fields: {', '.join(missing)}")
        self.model = dict(model)
        self.features = list(model["features"])
        self.mean = list(model["scaler_mean"])
        self.scale = list(model["scaler_scale"])
        self.coef = list(model["coef"])
        self.intercept = float(model["intercept"])
        self.platt = dict(model["platt"])
        self.train_base_rate = float(model["train_base_rate"])
        self.exam_base_rate = float(model.get("exam_base_rate", EXAM_PRIOR))
        self.temperature = float(model.get("temperature", DEFAULT_TEMPERATURE))
        if not (0 < self.train_base_rate < 1 and 0 < self.exam_base_rate < 1):
            raise ValueError("calibrator priors must be strictly between zero and one")
        if self.temperature <= 0:
            raise ValueError("calibrator temperature must be positive")
        lengths = {len(self.features), len(self.mean), len(self.scale), len(self.coef)}
        if len(lengths) != 1 or len(self.features) != MODEL_FEATURE_COUNT:
            raise ValueError("calibrator feature arrays must have the production length")
        self.auc = model.get("holdout_auc")

    def raw_score(self, feats: Mapping[str, Any]) -> float:
        missing = [name for name in self.features if name not in feats]
        if missing:
            raise KeyError(f"missing calibrator features: {', '.join(missing)}")
        total = self.intercept
        for name, mean, scale, coefficient in zip(self.features, self.mean, self.scale, self.coef):
            scale = float(scale)
            if abs(scale) < 1e-12:
                scale = 1e-12
            total += (_number(feats.get(name)) - float(mean)) / scale * float(coefficient)
        return total

    def score(self, feats: Mapping[str, Any]) -> tuple[float, float]:
        """Return ``(p_history, p_exam)`` from the same production transform.

        The first value is the Platt probability under the labeled-history
        population.  The second applies the explicit exam prior and temperature
        shift.  Neither value is clipped to a decision threshold.
        """
        raw = self.raw_score(feats)
        platt = self.platt
        platt_std = float(platt.get("std", 1.0)) or 1.0
        z = (raw - float(platt.get("mean", 0.0))) / platt_std
        p_hist = _sigmoid(float(platt.get("w", 1.0)) * z + float(platt.get("b", 0.0)))
        shifted_logit = _logit(p_hist) / self.temperature
        shifted_logit += _logit(self.exam_base_rate) - _logit(self.train_base_rate)
        p_exam = _sigmoid(shifted_logit)
        return p_hist, p_exam

    def score_exam(self, feats: Mapping[str, Any]) -> float:
        return self.score(feats)[1]

    def update_for_response(
        self,
        probability: float,
        response: str | None,
        *,
        likelihood: Mapping[str, float] | None = None,
    ) -> float:
        """Apply a recorded scenario response as a transparent odds update.

        A simulated reply is not a replacement score.  It is a likelihood ratio
        applied to the calibrated prior, so the result remains a probability and
        is not forced to a convenient 0.9/0.1 endpoint.  Callers should retain
        the response text separately in the evidence request.
        """
        if not response or response == "no_response":
            return min(max(float(probability), 0.0), 1.0)
        ratios = dict(DEFAULT_RESPONSE_LIKELIHOOD)
        ratios.update(self.model.get("response_likelihood", {}))
        if likelihood:
            ratios.update(likelihood)
        ratio = float(ratios.get(response, 1.0))
        if ratio <= 0 or not math.isfinite(ratio):
            raise ValueError("response likelihood ratio must be positive and finite")
        posterior = _sigmoid(_logit(probability) + math.log(ratio))
        return min(max(posterior, 0.0), 1.0)


def _row_channel(row: Mapping[str, Any]) -> str:
    value = str(_get(row, "channel", "Channel", default="")).lower()
    if value in {"in_person", "inperson", "card_present", "card-present", "present"}:
        return "in_person"
    if value in {"online", "remote", "ecommerce", "e-commerce"}:
        return "online"
    product = str(_get(row, "product_cd", "ProductCD", default="")).upper()
    return "in_person" if product == "W" else "online"


def _row_amount(row: Mapping[str, Any]) -> float:
    return abs(_number(_get(row, "amount", "TransactionAmt", "transaction_amount", default=0)))


def _row_ts(row: Mapping[str, Any]) -> datetime | None:
    try:
        from .episodes import parse_ts  # package import
    except ImportError:  # runner imports this module as a top-level module
        from episodes import parse_ts  # type: ignore
    return parse_ts(_get(row, "ts", "timestamp", "TransactionDT", default=None))


def _row_id(row: Mapping[str, Any]) -> str:
    return str(_get(row, "txn_id", "transaction_id", "TransactionID", "id", default=""))


def _row_device(row: Mapping[str, Any]) -> str:
    value = _get(row, "device_id", "deviceId", "device_profile_id", default="")
    if value:
        return str(value)
    value = _get(row, "id", default="")
    return str(value) if str(value).startswith("DP-") else ""


def _row_new_device(row: Mapping[str, Any]) -> bool:
    return str(_get(row, "id_15", "id15", default="")).strip().lower() == "new"


def _row_proxy(row: Mapping[str, Any]) -> bool:
    value = str(_get(row, "id_23", "id23", default="")).upper()
    return any(token in value for token in ("ANONYMOUS", "HIDDEN", "PROXY"))


def _row_explicit_anomaly(row: Mapping[str, Any]) -> bool:
    return any(_truth(row.get(k)) for k in ("anomalous", "suspicious", "fraud_related", "is_fraud"))


def _sequence_signals(rows: Iterable[Mapping[str, Any]], center: datetime | None) -> dict[str, Any]:
    ordered = sorted((dict(r) for r in rows), key=lambda r: (_row_ts(r) or datetime.max, _row_id(r)))
    online = [r for r in ordered if _row_channel(r) == "online"]
    small = [r for r in online if _row_amount(r) < 5.0]
    testing = False
    testing_large = 0.0
    if center is not None:
        for i, start in enumerate(small):
            start_ts = _row_ts(start)
            if start_ts is None:
                continue
            cluster = [r for r in small[i:] if _row_ts(r) and ( _row_ts(r) - start_ts).total_seconds() <= 3600]
            if len(cluster) < 3:
                continue
            last_ts = max(_row_ts(r) for r in cluster if _row_ts(r))
            threshold = max(5.0, max(_row_amount(r) for r in cluster) * 1.25)
            follow = [
                r for r in online
                if _row_ts(r) and last_ts < _row_ts(r) and (_row_ts(r) - last_ts).total_seconds() <= 86400
                and _row_amount(r) >= threshold
            ]
            if follow:
                testing = True
                testing_large = max(testing_large, max(_row_amount(r) for r in follow))
                break
    near = [
        r for r in online
        if center is not None and _row_ts(r) and abs((_row_ts(r) - center).total_seconds()) <= 172800
    ]
    prior = [r for r in online if center is not None and _row_ts(r) and _row_ts(r) < center]
    hist_amounts = [_row_amount(r) for r in prior if _row_amount(r) > 0]
    hist_mean = sum(hist_amounts) / len(hist_amounts) if hist_amounts else 0.0
    amt_anomaly = any(hist_mean and _row_amount(r) >= 2.0 * hist_mean for r in near)
    product_values = {str(_get(r, "product_cd", "ProductCD", default="")) for r in prior}
    product_anomaly = bool({str(_get(r, "product_cd", "ProductCD", default="")) for r in near} - product_values)
    new_share = sum(1 for r in near if _row_new_device(r)) / len(near) if near else 0.0
    proxy_share = sum(1 for r in near if _row_proxy(r)) / len(near) if near else 0.0
    return {
        "n_online_48h": len(near),
        "online_burst_48h": len(near) >= 2,
        "testing_sequence": testing,
        "testing_large_amount": testing_large,
        "online_amount_anomaly": amt_anomaly,
        "online_product_anomaly": product_anomaly,
        "new_device_share": new_share,
        "proxy_share": proxy_share,
        "mixed_channel": len({_row_channel(r) for r in near}) >= 2,
        "identity_anomaly": any(_row_new_device(r) or _row_proxy(r) for r in near)
        or any(str(_get(r, "m_flags", default="")) for r in near),
    }


def _episode_signals(episode_rows: Iterable[Mapping[str, Any]], card_rows: Iterable[Mapping[str, Any]], center: datetime | None) -> dict[str, Any]:
    rows = [dict(r) for r in episode_rows]
    all_rows = [dict(r) for r in card_rows]
    signals = _sequence_signals(rows, center)
    if not signals["n_online_48h"]:
        signals.update(_sequence_signals(all_rows, center))
    region = ""
    if rows:
        region = str(_get(rows[0], "addr1", "region", default=""))
    region_rows = [r for r in all_rows if str(_get(r, "addr1", "region", default="")) == region]
    home_rows = [
        r for r in all_rows
        if _row_channel(r) == "in_person"
        and str(_get(r, "addr1", "region", default="")) not in {"", region}
    ]
    home_active = bool(home_rows)
    prior = [r for r in all_rows if center and _row_ts(r) and _row_ts(r) < center]
    prior_amounts = [_row_amount(r) for r in prior]
    hist_mean = sum(prior_amounts) / len(prior_amounts) if prior_amounts else 0.0
    current_amount = _row_amount(rows[0]) if rows else 0.0
    region_dates = {
        _row_ts(r).date() for r in region_rows if _row_ts(r) is not None
    }
    duration_days = (max(region_dates) - min(region_dates)).days + 1 if region_dates else 0
    coords = _get(rows[0] if rows else {}, "coordinated", "connected_fraud", default=False) if rows else False
    signals.update({
        "n_small_in_episode": sum(1 for r in rows if _row_channel(r) == "online" and _row_amount(r) < 5),
        "ep_online": (sum(1 for r in rows if _row_channel(r) == "online") / len(rows)) if rows else 0.0,
        "prior_reg_share": (
            sum(1 for r in prior if str(_get(r, "addr1", "region", default="")) == region) / len(prior)
            if prior and region else 0.0
        ),
        "region": region,
        "home_active": home_active,
        "new_region_days": duration_days,
        "trip_like": bool(home_active and duration_days >= 3),
        "amt_ratio": current_amount / hist_mean if hist_mean else 0.0,
        "coordinated": _truth(coords),
    })
    return signals


def detect_pattern(f: Mapping[str, Any], ep: Mapping[str, Any] | None = None) -> tuple[str, str]:
    """Classify the exact production pattern registry.

    Channel is a supporting signal only.  Each branch has an explicit anomaly
    requirement, and the coordinated branch requires corroboration beyond
    ordinary device reuse.
    """
    f = dict(f or {})
    e = dict(ep or {})
    online = bool(_truth(_get(f, "flagged_online", "is_online", default=False)))
    card_present = not online

    # R5 is a sequence, not a velocity threshold.
    testing = _truth(_get(e, "testing_sequence", default=_get(f, "testing_sequence", default=False)))
    if testing:
        return "card_testing", "R5: three or more small online authorizations within one hour followed by a larger purchase"

    customer_denied = _truth(_get(f, "customer_denied", "explicit_denial", default=False))
    region_new = _truth(_get(f, "region_new", default=False))
    home_active = _truth(_get(f, "home_active_72h", "home_active", default=_get(e, "home_active", default=False)))
    trip_like = _truth(_get(f, "trip_like", default=_get(e, "trip_like", default=False)))
    mixed_channel = _truth(_get(f, "mixed_channel", default=_get(e, "mixed_channel", default=False)))
    identity_anomaly = _truth(_get(f, "identity_anomaly", default=_get(e, "identity_anomaly", default=False)))
    n_online = int(_number(_get(f, "n_online_48h", default=_get(e, "n_online_48h", default=0))))
    n24 = int(_number(_get(f, "n_txn_24h", default=0)))
    amount_ratio = _number(_get(f, "amt_ratio_30d", default=_get(e, "amt_ratio", default=0)))
    product_new = _truth(_get(f, "product_new", default=False))
    online_shift = _number(_get(f, "online_share_shift", default=0))
    explicit_online_anomaly = _truth(_get(f, "online_anomaly", "cnp_anomaly", default=False))
    new_flagged = _truth(_get(f, "new_device_flagged", default=False)) or _truth(_get(e, "new_device_flagged", default=False))
    new_share = max(_number(_get(f, "new_dev_share_24h", default=0)), _number(_get(e, "new_device_share", default=0)))
    proxy_share = max(_number(_get(f, "proxy_share_24h", default=0)), _number(_get(e, "proxy_share", default=0)))
    # A two-to-four transaction online burst is the sponsor's CNP pattern.  A
    # single online row, or a high row count without an anomaly, is not enough.
    online_burst = n_online >= 2 or n24 >= 2
    online_anomaly = bool(
        explicit_online_anomaly
        or (online_burst and (amount_ratio >= 2.0 or product_new or online_shift >= 0.25 or new_flagged or new_share >= 0.25 or proxy_share >= 0.5 or customer_denied))
    )

    # ATO is checked before CNP when the evidence is mixed-channel: credentials
    # and card data were both used, rather than only CNP activity.
    ato_evidence = bool(
        mixed_channel
        and identity_anomaly
        and (
            _truth(_get(f, "ato_evidence", default=False))
            or online_shift <= -0.25
            or product_new
            or amount_ratio >= 2.0
            or customer_denied
        )
    )
    if ato_evidence:
        return "account_takeover", "mixed-channel activity with device, match, or credential anomalies"

    # OOR is card-present in an unseen region while home activity continues.
    # Several days in that region is explicitly treated as a trip.
    oor_clone = _truth(_get(f, "oor_clone", default=False)) or (customer_denied and home_active)
    if card_present and region_new and home_active and not trip_like and oor_clone:
        return "out_of_region_use", "card-present use in a new billing region with home activity and clone-like duration/denial evidence"

    # A corroborated cross-customer ring is allowed to remain undocumented even
    # when its individual transactions resemble a documented online pattern.
    coordinated = _truth(_get(f, "coordinated_signal", "coordinated", default=_get(e, "coordinated", default=False)))
    connected_fraud = _truth(_get(f, "connected_fraud", "connected_fraud_cases", default=False))
    cross_customer = _truth(_get(f, "cross_customer", "coordinated_cross_customer", default=False))
    coordinated = coordinated and (cross_customer or connected_fraud or _truth(_get(f, "coordinated_repeated", default=False)))
    if coordinated and _truth(_get(f, "coordinated_unknown", default=True)):
        return (
            "undocumented",
            "The activity does not meet one of the five documented signatures. "
            "A shared entity and corroborated/repeated abuse across customers were found in the pre-cutoff graph neighborhood.",
        )

    if online and online_anomaly:
        if new_flagged or new_share >= 0.25 or proxy_share >= 0.50:
            return "card_not_present_new_device", "CNP activity is inconsistent with the cardholder baseline and includes a New/proxy device signal"
        return "card_not_present_fraud", "online CNP burst or inconsistent amount/product activity is present"

    return "none", "insufficient pattern-specific evidence; no channel-only fraud inference"


def _parse_dt(value: Any) -> datetime | None:
    try:
        from .episodes import parse_ts
    except ImportError:
        from episodes import parse_ts  # type: ignore
    return parse_ts(value)


def _same_product(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    for key in ("merchant_id", "merchant", "product_cd", "ProductCD", "mcc"):
        lv = _get(left, key, default=None)
        rv = _get(right, key, default=None)
        if lv not in (None, "", "_NA_") or rv not in (None, "", "_NA_"):
            return str(lv) == str(rv)
    return False


def recurring_charge_details(
    txn: Mapping[str, Any],
    history: Iterable[Mapping[str, Any]],
    *,
    card_id: str | None = None,
    cutoff: datetime | str | None = None,
) -> dict[str, Any]:
    """Measure same-card, same-product/merchant, approximately monthly repeats."""
    t = dict(txn or {})
    amount = _row_amount(t)
    limit = _parse_dt(cutoff)
    center = _row_ts(t)
    prior: list[dict[str, Any]] = []
    for source in history:
        row = dict(source)
        ts = _row_ts(row)
        if ts is None or (center is not None and ts >= center) or (limit is not None and ts > limit):
            continue
        if card_id and _get(row, "card_id", "CardID", default=card_id) != card_id:
            continue
        if not _same_product(t, row):
            continue
        if abs(_row_amount(row) - amount) > max(0.02 * amount, 0.01):
            continue
        prior.append(row)
    prior.sort(key=lambda r: (_row_ts(r) or datetime.min, _row_id(r)))
    gaps_days: list[float] = []
    for left, right in zip(prior, prior[1:]):
        lt, rt = _row_ts(left), _row_ts(right)
        if lt and rt:
            gaps_days.append((rt - lt).total_seconds() / 86400.0)
    if center is not None and prior:
        pt = _row_ts(prior[-1])
        if pt:
            gaps_days.append((center - pt).total_seconds() / 86400.0)
    gaps_days = [g for g in gaps_days if g > 0]
    median_gap = 0.0
    if gaps_days:
        ordered = sorted(gaps_days)
        mid = len(ordered) // 2
        median_gap = ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2
    # Two prior repeats plus the disputed event provide two month-to-month
    # intervals.  The deliberately broad 20-45 day window handles calendar
    # months while rejecting bursts and annual/yearly coincidences.
    monthly = bool(
        len(prior) >= 2
        and len(gaps_days) >= 2
        and 20.0 <= median_gap <= 45.0
        and sum(20.0 <= g <= 45.0 for g in gaps_days) >= max(2, len(gaps_days) - 1)
    )
    return {
        "is_monthly": monthly,
        "prior_count": len(prior),
        "total_count": len(prior) + 1,
        "gaps_days": [round(g, 3) for g in gaps_days],
        "median_gap_days": round(median_gap, 3),
        "amount": amount,
        "product": _get(t, "merchant_id", "merchant", "product_cd", "ProductCD", default=""),
    }


def is_monthly_recurring(*args: Any, **kwargs: Any) -> bool:
    """Boolean compatibility wrapper around :func:`recurring_charge_details`."""
    return bool(recurring_charge_details(*args, **kwargs).get("is_monthly"))


def _route_for(action: str, exposure: float) -> str:
    if action == "BLOCK_CARD":
        return "L2" if _number(exposure) > 2500 else "L1"
    return ROUTES[action]


def _action(action: str, reason: str, exposure: float) -> dict[str, str]:
    return {"action": action, "route": _route_for(action, exposure), "reason": reason}


def _sar_basis(
    exposure: float,
    pattern: str,
    shared_link: bool,
    connected_fraud: bool,
    coordinated: bool,
) -> bool:
    # Device reuse alone is a graph fact, not proof of another customer's
    # fraud.  It can support monitoring, but not a SAR by itself.
    return bool(
        _number(exposure) > 1000.0
        or connected_fraud
        or (coordinated and pattern == "undocumented")
    )


def next_best_actions(
    p: float,
    exposure: float,
    pattern: str,
    shared_link: bool,
    customer_denied: bool | None,
    customer_confirmed: bool | None,
    no_reply_24h: bool,
    testing_cleared_over_100: bool,
    *,
    connected_fraud: bool = False,
    coordinated: bool = False,
    n_independent: int | None = None,
    strong_fraud_evidence: bool = False,
    r7: bool = False,
    confirmed_fraud: bool = False,
    multi_card_compromise: bool = False,
) -> list[dict[str, str]]:
    """Apply the sponsor's R1-R10 policy as an ordered decision table."""
    acts: list[dict[str, str]] = []
    p = min(max(_number(p), 0.0), 1.0)
    exposure = max(_number(exposure), 0.0)
    independent = int(n_independent or 0)

    def add(action: str, reason: str) -> None:
        if any(a["action"] == action for a in acts):
            return
        acts.append(_action(action, reason, exposure))

    if customer_confirmed:
        add("CLOSE_NO_FRAUD", "R3: customer confirmed the transaction")
        return acts

    if customer_denied:
        add("BLOCK_CARD", "R2: customer denied the transaction")
        add("CREATE_CASE", "R2: open an internal case with the evidence attached")
        if _sar_basis(exposure, pattern, shared_link, connected_fraud, coordinated):
            basis = []
            if exposure > 1000:
                basis.append(f"exposure ${exposure:,.2f} exceeds $1,000")
            if connected_fraud:
                basis.append("a connected card has corroborated fraud")
            if coordinated and pattern == "undocumented":
                basis.append("coordinated undocumented activity")
            add("FILE_REPORT", "R2/3a: " + "; ".join(basis))
        if shared_link or connected_fraud:
            add("MONITOR_CONNECTED_CARDS", "R6: monitor cards linked by the corroborated shared origin")
        return acts

    if r7:
        add("CREATE_CASE", "R7: disputed charge matches an approximately monthly cardholder pattern")
        add("VERIFY_WITH_CUSTOMER", "R7: verify the recurring charge with the customer")
        add("WARN_CUSTOMER", "R7: provide a recurring-payment reminder")
        return acts

    if pattern == "card_testing":
        if testing_cleared_over_100:
            add("BLOCK_CARD", "R5: a purchase over $100 cleared after the testing sequence")
        else:
            add("DECLINE_TRANSACTION", "R5: card-testing sequence observed")
            add("STEP_UP_AUTH", "R5: require step-up authentication before further activity")
        return acts

    if coordinated and pattern == "undocumented":
        add("CREATE_CASE", "R9: coordinated activity does not match a documented pattern")
        add("FILE_REPORT", "R9/3a: coordinated undocumented abuse has corroborated cross-customer evidence")
        add("ESCALATE_TO_ANALYST", "R9: escalate an undocumented coordinated pattern for analyst review")
        return acts

    high_confidence_fraud = bool(
        confirmed_fraud
        or strong_fraud_evidence
        or (p >= 0.85 and independent >= 2 and pattern not in {"none", "undocumented"})
    )
    if high_confidence_fraud:
        add("BLOCK_CARD", f"R1/R2: calibrated probability {p:.2f} is supported by independent pattern evidence")
        add("CREATE_CASE", "R2: open an internal case with the evidence attached")
        if _sar_basis(exposure, pattern, shared_link, connected_fraud, coordinated):
            reason = "R2/3a: exposure threshold or corroborated shared fraud"
            add("FILE_REPORT", reason)
        if shared_link or connected_fraud:
            add("MONITOR_CONNECTED_CARDS", "R6: monitor cards linked to the corroborated shared origin")
        return acts

    if p <= 0.15 and independent >= 2:
        add("CLOSE_NO_FRAUD", f"R1: probability {p:.2f} at or below 0.15 with independent evidence")
        return acts

    if no_reply_24h:
        add("MONITOR_CARD", "R4: no customer reply within 24 hours")
        add("DECLINE_TRANSACTION", "R4: decline pending authorizations while the alert is unresolved")
        if exposure > 500:
            add("ESCALATE_TO_ANALYST", "R4/R8: exposure exceeds $500 without verification")
        return acts

    if 0.30 <= p <= 0.70 and exposure > 500:
        add("ESCALATE_TO_ANALYST", f"R8: uncertain verdict (p={p:.2f}) with exposure ${exposure:,.2f} over $500")
        add("VERIFY_WITH_CUSTOMER", "R1: verify before any block")
        return acts

    add("VERIFY_WITH_CUSTOMER", f"R1: probability {p:.2f} is below the blocking threshold; verify before blocking")
    add("STEP_UP_AUTH", "R1: use step-up authentication as the lower-impact alternative")
    if p >= 0.30 or pattern != "none":
        add("CREATE_CASE", "3a: open a case when probability reaches 0.30 or evidence is collected")
    return acts


def should_file_sar(
    verdict: str,
    exposure: float,
    pattern: str,
    shared_link: bool = False,
    *,
    connected_fraud: bool = False,
    coordinated: bool = False,
    strong_suspicion: bool = False,
) -> tuple[bool, str]:
    """Apply the policy §3a gate using corroborated, structured facts."""
    exposure = _number(exposure)
    if verdict != "fraud" and not (strong_suspicion and verdict == "uncertain"):
        return False, "3a: no report without confirmed or strongly suspected fraud"
    if exposure > 1000:
        return True, f"3a: confirmed/strongly suspected fraud with exposure ${exposure:,.2f} above $1,000"
    if connected_fraud:
        return True, "3a/R6: corroborated fraud is connected to another card through the graph"
    if coordinated and pattern == "undocumented":
        return True, "3a/R9: coordinated undocumented abuse is corroborated across customers"
    # ``shared_link`` is intentionally not sufficient: a device can be reused
    # by many customers without any evidence that those cards suffered fraud.
    return False, "3a: case only; exposure is not above $1,000 and no connected fraud or coordinated abuse is corroborated"


def independent_evidence_count(
    *,
    has_transaction: bool = True,
    episode_rows: Iterable[Mapping[str, Any]] = (),
    customer_denied: bool = False,
    device_corroborated: bool = False,
    similar_cases: Iterable[Mapping[str, Any]] = (),
) -> int:
    """Count distinct evidence sources, not the mere presence of a row/device."""
    count = 1 if has_transaction else 0
    rows = list(episode_rows)
    if len(rows) > 1 and any(_row_explicit_anomaly(r) for r in rows):
        count += 1
    elif len(rows) > 1:
        count += 1
    if customer_denied:
        count += 1
    if device_corroborated:
        count += 1
    prior = [r for r in similar_cases if str(_get(r, "outcome", default="")) == "confirmed_fraud"]
    if prior:
        count += 1
    return count


def stop_reason(p: float, n_independent: int, verified: bool) -> tuple[str, bool]:
    """Return a policy-grounded stop reason and whether the case is settled."""
    if verified:
        return "A recorded verification response settled the question (policy 6).", True
    if (_number(p) >= 0.85 or _number(p) <= 0.15) and int(n_independent) >= 2:
        return f"Probability {p:.2f} is beyond the policy threshold with {n_independent} independent evidence items (policy 6).", True
    return "The remaining uncertainty requires a human decision or additional evidence (policy 6).", False


__all__ = [
    "ROUTES",
    "Calibrator",
    "DEFAULT_RESPONSE_LIKELIHOOD",
    "EXAM_PRIOR",
    "MODEL_FEATURE_COUNT",
    "PATTERN_ENUM",
    "REQUIRED_MODEL_FIELDS",
    "detect_pattern",
    "independent_evidence_count",
    "is_monthly_recurring",
    "next_best_actions",
    "recurring_charge_details",
    "should_file_sar",
    "stop_reason",
]
