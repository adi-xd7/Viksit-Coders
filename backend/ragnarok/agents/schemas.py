"""Schemas the LLM fills in (structured output). Deliberately flat and permissive:
code converts them into the core contracts (ragnarok.models), fills dates from
the store, validates citations and drops anything invalid with a logged reason.
There is no as_of field anywhere: agents cannot choose the date."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ToolName = Literal["search", "read_doc", "get_trade_rows", "trade_calc", "validate_citation"]
CalcOp = Literal["sum", "mean", "yoy_change", "yoy_pct_change", "share", "period_change", "period_pct_change", "net_offset"]


def _all_required(schema: dict, cls=None) -> None:
    schema["required"] = list(schema.get("properties", {}))


class _LLM(BaseModel):
    """Base for schemas sent to the model. Every property is marked required in the
    JSON schema (optional properties make the structured-output grammar explode);
    Python-side defaults remain for code and tests."""

    model_config = ConfigDict(json_schema_extra=_all_required)


class ToolRequest(BaseModel):
    """Internal tool request (never sent as a schema). The model asks for tools through
    the typed lists in ResearchTurn, which are converted to ToolRequests in code."""

    tool: ToolName
    purpose: str = Field(description="why this request is needed")
    query: str = Field("", description="search: the query text")
    countries: list[str] = Field(default_factory=list, description="search filter")
    sectors: list[str] = Field(default_factory=list, description="search filter; also get_trade_rows sector")
    event_ids: list[str] = Field(default_factory=list, description='search filter; "none" selects background documents')
    source_types: list[str] = Field(default_factory=list, description="search filter")
    max_reliability: int = Field(0, description="search filter: worst tier allowed 1-4 (2 = tiers 1 and 2); 0 = any")
    doc_id: str = Field("", description="read_doc / validate_citation")
    paragraphs: list[str] = Field(default_factory=list, description='read_doc: refs such as "P3"; empty = whole document')
    origin: str = Field("", description="get_trade_rows: exporting country")
    destination: str = Field("", description="get_trade_rows: importing country")
    table_ids: list[str] = Field(default_factory=list, description="get_trade_rows")
    period_from: str = Field("", description="get_trade_rows: YYYY-MM")
    period_to: str = Field("", description="get_trade_rows: YYYY-MM")
    calc_op: str = Field("", description="trade_calc: " + " | ".join(CalcOp.__args__))
    row_ids: list[str] = Field(default_factory=list, description="trade_calc: rows to sum/average; current rows (yoy); numerator (share); gross (net_offset); [from, to] (period_*). get_trade_rows: specific rows")
    row_ids_b: list[str] = Field(default_factory=list, description="trade_calc: prior-year rows (yoy); denominator rows (share); offset rows (net_offset)")
    denominator_label: str = Field("", description="trade_calc share: what the denominator is")
    field: str = Field("value", description='trade_calc: "value" or "volume"')
    paragraph_ref: str = Field("", description="validate_citation")
    row_id: str = Field("", description="validate_citation")
    quote: str = Field("", description="validate_citation")


class SearchReq(_LLM):
    purpose: str
    query: str
    countries: list[str] = Field(default_factory=list)
    sectors: list[str] = Field(default_factory=list)
    event_ids: list[str] = Field(default_factory=list, description='"none" selects background documents')
    source_types: list[str] = Field(default_factory=list)
    max_reliability: int = Field(0, description="worst tier allowed 1-4 (2 = tiers 1 and 2); 0 = any")


class ReadReq(_LLM):
    purpose: str
    doc_id: str
    paragraphs: list[str] = Field(default_factory=list, description='refs such as "P3"; empty = whole document')


class TradeReq(_LLM):
    purpose: str
    origin: str = Field("", description="exporting country; empty = any")
    destination: str = Field("", description="importing country; empty = any")
    sectors: list[str] = Field(default_factory=list)
    table_ids: list[str] = Field(default_factory=list)
    row_ids: list[str] = Field(default_factory=list)
    period_from: str = Field("", description="YYYY-MM or empty")
    period_to: str = Field("", description="YYYY-MM or empty")


class CalcReq(_LLM):
    purpose: str
    calc_op: str = Field(description=" | ".join(CalcOp.__args__))
    row_ids: list[str] = Field(description="rows to sum/average; current rows (yoy); numerator (share); gross (net_offset); [from, to] (period_*)")
    row_ids_b: list[str] = Field(default_factory=list, description="prior-year rows (yoy); denominator rows (share); offset rows (net_offset)")
    denominator_label: str = Field("", description="share only: what the denominator is")
    field: str = Field("value", description='"value" or "volume"')


class CheckReq(_LLM):
    purpose: str
    doc_id: str
    paragraph_ref: str = ""
    row_id: str = ""
    quote: str


class ResearchTurn(_LLM):
    searches: list[SearchReq] = Field(default_factory=list)
    reads: list[ReadReq] = Field(default_factory=list)
    trade_rows: list[TradeReq] = Field(default_factory=list)
    calcs: list[CalcReq] = Field(default_factory=list)
    citation_checks: list[CheckReq] = Field(default_factory=list)
    done: bool = Field(description="true when you have enough evidence for your final answer")
    note: str = ""

    def to_requests(self) -> list[ToolRequest]:
        out = [ToolRequest(tool="search", **r.model_dump()) for r in self.searches]
        out += [ToolRequest(tool="read_doc", **r.model_dump()) for r in self.reads]
        out += [ToolRequest(tool="get_trade_rows", **r.model_dump()) for r in self.trade_rows]
        out += [ToolRequest(tool="trade_calc", **r.model_dump()) for r in self.calcs]
        out += [ToolRequest(tool="validate_citation", **r.model_dump()) for r in self.citation_checks]
        return out

    @classmethod
    def of(cls, requests: list[ToolRequest], done: bool = True) -> "ResearchTurn":
        """Build from ToolRequests (tests and scripted backends)."""
        kinds = {"search": ("searches", SearchReq), "read_doc": ("reads", ReadReq), "get_trade_rows": ("trade_rows", TradeReq),
                 "trade_calc": ("calcs", CalcReq), "validate_citation": ("citation_checks", CheckReq)}
        lists: dict[str, list] = {k: [] for k, _ in kinds.values()}
        for r in requests:
            name, model = kinds[r.tool]
            data = r.model_dump()
            lists[name].append(model(**{k: data[k] for k in model.model_fields if k in data}))
        return cls(done=done, **lists)


class MemoryResearchTurn(ResearchTurn):
    """ResearchTurn used when the agent was shown its own lessons: it says which it applied."""

    memory_used: list[str] = Field(default_factory=list, description="IDs of your lessons (M-...) that shaped these requests; empty if none")
    memory_effect: str = Field("", description="how those lessons changed your requests; empty if none")


class ResearchPlan(_LLM):
    """Tool requests only (the no-memory plan inside DualResearchTurn)."""

    searches: list[SearchReq] = Field(default_factory=list)
    reads: list[ReadReq] = Field(default_factory=list)
    trade_rows: list[TradeReq] = Field(default_factory=list)
    calcs: list[CalcReq] = Field(default_factory=list)
    citation_checks: list[CheckReq] = Field(default_factory=list)

    def to_requests(self) -> list[ToolRequest]:
        return ResearchTurn(done=True, **self.model_dump()).to_requests()


class DualResearchTurn(MemoryResearchTurn):
    """One planning call that records both plans: plan_without_memory (what the agent would
    request if it had no memory; recorded, never executed) and the executed requests above."""

    plan_without_memory: ResearchPlan = Field(description="the requests you would make WITHOUT your memory (not executed)")

    @classmethod
    def dual(cls, executed: list[ToolRequest], baseline: list[ToolRequest], memory_used: list[str] | None = None,
             memory_effect: str = "", done: bool = True) -> "DualResearchTurn":
        """Build from ToolRequests (tests and scripted backends)."""
        ex = ResearchTurn.of(executed, done=done).model_dump()
        b = ResearchTurn.of(baseline).model_dump(exclude={"done", "note"})
        return cls(**ex, plan_without_memory=ResearchPlan(**b), memory_used=memory_used or [], memory_effect=memory_effect)


class TargetedSearch(_LLM):
    missing_item: int = Field(description="number of the missing-evidence item this search targets (1-based)")
    purpose: str
    query: str = Field(description="a NEW query: must differ from every earlier query in this case")
    countries: list[str] = Field(default_factory=list)
    sectors: list[str] = Field(default_factory=list)
    event_ids: list[str] = Field(default_factory=list, description='"none" selects background documents')
    source_types: list[str] = Field(default_factory=list)
    max_reliability: int = Field(0, description="worst tier allowed 1-4; 0 = any")

    def to_request(self) -> ToolRequest:
        return ToolRequest(tool="search", **self.model_dump(exclude={"missing_item"}))


class SendBackPlan(_LLM):
    searches: list[TargetedSearch]
    note: str = ""


class SendBackPlanM(SendBackPlan):
    """SendBackPlan when Heimdall was shown its own lessons."""

    memory_used: list[str] = Field(default_factory=list, description="IDs of your lessons (M-...) that shaped this plan")
    memory_effect: str = Field("", description="how those lessons changed the plan; empty if none")


class DualSendBackPlan(SendBackPlanM):
    """SendBackPlanM that also records the plan Heimdall would make without memory (not executed)."""

    searches_without_memory: list[TargetedSearch] = Field(description="the searches you would plan WITHOUT your memory (not executed)")


class CitationDraft(_LLM):
    doc_id: str
    paragraph_ref: str = Field("", description='e.g. "P3" (empty when citing a trade row)')
    row_id: str = Field("", description='trade row ID, e.g. "ABC-0001#R4" (empty when citing a paragraph)')
    quote: str = Field(description="short exact quote from the cited paragraph or trade row")


class InjectionReport(_LLM):
    doc_id: str
    paragraph_ref: str = ""
    description: str


class EstimateDraft(_LLM):
    country: str
    sector: str
    metric: str = Field(description="short metric name")
    metric_definition: str = Field(description="what exactly is measured, over which route/period")
    unit: str = Field(description='"USD M", "percent" or "tonnes"; must match the calc records')
    period: str
    denominator: str = Field("", description="required when unit is percent")
    low: float
    high: float
    calc_ids: list[str] = Field(description="trade_calc records whose results are the bounds")
    assumptions: list[str] = Field(default_factory=list)
    missing_data: list[str] = Field(default_factory=list)
    confidence: Literal["low", "medium", "high"] = "low"
    uncertainty_note: str = ""


class ClaimDraft(_LLM):
    text: str
    country: str = ""
    sector: str = ""
    claim_type: Literal["fact", "inference"]
    citations: list[CitationDraft]
    assumptions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    calc_ids: list[str] = Field(default_factory=list)
    estimate: EstimateDraft | None = None


class AdvocateBrief(_LLM):
    claims: list[ClaimDraft]
    injection_reports: list[InjectionReport] = Field(default_factory=list)


class RevisedClaimDraft(ClaimDraft):
    revises_claim_id: str = Field("", description="ID of your earlier claim this replaces; empty for a new claim")


class WithdrawDraft(_LLM):
    claim_id: str
    reason: str


class AdvocateRevision(_LLM):
    """Run n >= 2: revised and new claims, and withdrawals. Earlier claims neither
    revised nor withdrawn stand unchanged and are re-ruled by Odin."""

    claims: list[RevisedClaimDraft]
    withdrawn: list[WithdrawDraft] = Field(default_factory=list)
    injection_reports: list[InjectionReport] = Field(default_factory=list)


class FindingDraft(_LLM):
    missing_item: int = Field(description="number of the missing-evidence item (1-based)")
    status: Literal["found", "partial", "not_found"]
    summary: str = Field(description="what the evidence shows about the gap, or why nothing was found")
    citations: list[CitationDraft] = Field(default_factory=list, description="the evidence found for this item")
    trade_table_ids: list[str] = Field(default_factory=list)


class ResearchFindings(_LLM):
    findings: list[FindingDraft]
    still_missing: list[str] = Field(default_factory=list, description="data still missing after this research")
    injection_reports: list[InjectionReport] = Field(default_factory=list)


class CorrectionNote(_LLM):
    doc_id: str
    relation: Literal["correction", "retraction", "contradiction", "superseded", "rumour", "unrelated_event"]
    about_doc_id: str = ""
    note: str


class HeimdallReport(_LLM):
    countries: list[str] = Field(description="ONLY the countries whose exposure the question asks about")
    sectors: list[str] = Field(description='ONLY the commodities/sectors whose exposure the question asks about, lower-case, e.g. "wheat"')
    related_countries: list[str] = Field(default_factory=list, description="exporters, transit and alternative-supplier countries")
    commodities: list[str] = Field(default_factory=list)
    routes: list[str] = Field(default_factory=list)
    candidate_event_ids: list[str] = Field(default_factory=list)
    event_status: Literal["established", "disproved", "uncertain"]
    status_reasons: str
    event_citations: list[CitationDraft]
    corrections: list[CorrectionNote] = Field(default_factory=list)
    key_doc_ids: list[str] = Field(default_factory=list)
    trade_table_ids: list[str] = Field(default_factory=list)
    missing_data: list[str] = Field(default_factory=list)
    injection_reports: list[InjectionReport] = Field(default_factory=list)


class AttackDraft(_LLM):
    target_claim_id: str
    objection: str = Field(description="specific objection, not generic disagreement")
    counter_evidence: list[CitationDraft] = Field(default_factory=list)
    evidence_gap: str = Field("", description="the concrete missing evidence, if attacking a gap")
    why_it_matters: str


class AttackSet(_LLM):
    attacks: list[AttackDraft]
    injection_reports: list[InjectionReport] = Field(default_factory=list)


class ResponseDraft(_LLM):
    attack_id: str
    response: Literal["defend", "concede"]
    argument: str
    new_evidence: list[CitationDraft] = Field(default_factory=list,
                                              description="for a defense: citations NOT already used by the attacked claim")
    partial: bool = Field(False, description="concession of part of the claim only")
    revised_claim_text: str = Field("", description="required for a partial concession")


class ResponseSet(_LLM):
    responses: list[ResponseDraft]


class RulingDraft(_LLM):
    claim_id: str
    verdict: Literal["established", "contested", "conceded", "rejected"]
    claim_type: Literal["fact", "inference"]
    rationale: str
    supporting_citations: list[CitationDraft] = Field(default_factory=list)
    contradicting_citations: list[CitationDraft] = Field(default_factory=list)


class OdinRange(_LLM):
    country: str
    sector: str
    metric: str
    metric_definition: str
    unit: str
    period: str
    denominator: str = ""
    low: float | None = None
    high: float | None = None
    insufficient_evidence: bool = False
    calc_ids: list[str] = Field(default_factory=list)
    basis_claim_ids: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    missing_data: list[str] = Field(default_factory=list)
    confidence: Literal["low", "medium", "high"] = "low"
    rationale: str


class MissingDraft(_LLM):
    description: str
    why_needed: str
    countries: list[str] = Field(default_factory=list)
    sectors: list[str] = Field(default_factory=list)
    source_types: list[str] = Field(default_factory=list)


class SufficiencyDraft(_LLM):
    sufficient: bool
    reason: str
    missing: list[MissingDraft] = Field(default_factory=list)


class OdinRulings(_LLM):
    """Odin call 1: a ruling on every claim."""

    rulings: list[RulingDraft]
    injection_reports: list[InjectionReport] = Field(default_factory=list)


class OdinAssessment(_LLM):
    """Odin call 2 (after his rulings): ranges, sufficiency, summary, outlook."""

    ranges: list[OdinRange]
    sufficiency: SufficiencyDraft
    executive_summary: str
    outlook_text: str = Field(description="next-quarter outlook")
    outlook_assumptions: list[str]
    evidence_quality_notes: list[str] = Field(default_factory=list)


class OdinVerdict(_LLM):
    """Odin's single merged call: rulings on every claim, ranges, sufficiency, summary, outlook."""

    rulings: list[RulingDraft]
    ranges: list[OdinRange]
    sufficiency: SufficiencyDraft
    executive_summary: str
    outlook_text: str = Field(description="next-quarter outlook")
    outlook_assumptions: list[str]
    evidence_quality_notes: list[str] = Field(default_factory=list)
    injection_reports: list[InjectionReport] = Field(default_factory=list)
    memory_used: list[str] = Field(default_factory=list, description="IDs of your lessons (M-...) that shaped your rulings; empty if none")
    memory_effect: str = Field("", description="how those lessons changed your rulings; empty if none")


class OdinJudgment(BaseModel):
    """Both Odin outputs together (internal; also what scripted test models return)."""

    rulings: list[RulingDraft]
    ranges: list[OdinRange]
    sufficiency: SufficiencyDraft
    executive_summary: str
    outlook_text: str
    outlook_assumptions: list[str]
    evidence_quality_notes: list[str] = Field(default_factory=list)
    injection_reports: list[InjectionReport] = Field(default_factory=list)
