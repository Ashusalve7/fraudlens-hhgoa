"""Resumable, verifiable TigerGraph loader for FraudLens.

Vertices and edges are upserted in the order declared by ``load_contract``.
Each parquet chunk has its own checkpoint, so a transient REST failure does not
make later edge types disappear behind a fail-fast return.  A final health
report compares both expected vertices and expected edges with the graph.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import pandas as pd

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from load_contract import (  # noqa: E402
    EDGE_PLAN,
    HEALTH_PATH,
    PLAN,
    PLAN_BY_NAME,
    VERTEX_PLAN,
    atomic_write_json,
    graph_health_contract,
    inspect_sources,
    load_manifest,
    read_json,
    sha256_file,
    utc_now,
)
from tg import get_conn  # noqa: E402

LOG_PATH = HERE / "out" / "load_log.json"
COUNTS_PATH = HERE / "out" / "graph_counts.json"
CHUNK_DEFAULT = 10_000


def sanitize(frame: pd.DataFrame) -> pd.DataFrame:
    """Make parquet values safe for TigerGraph RESTPP upserts."""
    frame = frame.copy()
    for column in frame.columns:
        series = frame[column]
        if pd.api.types.is_datetime64_any_dtype(series):
            frame[column] = series.dt.strftime("%Y-%m-%d %H:%M:%S").fillna("1970-01-01 00:00:00")
        elif pd.api.types.is_bool_dtype(series):
            frame[column] = series.fillna(False).astype(bool)
        elif pd.api.types.is_integer_dtype(series):
            frame[column] = series.fillna(0).astype("int64")
        elif pd.api.types.is_float_dtype(series):
            frame[column] = series.fillna(0.0).astype("float64")
        elif pd.api.types.is_object_dtype(series) or pd.api.types.is_string_dtype(series):
            text = series.astype("string")
            invalid = text.isna() | text.isin(["", "nan", "None", "<NA>"])
            frame[column] = text.mask(invalid, "_NA_").astype(str)
    return frame


def _normalise_count(value: Any, expected_key: str) -> int | None:
    if isinstance(value, dict):
        if expected_key in value:
            return int(value[expected_key])
        # TigerGraph versions occasionally return a one-item map with a fully
        # qualified edge key.  Do not guess when there are multiple values.
        if len(value) == 1:
            return int(next(iter(value.values())))
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _count_vertex(conn: Any, vertex_type: str, retries: int = 3) -> int | None:
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            try:
                value = conn.getVertexCount(vertex_type, realtime=True)
            except TypeError:  # older pyTigerGraph
                value = conn.getVertexCount(vertex_type)
            return _normalise_count(value, vertex_type)
        except Exception as exc:  # pragma: no cover - remote-only path
            last_error = exc
            if attempt + 1 < retries:
                time.sleep(1.0 + attempt)
    if last_error:
        print(f"  count {vertex_type}: ERROR {str(last_error)[:160]}", flush=True)
    return None


def _count_edge(conn: Any, spec: Any, retries: int = 3) -> int | None:
    last_error: Exception | None = 0
    for attempt in range(retries):
        try:
            value = conn.getEdgeCount(spec.graph_type, spec.from_type, spec.to_type)
            return _normalise_count(value, spec.graph_type)
        except Exception as exc:  # pragma: no cover - remote-only path
            last_error = exc
            if attempt + 1 < retries:
                time.sleep(1.0 + attempt)
    if last_error:
        print(f"  count edge {spec.graph_type}: ERROR {str(last_error)[:160]}", flush=True)
    return None


def _manifest_fingerprint(name: str, path: Path) -> str:
    manifest = load_manifest()
    entry = manifest.get("source_inspection", {}).get("entries", {}).get(name)
    # Re-check inexpensive metadata; never trust a manifest for a replaced file.
    if entry and entry.get("sha256") and entry.get("size_bytes") == path.stat().st_size:
        return str(entry["sha256"])
    return sha256_file(path)


def _string_graph_ids(frame: pd.DataFrame, spec: Any) -> pd.DataFrame:
    """Normalize every primary/foreign key before the RESTPP upsert."""
    result = frame.copy()
    for column in spec.id_columns:
        values = result[column].astype("string")
        invalid = values.isna() | values.str.strip().isin({"", "nan", "None", "<NA>"})
        if invalid.any():
            raise RuntimeError(f"{column} contains null or empty graph IDs")
        result[column] = values.str.strip().astype(str)
    return result


def _load_one(conn: Any, spec: Any, frame: pd.DataFrame, fingerprint: str, log: dict[str, Any], run_id: str, chunk_size: int) -> tuple[bool, list[str]]:
    entity_log = log["entities"].setdefault(spec.name, {})
    if entity_log.get("source_sha256") != fingerprint:
        entity_log.clear()
        entity_log.update({
            "kind": spec.kind,
            "graph_type": spec.graph_type,
            "source_sha256": fingerprint,
            "rows": int(len(frame)),
            "chunk_size": int(chunk_size),
            "chunks": {},
            "done": False,
        })
    chunks = entity_log.setdefault("chunks", {})
    errors: list[str] = []
    normalized = _string_graph_ids(frame, spec)
    if normalized.empty:
        entity_log["done"] = True
        chunks["0"] = {"status": "done", "rows": 0, "source_sha256": fingerprint}
        atomic_write_json(LOG_PATH, log)
        return True, []
    total_chunks = max(1, (len(normalized) + chunk_size - 1) // chunk_size)
    for index, start in enumerate(range(0, len(normalized), chunk_size)):
        chunk = sanitize(normalized.iloc[start : start + chunk_size])
        checkpoint = chunks.setdefault(str(index), {"status": "pending", "attempts": 0})
        if checkpoint.get("status") == "done" and checkpoint.get("source_sha256") == fingerprint:
            continue
        checkpoint["status"] = "running"
        checkpoint["attempts"] = int(checkpoint.get("attempts", 0)) + 1
        checkpoint["source_sha256"] = fingerprint
        checkpoint["started_at"] = utc_now()
        try:
            if spec.kind == "v":
                accepted = conn.upsertVertexDataFrame(chunk, spec.graph_type, v_id=spec.id_columns[0])
            else:
                accepted = conn.upsertEdgeDataFrame(
                    chunk,
                    spec.from_type,
                    spec.graph_type,
                    spec.to_type,
                    from_id=spec.id_columns[0],
                    to_id=spec.id_columns[1],
                    attributes={column: column for column in spec.attributes},
                )
            if accepted is not None and int(accepted) != len(chunk):
                raise RuntimeError(f"accepted {accepted} of {len(chunk)} rows")
            checkpoint.update({"status": "done", "rows": int(len(chunk)), "finished_at": utc_now()})
            print(f"  {spec.name} chunk {index + 1}/{total_chunks} ({len(chunk):,} rows)", flush=True)
        except Exception as exc:  # continue to the next edge/chunk
            message = f"{type(exc).__name__}: {str(exc)[:500]}"
            checkpoint.update({"status": "failed", "error": message, "finished_at": utc_now()})
            errors.append(f"{spec.name}[chunk {index}]: {message}")
            print(f"  {spec.name} chunk {index + 1}/{total_chunks}: FAILED {message}", flush=True)
        atomic_write_json(LOG_PATH, log)

    entity_log["done"] = bool(chunks) and all(item.get("status") == "done" for item in chunks.values())
    entity_log["updated_at"] = utc_now()
    atomic_write_json(LOG_PATH, log)
    return entity_log["done"], errors


def _remote_counts(conn: Any) -> tuple[dict[str, int | None], dict[str, int | None], dict[str, Any]]:
    vertices: dict[str, int | None] = {}
    edges: dict[str, int | None] = {}
    errors: list[str] = []
    for spec in VERTEX_PLAN:
        value = _count_vertex(conn, spec.graph_type)
        vertices[spec.graph_type] = value
        if value is None:
            errors.append(f"could not count vertex {spec.graph_type}")
    for spec in EDGE_PLAN:
        value = _count_edge(conn, spec)
        edges[spec.graph_type] = value
        if value is None:
            errors.append(f"could not count edge {spec.graph_type}")
    # AgentCase is observed-only and must not be treated as a static expected
    # count.  It is still useful in the health contract when present.
    managed: dict[str, Any] = {}
    try:
        managed["AgentCase"] = _count_vertex(conn, "AgentCase", retries=1)
    except Exception as exc:  # pragma: no cover
        managed["AgentCase"] = None
        errors.append(f"could not count managed AgentCase: {exc}")
    return vertices, edges, {"managed": managed, "errors": errors}


def _make_health(
    *,
    run_id: str,
    mode: str,
    source_validation: dict[str, Any],
    log: dict[str, Any],
    selected: set[str],
    remote: tuple[dict[str, int | None], dict[str, int | None], dict[str, Any]] | None,
    load_errors: list[str],
) -> dict[str, Any]:
    health = graph_health_contract(run_id, mode=mode)
    health["source"] = {
        "manifest_path": str(load_manifest().get("manifest_path", HEALTH_PATH.parent / "load_manifest.json")),
        "manifest_contract_version": load_manifest().get("contract_version"),
        "valid": bool(source_validation.get("valid")),
        "errors": list(source_validation.get("errors", [])),
        "expected_files": len(PLAN),
        "inspected_files": len(source_validation.get("entries", {})),
    }
    health["expected"]["vertices"] = source_validation.get("expected_vertex_counts", {})
    health["expected"]["edges"] = source_validation.get("expected_edge_counts", {})
    health["checks"]["source_files"] = {
        "status": "pass" if source_validation.get("valid") else "fail",
        "details": {"errors": source_validation.get("errors", [])},
    }
    health["checks"]["local_keys_and_orphans"] = {
        "status": "pass" if source_validation.get("valid") else "fail",
        "details": {"orphan_checks": source_validation.get("orphan_checks", [])},
    }
    health["checks"]["next_txn"] = {
        "status": "pass" if source_validation.get("next_txn", {}).get("valid") else "fail",
        "details": source_validation.get("next_txn", {}),
    }
    entity_states = {}
    for name, entity in log.get("entities", {}).items():
        entity_states[name] = {
            "done": bool(entity.get("done")),
            "rows": entity.get("rows"),
            "source_sha256": entity.get("source_sha256"),
            "failed_chunks": [
                key for key, value in entity.get("chunks", {}).items()
                if value.get("status") != "done"
            ],
        }
    health["checks"]["resume"] = {
        "status": "pass" if not load_errors else "fail",
        "details": {"run_id": run_id, "selected": sorted(selected), "entities": entity_states},
    }

    if remote is None:
        health["checks"]["remote_counts"] = {
            "status": "not_run",
            "details": {"reason": "connection unavailable or --verify-only without connection"},
        }
    else:
        observed_vertices, observed_edges, managed = remote
        health["observed"]["vertices"] = observed_vertices
        health["observed"]["edges"] = observed_edges
        health["observed"]["managed_vertices"] = managed.get("managed", {})
        count_errors = list(managed.get("errors", []))
        vertex_details: dict[str, Any] = {}
        for vertex_type, expected in health["expected"]["vertices"].items():
            observed = observed_vertices.get(vertex_type)
            vertex_details[vertex_type] = {
                "expected": expected,
                "observed": observed,
                "difference": observed - expected if observed is not None else None,
                "status": "pass" if observed == expected else "fail",
            }
        edge_details: dict[str, Any] = {}
        for edge_type, expected in health["expected"]["edges"].items():
            observed = observed_edges.get(edge_type)
            edge_details[edge_type] = {
                "expected": expected,
                "observed": observed,
                "difference": observed - expected if observed is not None else None,
                "status": "pass" if observed == expected else "fail",
            }
        failed = [
            f"vertex {key}: expected {value['expected']}, observed {value['observed']}"
            for key, value in vertex_details.items() if value["status"] != "pass"
        ] + [
            f"edge {key}: expected {value['expected']}, observed {value['observed']}"
            for key, value in edge_details.items() if value["status"] != "pass"
        ]
        health["checks"]["remote_counts"] = {
            "status": "pass" if not failed and not count_errors else "fail",
            "details": {"vertices": vertex_details, "edges": edge_details, "errors": count_errors},
        }
        if failed:
            load_errors.extend(failed)

    health["errors"] = list(dict.fromkeys(load_errors))
    local_ok = bool(source_validation.get("valid"))
    remote_ok = health["checks"]["remote_counts"]["status"] in {"pass", "not_run"}
    if not local_ok or health["checks"]["resume"]["status"] == "fail":
        health["status"] = "failed"
    elif remote is not None and health["checks"]["remote_counts"]["status"] == "fail":
        health["status"] = "partial" if mode == "only" else "failed"
    elif mode == "only":
        health["status"] = "healthy" if selected == set(PLAN_BY_NAME) else "partial"
    else:
        health["status"] = "healthy" if remote_ok else "failed"
    health["summary"] = {
        "expected_vertex_total": sum(health["expected"]["vertices"].values()),
        "observed_vertex_total": sum(v for v in health["observed"]["vertices"].values() if isinstance(v, int)),
        "expected_edge_total": sum(health["expected"]["edges"].values()),
        "observed_edge_total": sum(v for v in health["observed"]["edges"].values() if isinstance(v, int)),
        "failed_checks": [name for name, value in health["checks"].items() if value.get("status") == "fail"],
        "error_count": len(health["errors"]),
    }
    return health


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", help="comma-separated load names")
    parser.add_argument("--chunk-size", type=int, default=CHUNK_DEFAULT)
    parser.add_argument("--verify-only", action="store_true", help="do not upsert; only inspect and count")
    parser.add_argument("--no-remote", action="store_true", help="write local health without connecting")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.chunk_size < 1:
        raise SystemExit("--chunk-size must be positive")
    selected = set(args.only.split(",")) if args.only else {spec.name for spec in PLAN}
    unknown = selected - set(PLAN_BY_NAME)
    if unknown:
        raise SystemExit(f"unknown --only values: {sorted(unknown)}")

    run_id = str(uuid.uuid4())
    source_validation = inspect_sources(deep=True)
    log = read_json(LOG_PATH, default={}) or {}
    if not isinstance(log, dict) or log.get("version") != 2:
        log = {"version": 2, "entities": {}}
    log.setdefault("entities", {})
    log.update({"version": 2, "run_id": run_id, "updated_at": utc_now(), "mode": "verify-only" if args.verify_only else "load"})
    atomic_write_json(LOG_PATH, log)

    conn = None
    connection_error: str | None = None
    if not args.no_remote:
        try:
            conn = get_conn()
        except Exception as exc:  # retain a useful health artifact
            connection_error = f"{type(exc).__name__}: {exc}"
            print(connection_error, flush=True)

    load_errors: list[str] = []
    if not args.verify_only and conn is not None:
        for spec in PLAN:
            if spec.name not in selected:
                continue
            path = spec.path
            if not path.exists():
                load_errors.append(f"missing {spec.file_name}")
                atomic_write_json(LOG_PATH, log)
                continue
            try:
                frame = pd.read_parquet(path)
                fingerprint = _manifest_fingerprint(spec.name, path)
                print(f"{spec.name}: {len(frame):,} rows", flush=True)
                _, errors = _load_one(conn, spec, frame, fingerprint, log, run_id, args.chunk_size)
                load_errors.extend(errors)
            except Exception as exc:  # continue later edge types
                message = f"{spec.name}: {type(exc).__name__}: {str(exc)[:500]}"
                load_errors.append(message)
                log["entities"].setdefault(spec.name, {})["last_error"] = message
                atomic_write_json(LOG_PATH, log)
                print(f"{message}; continuing", flush=True)

    remote = None
    if conn is not None and not args.no_remote:
        remote = _remote_counts(conn)
    elif connection_error:
        load_errors.append(connection_error)
    if not source_validation.get("valid"):
        load_errors.extend(source_validation.get("errors", []))

    health = _make_health(
        run_id=run_id,
        mode="only" if args.only else ("verify-only" if args.verify_only else "load"),
        source_validation=source_validation,
        log=log,
        selected=selected,
        remote=remote,
        load_errors=load_errors,
    )
    atomic_write_json(HEALTH_PATH, health)
    counts = {
        "vertices": health["observed"]["vertices"],
        "edges": health["observed"]["edges"],
        "managed_vertices": health["observed"]["managed_vertices"],
        "health_status": health["status"],
        "health_path": str(HEALTH_PATH),
    }
    atomic_write_json(COUNTS_PATH, counts)
    print(json.dumps({"status": health["status"], "health": str(HEALTH_PATH), "errors": health["errors"][:10]}, indent=2))
    if health["status"] == "failed":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
