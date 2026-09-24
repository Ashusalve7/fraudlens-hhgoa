"""FraudLens analyst dashboard.

The application serves the built single-page application in ``dashboard/dist`` and
exposes a small, read-only API for the case queue and graph-backed investigation
context.  It does not write to the graph.

Run from the ``fraudlens/`` folder with::

    .venv/Scripts/python.exe -m uvicorn dashboard.app:app --port 8000

For a non-loopback deployment, set ``FRAUDLENS_API_TOKEN`` (or
``DASHBOARD_API_TOKEN``) to require a token on API requests.  Loopback requests
retain the local development workflow.
"""

from __future__ import annotations

import copy
import csv
import hashlib
import hmac
import ipaddress
import json
import logging
import math
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from threading import RLock
from typing import Annotated, Any
from urllib.parse import unquote

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
# Keep the existing import layout used by the local agent modules.  The imports
# are intentionally confined to this process; no code below writes to the graph.
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agent"))
sys.path.insert(0, str(ROOT / "pipeline"))

from evidence import Evidence  # noqa: E402

logger = logging.getLogger("fraudlens.dashboard")

CASES_DIR = (ROOT / "cases").resolve()
CASE_PACK_PATH = (ROOT.parent / "HHGOA_IEEE" / "case_pack.csv").resolve()
MODEL_PATH = (ROOT / "eval" / "out" / "model.json").resolve()
DIST_DIR = (HERE / "dist").resolve()
DIST_INDEX = DIST_DIR / "index.html"
DIST_ASSETS = DIST_DIR / "assets"

# Case identifiers are part of the public API.  Do not rely on a path sanitizer
# here: accepting anything other than this exact format makes filesystem access
# ambiguous and makes URL-encoded traversal attempts needlessly difficult to audit.
CASE_ID_RE = re.compile(r"^HHG-[0-9]{3}$")

# These are read-only expectations used by the health check.  They mirror the
# relationships required by the dashboard's evidence and case-memory views.
CORE_EDGE_TYPES = (
    "OWNS_CARD",
    "PAID_WITH",
    "FROM_DEVICE",
    "P_EMAIL",
    "R_EMAIL",
    "BILLED_IN",
    "NEXT_TXN",
    "CASE_TXN",
    "CASE_CARD",
    "CASE_CONN_CARD",
    "CASE_DEVICE",
    "AG_TXN",
    "AG_CARD",
    "AG_DEVICE",
    "AG_SIMILAR",
)
VERTEX_TYPES = (
    "Transaction",
    "Customer",
    "Card",
    "DeviceProfile",
    "EmailDomain",
    "BillingRegion",
    "ClosedCase",
    "AgentCase",
)

# A request should not be able to turn a dashboard interaction into an
# unbounded graph traversal.  The upper bound is deliberately finite even if a
# caller supplies a very large integer.
MIN_GRAPH_WINDOW_DAYS = 1
MAX_GRAPH_WINDOW_DAYS = 365
MAX_TXN_ID_LENGTH = 128

FEATURE_LABELS = {
    "flagged_amount": "Flagged transaction amount",
    "flagged_online": "Online (card-not-present) channel",
    "flagged_risk": "Bank model risk score",
    "n_small_auth_1h": "Small authorizations in prior hour",
    "amt_ratio_30d": "Amount vs 30-day baseline",
    "product_new": "Never-used product code",
    "new_dev_share_24h": "New-device share of 24h window",
    "proxy_share_24h": "Proxy/anonymizer share of 24h window",
    "device_shared_cards_7d": "Other cards on same device (7d)",
    "region_new": "Billing region unseen before",
    "region_new_n_72h": "Txns in this region (72h)",
    "home_active_72h": "Home-region activity continued",
    "online_share_shift": "Channel-mix shift (24h vs 30d)",
    "pemail_changed": "Purchaser email changed",
    "m1_not_T": "Cardholder match flag anomalous",
    "n_txn_24h": "Transactions in +/-24h window",
}


def _env_float(*names: str, default: float, maximum: float = 3600.0) -> float:
    """Read a bounded numeric environment setting without failing app startup."""
    for name in names:
        raw = os.getenv(name)
        if raw is None or not str(raw).strip():
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            logger.warning("Ignoring invalid dashboard setting %s", name)
            continue
        if not math.isfinite(value):
            logger.warning("Ignoring invalid dashboard setting %s", name)
            continue
        if value < 0:
            return 0.0
        return min(value, maximum)
    return default


CACHE_VERSION = "1"


def _cache_version() -> str:
    """Return an operator-controlled version component for all in-memory caches."""
    for name in (
        "FRAUDLENS_CACHE_VERSION",
        "DASHBOARD_CACHE_VERSION",
        "API_CACHE_VERSION",
        "CACHE_VERSION",
    ):
        value = os.getenv(name)
        if value is not None and str(value).strip():
            return str(value).strip()[:128]
    return CACHE_VERSION


GRAPH_STATS_CACHE_TTL = _env_float(
    "FRAUDLENS_GRAPH_STATS_TTL_SECONDS",
    "FRAUDLENS_CACHE_TTL_SECONDS",
    "CACHE_TTL_SECONDS",
    default=15.0,
)
EXPLANATION_CACHE_TTL = _env_float(
    "FRAUDLENS_EXPLANATION_CACHE_TTL_SECONDS",
    "FRAUDLENS_CACHE_TTL_SECONDS",
    "CACHE_TTL_SECONDS",
    default=300.0,
)


class _TTLCache:
    """Small thread-safe, bounded, copy-on-read/write cache.

    FastAPI runs synchronous route functions in a worker pool, so a plain dict
    would otherwise allow concurrent callers to observe partially shared response
    objects or grow without bound.  ``version`` belongs in the caller's key; it
    is intentionally not inferred from graph contents here.
    """

    def __init__(self, *, ttl_seconds: float, max_entries: int) -> None:
        self.ttl_seconds = max(0.0, float(ttl_seconds))
        self.max_entries = max(1, int(max_entries))
        self._values: dict[Any, tuple[float, Any]] = {}
        self._lock = RLock()

    def get(self, key: Any) -> Any | None:
        if self.ttl_seconds <= 0:
            return None
        now = time.monotonic()
        with self._lock:
            item = self._values.get(key)
            if item is None:
                return None
            expires_at, value = item
            if expires_at <= now:
                self._values.pop(key, None)
                return None
            return copy.deepcopy(value)

    def set(self, key: Any, value: Any) -> None:
        if self.ttl_seconds <= 0:
            return
        with self._lock:
            now = time.monotonic()
            expired = [k for k, (expires_at, _v) in self._values.items() if expires_at <= now]
            for expired_key in expired:
                self._values.pop(expired_key, None)
            if key in self._values:
                self._values.pop(key, None)
            elif len(self._values) >= self.max_entries:
                oldest = min(self._values, key=lambda k: self._values[k][0])
                self._values.pop(oldest, None)
            self._values[key] = (now + self.ttl_seconds, copy.deepcopy(value))

    def clear(self) -> None:
        with self._lock:
            self._values.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._values)


_graph_stats_cache = _TTLCache(ttl_seconds=GRAPH_STATS_CACHE_TTL, max_entries=4)
_explain_cache = _TTLCache(ttl_seconds=EXPLANATION_CACHE_TTL, max_entries=64)
_case_pack_cache = _TTLCache(ttl_seconds=EXPLANATION_CACHE_TTL, max_entries=4)
_stats_lock = RLock()
_explain_locks_guard = RLock()
_explain_locks: dict[Any, RLock] = {}
_ev_lock = RLock()
_ev: Evidence | None = None


class CaseSummary(BaseModel):
    case_id: str
    verdict: str
    status: str
    pattern: str
    fraud_probability: float
    exposure_usd: float
    sar: Any
    affected_count: int
    tool_calls: int
    latency_s: float
    states: list[str] = Field(default_factory=list)


class GraphStatsResponse(BaseModel):
    graph: str
    counts: dict[str, int | None]
    status: str = "ok"
    available: bool = True


class GraphRingResponse(BaseModel):
    txn_id: str
    device: dict[str, Any]
    cards: list[str]
    n_txns: int
    prior_cases: list[str]
    sample: list[dict[str, Any]]


class Contribution(BaseModel):
    feature: str
    label: str
    value: float
    contribution: float
    toward: str


class ExplanationResponse(BaseModel):
    model: dict[str, Any]
    probability: float
    pattern: str
    contributions: list[Contribution]
    n_evidence: int
    similar_prior_cases: list[str]
    graph: dict[str, Any]
    device_cards: int


class CoreEdgeHealth(BaseModel):
    expected: list[str]
    present: list[str]
    missing: list[str]
    checked: bool


class GraphHealth(BaseModel):
    name: str
    connected: bool
    core_edges: CoreEdgeHealth


class HealthResponse(BaseModel):
    status: str
    ready: bool
    service: str
    graph: GraphHealth
    # Keep the explicit expectation visible at the top level for probes that
    # do not want to know the nested response shape.
    core_edge_expectations: list[str]


app = FastAPI(
    title="FraudLens",
    description="FraudLens investigation dashboard API and production single-page application.",
    version="1.0.0",
)

# The Vite build emits absolute /assets URLs.  StaticFiles supplies the correct
# content types and its own path containment checks for those files.
app.mount("/assets", StaticFiles(directory=str(DIST_ASSETS), check_dir=False), name="assets")


@app.middleware("http")
async def dashboard_security_headers(request: Request, call_next):
    """Apply lightweight browser headers and optional non-loopback API auth.

    A token is opt-in.  When configured, requests originating from a loopback
    address retain the local development workflow; requests from other addresses
    must present it in a standard API-token header or as a Bearer token.  Proxy
    forwarding headers are intentionally not trusted by default.
    """
    path = unquote(request.url.path)
    if path == "/api" or path.startswith("/api/"):
        expected = _configured_api_token()
        if expected and not _is_loopback_client(request) and not _has_valid_token(request, expected):
            response = JSONResponse(
                status_code=401,
                content={"detail": "authentication required"},
                headers={"WWW-Authenticate": "Bearer"},
            )
            _set_response_headers(response, path)
            return response

    response = await call_next(request)
    _set_response_headers(response, path)
    return response


@app.exception_handler(Exception)
async def unhandled_dashboard_error(request: Request, exc: Exception):
    """Never serialize an unexpected backend exception to a client."""
    logger.error("Unhandled dashboard error (%s)", type(exc).__name__)
    return JSONResponse(status_code=500, content={"detail": "internal server error"})


def _set_response_headers(response, path: str) -> None:
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("X-Frame-Options", "DENY")
    if path == "/api" or path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-store")
    elif path.startswith("/assets/"):
        response.headers.setdefault("Cache-Control", "public, max-age=31536000, immutable")
    else:
        response.headers.setdefault("Cache-Control", "no-cache")


def _configured_api_token() -> str | None:
    for name in (
        "FRAUDLENS_API_TOKEN",
        "DASHBOARD_API_TOKEN",
        "API_TOKEN",
        "FRAUDLENS_DASHBOARD_TOKEN",
        "FRAUDLENS_DASHBOARD_API_TOKEN",
        "DASHBOARD_TOKEN",
    ):
        value = os.getenv(name)
        if value is not None and value.strip():
            return value.strip()
    return None


def _is_loopback_client(request: Request) -> bool:
    client = request.client
    host = client.host if client is not None else ""
    if not host:
        return False
    host = str(host).strip().strip("[]")
    if host.lower() == "localhost":
        return True
    try:
        address = ipaddress.ip_address(host.split("%", 1)[0])
        if address.is_loopback:
            return True
        mapped = getattr(address, "ipv4_mapped", None)
        return bool(mapped is not None and mapped.is_loopback)
    except ValueError:
        return False


def _has_valid_token(request: Request, expected: str) -> bool:
    supplied = (
        request.headers.get("X-API-Key")
        or request.headers.get("X-API-Token")
        or request.headers.get("X-Access-Token")
        or request.headers.get("X-FraudLens-Token")
    )
    if not supplied:
        authorization = request.headers.get("Authorization", "")
        scheme, _, value = authorization.partition(" ")
        if scheme.lower() == "bearer":
            supplied = value.strip()
    if not supplied:
        return False
    return hmac.compare_digest(str(supplied), str(expected))


def _graph_name() -> str:
    value = str(os.getenv("TG_GRAPHNAME") or "FraudGraph").strip()
    return value[:128] or "FraudGraph"


def ev() -> Evidence:
    """Return the shared evidence adapter, creating it at most once."""
    global _ev
    if _ev is None:
        with _ev_lock:
            if _ev is None:
                _ev = Evidence()
    return _ev


def _safe_case_path(case_id: str) -> Path:
    """Validate a case ID and resolve it beneath the configured cases directory."""
    if not isinstance(case_id, str) or CASE_ID_RE.fullmatch(case_id) is None:
        raise HTTPException(status_code=404, detail="case not found")

    root = CASES_DIR.resolve()
    candidate = (root / f"{case_id}.json").resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        # This also catches a symlink whose resolved target leaves CASES_DIR.
        raise HTTPException(status_code=404, detail="case not found") from None
    return candidate


def _read_case(case_id: str, path: Path | None = None) -> dict[str, Any]:
    case_path = path or _safe_case_path(case_id)
    try:
        with case_path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="case not found") from None
    except (OSError, UnicodeError, json.JSONDecodeError):
        logger.error("Case data could not be read (%s)", case_id)
        raise HTTPException(status_code=500, detail="case data unavailable") from None

    if not isinstance(data, dict) or data.get("case_id") != case_id:
        logger.error("Case data failed identity validation (%s)", case_id)
        raise HTTPException(status_code=500, detail="case data unavailable")
    return data


def _file_fingerprint(path: Path) -> str:
    """Return a content version for files that influence cached explanations."""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return "missing"


def _case_pack() -> dict[str, dict[str, str]]:
    """Load the static trigger pack without allowing its absence to expose paths."""
    fingerprint = _file_fingerprint(CASE_PACK_PATH)
    key = ("case-pack", _cache_version(), fingerprint)
    cached = _case_pack_cache.get(key)
    if cached is not None:
        return cached

    rows: dict[str, dict[str, str]] = {}
    try:
        with CASE_PACK_PATH.open("r", newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                case_id = str(row.get("case_id") or "")
                if CASE_ID_RE.fullmatch(case_id):
                    rows[case_id] = row
    except (OSError, UnicodeError, csv.Error, KeyError):
        logger.error("Case trigger pack is unavailable")
        return {}

    _case_pack_cache.set(key, rows)
    return rows


def _case_summary(data: dict[str, Any]) -> dict[str, Any]:
    case = data["case"]
    sar = data["sar"]
    return {
        "case_id": data["case_id"],
        "verdict": case["verdict"],
        "status": case["status"],
        "pattern": case["pattern"],
        "fraud_probability": case["fraud_probability"],
        "exposure_usd": case["exposure_usd"],
        "sar": sar["file"],
        "affected_count": len(case.get("affected_txn_ids") or []),
        "tool_calls": data.get("tool_calls", 0),
        "latency_s": data.get("latency_s", 0),
        "states": data.get("_states") or [],
    }


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    """Serve the current production build, not the Vite development shell."""
    return _spa_response()


@app.get("/api/cases", response_model=list[CaseSummary], tags=["cases"], summary="List investigation cases")
def cases() -> list[dict[str, Any]]:
    """Return the local case queue without contacting the graph."""
    summaries: list[dict[str, Any]] = []
    try:
        files = sorted(CASES_DIR.glob("HHG-*.json"))
    except OSError:
        return summaries

    for file_path in files:
        if CASE_ID_RE.fullmatch(file_path.stem) is None:
            continue
        try:
            path = _safe_case_path(file_path.stem)
            if not path.is_file():
                continue
            data = _read_case(file_path.stem, path)
            summaries.append(_case_summary(data))
        except HTTPException:
            # A malformed or escaping file must not make the queue disclose it
            # or prevent other valid cases from being shown.
            continue
        except (KeyError, TypeError, ValueError):
            logger.error("Case summary is malformed (%s)", file_path.stem)
            continue
    return summaries


@app.get(
    "/api/cases/{case_id}",
    response_model=dict[str, Any],
    tags=["cases"],
    summary="Get an investigation case",
)
def case_detail(case_id: str) -> dict[str, Any]:
    """Return one case answer and, when available, its local trigger metadata."""
    data = _read_case(case_id)
    case_id_from_pack = _case_pack().get(case_id)
    if case_id_from_pack:
        # Keep the historical response fields and their names for frontend/API
        # compatibility.  Missing optional CSV metadata is not fatal.
        for field in (
            "trigger_type",
            "trigger_text",
            "opened_at",
            "flagged_txn_id",
            "card_id",
            "customer_id",
        ):
            if field in case_id_from_pack:
                data[field] = case_id_from_pack[field]
    return data


def _spa_response() -> FileResponse:
    if not DIST_INDEX.is_file():
        logger.error("Dashboard production build is unavailable")
        raise HTTPException(status_code=503, detail="dashboard build unavailable")
    return FileResponse(
        DIST_INDEX,
        media_type="text/html",
        headers={"Cache-Control": "no-cache"},
    )


@app.get(
    "/api/graph/stats",
    response_model=GraphStatsResponse,
    tags=["graph"],
    summary="Get graph summary counts",
)
def graph_stats() -> GraphStatsResponse | JSONResponse:
    """Return bounded, cached vertex counts for the configured graph."""
    graph = _graph_name()
    try:
        # Resolve the shared connection before looking up the cache so a
        # replaced/test connection cannot receive another connection's counts.
        conn = ev().conn
    except Exception as exc:
        _log_graph_failure("connect", exc)
        return _graph_unavailable_response(graph)

    key = ("graph-stats", _cache_version(), graph, id(conn))
    with _stats_lock:
        cached = _graph_stats_cache.get(key)
        if cached is not None:
            return GraphStatsResponse.model_validate(cached)

        counts: dict[str, int | None] = {}
        failures = 0

        def count_one(vertex_type: str) -> tuple[str, int | None]:
            try:
                value = conn.getVertexCount(vertex_type)
                return vertex_type, _coerce_count(value)
            except Exception as exc:  # workspace asleep, permissions, or network failure
                _log_graph_failure("count", exc)
                return vertex_type, None

        # Counts do not depend on one another; use a small fixed-size pool rather
        # than serializing the round trips.
        with ThreadPoolExecutor(
            max_workers=min(8, len(VERTEX_TYPES)), thread_name_prefix="fraudlens-count"
        ) as pool:
            results = list(pool.map(count_one, VERTEX_TYPES))
        for vertex_type, value in results:
            counts[vertex_type] = value
            if value is None:
                failures += 1

        payload: dict[str, Any] = {
            "graph": graph,
            "counts": counts,
            "status": "ok"
            if failures == 0
            else ("unavailable" if failures == len(VERTEX_TYPES) else "degraded"),
            "available": failures == 0,
        }
        if failures:
            if failures == len(VERTEX_TYPES):
                return _graph_unavailable_response(graph, counts)
            # Do not cache a partial result: a sleeping workspace can recover on
            # the next request without waiting for the TTL.
            return JSONResponse(status_code=200, content=payload)

        _graph_stats_cache.set(key, payload)
        return GraphStatsResponse.model_validate(payload)


def _coerce_count(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError("boolean is not a count")
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        if value < 0 or not value.is_integer():
            raise ValueError("invalid count")
        return int(value)
    if isinstance(value, str):
        parsed = int(value.strip())
        if parsed < 0:
            raise ValueError("invalid count")
        return parsed
    if isinstance(value, dict):
        for key in ("count", "COUNT", "value"):
            if key in value:
                return _coerce_count(value[key])
    raise ValueError("invalid count")


def _log_graph_failure(operation: str, exc: Exception) -> None:
    # Log only the operation and exception class.  Provider messages can contain
    # hostnames, request details, or other graph-internal information.
    logger.warning("Graph %s unavailable (%s)", operation, type(exc).__name__)


def _graph_unavailable_response(graph: str, counts: dict[str, int | None] | None = None) -> JSONResponse:
    payload: dict[str, Any] = {
        "detail": "graph service is temporarily unavailable",
        "graph": graph,
        "status": "unavailable",
        "available": False,
    }
    if counts is not None:
        payload["counts"] = counts
    return JSONResponse(status_code=503, content=payload)


def _parse_graph_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    text = str(value)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text)


def _validate_window_days(value: int) -> int:
    try:
        window_days = int(value)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="window_days is out of range") from None
    if isinstance(value, bool) or not (MIN_GRAPH_WINDOW_DAYS <= window_days <= MAX_GRAPH_WINDOW_DAYS):
        raise HTTPException(status_code=422, detail="window_days is out of range")
    return window_days


def _validate_txn_id(txn_id: str) -> str:
    if not isinstance(txn_id, str) or not txn_id or len(txn_id) > MAX_TXN_ID_LENGTH or "\x00" in txn_id:
        raise HTTPException(status_code=404, detail="txn or device not found")
    return txn_id


@app.get(
    "/api/graph/ring/{txn_id}",
    response_model=GraphRingResponse,
    tags=["graph"],
    summary="Get a device-neighborhood traversal",
)
def graph_ring(
    txn_id: str,
    window_days: Annotated[int, Query(ge=MIN_GRAPH_WINDOW_DAYS, le=MAX_GRAPH_WINDOW_DAYS)] = 45,
) -> GraphRingResponse | JSONResponse:
    """Return a bounded two-hop device-neighborhood result for a transaction."""
    txn_id = _validate_txn_id(txn_id)
    window_days = _validate_window_days(window_days)
    try:
        evidence = ev()
        context = evidence.txn_context(txn_id)
        txn = (context or {}).get("txn") if isinstance(context, dict) else None
        device = (context or {}).get("device") if isinstance(context, dict) else None
        if not isinstance(txn, dict) or not isinstance(device, dict) or not device:
            # A missing entity is a normal 404.  Keep it distinct from provider
            # failures, which are handled by the generic exception path below.
            context = None
        else:
            t0 = _parse_graph_datetime(txn.get("ts"))
            start = (t0 - timedelta(days=window_days)).strftime("%Y-%m-%d %H:%M:%S")
            end = (t0 + timedelta(days=window_days)).strftime("%Y-%m-%d %H:%M:%S")
            neighborhood = evidence.device_neighborhood(device["device_id"], start, end)
    except Exception as exc:
        _log_graph_failure("traversal", exc)
        return _graph_unavailable_response(_graph_name())

    if context is None:
        raise HTTPException(status_code=404, detail="txn or device not found")
    if not isinstance(neighborhood, dict):
        _log_graph_failure("traversal", TypeError("invalid result"))
        return _graph_unavailable_response(_graph_name())

    cards = [
        str(row.get("card_id"))
        for row in (neighborhood.get("cards") or [])
        if isinstance(row, dict) and row.get("card_id") is not None
    ]
    txns = [row for row in (neighborhood.get("txns") or []) if isinstance(row, dict)]
    prior_cases = [
        str(row.get("case_id"))
        for row in (neighborhood.get("prior_cases") or [])
        if isinstance(row, dict) and row.get("case_id") is not None
    ]
    sample = [
        {
            "txn_id": row.get("txn_id"),
            "ts": row.get("ts"),
            "amount": row.get("amount"),
            "id_15": row.get("id_15"),
            "id_23": row.get("id_23"),
        }
        for row in txns[:8]
    ]
    return GraphRingResponse(
        txn_id=txn_id,
        device=device,
        cards=cards,
        n_txns=len(txns),
        prior_cases=prior_cases,
        sample=sample,
    )


def _lock_for_explanation(key: Any) -> RLock:
    with _explain_locks_guard:
        return _explain_locks.setdefault(key, RLock())


def _build_explanation(case_id: str, answer: dict[str, Any], case: dict[str, str]) -> dict[str, Any]:
    """Build an explanation after the case has been validated and cache-locked."""
    from decision import EXAM_PRIOR, TEMP, detect_pattern
    from features import compute_features, episode_features

    flagged_txn_id = str(case.get("flagged_txn_id") or "").strip()
    card_id = str(case.get("card_id") or "").strip()
    customer_id = str(case.get("customer_id") or "").strip()
    if not flagged_txn_id or not card_id or not customer_id:
        raise ValueError("incomplete case trigger metadata")

    evidence = ev()
    context = evidence.txn_context(flagged_txn_id)
    if not isinstance(context, dict) or not isinstance(context.get("txn"), dict):
        raise ValueError("transaction context is unavailable")
    t0 = _parse_graph_datetime(context["txn"].get("ts"))
    card_rows = evidence.card_window(
        card_id,
        (t0 - timedelta(days=60)).strftime("%Y-%m-%d %H:%M:%S"),
        (t0 + timedelta(hours=72)).strftime("%Y-%m-%d %H:%M:%S"),
    )
    device = context.get("device")
    device_neighborhood = None
    if isinstance(device, dict) and device.get("device_id"):
        device_neighborhood = evidence.device_neighborhood(
            str(device["device_id"]),
            (t0 - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S"),
            (t0 + timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S"),
        )

    features = compute_features(context, card_rows or [], device_neighborhood)
    episode_rows = [
        row
        for row in (card_rows or [])
        if isinstance(row, dict) and _safe_row_in_window(row.get("ts"), t0, hours=24)
    ]
    episode = episode_features(episode_rows, card_rows or [], t0)
    pattern, _pattern_reason = detect_pattern(features, episode)
    model = json.loads(MODEL_PATH.read_text(encoding="utf-8"))

    model_features = model.get("features") or []
    means = model.get("scaler_mean") or []
    scales = model.get("scaler_scale") or []
    coefficients = model.get("coef") or []
    if not (len(model_features) == len(means) == len(scales) == len(coefficients)):
        raise ValueError("model metadata is inconsistent")

    contributions: list[dict[str, Any]] = []
    for feature, mean, scale, coefficient in zip(model_features, means, scales, coefficients, strict=True):
        value = float(features[feature])
        scale_value = float(scale)
        if scale_value == 0:
            raise ValueError("model scale is zero")
        contribution = (value - float(mean)) / scale_value * float(coefficient)
        contributions.append(
            {
                "feature": str(feature),
                "label": FEATURE_LABELS.get(str(feature), str(feature)),
                "value": round(value, 3),
                "contribution": round(contribution, 2),
                "toward": "fraud" if contribution > 0 else "legitimate",
            }
        )
    contributions.sort(key=lambda item: -abs(float(item["contribution"])))

    answer_case = answer.get("case")
    if not isinstance(answer_case, dict):
        raise ValueError("case answer is incomplete")
    amount = float(context["txn"].get("amount") or 0)
    customer_node = {"id": customer_id, "type": "customer", "label": customer_id[:128]}
    card_node = {"id": card_id, "type": "card", "label": card_id[:128]}
    txn_node = {"id": flagged_txn_id, "type": "transaction", "label": f"${amount:,.2f}"}
    nodes: list[dict[str, Any]] = [customer_node, card_node, txn_node]
    edges: list[dict[str, str]] = [
        {"from": customer_id, "to": card_id, "label": "owns"},
        {"from": card_id, "to": flagged_txn_id, "label": "made"},
    ]

    if isinstance(device, dict) and device.get("device_id"):
        device_id = str(device["device_id"])
        nodes.append(
            {
                "id": device_id,
                "type": "device",
                "label": str(device.get("device_info") or "device")[:26],
            }
        )
        edges.append({"from": flagged_txn_id, "to": device_id, "label": "from device"})
        for connected in (device_neighborhood or {}).get("cards", [])[:4]:
            if not isinstance(connected, dict) or not connected.get("card_id"):
                continue
            connected_id = str(connected["card_id"])
            if connected_id == card_id:
                continue
            nodes.append({"id": connected_id, "type": "connected_card", "label": connected_id[:128]})
            edges.append({"from": device_id, "to": connected_id, "label": "also used by"})

    region = str(context["txn"].get("addr1") or "")
    if region and region != "_NA_":
        region_id = f"R-{region}"[:128]
        nodes.append({"id": region_id, "type": "region", "label": f"Region {region}"[:128]})
        edges.append({"from": flagged_txn_id, "to": region_id, "label": "billed in"})

    similar = [
        str(value)
        for value in (answer_case.get("similar_prior_cases") or [])
        if isinstance(value, (str, int))
    ]
    for prior_case in similar[:3]:
        nodes.append({"id": prior_case, "type": "prior_case", "label": prior_case[:128]})
        edges.append({"from": case_id, "to": prior_case, "label": "similar to"})

    return {
        "model": {
            "trained_on": "labeled closed-case history",
            "holdout_auc": round(float(model.get("holdout_auc") or 0), 3),
            "exam_prior": float(EXAM_PRIOR),
            "temperature": float(TEMP),
        },
        "probability": answer_case["fraud_probability"],
        "pattern": answer_case["pattern"],
        "contributions": contributions,
        "n_evidence": len(answer_case.get("evidence") or []),
        "similar_prior_cases": similar,
        "graph": {"nodes": nodes, "edges": edges},
        "device_cards": len((device_neighborhood or {}).get("cards") or []) if device_neighborhood else 0,
    }


def _safe_row_in_window(value: Any, center: datetime, *, hours: int) -> bool:
    try:
        row_time = _parse_graph_datetime(value)
        return center - timedelta(hours=hours) <= row_time <= center + timedelta(hours=hours)
    except (TypeError, ValueError, OverflowError):
        return False


@app.get(
    "/api/explain/{case_id}",
    response_model=ExplanationResponse,
    tags=["cases"],
    summary="Explain a case score",
)
def explain(case_id: str) -> ExplanationResponse | JSONResponse:
    """Return a versioned, expiring feature-contribution explanation."""
    case_path = _safe_case_path(case_id)
    key = (
        "explain",
        case_id,
        _cache_version(),
        _graph_name(),
        _file_fingerprint(case_path),
        _file_fingerprint(CASE_PACK_PATH),
        _file_fingerprint(MODEL_PATH),
    )
    with _lock_for_explanation(key):
        cached = _explain_cache.get(key)
        if cached is not None:
            return ExplanationResponse.model_validate(cached)

        pack = _case_pack()
        case = pack.get(case_id)
        if case is None:
            raise HTTPException(status_code=404, detail="case not in pack")
        answer = _read_case(case_id, case_path)
        try:
            output = _build_explanation(case_id, answer, case)
            validated = ExplanationResponse.model_validate(output)
            _explain_cache.set(key, output)
            return validated
        except Exception as exc:
            # Includes an asleep workspace, provider/network errors, and malformed
            # graph rows.  Keep the response stable and provider-neutral.
            _log_graph_failure("explanation", exc)
            return _graph_unavailable_response(_graph_name())


def _edge_names(value: Any) -> set[str]:
    """Normalize the small number of schema shapes returned by TG clients."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return {value}
    if isinstance(value, dict):
        for key in ("EdgeTypes", "edge_types", "edges", "edgeTypes"):
            if key in value:
                return _edge_names(value[key])
        names: set[str] = set()
        for key, item in value.items():
            if isinstance(key, str) and isinstance(item, (dict, list, str)):
                names.update(_edge_names(item))
        return names
    if isinstance(value, (list, tuple, set)):
        names: set[str] = set()
        for item in value:
            if isinstance(item, str):
                names.add(item)
            elif isinstance(item, dict):
                candidate = item.get("Name") or item.get("name") or item.get("edge_type")
                if isinstance(candidate, str):
                    names.add(candidate)
        return names
    return set()


def _read_edge_expectations(conn: Any) -> tuple[set[str] | None, bool]:
    """Return discovered edge names and whether the schema probe failed.

    A connection object without the optional schema method is an unknown/degraded
    capability; an exception from a present method means the graph could not be
    inspected and should be reported as unavailable.
    """
    getter = getattr(conn, "getEdgeTypes", None)
    if not callable(getter):
        return None, False
    try:
        try:
            return _edge_names(getter(force=True)), False
        except TypeError:
            return _edge_names(getter()), False
    except Exception as exc:
        _log_graph_failure("schema", exc)
        return None, True


def _health_payload() -> HealthResponse:
    graph = _graph_name()
    expected = list(CORE_EDGE_TYPES)
    try:
        conn = ev().conn
    except Exception as exc:
        _log_graph_failure("health", exc)
        return HealthResponse(
            status="unavailable",
            ready=False,
            service="fraudlens-dashboard",
            graph=GraphHealth(
                name=graph,
                connected=False,
                core_edges=CoreEdgeHealth(expected=expected, present=[], missing=expected, checked=False),
            ),
            core_edge_expectations=expected,
        )

    present_set, schema_probe_failed = _read_edge_expectations(conn)
    if present_set is None:
        return HealthResponse(
            status="unavailable" if schema_probe_failed else "degraded",
            ready=False,
            service="fraudlens-dashboard",
            graph=GraphHealth(
                name=graph,
                connected=not schema_probe_failed,
                core_edges=CoreEdgeHealth(
                    expected=expected,
                    present=[],
                    missing=expected if schema_probe_failed else [],
                    checked=False,
                ),
            ),
            core_edge_expectations=expected,
        )

    present = sorted(present_set.intersection(expected))
    missing = [edge for edge in expected if edge not in present_set]
    return HealthResponse(
        status="ok" if not missing else "degraded",
        ready=not missing,
        service="fraudlens-dashboard",
        graph=GraphHealth(
            name=graph,
            connected=True,
            core_edges=CoreEdgeHealth(expected=expected, present=present, missing=missing, checked=True),
        ),
        core_edge_expectations=expected,
    )


@app.get(
    "/health", response_model=HealthResponse, tags=["system"], summary="Check dashboard and graph readiness"
)
def health() -> HealthResponse:
    """Report readiness without returning graph-provider diagnostics."""
    return _health_payload()


@app.get(
    "/api/health",
    response_model=HealthResponse,
    tags=["system"],
    summary="Check dashboard and graph readiness",
    include_in_schema=False,
)
def api_health() -> HealthResponse:
    """API-prefixed health alias for deployments that group API routes."""
    return _health_payload()


# The final route is deliberately a history fallback.  API paths are excluded so
# a typo such as /api/unknown cannot be mistaken for a client-side SPA route.
@app.api_route(
    "/{full_path:path}",
    methods=["GET", "HEAD"],
    include_in_schema=False,
)
def spa_history_fallback(full_path: str) -> FileResponse:
    decoded_path = unquote(full_path).lstrip("/")
    if decoded_path == "api" or decoded_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="not found")
    return _spa_response()
