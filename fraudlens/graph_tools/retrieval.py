"""Local deterministic policy retrieval and graph-context provenance helpers."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

try:
    from pipeline.embeddings import EMBEDDING_DIM, EMBEDDING_MODEL, cosine, embed_text
except ImportError:  # pragma: no cover - direct package execution
    from ..pipeline.embeddings import EMBEDDING_DIM, EMBEDDING_MODEL, cosine, embed_text

_TOKEN = re.compile(r"[a-z0-9]+", re.IGNORECASE)


def _tokens(value: str) -> set[str]:
    return set(_TOKEN.findall(str(value).lower()))


def load_policy_index(out_dir: Path) -> tuple[pd.DataFrame, np.ndarray, dict[str, Any]]:
    """Load the rich local policy artifact, falling back to graph text.

    The fallback still uses deterministic embeddings; it never calls an
    external embedding API or invents a policy chunk.
    """
    rich_path = out_dir / "policy_chunks.parquet"
    vector_path = out_dir / "policy_embeddings.npz"
    if rich_path.exists():
        frame = pd.read_parquet(rich_path).copy()
    else:
        graph_path = out_dir / "load" / "v_PolicyChunk.parquet"
        if not graph_path.exists():
            return pd.DataFrame(), np.zeros((0, EMBEDDING_DIM), dtype=np.float32), {
                "available": False,
                "reason": "policy artifact and graph PolicyChunk load file are missing",
                "model": EMBEDDING_MODEL,
                "dimension": EMBEDDING_DIM,
            }
        frame = pd.read_parquet(graph_path).copy()
        for column, default in (("source_path", "unknown"), ("source_section", "unknown"),
                                ("source_anchor", ""), ("chunk_index", 0), ("content_hash", ""),
                                ("policy_rule", ""), ("patterns", "")):
            if column not in frame:
                frame[column] = default
    if vector_path.exists():
        with np.load(vector_path, allow_pickle=False) as archive:
            ids = [str(value) for value in archive["chunk_ids"].tolist()]
            vectors = np.asarray(archive["vectors"], dtype=np.float32)
            model = str(archive["model"][0]) if "model" in archive else EMBEDDING_MODEL
    else:
        ids = frame["chunk_id"].astype(str).tolist()
        vectors = np.vstack([embed_text(text) for text in frame["text"].astype(str)]).astype(np.float32)
        model = EMBEDDING_MODEL
    by_id = {str(value): index for index, value in enumerate(frame["chunk_id"].astype(str))}
    ordered = [by_id[value] for value in ids if value in by_id]
    vectors = vectors[: len(ordered)]
    frame = frame.iloc[ordered].reset_index(drop=True)
    return frame, vectors, {
        "available": True,
        "model": model,
        "dimension": int(vectors.shape[1]) if vectors.ndim == 2 else 0,
        "source": str(rich_path if rich_path.exists() else out_dir / "load" / "v_PolicyChunk.parquet"),
        "count": int(len(frame)),
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
    out_dir = out_dir or Path(__file__).resolve().parent.parent / "pipeline" / "out"
    frame, vectors, index_info = load_policy_index(out_dir)
    if not len(frame):
        return {"items": [], "retrieval": {**index_info, "query": query, "graph_context": graph_context or {}}}
    query_text = str(query or "")
    context = graph_context or {}
    context_terms = " ".join(f"{key} {value}" for key, value in context.items() if value not in (None, "", []))
    query_vector = embed_text(query_text + " " + context_terms)
    query_tokens = _tokens(query_text + " " + context_terms)
    pattern_key = str(pattern or "").lower().replace("-", "_")
    scores: list[tuple[float, int]] = []
    for index, row in frame.iterrows():
        text = str(row.get("text", ""))
        semantic = cosine(query_vector, vectors[index])
        lexical = len(query_tokens & _tokens(f"{row.get('title', '')} {text}")) / max(1, len(query_tokens))
        tags = str(row.get("patterns", "") or "").lower().replace("-", "_")
        tag_bonus = 0.20 if pattern_key and pattern_key in tags else 0.0
        scores.append((float(semantic + (0.25 * lexical) + tag_bonus), int(index)))
    scores.sort(key=lambda item: (-item[0], str(frame.iloc[item[1]]["chunk_id"])))
    items: list[dict[str, Any]] = []
    for score, index in scores[: max(1, min(int(limit), 50))]:
        row = frame.iloc[index]
        items.append({
            "chunk_id": str(row["chunk_id"]),
            "kind": str(row.get("kind", "")),
            "title": str(row.get("title", "")),
            "text": str(row.get("text", "")),
            "score": round(float(score), 8),
            "semantic_score": round(float(cosine(query_vector, vectors[index])), 8),
            "provenance": {
                "source_path": str(row.get("source_path", "unknown")),
                "source_section": str(row.get("source_section", "unknown")),
                "source_anchor": str(row.get("source_anchor", "")),
                "content_hash": str(row.get("content_hash", "")),
                "policy_rule": str(row.get("policy_rule", "")),
                "patterns": str(row.get("patterns", "")),
            },
        })
    return {
        "items": items,
        "retrieval": {
            **index_info,
            "query": query_text,
            "pattern": pattern,
            "graph_context": context,
            "scoring": "cosine(local-384d)+lexical-overlap+pattern-tag-boost",
            "fallback": "local deterministic embedding artifact" if index_info.get("source", "").endswith("policy_chunks.parquet") else "local deterministic embedding of graph text",
        },
    }


def case_provenance(row: dict[str, Any], *, source: str = "closed_cases_history.csv") -> dict[str, Any]:
    """Normalize a case row while retaining the actual source identity."""
    return {
        "case_id": str(row.get("case_id", "")),
        "customer_id": str(row.get("customer_id", "")),
        "card_id": str(row.get("card_id", "")),
        "pattern": str(row.get("pattern", "")),
        "outcome": str(row.get("outcome", "")),
        "exposure_usd": float(row.get("exposure_usd", 0) or 0),
        "n_txns": int(row.get("n_txns", 0) or 0),
        "actions": str(row.get("actions", "") or ""),
        "notes": str(row.get("notes", "") or ""),
        "provenance": {"source": source, "source_key": str(row.get("case_id", ""))},
    }
