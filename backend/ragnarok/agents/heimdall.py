"""Heimdall: question + as_of -> Case File, with event verification."""

from __future__ import annotations

from dataclasses import dataclass, field

from ragnarok.agents.common import AgentEnv, load_prompt, research
from ragnarok.agents.schemas import HeimdallReport
from ragnarok.models import AgentName, CaseFile, Citation, EventStatus, LogEventType

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
    research(env, system, TASK, context, ctx.settings.max_research_rounds, min_searches=1,
             effort=ctx.settings.effort_advocate, label="heimdall research")

    def validate(r: HeimdallReport) -> list[str]:
        problems = []
        if not r.countries:
            problems.append("countries must not be empty")
        good, bad = env.citations(r.event_citations)
        problems += [f"invalid event citation {b}" for b in bad]
        if r.event_status != "uncertain" and not good:
            problems.append(f"event_status '{r.event_status}' needs at least one valid event citation")
        return problems

    user = (f"{context}\n\n<task>\n{TASK}\n</task>\n\n<evidence>\n{env.evidence_text()}\n</evidence>\n\n"
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
