"""Odin Final Intelligence Briefing Generator.

Transforms validated Odin rulings, evidence citations, and deterministic exposure ranges
into the canonical Briefing model and publication-grade Markdown reports.
Strictly grounded in Odin's rulings — zero LLM mental math, zero fabricated citations.
"""

from __future__ import annotations

import datetime
import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple
from pydantic import BaseModel, Field

from backend.models import (
    AgentRole,
    Attack,
    Basis,
    Briefing,
    CaseFile,
    Citation,
    Claim,
    Concession,
    Defense,
    DocMeta,
    Document,
    EventVerificationStatus,
    ExposureRange,
    Ruling,
    SufficiencyResult,
    SufficiencyStatus,
    TradeRow,
    Verdict,
)
from backend.agents.odin import scan_text_for_injections

logger = logging.getLogger("briefing")


def normalize_text(text: str) -> str:
    """Normalizes whitespace and casing for robust text/quote comparison."""
    text = re.sub(r"\s+", " ", text or "")
    return text.strip().lower()


class CitationValidationReport(BaseModel):
    """Detailed validation report for an individual evidence citation."""
    citation: Citation
    is_valid: bool
    canonical_str: str
    pub_date: Optional[str] = None
    tier: Optional[int] = None
    failure_reasons: List[str] = Field(default_factory=list)
    doc_meta: Optional[DocMeta] = None
    paragraph_text: Optional[str] = None


def parse_citation(cit_str: str) -> Optional[Citation]:
    """Parses canonical string '[DOC_ID Pn, YYYY-MM-DD]' or '[TAB#row]' into a Citation model."""
    if not cit_str:
        return None
    cleaned = cit_str.strip()
    if not (cleaned.startswith("[") and cleaned.endswith("]")):
        return None
    inner = cleaned[1:-1].strip()
    if not inner:
        return None

    # Trade row: TAB-001#5 or TAB-001#5, 2027-01-20
    if "#" in inner:
        parts = [p.strip() for p in inner.split(",")]
        return Citation(
            doc_id="",
            trade_row_ref=parts[0],
            pub_date=parts[1] if len(parts) > 1 else None,
        )

    # Document citation: DOC_ID Pn, YYYY-MM-DD or DOC_ID Pn
    match = re.match(r"^([A-Za-z0-9_\-]+)(?:\s+P(\d+))?(?:,\s*(\d{4}-\d{2}-\d{2}))?$", inner)
    if match:
        doc_id = match.group(1)
        p_num = int(match.group(2)) if match.group(2) else None
        pub_date = match.group(3) if match.group(3) else None
        return Citation(
            doc_id=doc_id,
            paragraph_num=p_num,
            pub_date=pub_date,
        )
    return None


def validate_citation_provenance(
    citation: Citation,
    as_of: str,
    doc_store: Dict[str, Document],
    trade_store: Optional[Dict[str, List[TradeRow]]] = None,
    claim: Optional[Claim] = None,
) -> CitationValidationReport:
    """Strictly validates citation against physical document/trade store and as-of clock constraint.
    
    Checks:
    1. Trade table and row existence, undamaged status, and month cutoff.
    2. Document existence in evidence store.
    3. Publication date cutoff (clock constraint against as_of).
    4. Cited publication date matching source metadata (if specified).
    5. Exclusion of formally retracted, superseded, damaged, or duplicate documents.
    6. Specific paragraph existence and non-empty content.
    7. Quote verification (exact/normalized substring matching).
    8. Structural claim support verification (lexical and entity topic overlap).
    """
    failures: List[str] = []

    # 1. Trade row citation branch
    if citation.trade_row_ref:
        parts = citation.trade_row_ref.split("#")
        table_id = parts[0]
        row_num_str = parts[1] if len(parts) > 1 else None

        if not trade_store or table_id not in trade_store:
            failures.append(f"Trade table '{table_id}' not found in trade store.")
            return CitationValidationReport(
                citation=citation,
                is_valid=False,
                canonical_str=f"[{citation.trade_row_ref}]",
                failure_reasons=failures,
            )

        if row_num_str is not None:
            try:
                row_num = int(row_num_str)
                rows = [r for r in trade_store[table_id] if r.row_num == row_num]
                if not rows:
                    failures.append(f"Row #{row_num} not found in trade table '{table_id}'.")
                else:
                    target_row = rows[0]
                    if target_row.is_damaged:
                        failures.append(f"Trade row '{citation.trade_row_ref}' is damaged: {target_row.damage_reason or 'corrupted'}.")
                    if target_row.month and as_of:
                        as_of_ym = as_of[:7]
                        if target_row.month > as_of_ym:
                            failures.append(f"Trade row month {target_row.month} is after as-of month {as_of_ym}.")
            except ValueError:
                failures.append(f"Malformed trade row reference: '{citation.trade_row_ref}'.")

        is_v = len(failures) == 0
        return CitationValidationReport(
            citation=citation,
            is_valid=is_v,
            canonical_str=f"[{citation.trade_row_ref}]",
            tier=1,
            failure_reasons=failures,
        )

    # 2. Document citation branch
    doc_id = citation.doc_id
    if not doc_id or doc_id not in doc_store:
        failures.append(f"Referenced document '{doc_id}' does not exist in evidence store.")
        return CitationValidationReport(
            citation=citation,
            is_valid=False,
            canonical_str=f"[{doc_id} P?]",
            failure_reasons=failures,
        )

    doc = doc_store[doc_id]
    meta = doc.meta
    pub_date = meta.PUB_DATE
    tier = meta.RELIABILITY

    # Clock cutoff validation
    if pub_date and as_of and pub_date > as_of:
        failures.append(f"Clock violation: publication date {pub_date} is after investigation as-of {as_of}.")

    # Cited publication date match verification
    if citation.pub_date and pub_date and citation.pub_date != pub_date:
        failures.append(f"Cited publication date '{citation.pub_date}' does not match source publication date '{pub_date}'.")

    # Document integrity checks
    if doc.is_retracted:
        failures.append(f"Document '{doc_id}' was formally retracted.")
    if doc.superseded_by:
        failures.append(f"Document '{doc_id}' is superseded by correction '{doc.superseded_by}'.")
    if doc.is_damaged:
        failures.append(f"Document '{doc_id}' is damaged or unreadable.")
    if doc.is_duplicate:
        failures.append(f"Document '{doc_id}' is a duplicate of '{doc.duplicate_of or 'earlier source'}'.")

    # Paragraph verification
    p_num = citation.paragraph_num
    p_text = None
    if p_num is None:
        failures.append(f"Citation for document '{doc_id}' is missing a specific paragraph reference.")
    elif p_num not in doc.paragraphs:
        failures.append(f"Paragraph P{p_num} does not exist in document '{doc_id}' (available: {sorted(list(doc.paragraphs.keys()))}).")
    else:
        p_text = doc.paragraphs[p_num]
        if not p_text.strip():
            failures.append(f"Paragraph P{p_num} in document '{doc_id}' is empty.")

        # Quote match verification if quote is supplied
        if citation.quoted_text:
            norm_q = normalize_text(citation.quoted_text)
            norm_p = normalize_text(p_text)
            if norm_q not in norm_p:
                failures.append(f"Quoted excerpt not found in document '{doc_id}' P{p_num}.")

        # Claim support check (structural keyword/entity verification)
        if claim and claim.statement and p_text:
            stop_words = {
                "the", "and", "for", "with", "from", "that", "this", "over", "into",
                "been", "have", "were", "what", "where", "when", "which", "there",
                "their", "about", "will", "would", "could", "should", "than", "then",
            }
            # Substantive content terms from statement
            claim_statement_terms = {
                w for w in re.findall(r"[a-z0-9\-]+", claim.statement.lower())
                if len(w) > 3 and w not in stop_words
            }
            # Sector term if not generic
            if claim.sector and claim.sector.lower() not in ("general", "unknown"):
                claim_statement_terms.add(claim.sector.lower())

            para_terms = set(re.findall(r"[a-z0-9\-]+", p_text.lower()))
            if claim_statement_terms and not (claim_statement_terms & para_terms):
                failures.append(
                    f"Evidence paragraph P{p_num} in document '{doc_id}' lacks supporting content for claim '{claim.claim_id}': "
                    f"zero substantive keyword or sector overlap with claim statement."
                )

    is_valid = len(failures) == 0
    p_str = f"P{p_num}" if p_num is not None else "P?"
    date_part = f", {pub_date}" if pub_date else ""
    canonical = f"[{doc_id} {p_str}{date_part}]"

    return CitationValidationReport(
        citation=citation,
        is_valid=is_valid,
        canonical_str=canonical,
        pub_date=pub_date,
        tier=tier,
        failure_reasons=failures,
        doc_meta=meta,
        paragraph_text=p_text,
    )


def validate_citation_str(
    cit_str: str,
    as_of: str,
    doc_store: Dict[str, Document],
    trade_store: Optional[Dict[str, List[TradeRow]]] = None,
    claim: Optional[Claim] = None,
) -> CitationValidationReport:
    """Parses and validates a citation string against document/trade store and as-of constraints."""
    parsed = parse_citation(cit_str)
    if not parsed:
        return CitationValidationReport(
            citation=Citation(doc_id="MALFORMED"),
            is_valid=False,
            canonical_str=cit_str,
            failure_reasons=[f"Malformed citation format: '{cit_str}'. Expected '[DOC_ID Pn, YYYY-MM-DD]' or '[TAB#row]'."],
        )
    return validate_citation_provenance(
        citation=parsed,
        as_of=as_of,
        doc_store=doc_store,
        trade_store=trade_store,
        claim=claim,
    )


class BriefingGenerator:
    """Constructs verifiable intelligence briefings grounded strictly in Odin's rulings."""

    def __init__(
        self,
        case_file: CaseFile,
        rulings: List[Ruling],
        exposure_ranges: Optional[List[ExposureRange]] = None,
        doc_store: Optional[Dict[str, Document]] = None,
        trade_store: Optional[Dict[str, List[TradeRow]]] = None,
        claims: Optional[List[Claim]] = None,
        attacks: Optional[List[Attack]] = None,
        defenses: Optional[List[Defense]] = None,
        concessions: Optional[List[Concession]] = None,
        sufficiency_result: Optional[SufficiencyResult] = None,
        overall_status: str = "ready_for_briefing",
        incomplete_reason: Optional[str] = None,
        run_count: int = 1,
        max_runs: int = 3,
        thor_failed: bool = False,
        loki_failed: bool = False,
        token_usage: int = 0,
        tool_call_counts: Optional[Dict[str, int]] = None,
    ):
        self.case_file = case_file
        self.rulings = rulings
        self.exposure_ranges = exposure_ranges or []
        self.doc_store = doc_store or {}
        self.trade_store = trade_store or {}
        self.claims_map: Dict[str, Claim] = {c.claim_id: c for c in (claims or [])}
        self.attacks = attacks or []
        self.defenses = defenses or []
        self.concessions = concessions or []
        self.sufficiency_result = sufficiency_result
        self.overall_status = overall_status
        self.incomplete_reason = incomplete_reason
        self.run_count = run_count
        self.max_runs = max_runs
        self.thor_failed = thor_failed
        self.loki_failed = loki_failed
        self.token_usage = token_usage
        self.tool_call_counts = tool_call_counts or {}

        # Cache for validated citations to avoid redundant checks
        self._citation_cache: Dict[str, CitationValidationReport] = {}
        self._validation_failures: List[Dict[str, Any]] = []

    def _validate_citation(self, citation: Citation, claim: Optional[Claim] = None) -> CitationValidationReport:
        key = f"{citation.doc_id}:{citation.paragraph_num}:{citation.trade_row_ref}:{citation.quoted_text}:{citation.pub_date}:{claim.claim_id if claim else ''}"
        if key not in self._citation_cache:
            report = validate_citation_provenance(
                citation=citation,
                as_of=self.case_file.as_of,
                doc_store=self.doc_store,
                trade_store=self.trade_store,
                claim=claim,
            )
            self._citation_cache[key] = report
            if not report.is_valid:
                self._validation_failures.append({
                    "citation": report.canonical_str,
                    "claim_id": claim.claim_id if claim else None,
                    "reasons": report.failure_reasons,
                })
        return self._citation_cache[key]

    def build_executive_summary(self) -> str:
        """Section A: Executive Summary."""
        cf = self.case_file
        as_of = cf.as_of

        # 1. Event verification special handling
        if cf.verification_status == EventVerificationStatus.NOT_REAL:
            return (
                f"EXECUTIVE SUMMARY — EVENT NOT REAL / COUNTERFEIT NOTICE\n"
                f"Investigation of alleged supply chain disruption '{cf.case_id}' as of {as_of}.\n\n"
                f"DETERMINATION: Event verification confirmed that the disruption event is NOT REAL "
                f"({cf.verification_reason or 'Fabricated or decoy event notice'}). "
                f"No actual commercial trade disruption occurred. Zero net exposure across all examined country-sector pairs. "
                f"The trial concluded early without conducting advocate hearings."
            )

        event_qualifier = ""
        if cf.verification_status == EventVerificationStatus.UNCERTAIN:
            event_qualifier = (
                "WARNING: Official verification of the disruption event remains UNCERTAIN as of the cutoff date. "
                "All exposure findings are provisional and contingent upon formal event confirmation.\n\n"
            )

        # 2. Rulings breakdown
        est_count = sum(1 for r in self.rulings if r.verdict == Verdict.ESTABLISHED)
        con_count = sum(1 for r in self.rulings if r.verdict == Verdict.CONTESTED)
        cnc_count = sum(1 for r in self.rulings if r.verdict == Verdict.CONCEDED)
        rej_count = sum(1 for r in self.rulings if r.verdict == Verdict.REJECTED)

        # 3. Completion status statement
        if self.overall_status == "ready_for_briefing":
            status_desc = "The trial reached evidence sufficiency and concluded successfully."
        elif self.overall_status == "send_back_loop":
            status_desc = f"The trial is awaiting further research from Heimdall (Send-Back Run {self.run_count})."
        elif self.overall_status in ("terminated_limits_exhausted", "incomplete"):
            status_desc = f"The investigation was stopped due to execution/resource limits ({self.incomplete_reason or 'Run or budget limit reached'})."
        else:
            status_desc = f"Investigation status: {self.overall_status} ({self.incomplete_reason or ''})."

        summary_lines = [
            f"{event_qualifier}Investigation of supply chain disruption event '{cf.case_id}' ({cf.query}) as of {as_of}.",
            f"Trial Status: {status_desc}",
            f"Judicial Outcomes: Odin issued {len(self.rulings)} binding rulings ({est_count} established, {con_count} contested, {cnc_count} conceded, {rej_count} rejected).",
        ]

        if est_count > 0:
            est_topics = [
                self.claims_map[r.claim_id].statement[:60] + "..."
                for r in self.rulings
                if r.verdict == Verdict.ESTABLISHED and r.claim_id in self.claims_map
            ]
            summary_lines.append(f"Key Established Findings: {'; '.join(est_topics[:3])}.")
        else:
            summary_lines.append("Key Established Findings: No submitted disruption severity claims met the evidentiary threshold to be ruled established.")

        if con_count > 0:
            summary_lines.append(f"Material Uncertainties: {con_count} claims remain contested due to conflicting evidence or missing corroboration.")

        return "\n\n".join(summary_lines)

    def build_established_findings(self) -> List[Dict[str, Any]]:
        """Section B: Established Findings."""
        results = []
        for r in self.rulings:
            if r.verdict != Verdict.ESTABLISHED:
                continue

            claim = self.claims_map.get(r.claim_id)
            statement = claim.statement if claim else r.rationale

            # Validate and format canonical citations
            canonical_cits = []
            evidence_excerpts = []
            for cit in r.admissible_citations:
                rep = self._validate_citation(cit, claim=claim)
                if rep.is_valid:
                    canonical_cits.append(rep.canonical_str)
                    if rep.paragraph_text:
                        evidence_excerpts.append(rep.paragraph_text[:120] + "...")

            # If all citations failed validation for a sourced_fact finding, mark finding explicitly
            if r.basis == Basis.SOURCED_FACT and not canonical_cits:
                statement = f"[INSUFFICIENTLY SUPPORTED - Citations Failed Validation] {statement}"

            results.append({
                "claim_id": r.claim_id,
                "finding": statement,
                "basis": r.basis.value,
                "country": claim.country if claim else "general",
                "sector": claim.sector if claim else "general",
                "posture": claim.posture if claim else "high",
                "admissible_citations": canonical_cits,
                "evidence_excerpts": evidence_excerpts,
                "rationale": r.rationale,
            })
        return results

    def build_contested_findings(self) -> List[Dict[str, Any]]:
        """Section C: Contested Findings."""
        results = []
        for r in self.rulings:
            if r.verdict != Verdict.CONTESTED:
                continue

            claim = self.claims_map.get(r.claim_id)
            statement = claim.statement if claim else r.rationale

            canonical_cits = []
            for cit in r.admissible_citations:
                rep = self._validate_citation(cit, claim=claim)
                if rep.is_valid:
                    canonical_cits.append(rep.canonical_str)

            # Look up opposing cross-exam attacks against this claim
            attacks_against = [
                a.argument for a in self.attacks if a.target_claim_id == r.claim_id
            ]

            results.append({
                "claim_id": r.claim_id,
                "disputed_statement": statement,
                "basis": r.basis.value,
                "country": claim.country if claim else "general",
                "sector": claim.sector if claim else "general",
                "citations": canonical_cits,
                "rationale": r.rationale,
                "opposing_arguments": attacks_against,
                "missing_evidence_to_resolve": "Independent corroboration or baseline trade verification required.",
            })
        return results

    def build_conceded_findings(self) -> List[Dict[str, Any]]:
        """Section D: Conceded Findings."""
        results = []
        for r in self.rulings:
            if r.verdict != Verdict.CONCEDED:
                continue

            claim = self.claims_map.get(r.claim_id)
            statement = claim.statement if claim else r.rationale
            conceded_by = claim.agent.value.title() if claim else "Advocate"

            matching_conc = next((c for c in self.concessions if c.claim_id == r.claim_id), None)
            conc_rationale = matching_conc.rationale if matching_conc else r.rationale

            results.append({
                "claim_id": r.claim_id,
                "conceded_by": conceded_by,
                "statement": statement,
                "rationale": conc_rationale,
            })
        return results

    def build_rejected_findings(self) -> List[Dict[str, Any]]:
        """Section E: Rejected Findings."""
        results = []
        for r in self.rulings:
            if r.verdict != Verdict.REJECTED:
                continue

            claim = self.claims_map.get(r.claim_id)
            statement = claim.statement if claim else r.rationale

            results.append({
                "claim_id": r.claim_id,
                "statement": statement,
                "disqualified_reason": r.disqualified_reason or "Inadmissible evidence or clock violation",
                "rationale": r.rationale,
                "evidentiary_note": "Rejection confirms lack of admissible support; it does not affirm the converse claim.",
            })
        return results

    def build_exposure_table(self) -> List[ExposureRange]:
        """Section F: Exposure Analysis Table."""
        # Use existing Phase 2 exposure ranges directly
        # If Thor or Loki failed, ensure explicit representation without fabricating values
        final_table = []
        for er in self.exposure_ranges:
            thor_r = er.thor_range if not self.thor_failed else None
            loki_r = er.loki_range if not self.loki_failed else None

            assumptions = list(er.assumptions)
            if self.thor_failed and "Thor advocate failed to return a valid position" not in assumptions:
                assumptions.append("Thor advocate failed to return a valid position.")
            if self.loki_failed and "Loki advocate failed to return a valid position" not in assumptions:
                assumptions.append("Loki advocate failed to return a valid position.")

            final_table.append(
                ExposureRange(
                    country=er.country,
                    sector=er.sector,
                    thor_range=thor_r,
                    loki_range=loki_r,
                    odin_range=er.odin_range,
                    status=er.status,
                    rationale=er.rationale,
                    established_claim_ids=er.established_claim_ids,
                    contested_claim_ids=er.contested_claim_ids,
                    conceded_claim_ids=er.conceded_claim_ids,
                    rejected_claim_ids=er.rejected_claim_ids,
                    trade_row_refs=er.trade_row_refs,
                    assumptions=assumptions,
                )
            )
        return final_table

    def build_outlook(self) -> str:
        """Section G: Outlook and Implications."""
        established = [r for r in self.rulings if r.verdict == Verdict.ESTABLISHED]
        contested = [r for r in self.rulings if r.verdict == Verdict.CONTESTED]

        lines = [
            "### 1. Established Facts & Baseline Trajectory",
        ]
        if established:
            for r in established:
                claim = self.claims_map.get(r.claim_id)
                lines.append(f"- {claim.country if claim else 'Target'} ({claim.sector if claim else 'trade'}): {r.rationale}")
        else:
            lines.append("- No disruption parameters were conclusively established by Tier 1-3 evidence.")

        lines.append("\n### 2. Inferences Supported by Admissible Evidence")
        inferences = [r for r in established if r.basis == Basis.INFERENCE]
        if inferences:
            for r in inferences:
                lines.append(f"- Logical inference grounded in validated baseline: {r.rationale}")
        else:
            lines.append("- No secondary inferences have been validated as established.")

        lines.append("\n### 3. Contested Issues & Critical Sensitivities")
        if contested:
            for r in contested:
                lines.append(f"- Claim {r.claim_id} remains contested: {r.rationale}")
        else:
            lines.append("- No contested disputes remain unresolved.")

        lines.append("\n### 4. Important Unknowns")
        if self.sufficiency_result and self.sufficiency_result.unresolved_gaps:
            for g in self.sufficiency_result.unresolved_gaps:
                lines.append(f"- Execution limitation: {g}")
        else:
            lines.append("- All required baseline data and event verifications are accounted for on record.")

        return "\n".join(lines)

    def build_verification_summary(self) -> Dict[str, Any]:
        """Section H: Verification Summary."""
        verdict_counts = {
            "established": sum(1 for r in self.rulings if r.verdict == Verdict.ESTABLISHED),
            "contested": sum(1 for r in self.rulings if r.verdict == Verdict.CONTESTED),
            "conceded": sum(1 for r in self.rulings if r.verdict == Verdict.CONCEDED),
            "rejected": sum(1 for r in self.rulings if r.verdict == Verdict.REJECTED),
        }

        # Count sources and tiers from admissible citations in rulings
        cited_doc_ids: Set[str] = set()
        tier_counts = {1: 0, 2: 0, 3: 0, 4: 0}
        for r in self.rulings:
            for cit in r.admissible_citations:
                if cit.doc_id in self.doc_store:
                    cited_doc_ids.add(cit.doc_id)
                    t = self.doc_store[cit.doc_id].meta.RELIABILITY
                    if t in tier_counts:
                        tier_counts[t] += 1

        total_cits = len(self._citation_cache)
        valid_cits = sum(1 for rep in self._citation_cache.values() if rep.is_valid)
        invalid_cits = sum(1 for rep in self._citation_cache.values() if not rep.is_valid)

        # Check clock compliance
        clock_compliant = not any(
            "Clock violation" in f.get("reasons", [""])[0] for f in self._validation_failures
        )

        return {
            "rulings_count": len(self.rulings),
            "verdict_breakdown": verdict_counts,
            "total_citations_checked": total_cits,
            "valid_citations_count": valid_cits,
            "invalid_citations_count": invalid_cits,
            "citation_failures": self._validation_failures[:10],
            "sources_used_count": len(cited_doc_ids),
            "reliability_tier_distribution": {f"Tier {k}": v for k, v in tier_counts.items()},
            "as_of_date_compliance": clock_compliant,
            "as_of_date": self.case_file.as_of,
            "trial_completion_status": self.overall_status,
            "incomplete_reason": self.incomplete_reason,
            "execution_metrics": {
                "runs_executed": self.run_count,
                "max_runs": self.max_runs,
                "token_usage": self.token_usage,
                "tool_call_counts": self.tool_call_counts,
            },
            "advocate_status": {
                "thor": "failed" if self.thor_failed else "normal",
                "loki": "failed" if self.loki_failed else "normal",
            },
        }

    def build_traps_and_sources(self) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        """Section I: Sources and Traps Caught."""
        # 1. Sources used in established or contested rulings
        cited_doc_ids: Set[str] = set()
        for r in self.rulings:
            if r.verdict in (Verdict.ESTABLISHED, Verdict.CONTESTED):
                for cit in r.admissible_citations:
                    if cit.doc_id in self.doc_store:
                        cited_doc_ids.add(cit.doc_id)

        sources_list = []
        for doc_id in sorted(list(cited_doc_ids)):
            meta = self.doc_store[doc_id].meta
            sources_list.append({
                "doc_id": meta.DOC_ID,
                "title": meta.TITLE or f"Document {meta.DOC_ID}",
                "pub_date": meta.PUB_DATE,
                "reliability_tier": meta.RELIABILITY,
                "source_name": meta.SOURCE_NAME or "Official",
                "country": meta.COUNTRY,
                "sector": meta.SECTOR,
            })

        # 2. Actual traps detected across the document store
        traps: Dict[str, Any] = {
            "prompt_injections_detected": [],
            "retractions_caught": [],
            "superseded_corrections": [],
            "duplicates_detected": [],
            "damaged_records_excluded": [],
            "clock_violations_rejected": [],
            "tier_4_only_rejections": [],
        }

        for doc_id, doc in self.doc_store.items():
            if not doc.injection_detected:
                full_text = doc.raw_text or " ".join(doc.paragraphs.values())
                is_inj, details = scan_text_for_injections(full_text)
                if is_inj:
                    doc.injection_detected = True
                    doc.injection_details = details
            if doc.injection_detected:
                traps["prompt_injections_detected"].append({
                    "doc_id": doc_id,
                    "details": doc.injection_details or "Prompt injection instructions detected in evidence",
                })
            if doc.is_retracted:
                traps["retractions_caught"].append({
                    "doc_id": doc_id,
                    "date": doc.meta.PUB_DATE,
                })
            if doc.superseded_by:
                traps["superseded_corrections"].append({
                    "doc_id": doc_id,
                    "superseded_by": doc.superseded_by,
                })
            if doc.is_duplicate:
                traps["duplicates_detected"].append({
                    "doc_id": doc_id,
                    "duplicate_of": doc.duplicate_of,
                })
            if doc.is_damaged:
                traps["damaged_records_excluded"].append({"doc_id": doc_id})
            if doc.meta.PUB_DATE and self.case_file.as_of and doc.meta.PUB_DATE > self.case_file.as_of:
                traps["clock_violations_rejected"].append({
                    "doc_id": doc_id,
                    "pub_date": doc.meta.PUB_DATE,
                    "as_of": self.case_file.as_of,
                })

        # Check for damaged trade rows
        for tid, rows in self.trade_store.items():
            for r in rows:
                if r.is_damaged:
                    traps["damaged_records_excluded"].append({
                        "trade_row_ref": f"{r.table_id}#{r.row_num}",
                        "damage_reason": r.damage_reason or "Corrupted trade data",
                    })

        # Check for Tier-4-only rejected rulings
        for r in self.rulings:
            if r.verdict == Verdict.REJECTED and r.disqualified_reason and "tier_4" in r.disqualified_reason.lower():
                traps["tier_4_only_rejections"].append({
                    "claim_id": r.claim_id,
                    "disqualified_reason": r.disqualified_reason,
                })

        return traps, sources_list

    def build_markdown_report(
        self,
        exec_summary: str,
        established: List[Dict[str, Any]],
        contested: List[Dict[str, Any]],
        conceded: List[Dict[str, Any]],
        rejected: List[Dict[str, Any]],
        exposure_table: List[ExposureRange],
        outlook: str,
        verification_summary: Dict[str, Any],
        traps: Dict[str, Any],
        sources: List[Dict[str, Any]],
    ) -> str:
        """Section J: Full human-readable Markdown Report."""
        cf = self.case_file
        md = [
            f"# TRIAL OF THE NINE REALMS — JUDICIAL INTELLIGENCE BRIEFING",
            f"**Case ID**: `{cf.case_id}` | **As-of Date**: `{cf.as_of}` | **Target Query**: {cf.query}",
            f"**Event Verification**: `{cf.verification_status.value.upper()}` | **Trial Status**: `{self.overall_status.upper()}`\n",
            "---",
            "## A. Executive Summary\n",
            exec_summary,
            "\n---",
            "## B. Established Findings\n",
        ]

        if established:
            for item in established:
                cits_str = " ".join(item["admissible_citations"]) if item["admissible_citations"] else "[No Citation]"
                md.append(f"### Claim `{item['claim_id']}` ({item['country']} - {item['sector']})")
                md.append(f"- **Statement**: {item['finding']}")
                md.append(f"- **Basis**: `{item['basis']}` | **Admissible Citations**: {cits_str}")
                md.append(f"- **Judicial Rationale**: {item['rationale']}\n")
        else:
            md.append("*(Zero claims established by admissible Tier 1-3 evidence.)*\n")

        md.extend([
            "---",
            "## C. Contested Findings\n",
        ])
        if contested:
            for item in contested:
                cits_str = " ".join(item["citations"]) if item["citations"] else "[No Citation]"
                md.append(f"### Claim `{item['claim_id']}` ({item['country']} - {item['sector']})")
                md.append(f"- **Disputed Statement**: {item['disputed_statement']}")
                md.append(f"- **Citations on Record**: {cits_str}")
                md.append(f"- **Judicial Rationale**: {item['rationale']}")
                if item["opposing_arguments"]:
                    md.append(f"- **Opposing Arguments**: {'; '.join(item['opposing_arguments'])}")
                md.append(f"- **Resolution Gap**: {item['missing_evidence_to_resolve']}\n")
        else:
            md.append("*(Zero claims contested.)*\n")

        md.extend([
            "---",
            "## D. Conceded Findings\n",
        ])
        if conceded:
            for item in conceded:
                md.append(f"- **Claim `{item['claim_id']}`** (Conceded by {item['conceded_by']}): {item['statement']} — *Rationale*: {item['rationale']}")
        else:
            md.append("*(Zero explicit concessions on record.)*\n")

        md.extend([
            "---",
            "## E. Rejected Findings\n",
        ])
        if rejected:
            for item in rejected:
                md.append(f"- **Claim `{item['claim_id']}`**: {item['statement']}")
                md.append(f"  - *Disqualification Reason*: `{item['disqualified_reason']}`")
                md.append(f"  - *Judicial Rationale*: {item['rationale']}")
                md.append(f"  - *Note*: {item['evidentiary_note']}\n")
        else:
            md.append("*(Zero claims rejected.)*\n")

        md.extend([
            "---",
            "## F. Exposure Analysis Table\n",
            "| Country | Sector | Thor Range (High) | Loki Range (Limited) | Odin Adjudicated Range | Status | Trade Baselines |",
            "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
        ])

        if exposure_table:
            for er in exposure_table:
                thor_s = f"[{er.thor_range[0]}, {er.thor_range[1]}]%" if er.thor_range else "None (Failed/Missing)"
                loki_s = f"[{er.loki_range[0]}, {er.loki_range[1]}]%" if er.loki_range else "None (Failed/Missing)"
                odin_s = f"[{er.odin_range[0]}, {er.odin_range[1]}]" if er.odin_range else "**UNRESOLVED**"
                rows_s = ", ".join(er.trade_row_refs) if er.trade_row_refs else "None"
                md.append(f"| {er.country} | {er.sector} | {thor_s} | {loki_s} | {odin_s} | `{er.status.upper()}` | {rows_s} |")
        else:
            md.append("| *(None)* | *(None)* | *(None)* | *(None)* | *(None)* | `UNRESOLVED` | *(None)* |")

        md.extend([
            "\n---",
            "## G. Outlook and Implications\n",
            outlook,
            "\n---",
            "## H. Verification & Execution Summary\n",
            f"- **Rulings Total**: {verification_summary['rulings_count']} ({verification_summary['verdict_breakdown']})",
            f"- **Citations Validated**: {verification_summary['valid_citations_count']} valid, {verification_summary['invalid_citations_count']} invalid (Total: {verification_summary['total_citations_checked']})",
            f"- **Sources Used**: {verification_summary['sources_used_count']} documents ({verification_summary['reliability_tier_distribution']})",
            f"- **As-Of Compliance**: `{'PASS' if verification_summary['as_of_date_compliance'] else 'FAIL'}` (Cutoff: {verification_summary['as_of_date']})",
            f"- **Execution Metrics**: Runs={verification_summary['execution_metrics']['runs_executed']}/{verification_summary['execution_metrics']['max_runs']}, Tokens={verification_summary['execution_metrics']['token_usage']}, Advocates: Thor={verification_summary['advocate_status']['thor']}, Loki={verification_summary['advocate_status']['loki']}",
            "\n---",
            "## I. Sources & Traps Caught\n",
            "### Sources on Record",
        ])

        if sources:
            for s in sources:
                md.append(f"- `[{s['doc_id']}]` **{s['title']}** (Pub: {s['pub_date']}, Tier {s['reliability_tier']}, {s['source_name']})")
        else:
            md.append("*(Zero sources cited in final findings.)*")

        md.append("\n### Traps & Data Quality Exclusions Caught")
        injs = traps.get("prompt_injections_detected", [])
        if injs:
            md.append(f"- **Prompt Injections Caught**: {len(injs)} injection attempts isolated ({', '.join(i['doc_id'] for i in injs)})")
        rets = traps.get("retractions_caught", [])
        if rets:
            md.append(f"- **Retractions Caught**: {len(rets)} retracted documents excluded ({', '.join(r['doc_id'] for r in rets)})")
        dups = traps.get("duplicates_detected", [])
        if dups:
            md.append(f"- **Duplicates Caught**: {len(dups)} duplicate sources disqualified ({', '.join(d['doc_id'] for d in dups)})")
        dams = traps.get("damaged_records_excluded", [])
        if dams:
            md.append(f"- **Damaged Records Excluded**: {len(dams)} unreadable/damaged records excluded")
        t4s = traps.get("tier_4_only_rejections", [])
        if t4s:
            md.append(f"- **Tier 4 Weak Evidence Rejections**: {len(t4s)} claims rejected for lack of corroboration ({', '.join(t['claim_id'] for t in t4s)})")

        if not any([injs, rets, dups, dams, t4s]):
            md.append("- *(Zero adversarial traps or corrupted records detected in evidence corpus.)*")

        return "\n".join(md)

    def generate(self) -> Briefing:
        """Assembles the final validated Briefing model and Markdown document."""
        # Pre-validate all citations from rulings with claim context
        for r in self.rulings:
            claim = self.claims_map.get(r.claim_id)
            for cit in r.admissible_citations:
                self._validate_citation(cit, claim=claim)
            for cit in r.inadmissible_citations:
                self._validate_citation(cit, claim=claim)

        exec_summary = self.build_executive_summary()
        established = self.build_established_findings()
        contested = self.build_contested_findings()
        conceded = self.build_conceded_findings()
        rejected = self.build_rejected_findings()
        exposure_table = self.build_exposure_table()
        outlook = self.build_outlook()
        verification_summary = self.build_verification_summary()
        traps, sources = self.build_traps_and_sources()

        markdown_report = self.build_markdown_report(
            exec_summary=exec_summary,
            established=established,
            contested=contested,
            conceded=conceded,
            rejected=rejected,
            exposure_table=exposure_table,
            outlook=outlook,
            verification_summary=verification_summary,
            traps=traps,
            sources=sources,
        )

        # Assumptions list
        assumptions = []
        for er in exposure_table:
            assumptions.extend(er.assumptions)
        # Deduplicate assumptions
        unique_assumptions = list(dict.fromkeys(assumptions))

        return Briefing(
            case_id=self.case_file.case_id,
            as_of=self.case_file.as_of,
            event_verification={
                "status": self.case_file.verification_status.value,
                "reason": self.case_file.verification_reason,
                "active_event_id": self.case_file.active_event_id,
            },
            executive_summary=exec_summary,
            established_findings=established,
            contested_findings=contested,
            conceded_claims=conceded,
            rejected_claims=rejected,
            exposure_table=exposure_table,
            next_quarter_outlook=outlook,
            assumptions=unique_assumptions,
            verification_summary=verification_summary,
            traps_and_data_quality=traps,
            sources=sources,
            markdown_content=markdown_report,
        )


def generate_briefing(
    case_file: CaseFile,
    rulings: List[Ruling],
    exposure_ranges: Optional[List[ExposureRange]] = None,
    doc_store: Optional[Dict[str, Document]] = None,
    trade_store: Optional[Dict[str, List[TradeRow]]] = None,
    claims: Optional[List[Claim]] = None,
    attacks: Optional[List[Attack]] = None,
    defenses: Optional[List[Defense]] = None,
    concessions: Optional[List[Concession]] = None,
    sufficiency_result: Optional[SufficiencyResult] = None,
    overall_status: str = "ready_for_briefing",
    incomplete_reason: Optional[str] = None,
    run_count: int = 1,
    max_runs: int = 3,
    thor_failed: bool = False,
    loki_failed: bool = False,
    token_usage: int = 0,
    tool_call_counts: Optional[Dict[str, int]] = None,
) -> Briefing:
    """Convenience function to generate a validated Briefing from trial artifacts."""
    gen = BriefingGenerator(
        case_file=case_file,
        rulings=rulings,
        exposure_ranges=exposure_ranges,
        doc_store=doc_store,
        trade_store=trade_store,
        claims=claims,
        attacks=attacks,
        defenses=defenses,
        concessions=concessions,
        sufficiency_result=sufficiency_result,
        overall_status=overall_status,
        incomplete_reason=incomplete_reason,
        run_count=run_count,
        max_runs=max_runs,
        thor_failed=thor_failed,
        loki_failed=loki_failed,
        token_usage=token_usage,
        tool_call_counts=tool_call_counts,
    )
    return gen.generate()
