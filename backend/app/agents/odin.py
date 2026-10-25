"""Odin Agent — Final Judicial Adjudication Engine in the Trial of the Nine Realms courtroom."""

import logging
from typing import Any, Optional, Literal

from backend.app.schemas.evidence import EvidenceReference, Document
from backend.app.schemas.claim import Claim, ExposureEstimate
from backend.app.schemas.debate import CrossExamination, Concession
from backend.app.schemas.debate_result import DebateResult
from backend.app.schemas.odin_result import ClaimRuling, OdinResult
from backend.app.services.retrieval import BaseRetrievalService
from backend.app.services.citations import CitationValidator
from backend.app.services.logging_service import StructuredLogger

logger = logging.getLogger("ragnarok.odin")


class OdinAgent:
    """
    Odin, the All-Father: Chief Magistrate of the Trial of the Nine Realms.

    Responsibilities:
      1. Consumes completed debate deliverables (Loki & Thor round outputs, Heimdall verification, attacks, concessions).
      2. Evaluates each material claim independently against the evidentiary record and adversarial scrutiny.
      3. Distinguishes sourced facts (directly stated in documents) from inferences (derived by reasoning).
      4. Issues a structured ruling for every claim: 'established', 'contested', or 'conceded'.
      5. Enforces evidence admissibility: clock cutoff (as_of_date), retraction detection, tier credibility (ATL-0012).
      6. Preserves unresolved contradictions rather than picking sides arbitrarily.
      7. Treats concessions objectively: records what was conceded without falsely treating it as automatic proof of the opposing claim.
      8. Evaluates evidence sufficiency for the case.
      9. Produces a structured OdinResult and updates CaseFile.judicial_rulings.
    """

    def __init__(
        self,
        retrieval_service: Optional[BaseRetrievalService] = None,
        logger_service: Optional[StructuredLogger] = None,
    ):
        self.retrieval = retrieval_service
        self.logger = logger_service or StructuredLogger(agent_name="odin")

    # -------------------------------------------------------------------------
    # Public Adjudication Interface
    # -------------------------------------------------------------------------

    def adjudicate_debate(self, debate_result: DebateResult) -> OdinResult:
        """
        Execute Odin's judicial evaluation of the completed courtroom debate.
        Produces a structured OdinResult with itemized rulings for every material claim.
        """
        if debate_result is None:
            raise ValueError("DebateResult cannot be None for Odin adjudication.")

        case_id = getattr(debate_result, "case_id", "UNKNOWN_CASE")
        as_of_date = getattr(debate_result, "as_of_date", "1970-01-01")
        run_no = getattr(debate_result, "run_number", 1) or 1

        self.logger.log_event("odin_adjudication_started", case_id, {
            "as_of_date": as_of_date,
            "run_number": run_no,
            "debate_status": debate_result.status,
            "claims_count": len(debate_result.claims),
            "attacks_count": len(debate_result.attacks),
            "concessions_count": len(debate_result.concessions),
        })

        # Safeguard: Do not adjudicate if debate failed with an uncontained error
        if debate_result.status == "error":
            err_msg = f"Cannot adjudicate debate {case_id}: Debate terminated with error in stage '{debate_result.failed_stage}'."
            logger.error(err_msg)
            return OdinResult(
                agent="odin",
                case_id=case_id,
                as_of_date=as_of_date,
                run_number=run_no,
                adjudication_status="error",
                claim_rulings=[],
                established_claims=[],
                contested_claims=[],
                conceded_claims=[],
                unresolved_disputes=[],
                evidence_limitations=["Debate failed prior to judicial adjudication."],
                evidence_examined=[],
                is_evidence_sufficient=False,
                summary=f"Judicial adjudication halted: {err_msg}",
                error_message=err_msg,
            )

        evidence_examined: set[str] = set()
        unresolved_disputes: list[str] = []
        evidence_limitations: list[str] = []

        try:
            # 1. Gather all material claims submitted across debate rounds
            all_claims = self._collect_claims(debate_result)

            if not all_claims:
                return OdinResult(
                    agent="odin",
                    case_id=case_id,
                    as_of_date=as_of_date,
                    run_number=run_no,
                    adjudication_status="insufficient_evidence",
                    claim_rulings=[],
                    established_claims=[],
                    contested_claims=[],
                    conceded_claims=[],
                    unresolved_disputes=["Zero claims were submitted for judicial ruling."],
                    evidence_limitations=["No material claims presented to the court."],
                    evidence_examined=[],
                    is_evidence_sufficient=False,
                    summary="Odin Judicial Ruling: No claims were submitted by either advocate. Evidence is insufficient.",
                    error_message=None,
                )

            # 2. Adjudicate each claim independently
            claim_rulings: list[ClaimRuling] = []
            for claim in all_claims:
                ruling = self._evaluate_single_claim(
                    claim=claim,
                    debate_result=debate_result,
                    as_of_date=as_of_date,
                    evidence_examined=evidence_examined,
                    unresolved_disputes=unresolved_disputes,
                    evidence_limitations=evidence_limitations,
                )
                claim_rulings.append(ruling)

            # 3. Categorize ruling lists
            established_claims = [r.claim_id for r in claim_rulings if r.ruling == "established"]
            contested_claims = [r.claim_id for r in claim_rulings if r.ruling == "contested"]
            conceded_claims = [r.claim_id for r in claim_rulings if r.ruling == "conceded"]

            # 4. Determine evidence sufficiency
            # Evidence is sufficient if core material claims are established and key evidence is not missing
            has_established = len(established_claims) > 0
            has_excessive_unsupported = any("lacks admissible" in r.reasoning.lower() for r in claim_rulings if r.claim_id.endswith("C01"))
            is_evidence_sufficient = has_established and not has_excessive_unsupported

            # 5. Build judicial executive summary
            summary = self._generate_summary(
                case_id=case_id,
                as_of_date=as_of_date,
                run_number=run_no,
                rulings=claim_rulings,
                established=established_claims,
                contested=contested_claims,
                conceded=conceded_claims,
                unresolved_disputes=unresolved_disputes,
                evidence_limitations=evidence_limitations,
                is_sufficient=is_evidence_sufficient,
            )

            # 6. Update CaseFile judicial_rulings in place
            if hasattr(debate_result, "case_file") and debate_result.case_file is not None:
                debate_result.case_file.judicial_rulings = [
                    r.model_dump() for r in claim_rulings
                ]

            result = OdinResult(
                agent="odin",
                case_id=case_id,
                as_of_date=as_of_date,
                run_number=run_no,
                adjudication_status="completed",
                claim_rulings=claim_rulings,
                established_claims=established_claims,
                contested_claims=contested_claims,
                conceded_claims=conceded_claims,
                unresolved_disputes=list(dict.fromkeys(unresolved_disputes)),
                evidence_limitations=list(dict.fromkeys(evidence_limitations)),
                evidence_examined=sorted(evidence_examined),
                is_evidence_sufficient=is_evidence_sufficient,
                summary=summary,
                error_message=None,
            )

            self.logger.log_event("odin_adjudication_completed", case_id, {
                "rulings_count": len(claim_rulings),
                "established_count": len(established_claims),
                "contested_count": len(contested_claims),
                "conceded_count": len(conceded_claims),
                "is_evidence_sufficient": is_evidence_sufficient,
            })

            return result

        except Exception as e:
            logger.exception(f"Odin adjudication failed with internal error on case {case_id}: {e}")
            return OdinResult(
                agent="odin",
                case_id=case_id,
                as_of_date=as_of_date,
                run_number=run_no,
                adjudication_status="error",
                claim_rulings=[],
                established_claims=[],
                contested_claims=[],
                conceded_claims=[],
                unresolved_disputes=[],
                evidence_limitations=[f"Internal error during judicial evaluation: {e}"],
                evidence_examined=sorted(evidence_examined),
                is_evidence_sufficient=False,
                summary=f"Judicial adjudication error: {e}",
                error_message=f"Odin adjudication execution error: {e}",
            )

    # -------------------------------------------------------------------------
    # Single Claim Evaluation Engine
    # -------------------------------------------------------------------------

    def _evaluate_single_claim(
        self,
        claim: Claim,
        debate_result: DebateResult,
        as_of_date: str,
        evidence_examined: set[str],
        unresolved_disputes: list[str],
        evidence_limitations: list[str],
    ) -> ClaimRuling:
        """
        Evaluate a single claim against admissible evidence, cross-examination attacks,
        and concession records.
        """
        claim_id = claim.claim_id
        statement = claim.statement
        proponent = claim.agent
        claim_type = claim.claim_type

        # 1. Gather all attacks and concessions relevant to this claim
        all_attacks = debate_result.attacks or []
        attacks_on_claim = [a for a in all_attacks if a.target_claim_id == claim_id]

        all_concessions = debate_result.concessions or []
        concessions_on_claim = [c for c in all_concessions if c.target_claim_id == claim_id]

        # 2. Identify advocate positions
        loki_pos: Optional[str] = None
        thor_pos: Optional[str] = None

        if proponent == "thor":
            thor_pos = f"Advocates high exposure: {statement}"
            loki_challenges = [a for a in attacks_on_claim if a.challenger == "loki"]
            if loki_challenges:
                loki_pos = f"Challenges claim ({loki_challenges[0].challenge_type}): {loki_challenges[0].objection}"
        elif proponent == "loki":
            loki_pos = f"Advocates limited exposure: {statement}"
            thor_challenges = [a for a in attacks_on_claim if a.challenger == "thor"]
            if thor_challenges:
                thor_pos = f"Challenges claim ({thor_challenges[0].challenge_type}): {thor_challenges[0].objection}"

        # 3. Audit supporting citations for admissibility
        admissible_supporting: list[EvidenceReference] = []
        supporting_discrepancies: list[str] = []

        for cit in claim.citations:
            evidence_examined.add(cit.doc_id)
            adm_err = self._check_evidence_admissibility(cit, as_of_date)
            if adm_err:
                supporting_discrepancies.append(adm_err)
            else:
                admissible_supporting.append(cit)

        # 4. Audit counter-citations from attacks for admissibility
        admissible_counter: list[EvidenceReference] = []
        for attack in attacks_on_claim:
            for c_cit in attack.counter_citations:
                evidence_examined.add(c_cit.doc_id)
                adm_err = self._check_evidence_admissibility(c_cit, as_of_date)
                if not adm_err:
                    admissible_counter.append(c_cit)

        # 5. Check for formal concessions by the proponent
        # An explicit concession withdraws or qualifies the claim
        proponent_concessions = [
            c for c in concessions_on_claim if c.agent == proponent and c.action == "concede"
        ]
        range_adjustments = [
            c for c in concessions_on_claim if c.agent == proponent and c.action == "adjust_range"
        ]

        # ---------------------------------------------------------------------
        # Judicial Ruling Determination
        # ---------------------------------------------------------------------

        # Case A: Formal Concession
        if proponent_concessions:
            primary_conc = proponent_concessions[0]
            ruling = "conceded"
            confidence = 0.90
            conceded_reason = primary_conc.reason
            reasoning = (
                f"Formally conceded by {proponent.title()} under adversarial challenge "
                f"({primary_conc.target_challenge_id or 'challenge'}): '{conceded_reason}'. "
                f"Note: Concession records the withdrawal of this assertion; it does not automatically establish "
                f"the opponent's counter-claim without independent evidence."
            )
            conceded_by_agent: Optional[Literal["loki", "thor"]] = (
                "thor" if proponent == "thor" else ("loki" if proponent == "loki" else None)
            )
            discrepancy_str = "; ".join(supporting_discrepancies) if supporting_discrepancies else None

            return ClaimRuling(
                claim_id=claim_id,
                claim_statement=statement,
                proponent=proponent,
                claim_type=claim_type,
                ruling=ruling,
                confidence=confidence,
                reasoning=reasoning,
                supporting_citations=admissible_supporting,
                contradicting_citations=admissible_counter,
                loki_position=loki_pos,
                thor_position=thor_pos,
                concessions=concessions_on_claim,
                is_conceded=True,
                conceded_by=conceded_by_agent,
                evidence_gaps=[f"Claim withdrawn by proponent: {conceded_reason}"],
                discrepancy_notes=discrepancy_str,
                adjudicated_range=None,
            )

        # Case B: Inadmissible, Missing, or Completely Unsupported Evidence
        if claim.is_unsupported or not admissible_supporting:
            ruling = "contested"
            confidence = 0.25
            gap_desc = (
                f"Claim {claim_id} lacks admissible supporting evidence: "
                f"{'; '.join(supporting_discrepancies) if supporting_discrepancies else 'Zero citations provided'}."
            )
            evidence_limitations.append(gap_desc)
            reasoning = (
                f"Cannot be established: Claim lacks admissible evidentiary foundation. "
                f"Citations are either missing, retracted, clock violations, or uncorroborated Tier 4 rumors."
            )
            discrepancy_str = "; ".join(supporting_discrepancies) if supporting_discrepancies else None

            return ClaimRuling(
                claim_id=claim_id,
                claim_statement=statement,
                proponent=proponent,
                claim_type=claim_type,
                ruling=ruling,
                confidence=confidence,
                reasoning=reasoning,
                supporting_citations=[],
                contradicting_citations=admissible_counter,
                loki_position=loki_pos,
                thor_position=thor_pos,
                concessions=concessions_on_claim,
                is_conceded=False,
                conceded_by=None,
                evidence_gaps=[gap_desc],
                discrepancy_notes=discrepancy_str,
                adjudicated_range=None,
            )

        # Case C: Material Factual Dispute / Unresolved Contradiction
        # If the claim faces credible admissible counter-citations that directly conflict
        has_material_counter_evidence = (
            len(admissible_counter) > 0
            and any(c.reliability_tier in (1, 2, 3) for c in admissible_counter)
        )
        is_direct_contradiction_attack = any(
            a.challenge_type in ("contradiction", "omitted_substitution") for a in attacks_on_claim
        )

        if has_material_counter_evidence and is_direct_contradiction_attack:
            ruling = "contested"
            confidence = 0.55
            dispute_text = (
                f"Commercial tension on claim {claim_id}: {proponent.title()} presents {admissible_supporting[0].doc_id}, "
                f"but opponent presents counter-evidence in {admissible_counter[0].doc_id}. "
                f"Evidence remains balanced and conflicting without decisive proof."
            )
            unresolved_disputes.append(dispute_text)
            reasoning = (
                f"Materially contested: Admissible evidence exists on both sides without decisive refutation. "
                f"Proponent cites {', '.join(c.doc_id for c in admissible_supporting[:2])}, while challenger presents "
                f"admissible counter-evidence in {', '.join(c.doc_id for c in admissible_counter[:2])}. "
                f"Court preserves this unresolved trade dispute."
            )
            discrepancy_str = "; ".join(supporting_discrepancies) if supporting_discrepancies else None

            return ClaimRuling(
                claim_id=claim_id,
                claim_statement=statement,
                proponent=proponent,
                claim_type=claim_type,
                ruling=ruling,
                confidence=confidence,
                reasoning=reasoning,
                supporting_citations=admissible_supporting,
                contradicting_citations=admissible_counter,
                loki_position=loki_pos,
                thor_position=thor_pos,
                concessions=concessions_on_claim,
                is_conceded=False,
                conceded_by=None,
                evidence_gaps=["Competing trade evidence remains conflicting and unresolved."],
                discrepancy_notes=discrepancy_str,
                adjudicated_range=claim.estimates[0] if claim.estimates else None,
            )

        # Case D: Established Sourced Fact or Reasoned Inference
        ruling = "established"
        min_tier = min(c.reliability_tier or 3 for c in admissible_supporting)

        if claim_type == "sourced_fact":
            confidence = 0.95 if min_tier == 1 else (0.88 if min_tier == 2 else 0.80)
            reasoning = (
                f"Established as sourced fact: Directly verified by admissible Tier {min_tier} source(s) "
                f"{', '.join(f'{c.doc_id} [{c.paragraph}]' for c in admissible_supporting[:2])}."
            )
        else:
            confidence = 0.84
            reasoning = (
                f"Established as reasoned inference: Proposition is soundly derived from verified baselines in "
                f"{', '.join(f'{c.doc_id} [{c.paragraph}]' for c in admissible_supporting[:2])}."
            )

        # If a range was adjusted by concession, validate the adjusted range
        adjudicated_range = None
        if range_adjustments and range_adjustments[0].adjusted_estimates:
            adjudicated_range = range_adjustments[0].adjusted_estimates[0]
            reasoning += f" (Refined to adjusted range: {adjudicated_range.min_estimate:.1f} - {adjudicated_range.max_estimate:.1f}%)."
        elif claim.estimates:
            adjudicated_range = claim.estimates[0]

        discrepancy_str = "; ".join(supporting_discrepancies) if supporting_discrepancies else None

        return ClaimRuling(
            claim_id=claim_id,
            claim_statement=statement,
            proponent=proponent,
            claim_type=claim_type,
            ruling=ruling,
            confidence=confidence,
            reasoning=reasoning,
            supporting_citations=admissible_supporting,
            contradicting_citations=admissible_counter,
            loki_position=loki_pos,
            thor_position=thor_pos,
            concessions=concessions_on_claim,
            is_conceded=False,
            conceded_by=None,
            evidence_gaps=[],
            discrepancy_notes=discrepancy_str,
            adjudicated_range=adjudicated_range,
        )

    # -------------------------------------------------------------------------
    # Helper Validation & Ingestion Methods
    # -------------------------------------------------------------------------

    def _collect_claims(self, debate_result: DebateResult) -> list[Claim]:
        """Collect and deduplicate all material claims from the debate deliverable."""
        claims_dict: dict[str, Claim] = {}

        # 1. From CaseFile claims
        for c in (debate_result.claims or []):
            claims_dict[c.claim_id] = c

        # 2. From Loki Round 1
        if debate_result.loki_round1 and debate_result.loki_round1.claims:
            for c in debate_result.loki_round1.claims:
                if c.claim_id not in claims_dict:
                    claims_dict[c.claim_id] = c

        # 3. From Thor Round 1
        if debate_result.thor_round1 and debate_result.thor_round1.claims:
            for c in debate_result.thor_round1.claims:
                if c.claim_id not in claims_dict:
                    claims_dict[c.claim_id] = c

        return list(claims_dict.values())

    def _check_evidence_admissibility(self, cit: EvidenceReference, as_of_date: str) -> Optional[str]:
        """
        Validate evidence admissibility under courtroom rules.
        Returns an error string if inadmissible, None if admissible.
        """
        # 1. Doc ID format
        if not CitationValidator.validate_doc_id_format(cit.doc_id):
            return f"Invalid Runemark doc ID format: '{cit.doc_id}'"

        # 2. Clock cutoff violation
        if cit.publication_date and CitationValidator.is_clock_violation(cit.publication_date, as_of_date):
            return f"Clock cutoff violation: {cit.doc_id} published on {cit.publication_date} > as-of {as_of_date}"

        # 3. Retraction / False decoy
        retraction = CitationValidator.check_retraction(cit.doc_id)
        if retraction is not None:
            corr_id, reason = retraction
            return f"Retracted/discredited decoy: {cit.doc_id} ({reason}, see correction {corr_id})"

        # 4. Tier 4 Uncorroborated Rumor
        if cit.reliability_tier == 4:
            return f"Inadmissible Tier 4 rumor/social post: {cit.doc_id} cannot substantiate fact"

        # 5. Prompt Injection Defense
        _, injected = CitationValidator.sanitize_content(cit.quote_or_datapoint)
        if injected:
            return f"Prompt injection attempt detected in {cit.doc_id} quote; scrubbed and disregarded"

        return None

    # -------------------------------------------------------------------------
    # Judicial Executive Summary Generation
    # -------------------------------------------------------------------------

    def _generate_summary(
        self,
        case_id: str,
        as_of_date: str,
        run_number: int,
        rulings: list[ClaimRuling],
        established: list[str],
        contested: list[str],
        conceded: list[str],
        unresolved_disputes: list[str],
        evidence_limitations: list[str],
        is_sufficient: bool,
    ) -> str:
        """Deterministic plain-language judicial summary authored from Odin's rulings only."""
        lines = [
            f"=== ODIN FINAL JUDICIAL RULING ===",
            f"Case: {case_id} | As-of Date: {as_of_date} | Trial Run: {run_number}",
            f"Evidence Sufficiency: {'SUFFICIENT' if is_sufficient else 'INSUFFICIENT (RETRIAL RECOMMENDED)'}",
            f"Claims Adjudicated ({len(rulings)} total): {len(established)} Established, {len(contested)} Contested, {len(conceded)} Conceded",
            "",
            "Judicial Determinations per Claim:",
        ]

        for r in rulings:
            status_tag = r.ruling.upper()
            lines.append(f"  [{r.claim_id}] {status_tag} (Confidence: {r.confidence:.2f}) — Proponent: {r.proponent.title()}")
            lines.append(f"    Assertion: {r.claim_statement}")
            lines.append(f"    Ruling Rationale: {r.reasoning}")
            if r.adjudicated_range:
                lines.append(f"    Adjudicated Exposure: {r.adjudicated_range.format_range()}")
            if r.discrepancy_notes:
                lines.append(f"    Evidentiary Notes: {r.discrepancy_notes}")

        if conceded:
            lines.append("")
            lines.append("Recorded Formal Concessions:")
            for r in rulings:
                if r.is_conceded:
                    lines.append(f"  - Claim {r.claim_id} conceded by {r.conceded_by}: {r.reasoning}")

        if unresolved_disputes:
            lines.append("")
            lines.append("Preserved Material Disputes:")
            for d in unresolved_disputes:
                lines.append(f"  - {d}")

        if evidence_limitations:
            lines.append("")
            lines.append("Evidence Limitations & Gaps:")
            for lim in evidence_limitations:
                lines.append(f"  - {lim}")

        return "\n".join(lines)
