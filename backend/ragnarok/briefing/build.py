"""Briefing built from Odin's rulings and verified evidence only (Markdown + JSON).

Nothing here comes from the advocates' raw arguments except what Odin ruled on:
findings are the ruled claims grouped by verdict, with their citations;
advocates' ranges appear only in the exposure table, labelled as theirs.

Every citation is re-validated against the store at build time (document /
paragraph / row exists, quote matches, published on or before as_of) and every
estimate's calculation provenance is replayed (calc records exist, are complete,
reproduce from the source rows, and the bounds equal their results). Anything
that fails is dropped, listed in the briefing and returned for the audit log;
it is never shown as valid. An estimate that cannot be justified is shown as
unavailable with the reason.
"""

from __future__ import annotations

from ragnarok.agents.estimates import bound_problems, load_calcs
from ragnarok.agents.odin import OdinResult
from ragnarok.models import (
    AgentName,
    Briefing,
    BriefingFinding,
    CaseFile,
    Citation,
    Claim,
    ExposureEstimate,
    ExposureRow,
    Outlook,
    RunSummary,
    SourceRef,
    Verdict,
)
from ragnarok.retrieval.citations import validate_citation
from ragnarok.store.db import Store


def cite(c: Citation) -> str:
    loc = c.row_id if c.row_id else f"{c.doc_id} {c.paragraph_ref}"
    return f"[{loc}, {c.pub_date}]"


def _rng(e: ExposureEstimate | None, why: str | None = None) -> str:
    if e is None:
        return f"unavailable ({why})" if why else "—"
    return f"{e.low:,.1f} – {e.high:,.1f} {e.unit}"


def check_citations(store: Store, cits: list[Citation], as_of, where: str) -> tuple[list[Citation], list[dict]]:
    good, dropped = [], []
    for c in cits:
        chk = validate_citation(store, c, as_of)
        if chk.ok:
            good.append(c)
        else:
            dropped.append({"where": where, "ref": c.row_id or f"{c.doc_id}#{c.paragraph_ref}", "issues": chk.issues})
    return good, dropped


def estimate_problems(store: Store, calc, e: ExposureEstimate) -> list[str]:
    """Calculation provenance: records exist, replay identically from in-window rows, bounds match."""
    probs = bound_problems(store, e.low, e.high, e.unit, e.calculation_ids)
    recs, _ = load_calcs(store, e.calculation_ids)
    if calc is not None:
        for cid, r in recs.items():
            ok, why = calc.verify(r)
            if not ok:
                probs.append(f"calc {cid} does not replay from the source rows: {why}")
    return probs


def build_briefing(store: Store, cf: CaseFile, claims: list[Claim], odin: OdinResult, concessions: dict,
                   notes: list[str], traps: list[str], runs_completed: int = 1, runs: list[RunSummary] | None = None,
                   superseded: list[str] | None = None, final_run: int | None = None,
                   calc=None) -> tuple[Briefing, str, list[dict]]:
    """Returns (briefing, markdown, dropped); `dropped` lists every citation or estimate removed
    by the build-time checks (the caller logs them)."""
    as_of = cf.as_of
    dropped: list[dict] = []
    by_claim = {c.claim_id: c for c in claims}
    sections: dict[Verdict, list[BriefingFinding]] = {v: [] for v in Verdict}
    unverifiable: list[str] = []
    for r in odin.rulings:
        c = by_claim[r.claim_id]
        text = c.text
        con = concessions.get(c.claim_id)
        if con is not None and con.partial and con.revised_claim_text:
            text = f"{c.text} — revised after partial concession: {con.revised_claim_text}"
        cits, bad = check_citations(store, c.citations or r.supporting_citations, as_of, f"claim {c.claim_id}")
        dropped += bad
        if not cits:
            unverifiable.append(f"{c.claim_id} ({r.verdict.value}): no citation passed the build-time check; not shown "
                                "as a finding")
            continue
        sections[r.verdict].append(BriefingFinding(claim_id=c.claim_id, ruling_id=r.ruling_id, verdict=r.verdict,
                                                   claim_type=r.claim_type, text=text, citations=cits))
    event_cits, bad = check_citations(store, cf.event_citations, as_of, "event verification")
    dropped += bad

    pairs = sorted({(x.lower(), y.lower()) for x in cf.countries for y in (cf.sectors or ["all"])}
                   | {(e.country.lower(), e.sector.lower()) for c in claims if (e := c.exposure)}
                   | {(e.country.lower(), e.sector.lower()) for e in odin.ranges})
    verdict_of = {r.claim_id: r.verdict.value for r in odin.rulings}
    rows = []
    for country, sector in pairs:
        unavailable: dict[str, str] = {}

        def pick(agent: AgentName):
            hits = [(c, c.exposure) for c in claims if c.agent == agent and c.exposure
                    and c.exposure.country.lower() == country and c.exposure.sector.lower() == sector]
            hits.sort(key=lambda h: -h[0].run_number)  # the latest run's estimate
            if hits:
                return hits[0]
            removed = [c for c in claims if c.agent == agent and (c.country or "").lower() == country
                       and (c.sector or "").lower() == sector and any("estimate removed by code" in x for x in c.limitations)]
            unavailable[agent.value] = ("estimate removed by code: numbers not reproducible from calc records" if removed
                                        else f"no estimate submitted by {agent.value} for this pair")
            return None, None

        tc, te = pick(AgentName.THOR)
        lc, le = pick(AgentName.LOKI)
        oe = next((e for e in odin.ranges if e.country.lower() == country and e.sector.lower() == sector), None)
        ins = next((i for i in odin.insufficient if i["country"].lower() == country and i["sector"] == sector), None)
        if oe is None:
            unavailable["odin"] = ("insufficient evidence: " + "; ".join(ins["missing_data"])[:200] if ins
                                   else "Odin gave no range for this pair")
        est = {"thor": te, "loki": le, "odin": oe}
        for who, e in list(est.items()):
            if e is None:
                continue
            probs = estimate_problems(store, calc, e)
            if probs:
                dropped.append({"where": f"{who} estimate {country}/{sector}", "ref": ",".join(e.calculation_ids),
                                "issues": probs})
                unavailable[who] = "calculation provenance failed: " + "; ".join(probs)[:200]
                est[who] = None
        note = []
        if tc:
            note.append(f"Thor {tc.claim_id}: {verdict_of.get(tc.claim_id, 'unruled')}")
        if lc:
            note.append(f"Loki {lc.claim_id}: {verdict_of.get(lc.claim_id, 'unruled')}")
        display_country = next((x for x in cf.countries if x.lower() == country), country.title())
        rows.append(ExposureRow(country=display_country, sector=sector, thor=est["thor"], loki=est["loki"],
                                odin=est["odin"], unavailable=unavailable, note="; ".join(note)))

    findings = sum(sections.values(), [])
    cited = sorted({c.doc_id for f in findings for c in f.citations} | {c.doc_id for c in event_cits})
    sources = []
    for d in cited:
        doc = store.get_document(d)
        if doc and doc.meta.pub_date:
            m = doc.meta
            sources.append(SourceRef(doc_id=d, title=m.title, pub_date=m.pub_date, pub_time=m.pub_time,
                                     source_name=m.source_name, reliability_tier=m.reliability_tier))

    assumptions = [f"{f.claim_id} ({f.claim_type.value}): {a}" for f in findings for a in by_claim[f.claim_id].assumptions]
    uncertainty = []
    for r in rows:
        for who, e in (("Thor", r.thor), ("Loki", r.loki), ("Odin", r.odin)):
            if e is not None:
                assumptions += [f"{who} {r.country}/{r.sector} estimate: {a}" for a in e.assumptions]
                uncertainty.append(f"{who} {r.country}/{r.sector}: confidence {e.confidence.value}"
                                   + (f" — {e.uncertainty_note}" if e.uncertainty_note else ""))

    missing = [f"{m.description} (why: {m.why_needed})" for m in odin.missing] + [
        f"{i['country']}/{i['sector']}: {'; '.join(i['missing_data'])}" for i in odin.insufficient]
    if not odin.sufficient:
        missing.insert(0, f"Odin judged the evidence insufficient: {odin.sufficiency_reason}")
    failures = list(notes) + [f"code guard: {g}" for g in odin.guards] + [f"unruled claim: {u}" for u in odin.unruled]
    failures += unverifiable
    dropped_txt = [f"{d['where']}: {d['ref']} — {'; '.join(d['issues'])[:200]}" for d in dropped]
    # incomplete: Odin still judged the evidence insufficient when the trial ended (run limit reached,
    # no genuinely new evidence, or nothing specific to send back); partial: sufficient but with
    # failures, unchallenged sides, unruled claims or dropped citations.
    if not odin.sufficient:
        status = "incomplete"
    elif odin.unruled or notes or dropped or unverifiable:
        status = "partial"
    else:
        status = "complete"
    if status == "complete" and missing and cf.event_status.value == "uncertain":
        status = "partial"
    summary = odin.executive_summary if len(odin.executive_summary) >= 20 else odin.executive_summary + " (summary not provided)"
    b = Briefing(
        case_id=cf.case_id, as_of=as_of, status=status, runs_completed=runs_completed, executive_summary=summary,
        event_status=cf.event_status, event_citations=event_cits, established=sections[Verdict.ESTABLISHED],
        contested=sections[Verdict.CONTESTED], conceded=sections[Verdict.CONCEDED], rejected=sections[Verdict.REJECTED],
        exposure_table=rows, outlook=Outlook(text=odin.outlook_text if len(odin.outlook_text) >= 10 else odin.outlook_text + " (no outlook)",
                                             assumptions=odin.outlook_assumptions or ["no assumptions stated by Odin"]),
        sources=sources, missing_data_notes=missing, evidence_quality_notes=odin.evidence_quality_notes,
        traps_and_failures=traps + failures, assumptions=assumptions, uncertainty=uncertainty,
        dropped_citations=dropped_txt, runs=runs or [], superseded=superseded or [],
    )
    return b, to_markdown(b, cf, odin, final_run), dropped


def _metric(r: ExposureRow) -> str:
    e = r.odin or r.thor or r.loki
    if e is None:
        return "—"
    return f"{e.metric} ({e.unit}, {e.period}" + (f", per {e.denominator}" if e.denominator else "") + ")"


def to_markdown(b: Briefing, cf: CaseFile, odin: OdinResult, final_run: int | None = None) -> str:
    L = [f"# Intelligence briefing — case {b.case_id}", "",
         f"**Question:** {cf.question}  ", f"**As of:** {b.as_of}  ", f"**Status:** {b.status.upper()} "
         f"(runs completed: {b.runs_completed}{f'; findings from the run {final_run} rulings' if final_run else ''})", ""]
    if b.status == "incomplete":
        L += [f"> This briefing is **INCOMPLETE**: Odin judged the evidence insufficient after {b.runs_completed} run(s). "
              "See *Investigation runs* and *Missing data*.", ""]
    elif b.status != "complete":
        L += ["> This briefing is **not complete**: see *Missing data* and *Traps, corrections and failures*.", ""]
    L += ["## Executive summary", "", b.executive_summary, ""]
    L += ["## Event verification", "", f"**Status: {b.event_status.value}** — {cf.event_verification_notes}", ""]
    L += [f"- {c.doc_id} {c.paragraph_ref or c.row_id}: “{c.quote}” {cite(c)}" for c in b.event_citations]
    if cf.corrections:
        L += ["", "Corrections / contradictions noted by Heimdall:"] + [f"- {x}" for x in cf.corrections]
    L.append("")
    titles = (("Established findings", b.established), ("Contested findings", b.contested),
              ("Conceded findings", b.conceded), ("Rejected claims", b.rejected))
    rationale = {r.claim_id: r.rationale for r in odin.rulings}
    for title, items in titles:
        L += [f"## {title}", ""]
        if not items:
            L += ["_None._", ""]
            continue
        for f in items:
            L.append(f"- **{f.claim_id}** ({f.claim_type.value}) {f.text} " + " ".join(cite(c) for c in f.citations))
            L.append(f"  - *Odin:* {rationale.get(f.claim_id, '')}")
        L.append("")
    L += ["## Exposure", "", "Separate ranges from each side and from Odin's ruling; Odin's range is not an average.", "",
          "| Country | Sector | Metric (unit, period, denominator) | Thor (high case) | Loki (limited case) | Odin (ruling) | Notes |",
          "|---|---|---|---|---|---|---|"]
    for r in b.exposure_table:
        u = r.unavailable
        L.append(f"| {r.country} | {r.sector} | {_metric(r)} | {_rng(r.thor, u.get('thor'))} | {_rng(r.loki, u.get('loki'))} "
                 f"| {_rng(r.odin, u.get('odin'))} | {r.note} |")
    L.append("")
    for r in b.exposure_table:
        for who, e in (("Thor", r.thor), ("Loki", r.loki), ("Odin", r.odin)):
            if e is None:
                continue
            L.append(f"- **{who} — {r.country}/{r.sector}:** {e.metric}: {e.metric_definition}. Unit {e.unit}, period {e.period}"
                     + (f", denominator {e.denominator}" if e.denominator else "") + f". Calculations: {', '.join(e.calculation_ids)}"
                     f" (rows {', '.join(e.trade_row_refs[:8])}{'…' if len(e.trade_row_refs) > 8 else ''}). "
                     f"Confidence: {e.confidence.value}." + (f" Missing: {'; '.join(e.missing_data)}." if e.missing_data else ""))
    L += ["", "## Assumptions and uncertainty", ""] + [f"- {a}" for a in b.assumptions or ["No assumptions stated."]]
    L += [f"- Uncertainty: {u}" for u in b.uncertainty]
    if b.runs:
        L += ["", "## Investigation runs", ""]
        for r in b.runs:
            counts: dict[str, int] = {}
            for v in r.verdicts.values():
                counts[v] = counts.get(v, 0) + 1
            L.append(f"- **Run {r.run_number}:** " + (f"{len(r.verdicts)} claim(s) ruled "
                     f"({', '.join(f'{k} {n}' for k, n in sorted(counts.items()))}); " if r.verdicts else "no rulings; ")
                     + (f"Odin: {'sufficient' if r.sufficient else 'insufficient'}. " if r.sufficient is not None else "")
                     + (f"New evidence: {', '.join(r.new_evidence)}. " if r.new_evidence else "")
                     + (f"Sent back for: {'; '.join(r.sendback_missing)}. " if r.sendback_missing else "")
                     + (f"Notes: {r.note}" if r.note else ""))
        if b.superseded:
            L += ["", "Superseded claims (replaced or withdrawn in a later run; not in the findings above):"]
            L += [f"- {x}" for x in b.superseded]
    L += ["", "## Next-quarter outlook", "", b.outlook.text, "", "Assumptions:"] + [f"- {a}" for a in b.outlook.assumptions]
    L += ["", "## Missing data and evidence quality", ""] + [f"- {m}" for m in b.missing_data_notes or ["None noted."]]
    L += [f"- {n}" for n in b.evidence_quality_notes]
    L += ["", "## Traps, corrections and failures", ""] + [f"- {t}" for t in b.traps_and_failures or ["None recorded."]]
    if b.dropped_citations:
        L += ["", "Dropped at build time (failed the citation / calculation-provenance check; not used above):"]
        L += [f"- {d}" for d in b.dropped_citations]
    L += ["", "## Sources", "", "All sources are Runemark documents from the ingested evidence packs.", ""]
    L += [f"- {s.doc_id} — {s.title} — {s.source_name} (tier {s.reliability_tier}), {s.pub_date}"
          f"{' ' + s.pub_time.strftime('%H:%M') if s.pub_time else ''}" for s in b.sources]
    return "\n".join(L) + "\n"
