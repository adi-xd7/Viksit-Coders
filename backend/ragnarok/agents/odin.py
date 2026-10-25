"""Odin: code pre-checks, rulings on every claim, own exposure ranges, sufficiency.

Code guards applied to Odin's output (after one repair attempt):
- every claim gets exactly one ruling; a claim Odin did not rule on is reported as unruled;
- "conceded" only where the proponent conceded; a full concession is always "conceded";
- "established" is impossible for a claim with hard pre-check failures (invalid or
  post-as_of citations, tier-4-only support, corrected-only support, unreproducible
  calculations, support from flagged instruction text) -> "rejected [code guard]";
- range bounds must equal results of complete calc records, else the range is
  recorded as insufficient evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ragnarok.agents.advocates import CrossExam, render_claims
from ragnarok.agents.common import AgentEnv, load_prompt, research, wrap_document
from ragnarok.agents.estimates import bound_problems, calc_row_refs, load_calcs, norm_unit
from ragnarok.agents.heimdall import render_case_file
from ragnarok.agents.schemas import OdinAssessment, OdinJudgment, OdinRange, OdinRulings
from ragnarok.memory.store import render_lessons
from ragnarok.models import (
    DAMAGE_KINDS,
    AgentName,
    CaseFile,
    Citation,
    Claim,
    ClaimType,
    Confidence,
    ExposureEstimate,
    LogEventType,
    MissingEvidence,
    RelationType,
    Ruling,
    Verdict,
)
from ragnarok.retrieval.citations import validate_claim
from ragnarok.store.db import Store


@dataclass
class Precheck:
    claim_id: str
    valid_citations: int
    issues: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    hard_fail: list[str] = field(default_factory=list)

    def render(self) -> str:
        parts = [f"valid citations: {self.valid_citations}"]
        if self.hard_fail:
            parts.append("HARD FAILURES (cannot be established): " + "; ".join(self.hard_fail))
        if self.issues:
            parts.append("issues: " + "; ".join(self.issues))
        if self.flags:
            parts.append("flags: " + "; ".join(self.flags))
        return " | ".join(parts)


def precheck(store: Store, calc, claim: Claim, as_of) -> Precheck:
    chk = validate_claim(store, calc, claim, as_of)
    pc = Precheck(claim_id=claim.claim_id, valid_citations=sum(1 for c in chk.citations[: len(claim.citations)] if c.ok))
    for c, r in zip(claim.citations, chk.citations):
        if not r.ok:
            pc.issues += [f"{c.doc_id}/{c.paragraph_ref or c.row_id}: {i}" for i in r.issues]
    pc.issues += chk.calc_issues
    tiers, corrected_only = [], True
    for c in claim.citations:
        doc = store.get_document(c.doc_id)
        if doc is None:
            continue
        tiers.append(doc.meta.reliability_tier)
        if doc.is_exact_duplicate:
            canon = next(r.target_doc_id for r in doc.relations if r.type == RelationType.DUPLICATE_OF)
            pc.flags.append(f"{c.doc_id} is an exact duplicate of {canon}")
        dmg = sorted({f.kind.value for f in doc.damage_flags if f.kind in DAMAGE_KINDS})
        if dmg:
            pc.flags.append(f"{c.doc_id} is damaged ({', '.join(dmg)})")
        if c.paragraph_ref and any(f.paragraph_ref == c.paragraph_ref and f.severity == "high" for f in doc.injection_flags):
            # a quote overlapping the flagged span is already an invalid citation (validator)
            pc.flags.append(f"{c.doc_id}/{c.paragraph_ref} also contains flagged embedded-instruction text")
        corr = [src for src, t, _ in store.incoming_relations(c.doc_id) if t in ("corrects", "retracts")
                and (d := store.get_document(src)) and d.meta.pub_date and d.meta.pub_date <= as_of]
        if corr:
            pc.flags.append(f"{c.doc_id} is corrected/retracted by {', '.join(corr)}")
        else:
            corrected_only = False
        if c.row_id:
            row = store.get_trade_row(c.row_id)
            if row and row.status.value != "valid":
                pc.flags.append(f"{c.row_id} is an invalid trade row ({row.status.value})")
    if pc.valid_citations == 0:
        pc.hard_fail.append("no valid citation")
    if tiers and all(t == 4 for t in tiers):
        pc.hard_fail.append("all support comes from tier-4 sources")
    if claim.citations and corrected_only:
        pc.hard_fail.append("all cited documents were later corrected or retracted")
    if claim.exposure is not None and chk.calc_issues:
        pc.hard_fail.append("estimate calculations do not reproduce")
    if any("after as_of" in i for i in pc.issues):
        pc.hard_fail.append("cites a document published after as_of")
    return pc


@dataclass
class OdinResult:
    rulings: list[Ruling]
    ranges: list[ExposureEstimate]
    insufficient: list[dict]  # country/sector ranges Odin (or code) marked insufficient
    sufficient: bool
    sufficiency_reason: str
    missing: list[MissingEvidence]
    executive_summary: str
    outlook_text: str
    outlook_assumptions: list[str]
    evidence_quality_notes: list[str]
    prechecks: dict[str, Precheck]
    guards: list[str] = field(default_factory=list)  # code corrections applied to Odin's output
    unruled: list[str] = field(default_factory=list)


def _evidence_for(store: Store, claims: list[Claim]) -> str:
    """The cited passages themselves, wrapped, so Odin can judge support."""
    seen, blocks = set(), []
    for c in claims:
        for x in c.citations:
            key = (x.doc_id, x.paragraph_ref, x.row_id)
            if key in seen:
                continue
            seen.add(key)
            doc = store.get_document(x.doc_id)
            if doc is None:
                continue
            if x.paragraph_ref:
                p = doc.paragraph(x.paragraph_ref)
                text = (p.evidence_text if p and p.evidence_text is not None else p.text) if p else "(paragraph not found)"
                ref = x.paragraph_ref
            else:
                row = store.get_trade_row(x.row_id)
                text = (f"{row.row_id} | {row.period} | value {row.value} {row.currency} M | volume {row.volume} "
                        f"{row.volume_unit} | {row.status.value}") if row else "(row not found)"
                ref = x.row_id.split("#")[-1]
            blocks.append(wrap_document(x.doc_id, f"[{doc.meta.title}] {text}", ref=ref, tier=doc.meta.reliability_tier,
                                        date_=doc.meta.pub_date, source=doc.meta.source_name,
                                        source_type=doc.meta.source_type))
    return "\n".join(blocks)


def _calcs_text(store: Store, calc, claims: list[Claim]) -> str:
    """Every calc record the claims rely on, replayed by code, so Odin can judge and reuse them."""
    ids = list(dict.fromkeys(i for c in claims for i in c.calculation_ids + (c.exposure.calculation_ids if c.exposure else [])))
    recs, missing = load_calcs(store, ids)
    lines = [f"{cid}: does not exist" for cid in missing]
    for cid, r in recs.items():
        ok, why = calc.verify(r)
        excl = "; ".join(f"{k}: {v}" for k, v in r.excluded_rows.items())
        lines.append(f"{cid}: {r.operation} = {r.result} {r.unit} | {r.formula} | rows {', '.join(i.row_id for i in r.inputs if i.row_id)}"
                     + (f" | denominator: {r.parameters['denominator']}" if r.parameters.get("denominator") not in (None, "n/a") else "")
                     + (f" | EXCLUDED: {excl}" if excl else "") + f" | complete: {r.complete}"
                     + f" | replay from source rows: {'OK' if ok else 'FAILED - ' + why}")
    return "\n".join(lines) or "(no calculations cited)"


def _cross_exam_text(cx: CrossExam) -> str:
    lines = []
    for a in cx.attacks:
        lines.append(f"[{a.attack_id}] {a.attacker.value} attacks {a.target_claim_id}: {a.objection} (why: {a.why_it_matters})"
                     + (f" gap: {a.evidence_gap}" if a.evidence_gap else "")
                     + "".join(f" | counter: {c.doc_id}/{c.paragraph_ref or c.row_id} \"{c.quote}\"" for c in a.counter_evidence))
    for d in cx.defenses:
        lines.append(f"[{d.defense_id}] {d.defender.value} defends {d.claim_id} vs {d.attack_id} with NEW evidence: {d.argument}"
                     + "".join(f" | new: {c.doc_id}/{c.paragraph_ref or c.row_id} \"{c.quote}\"" for c in d.new_evidence))
    for c in cx.concessions:
        lines.append(f"[{c.concession_id}] {c.agent.value} CONCEDES {c.claim_id} ({'partial' if c.partial else 'full'}) vs "
                     f"{c.attack_id}: {c.reason}" + (f" | revised claim: {c.revised_claim_text}" if c.revised_claim_text else ""))
    for i in cx.invalid_defenses:
        lines.append(f"[invalid defense] {i.agent.value} on {i.claim_id} vs {i.attack_id}: {i.reason}; the attack stands undefended")
    lines += [f"[unanswered] attack {a} received no response" for a in cx.unanswered]
    lines += [f"[cross-exam failure] {f}" for f in cx.failures]
    return "\n".join(lines) or "(no cross-examination took place)"


def run_odin(env: AgentEnv, cf: CaseFile, claims: list[Claim], cx: CrossExam, notes: list[str],
             run_history: str = "") -> OdinResult:
    ctx = env.ctx
    store = env.service.store
    calc = env.service.calculator(ctx.as_of)
    system = load_prompt(AgentName.ODIN)
    pcs = {c.claim_id: precheck(store, calc, c, ctx.as_of) for c in claims}
    for c in claims:
        env.log(LogEventType.PRECHECK, f"pre-check {c.claim_id}: {pcs[c.claim_id].render()}"[:500],
                {"precheck": pcs[c.claim_id].__dict__}, [c.claim_id])
    claim_ids = [c.claim_id for c in claims]
    full_concession = {k.claim_id for k in cx.concessions if not k.partial}
    any_concession = {k.claim_id: k for k in cx.concessions}
    pairs = sorted({(country, sector) for country in cf.countries for sector in (cf.sectors or ["all"])})
    advocates_est = "\n".join(
        f"{c.agent.value} {c.claim_id}: {e.country}/{e.sector} {e.metric} {e.low}..{e.high} {e.unit} ({e.period}); calcs "
        f"{', '.join(e.calculation_ids)}" for c in claims if (e := c.exposure)) or "(none)"
    context = (
        f"{render_case_file(cf)}\n\n<claims>\n"
        + "\n".join(f"{render_claims([c])}\n  PRE-CHECK: {pcs[c.claim_id].render()}" for c in claims)
        + f"\n</claims>\n\n<cited_evidence>\n{_evidence_for(store, claims)}\n</cited_evidence>\n\n"
        f"<cross_examination>\n{_cross_exam_text(cx)}\n</cross_examination>\n\n"
        f"<advocate_estimates>\n{advocates_est}\n</advocate_estimates>\n\n"
        f"<calculations>\n{_calcs_text(store, calc, claims)}\n</calculations>\n\n"
        f"<trial_notes>\n{chr(10).join(notes) or 'none'}\n</trial_notes>"
        + (f"\n\n<run_history>\n{run_history}\n</run_history>" if run_history else "")
    )
    lessons = env.recall(["ruling"], f"ruling in run {ctx.run_number}")
    if lessons:
        context += "\n\n" + render_lessons(lessons)
    task = ("Rule on every claim (IDs: " + ", ".join(claim_ids) + "). Give your own exposure range for each of these "
            "country/sector pairs: " + "; ".join(f"{a}/{b}" for a, b in pairs) + " (or mark insufficient). Assess "
            "sufficiency. Request read_doc / trade_calc / validate_citation if you need to check passages or compute "
            "your range bounds.")
    # Odin's prompt is large, so no baseline plan: memory influence is recorded as agent-stated.
    research(env, system, task, context, 1, effort=ctx.settings.effort_judge, label="odin research", lessons=lessons,
             memory_baseline=False)

    def range_probs(r: OdinRange) -> list[str]:
        if r.insufficient_evidence:
            return [] if r.missing_data else [f"range {r.country}/{r.sector}: insufficient ranges must list missing data"]
        return [f"range {r.country}/{r.sector}: {p}" for p in bound_problems(store, r.low, r.high, r.unit, r.calc_ids)]

    def validate_rulings(j: OdinRulings) -> list[str]:
        p = []
        ruled = [r.claim_id for r in j.rulings]
        p += [f"no ruling for claim {c}" for c in claim_ids if c not in ruled]
        p += [f"unknown claim {c}" for c in ruled if c not in claim_ids]
        p += [f"claim {c} ruled more than once" for c in set(ruled) if ruled.count(c) > 1]
        for r in j.rulings:
            if r.claim_id not in pcs:
                continue
            if r.verdict == "conceded" and r.claim_id not in any_concession:
                p.append(f"{r.claim_id}: 'conceded' requires a recorded concession by the proponent; there is none")
            if r.claim_id in full_concession and r.verdict != "conceded":
                p.append(f"{r.claim_id}: the proponent fully conceded; the verdict must be 'conceded'")
            if r.verdict == "established" and pcs[r.claim_id].hard_fail:
                p.append(f"{r.claim_id}: cannot be established ({'; '.join(pcs[r.claim_id].hard_fail)})")
            if len(r.rationale.strip()) < 20:
                p.append(f"{r.claim_id}: rationale too short")
        return p

    def validate_assessment(a: OdinAssessment) -> list[str]:
        covered = {(x.country.lower(), x.sector.lower()) for x in a.ranges}
        p = [f"no range (or insufficient marker) for {x}/{y}" for x, y in pairs if (x.lower(), y.lower()) not in covered]
        for r in a.ranges:
            p += range_probs(r)
        return p

    # Call 1: rulings. Call 2: ranges, sufficiency and summary, given the rulings.
    # (Two calls keep each structured-output grammar small enough for the API.)
    base = f"{context}\n\n<task>\n{task}\n</task>\n\n<odin_checks>\n{env.evidence_text()}\n</odin_checks>"
    jr = ctx.llm.structured(AgentName.ODIN, system, base + "\n\nStep 1 of 2: give your ruling on every claim now.",
                            OdinRulings, effort=ctx.settings.effort_judge, validate=validate_rulings,
                            label="odin rulings", allow_residual=True)
    env.report_injections(jr.injection_reports)
    ruled_text = "\n".join(f"{r.claim_id}: {r.verdict} ({r.claim_type}) - {r.rationale}" for r in jr.rulings)
    ja = ctx.llm.structured(AgentName.ODIN, system, f"{base}\n\n<your_rulings>\n{ruled_text}\n</your_rulings>\n\n"
                            "Step 2 of 2: from your rulings and the trade data, give your exposure ranges, sufficiency "
                            "assessment, executive summary and next-quarter outlook.",
                            OdinAssessment, effort=ctx.settings.effort_judge, validate=validate_assessment,
                            label="odin assessment", allow_residual=True)
    j = OdinJudgment(rulings=jr.rulings, injection_reports=jr.injection_reports, **ja.model_dump())

    guards: list[str] = []
    rulings: list[Ruling] = []
    done: set[str] = set()
    for r in j.rulings:
        if r.claim_id not in pcs or r.claim_id in done:
            continue
        done.add(r.claim_id)
        pc = pcs[r.claim_id]
        verdict, rationale = Verdict(r.verdict), r.rationale
        if r.claim_id in full_concession and verdict != Verdict.CONCEDED:
            guards.append(f"{r.claim_id}: verdict {verdict.value} -> conceded (proponent fully conceded)")
            verdict, rationale = Verdict.CONCEDED, f"[code guard: proponent conceded] {rationale}"
        if verdict == Verdict.CONCEDED and r.claim_id not in any_concession:
            guards.append(f"{r.claim_id}: 'conceded' without a concession -> contested")
            verdict, rationale = Verdict.CONTESTED, f"[code guard: no concession recorded] {rationale}"
        if verdict == Verdict.ESTABLISHED and pc.hard_fail:
            guards.append(f"{r.claim_id}: 'established' blocked by pre-check ({'; '.join(pc.hard_fail)}) -> rejected")
            verdict, rationale = Verdict.REJECTED, f"[code guard: {'; '.join(pc.hard_fail)}] {rationale}"
        sup = [c for c in (env.to_citation(x, require_retrieved=False) for x in r.supporting_citations) if isinstance(c, Citation)]
        con = [c for c in (env.to_citation(x, require_retrieved=False) for x in r.contradicting_citations) if isinstance(c, Citation)]
        ruling = Ruling(ruling_id=f"R-{r.claim_id}", run_number=ctx.run_number, claim_id=r.claim_id, verdict=verdict,
                        claim_type=ClaimType(r.claim_type), rationale=rationale if len(rationale) >= 20 else rationale + " (no detail)",
                        citations_valid=not pc.issues and pc.valid_citations > 0, citation_issues=pc.issues,
                        supporting_citations=sup, contradicting_citations=con,
                        concession_id=any_concession[r.claim_id].concession_id if verdict == Verdict.CONCEDED else None)
        rulings.append(ruling)
        env.log(LogEventType.RULING, f"{r.claim_id}: {verdict.value} ({ruling.claim_type.value}) - {rationale}"[:500],
                {"ruling": ruling.model_dump(mode="json")}, [r.claim_id])
    unruled = [c for c in claim_ids if c not in done]
    for c in unruled:
        env.log(LogEventType.ERROR, f"Odin gave no ruling on {c}; reported as unruled (no verdict invented)", refs=[c])

    ranges, insufficient = [], []
    for r in j.ranges:
        probs = range_probs(r)
        if r.insufficient_evidence or probs:
            if probs:
                guards.append(f"range {r.country}/{r.sector} marked insufficient: {'; '.join(probs)[:200]}")
            insufficient.append({"country": r.country, "sector": r.sector.lower(), "metric": r.metric,
                                 "missing_data": r.missing_data or ["range bounds not reproducible from calc records"],
                                 "rationale": r.rationale, "code_issues": probs})
            continue
        unit = norm_unit(r.unit)
        try:
            ranges.append(ExposureEstimate(
                estimate_id=f"E-odin-{r.country}-{r.sector}".replace(" ", "_"), agent=AgentName.ODIN, country=r.country,
                sector=r.sector.lower(), metric=r.metric, metric_definition=r.metric_definition, unit=unit,
                currency="USD" if unit == "USD M" else None, period=r.period, denominator=r.denominator or None,
                low=r.low, high=r.high, trade_row_refs=calc_row_refs(store, r.calc_ids), calculation_ids=r.calc_ids,
                assumptions=r.assumptions, missing_data=r.missing_data, confidence=Confidence(r.confidence),
                uncertainty_note=r.rationale))
        except ValueError as exc:
            guards.append(f"range {r.country}/{r.sector} invalid: {exc}"[:200])
            insufficient.append({"country": r.country, "sector": r.sector.lower(), "metric": r.metric,
                                 "missing_data": [str(exc)[:200]], "rationale": r.rationale, "code_issues": [str(exc)[:200]]})
    for g in guards:
        env.log(LogEventType.ERROR, f"Odin output corrected by code: {g}"[:500])
    missing = []
    for m in j.sufficiency.missing:
        try:
            missing.append(MissingEvidence(description=m.description, why_needed=m.why_needed, countries=m.countries,
                                           sectors=m.sectors, source_types=m.source_types))
        except ValueError:
            continue
    env.log(LogEventType.SUFFICIENCY, f"Odin sufficiency: {'sufficient' if j.sufficiency.sufficient else 'INSUFFICIENT'} - "
            f"{j.sufficiency.reason}"[:500], {"missing": [m.model_dump() for m in missing]})
    return OdinResult(rulings=rulings, ranges=ranges, insufficient=insufficient, sufficient=j.sufficiency.sufficient,
                      sufficiency_reason=j.sufficiency.reason, missing=missing, executive_summary=j.executive_summary,
                      outlook_text=j.outlook_text, outlook_assumptions=j.outlook_assumptions,
                      evidence_quality_notes=j.evidence_quality_notes, prechecks=pcs, guards=guards, unruled=unruled)
