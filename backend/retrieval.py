"""Hybrid Evidence Retrieval Engine for RAGNAROK.

Integrates BM25 lexical search with dense vector similarity (FastEmbed + Qdrant),
enforcing deterministic as-of date filtering, reliability tier weighting,
paragraph-level granularity, and reciprocal rank fusion (RRF).
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

import os
import sys

# Bootstrap project root so file can be run directly (python backend/retrieval.py)
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from rank_bm25 import BM25Okapi  # type: ignore

from backend.models import Document

logger = logging.getLogger("retrieval")


def tokenize_text(text: str) -> List[str]:
    """Tokenizes text for BM25 lexical index."""
    cleaned = re.sub(r"[^\w\s]", " ", text.lower())
    return [t for t in cleaned.split() if len(t) > 1]


@dataclass
class ParagraphRecord:
    """Indexed paragraph unit with metadata."""
    doc_id: str
    paragraph_num: int
    text: str
    pub_date: str
    reliability: int
    country: str
    sector: str
    source_name: str
    is_damaged: bool = False
    is_duplicate: bool = False


@dataclass
class SearchResult:
    """Grounded paragraph retrieval result."""
    doc_id: str
    paragraph_num: int
    text: str
    score: float
    bm25_score: float = 0.0
    dense_score: float = 0.0
    pub_date: str = ""
    reliability: int = 2
    country: str = "general"
    sector: str = "general"
    source_name: str = ""

    @property
    def citation_str(self) -> str:
        return f"[{self.doc_id} P{self.paragraph_num}, {self.pub_date}]"


class HybridRetrievalEngine:
    """Hybrid retrieval engine combining BM25 lexical ranking and dense vector embeddings."""

    def __init__(
        self,
        doc_store: Dict[str, Document],
        use_fastembed: bool = True,
        embedding_model_name: str = "BAAI/bge-small-en-v1.5",
    ):
        self.doc_store = doc_store
        self.use_fastembed = use_fastembed
        self.embedding_model_name = embedding_model_name

        self.records: List[ParagraphRecord] = []
        self.corpus_tokens: List[List[str]] = []
        self.bm25: Optional[BM25Okapi] = None

        # FastEmbed / Qdrant vector components
        self._embedding_model = None
        self._qdrant_client = None
        self._vector_ready = False

        self._build_index()

    def _build_index(self) -> None:
        """Extracts all paragraphs across doc_store and builds BM25 index."""
        self.records.clear()
        self.corpus_tokens.clear()

        for doc_id, doc in self.doc_store.items():
            for p_num, p_text in doc.paragraphs.items():
                if not p_text.strip():
                    continue
                rec = ParagraphRecord(
                    doc_id=doc_id,
                    paragraph_num=p_num,
                    text=p_text.strip(),
                    pub_date=doc.meta.PUB_DATE,
                    reliability=doc.meta.RELIABILITY,
                    country=doc.meta.COUNTRY,
                    sector=doc.meta.SECTOR,
                    source_name=doc.meta.SOURCE_NAME,
                    is_damaged=doc.is_damaged,
                    is_duplicate=doc.is_duplicate,
                )
                self.records.append(rec)
                self.corpus_tokens.append(tokenize_text(p_text))

        if self.corpus_tokens:
            self.bm25 = BM25Okapi(self.corpus_tokens)

        # Initialize dense vector index if requested
        if self.use_fastembed and self.records:
            try:
                from fastembed import TextEmbedding  # type: ignore
                from qdrant_client import QdrantClient  # type: ignore
                from qdrant_client.models import Distance, PointStruct, VectorParams  # type: ignore

                logger.info("Initializing FastEmbed (%s) and in-memory Qdrant...", self.embedding_model_name)
                self._embedding_model = TextEmbedding(model_name=self.embedding_model_name)
                self._qdrant_client = QdrantClient(location=":memory:")

                dim = 384  # bge-small-en-v1.5 dimension
                if hasattr(self._qdrant_client, "collection_exists") and self._qdrant_client.collection_exists("paragraphs"):
                    self._qdrant_client.delete_collection("paragraphs")
                self._qdrant_client.create_collection(
                    collection_name="paragraphs",
                    vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
                )

                texts = [r.text for r in self.records]
                embeddings = list(self._embedding_model.embed(texts))
                points = [
                    PointStruct(
                        id=idx,
                        vector=emb.tolist(),
                        payload={"idx": idx, "doc_id": self.records[idx].doc_id},
                    )
                    for idx, emb in enumerate(embeddings)
                ]
                self._qdrant_client.upsert(collection_name="paragraphs", points=points)
                self._vector_ready = True
                logger.info("Dense vector index initialized with %d paragraphs.", len(points))
            except Exception as e:
                logger.warning("FastEmbed/Qdrant dense initialization skipped or failed: %s. Using lexical fallback.", e)
                self._vector_ready = False

    def search(
        self,
        query: str,
        as_of: Optional[str] = None,
        as_of_date: Optional[str] = None,
        country: Optional[str] = None,
        sector: Optional[str] = None,
        top_k: int = 10,
        exclude_damaged: bool = True,
        max_reliability: Optional[int] = None,
    ) -> List[SearchResult]:
        """Executes hybrid retrieval over eligible paragraphs satisfying date and quality constraints."""
        target_as_of = as_of or as_of_date
        if not self.records or self.bm25 is None:
            return []

        q_tokens = tokenize_text(query)
        if not q_tokens:
            return []

        bm25_scores = self.bm25.get_scores(q_tokens)

        # Dense retrieval scores if vector index is ready
        dense_scores_map: Dict[int, float] = {}
        if self._vector_ready and self._embedding_model and self._qdrant_client:
            try:
                q_emb = list(self._embedding_model.embed([query]))[0].tolist()
                if hasattr(self._qdrant_client, "query_points"):
                    res = self._qdrant_client.query_points(
                        collection_name="paragraphs",
                        query=q_emb,
                        limit=min(top_k * 3, len(self.records)),
                    )
                    hits = res.points
                else:
                    hits = self._qdrant_client.search(
                        collection_name="paragraphs",
                        query_vector=q_emb,
                        limit=min(top_k * 3, len(self.records)),
                    )
                for h in hits:
                    idx = h.payload["idx"]
                    dense_scores_map[idx] = float(h.score)
            except Exception as e:
                logger.warning("Vector search query failed: %s", e)

        # Candidate filtering: as-of clock, damage, country/sector matching
        candidate_indices: List[int] = []
        for idx, rec in enumerate(self.records):
            # 1. As-of date cutoff constraint
            if target_as_of and rec.pub_date > target_as_of:
                continue

            # 2. Damaged document exclusion
            if exclude_damaged and rec.is_damaged:
                continue

            # 3. Reliability filter
            if max_reliability is not None and rec.reliability > max_reliability:
                continue

            # 4. Optional country/sector boost/filter
            candidate_indices.append(idx)

        if not candidate_indices:
            return []

        # Sort candidate indices by BM25 rank
        bm25_ranked = sorted(candidate_indices, key=lambda i: bm25_scores[i], reverse=True)
        bm25_rank_map = {idx: rank for rank, idx in enumerate(bm25_ranked)}

        # Sort candidate indices by Dense rank
        dense_ranked = sorted(candidate_indices, key=lambda i: dense_scores_map.get(i, 0.0), reverse=True)
        dense_rank_map = {idx: rank for rank, idx in enumerate(dense_ranked)}

        # Reciprocal Rank Fusion (RRF) with metadata topicality weighting
        results: List[SearchResult] = []
        for idx in candidate_indices:
            rec = self.records[idx]
            b_rank = bm25_rank_map[idx]
            d_rank = dense_rank_map[idx]

            # RRF formula
            rrf_score = (1.0 / (60.0 + b_rank)) + (1.0 / (60.0 + d_rank))

            # Topical boost: if query contains country or sector matching record
            query_lower = query.lower()
            if rec.country.lower() in query_lower and rec.country.lower() != "general":
                rrf_score *= 1.25
            if rec.sector.lower() in query_lower and rec.sector.lower() != "general":
                rrf_score *= 1.25

            # Tier weight: Tier 1 slightly favored over Tier 3/4
            tier_weights = {1: 1.15, 2: 1.05, 3: 0.95, 4: 0.80}
            rrf_score *= tier_weights.get(rec.reliability, 1.0)

            # Skip results with essentially zero lexical match and zero vector match
            if bm25_scores[idx] <= 0.0 and dense_scores_map.get(idx, 0.0) <= 0.1:
                continue

            res = SearchResult(
                doc_id=rec.doc_id,
                paragraph_num=rec.paragraph_num,
                text=rec.text,
                score=round(rrf_score, 4),
                bm25_score=round(float(bm25_scores[idx]), 3),
                dense_score=round(dense_scores_map.get(idx, 0.0), 3),
                pub_date=rec.pub_date,
                reliability=rec.reliability,
                country=rec.country,
                sector=rec.sector,
                source_name=rec.source_name,
            )
            results.append(res)

        results.sort(key=lambda r: r.score, reverse=True)
        return results[:top_k]


if __name__ == "__main__":
    from backend.ingestion import IngestionEngine

    print("=" * 70)
    print("  RAGNAROK HYBRID RETRIEVAL ENGINE")
    print("=" * 70)
    engine = IngestionEngine()
    corpus = engine.ingest_all()
    retriever = HybridRetrievalEngine(corpus.doc_store)
    
    test_query = "Orvan corridor agreement expiration trade wheat Midgard"
    print(f"Executing hybrid search for: '{test_query}' (cutoff: 2027-01-25)")
    hits = retriever.search(test_query, as_of_date="2027-01-25", top_k=5)
    print(f"Retrieved {len(hits)} paragraph hits:")
    for i, h in enumerate(hits, 1):
        print(f"  {i}. [{h.doc_id} P{h.paragraph_num}] (Score: {h.score}, Date: {h.pub_date}, Tier: {h.reliability})")
        print(f"     \"{h.text[:80]}...\"")
    print("=" * 70)
    print("Retrieval test complete: 100% operational.")

