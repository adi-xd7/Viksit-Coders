"""A scripted stand-in for the model (isolated tests only).

It answers by schema and agent, reading IDs it needs (calc IDs, claim IDs,
attack IDs, pairs) from the prompt text the real code sends, so the full
trial machinery runs unchanged. Overrides let a test script a misbehaving or
"compromised" model. Every prompt is recorded for inspection.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from ragnarok.agents import schemas as S
from ragnarok.llm.client import BackendResult
from ragnarok.models import AgentName

Handler = Callable[[str, int], Any]  # (user prompt, call number for this agent+schema) -> parsed object


def calcs_in(text: str) -> list[tuple[str, float, str]]:
    return [(m.group(1), float(m.group(2)), m.group(3).strip())
            for m in re.finditer(r"trade_calc (CALC-[0-9a-f]+): \w+ -> result (-?[\d.]+) ([A-Za-z ]+?) \|", text)]


def claim_ids(text: str, prefix: str) -> list[str]:
    return list(dict.fromkeys(re.findall(rf"\[({prefix}\d+-\d+)\]", text)))


def missing_items(text: str) -> list[tuple[int, str]]:
    block = text.split("<sendback>")[1].split("</sendback>")[0]
    return [(int(m.group(1)), m.group(2)) for m in re.finditer(r"^(\d+)\. (.+?) \(why needed", block, re.M)]


def memory_ids(text: str) -> list[str]:
    if "<your_memory>" not in text:
        return []
    return re.findall(r"\[(M-[a-z]+-[0-9a-f]+)\]", text.split("<your_memory>")[1].split("</your_memory>")[0])


def C(doc, ref, quote, row=""):
    return S.CitationDraft(doc_id=doc, paragraph_ref=ref or "", row_id=row, quote=quote)


Q_SPARE = "but the rail operator said its spare capacity was limited"  # SYN-0001 P2
Q_LOCK = "loadings of grain fell sharply in March after the river lock closed for repairs"  # SYN-0001 P1
Q_BUYERS = "Buyers in Beta reported that delivered prices rose by a modest amount"  # SYN-0001 P3
Q_RAIL = "Exporters moved part of the cargo to the rail line through Gamma"  # SYN-0002 P1
Q_MILLERS = "Millers in Beta said they bought more grain from Gamma this month."  # SYN-0003 P1
Q_STOCKS = "Stocks cover about six weeks of demand."  # SYN-0003 P2


def default_handlers() -> dict[tuple[str, str], Handler]:
    def research(agent: str):
        def h(user: str, n: int):
            reqs = {
                "heimdall": [S.ToolRequest(tool="search", purpose="event", query="lock closure grain loadings Alpha"),
                             S.ToolRequest(tool="read_doc", purpose="notice", doc_id="SYN-0002")],
                "thor": [S.ToolRequest(tool="search", purpose="loss", query="grain loadings fell sharply lock closed"),
                         S.ToolRequest(tool="get_trade_rows", purpose="rows", table_ids=["SYN-0012"]),
                         S.ToolRequest(tool="trade_calc", purpose="low", calc_op="sum", row_ids=["SYN-0012#R1"]),
                         S.ToolRequest(tool="trade_calc", purpose="high", calc_op="sum", row_ids=["SYN-0012#R1", "SYN-0012#R4"])],
                "loki": [S.ToolRequest(tool="search", purpose="substitutes", query="millers bought grain from Gamma rail"),
                         S.ToolRequest(tool="read_doc", purpose="stocks", doc_id="SYN-0003")],
                "odin": [S.ToolRequest(tool="validate_citation", purpose="check", doc_id="SYN-0001", paragraph_ref="P2",
                                       quote=Q_SPARE)],
            }[agent]
            if "<new_evidence>" in user and agent in ("thor", "loki"):  # run 2: a new query of the advocate's own
                reqs = [r.model_copy(update={"query": r.query + " after the new evidence"}) if r.tool == "search" else r
                        for r in reqs]
            if "cross-exam" in user.lower() or "respond to every attack" in user.lower():
                reqs = [S.ToolRequest(tool="read_doc", purpose="counter", doc_id="SYN-0003")] if agent != "odin" else []
                if agent == "thor":
                    reqs.append(S.ToolRequest(tool="read_doc", purpose="new", doc_id="SYN-0001"))
            return S.ResearchTurn.of(reqs, done=True)
        return h

    def heimdall(user: str, n: int):
        return S.HeimdallReport(countries=["Beta"], sectors=["grain"], commodities=["grain"], routes=["Alpha to Beta"],
                                candidate_event_ids=["EVZ"], event_status="established",
                                status_reasons="Official notice and wire report confirm the lock closure.",
                                event_citations=[C("SYN-0002", "P1", Q_RAIL)], trade_table_ids=["SYN-0012"],
                                key_doc_ids=["SYN-0001", "SYN-0002"], missing_data=["rail capacity figures"])

    def thor_brief(user: str, n: int):
        cs = [c for c in calcs_in(user) if c[2] == "USD M"]
        lo, hi = min(cs, key=lambda c: c[1]), max(cs, key=lambda c: c[1])
        return S.AdvocateBrief(claims=[
            S.ClaimDraft(text="Alpha grain loadings fell sharply after the lock closed.", country="Beta", sector="grain",
                         claim_type="fact", citations=[C("SYN-0001", "P1", Q_LOCK)]),
            S.ClaimDraft(text="Beta's grain imports from Alpha worth up to the computed range are exposed.", country="Beta",
                         sector="grain", claim_type="inference", citations=[C("SYN-0001", "P2", Q_SPARE)],
                         calc_ids=[lo[0], hi[0]],
                         estimate=S.EstimateDraft(country="Beta", sector="grain", metric="exposed_import_value",
                                                  metric_definition="Value of Alpha->Beta grain imports in valid months",
                                                  unit="USD M", period="2030-01..2030-04", low=lo[1], high=hi[1],
                                                  calc_ids=[lo[0], hi[0]])),
        ])

    def loki_brief(user: str, n: int):
        return S.AdvocateBrief(claims=[
            S.ClaimDraft(text="Beta millers substituted grain from Gamma.", country="Beta", sector="grain", claim_type="fact",
                         citations=[C("SYN-0003", "P1", Q_MILLERS)]),
            S.ClaimDraft(text="Beta stocks cushion the disruption for weeks.", country="Beta", sector="grain",
                         claim_type="inference", citations=[C("SYN-0003", "P2", Q_STOCKS)]),
        ])

    def attacks(agent: str):
        def h(user: str, n: int):
            opp = "L" if agent == "thor" else "T"
            target = claim_ids(user.split("<opponent_claims>")[1], opp)[0]
            return S.AttackSet(attacks=[S.AttackDraft(
                target_claim_id=target, objection="The claim relies on a single source and ignores contrary evidence.",
                evidence_gap="No trade rows show the volume of the substitute flow.",
                why_it_matters="Without volumes the claim cannot change the exposure range.")])
        return h

    def responses(agent: str):
        def h(user: str, n: int):
            aids = re.findall(r"\[(A\d+-[TL]\d+)\]", user.split("<attacks_on_your_claims>")[1])
            if agent == "thor":
                return S.ResponseSet(responses=[S.ResponseDraft(attack_id=a, response="defend",
                                                                argument="New evidence shows buyers saw price rises.",
                                                                new_evidence=[C("SYN-0001", "P3", Q_BUYERS)]) for a in aids])
            return S.ResponseSet(responses=[S.ResponseDraft(attack_id=a, response="concede",
                                                            argument="The substitution volume is not documented.") for a in aids])
        return h

    def odin(user: str, n: int):
        ids = re.search(r"Rule on every claim \(IDs: ([^)]*)\)", user).group(1).split(", ")
        conceded = set(re.findall(r"CONCEDES (\S+)", user))
        rulings = [S.RulingDraft(claim_id=c, verdict="conceded" if c in conceded else "established" if c.startswith("T")
                                 else "contested", claim_type="fact", rationale="Supported by the cited passages as checked.")
                   for c in ids]
        m = re.search(r"thor \S+: Beta/grain \S+ (-?[\d.]+)\.\.(-?[\d.]+) USD M \([^)]*\); calcs (CALC-\w+), (CALC-\w+)", user)
        ranges = [S.OdinRange(country="Beta", sector="grain", metric="exposed_import_value",
                              metric_definition="Value of Alpha->Beta grain imports in valid months", unit="USD M",
                              period="2030-01..2030-04", low=float(m.group(1)), high=float(m.group(2)),
                              calc_ids=[m.group(3), m.group(4)], rationale="Upheld Thor's computed values.")] if m else [
            S.OdinRange(country="Beta", sector="grain", metric="n/a", metric_definition="n/a", unit="USD M", period="n/a",
                        insufficient_evidence=True, missing_data=["no reproducible estimate"], rationale="none")]
        return S.OdinJudgment(rulings=rulings, ranges=ranges,
                              sufficiency=S.SufficiencyDraft(sufficient=True, reason="Enough for a first briefing."),
                              executive_summary="Beta is exposed to the Alpha lock closure; substitution is undocumented.",
                              outlook_text="Exposure persists next quarter if the lock stays shut.",
                              outlook_assumptions=["the lock reopens no earlier than the second quarter"])

    def sendback_plan(user: str, n: int):
        items = missing_items(user)
        return S.SendBackPlan(searches=[S.TargetedSearch(missing_item=i, purpose="gap", query=f"targeted evidence for gap {i}: {d[:60]}")
                                        for i, d in items])

    def findings(user: str, n: int):
        return S.ResearchFindings(findings=[S.FindingDraft(missing_item=i, status="not_found", summary="nothing new found")
                                            for i, _ in missing_items(user)])

    def revision(user: str, n: int):
        return S.AdvocateRevision(claims=[])

    h: dict[tuple[str, str], Handler] = {}
    h[("heimdall", "SendBackPlan")] = sendback_plan
    h[("heimdall", "ResearchFindings")] = findings
    h[("thor", "AdvocateRevision")] = revision
    h[("loki", "AdvocateRevision")] = revision
    for a in ("heimdall", "thor", "loki", "odin"):
        h[(a, "ResearchTurn")] = research(a)
    h[("heimdall", "HeimdallReport")] = heimdall
    h[("thor", "AdvocateBrief")] = thor_brief
    h[("loki", "AdvocateBrief")] = loki_brief
    for a in ("thor", "loki"):
        h[(a, "AttackSet")] = attacks(a)
        h[(a, "ResponseSet")] = responses(a)
    h[("odin", "OdinJudgment")] = odin
    return h


class ScriptedBackend:
    def __init__(self, overrides: dict[tuple[str, str], Handler] | None = None) -> None:
        self.handlers = default_handlers() | (overrides or {})
        self.calls: list[dict] = []
        self.counts: dict[tuple[str, str], int] = {}

    def call(self, *, model, system, user, schema, effort, max_tokens, agent: AgentName):
        key = (agent.value, schema.__name__)
        n = self.counts.get(key, 0)
        self.counts[key] = n + 1
        self.calls.append({"agent": agent.value, "schema": schema.__name__, "system": system, "user": user, "n": n})
        if schema in (S.OdinRulings, S.OdinAssessment):  # Odin's two calls are scripted as one judgment
            j = self.handlers[("odin", "OdinJudgment")](user, n)
            out = (S.OdinRulings(rulings=j.rulings, injection_reports=j.injection_reports) if schema is S.OdinRulings
                   else S.OdinAssessment(**j.model_dump(exclude={"rulings", "injection_reports"})))
        elif key not in self.handlers and schema in (S.MemoryResearchTurn, S.SendBackPlanM):
            # memory-aware variants: same plan as without memory unless a test scripts otherwise
            base = S.ResearchTurn if schema is S.MemoryResearchTurn else S.SendBackPlan
            out = self.handlers[(agent.value, base.__name__)](user, n)
            out = schema(**out.model_dump(), memory_used=[], memory_effect="")
        else:
            out = self.handlers[key](user, n)
        if isinstance(out, BackendResult):
            return out
        return BackendResult(parsed=out, raw_text=out.model_dump_json(), input_tokens=len(user) // 4,
                             output_tokens=200, stop_reason="end_turn", model=model)
