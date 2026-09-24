"""Deterministic, dependency-light 384-dimensional text embeddings.

The implementation is a signed feature-hashing encoder.  It intentionally has
no network or model-service dependency: the same text always produces the same
unit-length vector, and the vector can be uploaded to TigerGraph when vector
indexing is available or queried from a local ``.npz`` artifact otherwise.
"""
from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable

import numpy as np

EMBEDDING_DIM = 384
EMBEDDING_MODEL = "fraudlens-signed-hashing-v1"
_TOKEN_RE = re.compile(r"[a-z0-9]+(?:[._/-][a-z0-9]+)*", re.IGNORECASE)


def _tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def _add_feature(vector: np.ndarray, feature: str, weight: float = 1.0) -> None:
    digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
    number = int.from_bytes(digest, "little", signed=False)
    index = number % EMBEDDING_DIM
    sign = 1.0 if (number >> 63) & 1 else -1.0
    vector[index] += sign * weight


def embed_text(text: str) -> np.ndarray:
    """Return a deterministic L2-normalized 384-d vector."""
    vector = np.zeros(EMBEDDING_DIM, dtype=np.float64)
    tokens = _tokens(text or "")
    if not tokens:
        return vector.astype(np.float32)

    # Word unigrams/bigrams retain policy terms such as R1 and "new device";
    # character trigrams provide stable recall for spelling variants.
    for token in tokens:
        _add_feature(vector, f"w:{token}")
    for left, right in zip(tokens, tokens[1:]):
        _add_feature(vector, f"b:{left}|{right}", 0.65)
    padded = f"  {' '.join(tokens)}  "
    for i in range(len(padded) - 2):
        trigram = padded[i : i + 3]
        if " " not in trigram:
            _add_feature(vector, f"c:{trigram}", 0.18)

    norm = float(np.linalg.norm(vector))
    if norm:
        vector /= norm
    return vector.astype(np.float32)


def embed_many(texts: Iterable[str]) -> np.ndarray:
    vectors = [embed_text(text) for text in texts]
    if not vectors:
        return np.zeros((0, EMBEDDING_DIM), dtype=np.float32)
    return np.vstack(vectors).astype(np.float32)


def cosine(left: np.ndarray, right: np.ndarray) -> float:
    a = np.asarray(left, dtype=np.float32).reshape(-1)
    b = np.asarray(right, dtype=np.float32).reshape(-1)
    if a.size != EMBEDDING_DIM or b.size != EMBEDDING_DIM:
        raise ValueError(f"vectors must have dimension {EMBEDDING_DIM}")
    denominator = float(np.linalg.norm(a) * np.linalg.norm(b))
    return float(np.dot(a, b) / denominator) if denominator else 0.0
