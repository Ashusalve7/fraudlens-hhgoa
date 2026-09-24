"""Shared load-plan and graph-health contract for FraudLens.

The load files are the source of truth for expected graph counts.  Keeping the
plan in one module prevents the schema, builder, loader, verifier, and MCP
backend from drifting apart.
"""
from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT.parent / "HHGOA_IEEE"
OUT = ROOT / "pipeline" / "out"
LOAD = OUT / "load"
MANIFEST_PATH = OUT / "load_manifest.json"
HEALTH_PATH = OUT / "graph_health.json"

CONTRACT_VERSION = "fraudlens.load-plan/v2"
HEALTH_CONTRACT_VERSION = "fraudlens.graph-health/v1"


@dataclass(frozen=True)
class LoadSpec:
    """One RESTPP-upsertable vertex or edge parquet file."""

    name: str
    kind: str  # "v" or "e"
    graph_type: str
    from_type: str | None = None
    to_type: str | None = None
    id_columns: tuple[str, ...] = ()
    attributes: tuple[str, ...] = ()

    @property
    def file_name(self) -> str:
        return f"{self.name}.parquet"

    @property
    def path(self) -> Path:
        return LOAD / self.file_name

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


# Vertices are loaded before edges.  AgentCase is intentionally managed at
# runtime by agent/evidence.py and is not part of the bulk load.  PolicyChunk is
# generated from the sponsor README and therefore is a static bulk vertex.
PLAN: tuple[LoadSpec, ...] = (
    LoadSpec("v_Customer", "v", "Customer", id_columns=("customer_id",)),
    LoadSpec("v_Card", "v", "Card", id_columns=("card_id",)),
    LoadSpec("v_EmailDomain", "v", "EmailDomain", id_columns=("domain",)),
    LoadSpec("v_BillingRegion", "v", "BillingRegion", id_columns=("region_id",)),
    LoadSpec("v_DeviceProfile", "v", "DeviceProfile", id_columns=("device_id",)),
    LoadSpec("v_ClosedCase", "v", "ClosedCase", id_columns=("case_id",)),
    LoadSpec("v_Transaction", "v", "Transaction", id_columns=("txn_id",)),
    LoadSpec("v_PolicyChunk", "v", "PolicyChunk", id_columns=("chunk_id",)),
    LoadSpec(
        "e_OWNS_CARD", "e", "OWNS_CARD", "Customer", "Card",
        ("customer_id", "card_id"), ("first_seen",),
    ),
    LoadSpec(
        "e_PAID_WITH", "e", "PAID_WITH", "Transaction", "Card",
        ("from", "card_id"), (),
    ),
    LoadSpec(
        "e_FROM_DEVICE", "e", "FROM_DEVICE", "Transaction", "DeviceProfile",
        ("from", "device_id"), (),
    ),
    LoadSpec(
        "e_P_EMAIL", "e", "P_EMAIL", "Transaction", "EmailDomain",
        ("from", "domain"), (),
    ),
    LoadSpec(
        "e_R_EMAIL", "e", "R_EMAIL", "Transaction", "EmailDomain",
        ("from", "domain"), (),
    ),
    LoadSpec(
        "e_BILLED_IN", "e", "BILLED_IN", "Transaction", "BillingRegion",
        ("from", "region_id"), (),
    ),
    LoadSpec(
        "e_NEXT_TXN", "e", "NEXT_TXN", "Transaction", "Transaction",
        ("txn_id", "next_id"), ("gap_seconds",),
    ),
    LoadSpec(
        "e_CASE_TXN", "e", "CASE_TXN", "ClosedCase", "Transaction",
        ("case_id", "txn_id"), (),
    ),
    LoadSpec(
        "e_CASE_CARD", "e", "CASE_CARD", "ClosedCase", "Card",
        ("case_id", "card_id"), (),
    ),
    LoadSpec(
        "e_CASE_CONN_CARD", "e", "CASE_CONN_CARD", "ClosedCase", "Card",
        ("case_id", "card_id"), (),
    ),
    LoadSpec(
        "e_CASE_DEVICE", "e", "CASE_DEVICE", "ClosedCase", "DeviceProfile",
        ("case_id", "device_id"), (),
    ),
)

PLAN_BY_NAME = {spec.name: spec for spec in PLAN}
VERTEX_PLAN = tuple(spec for spec in PLAN if spec.kind == "v")
EDGE_PLAN = tuple(spec for spec in PLAN if spec.kind == "e")

# These types are intentionally not counted as a static expected count.  An
# AgentCase is created by an investigation, and vector indexes are optional.
MANAGED_VERTEX_TYPES = ("AgentCase",)
MANAGED_COMPONENTS = {
    "AgentCase": {
        "owner": "agent/evidence.py or MCP case_write",
        "bulk_loaded": False,
        "count_invariant": "observed_only",
        "compatibility": "existing AgentCase attributes and AG_* edges",
    },
    "PolicyChunk.embedding": {
        "owner": "pipeline/index_policy.py",
        "bulk_loaded": False,
        "count_invariant": "optional_vector_index",
        "compatibility": "local 384-d artifact remains authoritative when TigerVector is unavailable",
    },
}


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write_json(path: Path, value: Any) -> None:
    """Write JSON atomically so a killed loader never leaves a truncated log."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, default=str), encoding="utf-8")
    os.replace(temporary, path)


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _empty_series_error(values: pd.Series) -> int:
    text = values.astype("string")
    return int((text.isna() | text.str.strip().isin(("", "nan", "None", "<NA>"))).sum())


def _dataframe_signature(path: Path, spec: LoadSpec) -> dict[str, Any]:
    """Return cheap file/schema facts and exact key/duplicate facts."""
    import pyarrow.parquet as pq

    parquet = pq.ParquetFile(path)
    columns = list(parquet.schema.names)
    result: dict[str, Any] = {
        "file": spec.file_name,
        "kind": spec.kind,
        "graph_type": spec.graph_type,
        "from_type": spec.from_type,
        "to_type": spec.to_type,
        "rows": int(parquet.metadata.num_rows),
        "columns": columns,
        "sha256": sha256_file(path),
        "size_bytes": int(path.stat().st_size),
    }
    missing = sorted(set(spec.id_columns) - set(columns))
    result["missing_id_columns"] = missing
    if missing:
        return result

    keys = pd.read_parquet(path, columns=list(spec.id_columns))
    null_or_empty = {column: _empty_series_error(keys[column]) for column in spec.id_columns}
    duplicate_rows = int(keys.duplicated(list(spec.id_columns), keep=False).sum())
    result["null_or_empty_ids"] = null_or_empty
    result["null_or_empty_id_total"] = int(sum(null_or_empty.values()))
    result["id_dtypes"] = {column: str(keys[column].dtype) for column in spec.id_columns}
    result["non_string_id_columns"] = [
        column for column in spec.id_columns if not pd.api.types.is_string_dtype(keys[column].dtype)
    ]
    result["duplicate_key_rows"] = duplicate_rows
    result["unique_key_count"] = int(len(keys.drop_duplicates(list(spec.id_columns))))
    return result


def _id_set(path: Path, column: str) -> set[str]:
    values = pd.read_parquet(path, columns=[column])[column]
    return set(values.astype(str).tolist())


def validate_next_txn(load_dir: Path = LOAD) -> dict[str, Any]:
    """Validate that NEXT_TXN is a same-card, chronological, acyclic chain."""
    edge_path = load_dir / "e_NEXT_TXN.parquet"
    txn_path = load_dir / "v_Transaction.parquet"
    card_map_path = load_dir.parent / "txn_card_map.parquet"
    if not card_map_path.exists():
        card_map_path = OUT / "txn_card_map.parquet"
    result: dict[str, Any] = {"valid": False, "checks": {}, "metrics": {}}
    if not edge_path.exists() or not txn_path.exists() or not card_map_path.exists():
        result["error"] = "NEXT_TXN, Transaction, or txn_card_map input is missing"
        return result

    edge = pd.read_parquet(edge_path)
    txn = pd.read_parquet(txn_path, columns=["txn_id", "ts"])
    card_map = pd.read_parquet(card_map_path, columns=["TransactionID", "card_id"])
    card_map["txn_id"] = card_map["TransactionID"].astype(str)
    edge["txn_id"] = edge["txn_id"].astype(str)
    edge["next_id"] = edge["next_id"].astype(str)
    txn["txn_id"] = txn["txn_id"].astype(str)
    txn["ts"] = pd.to_datetime(txn["ts"], errors="coerce")
    gap = pd.to_numeric(edge["gap_seconds"], errors="coerce")

    endpoints = set(txn["txn_id"])
    same_card = edge[["txn_id", "next_id"]].merge(
        card_map.rename(columns={"txn_id": "from_id", "card_id": "from_card"}),
        left_on="txn_id",
        right_on="from_id",
        how="left",
    ).merge(
        card_map.rename(columns={"txn_id": "to_id", "card_id": "to_card"}),
        left_on="next_id",
        right_on="to_id",
        how="left",
    )
    times = edge[["txn_id", "next_id"]].merge(
        txn.rename(columns={"txn_id": "from_id", "ts": "from_ts"}),
        left_on="txn_id",
        right_on="from_id",
        how="left",
    ).merge(
        txn.rename(columns={"txn_id": "to_id", "ts": "to_ts"}),
        left_on="next_id",
        right_on="to_id",
        how="left",
    )
    expected_gap = (times["to_ts"] - times["from_ts"]).dt.total_seconds()
    valid_expected_gap = expected_gap.notna() & (expected_gap >= 0) & ((expected_gap - gap).abs() < 1e-6)

    checks = {
        "endpoints_exist": bool(edge["txn_id"].isin(endpoints).all() and edge["next_id"].isin(endpoints).all()),
        "no_self_edges": bool((edge["txn_id"] != edge["next_id"]).all()),
        "one_outgoing_per_source": not bool(edge["txn_id"].duplicated().any()),
        "one_incoming_per_target": not bool(edge["next_id"].duplicated().any()),
        "same_card": bool((same_card["from_card"] == same_card["to_card"]).all()),
        "chronological": bool(valid_expected_gap.all()),
        "gap_is_uint64": bool(gap.notna().all() and (gap >= 0).all() and (gap % 1 == 0).all()),
    }
    result["checks"] = checks
    result["metrics"] = {
        "rows": int(len(edge)),
        "unique_sources": int(edge["txn_id"].nunique()),
        "unique_targets": int(edge["next_id"].nunique()),
        "min_gap_seconds": int(gap.min()) if len(gap) else 0,
        "max_gap_seconds": int(gap.max()) if len(gap) else 0,
    }
    result["valid"] = all(checks.values())
    return result


def _orphan_report(load_dir: Path, signatures: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    reports: list[dict[str, Any]] = []
    vertex_id_columns = {
        spec.graph_type: spec.id_columns[0] for spec in VERTEX_PLAN
    }
    ids = {vtype: _id_set(load_dir / f"v_{vtype}.parquet", col) for vtype, col in vertex_id_columns.items()}
    for spec in EDGE_PLAN:
        path = load_dir / spec.file_name
        if not path.exists():
            continue
        frame = pd.read_parquet(path, columns=list(spec.id_columns))
        source_values = set(frame[spec.id_columns[0]].astype(str))
        target_values = set(frame[spec.id_columns[1]].astype(str))
        source_orphans = len(source_values - ids.get(spec.from_type or "", set()))
        target_orphans = len(target_values - ids.get(spec.to_type or "", set()))
        reports.append({
            "edge_type": spec.graph_type,
            "source_type": spec.from_type,
            "target_type": spec.to_type,
            "orphan_source_ids": int(source_orphans),
            "orphan_target_ids": int(target_orphans),
            "valid": source_orphans == 0 and target_orphans == 0,
        })
    return reports


def inspect_sources(
    load_dir: Path = LOAD,
    specs: Sequence[LoadSpec] = PLAN,
    *,
    deep: bool = True,
) -> dict[str, Any]:
    """Inspect local files without contacting TigerGraph."""
    entries: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    for spec in specs:
        path = load_dir / spec.file_name
        if not path.exists():
            errors.append(f"missing {spec.file_name}")
            continue
        try:
            entries[spec.name] = _dataframe_signature(path, spec)
        except Exception as exc:  # pragma: no cover - defensive around corrupt parquet
            errors.append(f"{spec.file_name}: {type(exc).__name__}: {exc}")

    for name, entry in entries.items():
        if entry.get("missing_id_columns"):
            errors.append(f"{name}: missing id columns {entry['missing_id_columns']}")
        if entry.get("null_or_empty_id_total", 0):
            errors.append(f"{name}: null/empty IDs ({entry['null_or_empty_id_total']})")
        if entry.get("duplicate_key_rows", 0):
            errors.append(f"{name}: duplicate key rows ({entry['duplicate_key_rows']})")
        if entry.get("non_string_id_columns"):
            errors.append(
                f"{name}: graph IDs must use string dtype ({entry['non_string_id_columns']})"
            )

    next_validation: dict[str, Any] | None = None
    if deep and all((load_dir / name).exists() for name in ("e_NEXT_TXN.parquet", "v_Transaction.parquet")):
        next_validation = validate_next_txn(load_dir)
        if not next_validation.get("valid"):
            errors.append("e_NEXT_TXN: invalid chronological same-card chain")

    orphan_reports: list[dict[str, Any]] = []
    if deep and not errors:
        try:
            orphan_reports = _orphan_report(load_dir, entries)
            errors.extend(
                f"{r['edge_type']}: orphan endpoints"
                for r in orphan_reports if not r["valid"]
            )
        except Exception as exc:  # pragma: no cover
            errors.append(f"orphan validation failed: {type(exc).__name__}: {exc}")

    return {
        "contract_version": CONTRACT_VERSION,
        "generated_at": utc_now(),
        "load_directory": str(load_dir),
        "entries": entries,
        "expected_vertex_counts": {
            s.graph_type: int(entries[s.name]["rows"])
            for s in VERTEX_PLAN if s.name in entries
        },
        "expected_edge_counts": {
            s.graph_type: int(entries[s.name]["rows"])
            for s in EDGE_PLAN if s.name in entries
        },
        "next_txn": next_validation,
        "orphan_checks": orphan_reports,
        "errors": errors,
        "valid": not errors and len(entries) == len(specs),
    }


def source_manifest(
    *,
    source_files: Iterable[Path] = (),
    validation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    inspected = validation or inspect_sources()
    inputs = []
    for path in source_files:
        if path.exists():
            inputs.append({
                "path": str(path),
                "size_bytes": int(path.stat().st_size),
                "sha256": sha256_file(path),
            })
    return {
        "contract_version": CONTRACT_VERSION,
        "generated_at": utc_now(),
        "source_inputs": inputs,
        "source_inspection": inspected,
        "expected_vertex_counts": inspected["expected_vertex_counts"],
        "expected_edge_counts": inspected["expected_edge_counts"],
        "plan": [spec.as_dict() for spec in PLAN],
        "managed_components": MANAGED_COMPONENTS,
    }


def load_manifest() -> dict[str, Any]:
    return read_json(MANIFEST_PATH, default={}) or {}


def source_entry(name: str) -> dict[str, Any] | None:
    return load_manifest().get("source_inspection", {}).get("entries", {}).get(name)


def expected_counts() -> tuple[dict[str, int], dict[str, int]]:
    manifest = load_manifest()
    vertices = manifest.get("expected_vertex_counts", {})
    edges = manifest.get("expected_edge_counts", {})
    if not vertices or not edges:
        inspected = inspect_sources()
        vertices, edges = inspected["expected_vertex_counts"], inspected["expected_edge_counts"]
    return vertices, edges


def graph_health_contract(run_id: str, *, mode: str = "load") -> dict[str, Any]:
    """Return the stable graph_health.json envelope (before observations)."""
    return {
        "contract_version": HEALTH_CONTRACT_VERSION,
        "run_id": run_id,
        "generated_at": utc_now(),
        "graph": os.environ.get("TG_GRAPHNAME", "FraudGraph"),
        "mode": mode,
        "status": "pending",
        "summary": {},
        "source": {
            "manifest_path": str(MANIFEST_PATH),
            "manifest_contract_version": CONTRACT_VERSION,
            "valid": False,
            "errors": [],
        },
        "expected": {
            "vertices": {},
            "edges": {},
            "managed_vertices": list(MANAGED_VERTEX_TYPES),
        },
        "observed": {
            "vertices": {},
            "edges": {},
            "managed_vertices": {},
            "vector_indexes": {},
        },
        "checks": {
            "source_files": {"status": "pending", "details": {}},
            "local_keys_and_orphans": {"status": "pending", "details": {}},
            "next_txn": {"status": "pending", "details": {}},
            "resume": {"status": "pending", "details": {}},
            "remote_counts": {"status": "pending", "details": {}},
        },
        "errors": [],
        "remaining_risks": [
            "TigerGraph count endpoints may be eventually consistent for edge types.",
            "A non-empty AgentCase type and optional vector indexes are managed components, not static bulk counts.",
        ],
    }
