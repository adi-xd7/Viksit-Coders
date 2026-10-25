"""
Index builder — creates FAISS vector and BM25 keyword indices
from the parsed document corpus.

Each document is chunked, embedded, and indexed for hybrid retrieval.
"""

from __future__ import annotations

import json
import pickle
import re
from pathlib import Path
from typing import Any

import numpy as np

import config
from heimdall.logger import HeimdallLogger


# ── Chunk dataclass (stored as JSON) ─────────────────────────────────────────

def _make_chunk(doc_id: str, chunk_idx: int, text: str,
                metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        "doc_id": doc_id,
        "chunk_idx": chunk_idx,
        "text": text,
        "metadata": metadata,
    }


# ── Text chunking ────────────────────────────────────────────────────────────

def chunk_text(text: str, chunk_size: int = config.CHUNK_SIZE,
               overlap: int = config.CHUNK_OVERLAP) -> list[str]:
    """Split text into overlapping chunks by character count."""
    if not text:
        return []
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        if chunk.strip():
            chunks.append(chunk.strip())
        start = end - overlap
    return chunks


# ── Tokeniser for BM25 ──────────────────────────────────────────────────────

_WORD_RE = re.compile(r"\w+")

def tokenize(text: str) -> list[str]:
    """Simple whitespace + punctuation tokeniser, lowercased."""
    return [w.lower() for w in _WORD_RE.findall(text)]


# ── Index builder ────────────────────────────────────────────────────────────

class IndexBuilder:
    """Build and persist FAISS + BM25 indices from parsed documents."""

    def __init__(self, logger: HeimdallLogger | None = None):
        self.logger = logger or HeimdallLogger()
        self.chunks: list[dict[str, Any]] = []
        self._faiss_index = None
        self._bm25 = None

    def build(self, doc_texts: dict[str, str],
              doc_metadata: dict[str, dict[str, Any]]) -> None:
        """
        Build indices from parsed document texts.

        Args:
            doc_texts: {DOC_ID: plain_text}
            doc_metadata: {DOC_ID: manifest_entry}
        """
        self.logger.info("Building indices",
                         doc_count=len(doc_texts))

        # 1. Chunk all documents
        self.chunks = []
        for doc_id, text in doc_texts.items():
            if not text:
                continue
            meta = doc_metadata.get(doc_id, {})
            text_chunks = chunk_text(text)
            for i, chunk_text_str in enumerate(text_chunks):
                self.chunks.append(_make_chunk(doc_id, i, chunk_text_str, meta))

        if not self.chunks:
            self.logger.failure("build_index", "no chunks to index")
            return

        self.logger.info(f"Created {len(self.chunks)} chunks from "
                         f"{len(doc_texts)} documents")

        # 2. Build FAISS index
        self._build_faiss()

        # 3. Build BM25 index
        self._build_bm25()

        # 4. Persist
        self._save()

    def _build_faiss(self) -> None:
        """Create FAISS flat-L2 index from chunk embeddings."""
        import faiss
        from sentence_transformers import SentenceTransformer

        self.logger.info("Loading embedding model",
                         model=config.EMBEDDING_MODEL_NAME)
        model = SentenceTransformer(config.EMBEDDING_MODEL_NAME)

        texts = [c["text"] for c in self.chunks]
        self.logger.info(f"Encoding {len(texts)} chunks")
        embeddings = model.encode(texts, show_progress_bar=True,
                                  convert_to_numpy=True)
        embeddings = np.array(embeddings, dtype="float32")

        # Normalise for cosine similarity via inner-product
        faiss.normalize_L2(embeddings)

        index = faiss.IndexFlatIP(config.EMBEDDING_DIMENSION)
        index.add(embeddings)
        self._faiss_index = index

        self.logger.info(f"FAISS index built with {index.ntotal} vectors")

    def _build_bm25(self) -> None:
        """Create BM25 index from tokenised chunks."""
        from rank_bm25 import BM25Okapi

        corpus = [tokenize(c["text"]) for c in self.chunks]
        self._bm25 = BM25Okapi(corpus)
        self.logger.info(f"BM25 index built with {len(corpus)} documents")

    def _save(self) -> None:
        """Persist indices to disk."""
        config.INDEX_DIR.mkdir(parents=True, exist_ok=True)

        # FAISS
        if self._faiss_index is not None:
            import faiss
            faiss.write_index(self._faiss_index,
                              str(config.FAISS_INDEX_PATH))

        # BM25
        if self._bm25 is not None:
            with open(config.BM25_INDEX_PATH, "wb") as f:
                pickle.dump(self._bm25, f)

        # Chunks metadata
        with open(config.CHUNKS_PATH, "w", encoding="utf-8") as f:
            json.dump(self.chunks, f, default=str)

        self.logger.info("Indices saved to disk")

    def load(self) -> bool:
        """Load persisted indices. Returns True if successful."""
        try:
            import faiss

            if not (config.FAISS_INDEX_PATH.exists() and
                    config.BM25_INDEX_PATH.exists() and
                    config.CHUNKS_PATH.exists()):
                return False

            self._faiss_index = faiss.read_index(
                str(config.FAISS_INDEX_PATH))

            with open(config.BM25_INDEX_PATH, "rb") as f:
                self._bm25 = pickle.load(f)

            with open(config.CHUNKS_PATH, "r", encoding="utf-8") as f:
                self.chunks = json.load(f)

            self.logger.info("Indices loaded from disk",
                             chunks=len(self.chunks))
            return True
        except Exception as exc:
            self.logger.failure("load_index", str(exc))
            return False

    @property
    def faiss_index(self):
        return self._faiss_index

    @property
    def bm25(self):
        return self._bm25

    @property
    def is_built(self) -> bool:
        return (self._faiss_index is not None and
                self._bm25 is not None and
                len(self.chunks) > 0)
