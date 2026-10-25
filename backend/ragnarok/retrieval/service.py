"""Retrieval service: the only door agents have to evidence.

Every path takes a mandatory as_of date and enforces publication_date <= as_of
in code (documents with no readable date never pass). Explicit requests for
out-of-window content return no content and log CLOCK_VIOLATION_BLOCKED.
Searches log QUERY and RETRIEVED; an identical repeat request (same case,
agent, normalised query, filters, as_of, limit and index version) is served
from the cache and logged as reused.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any

from ragnarok.config import Settings, get_settings
from ragnarok.models import DAMAGE_KINDS, AgentName, LogEvent, LogEventType, RelationType, RowStatus, TradeRow
from ragnarok.retrieval.embed import Embedder, FastEmbedder
from ragnarok.retrieval.index import HybridIndex, passes
from ragnarok.retrieval.text import normalise_query
from ragnarok.retrieval.types import (
    DocView,
    ParagraphView,
    SearchFilters,
    SearchHit,
    SearchResult,
    TradeQuery,
    TradeResult,
)
from ragnarok.store.db import Store

ADHOC_CASE = "adhoc"


def _as_date(v: date | str) -> date:
    if isinstance(v, date):
        return v
    return date.fromisoformat(str(v))


def _month_start(period: str) -> date:
    y, m = map(int, period.split("-"))
    return date(y, m, 1)


class RetrievalService:
    def __init__(self, store: Store, settings: Settings | None = None, embedder: Embedder | None = None,
                 index: HybridIndex | None = None) -> None:
        self.store = store
        self.settings = settings or get_settings()
        if index is not None:  # share a built index (and its embedder) across threads
            self.index, self.embedder = index, index.embedder
        else:
            self.embedder = embedder or FastEmbedder(self.settings.embedding_model, self.settings.index_dir / "models")
            self.index = HybridIndex(store, self.embedder, rrf_k=self.settings.rrf_k)

    def fork(self) -> "RetrievalService":
        """A service for another thread: own SQLite connection, shared index."""
        return RetrievalService(Store(self.store.path), self.settings, index=self.index)

    # ------------------------------------------------------------ logging ---

    def _log(self, case_id: str, run: int, agent: AgentName, type_: LogEventType, summary: str,
             payload: dict[str, Any] | None = None, refs: list[str] | None = None) -> int:
        return self.store.append_event(LogEvent(
            case_id=case_id, run_number=run, agent=agent, type=type_, summary=summary[:500],
            payload=payload or {}, refs=refs or [],
        ))

    def _blocked(self, case_id: str, run: int, agent: AgentName, what: str, ids: list[str], as_of: date) -> None:
        self._log(case_id, run, agent, LogEventType.CLOCK_VIOLATION_BLOCKED,
                  f"{agent.value} requested {what} not provably published on or before as_of {as_of}; content withheld",
                  {"as_of": as_of.isoformat(), "what": what}, ids)

    # ------------------------------------------------------------- search ---

    def search(self, query: str, as_of: date | str, agent: AgentName | str, filters: SearchFilters | dict | None = None,
               limit: int | None = None, case_id: str = ADHOC_CASE, run_number: int = 0) -> SearchResult:
        if as_of is None:
            raise ValueError("as_of is required")
        as_of = _as_date(as_of)
        agent = AgentName(agent)
        f = filters if isinstance(filters, SearchFilters) else SearchFilters(**(filters or {}))
        cap = self.settings.max_evidence_per_query
        limit = max(1, min(limit or cap, cap))
        if not query or not query.strip():
            raise ValueError("query must not be empty")
        self.index.refresh(store=self.store)
        qn = normalise_query(query)
        request = {"case_id": case_id, "agent": agent.value, "query": qn, "filters": f.model_dump(mode="json"),
                   "as_of": as_of.isoformat(), "limit": limit, "index_version": self.index.version,
                   "embedding_model": self.embedder.model_name}
        key = hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()

        if f.date_from and f.date_from > as_of or f.date_to and f.date_to > as_of:
            self._blocked(case_id, run_number, agent, f"a publication date range beyond the as_of date "
                          f"({f.date_from or '-'}..{f.date_to or '-'})", [], as_of)

        shown_filters = dict(request["filters"])  # the log shows how many refs were excluded, not the whole list
        if f.exclude_chunks:
            shown_filters["exclude_chunks"] = f"{len(f.exclude_chunks)} already-retrieved paragraph(s)"
        cached = self.store.cache_get(key)
        if cached is not None:
            result_json, first_seq = cached
            res = SearchResult.model_validate_json(result_json)
            seq = self._log(case_id, run_number, agent, LogEventType.QUERY,
                            f"{agent.value} query (reused from cache, identical request): {query}"[:500],
                            {"query": query, "query_norm": qn, "filters": shown_filters, "as_of": request["as_of"],
                             "limit": limit, "reused": True, "first_query_seq": first_seq, "cache_key": key})
            self._log(case_id, run_number, agent, LogEventType.RETRIEVED,
                      f"{len(res.hits)} paragraph(s) reused from cache", {"reused": True, "query_seq": seq},
                      [h.chunk_id for h in res.hits])
            return res.model_copy(update={"reused": True, "query_seq": seq, "first_query_seq": first_seq, "query": query})

        seq = self._log(case_id, run_number, agent, LogEventType.QUERY, f"{agent.value} query: {query}"[:500],
                        {"query": query, "query_norm": qn, "filters": shown_filters, "as_of": request["as_of"],
                         "limit": limit, "reused": False, "cache_key": key})
        if f.exclude_chunks:  # set lookup, not a list scan per chunk
            f = f.model_copy(update={"exclude_chunks": frozenset(f.exclude_chunks)})
        cands = [i for i, c in enumerate(self.index.chunks) if passes(c, f, as_of)]
        ranked = self.index.rank(query, cands, limit)
        hits = [self._hit(i, s, f, as_of) for i, s in ranked]
        res = SearchResult(query=query, query_norm=qn, as_of=as_of, agent=agent, filters=f, limit=limit, hits=hits,
                           candidates=len(cands), query_seq=seq)
        self._log(case_id, run_number, agent, LogEventType.RETRIEVED,
                  f"{len(hits)} paragraph(s) from {len({h.doc_id for h in hits})} document(s); {len(cands)} candidates",
                  {"query_seq": seq, "scores": {h.chunk_id: h.scores.model_dump() for h in hits}},
                  [h.chunk_id for h in hits])
        self.store.cache_put(key, case_id, agent.value, qn, json.dumps(request, sort_keys=True), res.model_dump_json(), seq)
        return res

    def _visible(self, doc_id: str, as_of: date) -> bool:
        d = self.store.conn.execute("SELECT pub_date FROM documents WHERE doc_id=?", (doc_id,)).fetchone()
        return bool(d and d["pub_date"] and date.fromisoformat(d["pub_date"]) <= as_of)

    def _hit(self, i: int, scores, f: SearchFilters, as_of: date) -> SearchHit:
        c = self.index.chunks[i]
        corrected_by = [src for src, typ, _ in self.store.incoming_relations(c.doc_id)
                        if typ in (RelationType.CORRECTS.value, RelationType.RETRACTS.value) and self._visible(src, as_of)]
        return SearchHit(
            chunk_id=c.chunk_id, doc_id=c.doc_id, paragraph_ref=c.paragraph_ref, text=c.text, title=c.title,
            pub_date=c.pub_date, pub_time=c.pub_time, reliability_tier=c.reliability_tier, source_name=c.source_name,
            source_type=c.source_type, country=c.country, sector=c.sector, table_sectors=c.table_sectors,
            event_id=c.event_id, damage=c.damage, injection_flagged=c.injection_flagged,
            possible_duplicate_of=[d for d in c.possible_duplicate_of if self._visible(d, as_of)],
            duplicate_of=c.duplicate_of if f.include_duplicates else None,
            corrects=[d for d in c.corrects if self._visible(d, as_of)], corrected_by=corrected_by, scores=scores,
        )

    # ----------------------------------------------------------- read_doc ---

    def read_doc(self, doc_id: str, as_of: date | str, agent: AgentName | str, paragraphs: list[str] | None = None,
                 case_id: str = ADHOC_CASE, run_number: int = 0, original_text: bool = False) -> DocView:
        """Read a document (or some paragraphs). Agents get evidence text; `original_text`
        is for human-facing views and Odin's audit, never for advocate prompts."""
        as_of = _as_date(as_of)
        agent = AgentName(agent)
        doc = self.store.get_document(doc_id)
        refs = ",".join(paragraphs) if paragraphs else "all"
        if doc is None:
            self._log(case_id, run_number, agent, LogEventType.ERROR, f"{agent.value} read_doc: {doc_id} does not exist",
                      {"doc_id": doc_id}, [doc_id])
            return DocView(doc_id=doc_id, status="not_found", reason="no such document")
        m = doc.meta
        if m.pub_date is None or m.pub_date > as_of:
            self._blocked(case_id, run_number, agent, f"document {doc_id} ({refs})", [doc_id], as_of)
            return DocView(doc_id=doc_id, status="blocked", reason=f"published after as_of {as_of} or undated")
        wanted = paragraphs or [p.ref for p in doc.paragraphs]
        flagged = {f.paragraph_ref for f in doc.injection_flags if f.paragraph_ref}
        views, missing = [], []
        for ref in wanted:
            p = doc.paragraph(ref)
            if p is None:
                missing.append(ref)
                continue
            text = p.text if original_text or p.evidence_text is None else p.evidence_text
            views.append(ParagraphView(ref=p.ref, text=text, injection_flagged=p.ref in flagged))
        relations = [f"{r.type.value} {r.target_doc_id}" for r in doc.relations if self._visible(r.target_doc_id, as_of)]
        relations += [f"{'corrected_by' if t == 'corrects' else 'retracted_by' if t == 'retracts' else t + '_from'} {src}"
                      for src, t, _ in self.store.incoming_relations(doc_id) if self._visible(src, as_of)]
        self._log(case_id, run_number, agent, LogEventType.RETRIEVED, f"{agent.value} read {doc_id} ({refs})",
                  {"tool": "read_doc", "missing_refs": missing}, [f"{doc_id}#{v.ref}" for v in views] or [doc_id])
        return DocView(
            doc_id=doc_id, status="ok", title=m.title, pub_date=m.pub_date, pub_time=m.pub_time,
            reliability_tier=m.reliability_tier, source_name=m.source_name, source_type=m.source_type, country=m.country,
            sector=m.sector, event_id=m.event_id, paragraphs=views, missing_refs=missing,
            damage=sorted({f"{f.kind.value}: {f.detail}" for f in doc.damage_flags if f.kind in DAMAGE_KINDS}),
            relations=relations,
        )

    # ------------------------------------------------------- trade rows ---

    def _doc_dates(self) -> dict[str, date | None]:
        return {r["doc_id"]: (date.fromisoformat(r["pub_date"]) if r["pub_date"] else None)
                for r in self.store.conn.execute("SELECT doc_id, pub_date FROM documents")}

    def _duplicate_docs(self) -> set[str]:
        return {r["doc_id"] for r in self.store.conn.execute(
            "SELECT doc_id FROM doc_relations WHERE type=?", (RelationType.DUPLICATE_OF.value,))}

    def rows_in_window(self, row_ids: list[str], as_of: date) -> tuple[list[TradeRow], dict[str, str]]:
        """Resolve row IDs under the as_of gate (no logging). Returns rows and {row_id: reason} for the rest."""
        dates = self._doc_dates()
        rows, withheld = [], {}
        for rid in row_ids:
            r = self.store.get_trade_row(rid)
            if r is None:
                withheld[rid] = "row not found"
            elif dates.get(r.source_doc_id) is None or dates[r.source_doc_id] > as_of:
                withheld[rid] = f"source {r.source_doc_id} published after as_of {as_of} (blocked)"
            elif r.period and _month_start(r.period) > as_of:
                withheld[rid] = f"period {r.period} is after as_of {as_of} (blocked)"
            else:
                rows.append(r)
        return rows, withheld

    def get_trade_rows(self, query: TradeQuery | dict, as_of: date | str, agent: AgentName | str,
                       case_id: str = ADHOC_CASE, run_number: int = 0) -> TradeResult:
        as_of = _as_date(as_of)
        agent = AgentName(agent)
        q = query if isinstance(query, TradeQuery) else TradeQuery(**query)
        dates = self._doc_dates()
        dups = self._duplicate_docs()
        blocked: list[str] = []
        not_found: list[str] = []
        explicit = set(q.row_ids or []) | set(q.table_ids or [])
        if q.row_ids:
            source = []
            for rid in q.row_ids:
                r = self.store.get_trade_row(rid)
                (source.append(r) if r else not_found.append(rid))
        else:
            source = self.store.all_trade_rows()
            if q.table_ids:
                known = {r.table_id for r in source}
                not_found += [t for t in q.table_ids if t not in known]
                source = [r for r in source if r.table_id in q.table_ids]
        self._log(case_id, run_number, agent, LogEventType.QUERY, f"{agent.value} trade-row request",
                  {"tool": "get_trade_rows", "query": q.model_dump(mode="json"), "as_of": as_of.isoformat()})
        out: list[TradeRow] = []
        for r in source:
            d = dates.get(r.source_doc_id)
            late = d is None or d > as_of or (r.period is not None and _month_start(r.period) > as_of)
            if late:
                if r.row_id in explicit or r.table_id in explicit:
                    blocked.append(r.row_id)
                continue
            if not q.include_duplicates and r.source_doc_id in dups and r.row_id not in explicit:
                continue
            if q.origin and r.origin.lower() not in q.origin:
                continue
            if q.destination and r.destination.lower() not in q.destination:
                continue
            if q.sector and r.sector.lower() not in q.sector:
                continue
            if q.period_from and (r.period is None or r.period < q.period_from):
                continue
            if q.period_to and (r.period is None or r.period > q.period_to):
                continue
            if q.valid_only and r.status != RowStatus.VALID:
                continue
            out.append(r)
        if blocked:
            self._blocked(case_id, run_number, agent, f"{len(blocked)} trade row(s)", blocked, as_of)
        if not_found:
            self._log(case_id, run_number, agent, LogEventType.ERROR, f"{agent.value} requested unknown trade rows/tables",
                      {"not_found": not_found}, not_found)
        self._log(case_id, run_number, agent, LogEventType.RETRIEVED,
                  f"{len(out)} trade row(s) ({sum(r.status != RowStatus.VALID for r in out)} invalid, shown with reasons)",
                  {"tool": "get_trade_rows"}, [r.row_id for r in out])
        return TradeResult(as_of=as_of, agent=agent, query=q, rows=out, blocked=blocked, not_found=not_found)

    # ------------------------------------------------------- calculations ---

    def calculator(self, as_of: date | str):
        """A TradeCalculator whose rows come through this service's as_of gate."""
        from ragnarok.calc.trade_calc import TradeCalculator

        return TradeCalculator(self.rows_in_window, _as_date(as_of))

    def save_calculation(self, record, case_id: str = ADHOC_CASE) -> str:
        self.store.save_calculation(record.calc_id, case_id, record.model_dump_json())
        return record.calc_id

    # --------------------------------------------------------- hot ingest ---

    def hot_ingest(self, pack_dir: Path | str, case_id: str = ADHOC_CASE):
        """Ingest a new pack into the live store and index (no restart, no code change)."""
        from ragnarok.ingest.pipeline import ingest_pack

        rep = ingest_pack(pack_dir, self.store, self.settings)
        before = len(self.index.chunks)
        self.index.refresh(store=self.store)
        self._log(case_id, 0, AgentName.HEIMDALL, LogEventType.INGEST,
                  f"hot ingest of pack {rep.pack_id}: {len(rep.documents)} document(s); index {before} -> "
                  f"{len(self.index.chunks)} paragraphs", {"pack_id": rep.pack_id, "errors": rep.errors},
                  [d.meta.doc_id for d in rep.documents])
        return rep
