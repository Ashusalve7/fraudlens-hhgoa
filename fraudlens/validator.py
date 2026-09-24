"""Semantic validator for FraudLens answer files.

The validator checks facts and policy relationships, not merely JSON shape.  It
uses local parquet/CSV artifacts when available and never opens a graph
connection by default.  A caller may provide graph IDs or a graph-existence
callback for an explicit integration check.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import sys
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "HHGOA_IEEE"
CASES_DIR = HERE / "cases"
ANSWER_SCHEMA_PATH = HERE / "schemas" / "answer.schema.json"

PATTERN_ENUM = {
    "card_testing",
    "card_not_present_fraud",
    "card_not_present_new_device",
    "out_of_region_use",
    "account_takeover",
    "undocumented",
    "none",
}
ACTIONS = {
    "ALLOW_TRANSACTION",
    "DECLINE_TRANSACTION",
    "MONITOR_CARD",
    "MONITOR_CONNECTED_CARDS",
    "WARN_CUSTOMER",
    "VERIFY_WITH_CUSTOMER",
    "STEP_UP_AUTH",
    "BLOCK_CARD",
    "BLOCK_ALL_CARDS",
    "GENERATE_REPORT",
    "CREATE_CASE",
    "FILE_REPORT",
    "ESCALATE_TO_ANALYST",
    "CLOSE_NO_FRAUD",
}
AUTO_ACTIONS = {
    "ALLOW_TRANSACTION",
    "MONITOR_CARD",
    "MONITOR_CONNECTED_CARDS",
    "WARN_CUSTOMER",
    "VERIFY_WITH_CUSTOMER",
    "STEP_UP_AUTH",
    "GENERATE_REPORT",
    "CREATE_CASE",
    "ESCALATE_TO_ANALYST",
    "CLOSE_NO_FRAUD",
}
REQUEST_TYPES = {"customer_validation", "step_up_auth", "analyst_info"}
EVIDENCE_SOURCES = {"graph", "document", "customer", "external"}
STATUSES = {"open", "closed_fraud", "closed_legitimate", "escalated"}
VERDICTS = {"fraud", "legitimate", "uncertain"}

TOP_FIELDS = {
    "case_id",
    "case",
    "evidence_requests",
    "next_best_actions",
    "sar",
    "stop_reason",
    "tool_calls",
    "tokens",
    "latency_s",
}
CASE_FIELDS = {
    "status",
    "verdict",
    "fraud_probability",
    "pattern",
    "pattern_description",
    "affected_txn_ids",
    "first_suspicious_txn_id",
    "connected_card_ids",
    "connected_device_profiles",
    "exposure_usd",
    "evidence",
    "similar_prior_cases",
    "summary",
    "written_to_graph",
    "graph_case_id",
}
EVIDENCE_FIELDS = {"claim", "source", "ref", "entity_ids"}
REQUEST_FIELDS = {"type", "asked_after_step", "assumed_response"}
NBA_FIELDS = {"initial", "final", "what_changed"}
ACTION_FIELDS = {"action", "route", "reason"}
SAR_FIELDS = {"file", "reason", "narrative", "subjects", "total_amount_usd", "activity_dates"}


def _dt(value: Any) -> datetime | None:
    if value in (None, "", "_NA_"):
        return None
    if isinstance(value, datetime):
        parsed = value
    elif hasattr(value, "to_pydatetime"):
        try:
            parsed = value.to_pydatetime()
        except Exception:
            return None
        if not isinstance(parsed, datetime):
            return None
    else:
        parsed = None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
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


def _num(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _field(row: Mapping[str, Any] | None, *keys: str, default: Any = "") -> Any:
    if not row:
        return default
    for key in keys:
        if key in row and row[key] not in (None, "", "_NA_"):
            return row[key]
    return default


def _sentences(text: str) -> list[str]:
    cleaned = str(text or "").strip()
    if not cleaned:
        return []
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", cleaned) if part.strip()]


def _action_key(action: Mapping[str, Any]) -> tuple[str, str]:
    return (str(action.get("action", "")), str(action.get("route", "")))


@dataclass
class ValidationContext:
    case_rows: dict[str, dict[str, Any]] = field(default_factory=dict)
    txn_meta: dict[str, dict[str, Any]] = field(default_factory=dict)
    card_ids: set[str] = field(default_factory=set)
    customer_ids: set[str] = field(default_factory=set)
    device_ids: set[str] = field(default_factory=set)
    closed_case_ids: set[str] = field(default_factory=set)
    graph_case_ids: set[str] | None = None
    graph_case_exists: Callable[[str], bool] | None = None

    def valid_id(self, value: Any) -> bool:
        text = str(value)
        return (
            text in self.txn_meta
            or text in self.card_ids
            or text in self.customer_ids
            or text in self.device_ids
            or text in self.closed_case_ids
        )

    def txn(self, txn_id: str) -> dict[str, Any] | None:
        return self.txn_meta.get(str(txn_id))

    @classmethod
    def from_repo(cls, root: Path = HERE, data: Path | None = None) -> ValidationContext:
        data = data or root.parent / "HHGOA_IEEE"
        context = cls()
        pack = data / "case_pack.csv"
        if pack.exists():
            with pack.open(newline="", encoding="utf-8") as handle:
                for row in csv.DictReader(handle):
                    context.case_rows[str(row["case_id"])] = dict(row)
        closed = data / "closed_cases_history.csv"
        if closed.exists():
            with closed.open(newline="", encoding="utf-8") as handle:
                context.closed_case_ids = {str(row["case_id"]) for row in csv.DictReader(handle)}
        try:
            import pandas as pd
        except ImportError:
            pd = None  # type: ignore
        if pd is not None:
            txn_path = root / "pipeline" / "out" / "load" / "v_Transaction.parquet"
            if txn_path.exists():
                frame = pd.read_parquet(
                    txn_path,
                    columns=["txn_id", "ts", "amount", "card_id"]
                    if _has_parquet_columns(txn_path, {"card_id"})
                    else ["txn_id", "ts", "amount"],
                )
                for row in frame.to_dict("records"):
                    context.txn_meta[str(row["txn_id"])] = dict(row)
            card_path = root / "pipeline" / "out" / "card_map.parquet"
            if card_path.exists():
                cards = pd.read_parquet(card_path)
                context.card_ids = {str(v) for v in cards["card_id"].dropna()}
                context.customer_ids = {str(v) for v in cards["customer_id"].dropna()}
            if not context.device_ids:
                context.device_ids = _load_device_ids(data)
        if not context.customer_ids:
            context.customer_ids = {cid.split("-K", 1)[0] for cid in context.card_ids}
        return context

    def check_graph_case(self, graph_case_id: str) -> bool | None:
        if self.graph_case_exists is not None:
            return bool(self.graph_case_exists(graph_case_id))
        if self.graph_case_ids is not None:
            return graph_case_id in self.graph_case_ids
        return None


def _has_parquet_columns(path: Path, wanted: set[str]) -> bool:
    try:
        import pyarrow.parquet as pq

        return wanted.issubset(set(pq.ParquetFile(path).schema.names))
    except Exception:
        return False


def _load_device_ids(data: Path) -> set[str]:
    """Derive sponsor device IDs from identity without loading the raw 700MB CSV."""
    identity = data / "identity.csv"
    if not identity.exists():
        return set()
    result: set[str] = set()
    try:
        import pandas as pd

        for frame in pd.read_csv(
            identity,
            usecols=["DeviceInfo", "id_30", "id_31", "id_33"],
            chunksize=100_000,
            low_memory=False,
        ):
            for key in ("DeviceInfo", "id_30", "id_31", "id_33"):
                frame[key] = frame[key].fillna("").astype(str).replace("nan", "")
            for values in frame[["DeviceInfo", "id_30", "id_31", "id_33"]].itertuples(index=False, name=None):
                result.add("DP-" + hashlib.md5("|".join(values).encode()).hexdigest()[:12])
    except Exception:
        return set()
    return result


@lru_cache(maxsize=1)
def _answer_schema_validator():
    from jsonschema import Draft202012Validator, FormatChecker

    schema = json.loads(ANSWER_SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def schema_problems(answer: Any) -> list[str]:
    """Return deterministic strict-JSON-Schema findings for one answer."""
    errors = sorted(
        _answer_schema_validator().iter_errors(answer),
        key=lambda error: (tuple(str(part) for part in error.absolute_path), error.message),
    )
    return [f"schema {path}: {error.message}" for error in errors for path in [error.json_path]]


def _exact(problems: list[str], obj: Mapping[str, Any], allowed: set[str], label: str) -> None:
    for key in sorted(set(obj) - allowed):
        problems.append(f"extra {label} field '{key}'")
    for key in sorted(allowed - set(obj)):
        problems.append(f"missing {label} field '{key}'")


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _validate_evidence(
    evidence: Any,
    problems: list[str],
    context: ValidationContext,
    *,
    has_request: bool,
    explicit_denial: bool,
    cutoff: datetime | None,
) -> None:
    if not isinstance(evidence, list):
        problems.append("case.evidence must be a list")
        return
    for index, item in enumerate(evidence):
        label = f"evidence[{index}]"
        if not isinstance(item, Mapping):
            problems.append(f"{label} must be an object")
            continue
        _exact(problems, item, EVIDENCE_FIELDS, label)
        claim = str(item.get("claim", ""))
        source = item.get("source")
        ref = str(item.get("ref", ""))
        if source not in EVIDENCE_SOURCES:
            problems.append(f"{label} has invalid source {source!r}")
        if not claim.strip() or not ref.strip():
            problems.append(f"{label} missing claim/ref")
        entities = item.get("entity_ids")
        if not isinstance(entities, list) or any(not isinstance(v, str) for v in entities):
            problems.append(f"{label}.entity_ids must be a list of strings")
        else:
            for entity in entities:
                if not context.valid_id(entity):
                    problems.append(f"{label} references unknown entity {entity}")
        lower = claim.lower()
        if source == "customer":
            response_words = (
                "asked",
                "contacted",
                "confirmed",
                "denied",
                "recognized",
                "did not authorize",
                "did not authorise",
            )
            if any(word in lower for word in response_words) and not (has_request or explicit_denial):
                problems.append(
                    f"{label} claims a customer response without a request or explicit denial trigger"
                )
            if ("confirmed" in lower or "recognized" in lower) and not has_request:
                problems.append(f"{label} claims confirmation without an evidence request")
        if "get_device_neighborhood" in ref:
            if "device_id=" not in ref:
                problems.append(f"{label} device evidence lacks an actual device_id query parameter")
            if not any(entity.startswith("DP-") for entity in entities):
                problems.append(f"{label} device evidence lacks a device ID")
        if ("get_card_window" in ref or "get_customer_history" in ref or "get_region_activity" in ref) and (
            "start=" not in ref or "end=" not in ref
        ):
            problems.append(f"{label} query evidence lacks its actual time window")
        if cutoff is not None:
            # Check ISO date/time values in refs.  A future end bound is a
            # temporal leak even if the underlying row happens to be valid.
            for match in re.finditer(r"(?:start|end|opened_at)=([^,)]*)", ref):
                value = _dt(match.group(1))
                if value and value > cutoff:
                    problems.append(f"{label} query window extends beyond opened_at")


def _validate_actions(
    actions: Any,
    problems: list[str],
    *,
    label: str,
    exposure: float,
    verdict: str,
    pattern: str,
    evidence_text: str,
    has_request: bool,
    explicit_denial: bool,
    connected_fraud: bool,
) -> None:
    if not isinstance(actions, list):
        problems.append(f"{label} must be a list")
        return
    seen_actions: set[str] = set()
    for index, action in enumerate(actions):
        item_label = f"{label}[{index}]"
        if not isinstance(action, Mapping):
            problems.append(f"{item_label} must be an object")
            continue
        _exact(problems, action, ACTION_FIELDS, item_label)
        name = action.get("action")
        route = action.get("route")
        reason = str(action.get("reason", ""))
        if name not in ACTIONS:
            problems.append(f"{item_label} has unknown action {name!r}")
            continue
        if name in seen_actions:
            problems.append(f"{item_label} duplicates action {name}")
        seen_actions.add(str(name))
        if name in AUTO_ACTIONS and route != "auto":
            problems.append(f"{item_label} {name} must use auto")
        if name == "DECLINE_TRANSACTION" and route != "L1":
            problems.append(f"{item_label} DECLINE_TRANSACTION must use L1")
        if name == "BLOCK_CARD":
            expected = "L2" if exposure > 2500 else "L1"
            if route != expected:
                problems.append(
                    f"{item_label} BLOCK_CARD route must be {expected} at exposure ${exposure:,.2f}"
                )
        if name in {"BLOCK_ALL_CARDS", "FILE_REPORT"} and route != "L2":
            problems.append(f"{item_label} {name} must use L2")
        rule_numbers = [int(value) for value in re.findall(r"\bR(\d+)\b", reason, re.IGNORECASE)]
        has_policy_citation = bool(rule_numbers or re.search(r"\b3a\b|\bpolicy\b", reason, re.IGNORECASE))
        if not has_policy_citation or any(number not in range(1, 11) for number in rule_numbers):
            problems.append(f"{item_label} reason does not cite policy R1-R10, 3a, or policy")
        lower = reason.lower()
        if name == "BLOCK_CARD":
            if verdict == "legitimate":
                problems.append(f"{item_label} blocks a card in a legitimate verdict")
            testing_clear = pattern == "card_testing" and "over $100" in lower
            denial = explicit_denial or (has_request and "deni" in evidence_text.lower())
            corroborated = (
                connected_fraud
                or "confirmed fraud" in evidence_text.lower()
                or "corroborat" in evidence_text.lower()
            )
            if not (testing_clear or denial or corroborated):
                problems.append(f"{item_label} blocks a card without denial, testing, or corroborated fraud")
        credential_evidence = "credential" in evidence_text.lower()
        if name == "BLOCK_ALL_CARDS" and not ((connected_fraud and evidence_text) or credential_evidence):
            problems.append(f"{item_label} BLOCK_ALL_CARDS lacks multi-card/credential evidence")
        if name == "MONITOR_CONNECTED_CARDS" and not connected_fraud:
            problems.append(f"{item_label} monitors connected cards without corroborated graph fraud")
    if pattern == "card_testing":
        names = {a.get("action") for a in actions if isinstance(a, Mapping)}
        if not ({"DECLINE_TRANSACTION", "STEP_UP_AUTH"} & names) and "BLOCK_CARD" not in names:
            problems.append(f"{label} card-testing actions do not implement R5")
    if pattern == "undocumented":
        names = {a.get("action") for a in actions if isinstance(a, Mapping)}
        if "FILE_REPORT" in names and not (
            "coordinated" in evidence_text.lower() or "repeated abuse" in evidence_text.lower()
        ):
            problems.append(f"{label} files an undocumented pattern without coordinated/repeated evidence")


def _validate_sar(
    sar: Any,
    problems: list[str],
    context: ValidationContext,
    *,
    case: Mapping[str, Any],
    affected: list[str],
    exposure: float,
    has_request: bool,
    explicit_denial: bool,
    connected_fraud: bool,
) -> None:
    if not isinstance(sar, Mapping):
        problems.append("sar must be an object")
        return
    _exact(problems, sar, SAR_FIELDS, "sar")
    if not isinstance(sar.get("file"), bool):
        problems.append("sar.file must be boolean")
        return
    reason = str(sar.get("reason", ""))
    if not re.search(r"\bR(?:10|[1-9])\b|\b3a\b|\bpolicy\b", reason, re.IGNORECASE):
        problems.append("SAR reason does not cite policy R1-R10, 3a, or policy")
    if not sar["file"]:
        if (
            sar.get("narrative") != ""
            or sar.get("subjects") != []
            or sar.get("total_amount_usd") != 0
            or sar.get("activity_dates") != []
        ):
            problems.append("SAR false object must have empty narrative/subjects/amount/dates")
        return
    if not affected:
        problems.append("filed SAR must identify an affected transaction episode")
    narrative = str(sar.get("narrative", ""))
    sentences = _sentences(narrative)
    if not 6 <= len(sentences) <= 12:
        problems.append(f"SAR narrative sentence count {len(sentences)} outside 6-12")
    subjects = sar.get("subjects")
    if not isinstance(subjects, list) or not subjects or any(not isinstance(v, str) for v in subjects):
        problems.append("SAR subjects must be a non-empty list of IDs")
    else:
        for subject in subjects:
            if not context.valid_id(subject):
                problems.append(f"SAR subject {subject} is not a dataset ID")
    if _num(sar.get("total_amount_usd")) is None or abs(float(sar["total_amount_usd"]) - exposure) > 0.01:
        problems.append("SAR total_amount_usd does not equal case exposure")
    dates = sar.get("activity_dates")
    if (
        not isinstance(dates, list)
        or len(dates) != 2
        or any(not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(v)) for v in dates)
    ):
        problems.append("SAR activity_dates must contain two YYYY-MM-DD dates")
    else:
        actual_dates = []
        for tid in affected:
            meta = context.txn(str(tid))
            ts = _dt(meta.get("ts")) if meta else None
            if ts:
                actual_dates.append(ts.date().isoformat())
        if actual_dates and dates != [min(actual_dates), max(actual_dates)]:
            problems.append("SAR activity_dates are not the actual episode min/max dates")
    lower = narrative.lower()
    if (
        "$1,000" in lower or "1000" in lower or "exceed" in lower or "threshold" in lower
    ) and exposure <= 1000:
        problems.append("SAR makes an exposure-threshold claim without exposure above $1,000")
    if (
        re.search(r"(?:shared|connected|another card|ring|corroborat).{0,45}(?:fraud|abuse)", lower)
        and not connected_fraud
    ):
        problems.append("SAR shared-link claim lacks corroborated connected fraud")
    if any(
        word in lower
        for word in (
            "asked",
            "contacted",
            "confirmed",
            "denied",
            "recognized",
            "did not authorize",
            "did not authorise",
        )
    ):
        if not (has_request or explicit_denial):
            problems.append("SAR customer-response claim lacks a request or explicit denial trigger")
        if ("confirmed" in lower or "recognized" in lower) and not has_request:
            problems.append("SAR confirmation claim lacks an evidence request")


def validate_answer(
    answer: Mapping[str, Any],
    case_row: Mapping[str, Any],
    context: ValidationContext | None = None,
    *,
    expected_tool_calls: int | None = None,
    tool_call_baseline: int | None = None,
) -> list[str]:
    """Return all semantic problems for one answer; an empty list means valid."""
    context = context or ValidationContext(case_rows={str(case_row.get("case_id")): dict(case_row)})
    problems: list[str] = []
    if not isinstance(answer, Mapping):
        return ["answer must be an object", *schema_problems(answer)]
    problems.extend(schema_problems(answer))
    _exact(problems, answer, TOP_FIELDS, "top-level")
    case_id = str(case_row.get("case_id", ""))
    if answer.get("case_id") != case_id:
        problems.append("case_id mismatch")
    case = answer.get("case")
    if not isinstance(case, Mapping):
        problems.append("case must be an object")
        return problems
    _exact(problems, case, CASE_FIELDS, "case")
    status = case.get("status")
    verdict = case.get("verdict")
    if status not in STATUSES:
        problems.append("bad status")
    if verdict not in VERDICTS:
        problems.append("bad verdict")
    if verdict == "fraud" and status not in {"closed_fraud", "open"}:
        problems.append("fraud verdict has an inconsistent status")
    if verdict == "legitimate" and status != "closed_legitimate":
        problems.append("legitimate verdict must be closed_legitimate")
    if verdict == "uncertain" and status not in {"escalated", "open"}:
        problems.append("uncertain verdict must be escalated or open")
    p = _num(case.get("fraud_probability"))
    if p is None or not 0 <= p <= 1:
        problems.append("fraud_probability is not a finite number in [0,1]")
    if case.get("pattern") not in PATTERN_ENUM:
        problems.append("bad pattern")
    description = case.get("pattern_description")
    if case.get("pattern") == "undocumented":
        if not isinstance(description, str) or not 2 <= len(_sentences(description)) <= 3:
            problems.append("undocumented pattern_description must contain two or three sentences")
    elif description != "":
        problems.append("pattern_description must be empty for documented/none patterns")

    flagged = str(case_row.get("flagged_txn_id", ""))
    affected = case.get("affected_txn_ids")
    if not isinstance(affected, list) or any(not isinstance(v, str) for v in affected):
        problems.append("affected_txn_ids must be a list of strings")
        affected = []
    if len(affected) != len(set(affected)):
        problems.append("affected_txn_ids contains duplicates")
    for tid in affected:
        if not context.valid_id(tid):
            problems.append(f"affected transaction {tid} is not a dataset ID")
    first = case.get("first_suspicious_txn_id")
    if flagged and not context.valid_id(flagged):
        problems.append(f"flagged transaction {flagged} is not a dataset ID")
    exposure_value = _num(case.get("exposure_usd"))
    if exposure_value is None or exposure_value < 0:
        problems.append("exposure_usd must be a non-negative finite number")
    if verdict == "fraud":
        if flagged not in affected:
            problems.append("fraud episode does not include the flagged transaction")
        if not affected or first not in affected:
            problems.append("fraud episode has no valid first_suspicious_txn_id")
    if affected and exposure_value is not None:
        total = 0.0
        known_rows = 0
        for tid in affected:
            meta = context.txn(tid)
            if meta:
                known_rows += 1
                total += abs(_num(meta.get("amount")) or 0.0)
        if known_rows and abs(total - exposure_value) > 0.01:
            problems.append("exposure_usd does not equal the sum of affected transaction amounts")
    if verdict == "legitimate" and (
        affected or first or exposure_value != 0 or case.get("pattern") != "none"
    ):
        problems.append("legitimate case must have empty episode, zero exposure, and pattern none")
    if affected and flagged not in affected and verdict != "legitimate":
        problems.append("non-empty episode must include the flagged transaction")
    if first and first not in affected:
        problems.append("first_suspicious_txn_id is not in affected_txn_ids")
    if first and context.txn(first) and affected:
        first_ts = _dt(context.txn(first).get("ts"))
        timestamps = [_dt(context.txn(t).get("ts")) for t in affected if context.txn(t)]
        if first_ts and any(ts and ts < first_ts for ts in timestamps):
            problems.append("first_suspicious_txn_id is not the earliest affected transaction")
    opened = _dt(case_row.get("opened_at"))
    expected_card = str(case_row.get("card_id", ""))
    for tid in affected:
        meta = context.txn(str(tid))
        ts = _dt(meta.get("ts")) if meta else None
        if opened and ts and ts > opened:
            problems.append(f"affected transaction {tid} is after opened_at")
        meta_card = str(_field(meta, "card_id", "CardID", default="")) if meta else ""
        if expected_card and meta_card and meta_card != expected_card:
            problems.append(f"affected transaction {tid} belongs to {meta_card}, not {expected_card}")

    connected_cards = case.get("connected_card_ids")
    connected_devices = case.get("connected_device_profiles")
    similar = case.get("similar_prior_cases")
    for name, values in (
        ("connected_card_ids", connected_cards),
        ("connected_device_profiles", connected_devices),
        ("similar_prior_cases", similar),
    ):
        if not isinstance(values, list) or any(not isinstance(v, str) for v in values):
            problems.append(f"case.{name} must be a list of strings")
        else:
            for value in values:
                if not context.valid_id(value):
                    problems.append(f"case.{name} contains unknown ID {value}")

    summary = str(case.get("summary", ""))
    if not 2 <= len(_sentences(summary)) <= 6:
        problems.append("summary must contain two to six sentences")
    written = case.get("written_to_graph")
    if not isinstance(written, bool):
        problems.append("written_to_graph must be boolean")
    graph_id = case.get("graph_case_id")
    if written is True:
        if not isinstance(graph_id, str) or not graph_id:
            problems.append("written_to_graph case has no graph_case_id")
        else:
            exists = context.check_graph_case(graph_id)
            if exists is False:
                problems.append(f"graph case {graph_id} does not exist")
    elif graph_id not in ("", None):
        problems.append("unwritten case must have an empty graph_case_id")

    requests = answer.get("evidence_requests")
    if not isinstance(requests, list):
        problems.append("evidence_requests must be a list")
        requests = []
    explicit_denial = str(case_row.get("trigger_type", "")).strip().lower() == "customer_report"
    _validate_evidence(
        case.get("evidence"),
        problems,
        context,
        has_request=bool(requests),
        explicit_denial=explicit_denial,
        cutoff=opened,
    )
    tool_calls = answer.get("tool_calls")
    if not isinstance(tool_calls, int) or isinstance(tool_calls, bool) or tool_calls < 0:
        problems.append("tool_calls must be a non-negative integer")
        tool_calls = 0
    if expected_tool_calls is not None and tool_calls != expected_tool_calls:
        problems.append(f"tool_calls {tool_calls} does not match per-case count {expected_tool_calls}")
    if tool_call_baseline is not None and tool_calls < tool_call_baseline:
        problems.append("tool_calls appears to be a cumulative counter reset incorrectly")
    for index, request in enumerate(requests):
        label = f"evidence_requests[{index}]"
        if not isinstance(request, Mapping):
            problems.append(f"{label} must be an object")
            continue
        _exact(problems, request, REQUEST_FIELDS, label)
        if request.get("type") not in REQUEST_TYPES:
            problems.append(f"{label} has invalid request type")
        step = request.get("asked_after_step")
        if not isinstance(step, int) or isinstance(step, bool) or step < 0 or step > tool_calls:
            problems.append(f"{label}.asked_after_step must be a per-case integer within tool_calls")
        if (
            not isinstance(request.get("assumed_response"), str)
            or not request.get("assumed_response", "").strip()
        ):
            problems.append(f"{label} must record an assumed response")

    nba = answer.get("next_best_actions")
    if not isinstance(nba, Mapping):
        problems.append("next_best_actions must be an object")
        nba = {}
    else:
        _exact(problems, nba, NBA_FIELDS, "next_best_actions")
    evidence_value = case.get("evidence")
    evidence_items = evidence_value if isinstance(evidence_value, list) else []
    evidence_text = " ".join(
        str(item.get("claim", "")) for item in evidence_items if isinstance(item, Mapping)
    )
    has_request = bool(requests)
    request_text = " ".join(
        str(request.get("assumed_response", "")) for request in requests if isinstance(request, Mapping)
    )
    explicit_denial = explicit_denial or bool(
        re.search(r"\bdeni(?:ed|al)|\bdid not authori[sz]e\b", request_text, re.IGNORECASE)
    )
    connected_fraud = bool(
        re.search(
            r"(?:confirmed|corroborat|another card).{0,50}(?:fraud|abuse)",
            evidence_text,
            re.IGNORECASE,
        )
    )
    exposure = exposure_value if exposure_value is not None else 0.0
    for part in ("initial", "final"):
        _validate_actions(
            nba.get(part, []),
            problems,
            label=f"next_best_actions.{part}",
            exposure=exposure,
            verdict=str(verdict),
            pattern=str(case.get("pattern")),
            evidence_text=evidence_text,
            has_request=has_request,
            explicit_denial=explicit_denial,
            connected_fraud=connected_fraud,
        )
    initial_actions = nba.get("initial", []) if isinstance(nba.get("initial", []), list) else []
    final_actions = nba.get("final", []) if isinstance(nba.get("final", []), list) else []
    changed = tuple(
        _action_key(action) for action in initial_actions if isinstance(action, Mapping)
    ) != tuple(_action_key(action) for action in final_actions if isinstance(action, Mapping))
    what = nba.get("what_changed")
    if not isinstance(what, str):
        problems.append("what_changed must be a string")
    elif changed and what == "nothing":
        problems.append("actions changed but what_changed is nothing")
    elif not changed and what != "nothing":
        problems.append("actions are unchanged but what_changed is not nothing")
    if not isinstance(answer.get("stop_reason"), str) or not answer.get("stop_reason", "").strip():
        problems.append("stop_reason must be a non-empty string")
    if (
        not isinstance(answer.get("tokens"), int)
        or isinstance(answer.get("tokens"), bool)
        or answer.get("tokens", -1) < 0
    ):
        problems.append("tokens must be a non-negative integer")
    if not _is_number(answer.get("latency_s")) or float(answer.get("latency_s", -1)) < 0:
        problems.append("latency_s must be a non-negative number")

    sar = answer.get("sar")
    _validate_sar(
        sar,
        problems,
        context,
        case=case,
        affected=affected,
        exposure=exposure,
        has_request=has_request,
        explicit_denial=explicit_denial,
        connected_fraud=connected_fraud,
    )
    if isinstance(sar, Mapping) and isinstance(nba.get("final"), list):
        has_file = any(a.get("action") == "FILE_REPORT" for a in nba["final"] if isinstance(a, Mapping))
        if bool(sar.get("file")) != has_file:
            problems.append("sar.file must agree with FILE_REPORT in final actions")
    return problems


def validate_files(
    case_rows: Iterable[Mapping[str, Any]],
    answers_dir: Path = CASES_DIR,
    context: ValidationContext | None = None,
    *,
    expected_tool_calls: Mapping[str, int] | None = None,
) -> dict[str, list[str]]:
    context = context or ValidationContext.from_repo()
    result: dict[str, list[str]] = {}
    for raw_case in case_rows:
        case = dict(raw_case)
        case_id = str(case["case_id"])
        path = answers_dir / f"{case_id}.json"
        if not path.exists():
            result[case_id] = ["FILE MISSING"]
            continue
        try:
            answer = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            result[case_id] = [f"invalid JSON: {exc}"]
            continue
        result[case_id] = validate_answer(
            answer,
            case,
            context,
            expected_tool_calls=(expected_tool_calls or {}).get(case_id),
        )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate FraudLens answers semantically")
    parser.add_argument("--cases-dir", type=Path, default=CASES_DIR)
    parser.add_argument("--data-dir", type=Path, default=DATA)
    parser.add_argument(
        "--check-graph",
        action="store_true",
        help="reserved for an explicitly injected graph checker; local validation never connects",
    )
    args = parser.parse_args(argv)
    pack = args.data_dir / "case_pack.csv"
    if not pack.exists():
        print(f"Missing case pack: {pack}", file=sys.stderr)
        return 2
    with pack.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    context = ValidationContext.from_repo(HERE, args.data_dir)
    findings = validate_files(rows, args.cases_dir, context)
    problems = [(case_id, problem) for case_id, items in findings.items() for problem in items]
    if args.check_graph:
        print(
            "Graph checks are not run by the local validator; provide graph_case_ids/callback in the API for an integration check."
        )
    if problems:
        print(f"{len(problems)} PROBLEMS:")
        for case_id, problem in problems:
            print(f" - {case_id}: {problem}")
        return 1
    print(f"ALL {len(rows)} ANSWERS SEMANTICALLY VALID")
    return 0


__all__ = [
    "ACTIONS",
    "ANSWER_SCHEMA_PATH",
    "CASE_FIELDS",
    "EVIDENCE_FIELDS",
    "PATTERN_ENUM",
    "REQUEST_FIELDS",
    "SAR_FIELDS",
    "TOP_FIELDS",
    "ValidationContext",
    "schema_problems",
    "validate_answer",
    "validate_files",
]


if __name__ == "__main__":
    raise SystemExit(main())
