"""Heimdall: question + as_of -> Case File, with event verification."""

from __future__ import annotations

from dataclasses import dataclass, field

from ragnarok.agents.common import AgentEnv, load_prompt, plan_with_memory, research
from ragnarok.llm.client import LimitHit
from ragnarok.agents.schemas import HeimdallReport, ResearchFindings, SendBackPlan, SendBackPlanM
from ragnarok.memory.store import render_lessons
from ragnarok.models import AgentName, CaseFile, Citation, EventStatus, LogEventType, RelationType, SendBack
from ragnarok.retrieval.text import normalise_query, normalise_quote

TASK = (
    "Build the Case File for the question: identify countries, sectors, commodities, routes and candidate event IDs; "
    "search event reports, official notices, corrections and trade notes; verify whether the event is established, "
    "disproved or uncertain as of the as-of date, with reasons and citations; note corrections, retractions, "
    "contradictions and rumours; list relevant trade table IDs (trade notes use the document ID as table ID) and the "
    "data still missing for an exposure estimate."
)


@dataclass
class HeimdallOutcome:
    case_file: CaseFile
    report: HeimdallReport
    dropped: list[str] = field(default_factory=list)  # invalid citations / IDs removed by code


def case_context(question: str, as_of) -> str:
    return f"<case>\nQuestion: {question}\nAs-of date: {as_of}\n</case>"


def run_heimdall(env: AgentEnv) -> HeimdallOutcome:
    ctx = env.ctx
    system = load_prompt(AgentName.HEIMDALL)
    context = case_context(ctx.question, ctx.as_of)
    lessons = env.recall(["research"], "the investigation")
    research(env, system, TASK, context, ctx.settings.max_research_rounds, min_searches=1,
             effort=ctx.settings.effort_advocate, label="heimdall research", lessons=lessons)

    def validate(r: HeimdallReport) -> list[str]:
        problems = []
        if not r.countries:
            problems.append("countries must not be empty")
        good, bad = env.citations(r.event_citations)
        problems += [f"invalid event citation {b}" for b in bad]
        if r.event_status != "uncertain" and not good:
            problems.append(f"event_status '{r.event_status}' needs at least one valid event citation")
        return problems

    user = (f"{context}\n\n{render_lessons(lessons)}\n\n<task>\n{TASK}\n</task>\n\n<evidence>\n{env.evidence_text()}\n</evidence>\n\n"
            "Write the Case File report now. Cite only paragraphs or trade rows shown in the evidence above.")
    report = ctx.llm.structured(AgentName.HEIMDALL, system, user, HeimdallReport, effort=ctx.settings.effort_advocate,
                                validate=validate, label="heimdall report", allow_residual=True)
    env.report_injections(report.injection_reports)

    good, bad = env.citations(report.event_citations)
    dropped = [f"event citation dropped: {b}" for b in bad]
    status = EventStatus(report.event_status)
    notes = report.status_reasons
    if status != EventStatus.UNCERTAIN and not good:
        dropped.append(f"event status '{status.value}' had no valid citation; downgraded to 'uncertain' by code")
        status, notes = EventStatus.UNCERTAIN, notes + " [code guard: no valid citation for the stated status]"

    store = env.service.store
    tables = []
    for t in report.trade_table_ids:
        tab = store.get_trade_table(t)
        if tab is None:
            dropped.append(f"trade table {t} does not exist")
            continue
        src = store.get_document(tab.source_doc_id)
        if src is None or src.meta.pub_date is None or src.meta.pub_date > ctx.as_of:
            dropped.append(f"trade table {t} is outside the as_of window")
            continue
        tables.append(t)
    docs = []
    for d in report.key_doc_ids:
        doc = store.get_document(d)
        if doc and doc.meta.pub_date and doc.meta.pub_date <= ctx.as_of:
            docs.append(d)
        else:
            dropped.append(f"key document {d} unknown or outside the as_of window")

    corrections = [f"{c.doc_id} {c.relation}{' of ' + c.about_doc_id if c.about_doc_id else ''}: {c.note}"
                   for c in report.corrections]
    cf = CaseFile(
        case_id=ctx.case_id, question=ctx.question, as_of=ctx.as_of, countries=report.countries,
        sectors=[s.lower() for s in report.sectors], related_countries=report.related_countries, commodities=[c.lower() for c in report.commodities],
        routes=report.routes, candidate_event_ids=report.candidate_event_ids, event_status=status,
        event_verification_notes=notes, event_citations=[c for c in good if isinstance(c, Citation)],
        evidence_doc_ids=sorted(set(docs)), trade_table_ids=sorted(set(tables)), missing_data=report.missing_data,
        corrections=corrections, run_number=ctx.run_number,
    )
    for msg in dropped:
        env.log(LogEventType.ERROR, f"heimdall output corrected by code: {msg}")
    env.log(LogEventType.CASE_FILE, f"Case File: event {status.value}; countries {', '.join(cf.countries)}; "
            f"sectors {', '.join(cf.sectors)}; {len(cf.trade_table_ids)} trade table(s)",
            {"case_file": cf.model_dump(mode="json")}, [f"{c.doc_id}#{c.paragraph_ref or c.row_id}" for c in cf.event_citations])
    return HeimdallOutcome(case_file=cf, report=report, dropped=dropped)


def render_case_file(cf: CaseFile) -> str:
    cites = "; ".join(f"{c.doc_id}/{c.paragraph_ref or c.row_id} ({c.pub_date}): \"{c.quote}\"" for c in cf.event_citations)
    return (
        "<case_file>\n"
        f"Question: {cf.question}\nAs-of date: {cf.as_of}\nCountries asked about: {', '.join(cf.countries)}\n"
        f"Sectors asked about: {', '.join(cf.sectors)}\nRelated countries: {', '.join(cf.related_countries) or 'none'}\n"
        f"Exposure pairs to estimate: {'; '.join(f'{c}/{s}' for c in cf.countries for s in cf.sectors)}\nCommodities: {', '.join(cf.commodities)}\nRoutes: {'; '.join(cf.routes)}\n"
        f"Candidate event IDs: {', '.join(cf.candidate_event_ids)}\n"
        f"Event status (Heimdall): {cf.event_status.value} - {cf.event_verification_notes}\n"
        f"Event citations: {cites or 'none'}\n"
        f"Corrections/contradictions: {' | '.join(cf.corrections) or 'none noted'}\n"
        f"Relevant trade tables: {', '.join(cf.trade_table_ids) or 'none listed'}\n"
        f"Key documents: {', '.join(cf.evidence_doc_ids) or 'none listed'}\n"
        f"Missing data: {' | '.join(cf.missing_data) or 'none listed'}\n"
        "</case_file>"
    )


# --------------------------------------------------------------------------- #
# Send-back research (run n >= 2)
# --------------------------------------------------------------------------- #


@dataclass
class ResearchItem:
    number: int
    description: str
    queries: list[dict] = field(default_factory=list)  # executed targeted searches {query, filters}
    status: str = "not_found"  # Heimdall's reading: found | partial | not_found
    summary: str = ""
    new_refs: list[str] = field(default_factory=list)  # genuinely new (code-verified)
    new_doc_ids: list[str] = field(default_factory=list)
    not_new: list[dict] = field(default_factory=list)  # cited but not new: {ref, reason}


@dataclass
class SendBackOutcome:
    case_file: CaseFile
    items: list[ResearchItem]
    new_evidence: list[dict]  # one record per new ref (with run number)
    refused_queries: list[dict] = field(default_factory=list)
    still_missing: list[str] = field(default_factory=list)

    @property
    def has_new_evidence(self) -> bool:
        return bool(self.new_evidence)


def _render_sendback(sb: SendBack) -> str:
    lines = [f"Odin judged the evidence insufficient after run {sb.run_number}: {sb.reason}", "Missing evidence:"]
    for i, m in enumerate(sb.missing, 1):
        extra = "; ".join(x for x in (f"countries: {', '.join(m.countries)}" if m.countries else "",
                                      f"sectors: {', '.join(m.sectors)}" if m.sectors else "",
                                      f"source types: {', '.join(m.source_types)}" if m.source_types else "") if x)
        lines.append(f"{i}. {m.description} (why needed: {m.why_needed}){' [' + extra + ']' if extra else ''}")
    return "<sendback>\n" + "\n".join(lines) + "\n</sendback>"


class Novelty:
    """Decides whether a ref is genuinely new relative to everything seen in earlier runs."""

    def __init__(self, store, seen_refs: set[str]) -> None:
        self.store = store
        self.seen_refs = set(seen_refs)
        self.seen_docs = {r.split("#", 1)[0] for r in seen_refs if "#" in r}
        self.seen_texts = {t for t in (self._text(r) for r in seen_refs) if t}

    def _text(self, ref: str) -> str | None:
        if "#R" in ref:
            row = self.store.get_trade_row(ref)
            return normalise_quote(row.raw_text) if row else None
        if "#" not in ref:
            return None
        d, p = ref.split("#", 1)
        para = self.store.get_paragraph(d, p)
        if para is None:
            return None
        return normalise_quote(para.evidence_text if para.evidence_text is not None else para.text)

    def why_not_new(self, ref: str) -> str | None:
        if ref in self.seen_refs:
            return "already retrieved in an earlier run"
        doc_id = ref.split("#", 1)[0]
        doc = self.store.get_document(doc_id)
        if doc is None:
            return "unknown document"
        dup_types = (RelationType.DUPLICATE_OF.value, RelationType.NEAR_DUPLICATE_OF.value)
        for rel in doc.relations:
            if rel.target_doc_id in self.seen_docs and rel.type.value in dup_types:
                return f"{rel.type.value} {rel.target_doc_id}, which was seen in an earlier run"
        for src, typ, _ in self.store.incoming_relations(doc_id):
            if src in self.seen_docs and typ in dup_types:
                return f"{src} (seen in an earlier run) is a {typ} this document"
        t = self._text(ref)
        if t and t in self.seen_texts:
            return "same text as evidence seen in an earlier run"
        return None


def _new_record(run: int, it: ResearchItem, ref: str, doc, quote: str) -> dict:
    m = doc.meta
    return {"run_number": run, "missing_item": it.number, "missing": it.description, "ref": ref, "doc_id": m.doc_id,
            "kind": "trade_row" if "#R" in ref else "paragraph", "pub_date": m.pub_date.isoformat() if m.pub_date else None,
            "tier": m.reliability_tier, "source_type": m.source_type, "title": m.title, "quote": quote[:300]}


def run_sendback_research(env: AgentEnv, cf: CaseFile, sb: SendBack, earlier_queries: set[str],
                          seen_refs: set[str]) -> SendBackOutcome:
    """New targeted searches for each missing item, then a code check that what Heimdall
    cites is genuinely new (not seen in earlier runs, not a duplicate)."""
    ctx = env.ctx
    store = env.service.store
    system = load_prompt(AgentName.HEIMDALL)
    env.forbidden_queries |= earlier_queries
    n_items = len(sb.missing)
    k = ctx.settings.max_sendback_queries_per_item
    context = (f"{render_case_file(cf)}\n\n{_render_sendback(sb)}\n\n<earlier_queries>\n"
               + "\n".join(f"- {q}" for q in sorted(earlier_queries)) + "\n</earlier_queries>")
    task = (f"Run {ctx.run_number}: for EACH missing item (1-{n_items}) write 1-{k} NEW targeted searches that could find "
            "that evidence (different wording, filters or source types from every earlier query listed). Do not repeat "
            "an earlier query. If an item is unlikely to exist in the evidence, still try one well-targeted search.")
    user = f"{context}\n\n<task>\n{task}\n</task>"

    def validate(p: SendBackPlan) -> list[str]:
        probs, seen = [], set()
        for s in p.searches:
            qn = normalise_query(s.query)
            if not 1 <= s.missing_item <= n_items:
                probs.append(f"search {s.query!r}: missing_item must be 1-{n_items}")
            if qn in earlier_queries:
                probs.append(f"search {s.query!r} repeats an earlier query; write a new one")
            if qn in seen:
                probs.append(f"search {s.query!r} appears twice in the plan")
            seen.add(qn)
        covered = {s.missing_item for s in p.searches}
        probs += [f"no search for missing item {i}" for i in range(1, n_items + 1) if i not in covered]
        return probs

    lessons = env.recall(["sendback", "research"], "the send-back research plan")
    if lessons:
        plan = plan_with_memory(env, system, user, lessons, ctx.settings.effort_advocate, "heimdall send-back plan",
                                schema=SendBackPlan, schema_m=SendBackPlanM,
                                to_requests=lambda p: [s.to_request() for s in p.searches], validate=validate)
    else:
        plan = ctx.llm.structured(AgentName.HEIMDALL, system, user, SendBackPlan, effort=ctx.settings.effort_advocate,
                                  validate=validate, label="heimdall send-back plan", allow_residual=True)

    items = [ResearchItem(number=i, description=m.description) for i, m in enumerate(sb.missing, 1)]
    refused, per_item, planned, accepted = [], {i: 0 for i in range(1, n_items + 1)}, set(), []
    for s in plan.searches:
        qn = normalise_query(s.query)
        reason = ("missing_item out of range" if not 1 <= s.missing_item <= n_items else
                  "repeats an earlier query" if qn in earlier_queries else
                  "duplicate within the plan" if qn in planned else
                  f"more than {k} searches for this item" if per_item[s.missing_item] >= k else None)
        if reason:
            refused.append({"query": s.query, "missing_item": s.missing_item, "reason": reason})
            env.log(LogEventType.ERROR, f"send-back query refused by code ({reason}): {s.query}", {"search": s.model_dump()})
            continue
        planned.add(qn)
        per_item[s.missing_item] += 1
        accepted.append(s)
    env.log(LogEventType.RESEARCH_PLAN, f"Heimdall run {ctx.run_number} plan: {len(accepted)} new targeted search(es) for "
            f"{n_items} missing item(s); {len(refused)} refused",
            {"searches": [s.model_dump() for s in accepted], "refused": refused, "sendback_id": sb.sendback_id})
    for s in accepted:
        try:
            out = env.run_tool(s.to_request())
        except LimitHit:
            break
        if out.ok:
            items[s.missing_item - 1].queries.append({"query": s.query, "filters": {
                "countries": s.countries, "sectors": s.sectors, "event_ids": s.event_ids, "source_types": s.source_types,
                "max_reliability": s.max_reliability}})

    research(env, system, "Follow up the targeted search results: read the most relevant documents and fetch trade rows "
             "that could fill the missing items. Any search must be a new query.", context, 1,
             effort=ctx.settings.effort_advocate, label="heimdall send-back follow-up")

    def validate_findings(f: ResearchFindings) -> list[str]:
        p = []
        nums = {x.missing_item for x in f.findings}
        p += [f"no finding for missing item {i}" for i in range(1, n_items + 1) if i not in nums]
        for x in f.findings:
            good, bad = env.citations(x.citations)
            p += [f"item {x.missing_item}: invalid citation {b}" for b in bad]
            if x.status != "not_found" and not good:
                p.append(f"item {x.missing_item}: status {x.status} needs a valid citation of the evidence found")
        return p

    fuser = (f"{context}\n\n<task>\nReport, for each missing item, what the new research found. Cite the evidence you "
             "found (paragraphs or trade rows shown below); status not_found if nothing relevant was found. An empty "
             "search is not proof that something did not happen.\n</task>\n\n<evidence>\n" + env.evidence_text()
             + "\n</evidence>")
    findings = ctx.llm.structured(AgentName.HEIMDALL, system, fuser, ResearchFindings, effort=ctx.settings.effort_advocate,
                                  validate=validate_findings, label="heimdall send-back findings", allow_residual=True)
    env.report_injections(findings.injection_reports)

    nov = Novelty(store, seen_refs)
    new_evidence: list[dict] = []
    new_tables: list[str] = []
    for x in findings.findings:
        if not 1 <= x.missing_item <= n_items:
            continue
        it = items[x.missing_item - 1]
        it.status, it.summary = x.status, x.summary
        good, _ = env.citations(x.citations)
        for c in good:
            ref = c.row_id or f"{c.doc_id}#{c.paragraph_ref}"
            why = nov.why_not_new(ref)
            if why:
                it.not_new.append({"ref": ref, "reason": why})
            elif ref not in it.new_refs:
                it.new_refs.append(ref)
                it.new_doc_ids.append(c.doc_id)
                new_evidence.append(_new_record(ctx.run_number, it, ref, store.get_document(c.doc_id), c.quote))
        for t in x.trade_table_ids:
            tab = store.get_trade_table(t)
            if tab is None or t in cf.trade_table_ids or t in new_tables:
                continue
            src = store.get_document(tab.source_doc_id)
            rows = [r.row_id for r in tab.rows]
            got = [r for r in rows if r in env.retrieved]  # only rows Heimdall actually retrieved (as_of-gated)
            if src is None or not got or any(r in seen_refs for r in rows) or nov.why_not_new(got[0]):
                continue
            new_tables.append(t)
            for r in got:
                if r not in it.new_refs:
                    it.new_refs.append(r)
                    it.new_doc_ids.append(tab.source_doc_id)
                    row = store.get_trade_row(r)
                    new_evidence.append(_new_record(ctx.run_number, it, r, src, row.raw_text if row else ""))
    for it in items:
        for nn in it.not_new:
            env.log(LogEventType.NEW_EVIDENCE, f"run {ctx.run_number} item {it.number}: {nn['ref']} is NOT new evidence "
                    f"({nn['reason']})", {"phase": "rejected", "item": it.number, **nn}, [nn["ref"]])
        if it.new_refs:
            env.log(LogEventType.NEW_EVIDENCE, f"run {ctx.run_number} item {it.number} ({it.status}): {len(it.new_refs)} new "
                    f"ref(s) for '{it.description[:120]}': {', '.join(it.new_refs[:8])}",
                    {"phase": "found", "item": it.number, "missing": it.description, "summary": it.summary,
                     "queries": it.queries, "evidence": [e for e in new_evidence if e["missing_item"] == it.number]},
                    it.new_refs)
    env.log(LogEventType.NEW_EVIDENCE, f"run {ctx.run_number}: {len(new_evidence)} genuinely new evidence ref(s) for "
            f"{sum(1 for it in items if it.new_refs)} of {n_items} missing item(s)"
            + ("" if new_evidence else " - no genuinely new evidence"),
            {"phase": "summary", "count": len(new_evidence), "items": [it.__dict__ for it in items],
             "new_tables": new_tables}, [e["ref"] for e in new_evidence])

    new_docs = {e["doc_id"] for e in new_evidence}
    cf2 = cf.model_copy(update={
        "run_number": ctx.run_number, "evidence_doc_ids": sorted(set(cf.evidence_doc_ids) | new_docs),
        "trade_table_ids": sorted(set(cf.trade_table_ids) | set(new_tables)),
        "missing_data": findings.still_missing or [it.description for it in items if not it.new_refs]})
    env.log(LogEventType.CASE_FILE, f"Case File updated for run {ctx.run_number}: +{len(new_docs)} document(s), "
            f"+{len(new_tables)} trade table(s)", {"case_file": cf2.model_dump(mode="json")}, sorted(new_docs))
    return SendBackOutcome(case_file=cf2, items=items, new_evidence=new_evidence, refused_queries=refused,
                           still_missing=cf2.missing_data)


def render_new_evidence(out: SendBackOutcome) -> str:
    lines = []
    for it in out.items:
        lines.append(f"Missing item {it.number}: {it.description} -> Heimdall: {it.status}. {it.summary}")
        for e in (x for x in out.new_evidence if x["missing_item"] == it.number):
            lines.append(f"  NEW {e['ref']} ({e['source_type']}, tier {e['tier']}, {e['pub_date']}): \"{e['quote'][:200]}\"")
    return "<new_evidence>\n" + "\n".join(lines) + "\n</new_evidence>"
