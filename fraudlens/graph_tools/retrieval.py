"""Deterministic policy retrieval with source-level provenance."""
from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

try:
    from pipeline.embeddings import EMBEDDING_DIM, EMBEDDING_MODEL, cosine, embed_text
except ImportError:  # pragma: no cover - package import path
    from ..pipeline.embeddings import EMBEDDING_DIM, EMBEDDING_MODEL, cosine, embed_text

_TOKEN = re.compile(r"[a-z0-9]+", re.IGNORECASE)


def _tokens(value: str) -> set[str]:
    return set(_TOKEN.findall(str(value).lower()))


def _normalise_tags(value: Any) -> set[str]:
    return {
        token
        for token in re.split(r"[^a-z0-9]+", str(value or "").lower())
        if token
    }


def _normalise_policy_frame(frame: pd.DataFrame) -> pd.DataFrame:
    required = {"chunk_id", "text"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"PolicyChunk frame is missing columns: {missing}")
    result = frame.copy()
    if result["chunk_id"].astype(str).duplicated().any():
        raise ValueError("PolicyChunk frame contains duplicate chunk_id values")
    defaults = {
        "kind": "policy",
        "title": "",
        "source_path": "unknown",
        "source_section": "unknown",
        "source_anchor": "",
        "content_hash": "",
        "policy_rule": "",
        "patterns": "",
    }
    for column, default in defaults.items():
        if column not in result:
            result[column] = default
        result[column] = result[column].fillna(default).astype(str)
    result["chunk_id"] = result["chunk_id"].astype(str)
    result["text"] = result["text"].astype(str)
    return result.reset_index(drop=True)


def _embed_frame(frame: pd.DataFrame) -> np.ndarray:
    if frame.empty:
        return np.zeros((0, EMBEDDING_DIM), dtype=np.float32)
    return np.vstack([embed_text(text) for text in frame["text"]]).astype(np.float32)


def _load_vector_pairs(
    vector_path: Path,
    frame: pd.DataFrame,
) -> tuple[np.ndarray, list[int], str, str]:
    """Align vectors by chunk ID; never rely on independent row positions."""
    with np.load(vector_path, allow_pickle=False) as archive:
        required = {"chunk_ids", "vectors"}
        if not required.issubset(archive.files):
            raise ValueError("policy vector archive is missing chunk_ids/vectors")
        ids = [str(value) for value in archive["chunk_ids"].tolist()]
        vectors = np.asarray(archive["vectors"], dtype=np.float32)
        model = str(archive["model"][0]) if "model" in archive and len(archive["model"]) else EMBEDDING_MODEL
    if vectors.ndim != 2 or vectors.shape[0] != len(ids) or vectors.shape[1] != EMBEDDING_DIM:
        raise ValueError("policy vector archive has an invalid shape or dimension")
    if len(set(ids)) != len(ids):
        raise ValueError("policy vector archive contains duplicate chunk IDs")

    by_id = {value: index for index, value in enumerate(frame["chunk_id"].astype(str))}
    positions = [by_id[value] for value in ids if value in by_id]
    if not positions:
        raise ValueError("policy vector archive does not match the PolicyChunk frame")
    vector_positions = [index for index, value in enumerate(ids) if value in by_id]
    ordered_vectors = vectors[vector_positions]
    return ordered_vectors, positions, model, "policy_embeddings.npz"


def load_policy_index(out_dir: Path) -> tuple[pd.DataFrame, np.ndarray, dict[str, Any]]:
    """Load rich local chunks or graph text with deterministic embeddings."""
    out_dir = Path(out_dir)
    rich_path = out_dir / "policy_chunks.parquet"
    graph_path = out_dir / "load" / "v_PolicyChunk.parquet"
    vector_path = out_dir / "policy_embeddings.npz"
    if rich_path.exists():
        source_path = rich_path
        source_kind = "rich_local_artifact"
    elif graph_path.exists():
        source_path = graph_path
        source_kind = "graph_policychunk_text"
    else:
        return pd.DataFrame(), np.zeros((0, EMBEDDING_DIM), dtype=np.float32), {
            "available": False,
            "reason": "policy artifact and graph PolicyChunk load file are missing",
            "model": EMBEDDING_MODEL,
            "dimension": EMBEDDING_DIM,
            "remote": False,
        }

    frame = _normalise_policy_frame(pd.read_parquet(source_path))
    positions = list(range(len(frame)))
    vector_source = "embedded_from_text_at_query_time"
    model = EMBEDDING_MODEL
    if vector_path.exists():
        try:
            vectors, positions, model, vector_source = _load_vector_pairs(vector_path, frame)
        except (OSError, ValueError, KeyError):
            vectors = _embed_frame(frame)
            vector_source = "embedded_from_text_after_invalid_vector_artifact"
    else:
        vectors = _embed_frame(frame)

    frame = frame.iloc[positions].reset_index(drop=True)
    return frame, vectors, {
        "available": True,
        "model": model,
        "dimension": int(vectors.shape[1]) if vectors.ndim == 2 else 0,
        "source": str(source_path),
        "source_kind": source_kind,
        "vector_source": vector_source,
        "count": int(len(frame)),
        "remote": False,
    }


def rank_policy_chunks(
    query: str,
    frame: pd.DataFrame,
    vectors: np.ndarray,
    *,
    pattern: str = "",
    graph_context: dict[str, Any] | None = None,
    limit: int = 5,
    index_info: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Rank a real PolicyChunk frame; shared by local and graph backends."""
    limit = int(limit)
    if limit < 1 or limit > 50:
        raise ValueError("limit must be between 1 and 50")
    frame = _normalise_policy_frame(frame)
    if vectors.shape != (len(frame), EMBEDDING_DIM):
        raise ValueError("policy vectors do not align with PolicyChunk rows")
    if not len(frame):
        return {
            "items": [],
            "retrieval": {
                **(index_info or {}),
                "query": str(query or ""),
                "pattern": pattern,
                "graph_context": graph_context or {},
                "scoring": "cosine(local-384d)+lexical-overlap+pattern-tag-boost",
            },
        }

    query_text = str(query or "")
    context = graph_context or {}
    context_terms = " ".join(
        f"{key} {value}" for key, value in context.items() if value not in (None, "", [])
    )
    query_vector = embed_text(query_text + " " + context_terms)
    query_tokens = _tokens(query_text + " " + context_terms)
    pattern_key = str(pattern or "").lower().replace("-", "_")
    scores: list[tuple[float, int, str]] = []
    for index, row in frame.iterrows():
        text = str(row["text"])
        semantic = cosine(query_vector, vectors[index])
        lexical = len(query_tokens & _tokens(f"{row['title']} {text}")) / max(1, len(query_tokens))
        tag_bonus = 0.20 if pattern_key and pattern_key in _normalise_tags(row["patterns"]) else 0.0
        scores.append((float(semantic + (0.25 * lexical) + tag_bonus), int(index), str(row["chunk_id"])))

    scores.sort(key=lambda item: (-item[0], item[2], item[1]))
    items: list[dict[str, Any]] = []
    for score, index, _ in scores[:limit]:
        row = frame.iloc[index]
        items.append(
            {
                "chunk_id": str(row["chunk_id"]),
                "kind": str(row["kind"]),
                "title": str(row["title"]),
                "text": str(row["text"]),
                "score": round(float(score), 8),
                "semantic_score": round(float(cosine(query_vector, vectors[index])), 8),
                "provenance": {
                    "source_path": str(row["source_path"]),
                    "source_section": str(row["source_section"]),
                    "source_anchor": str(row["source_anchor"]),
                    "content_hash": str(row["content_hash"]),
                    "policy_rule": str(row["policy_rule"]),
                    "patterns": str(row["patterns"]),
                },
            }
        )
    return {
        "items": items,
        "retrieval": {
            **(index_info or {}),
            "query": query_text,
            "pattern": pattern,
            "graph_context": context,
            "scoring": "cosine(local-384d)+lexical-overlap+pattern-tag-boost",
            "remote": bool((index_info or {}).get("remote", False)),
        },
    }


def search_policy(
    query: str,
    *,
    pattern: str = "",
    graph_context: dict[str, Any] | None = None,
    limit: int = 5,
    out_dir: Path | None = None,
) -> dict[str, Any]:
    """Return ranked real PolicyChunks and explicit retrieval provenance."""
    out_dir = Path(out_dir) if out_dir is not None else Path(__file__).resolve().parent.parent / "pipeline" / "out"
    frame, vectors, index_info = load_policy_index(out_dir)
    return rank_policy_chunks(
        query,
        frame,
        vectors,
        pattern=pattern,
        graph_context=graph_context,
        limit=limit,
        index_info=index_info,
    )


def _finite_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    return text or None


def case_provenance(row: dict[str, Any], *, source: str = "closed_cases_history.csv") -> dict[str, Any]:
    """Normalize a closed-case row while retaining its actual source identity."""
    report = row.get("report_filed")
    if isinstance(report, str):
        report_bool = report.strip().lower() in {"1", "true", "yes", "y"}
    else:
        report_bool = bool(report)
    return {
        "case_id": str(row.get("case_id", "")),
        "customer_id": str(row.get("customer_id", "") or ""),
        "card_id": str(row.get("card_id", "") or ""),
        "pattern": str(row.get("pattern", "") or ""),
        "outcome": str(row.get("outcome", "") or ""),
        "opened_at": _optional_text(row.get("opened_at")),
        "closed_at": _optional_text(row.get("closed_at")),
        "exposure_usd": _finite_float(row.get("exposure_usd")),
        "n_txns": max(0, int(_finite_float(row.get("n_txns")))),
        "report_filed": report_bool,
        "actions": str(row.get("actions", "") or ""),
        "notes": str(row.get("notes", "") or ""),
        "provenance": {"source": source, "source_key": str(row.get("case_id", ""))},
    }
