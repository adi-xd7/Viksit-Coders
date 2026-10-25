"""The single embedding model: fastembed (local ONNX), cached in SQLite by text hash.

Vectors are L2-normalised float32, so cosine similarity is a dot product.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Protocol

import numpy as np

from ragnarok.store.db import Store

logging.getLogger("fastembed").setLevel(logging.ERROR)


class Embedder(Protocol):
    model_name: str

    def embed(self, texts: list[str]) -> np.ndarray: ...


class FastEmbedder:
    def __init__(self, model_name: str, cache_dir: Path) -> None:
        self.model_name = model_name
        self.cache_dir = cache_dir
        self._model = None

    def _load(self):
        if self._model is None:
            from fastembed import TextEmbedding

            self.cache_dir.mkdir(parents=True, exist_ok=True)
            self._model = TextEmbedding(self.model_name, cache_dir=str(self.cache_dir))
        return self._model

    def embed(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, 0), dtype=np.float32)
        vecs = np.asarray(list(self._load().embed(texts)), dtype=np.float32)
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        return vecs / np.where(norms == 0, 1, norms)


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def embed_cached(store: Store, embedder: Embedder, texts: list[str]) -> np.ndarray:
    """Embed texts, reusing vectors stored for identical text and model."""
    hashes = [text_hash(t) for t in texts]
    have = store.get_embeddings(embedder.model_name, sorted(set(hashes)))
    todo = sorted({h: t for h, t in zip(hashes, texts) if h not in have}.items())
    if todo:
        vecs = embedder.embed([t for _, t in todo])
        store.put_embeddings(embedder.model_name, vecs.shape[1],
                             [(h, v.astype(np.float32).tobytes()) for (h, _), v in zip(todo, vecs)])
        for (h, _), v in zip(todo, vecs):
            have[h] = v.astype(np.float32).tobytes()
    if not texts:
        return np.zeros((0, 0), dtype=np.float32)
    return np.stack([np.frombuffer(have[h], dtype=np.float32) for h in hashes])
