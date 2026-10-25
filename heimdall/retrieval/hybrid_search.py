"""
Hybrid search engine — combines semantic (FAISS) and keyword (BM25) search
with Reciprocal Rank Fusion and metadata filtering.

Supports at least two metadata filters as required by the hackathon.
"""

from __future__ import annotations

from typing import Any

import numpy as np

import config
from heimdall.logger import HeimdallLogger
from heimdall.retrieval.index_builder import IndexBuilder, tokenize


class HybridSearchEngine:
    """
    Hybrid retrieval combining:
      1. Semantic search (FAISS, cosine similarity via normalized IP)
      2. Keyword search (BM25Okapi)
      3. Reciprocal Rank Fusion (RRF) to merge results
      4. Metadata filters (pub_date, country, sector, event_id,
         reliability, source_type — at least two required)
    """

    def __init__(self, index_builder: IndexBuilder,
                 logger: HeimdallLogger | None = None):
        self.ib = index_builder
        self.logger = logger or HeimdallLogger()

    # ── Core search ──────────────────────────────────────────────────────

    def search(
        self,
        query: str,
        top_k: int = config.HYBRID_TOP_K,
        *,
        # Metadata filters
        as_of_date: str | None = None,
        country: str | None = None,
        sector: str | None = None,
        event_id: str | None = None,
        source_type: str | None = None,
        reliability_max: int | None = None,
        # Control
        exclude_doc_ids: list[str] | None = None,
        semantic_weight: float = 0.5,
        keyword_weight: float = 0.5,
    ) -> list[dict[str, Any]]:
        """
        Run hybrid search with metadata filtering.

        Returns list of chunk dicts enriched with 'score' and 'rank'.
        """
        if not self.ib.is_built:
            self.logger.failure("hybrid_search", "indices not built")
            return []

        # 1. Pre-filter chunks by metadata
        candidate_indices = self._metadata_filter(
            as_of_date=as_of_date,
            country=country,
            sector=sector,
            event_id=event_id,
            source_type=source_type,
            reliability_max=reliability_max,
            exclude_doc_ids=exclude_doc_ids,
        )

        if not candidate_indices:
            self.logger.info("No chunks survived metadata filtering")
            return []

        # 2. Semantic search over candidates
        semantic_results = self._semantic_search(query, candidate_indices,
                                                 config.DEFAULT_TOP_K)

        # 3. Keyword search over candidates
        keyword_results = self._keyword_search(query, candidate_indices,
                                               config.DEFAULT_TOP_K)

        # 4. Reciprocal Rank Fusion
        fused = self._rrf_fuse(semantic_results, keyword_results,
                               semantic_weight, keyword_weight)

        # 5. Take top_k, deduplicate by doc_id
        results = self._deduplicate_and_rank(fused, top_k)

        # Log
        doc_ids = [r["doc_id"] for r in results]
        self.logger.retrieved_documents(doc_ids, query, "hybrid")

        return results

    # ── Semantic search ──────────────────────────────────────────────────

    def _semantic_search(self, query: str,
                         candidate_indices: list[int],
                         top_k: int) -> list[tuple[int, float]]:
        """Return (chunk_index, score) pairs from FAISS."""
        from sentence_transformers import SentenceTransformer

        model = SentenceTransformer(config.EMBEDDING_MODEL_NAME)
        query_emb = model.encode([query], convert_to_numpy=True)
        query_emb = np.array(query_emb, dtype="float32")

        import faiss
        faiss.normalize_L2(query_emb)

        # Search full index then filter to candidates
        k = min(self.ib.faiss_index.ntotal, max(top_k * 5, 100))
        scores, indices = self.ib.faiss_index.search(query_emb, k)

        candidate_set = set(candidate_indices)
        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx in candidate_set:
                results.append((int(idx), float(score)))
            if len(results) >= top_k:
                break

        return results

    # ── Keyword search ───────────────────────────────────────────────────

    def _keyword_search(self, query: str,
                        candidate_indices: list[int],
                        top_k: int) -> list[tuple[int, float]]:
        """Return (chunk_index, score) pairs from BM25."""
        tokens = tokenize(query)
        if not tokens:
            return []

        all_scores = self.ib.bm25.get_scores(tokens)

        # Filter to candidates and sort
        scored = [(idx, all_scores[idx]) for idx in candidate_indices
                  if all_scores[idx] > 0]
        scored.sort(key=lambda x: x[1], reverse=True)

        return scored[:top_k]

    # ── Metadata filtering ───────────────────────────────────────────────

    def _metadata_filter(
        self,
        as_of_date: str | None = None,
        country: str | None = None,
        sector: str | None = None,
        event_id: str | None = None,
        source_type: str | None = None,
        reliability_max: int | None = None,
        exclude_doc_ids: list[str] | None = None,
    ) -> list[int]:
        """Return indices of chunks that pass all metadata filters."""
        exclude_set = set(exclude_doc_ids or [])
        results = []

        for i, chunk in enumerate(self.ib.chunks):
            meta = chunk.get("metadata", {})

            # As-of date filter (mandatory in practice)
            if as_of_date:
                pub_date = meta.get("PUB_DATE", "9999-99-99")
                if pub_date > as_of_date:
                    continue

            # Country filter
            if country:
                doc_country = str(meta.get("COUNTRY", "")).lower()
                if doc_country != country.lower():
                    continue

            # Sector filter
            if sector:
                doc_sector = str(meta.get("SECTOR", "")).lower()
                if doc_sector != sector.lower() and doc_sector != "general":
                    continue

            # Event ID filter
            if event_id:
                doc_event = str(meta.get("EVENT_ID", "")).upper()
                if doc_event != event_id.upper() and doc_event != "NONE":
                    continue

            # Source type filter
            if source_type:
                doc_source = str(meta.get("SOURCE_TYPE", "")).lower()
                if doc_source != source_type.lower():
                    continue

            # Reliability filter
            if reliability_max is not None:
                try:
                    rel = int(meta.get("RELIABILITY", 4))
                except (ValueError, TypeError):
                    rel = 4
                if rel > reliability_max:
                    continue

            # Exclude previously returned docs
            if chunk["doc_id"] in exclude_set:
                continue

            results.append(i)

        return results

    # ── Reciprocal Rank Fusion ───────────────────────────────────────────

    def _rrf_fuse(
        self,
        semantic: list[tuple[int, float]],
        keyword: list[tuple[int, float]],
        sem_weight: float = 0.5,
        kw_weight: float = 0.5,
    ) -> list[tuple[int, float]]:
        """Fuse two ranked lists using RRF."""
        k = config.RRF_K
        scores: dict[int, float] = {}

        for rank, (idx, _) in enumerate(semantic):
            scores[idx] = scores.get(idx, 0) + sem_weight / (k + rank + 1)

        for rank, (idx, _) in enumerate(keyword):
            scores[idx] = scores.get(idx, 0) + kw_weight / (k + rank + 1)

        fused = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return fused

    # ── De-duplication ───────────────────────────────────────────────────

    def _deduplicate_and_rank(self, fused: list[tuple[int, float]],
                              top_k: int) -> list[dict[str, Any]]:
        """Keep the best chunk per doc_id, return enriched dicts."""
        seen_docs: set[str] = set()
        results: list[dict[str, Any]] = []

        for idx, score in fused:
            chunk = self.ib.chunks[idx]
            doc_id = chunk["doc_id"]
            if doc_id in seen_docs:
                continue
            seen_docs.add(doc_id)

            results.append({
                **chunk,
                "score": score,
                "rank": len(results) + 1,
            })
            if len(results) >= top_k:
                break

        return results
