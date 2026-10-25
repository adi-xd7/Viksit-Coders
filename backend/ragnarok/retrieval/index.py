"""Paragraph chunks and the hybrid (BM25 + one vector index) ranker with RRF fusion.

Order of operations for every query: (1) metadata filters and the as_of gate
select candidate chunks; (2) BM25 is built over the candidates only and the
query is scored; (3) cosine similarity against the candidates' vectors;
(4) Reciprocal Rank Fusion: score = sum over rankers of 1 / (k + rank).
Because the candidate set is fixed before ranking, out-of-window documents
cannot appear in results or influence BM25 statistics.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, time

import numpy as np
from rank_bm25 import BM25Okapi

from ragnarok.models import DAMAGE_KINDS, Document, RelationType
from ragnarok.retrieval.embed import Embedder, embed_cached
from ragnarok.retrieval.text import tokenize
from ragnarok.retrieval.types import HitScores, SearchFilters
from ragnarok.store.db import Store

BACKGROUND = "none"


@dataclass
class Chunk:
    chunk_id: str
    doc_id: str
    paragraph_ref: str
    ordinal: int
    text: str  # evidence text (what agents see)
    title: str
    pub_date: date | None
    pub_time: time | None
    reliability_tier: int | None
    source_name: str
    source_type: str
    country: str | None
    sector: str | None
    table_sectors: list[str]
    event_id: str | None
    pack_id: str
    damage: list[str]
    injection_flagged: bool
    duplicate_of: str | None
    possible_duplicate_of: list[str]
    corrects: list[str]
    tokens: list[str] = field(default_factory=list)

    @property
    def index_text(self) -> str:
        return f"{self.title}\n{self.text}"


def chunks_from_documents(docs: list[Document], table_sectors: dict[str, set[str]]) -> list[Chunk]:
    out: list[Chunk] = []
    for d in docs:
        m = d.meta
        flagged = {f.paragraph_ref for f in d.injection_flags if f.paragraph_ref}
        dup = next((r.target_doc_id for r in d.relations if r.type == RelationType.DUPLICATE_OF), None)
        near = [r.target_doc_id for r in d.relations if r.type == RelationType.NEAR_DUPLICATE_OF]
        corrects = [r.target_doc_id for r in d.relations if r.type in (RelationType.CORRECTS, RelationType.RETRACTS)]
        damage = sorted({f.kind.value for f in d.damage_flags if f.kind in DAMAGE_KINDS})
        for p in d.paragraphs:
            text = p.evidence_text if p.evidence_text is not None else p.text
            if not text.strip():
                continue
            c = Chunk(
                chunk_id=f"{m.doc_id}#{p.ref}", doc_id=m.doc_id, paragraph_ref=p.ref, ordinal=p.ordinal, text=text,
                title=m.title, pub_date=m.pub_date, pub_time=m.pub_time, reliability_tier=m.reliability_tier,
                source_name=m.source_name, source_type=m.source_type, country=m.country, sector=m.sector,
                table_sectors=sorted(table_sectors.get(m.doc_id, set())), event_id=m.event_id, pack_id=d.pack_id,
                damage=damage, injection_flagged=p.ref in flagged, duplicate_of=dup, possible_duplicate_of=near,
                corrects=corrects,
            )
            c.tokens = tokenize(c.index_text)
            out.append(c)
    return out


def passes(c: Chunk, f: SearchFilters, as_of: date) -> bool:
    """The as_of gate and metadata filters, applied in code to every chunk."""
    if c.pub_date is None or c.pub_date > as_of:
        return False
    if f.date_from and c.pub_date < f.date_from:
        return False
    if f.date_to and c.pub_date > f.date_to:
        return False
    if not f.include_duplicates and c.duplicate_of:
        return False
    if f.doc_ids and c.doc_id not in f.doc_ids:
        return False
    if f.country and (c.country or "").lower() not in f.country:
        return False
    if f.sector and not ({(c.sector or "").lower(), *c.table_sectors} & set(f.sector)):
        return False
    if f.event_id and (c.event_id.lower() if c.event_id else BACKGROUND) not in f.event_id:
        return False
    if f.source_type and c.source_type.lower() not in f.source_type:
        return False
    if f.max_reliability is not None and (c.reliability_tier is None or c.reliability_tier > f.max_reliability):
        return False
    return True


class HybridIndex:
    def __init__(self, store: Store, embedder: Embedder, rrf_k: int = 60) -> None:
        self.store = store
        self.embedder = embedder
        self.rrf_k = rrf_k
        self.chunks: list[Chunk] = []
        self.vectors = np.zeros((0, 0), dtype=np.float32)
        self.version = -1

    def refresh(self, force: bool = False, store: Store | None = None) -> bool:
        """Rebuild from the store if it changed (hot ingest). Only new texts are embedded.

        `store` lets a thread use its own SQLite connection with a shared index."""
        store = store or self.store
        v = store.version()
        if not force and v == self.version:
            return False
        chunks = chunks_from_documents(store.all_documents(), store.table_sectors_by_doc())
        self.vectors = embed_cached(store, self.embedder, [c.index_text for c in chunks])
        self.chunks = chunks
        self.version = v
        return True

    def rank(self, query: str, candidates: list[int], limit: int) -> list[tuple[int, HitScores]]:
        if not candidates:
            return []
        q_tokens = tokenize(query)
        bm25_rank: dict[int, tuple[int, float]] = {}
        if q_tokens:
            bm25 = BM25Okapi([self.chunks[i].tokens or ["_"] for i in candidates])
            scores = bm25.get_scores(q_tokens)
            order = sorted((s, -n, i) for n, (i, s) in enumerate(zip(candidates, scores)) if s > 0)[::-1]
            bm25_rank = {i: (r + 1, float(s)) for r, (s, _, i) in enumerate(order)}
        qv = self.embedder.embed([query])[0]
        cos = self.vectors[candidates] @ qv
        vorder = sorted(range(len(candidates)), key=lambda n: (-cos[n], n))
        vec_rank = {candidates[n]: (r + 1, float(cos[n])) for r, n in enumerate(vorder)}
        fused: list[tuple[float, int, HitScores]] = []
        for i in candidates:
            b = bm25_rank.get(i)
            v = vec_rank[i]
            rrf = 1.0 / (self.rrf_k + v[0]) + (1.0 / (self.rrf_k + b[0]) if b else 0.0)
            fused.append((rrf, i, HitScores(rrf=round(rrf, 6), bm25_rank=b[0] if b else None,
                                            bm25=round(b[1], 4) if b else None, vector_rank=v[0], cosine=round(v[1], 4))))
        fused.sort(key=lambda x: (-x[0], self.chunks[x[1]].chunk_id))
        return [(i, s) for _, i, s in fused[:limit]]
