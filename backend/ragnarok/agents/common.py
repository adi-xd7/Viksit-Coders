"""Shared agent machinery: prompts, document wrapping, code-enforced tool
permissions and budgets, the research loop, and citation conversion.

Security properties enforced here (not in prompts):
- Each agent can only run the tools in TOOL_PERMISSIONS[agent].
- Every tool runs with the case's as_of; no request field can change it.
- Tool calls are counted per agent and per case; over budget -> LIMIT_HIT.
- Distinct evidence (paragraphs/rows) retrieved per case is capped; over -> LIMIT_HIT.
- A search identical to a query from an earlier run can be refused (send-back research).
- Memory is private: an AgentEnv reads and writes only its own agent's lessons.
- Evidence shared with the Case File (Heimdall's code-run seed searches, read back
  from the query cache; the case file's trade rows) passes the same as_of gate and
  is logged for the receiving agent; it never counts as that agent's own search.
- Retrieved text is always wrapped in <document> tags with "<"/">" escaped,
  so a document cannot close its own wrapper or fake a system block.
- Citations are resolved against the store; dates come from the store, never
  from the model, and a citation must point to evidence this agent retrieved.
"""

from __future__ import annotations

import html
import json
import threading
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from ragnarok.agents.schemas import (
    CalcOp,
    CitationDraft,
    DualResearchTurn,
    InjectionReport,
    MemoryResearchTurn,
    ResearchTurn,
    ToolRequest,
)
from ragnarok.config import Settings
from ragnarok.ingest.injection import evidence_text, scan_text
from ragnarok.llm.client import LimitHit, LLMClient
from ragnarok.memory.lessons import LessonDraft
from ragnarok.memory.store import AgentMemory, lesson_key, memory_payload, render_lessons
from ragnarok.models import AgentName, Citation, LogEvent, LogEventType, MemoryEntry, RowStatus
from ragnarok.retrieval.citations import validate_citation
from ragnarok.retrieval.service import RetrievalService
from ragnarok.retrieval.text import normalise_query
from ragnarok.retrieval.types import SearchFilters, SearchResult, TradeQuery

PROMPTS = Path(__file__).parent / "prompts"

TOOL_PERMISSIONS: dict[AgentName, frozenset[str]] = {
    AgentName.HEIMDALL: frozenset({"search", "read_doc", "get_trade_rows"}),
    AgentName.THOR: frozenset({"search", "read_doc", "get_trade_rows", "trade_calc"}),
    AgentName.LOKI: frozenset({"search", "read_doc", "get_trade_rows", "trade_calc"}),
    AgentName.ODIN: frozenset({"read_doc", "trade_calc", "validate_citation"}),
}
MAX_REQUESTS_PER_ROUND = 5  # legacy default; the limit used is settings.max_requests_per_round
MAX_EVIDENCE_CHARS = 60_000
RETRIEVAL_TOOLS = frozenset({"search", "read_doc", "get_trade_rows"})


class ToolPermissionError(PermissionError):
    pass


def load_prompt(agent: AgentName) -> str:
    preamble = (PROMPTS / "preamble.md").read_text(encoding="utf-8").strip()
    role = (PROMPTS / f"{agent.value}.md").read_text(encoding="utf-8").strip()
    return f"{preamble}\n\n{role}"


def _esc(text: str) -> str:
    return html.escape(str(text), quote=False)


def wrap_document(doc_id: str, text: str, *, ref: str | None = None, tier: int | None = None,
                  date_: date | str | None = None, source: str = "", source_type: str = "",
                  flags: list[str] | None = None) -> str:
    """Wrap untrusted text. Angle brackets are escaped so the text cannot close the
    tag or open a fake one; attributes are escaped too."""
    attrs = {"id": f"{doc_id}#{ref}" if ref else doc_id, "tier": tier if tier is not None else "?",
             "date": str(date_) if date_ else "?", "source": source, "type": source_type}
    if flags:
        attrs["flags"] = ",".join(flags)
    a = " ".join(f'{k}="{html.escape(str(v), quote=True)}"' for k, v in attrs.items())
    return f"<document {a}>\n{_esc(text)}\n</document>"


# --------------------------------------------------------------------------- #
# Case context and per-thread agent environment
# --------------------------------------------------------------------------- #


@dataclass
class CaseContext:
    case_id: str
    question: str
    as_of: date
    settings: Settings
    llm: LLMClient
    run_number: int = 1
    # resume of an earlier attempt of this case: events before this seq belong to that attempt
    replay_before_seq: int = 0
    replay_recalls: dict[tuple, list[list[dict]]] = field(default_factory=dict)  # (agent, run, purpose) -> recalled lessons
    replay_writes: set[tuple] = field(default_factory=set)  # (agent, run, memory_id) written by the earlier attempt
    tool_calls: dict[str, int] = field(default_factory=dict)
    evidence: set[str] = field(default_factory=set)  # distinct paragraph/row refs retrieved in the case (all agents)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def check_evidence_budget(self) -> None:
        with self.lock:
            if len(self.evidence) >= self.settings.max_evidence_per_case:
                raise LimitHit("retrieved evidence for the case", len(self.evidence), self.settings.max_evidence_per_case)

    def add_evidence(self, refs: list[str]) -> None:
        with self.lock:
            self.evidence.update(r for r in refs if not r.startswith("CALC-"))

    def count_tool_call(self, agent: AgentName) -> None:
        with self.lock:
            used_agent = self.tool_calls.get(agent.value, 0)
            used_case = sum(self.tool_calls.values())
            if used_agent >= self.settings.max_tool_calls_per_agent:
                raise LimitHit(f"tool calls for {agent.value}", used_agent, self.settings.max_tool_calls_per_agent)
            if used_case >= self.settings.max_tool_calls_per_case:
                raise LimitHit("tool calls for the case", used_case, self.settings.max_tool_calls_per_case)
            self.tool_calls[agent.value] = used_agent + 1


@dataclass
class ToolOutcome:
    tool: str
    ok: bool
    text: str
    refs: list[str] = field(default_factory=list)
    error: str | None = None


class AgentEnv:
    """One agent's view: its tools (permission-checked), its retrieved evidence, its log."""

    def __init__(self, ctx: CaseContext, agent: AgentName, service: RetrievalService) -> None:
        self.ctx = ctx
        self.agent = agent
        self.service = service
        self.retrieved: set[str] = set()  # "DOC#P3", row IDs, calc IDs
        self.outcomes: list[ToolOutcome] = []
        self.searches = 0
        self.forbidden_queries: set[str] = set()  # normalised queries this agent may not send again (earlier runs)
        self._requests_seen: set[str] = set()  # search requests made in this attempt (resume replay detection)
        self.memory = AgentMemory(service.store, agent)  # this agent's own lessons only

    # ---------------------------------------------------------- logging ---

    def log(self, type_: LogEventType, summary: str, payload: dict[str, Any] | None = None,
            refs: list[str] | None = None, agent: AgentName | None = None) -> int:
        return self.service.store.append_event(LogEvent(
            case_id=self.ctx.case_id, run_number=self.ctx.run_number, agent=agent or self.agent, type=type_,
            summary=summary[:500], payload=payload or {}, refs=refs or []))

    # ------------------------------------------------------------ tools ---

    def run_tool(self, req: ToolRequest) -> ToolOutcome:
        if req.tool not in TOOL_PERMISSIONS[self.agent]:
            self.log(LogEventType.ERROR, f"{self.agent.value} requested tool '{req.tool}', which it is not permitted to use; refused",
                     {"tool": req.tool, "permitted": sorted(TOOL_PERMISSIONS[self.agent])})
            raise ToolPermissionError(f"{self.agent.value} may not use {req.tool}")
        if req.tool == "search" and normalise_query(req.query or "") in self.forbidden_queries:
            self.log(LogEventType.ERROR, f"{self.agent.value} repeated a query from an earlier run; refused (a new query is "
                     f"required): {req.query}", {"query": req.query, "rule": "send-back research needs new queries"})
            out = ToolOutcome("search", False, f"[refused by the system: the query {req.query!r} was already used earlier in "
                              "this case; write a new, more targeted query]", error="repeated_query")
            self.outcomes.append(out)
            return out
        try:
            self.ctx.count_tool_call(self.agent)
            if req.tool in RETRIEVAL_TOOLS:
                self.ctx.check_evidence_budget()
        except LimitHit as exc:
            self.log(LogEventType.LIMIT_HIT, f"{self.agent.value}: {exc}", {"what": exc.what, "used": exc.used, "limit": exc.limit})
            raise
        try:
            out = getattr(self, f"_tool_{req.tool}")(req)
        except (ValueError, KeyError, TypeError) as exc:
            out = ToolOutcome(req.tool, False, f"[tool error: {exc}]", error=str(exc))
        self.outcomes.append(out)
        self.retrieved.update(out.refs)
        self.ctx.add_evidence(out.refs)
        return out

    def receive_case_evidence(self, refs: list[str], note: str) -> ToolOutcome | None:
        """Evidence delivered with the Case File (Heimdall's new findings), fetched through the
        same as_of-gated service paths. Not a tool call of this agent, so it is not counted as one."""
        rows = [r for r in refs if "#R" in r]
        paras: dict[str, list[str]] = {}
        for r in refs:
            if "#P" in r and r not in rows:
                d, p = r.split("#", 1)
                paras.setdefault(d, []).append(p)
        parts, got = [], []
        for d, ps in paras.items():
            o = self._tool_read_doc(ToolRequest(tool="read_doc", purpose="case file evidence", doc_id=d, paragraphs=ps))
            if o.ok:
                parts.append(o.text)
                got += o.refs
        if rows:
            o = self._tool_get_trade_rows(ToolRequest(tool="get_trade_rows", purpose="case file evidence", row_ids=rows))
            parts.append(o.text)
            got += o.refs
        if not parts:
            return None
        out = ToolOutcome("case_file_evidence", True, f"[{note}]\n" + "\n".join(parts), refs=got)
        self.outcomes.append(out)
        self.retrieved.update(got)
        return out

    def receive_seed(self, seeds: list[dict], note: str) -> ToolOutcome | None:
        """Heimdall's code-run seed searches, read back from the query cache (no new search):
        the hits are re-checked against the as_of gate and logged as RETRIEVED for this agent
        (reused, with the seed query's seq). Not this agent's own search or tool call."""
        blocks, got = [], []
        for sd in seeds:
            cached = self.service.store.cache_get(sd["cache_key"])
            if cached is None:
                continue
            res = SearchResult.model_validate_json(cached[0])
            hits = [h for h in res.hits if h.pub_date is not None and h.pub_date <= self.ctx.as_of]
            refs = [h.chunk_id for h in hits]
            self.log(LogEventType.RETRIEVED, f"{self.agent.value} received {len(hits)} paragraph(s) from Heimdall's seed "
                     f"search {sd['query']!r} (query cache, no new search)",
                     {"seed": True, "reused": True, "from_agent": "heimdall", "query_seq": sd.get("query_seq"),
                      "query": sd["query"], "filters": sd.get("filters", {})}, refs)
            flagged = [h.chunk_id for h in hits if h.injection_flagged]
            if flagged:
                self.log(LogEventType.TRAP_INJECTION, f"{self.agent.value} received flagged paragraph(s) {', '.join(flagged)}"
                         "; instruction text withheld from the agent", {"query": sd["query"], "seed": True}, flagged)
            blocks.append(f"seed search {sd['query']!r} filters={sd.get('filters', {})} -> {len(hits)} hit(s)\n"
                          + "\n".join(self._hit_block(h) for h in hits))
            got += refs
        if not blocks:
            return None
        out = ToolOutcome("case_file_seed", True, f"[{note}]\n" + "\n".join(blocks), refs=got)
        self.outcomes.append(out)
        self.retrieved.update(got)
        self.ctx.add_evidence(got)
        return out

    # ----------------------------------------------------------- memory ---

    def recall(self, stages: list[str], purpose: str) -> list[MemoryEntry]:
        """Recall this agent's own lessons for a stage (always logged, also when there are none)."""
        if not self.ctx.settings.memory_enabled:
            return []
        key = (self.agent.value, self.ctx.run_number, purpose)
        if self.ctx.replay_recalls.get(key):
            lessons = self._replayed(self.ctx.replay_recalls[key].pop(0))
        else:
            lessons = self.memory.recall(stages, self.ctx.settings.memory_recall_limit)
        self.log(LogEventType.MEMORY_READ, f"{self.agent.value} recalled {len(lessons)} lesson(s) before {purpose}"
                 + (": " + " | ".join(m.lesson[:90] for m in lessons[:3]) if lessons else ""),
                 {"stages": stages, "purpose": purpose, "memory": memory_payload(lessons)}, [m.memory_id for m in lessons])
        return lessons

    def _replayed(self, recorded: list[dict]) -> list[MemoryEntry]:
        """Resume: the lessons this recall returned in the earlier attempt, as they were then
        (so a replayed step sees the same prompt). Own memory only."""
        out = []
        for rec in recorded:
            m = self.memory.get(rec["memory_id"])
            if m is not None:
                out.append(m.model_copy(update={"times_seen": rec.get("times_seen", m.times_seen),
                                                "confidence": rec.get("confidence", m.confidence)}))
        return out

    def remember(self, drafts: list[LessonDraft]) -> list[MemoryEntry]:
        out = []
        for d in drafts:
            if d.agent != self.agent:
                raise PermissionError(f"{self.agent.value} cannot write {d.agent.value}'s memory")
            mid = f"M-{self.agent.value}-{lesson_key(d.lesson)[:10]}"
            if (self.agent.value, self.ctx.run_number, mid) in self.ctx.replay_writes:
                self.log(LogEventType.MEMORY_WRITE, f"{self.agent.value} lesson {mid} was already written for run "
                         f"{self.ctx.run_number} by the earlier attempt of this case; not reinforced again",
                         {"memory_id": mid, "replayed": True}, [mid])
                continue
            entry, created = self.memory.write(d.lesson, kind=d.kind, stages=d.stages, context=d.context,
                                               confidence=d.confidence, source_case=self.ctx.case_id,
                                               source_run=self.ctx.run_number)
            self.log(LogEventType.MEMORY_WRITE, f"{self.agent.value} {'stored' if created else 'reinforced'} lesson "
                     f"{entry.memory_id} ({d.kind}): {entry.lesson}",
                     {"memory": memory_payload([entry])[0], "created": created, "stages": entry.stages}, [entry.memory_id])
            out.append(entry)
        return out

    def _cid(self) -> dict[str, Any]:
        return {"case_id": self.ctx.case_id, "run_number": self.ctx.run_number}

    def _tool_search(self, req: ToolRequest) -> ToolOutcome:
        if not req.query:
            raise ValueError("search needs a query")
        f = SearchFilters(country=req.countries, sector=req.sectors, event_id=req.event_ids, source_type=req.source_types,
                          max_reliability=req.max_reliability if 1 <= req.max_reliability <= 4 else None)
        res = self.service.search(req.query, self.ctx.as_of, self.agent, f, **self._cid())
        rkey = json.dumps([res.query_norm, f.model_dump(mode="json")], sort_keys=True)
        replay = (res.reused and rkey not in self._requests_seen and res.first_query_seq is not None
                  and res.first_query_seq < self.ctx.replay_before_seq)  # resumed case: replays the earlier attempt
        self._requests_seen.add(rkey)
        reused = res.reused and not replay
        if not reused:  # a cached repeat of an identical request is not a new search of the agent's own
            self.searches += 1
        flagged = [h.chunk_id for h in res.hits if h.injection_flagged]
        if flagged:
            self.log(LogEventType.TRAP_INJECTION, f"{self.agent.value} retrieved flagged paragraph(s) {', '.join(flagged)}; "
                     "instruction text withheld from the agent", {"query": req.query}, flagged)
        blocks = [self._hit_block(h) for h in res.hits]
        head = (f"search {req.query!r} filters={ {k: v for k, v in f.model_dump(mode='json').items() if v not in (None, False)} }"
                f" -> {len(res.hits)} hit(s){' (reused identical earlier query)' if reused else ''}")
        if not res.hits:
            head += "\n" + self._empty_search_hint(f)
        return ToolOutcome("search", True, head + "\n" + "\n".join(blocks), refs=[h.chunk_id for h in res.hits])

    @staticmethod
    def _hit_block(h) -> str:
        fl = list(h.damage) + (["injection-flagged"] if h.injection_flagged else [])
        fl += [f"possible-duplicate-of:{d}" for d in h.possible_duplicate_of]
        fl += [f"corrected-by:{d}" for d in h.corrected_by] + [f"corrects:{d}" for d in h.corrects]
        title = f"[{h.title}] " if h.title else ""
        return wrap_document(h.doc_id, title + h.text, ref=h.paragraph_ref, tier=h.reliability_tier,
                             date_=h.pub_date, source=h.source_name, source_type=h.source_type, flags=fl)

    def _empty_search_hint(self, f: SearchFilters) -> str:
        """Why a filtered search found nothing: which filter matches no in-window document, and the
        values that do exist (read from the evidence itself, so it works for any pack)."""
        from ragnarok.retrieval.index import passes

        active = {k: v for k, v in f.model_dump().items() if v not in (None, False, []) and k != "include_duplicates"}
        if not active:
            return "[no paragraph matched this query]"
        chunks = [c for c in self.service.index.chunks if passes(c, SearchFilters(), self.ctx.as_of)]
        values = {"country": {(c.country or "").lower() for c in chunks if c.country},
                  "sector": {(c.sector or "").lower() for c in chunks if c.sector} | {s for c in chunks for s in c.table_sectors},
                  "event_id": {(c.event_id or "none").lower() for c in chunks},
                  "source_type": {c.source_type.lower() for c in chunks if c.source_type}}
        notes = []
        for k, v in active.items():
            if not any(passes(c, SearchFilters(**{k: v}), self.ctx.as_of) for c in chunks):
                known = ", ".join(sorted(values[k])[:40]) if k in values else "?"
                notes.append(f"filter {k}={v} matches no document available as of {self.ctx.as_of}"
                             + (f" (values that exist: {known})" if k in values else ""))
        if not notes:
            notes.append("each filter matches some documents, but their combination matches none; drop or relax filters")
        return "[no hits: " + "; ".join(notes) + "]"

    def _tool_read_doc(self, req: ToolRequest) -> ToolOutcome:
        if not req.doc_id:
            raise ValueError("read_doc needs doc_id")
        v = self.service.read_doc(req.doc_id, self.ctx.as_of, self.agent, req.paragraphs or None, **self._cid())
        if v.status != "ok":
            return ToolOutcome("read_doc", False, f"read_doc {req.doc_id}: {v.status} ({v.reason})", error=v.status)
        flagged = [f"{v.doc_id}#{p.ref}" for p in v.paragraphs if p.injection_flagged]
        if flagged:
            self.log(LogEventType.TRAP_INJECTION, f"{self.agent.value} read flagged paragraph(s) {', '.join(flagged)}; "
                     "instruction text withheld", {}, flagged)
        fl = v.damage + v.relations
        body = "\n".join(f"[{p.ref}] {p.text}" for p in v.paragraphs)
        text = wrap_document(v.doc_id, f"[{v.title}]\n{body}", tier=v.reliability_tier, date_=v.pub_date,
                             source=v.source_name or "", source_type=v.source_type or "", flags=fl)
        extra = f" missing refs: {v.missing_refs}" if v.missing_refs else ""
        return ToolOutcome("read_doc", True, f"read_doc {req.doc_id}{extra}\n{text}",
                           refs=[f"{v.doc_id}#{p.ref}" for p in v.paragraphs])

    def _tool_get_trade_rows(self, req: ToolRequest) -> ToolOutcome:
        q = TradeQuery(origin=req.origin or None, destination=req.destination or None, sector=req.sectors or None,
                       table_ids=req.table_ids or None, row_ids=req.row_ids or None,
                       period_from=req.period_from or None, period_to=req.period_to or None)
        res = self.service.get_trade_rows(q, self.ctx.as_of, self.agent, **self._cid())
        docs = {r.source_doc_id for r in res.rows}
        meta = {d: self.service.store.get_document(d).meta for d in docs}
        lines = []
        by_table: dict[str, list] = {}
        for r in res.rows:
            by_table.setdefault(r.table_id, []).append(r)
        for tid, rows in by_table.items():
            m = meta[rows[0].source_doc_id]
            body = [f"table {tid}: {rows[0].origin} -> {rows[0].destination}, {rows[0].sector}"]
            for r in rows:
                val = f"{r.value} {r.currency} M" if r.value is not None else "MISSING"
                vol = f"{r.volume:g} {r.volume_unit}" if r.volume is not None else "MISSING"
                status = "valid" if r.status == RowStatus.VALID else f"INVALID ({r.status.value}: {r.damage_reason})"
                warn = f" warning: {'; '.join(r.warnings)}" if r.warnings else ""
                # the source sentence is what a row citation's quote must match; scanned like any document text
                src = evidence_text(r.raw_text, scan_text(r.raw_text)) or r.raw_text
                body.append(f"{r.row_id} | {r.period} | value {val} | volume {vol} | {status}{warn}\n"
                            f"    source text (quote this when citing {r.row_id}): \"{src}\"")
            lines.append(wrap_document(m.doc_id, "\n".join(body), tier=m.reliability_tier, date_=m.pub_date,
                                       source=m.source_name, source_type=m.source_type))
        note = ""
        if res.blocked:
            note += f" blocked (after as_of): {len(res.blocked)} row(s)."
        if res.not_found:
            note += f" not found: {res.not_found}."
        return ToolOutcome("get_trade_rows", True, f"get_trade_rows -> {len(res.rows)} row(s).{note}\n" + "\n".join(lines),
                           refs=[r.row_id for r in res.rows])

    def _tool_trade_calc(self, req: ToolRequest) -> ToolOutcome:
        calc = self.service.calculator(self.ctx.as_of)
        a, b, fld = req.row_ids, req.row_ids_b, (req.field or "value").lower()
        op = req.calc_op.strip().lower()
        if op not in CalcOp.__args__ or not a:
            raise ValueError(f"trade_calc needs calc_op (one of {', '.join(CalcOp.__args__)}) and row_ids")
        if fld not in ("value", "volume"):
            raise ValueError('field must be "value" or "volume"')
        if op == "sum":
            rec = calc.sum(a, fld)
        elif op == "mean":
            rec = calc.mean(a, fld)
        elif op in ("yoy_change", "yoy_pct_change"):
            rec = calc.yoy_change(a, b, fld, percent=op == "yoy_pct_change")
        elif op == "share":
            rec = calc.share(a, b, req.denominator_label or "", fld)
        elif op in ("period_change", "period_pct_change"):
            if len(a) != 2:
                raise ValueError("period_change needs row_ids [from, to]")
            rec = calc.period_change(a[0], a[1], fld, percent=op == "period_pct_change")
        else:
            rec = calc.net_offset(a, b, fld)
        self.service.save_calculation(rec, self.ctx.case_id)
        self.log(LogEventType.RETRIEVED,
                 f"{self.agent.value} trade_calc {op}: result {rec.result} {rec.unit} ({rec.calc_id})",
                 {"tool": "trade_calc", "calc": json.loads(rec.model_dump_json())}, [rec.calc_id] + [i.row_id for i in rec.inputs if i.row_id])
        excl = "; ".join(f"{k}: {v}" for k, v in rec.excluded_rows.items())
        text = (f"trade_calc {rec.calc_id}: {rec.operation} -> result {rec.result} {rec.unit}"
                f" | formula: {rec.formula} | inputs: {', '.join(i.row_id for i in rec.inputs if i.row_id)}"
                + (f" | denominator: {rec.parameters.get('denominator')}" if "denominator" in rec.parameters else "")
                + (f" | EXCLUDED: {excl}" if excl else "") + (f" | {rec.notes}" if rec.notes else ""))
        return ToolOutcome("trade_calc", rec.result is not None, text,
                           refs=[rec.calc_id] + [i.row_id for i in rec.inputs if i.row_id])

    def _tool_validate_citation(self, req: ToolRequest) -> ToolOutcome:
        if not req.doc_id or not req.quote:
            raise ValueError("validate_citation needs doc_id and quote")
        cit = self.to_citation(CitationDraft(doc_id=req.doc_id, paragraph_ref=req.paragraph_ref, row_id=req.row_id,
                                             quote=req.quote), require_retrieved=False)
        if isinstance(cit, str):
            return ToolOutcome("validate_citation", False, f"validate_citation: {cit}")
        chk = validate_citation(self.service.store, cit, self.ctx.as_of)
        return ToolOutcome("validate_citation", chk.ok, f"validate_citation {req.doc_id}: "
                           + ("valid" if chk.ok else "; ".join(chk.issues)))

    # -------------------------------------------------------- citations ---

    def ref_key(self, d: CitationDraft) -> str:
        return d.row_id if d.row_id else f"{d.doc_id}#{d.paragraph_ref}"

    def to_citation(self, d: CitationDraft, require_retrieved: bool = True) -> Citation | str:
        """A validated Citation, or a string saying why it is unusable."""
        store = self.service.store
        doc = store.get_document(d.doc_id)
        if doc is None or doc.meta.pub_date is None:
            return f"{d.doc_id}: no such dated document"
        if not d.paragraph_ref and not d.row_id:
            return f"{d.doc_id}: citation needs a paragraph ref or row ID"
        if require_retrieved and self.ref_key(d) not in self.retrieved:
            return f"{self.ref_key(d)}: not retrieved by {self.agent.value} in this case"
        try:
            cit = Citation(doc_id=d.doc_id, paragraph_ref=d.paragraph_ref or None, row_id=d.row_id or None,
                           pub_date=doc.meta.pub_date, quote=d.quote[:400] or "(empty)")
        except ValueError as exc:
            return f"{d.doc_id}: {exc}"
        chk = validate_citation(store, cit, self.ctx.as_of)
        return cit if chk.ok else f"{self.ref_key(d)}: " + "; ".join(chk.issues)

    def citations(self, drafts: list[CitationDraft]) -> tuple[list[Citation], list[str]]:
        good, bad = [], []
        for d in drafts:
            c = self.to_citation(d)
            (bad.append(c) if isinstance(c, str) else good.append(c))
        return good, bad

    def report_injections(self, reports: list[InjectionReport]) -> None:
        for r in reports:
            ref = f"{r.doc_id}#{r.paragraph_ref}" if r.paragraph_ref else r.doc_id
            self.log(LogEventType.TRAP_INJECTION, f"{self.agent.value} reported an injection attempt in {ref}: {r.description}"[:500],
                     {"reported_by": self.agent.value}, [ref])

    # ------------------------------------------------------- evidence text ---

    def evidence_text(self) -> str:
        parts, size = [], 0
        for o in reversed(self.outcomes):  # newest first within the budget, then restore order
            if size + len(o.text) > MAX_EVIDENCE_CHARS:
                parts.append("[older tool results omitted for length]")
                break
            parts.append(o.text)
            size += len(o.text)
        return "\n\n".join(reversed(parts)) or "(no evidence retrieved yet)"


# --------------------------------------------------------------------------- #
# Research loop
# --------------------------------------------------------------------------- #


def describe_request(r: ToolRequest) -> str:
    """Canonical one-line form of a tool request, used to compare plans."""
    if r.tool == "search":
        f = {k: v for k, v in (("countries", r.countries), ("sectors", r.sectors), ("event_ids", r.event_ids),
                               ("source_types", r.source_types), ("max_reliability", r.max_reliability)) if v}
        return f"search {normalise_query(r.query)!r} {json.dumps(f, sort_keys=True) if f else ''}".strip()
    if r.tool == "read_doc":
        return f"read_doc {r.doc_id} {','.join(r.paragraphs) or 'all'}"
    if r.tool == "get_trade_rows":
        return (f"get_trade_rows tables={','.join(r.table_ids)} rows={','.join(r.row_ids)} {r.origin}->{r.destination} "
                f"{','.join(r.sectors)} {r.period_from}..{r.period_to}")
    if r.tool == "trade_calc":
        return f"trade_calc {r.calc_op} {r.field} a={','.join(r.row_ids)} b={','.join(r.row_ids_b)}"
    return f"{r.tool} {r.doc_id} {r.paragraph_ref or r.row_id}"


def log_memory_effect(env: AgentEnv, lessons: list[MemoryEntry], original: list[ToolRequest] | None,
                      changed: list[ToolRequest], used_ids: list[str], effect: str, label: str,
                      baseline_kind: str = "separate") -> bool:
    """Log whether recalled lessons changed what the agent did. `original` is the plan the
    agent made WITHOUT its memory (None when no baseline was taken). Influence is recorded
    as MEMORY_APPLIED only when the agent attributes its plan to specific recalled lessons
    and (with a baseline) the plan actually differs; everything else is logged as such."""
    known = {m.memory_id: m for m in lessons}
    used = [i for i in dict.fromkeys(used_ids) if i in known]
    unknown = [i for i in used_ids if i not in known]
    chg = [describe_request(r) for r in changed]
    orig = [describe_request(r) for r in original] if original is not None else None
    added = [x for x in chg if orig is not None and x not in orig]
    removed = [x for x in (orig or []) if x not in chg]
    payload = {"label": label, "baseline": original is not None,
               "baseline_kind": baseline_kind if original is not None else "none", "original_action": orig, "changed_action": chg,
               "added": added, "removed": removed, "memory_used": memory_payload([known[i] for i in used]),
               "agent_stated_effect": effect[:600], "unknown_memory_ids": unknown}
    if used and (orig is None or added or removed):
        env.log(LogEventType.MEMORY_APPLIED,
                f"{env.agent.value} {label}: lesson(s) {', '.join(used)} changed the plan"
                + (f" vs the no-memory baseline (+{len(added)} / -{len(removed)} request(s))" if orig is not None
                   else " (agent-stated; no baseline)") + (f": {effect}" if effect else ""), payload, used)
        return True
    why = ("the plan matched the no-memory baseline" if used else
           "the agent attributed nothing to memory" + (" (its plan still differed from the baseline)" if added or removed else ""))
    env.log(LogEventType.MEMORY_READ, f"{env.agent.value} {label}: recalled lessons did not change the plan ({why})",
            payload, [m.memory_id for m in lessons])
    return False


def plan_with_memory(env: AgentEnv, system: str, user: str, lessons: list[MemoryEntry], effort: str, label: str,
                     schema=ResearchTurn, schema_m=MemoryResearchTurn, schema_dual=DualResearchTurn, to_requests=None,
                     baseline_requests=None, validate=None, essential=None, baseline: bool = True):
    """First planning step with memory, and the logged difference to a no-memory plan.

    MEMORY_BASELINE_MODE=combined (default): ONE call whose schema holds both the plan
    without memory (recorded, never executed) and the executed plan. separate: an extra
    baseline call without the lessons first (the older, costlier path). Baseline off (or
    baseline=False): the plan with memory only; influence is then agent-stated."""
    llm = env.ctx.llm
    st = env.ctx.settings
    to_requests = to_requests or (lambda t: t.to_requests())
    baseline_requests = baseline_requests or (lambda t: t.plan_without_memory.to_requests())
    want = baseline and st.memory_baseline
    mem_user = (f"{render_lessons(lessons)}\n\n{user}\n\nYour memory is listed above. If a lesson applies, let it shape "
                "your requests and name its ID in memory_used, saying in memory_effect what it changed; otherwise leave "
                "memory_used empty.")
    if want and st.memory_baseline_mode == "combined":
        mem_user += (" Also fill the no-memory plan field with the requests you would make if you had NO memory at all "
                     "(it is recorded for comparison and never executed).")
        turn = llm.structured(env.agent, system, mem_user, schema_dual, effort=effort, validate=validate,
                              essential=essential, label=f"{label} with memory (+ no-memory plan)", allow_residual=True)
        log_memory_effect(env, lessons, baseline_requests(turn), to_requests(turn), turn.memory_used, turn.memory_effect,
                          label, baseline_kind="combined")
        return turn
    plan0 = None
    if want:
        plan0 = llm.structured(env.agent, system, user, schema, effort=effort, validate=validate, essential=essential,
                               label=f"{label} baseline without memory", allow_residual=True)
    turn = llm.structured(env.agent, system, mem_user, schema_m, effort=effort, validate=validate, essential=essential,
                          label=f"{label} with memory", allow_residual=True)
    log_memory_effect(env, lessons, to_requests(plan0) if plan0 is not None else None, to_requests(turn),
                      turn.memory_used, turn.memory_effect, label, baseline_kind="separate" if plan0 is not None else "none")
    return turn


def run_requests(env: AgentEnv, requests: list[ToolRequest]) -> bool:
    """Execute tool requests in code (permission- and budget-checked). False = budget exhausted."""
    for req in requests:
        try:
            env.run_tool(req)
        except ToolPermissionError as exc:
            env.outcomes.append(ToolOutcome(req.tool, False, f"[refused by the system: {exc}]", error="permission"))
        except LimitHit:
            env.outcomes.append(ToolOutcome(req.tool, False, "[tool budget exhausted; finish with the evidence you have]",
                                            error="limit"))
            return False
    return True


def research(env: AgentEnv, system: str, task: str, context: str, rounds: int, min_searches: int = 0,
             effort: str = "medium", label: str = "research", lessons: list[MemoryEntry] | None = None,
             memory_baseline: bool = True) -> None:
    """Up to `rounds` planning turns of agent-chosen tool requests (at most
    MAX_REQUESTS_PER_ROUND each), executed in code; one extra turn only while the
    required own searches are unmet. With `lessons`, the first turn is planned with
    the agent's memory (see plan_with_memory)."""
    llm = env.ctx.llm
    cap = env.ctx.settings.max_requests_per_round
    r = 0
    extra_round_used = False
    while r < rounds or (env.searches < min_searches and not extra_round_used):
        if r >= rounds:
            extra_round_used = True
        must = (f"\nYou have made {env.searches} search(es); at least {min_searches} search(es) in total is required "
                "before you can finish." if env.searches < min_searches else "")
        only = (" This is your only planning turn: request everything you need now (searches, reads, trade rows, and "
                "trade_calc on rows already shown above)." if rounds == 1 and r == 0 else "")
        user = (f"{context}\n\n<task>\n{task}\n</task>\n\n<evidence_so_far>\n{env.evidence_text()}\n</evidence_so_far>\n\n"
                f"Research round {r + 1} of {rounds}. Request up to {cap} tool calls "
                f"(permitted: {', '.join(sorted(TOOL_PERMISSIONS[env.agent]))}), or set done=true when you have enough "
                f"evidence.{only}{must}")
        if r == 0 and lessons:
            turn = plan_with_memory(env, system, user, lessons, effort, f"{label} round 1", baseline=memory_baseline)
        else:
            turn = llm.structured(env.agent, system, user, ResearchTurn, effort=effort, label=f"{label} round {r + 1}")
        r += 1
        requests = turn.to_requests()[:cap]
        if not requests and (turn.done and env.searches >= min_searches):
            break
        if not run_requests(env, requests):
            return
        if turn.done and env.searches >= min_searches:
            break
