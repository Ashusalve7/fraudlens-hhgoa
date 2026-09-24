"""FraudLens case runner.

The runner is a deterministic orchestration layer.  It retrieves evidence at a
case's ``opened_at`` cutoff, assesses the canonical production detector, applies
R1-R10, and renders the sponsor answer shape.  It does not make a channel-only
fraud inference and it does not treat a simulated response as a replacement
calibrator score.
"""

from __future__ import annotations

import copy
import json
import os
import shutil
import sys
import tempfile
import time
from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "agent"))

from decision import (  # noqa: E402
    Calibrator,
    detect_pattern,
    independent_evidence_count,
    next_best_actions,
    recurring_charge_details,
    should_file_sar,
    stop_reason,
)
from episodes import (  # noqa: E402
    build_episode,
    episode_bounds,
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
from evidence import Evidence  # noqa: E402
from features import (  # noqa: E402
    compute_features,
    episode_features,
    summarize_device_corroboration,
)
from sar import build_sar as _build_sar  # noqa: E402

from validator import (  # noqa: E402
    ValidationContext,
    validate_files,
    validate_graph_files,
)

DATA = HERE.parent / "HHGOA_IEEE"
CASES_DIR = HERE / "cases"


def dt(s: Any) -> datetime:
    parsed = parse_ts(s)
    if parsed is None:
        raise ValueError(f"invalid timestamp: {s!r}")
    return parsed


def _fmt_ts(value: Any) -> str:
    parsed = parse_ts(value)
    return parsed.strftime("%Y-%m-%d %H:%M:%S") if parsed else str(value)


def _field(row: Mapping[str, Any] | None, *keys: str, default: Any = "") -> Any:
    if not row:
        return default
    for key in keys:
        if key in row and row[key] not in (None, "", "_NA_"):
            return row[key]
    return default


def _begin_case(ev: Any, case_id: str) -> None:
    """Reset a real Evidence ledger and support small test doubles."""
    for name in ("begin_case", "start_case", "reset_case"):
        method = getattr(ev, name, None)
        if callable(method):
            method(case_id)
            return
    calls = getattr(ev, "calls", None)
    if isinstance(calls, list):
        calls.clear()


def _tool_count(ev: Any) -> int:
    value = getattr(ev, "tool_count", None)
    if isinstance(value, int):
        return value
    value = getattr(ev, "call_count", None)
    if isinstance(value, int):
        return value
    calls = getattr(ev, "calls", None)
    return len(calls) if isinstance(calls, list) else 0


def _window(ev: Any, query_name: str) -> dict[str, str] | None:
    for record in reversed(getattr(ev, "query_log", []) or []):
        if record.get("query") == query_name:
            params = record.get("params", {})
            if "in_start" in params and "in_end" in params:
                return {"start": str(params["in_start"]), "end": str(params["in_end"])}
    return None


def load_case_pack() -> list[dict[str, Any]]:
    import csv

    with open(DATA / "case_pack.csv", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def select_cases(
    cases: Iterable[Mapping[str, Any]],
    selected_ids: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    """Select a subset while preserving canonical case-pack order."""
    if selected_ids is None:
        return [dict(case) for case in cases]
    wanted = {str(case_id).strip() for case_id in selected_ids if str(case_id).strip()}
    return [dict(case) for case in cases if str(case.get("case_id", "")) in wanted]


def normalize_answer(answer: Mapping[str, Any]) -> dict[str, Any]:
    """Return a non-mutating comparison form for full-pack versus subset runs."""
    normalized = copy.deepcopy(dict(answer))
    normalized["latency_s"] = 0.0
    return normalized


def _copy_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return dict(row)


def _ensure_flagged(
    rows: list[dict[str, Any]], flagged: Mapping[str, Any], cutoff: datetime
) -> list[dict[str, Any]]:
    visible = rows_at_cutoff(rows, cutoff, flagged=flagged)
    fid = txn_id(flagged)
    if fid and not any(txn_id(row) == fid for row in visible):
        fts = txn_ts(flagged)
        if fts is None or fts <= cutoff:
            visible.append(dict(flagged))
    return visible


def _device_id(ctx: Mapping[str, Any], txn: Mapping[str, Any]) -> str:
    device = ctx.get("device") or {}
    return str(_field(device, "device_id", "id", default="") or txn_device_id(txn))


def _case_trigger_denial(case: Mapping[str, Any]) -> bool:
    return str(case.get("trigger_type", "")).strip().lower() == "customer_report"


def _scenario_text(kind: str, txn: Mapping[str, Any], similar_ids: list[str], reason: str) -> str:
    amount = txn_amount(txn)
    channel = txn_channel(txn)
    if kind == "denied":
        basis = (
            f"nearest similar closed cases: {', '.join(similar_ids)}"
            if similar_ids
            else "the calibrated prior"
        )
        return (
            f"Simulated customer response: the customer states they did not authorize the {channel} "
            f"transaction of ${amount:,.2f}; the response assumption is based on {basis}."
        )
    if kind == "confirmed":
        basis = (
            f"nearest similar closed cases: {', '.join(similar_ids)}"
            if similar_ids
            else "the calibrated prior"
        )
        return (
            f"Simulated customer response: the customer confirms the {channel} transaction of "
            f"${amount:,.2f}; the response assumption is based on {basis}."
        )
    return f"Simulated response: no customer reply was available ({reason})."


def _should_request(initial: list[dict[str, Any]], p: float, pattern: str, trigger: str) -> bool:
    if trigger.strip().lower() == "customer_report":
        return False
    actions = {a.get("action") for a in initial}
    return "VERIFY_WITH_CUSTOMER" in actions and p < 0.85 and pattern != "card_testing"


def _simulate_response(p: float, pattern: str, similar_ids: list[str]) -> tuple[str, str]:
    """Choose a scenario branch without changing the calibrated score directly."""
    if p >= 0.55:
        return "denied", "the calibrated prior leans toward unauthorized use"
    if p <= 0.35:
        return "confirmed", "the calibrated prior leans toward legitimate use"
    return (
        "denied"
        if pattern in {"card_testing", "card_not_present_new_device", "undocumented"}
        else "confirmed",
        "the case is near the decision boundary, so the scenario tests the higher-risk branch"
        if pattern in {"card_testing", "card_not_present_new_device", "undocumented"}
        else "the case is near the decision boundary, so the scenario tests the customer-confirmation branch",
    )


def _shared_fact(dev: Mapping[str, Any], card_id: str, customer_id: str) -> dict[str, Any]:
    return summarize_device_corroboration(
        dev,
        own_card_id=card_id,
        own_customer_id=customer_id,
    )


def _count_independent(
    episode_rows: list[dict[str, Any]],
    *,
    customer_denied: bool,
    shared: Mapping[str, Any],
    similar_rows: list[dict[str, Any]],
) -> int:
    return independent_evidence_count(
        has_transaction=True,
        episode_rows=episode_rows,
        customer_denied=customer_denied,
        device_corroborated=bool(shared.get("corroborated")),
        similar_cases=similar_rows,
    )


def _detector_context(
    ctx: Mapping[str, Any],
    card_rows: list[dict[str, Any]],
    dev: Mapping[str, Any],
    txn: Mapping[str, Any],
    cutoff: datetime,
    *,
    customer_denied: bool = False,
    shared: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    """Build a bounded preliminary episode and the production feature context."""
    feats = compute_features(ctx, card_rows, dev, opened_at=cutoff)
    # Derive detector context from the bounded source window, not from a
    # pattern-none episode (which contains only the trigger and hides testing
    # or burst evidence).  The final fraud episode is rebuilt after detection.
    visible = rows_at_cutoff(card_rows, cutoff, flagged=txn)
    preliminary_ep = episode_features(visible, visible, txn_ts(txn) or cutoff, cutoff=cutoff)
    candidate_pattern = "card_not_present_fraud" if txn_channel(txn) == "online" else "none"
    candidate = build_episode(txn, visible, candidate_pattern, feats, cutoff=cutoff)
    for key in (
        "n_online_48h",
        "online_burst_48h",
        "testing_sequence",
        "testing_large_amount",
        "new_device_share",
        "proxy_share",
        "mixed_channel",
        "identity_anomaly",
        "near_threshold_burst_40m",
        "trip_like",
        "coordinated",
    ):
        if key in preliminary_ep:
            feats[key] = preliminary_ep[key]
    if _field(txn, "id_15", default="") or is_new_device(txn):
        feats["new_device_flagged"] = 1
    if is_proxy(txn):
        feats["proxy_flagged"] = 1
    if customer_denied:
        feats["customer_denied"] = True
    if shared:
        feats["connected_fraud"] = bool(shared.get("corroborated"))
        feats["cross_customer"] = len(shared.get("customers", [])) >= 2
        feats["coordinated_signal"] = bool(shared.get("corroborated") and len(shared.get("cards", [])) >= 1)
    return feats, candidate, preliminary_ep


def _query_windows(
    ev: Any,
    *,
    opened_at: datetime,
    t0: datetime,
) -> dict[str, dict[str, str]]:
    return {
        "card": _window(ev, "get_card_window")
        or {"start": _fmt_ts(opened_at - timedelta(days=60)), "end": _fmt_ts(opened_at)},
        "customer": _window(ev, "get_customer_history")
        or {"start": _fmt_ts(opened_at - timedelta(days=400)), "end": _fmt_ts(opened_at)},
        "device": _window(ev, "get_device_neighborhood")
        or {"start": _fmt_ts(opened_at - timedelta(days=7)), "end": _fmt_ts(opened_at)},
        "region": _window(ev, "get_region_activity")
        or {"start": _fmt_ts(t0 - timedelta(days=7)), "end": _fmt_ts(opened_at)},
    }


def investigate(ev: Evidence, cal: Calibrator, case: Mapping[str, Any]) -> dict[str, Any]:
    """Investigate one case without retaining state from the previous case."""
    t0_wall = time.time()
    case_id = str(case["case_id"])
    _begin_case(ev, case_id)
    state = ["TRIGGERED"]
    flagged_id = str(case["flagged_txn_id"]).strip()
    opened_at = dt(case["opened_at"])

    # 1. Context and cutoff -------------------------------------------------
    ctx = ev.txn_context(flagged_id)
    txn = dict(ctx.get("txn") or {})
    if not txn:
        raise ValueError(f"{case_id}: graph returned no flagged transaction {flagged_id}")
    txn.setdefault("txn_id", flagged_id)
    t0 = txn_ts(txn)
    if t0 is None:
        raise ValueError(f"{case_id}: flagged transaction has no timestamp")
    if t0 > opened_at:
        raise ValueError(f"{case_id}: flagged transaction is after opened_at")
    card_id = str(case["card_id"]).strip()
    customer_id = str(case["customer_id"]).strip()
    # Attach the actual device ID from the context for feature computation; the
    # transaction vertex itself does not carry a device_id attribute in the
    # installed schema.
    device_id = _device_id(ctx, txn)
    if device_id:
        txn["device_id"] = device_id
    state.append("CONTEXT_RETRIEVED")

    # The bounded graph algorithm is part of the decision evidence, not just a
    # dashboard decoration.  It confirms that the device/card path is present in
    # the returned relation set before shared-device corroboration can affect a
    # recommendation.
    ring_result = ev.graph_ring(flagged_id)
    ring_nodes = [
        dict(node)
        for node in ring_result.get("nodes", [])
        if isinstance(node, Mapping)
    ] if isinstance(ring_result, Mapping) else []
    ring_edges = [
        dict(edge)
        for edge in ring_result.get("edges", [])
        if isinstance(edge, Mapping)
    ] if isinstance(ring_result, Mapping) else []
    if not ring_nodes:
        raise ValueError(f"{case_id}: bounded graph ring returned no nodes")
    ring_device_ids = {
        str(node.get("id"))
        for node in ring_nodes
        if str(node.get("type", "")).lower() == "deviceprofile"
    }
    ring_card_ids = {
        str(node.get("id"))
        for node in ring_nodes
        if str(node.get("type", "")).lower() == "card"
    }
    algorithm_support = bool(
        ring_edges
        and (not device_id or device_id in ring_device_ids)
        and (not card_id or card_id in ring_card_ids)
    )

    # 2. Evidence queries: every end boundary is the case opening timestamp.
    card_start = min(t0 - timedelta(days=60), opened_at - timedelta(days=60))
    card_rows = list(ev.card_window(card_id, _fmt_ts(card_start), _fmt_ts(opened_at)))
    _history_cards, history_rows = ev.customer_history(
        customer_id,
        _fmt_ts(opened_at - timedelta(days=400)),
        _fmt_ts(opened_at),
    )
    if not history_rows:
        history_rows = list(card_rows)
    dev: dict[str, Any] = {"txns": [], "cards": [], "customers": [], "prior_cases": []}
    if device_id:
        dev = dict(
            ev.device_neighborhood(
                device_id,
                _fmt_ts(opened_at - timedelta(days=7)),
                _fmt_ts(opened_at),
            )
        )
        dev.setdefault("device_id", device_id)
        device_context = ctx.get("device") if isinstance(ctx.get("device"), Mapping) else {}
        for field in ("n_cards", "n_txn", "device_info", "os", "browser", "screen"):
            if field in device_context:
                dev.setdefault(field, device_context[field])
    region = str(_field(txn, "addr1", "region", default=""))
    if region:
        # The result is intentionally not merged: card_window is the complete
        # modeling source, while this bounded call records explicit region
        # provenance without changing feature semantics.
        list(
            ev.region_activity(
                card_id,
                region,
                _fmt_ts(opened_at - timedelta(days=7)),
                _fmt_ts(opened_at),
            )
        )
    state.append("EVIDENCE_GATHERED")

    # Defensive client-side cutoff, including transaction and device events.
    card_rows = _ensure_flagged(card_rows, txn, opened_at)
    history_rows = rows_at_cutoff(history_rows, opened_at)
    if isinstance(dev, dict):
        dev["txns"] = rows_at_cutoff(dev.get("txns", []) or [], opened_at)
        dev["prior_cases"] = [
            r
            for r in (dev.get("prior_cases", []) or [])
            if not _field(r, "opened_at", "closed_at", default=None)
            or (
                _field(r, "opened_at", "closed_at", default=None)
                and dt(_field(r, "opened_at", "closed_at")) <= opened_at
            )
        ]

    # 3. Recurrence, shared corroboration, and pattern assessment ----------
    recurrence = recurring_charge_details(
        txn,
        history_rows,
        card_id=card_id,
        cutoff=opened_at,
    )
    shared = _shared_fact(dev, card_id, customer_id)
    shared["algorithm_support"] = algorithm_support
    if shared.get("corroborated") and not algorithm_support:
        shared["corroborated"] = False
    explicit_denial = _case_trigger_denial(case) and not recurrence.get("is_monthly", False)
    feats, _preliminary, preliminary_ep = _detector_context(
        ctx,
        card_rows,
        dev,
        txn,
        opened_at,
        customer_denied=explicit_denial,
        shared=shared,
    )
    # A customer report is already a denial.  Make that fact available to the
    # detector and policy before constructing initial actions.
    if explicit_denial:
        feats["customer_denied"] = True
    if recurrence.get("is_monthly"):
        feats["recurring_r7"] = True
    if shared.get("corroborated"):
        feats["coordinated_signal"] = True
    if str(case.get("trigger_type", "")).strip().lower() == "analyst_request" and shared.get("corroborated"):
        # An analyst-requested shared-device investigation with a prior
        # confirmed case is the concrete R9 path, not a generic device claim.
        feats["coordinated_signal"] = True
        feats["cross_customer"] = len(shared.get("customers", [])) >= 2 or len(shared.get("cards", [])) >= 2

    pattern, pattern_why = detect_pattern(feats, preliminary_ep)
    # The explicit R7 discriminator takes precedence over a pattern label.
    r7 = bool(recurrence.get("is_monthly") and _case_trigger_denial(case))
    if r7:
        pattern, pattern_why = "none", "R7: approximately monthly same-card recurring charge"
    state.append("PATTERNS_ASSESSED")

    policy_memory = ev.policy_retrieval(
        (
            f"{_field(case, 'trigger_text', default='Review suspicious transaction')} "
            f"Pattern {pattern}. Determine the FraudLens policy response, evidence needs, "
            "approval routes, and escalation requirements."
        ),
        pattern=pattern,
        txn_id=flagged_id,
        card_id=card_id,
        customer_id=customer_id,
        device_id=device_id,
        limit=8,
    )
    policy_chunks = [
        dict(item)
        for item in policy_memory.get("policies", [])
        if isinstance(item, Mapping) and item.get("chunk_id")
    ]
    policy_provenance = policy_memory.get("provenance", {}).get("policy", {})
    if not policy_chunks or not policy_provenance.get("remote"):
        raise RuntimeError(f"{case_id}: graph-backed PolicyChunk retrieval is unavailable")
    state.append("POLICY_RETRIEVED")

    # 4. Memory lookup and final bounded episode ---------------------------
    episode_seed = build_episode(txn, card_rows, pattern, feats, cutoff=opened_at)
    episode = _ensure_flagged(episode_seed, txn, opened_at)
    # Never expose a row after the case was opened, even if a graph double did.
    episode = rows_at_cutoff(episode, opened_at, flagged=txn)
    if txn_id(txn) not in {txn_id(r) for r in episode}:
        episode.append(dict(txn))
    episode = sorted(
        {txn_id(r): r for r in episode if txn_id(r)}.values(),
        key=lambda r: (txn_ts(r) or datetime.max, txn_id(r)),
    )
    ep_features = episode_features(episode, card_rows, t0)
    # Detector context can gain a more precise signal from the final episode.
    feats.update(
        {
            k: v
            for k, v in ep_features.items()
            if k
            in {
                "testing_sequence",
                "n_online_48h",
                "online_burst_48h",
                "mixed_channel",
                "identity_anomaly",
                "trip_like",
                "near_threshold_burst_40m",
                "coordinated",
            }
        }
    )
    _p_history, p_initial = cal.score(feats)
    if explicit_denial:
        # The report is supplied evidence, not a later interview.  Include its
        # likelihood-ratio update in both initial and final probability.
        p_initial = cal.update_for_response(p_initial, "denied")
    # If the graph supplied a corroborated ring, make the policy precondition
    # explicit without changing the model artifact.
    connected_fraud = bool(shared.get("corroborated"))
    coordinated = bool(feats.get("coordinated_signal") and connected_fraud)
    strong_fraud_evidence = bool(
        connected_fraud and pattern in {"card_not_present_new_device", "undocumented"}
    )
    exposure_seed = round(sum(txn_amount(row) for row in episode), 2)
    if not exposure_seed and txn_id(txn):
        exposure_seed = round(txn_amount(txn), 2)
    similar_cases = list(ev.similar_cases(pattern, exposure_seed))[:3]
    similar_ids = [str(r.get("case_id")) for r in similar_cases if r.get("case_id")]
    # Memory can inform the response scenario, but a generic similar-case row
    # must not independently settle a case when the production pattern registry
    # found no pattern-specific evidence.
    memory_evidence = similar_cases if pattern != "none" else []
    state.append("MEMORY_RETRIEVED")

    evidence_requests: list[dict[str, Any]] = []
    scenario_kind: str | None = None
    scenario_text = ""
    p_final = p_initial
    customer_denied = explicit_denial
    customer_confirmed = False

    if r7:
        # R7 asks for verification and does not block.  The confirmation below
        # is explicitly a scenario, not a hard probability rewrite.
        initial = next_best_actions(
            p_initial,
            exposure_seed,
            "none",
            bool(shared.get("cards")),
            customer_denied=False,
            customer_confirmed=False,
            no_reply_24h=False,
            testing_cleared_over_100=False,
            connected_fraud=connected_fraud,
            coordinated=False,
            n_independent=_count_independent(
                episode, customer_denied=False, shared=shared, similar_rows=memory_evidence
            ),
            verdict="uncertain",
            r7=True,
        )
        scenario_kind = "confirmed"
        scenario_text = _scenario_text("confirmed", txn, similar_ids, "R7 approximately-monthly recurrence")
        evidence_requests.append(
            {
                "type": "customer_validation",
                "asked_after_step": _tool_count(ev),
                "assumed_response": scenario_text,
            }
        )
        p_final = cal.update_for_response(p_initial, "confirmed")
        customer_confirmed = True
        final = next_best_actions(
            p_final,
            0.0,
            "none",
            bool(shared.get("cards")),
            customer_denied=False,
            customer_confirmed=True,
            no_reply_24h=False,
            testing_cleared_over_100=False,
            connected_fraud=connected_fraud,
            coordinated=False,
            n_independent=_count_independent(
                episode, customer_denied=False, shared=shared, similar_rows=memory_evidence
            ),
            verdict="legitimate",
            r7=False,
        )
    else:
        n_independent_initial = _count_independent(
            episode, customer_denied=explicit_denial, shared=shared, similar_rows=memory_evidence
        )
        initial = next_best_actions(
            p_initial,
            exposure_seed,
            pattern,
            bool(shared.get("cards")),
            customer_denied=explicit_denial,
            customer_confirmed=False,
            no_reply_24h=False,
            testing_cleared_over_100=bool(
                pattern == "card_testing" and any(txn_amount(r) > 100 for r in episode)
            ),
            connected_fraud=connected_fraud,
            coordinated=coordinated,
            n_independent=n_independent_initial,
            verdict="uncertain",
            strong_fraud_evidence=strong_fraud_evidence,
        )
        if _should_request(initial, p_initial, pattern, str(case.get("trigger_type", ""))):
            scenario_kind, scenario_reason = _simulate_response(p_initial, pattern, similar_ids)
            scenario_text = _scenario_text(scenario_kind, txn, similar_ids, scenario_reason)
            evidence_requests.append(
                {
                    "type": "customer_validation",
                    "asked_after_step": _tool_count(ev),
                    "assumed_response": scenario_text,
                }
            )
            p_final = cal.update_for_response(p_initial, scenario_kind)
            customer_denied = scenario_kind == "denied"
            customer_confirmed = scenario_kind == "confirmed"
        final = next_best_actions(
            p_final,
            exposure_seed if customer_denied or p_final >= 0.85 else 0.0,
            pattern,
            bool(shared.get("cards")),
            customer_denied=customer_denied,
            customer_confirmed=customer_confirmed,
            no_reply_24h=False,
            testing_cleared_over_100=bool(
                pattern == "card_testing" and any(txn_amount(r) > 100 for r in episode)
            ),
            connected_fraud=connected_fraud,
            coordinated=coordinated,
            n_independent=_count_independent(
                episode, customer_denied=customer_denied, shared=shared, similar_rows=memory_evidence
            ),
            verdict="fraud" if customer_denied else "uncertain",
            strong_fraud_evidence=strong_fraud_evidence,
        )
    state.append("NBA_INITIAL" if not evidence_requests else "EVIDENCE_REQUESTED")
    if evidence_requests:
        state.append("EVIDENCE_RECEIVED")
    state.append("NBA_FINAL")

    # 5. Verdict, episode, and SAR ------------------------------------------
    n_independent = _count_independent(
        episode, customer_denied=customer_denied, shared=shared, similar_rows=memory_evidence
    )
    if r7 or customer_confirmed:
        verdict, status = "legitimate", "closed_legitimate"
        affected: list[str] = []
        first_suspicious = ""
        output_pattern = "none"
        output_exposure = 0.0
    elif customer_denied or (
        p_final >= 0.85
        and n_independent >= 2
        and pattern != "none"
        and (strong_fraud_evidence or connected_fraud or coordinated)
    ):
        verdict, status = "fraud", "closed_fraud"
        affected = [txn_id(r) for r in episode if txn_id(r)]
        first_suspicious = episode_bounds(episode)[0]
        output_pattern = pattern
        output_exposure = round(sum(txn_amount(r) for r in episode), 2)
    elif p_initial <= 0.15 and n_independent >= 2 and pattern != "none":
        verdict, status = "legitimate", "closed_legitimate"
        affected, first_suspicious = [], ""
        output_pattern, output_exposure = "none", 0.0
    else:
        verdict, status = "uncertain", "escalated"
        output_pattern = pattern
        if connected_fraud or coordinated:
            affected = [txn_id(row) for row in episode if txn_id(row)]
            first_suspicious = episode_bounds(episode)[0]
            output_exposure = round(sum(txn_amount(row) for row in episode), 2)
        else:
            affected, first_suspicious = [], ""
            output_exposure = 0.0

    connected_cards = (
        sorted(str(value) for value in shared.get("cards", []) if value)[:50]
        if connected_fraud or coordinated
        else []
    )
    device_profiles = [device_id] if device_id and (connected_fraud or coordinated) else []
    sar_file, sar_reason = should_file_sar(
        verdict,
        output_exposure,
        output_pattern,
        bool(shared.get("cards")),
        connected_fraud=connected_fraud,
        coordinated=coordinated,
        strong_suspicion=verdict == "uncertain" and connected_fraud,
    )
    # The policy function and SAR gate use the same fact set.  If a caller uses
    # a custom policy implementation, keep the answer internally consistent.
    final_actions = {a.get("action") for a in final}
    if sar_file and "FILE_REPORT" not in final_actions:
        final.append(
            {"action": "FILE_REPORT", "route": "L2", "reason": "3a: corroborated policy report basis"}
        )
    if not sar_file and "FILE_REPORT" in final_actions:
        final = [a for a in final if a.get("action") != "FILE_REPORT"]

    windows = _query_windows(ev, opened_at=opened_at, t0=t0)
    evidence_list = build_evidence(
        case,
        txn,
        feats,
        episode,
        output_pattern,
        pattern_why,
        dev,
        similar_ids,
        evidence_requests,
        query_windows=windows,
        device_id=device_id,
        customer_report_denial=explicit_denial,
        connected_fraud=connected_fraud,
        policy_chunks=policy_chunks,
        graph_ring=ring_result,
        cutoff=opened_at,
    )
    summary = build_summary(
        case,
        txn,
        output_pattern,
        p_final,
        verdict,
        affected,
        output_exposure,
        customer_denied,
        customer_confirmed,
        {"device_id": device_id} if device_id else {},
        evidence_requests=evidence_requests,
        customer_report_denial=explicit_denial,
        connected_fraud=connected_fraud,
    )
    what_changed = describe_change(initial, final, customer_denied, customer_confirmed, p_initial, p_final)
    stop, _settled = stop_reason(p_final, n_independent, bool(evidence_requests))

    sar = build_sar(
        sar_file,
        sar_reason,
        case,
        customer_id,
        card_id,
        affected,
        output_exposure,
        txn,
        output_pattern,
        {"device_id": device_id, **(dev if isinstance(dev, dict) else {})},
        episode_rows=episode,
        connected_cards=connected_cards,
        connected_devices=device_profiles,
        connected_fraud_cases=(
            shared.get("fraud_cases", []) if connected_fraud else []
        ),
        connected_fraud=connected_fraud,
        coordinated=coordinated,
        customer_asked=bool(evidence_requests),
        customer_denied=customer_denied or explicit_denial,
        evidence_requests=evidence_requests,
    )
    graph_case_id = f"AG-{case_id}"
    writer = getattr(ev, "write_agent_case", None)
    will_write = callable(writer)
    base_tool_count = _tool_count(ev)
    answer: dict[str, Any] = {
        "case_id": case_id,
        "case": {
            "status": status,
            "verdict": verdict,
            "fraud_probability": round(float(p_final), 4),
            "pattern": output_pattern,
            "pattern_description": pattern_why if output_pattern == "undocumented" else "",
            "affected_txn_ids": affected,
            "first_suspicious_txn_id": first_suspicious,
            "connected_card_ids": connected_cards,
            "connected_device_profiles": device_profiles,
            "exposure_usd": round(float(output_exposure), 2),
            "evidence": evidence_list,
            "similar_prior_cases": similar_ids,
            "summary": summary,
            "written_to_graph": will_write,
            "graph_case_id": graph_case_id if will_write else "",
        },
        "evidence_requests": evidence_requests,
        "next_best_actions": {
            "initial": initial,
            "final": final,
            "what_changed": what_changed,
        },
        "sar": sar,
        "stop_reason": stop,
        # A successful case_write is itself an auditable MCP tool call.  A failed
        # attempt is also retained by the adapter ledger, so both paths count it.
        "tool_calls": base_tool_count + int(will_write),
        "tokens": 0,
        "latency_s": round(time.time() - t0_wall, 4),
    }

    if will_write:
        prior_case_scores: dict[str, float] = {}
        for row in similar_cases[:3]:
            case_ref = str(row.get("case_id", "")).strip()
            if not case_ref:
                continue
            try:
                other_exposure = abs(float(row.get("exposure_usd", 0.0) or 0.0))
            except (TypeError, ValueError):
                continue
            distance = abs(other_exposure - exposure_seed)
            prior_case_scores[case_ref] = round(
                1.0 / (1.0 + distance / max(exposure_seed, 1.0)),
                6,
            )
        try:
            persisted = writer(
                {
                    "case_id": graph_case_id,
                    "verdict": verdict,
                    "pattern": output_pattern,
                    "pattern_description": pattern_why if output_pattern == "undocumented" else "",
                    "fraud_probability": round(float(p_final), 4),
                    "exposure_usd": round(float(output_exposure), 2),
                    "status": status,
                    "opened_at": _fmt_ts(opened_at),
                    "stop_reason": stop,
                    "summary": summary,
                    "answer_json": json.dumps(answer, sort_keys=True, separators=(",", ":")),
                },
                affected[:50],
                [card_id, *connected_cards],
                device_profiles,
                similar_ids[:3],
                prior_case_scores=prior_case_scores,
            )
            if str(persisted) != graph_case_id:
                raise RuntimeError("graph returned a different AgentCase identifier")
            state.append("CASE_WRITTEN")
        except Exception:
            # A graph write failure is explicit in the exported answer.  The
            # adapter ledger retains the failed call for audit/debugging.
            answer["case"]["written_to_graph"] = False
            answer["case"]["graph_case_id"] = ""
        answer["tool_calls"] = _tool_count(ev)

    state.append("ANSWER_EXPORTED")
    # ``state`` is intentionally not serialized: the sponsor answer format is
    # strict and rejects debug/extra top-level fields.
    _ = state
    return answer


def build_evidence(
    case: Mapping[str, Any],
    txn: Mapping[str, Any],
    feats: Mapping[str, Any],
    ep_rows: Iterable[Mapping[str, Any]],
    pattern: str,
    pattern_why: str,
    dev: Mapping[str, Any],
    similar_ids: Iterable[str],
    evidence_requests: Iterable[Mapping[str, Any]],
    *,
    query_windows: Mapping[str, Mapping[str, str]] | None = None,
    device_id: str = "",
    customer_report_denial: bool = False,
    connected_fraud: bool = False,
    policy_chunks: Iterable[Mapping[str, Any]] | None = None,
    graph_ring: Mapping[str, Any] | None = None,
    cutoff: datetime | str | None = None,
) -> list[dict[str, Any]]:
    """Render traceable claims using the exact rows and query windows supplied."""
    rows = [dict(row) for row in ep_rows or []]
    if cutoff is not None:
        rows = rows_at_cutoff(rows, cutoff)
        if txn_ts(txn) is not None and txn_ts(txn) > dt(cutoff):
            return []
    similar_id_list = [str(value) for value in similar_ids or [] if value]
    request_list = [dict(request) for request in evidence_requests or [] if isinstance(request, Mapping)]
    windows = dict(query_windows or {})
    result: list[dict[str, Any]] = []
    tid = txn_id(txn)
    result.append(
        {
            "claim": (
                f"Flagged transaction {tid}: ${txn_amount(txn):,.2f} {txn_channel(txn)} "
                f"({_field(txn, 'product_cd', 'ProductCD', default='unknown')}) with model risk score "
                f"{float(_field(txn, 'risk_score', default=0) or 0):.2f}; the score is an investigation input, not a verdict."
            ),
            "source": "graph",
            "ref": f"query:get_transaction_context(txn_id={tid})",
            "entity_ids": [tid] if tid else [],
        }
    )
    if isinstance(graph_ring, Mapping):
        ring_nodes = [
            node for node in graph_ring.get("nodes", []) if isinstance(node, Mapping)
        ]
        ring_edges = [
            edge for edge in graph_ring.get("edges", []) if isinstance(edge, Mapping)
        ]
        ring_ids = [tid] if tid else []
        result.append(
            {
                "claim": (
                    f"The bounded graph algorithm returned {len(ring_nodes)} node(s) and "
                    f"{len(ring_edges)} observed edge(s); its scope is the returned relation set, "
                    "not an unbounded global community."
                ),
                "source": "graph",
                "ref": f"mcp:graph_ring(txn_id={tid})",
                "entity_ids": ring_ids,
            }
        )
    for policy in list(policy_chunks or [])[:3]:
        chunk_id = str(_field(policy, "chunk_id", default="")).strip()
        title = str(_field(policy, "title", default="retrieved policy")).strip()
        provenance = policy.get("provenance", {}) if isinstance(policy, Mapping) else {}
        rule = str(_field(provenance, "policy_rule", default="")).strip()
        suffix = f" Rules: {rule}." if rule else ""
        result.append(
            {
                "claim": (
                    f"Retrieved sponsor policy chunk '{title}' was ranked for this case; "
                    f"the deterministic R1-R10 policy engine, not retrieval score, controls actions.{suffix}"
                ),
                "source": "graph",
                "ref": f"mcp:policy_retrieval(chunk_id={chunk_id})",
                "entity_ids": [],
            }
        )
    if rows:
        start = windows.get("card", {}).get("start", "the retrieved card window")
        end = windows.get("card", {}).get("end", "the investigation cutoff")
        result.append(
            {
                "claim": (
                    f"The bounded episode selected {len(rows)} transaction(s), totaling "
                    f"${sum(txn_amount(r) for r in rows):,.2f}, from the card-window query run "
                    f"from {start} through {end}."
                ),
                "source": "graph",
                "ref": f"query:get_card_window(start={start}, end={end})",
                "entity_ids": [txn_id(r) for r in rows if txn_id(r)],
            }
        )
    actual_device = str(device_id or _field(dev, "device_id", "id", default=""))
    if actual_device:
        dwin = windows.get("device", {})
        dstart, dend = (
            dwin.get("start", "the retrieved device window"),
            dwin.get("end", "the investigation cutoff"),
        )
        dev_cards = []
        for item in dev.get("cards", []) or []:
            value = _field(item, "card_id", "id", default=item if isinstance(item, str) else "")
            if value:
                dev_cards.append(str(value))
        prior_fraud = [
            r
            for r in (dev.get("prior_cases", []) or [])
            if str(_field(r, "outcome", default="")).lower() == "confirmed_fraud"
        ]
        claim = (
            f"The device-neighborhood query for {actual_device} from {dstart} through {dend} returned "
            f"{len(dev_cards)} card ID(s)"
        )
        if connected_fraud and prior_fraud:
            claim += f" and {len(prior_fraud)} prior confirmed-fraud case(s), providing corroboration."
        else:
            claim += "; device reuse alone is not treated as connected fraud."
        prior_ids = [str(_field(row, "case_id", default="")) for row in prior_fraud]
        result.append(
            {
                "claim": claim,
                "source": "graph",
                "ref": f"query:get_device_neighborhood(device_id={actual_device}, start={dstart}, end={dend})",
                "entity_ids": [actual_device, *dev_cards, *[value for value in prior_ids if value]],
            }
        )
    if similar_id_list:
        result.append(
            {
                "claim": (
                    f"Retrieved {len(similar_id_list)} nearest closed case(s) for pattern memory: "
                    f"{', '.join(similar_id_list)}."
                ),
                "source": "graph",
                "ref": f"query:find_similar_cases(pattern={pattern})",
                "entity_ids": similar_id_list,
            }
        )
    if customer_report_denial:
        result.append(
            {
                "claim": "The case trigger explicitly reports that the customer did not authorize the flagged transaction; no later interview is asserted.",
                "source": "customer",
                "ref": "trigger:customer_report",
                "entity_ids": [tid] if tid else [],
            }
        )
    for index, request in enumerate(request_list, 1):
        result.append(
            {
                "claim": f"Evidence request {index} recorded this explicitly simulated response: {request.get('assumed_response', '')}",
                "source": "customer",
                "ref": f"evidence_request:{index}",
                "entity_ids": [],
            }
        )
    if pattern == "undocumented" and pattern_why:
        if actual_device:
            dwin = windows.get("device", {})
            ref = (
                "query:get_device_neighborhood("
                f"device_id={actual_device}, start={dwin.get('start', 'the retrieved device window')}, "
                f"end={dwin.get('end', 'the investigation cutoff')})"
            )
            source = "graph"
        else:
            ref = "agent/decision.py::detect_pattern"
            source = "document"
        result.append(
            {
                "claim": pattern_why,
                "source": source,
                "ref": ref,
                "entity_ids": [value for value in (tid, actual_device) if value],
            }
        )
    # De-duplicate exact evidence objects while preserving query order.
    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in result:
        key = json.dumps(item, sort_keys=True, default=str)
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def build_summary(
    case: Mapping[str, Any],
    txn: Mapping[str, Any],
    pattern: str,
    p_final: float,
    verdict: str,
    affected: list[str],
    exposure: float,
    denied: bool,
    confirmed: bool,
    device: Mapping[str, Any],
    *,
    evidence_requests: Iterable[Mapping[str, Any]] | None = None,
    customer_report_denial: bool = False,
    connected_fraud: bool = False,
) -> str:
    trigger = {
        "risk_score": f"the model scored transaction {txn_id(txn)} at {float(_field(txn, 'risk_score', default=0) or 0):.2f}",
        "customer_report": f"the customer reported an unauthorized purchase on transaction {txn_id(txn)}",
        "analyst_request": f"an analyst requested review of transaction {txn_id(txn)}",
    }.get(str(case.get("trigger_type", "")).strip().lower(), f"transaction {txn_id(txn)} triggered review")
    sentences = [
        f"Alert {case.get('case_id')}: {trigger} (${txn_amount(txn):,.2f}, {txn_channel(txn)}).",
    ]
    if verdict == "fraud":
        sentences.append(
            f"Investigation supports {pattern.replace('_', ' ')} with {len(affected)} transaction(s) in the bounded episode and ${exposure:,.2f} exposure."
        )
    elif verdict == "legitimate":
        sentences.append(
            "The available evidence is consistent with legitimate activity; no fraud episode is asserted."
        )
    else:
        sentences.append(
            f"The evidence remains uncertain with fraud probability {p_final:.2f}; the alert is escalated rather than treated as a confirmed fraud finding."
        )
    if denied:
        if customer_report_denial:
            sentences.append(
                "The case trigger itself explicitly reports the customer did not authorize the transaction."
            )
        elif list(evidence_requests or []):
            sentences.append("The separately recorded customer evidence response denies the transaction.")
    elif confirmed:
        sentences.append("The separately recorded customer evidence response confirms the transaction.")
    if connected_fraud:
        sentences.append(
            "The graph neighborhood contains corroborated fraud on a connected card, not merely device reuse."
        )
    return " ".join(sentences)


def _action_key(action: Mapping[str, Any]) -> tuple[str, str]:
    return (str(action.get("action", "")), str(action.get("route", "")))


def action_diff(
    initial: Iterable[Mapping[str, Any]], final: Iterable[Mapping[str, Any]]
) -> dict[str, list[str]]:
    """Return material additions, removals, route changes, and reordering."""
    before_list = [dict(action) for action in initial]
    after_list = [dict(action) for action in final]
    before = {str(action.get("action", "")): action for action in before_list}
    after = {str(action.get("action", "")): action for action in after_list}
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    changed = sorted(
        f"{name} route {before[name].get('route')}→{after[name].get('route')}"
        for name in set(before) & set(after)
        if before[name].get("route") != after[name].get("route")
    )
    common = set(before) & set(after)
    before_order = [name for name in before if name in common]
    after_order = [name for name in after if name in common]
    if before_order != after_order:
        changed.append("action order " + "→".join(after_order))
    return {"added": added, "removed": removed, "changed": changed}


def describe_change(
    initial: Iterable[Mapping[str, Any]],
    final: Iterable[Mapping[str, Any]],
    denied: bool = False,
    confirmed: bool = False,
    p0: float | None = None,
    p1: float | None = None,
) -> str:
    """Describe the actual material action diff; identical actions say nothing."""
    diff = action_diff(initial, final)
    if not any(diff.values()):
        return "nothing"
    pieces: list[str] = []
    if diff["added"]:
        pieces.append("added " + ", ".join(diff["added"]))
    if diff["removed"]:
        pieces.append("removed " + ", ".join(diff["removed"]))
    if diff["changed"]:
        pieces.append("changed " + "; ".join(diff["changed"]))
    return "The final recommendation " + "; ".join(pieces) + "."


def build_sar(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Public compatibility wrapper for the structured SAR renderer."""
    return _build_sar(*args, **kwargs)


def main() -> int:
    only = None
    if "--cases" in sys.argv:
        index = sys.argv.index("--cases") + 1
        if index < len(sys.argv):
            only = set(sys.argv[index].split(","))
    ev = Evidence()
    cal = Calibrator()
    selected = select_cases(load_case_pack(), only)
    if not selected:
        raise SystemExit("no benchmark cases selected")
    CASES_DIR.mkdir(exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".case-staging-", dir=CASES_DIR))
    answers: list[tuple[Mapping[str, Any], dict[str, Any]]] = []
    try:
        # Investigate and persist to staging first. Current release files are not
        # touched if a graph call, schema check, or semantic validator fails.
        for case in selected:
            answer = investigate(ev, cal, case)
            answers.append((case, answer))
            staged = staging / f"{case['case_id']}.json"
            staged.write_text(
                json.dumps(answer, indent=2, default=str),
                encoding="utf-8",
            )
            c = answer["case"]
            print(
                f"{case['case_id']}: {c['verdict']:10s} p={c['fraud_probability']:.2f} "
                f"pattern={c['pattern']:28s} exposure=${c['exposure_usd']:>9,.2f} "
                f"sar={answer['sar']['file']!s:5s} tools={answer['tool_calls']} "
                f"latency={answer['latency_s']}s",
                flush=True,
            )

        expected_tools = {
            str(answer["case_id"]): int(answer["tool_calls"])
            for _case, answer in answers
        }
        findings = validate_files(
            selected,
            staging,
            ValidationContext.from_repo(HERE, DATA),
            expected_tool_calls=expected_tools,
        )
        problems = [
            f"{case_id}: {problem}"
            for case_id, items in findings.items()
            for problem in items
        ]
        if problems:
            raise RuntimeError(
                "staged case pack failed semantic validation:\n"
                + "\n".join(f" - {problem}" for problem in problems)
            )
        graph_findings = validate_graph_files(selected, staging, ev)
        graph_problems = [
            f"{case_id}: {problem}"
            for case_id, items in graph_findings.items()
            for problem in items
        ]
        if graph_problems:
            raise RuntimeError(
                "staged case pack failed graph read-back validation:\n"
                + "\n".join(f" - {problem}" for problem in graph_problems)
            )
        for case, _answer in answers:
            case_id = str(case["case_id"])
            os.replace(staging / f"{case_id}.json", CASES_DIR / f"{case_id}.json")
    finally:
        close = getattr(ev, "close", None)
        if callable(close):
            close()
        shutil.rmtree(staging, ignore_errors=True)
    print(f"Committed {len(answers)} semantically validated case answers.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
