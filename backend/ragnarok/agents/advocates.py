"""Thor (high exposure) and Loki (limited exposure): claims, attacks, responses.

Code-enforced rules:
- at least one search of the advocate's own before claims;
- a claim with no valid citation is rejected before Odin sees it;
- estimate bounds must equal results of trade_calc records the advocate produced;
- an attack must target an opponent claim and carry counter-evidence or a concrete gap;
- a defense must bring a new, valid citation not already used by the attacked claim,
  otherwise it is recorded as an invalid defense (the attack stands undefended).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ragnarok.agents.common import AgentEnv, load_prompt, research
from ragnarok.agents.estimates import bound_problems, calc_row_refs, load_calcs, norm_unit
from ragnarok.agents.schemas import AdvocateBrief, AdvocateRevision, AttackSet, ClaimDraft, ResponseSet
from ragnarok.memory.store import render_lessons
from ragnarok.models import (
    AgentName,
    Attack,
    Claim,
    ClaimType,
    Concession,
    Confidence,
    Defense,
    ExposureEstimate,
    LogEventType,
)

SIDE = {AgentName.THOR: "HIGH", AgentName.LOKI: "LIMITED"}
PREFIX = {AgentName.THOR: "T", AgentName.LOKI: "L"}


@dataclass
class Submission:
    claims: list[Claim] = field(default_factory=list)
    rejected: list[dict] = field(default_factory=list)  # code-rejected drafts with reasons (never reach Odin)
    failed: str | None = None  # the advocate could not produce a valid brief
    withdrawn: list[Concession] = field(default_factory=list)  # run n >= 2: earlier claims withdrawn
    revises: dict[str, str] = field(default_factory=dict)  # new claim ID -> earlier claim ID it replaces


@dataclass
class InvalidDefense:
    attack_id: str
    claim_id: str
    agent: AgentName
    reason: str
    argument: str


@dataclass
class CrossExam:
    attacks: list[Attack] = field(default_factory=list)
    defenses: list[Defense] = field(default_factory=list)
    concessions: list[Concession] = field(default_factory=list)
    invalid_defenses: list[InvalidDefense] = field(default_factory=list)
    unanswered: list[str] = field(default_factory=list)  # attack IDs with no response
    failures: list[str] = field(default_factory=list)  # e.g. "thor made no valid attack; loki unchallenged"
    rejected_attacks: list[dict] = field(default_factory=list)


def render_claims(claims: list[Claim], with_quotes: bool = True) -> str:
    out = []
    for c in claims:
        cites = "; ".join(f"{x.doc_id}/{x.paragraph_ref or x.row_id} ({x.pub_date})" + (f' "{x.quote}"' if with_quotes else "")
                          for x in c.citations)
        est = ""
        if c.exposure:
            e = c.exposure
            est = (f"\n  estimate: {e.country}/{e.sector} {e.metric} = {e.low}..{e.high} {e.unit} ({e.period}); "
                   f"definition: {e.metric_definition}; calcs: {', '.join(e.calculation_ids)}; assumptions: {'; '.join(e.assumptions)}")
        out.append(f"[{c.claim_id}] ({c.agent.value}, {c.claim_type.value}) {c.text}\n  citations: {cites}"
                   f"\n  assumptions: {'; '.join(c.assumptions) or 'none'}{est}")
    return "\n".join(out) or "(none)"


def _estimate(env: AgentEnv, d: ClaimDraft) -> tuple[ExposureEstimate | None, list[str]]:
    e = d.estimate
    if e is None:
        return None, []
    store = env.service.store
    probs = bound_problems(store, e.low, e.high, e.unit, e.calc_ids, allowed_calc_ids=env.retrieved)
    if probs:
        return None, probs
    unit = norm_unit(e.unit)
    denom = e.denominator or None
    if unit == "percent" and not denom:  # take the denominator the calc record itself states
        recs, _ = load_calcs(store, e.calc_ids)
        denom = next((str(r.parameters["denominator"]) for r in recs.values()
                      if r.unit == "percent" and r.parameters.get("denominator") not in (None, "n/a")), None)
    try:
        est = ExposureEstimate(
            estimate_id=f"E-{env.agent.value}", agent=env.agent, country=e.country, sector=e.sector.lower(), metric=e.metric,
            metric_definition=e.metric_definition, unit=unit, currency="USD" if unit == "USD M" else None, period=e.period,
            denominator=denom, low=e.low, high=e.high, trade_row_refs=calc_row_refs(store, e.calc_ids),
            calculation_ids=e.calc_ids, assumptions=e.assumptions, missing_data=e.missing_data,
            confidence=Confidence(e.confidence), uncertainty_note=e.uncertainty_note,
        )
    except ValueError as exc:
        return None, [f"estimate invalid: {exc}"]
    return est, []


def _claim_problems(env: AgentEnv, claims) -> list[str]:
    p = []
    for i, c in enumerate(claims, 1):
        good, bad = env.citations(c.citations)
        if not good:
            p.append(f"claim {i} has no valid citation ({'; '.join(bad) or 'none given'})")
        p += [f"claim {i}: invalid citation {x}" for x in bad]
        if c.estimate:
            _, ep = _estimate(env, c)
            p += [f"claim {i} estimate: {x}" for x in ep]
    return p


def _research_own(env: AgentEnv, system: str, task: str, context: str, lessons, label: str) -> str | None:
    """Research with at least one NEW search of the advocate's own in this run."""
    ctx = env.ctx
    start = env.searches
    research(env, system, task, context, ctx.settings.max_research_rounds, min_searches=start + 1,
             effort=ctx.settings.effort_advocate, label=label, lessons=lessons)
    if env.searches < start + 1:
        msg = f"{env.agent.value} did not make a search of its own in run {ctx.run_number}"
        env.log(LogEventType.ERROR, msg)
        return msg
    return None


def run_brief(env: AgentEnv, case_text: str) -> Submission:
    ctx = env.ctx
    agent = env.agent
    system = load_prompt(agent)
    task = (f"Research and argue that exposure is {SIDE[agent]}. Make at least one search of your own, fetch the trade rows "
            "you need and compute every estimate with trade_calc. For EVERY exposure pair in the case file that has trade "
            "data, give one claim with an estimate whose low and high come from two different defensible trade_calc "
            "results (e.g. different periods, or with/without documented substitute flows), preferably in USD M; where a "
            "pair has no trade data, say so in a claim's limitations instead of guessing.")
    lessons = env.recall(["research", "brief"], "planning the brief")
    sub = Submission()
    sub.failed = _research_own(env, system, task, case_text, lessons, f"{agent.value} research")
    if sub.failed:
        return sub

    def validate(b: AdvocateBrief) -> list[str]:
        p = []
        if not b.claims:
            p.append("at least one claim is required")
        if len(b.claims) > ctx.settings.max_claims_per_advocate:
            p.append(f"at most {ctx.settings.max_claims_per_advocate} claims")
        return p + _claim_problems(env, b.claims)

    user = (f"{case_text}\n\n{render_lessons(lessons)}\n\n<task>\n{task}\nNow write your claims (at most "
            f"{ctx.settings.max_claims_per_advocate}). Cite only paragraphs/rows shown in your evidence; estimate bounds "
            f"must be calc results.\n</task>\n\n<evidence>\n{env.evidence_text()}\n</evidence>")
    brief = ctx.llm.structured(agent, system, user, AdvocateBrief, effort=ctx.settings.effort_advocate,
                               validate=validate, label=f"{agent.value} brief", allow_residual=True)
    env.report_injections(brief.injection_reports)
    _build_claims(env, brief.claims, sub, {})
    if not sub.claims:
        sub.failed = f"{agent.value} produced no valid claim"
        env.log(LogEventType.ERROR, sub.failed)
    return sub


def render_previous(claims: list[Claim], verdicts: dict[str, str]) -> str:
    return "\n".join(f"{render_claims([c])}\n  ODIN'S RULING (run {c.run_number}): {verdicts.get(c.claim_id, 'not ruled')}"
                     for c in claims) or "(none)"


def run_revision(env: AgentEnv, case_text: str, previous: list[Claim], verdicts: dict[str, str],
                 new_evidence_text: str, new_refs: list[str]) -> Submission:
    """Run n >= 2: reconsider earlier claims in the light of Heimdall's new evidence."""
    ctx = env.ctx
    agent = env.agent
    system = load_prompt(agent)
    own = {c.claim_id: c for c in previous}
    env.receive_case_evidence(new_refs, f"Heimdall's new evidence for run {ctx.run_number}, delivered with the Case File")
    context = (f"{case_text}\n\n{new_evidence_text}\n\n<your_previous_claims>\n{render_previous(previous, verdicts)}\n"
               "</your_previous_claims>")
    task = (f"Run {ctx.run_number}: Odin sent the case back and Heimdall found new evidence (above). Argue that exposure is "
            f"{SIDE[agent]}. Make at least one new search of your own, then reconsider each earlier claim the new evidence "
            "affects: revise it (new claim with revises_claim_id), withdraw it if the new evidence undermines it, or leave "
            "it unchanged (it stands and is re-ruled). Add new claims where the new evidence supports them. Compute every "
            "estimate with trade_calc.")
    lessons = env.recall(["research", "brief"], f"reconsidering claims in run {ctx.run_number}")
    sub = Submission()
    sub.failed = _research_own(env, system, task, context, lessons, f"{agent.value} run {ctx.run_number} research")
    if sub.failed:
        return sub

    def validate(b: AdvocateRevision) -> list[str]:
        p = []
        if len(b.claims) > ctx.settings.max_claims_per_advocate:
            p.append(f"at most {ctx.settings.max_claims_per_advocate} claims")
        p += [f"revises_claim_id {c.revises_claim_id} is not one of your earlier claims ({', '.join(own)})"
              for c in b.claims if c.revises_claim_id and c.revises_claim_id not in own]
        p += [f"withdrawn {w.claim_id} is not one of your earlier claims" for w in b.withdrawn if w.claim_id not in own]
        return p + _claim_problems(env, b.claims)

    user = (f"{context}\n\n{render_lessons(lessons)}\n\n<task>\n{task}\nNow write your run-{ctx.run_number} claims and "
            "withdrawals. Cite only paragraphs/rows shown in your evidence; estimate bounds must be calc results.\n"
            f"</task>\n\n<evidence>\n{env.evidence_text()}\n</evidence>")
    rev = ctx.llm.structured(agent, system, user, AdvocateRevision, effort=ctx.settings.effort_advocate,
                             validate=validate, label=f"{agent.value} run {ctx.run_number} revision", allow_residual=True)
    env.report_injections(rev.injection_reports)
    for w in rev.withdrawn:
        if w.claim_id not in own or any(k.claim_id == w.claim_id for k in sub.withdrawn):
            continue
        reason = w.reason if len(w.reason) >= 10 else w.reason + " (withdrawn)"
        con = Concession(concession_id=f"W{ctx.run_number}-{w.claim_id}", run_number=ctx.run_number, agent=agent,
                         claim_id=w.claim_id, attack_id=None, reason=reason)
        sub.withdrawn.append(con)
        env.log(LogEventType.CONCESSION, f"{agent.value} withdraws {w.claim_id} in run {ctx.run_number}: {reason}"[:500],
                {"concession": con.model_dump(mode="json"), "withdrawal": True}, [w.claim_id])
    _build_claims(env, rev.claims, sub, own)
    return sub


def _build_claims(env: AgentEnv, drafts, sub: Submission, own_previous: dict[str, Claim]) -> None:
    ctx = env.ctx
    agent = env.agent
    for n, d in enumerate(drafts[: ctx.settings.max_claims_per_advocate], 1):
        cid = f"{PREFIX[agent]}{ctx.run_number}-{n}"
        good, bad = env.citations(d.citations)
        if not good:
            sub.rejected.append({"claim_id": cid, "text": d.text, "reason": "no valid citation", "issues": bad})
            env.log(LogEventType.ERROR, f"claim {cid} rejected in code before Odin: no valid citation", {"issues": bad[:10]})
            continue
        est, ep = _estimate(env, d)
        limitations = list(d.limitations)
        if ep:
            limitations.append("estimate removed by code: " + "; ".join(ep)[:300])
            env.log(LogEventType.ERROR, f"claim {cid}: estimate removed by code (numbers not reproducible from calc records)",
                    {"issues": ep[:10]})
        if bad:
            limitations.append(f"{len(bad)} invalid citation(s) dropped by code")
            env.log(LogEventType.ERROR, f"claim {cid}: {len(bad)} invalid citation(s) dropped by code", {"issues": bad[:10]})
        revises = getattr(d, "revises_claim_id", "") or None
        if revises and (revises not in own_previous or revises in sub.revises.values()):
            limitations.append(f"revises_claim_id {revises} ignored by code (not an earlier claim of this advocate, or "
                               "already revised)")
            revises = None
        try:
            claim = Claim(claim_id=cid, run_number=ctx.run_number, agent=agent, text=d.text, country=d.country or None,
                          sector=d.sector.lower() if d.sector else None, claim_type=ClaimType(d.claim_type), citations=good,
                          assumptions=d.assumptions, exposure=est, limitations=limitations,
                          calculation_ids=[c for c in d.calc_ids if c in env.retrieved], revises_claim_id=revises)
        except ValueError as exc:
            sub.rejected.append({"claim_id": cid, "text": d.text, "reason": f"invalid claim: {exc}"})
            env.log(LogEventType.ERROR, f"claim {cid} rejected in code: {exc}"[:500])
            continue
        sub.claims.append(claim)
        if revises:
            sub.revises[cid] = revises
        env.log(LogEventType.CLAIM, f"{cid} ({agent.value}, {claim.claim_type.value})"
                + (f" revises {revises}" if revises else "") + f": {claim.text}"[:500],
                {"claim": claim.model_dump(mode="json")}, [f"{c.doc_id}#{c.paragraph_ref or c.row_id}" for c in good]
                + ([revises] if revises else []))


def run_attacks(env: AgentEnv, case_text: str, own: list[Claim], opponent: list[Claim], round_number: int = 1,
                start: int = 0) -> tuple[list[Attack], list[dict]]:
    """One cross-examination round. Round 2+ re-attacks claims defended in the round before.
    Attack IDs continue across rounds (start = attacks this advocate already made in the run)."""
    ctx = env.ctx
    agent = env.agent
    system = load_prompt(agent)
    ids = {c.claim_id: c for c in opponent}
    context = (f"{case_text}\n\n<your_claims>\n{render_claims(own, False)}\n</your_claims>\n\n"
               f"<opponent_claims>\n{render_claims(opponent)}\n</opponent_claims>")
    task = ("Cross-examination: attack the opponent's weakest claims. For each attack give the target claim ID, a specific "
            "objection, counter-evidence citations and/or the concrete evidence gap, and why it matters. Search for "
            "counter-evidence if needed.")
    if round_number > 1:
        task += (f" This is rebuttal round {round_number}: the claims listed were defended with new evidence in the round "
                 "before; attack only if that defense leaves a real problem.")
    lessons = env.recall(["cross_exam"], f"cross-examination round {round_number}")
    context += ("\n\n" + render_lessons(lessons)) if lessons else ""
    research(env, system, task, context, 1, effort=ctx.settings.effort_advocate, label=f"{agent.value} cross-exam research")

    def check(a, n) -> list[str]:
        p = []
        if a.target_claim_id not in ids:
            p.append(f"attack {n}: target {a.target_claim_id} is not an opponent claim (valid: {', '.join(ids)})")
        good, bad = env.citations(a.counter_evidence)
        p += [f"attack {n}: invalid counter-evidence {b}" for b in bad]
        if not good and not (a.evidence_gap and len(a.evidence_gap.strip()) >= 10):
            p.append(f"attack {n}: needs valid counter-evidence or a concrete evidence gap")
        if len(a.objection.strip()) < 20 or len(a.why_it_matters.strip()) < 10:
            p.append(f"attack {n}: objection/why_it_matters too short to be a specific attack")
        return p

    def validate(s: AttackSet) -> list[str]:
        p = [] if s.attacks else ["at least one attack is required"]
        for n, a in enumerate(s.attacks[: ctx.settings.max_attacks_per_advocate], 1):
            p += check(a, n)
        return p

    user = (f"{context}\n\n<task>\n{task}\nWrite at most {ctx.settings.max_attacks_per_advocate} attacks.\n</task>\n\n"
            f"<evidence>\n{env.evidence_text()}\n</evidence>")
    s = ctx.llm.structured(agent, system, user, AttackSet, effort=ctx.settings.effort_advocate, validate=validate,
                           label=f"{agent.value} attacks", allow_residual=True)
    env.report_injections(s.injection_reports)
    attacks, rejected = [], []
    for n, a in enumerate(s.attacks[: ctx.settings.max_attacks_per_advocate], 1):
        aid = f"A{ctx.run_number}-{PREFIX[agent]}{start + n}"
        good, bad = env.citations(a.counter_evidence)
        target = ids.get(a.target_claim_id)
        try:
            if target is None:
                raise ValueError(f"target {a.target_claim_id} is not an opponent claim")
            att = Attack(attack_id=aid, run_number=ctx.run_number, round_number=round_number, attacker=agent, target_claim_id=target.claim_id,
                         target_agent=target.agent, objection=a.objection, counter_evidence=good,
                         evidence_gap=a.evidence_gap or None, why_it_matters=a.why_it_matters)
        except ValueError as exc:
            rejected.append({"attack_id": aid, "reason": str(exc)[:300], "objection": a.objection})
            env.log(LogEventType.ERROR, f"attack {aid} rejected in code: {exc}"[:500])
            continue
        attacks.append(att)
        env.log(LogEventType.ATTACK, f"{aid} {agent.value} -> {att.target_claim_id}: {att.objection}"[:500],
                {"attack": att.model_dump(mode="json"), "dropped_citations": bad},
                [att.target_claim_id] + [f"{c.doc_id}#{c.paragraph_ref or c.row_id}" for c in good])
    return attacks, rejected


def run_responses(env: AgentEnv, case_text: str, own: list[Claim], attacks: list[Attack], cx: CrossExam) -> None:
    """The challenged advocate defends (with NEW evidence) or concedes each attack."""
    if not attacks:
        return
    ctx = env.ctx
    agent = env.agent
    system = load_prompt(agent)
    claims = {c.claim_id: c for c in own}
    att_text = "\n".join(
        f"[{a.attack_id}] by {a.attacker.value} on {a.target_claim_id}: {a.objection}\n  why it matters: {a.why_it_matters}"
        + (f"\n  evidence gap: {a.evidence_gap}" if a.evidence_gap else "")
        + "".join(f'\n  counter-evidence: {c.doc_id}/{c.paragraph_ref or c.row_id} ({c.pub_date}) "{c.quote}"'
                  for c in a.counter_evidence) for a in attacks)
    context = (f"{case_text}\n\n<your_claims>\n{render_claims(list(claims.values()))}\n</your_claims>\n\n"
               f"<attacks_on_your_claims>\n{att_text}\n</attacks_on_your_claims>")
    task = ("Respond to every attack: defend with NEW evidence (a paragraph or trade row not already cited by the attacked "
            "claim) or concede. A concession can be partial (give the revised claim). Search for new evidence if needed.")
    lessons = env.recall(["cross_exam"], "answering attacks")
    context += ("\n\n" + render_lessons(lessons)) if lessons else ""
    research(env, system, task, context, 1, effort=ctx.settings.effort_advocate, label=f"{agent.value} defense research")

    def new_refs(a, drafts) -> tuple[list, list[str]]:
        good, bad = env.citations(drafts)
        old = {(c.doc_id, c.paragraph_ref, c.row_id) for c in claims[a.target_claim_id].citations}
        old |= {(c.doc_id, c.paragraph_ref, c.row_id) for d in cx.defenses if d.claim_id == a.target_claim_id
                for c in d.new_evidence}  # evidence used in an earlier defense of the same claim is not new
        return [c for c in good if (c.doc_id, c.paragraph_ref, c.row_id) not in old], bad

    by_id = {a.attack_id: a for a in attacks}

    def validate(s: ResponseSet) -> list[str]:
        p = []
        seen = [r.attack_id for r in s.responses]
        p += [f"no response to attack {a}" for a in by_id if a not in seen]
        for r in s.responses:
            a = by_id.get(r.attack_id)
            if a is None:
                p.append(f"unknown attack {r.attack_id}")
                continue
            if r.response == "defend":
                fresh, bad = new_refs(a, r.new_evidence)
                if not fresh:
                    p.append(f"defense of {r.attack_id} has no NEW valid citation (not already cited by "
                             f"{a.target_claim_id}); defend with new evidence or concede" + (f" ({'; '.join(bad)})" if bad else ""))
            elif r.partial and not r.revised_claim_text:
                p.append(f"partial concession on {r.attack_id} needs revised_claim_text")
        return p

    user = (f"{context}\n\n<task>\n{task}\n</task>\n\n<evidence>\n{env.evidence_text()}\n</evidence>")
    s = ctx.llm.structured(agent, system, user, ResponseSet, effort=ctx.settings.effort_advocate, validate=validate,
                           label=f"{agent.value} responses", allow_residual=True)
    answered = set()
    for r in s.responses:
        a = by_id.get(r.attack_id)
        if a is None or r.attack_id in answered:
            continue
        answered.add(r.attack_id)
        if r.response == "concede":
            try:
                con = Concession(concession_id=f"C-{r.attack_id}", run_number=ctx.run_number, agent=agent,
                                 claim_id=a.target_claim_id, attack_id=a.attack_id, reason=r.argument, partial=r.partial,
                                 revised_claim_text=r.revised_claim_text or None)
            except ValueError as exc:
                cx.invalid_defenses.append(InvalidDefense(a.attack_id, a.target_claim_id, agent, f"invalid concession: {exc}", r.argument))
                env.log(LogEventType.ERROR, f"concession on {a.attack_id} invalid: {exc}"[:500])
                continue
            cx.concessions.append(con)
            env.log(LogEventType.CONCESSION, f"{agent.value} concedes {a.target_claim_id} ({'partial' if r.partial else 'full'}) "
                    f"after {a.attack_id}: {r.argument}"[:500], {"concession": con.model_dump(mode="json")},
                    [a.target_claim_id, a.attack_id])
            continue
        fresh, bad = new_refs(a, r.new_evidence)
        if not fresh:
            reason = "defense brought no new valid evidence (code check: no citation outside the claim's own)"
            cx.invalid_defenses.append(InvalidDefense(a.attack_id, a.target_claim_id, agent, reason, r.argument))
            env.log(LogEventType.ERROR, f"defense of {a.target_claim_id} against {a.attack_id} invalid: {reason}",
                    {"argument": r.argument[:400], "dropped": bad}, [a.target_claim_id, a.attack_id])
            continue
        d = Defense(defense_id=f"D-{a.attack_id}", run_number=ctx.run_number, defender=agent, attack_id=a.attack_id,
                    claim_id=a.target_claim_id, argument=r.argument if len(r.argument) >= 20 else r.argument + " (defense)",
                    new_evidence=fresh)
        cx.defenses.append(d)
        env.log(LogEventType.DEFENSE, f"{agent.value} defends {a.target_claim_id} against {a.attack_id} with "
                f"{len(fresh)} new citation(s): {r.argument}"[:500], {"defense": d.model_dump(mode="json")},
                [a.target_claim_id, a.attack_id] + [f"{c.doc_id}#{c.paragraph_ref or c.row_id}" for c in fresh])
    cx.unanswered += [aid for aid in by_id if aid not in answered]
    for aid in by_id:
        if aid not in answered:
            env.log(LogEventType.ERROR, f"attack {aid} was not answered; it stands undefended", refs=[aid])
