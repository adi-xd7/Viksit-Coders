"""Shared agent machinery: prompts, document wrapping, code-enforced tool
permissions and budgets, the research loop, and citation conversion.

Security properties enforced here (not in prompts):
- Each agent can only run the tools in TOOL_PERMISSIONS[agent].
- Every tool runs with the case's as_of; no request field can change it.
- Tool calls are counted per agent and per case; over budget -> LIMIT_HIT.
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

from ragnarok.agents.schemas import CalcOp, CitationDraft, InjectionReport, ResearchTurn, ToolRequest
from ragnarok.config import Settings
from ragnarok.ingest.injection import evidence_text, scan_text
from ragnarok.llm.client import LimitHit, LLMClient
from ragnarok.models import AgentName, Citation, LogEvent, LogEventType, RowStatus
from ragnarok.retrieval.citations import validate_citation
from ragnarok.retrieval.service import RetrievalService
from ragnarok.retrieval.types import SearchFilters, TradeQuery

PROMPTS = Path(__file__).parent / "prompts"

TOOL_PERMISSIONS: dict[AgentName, frozenset[str]] = {
    AgentName.HEIMDALL: frozenset({"search", "read_doc", "get_trade_rows"}),
    AgentName.THOR: frozenset({"search", "read_doc", "get_trade_rows", "trade_calc"}),
    AgentName.LOKI: frozenset({"search", "read_doc", "get_trade_rows", "trade_calc"}),
    AgentName.ODIN: frozenset({"read_doc", "trade_calc", "validate_citation"}),
}
MAX_REQUESTS_PER_ROUND = 5
MAX_EVIDENCE_CHARS = 60_000


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
    tool_calls: dict[str, int] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)

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
        try:
            self.ctx.count_tool_call(self.agent)
        except LimitHit as exc:
            self.log(LogEventType.LIMIT_HIT, f"{self.agent.value}: {exc}", {"what": exc.what, "used": exc.used, "limit": exc.limit})
            raise
        try:
            out = getattr(self, f"_tool_{req.tool}")(req)
        except (ValueError, KeyError, TypeError) as exc:
            out = ToolOutcome(req.tool, False, f"[tool error: {exc}]", error=str(exc))
        self.outcomes.append(out)
        self.retrieved.update(out.refs)
        return out

    def _cid(self) -> dict[str, Any]:
        return {"case_id": self.ctx.case_id, "run_number": self.ctx.run_number}

    def _tool_search(self, req: ToolRequest) -> ToolOutcome:
        if not req.query:
            raise ValueError("search needs a query")
        f = SearchFilters(country=req.countries, sector=req.sectors, event_id=req.event_ids, source_type=req.source_types,
                          max_reliability=req.max_reliability if 1 <= req.max_reliability <= 4 else None)
        res = self.service.search(req.query, self.ctx.as_of, self.agent, f, **self._cid())
        self.searches += 1
        flagged = [h.chunk_id for h in res.hits if h.injection_flagged]
        if flagged:
            self.log(LogEventType.TRAP_INJECTION, f"{self.agent.value} retrieved flagged paragraph(s) {', '.join(flagged)}; "
                     "instruction text withheld from the agent", {"query": req.query}, flagged)
        blocks = []
        for h in res.hits:
            fl = list(h.damage) + (["injection-flagged"] if h.injection_flagged else [])
            fl += [f"possible-duplicate-of:{d}" for d in h.possible_duplicate_of]
            fl += [f"corrected-by:{d}" for d in h.corrected_by] + [f"corrects:{d}" for d in h.corrects]
            title = f"[{h.title}] " if h.title else ""
            blocks.append(wrap_document(h.doc_id, title + h.text, ref=h.paragraph_ref, tier=h.reliability_tier,
                                        date_=h.pub_date, source=h.source_name, source_type=h.source_type, flags=fl))
        head = (f"search {req.query!r} filters={ {k: v for k, v in f.model_dump(mode='json').items() if v not in (None, False)} }"
                f" -> {len(res.hits)} hit(s){' (reused identical earlier query)' if res.reused else ''}")
        return ToolOutcome("search", True, head + "\n" + "\n".join(blocks), refs=[h.chunk_id for h in res.hits])

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


def research(env: AgentEnv, system: str, task: str, context: str, rounds: int, min_searches: int = 0,
             effort: str = "medium", label: str = "research") -> None:
    """Up to `rounds` rounds of agent-chosen tool requests, executed in code."""
    llm = env.ctx.llm
    r = 0
    extra_round_used = False
    while r < rounds or (env.searches < min_searches and not extra_round_used):
        if r >= rounds:
            extra_round_used = True
        must = (f"\nYou have made {env.searches} search(es); at least {min_searches} of your own search(es) is required "
                "before you can finish." if env.searches < min_searches else "")
        user = (f"{context}\n\n<task>\n{task}\n</task>\n\n<evidence_so_far>\n{env.evidence_text()}\n</evidence_so_far>\n\n"
                f"Research round {r + 1} of {rounds}. Request up to {MAX_REQUESTS_PER_ROUND} tool calls "
                f"(permitted: {', '.join(sorted(TOOL_PERMISSIONS[env.agent]))}), or set done=true when you have enough "
                f"evidence.{must}")
        turn = llm.structured(env.agent, system, user, ResearchTurn, effort=effort, label=f"{label} round {r + 1}")
        r += 1
        requests = turn.to_requests()[:MAX_REQUESTS_PER_ROUND]
        if not requests and (turn.done and env.searches >= min_searches):
            break
        for req in requests:
            try:
                env.run_tool(req)
            except ToolPermissionError as exc:
                env.outcomes.append(ToolOutcome(req.tool, False, f"[refused by the system: {exc}]", error="permission"))
            except LimitHit:
                env.outcomes.append(ToolOutcome(req.tool, False, "[tool budget exhausted; finish with the evidence you have]",
                                                error="limit"))
                return
        if turn.done and env.searches >= min_searches:
            break
