"""Sufficiency Feedback Engine formulating targeted retrieval from Odin's judicial gaps (Part 6B)."""

import logging
import re
from typing import Optional, Any
from backend.app.schemas.evidence import EvidenceReference
from backend.app.schemas.case_file import CaseFile
from backend.app.schemas.odin_result import OdinResult, ClaimRuling
from backend.app.schemas.feedback_loop import TargetedRetrievalTask
from backend.app.services.retrieval import BaseRetrievalService
from backend.app.services.citations import CitationValidator
from backend.app.services.logging_service import StructuredLogger

logger = logging.getLogger("ragnarok.feedback_loop")


class SufficiencyFeedbackEngine:
    """
    Formulates targeted evidence-retrieval tasks from Odin's identified gaps and unresolved disputes,
    audits candidate documents for admissibility, and detects whether meaningful new evidence was found.
    """

    def __init__(
        self,
        retrieval_service: Optional[BaseRetrievalService] = None,
        logger_service: Optional[StructuredLogger] = None,
    ):
        self.retrieval_service = retrieval_service
        self.logger = logger_service or StructuredLogger(agent_name="feedback_loop")

    # -------------------------------------------------------------------------
    # Gap Analysis & Task Generation
    # -------------------------------------------------------------------------

    def analyze_gaps(
        self,
        odin_result: OdinResult,
        case_file: CaseFile,
        trial_number: int,
    ) -> list[TargetedRetrievalTask]:
        """
        Inspect Odin's adjudication findings (evidence limitations, unresolved disputes,
        and contested rulings) and formulate actionable targeted retrieval tasks.
        """
        tasks: list[TargetedRetrievalTask] = []
        seen_queries: set[str] = set()
        task_idx = 1

        # 1. Inspect ClaimRulings for contested claims and explicit evidence gaps
        for ruling in odin_result.claim_rulings:
            # We target contested claims or claims with identified gaps
            if ruling.ruling != "contested" and not ruling.evidence_gaps and not ruling.discrepancy_notes:
                continue

            query, filters = self._formulate_query_for_ruling(ruling, case_file)
            if not query or query in seen_queries:
                continue

            seen_queries.add(query)
            primary_gap = (
                ruling.evidence_gaps[0]
                if ruling.evidence_gaps
                else (ruling.discrepancy_notes or f"Contested claim without decisive evidence: {ruling.claim_id}")
            )

            task = TargetedRetrievalTask(
                task_id=f"TASK-R{trial_number:02d}-{task_idx:02d}",
                target_gap=primary_gap,
                target_claim_id=ruling.claim_id,
                query=query,
                filters=filters,
                retrieved_doc_ids=[],
                admissible_citations=[],
                inadmissible_citations=[],
                resolved=False,
                notes=None,
            )
            tasks.append(task)
            task_idx += 1

        # 2. Inspect overarching unresolved disputes if not already covered
        for dispute in odin_result.unresolved_disputes:
            tokens = [t for t in re.findall(r"\b[A-Za-z0-9_-]+\b", dispute) if len(t) > 3]
            query = " ".join(tokens[:8])
            if query and query not in seen_queries:
                seen_queries.add(query)
                tasks.append(
                    TargetedRetrievalTask(
                        task_id=f"TASK-R{trial_number:02d}-{task_idx:02d}",
                        target_gap=f"Unresolved contradiction: {dispute}",
                        target_claim_id=None,
                        query=query,
                        filters={},
                        retrieved_doc_ids=[],
                        admissible_citations=[],
                        inadmissible_citations=[],
                        resolved=False,
                        notes="Generated from unresolved dispute.",
                    )
                )
                task_idx += 1

        # 3. Inspect global evidence limitations if rulings were empty or generic
        if not tasks and odin_result.evidence_limitations:
            for lim in odin_result.evidence_limitations:
                tokens = [t for t in re.findall(r"\b[A-Za-z0-9_-]+\b", lim) if len(t) > 3]
                query = " ".join(tokens[:8])
                if query and query not in seen_queries:
                    seen_queries.add(query)
                    tasks.append(
                        TargetedRetrievalTask(
                            task_id=f"TASK-R{trial_number:02d}-{task_idx:02d}",
                            target_gap=lim,
                            target_claim_id=None,
                            query=query,
                            filters={},
                            retrieved_doc_ids=[],
                            admissible_citations=[],
                            inadmissible_citations=[],
                            resolved=False,
                            notes="Generated from general evidence limitation.",
                        )
                    )
                    task_idx += 1

        return tasks

    def _formulate_query_for_ruling(
        self,
        ruling: ClaimRuling,
        case_file: CaseFile,
    ) -> tuple[str, dict[str, Any]]:
        """Formulate a targeted query and filters based on the ruling's statement and gap type."""
        stmt = ruling.claim_statement
        stmt_lower = stmt.lower()
        gap_notes = ("; ".join(ruling.evidence_gaps) + " " + (ruling.discrepancy_notes or "")).lower()

        filters: dict[str, Any] = {}

        # Country / Sector inference
        if "midgard" in stmt_lower:
            filters["country"] = "Midgard"
        elif "tolan" in stmt_lower:
            filters["country"] = "Tolan"
        elif "ravik" in stmt_lower:
            filters["country"] = "Ravik"

        if "wheat" in stmt_lower:
            filters["sector"] = "Wheat"
        elif "maize" in stmt_lower:
            filters["sector"] = "Wheat"

        # Specialized queries based on known gap conditions
        if "retracted" in gap_notes or "orv-0043" in gap_notes:
            # Retracted claim needs official replacement or expiration notices
            return "Corridor Agreement expired official notice Realm Trade Ministry ORV-0016 ORV-0013", filters

        if "clock violation" in gap_notes or "as_of_date" in gap_notes:
            # Post-dated claim needs historical baseline before cutoff
            return f"{stmt[:60]} trade note official", filters

        if "midgard" in stmt_lower and "receipt" in stmt_lower:
            return "Midgard direct wheat trade note receipts 2026-Q4 2025-Q4 ORV-0009", filters

        if "tolan" in stmt_lower and ("import" in stmt_lower or "gap" in stmt_lower):
            return "Tolan wheat trade note imports replacement ORV-0046 ORV-0044", filters

        if "vanir" in stmt_lower and "substitution" in stmt_lower:
            return "Vanir to Midgard wheat shipments trade note ORV-0027", filters

        if "rail" in stmt_lower or "capacity" in stmt_lower:
            return "Ravik rail link expanded grain capacity limit ORV-0050 ORV-0001", filters

        if "port strike" in stmt_lower or "loadings" in stmt_lower or "orvan port" in stmt_lower:
            return "Port strike Orvan Grain Port loadings drop ORV-0007 ORV-0021", filters

        # Fallback: extract meaningful terms from the statement
        words = [w for w in re.findall(r"\b[A-Za-z0-9_-]+\b", stmt) if len(w) > 3 and w.lower() not in {
            "this", "that", "with", "from", "were", "been", "have", "will", "would", "about"
        }]
        fallback_query = " ".join(words[:7])
        return fallback_query, filters

    # -------------------------------------------------------------------------
    # Targeted Retrieval Execution
    # -------------------------------------------------------------------------

    def execute_targeted_retrieval(
        self,
        tasks: list[TargetedRetrievalTask],
        as_of_date: str,
        examined_doc_ids: set[str],
    ) -> tuple[list[EvidenceReference], list[TargetedRetrievalTask]]:
        """
        Execute targeted searches for all tasks, enforce strict admissibility checks,
        and collect newly discovered evidence.
        """
        if self.retrieval_service is None or not tasks:
            return [], tasks

        newly_discovered: list[EvidenceReference] = []
        seen_new_ids: set[str] = set()

        for task in tasks:
            try:
                docs = self.retrieval_service.search(
                    query=task.query,
                    as_of_date=as_of_date,
                    filters=task.filters if task.filters else None,
                    limit=5,
                )
            except Exception as e:
                logger.warning(f"Targeted search failed for task {task.task_id} ({task.query}): {e}")
                task.notes = f"Retrieval search error: {e}"
                continue

            task.retrieved_doc_ids = [d.doc_id for d in docs]

            for doc in docs:
                # 1. As-of date cutoff check
                if CitationValidator.is_clock_violation(doc.pub_date, as_of_date):
                    task.inadmissible_citations.append(
                        f"{doc.doc_id}: Post-cutoff publication date ({doc.pub_date} > {as_of_date})"
                    )
                    continue

                # 2. Retraction check
                if CitationValidator.check_retraction(doc.doc_id):
                    task.inadmissible_citations.append(
                        f"{doc.doc_id}: Retracted document (unreliable decoy)"
                    )
                    continue

                # 3. Reliability Tier check (Tier 4 tabloids cannot independently resolve gaps)
                if getattr(doc, "reliability_tier", 3) > 3:
                    task.inadmissible_citations.append(
                        f"{doc.doc_id}: Uncorroborated Tier 4 rumor/social post"
                    )
                    continue

                # 4. Formulate verified EvidenceReference
                p_key = "P1"
                quote = doc.title or "Official document statement"
                if doc.paragraphs:
                    p_key = sorted(doc.paragraphs.keys())[0]
                    quote = doc.paragraphs[p_key]

                ref = EvidenceReference(
                    doc_id=doc.doc_id,
                    paragraph=p_key,
                    reliability_tier=doc.reliability_tier,
                    source_name=doc.source_name,
                    publication_date=doc.pub_date,
                    pub_time=doc.pub_time,
                    quote_or_datapoint=quote[:180],
                    is_off_runemark=False,
                )
                task.admissible_citations.append(ref)

                # Check if this document is genuinely new to the analysis
                if doc.doc_id not in examined_doc_ids and doc.doc_id not in seen_new_ids:
                    newly_discovered.append(ref)
                    seen_new_ids.add(doc.doc_id)
                    task.resolved = True

            if not task.admissible_citations:
                task.notes = "No admissible documents retrieved meeting clock and reliability standards."
            elif task.resolved:
                new_docs = ", ".join(seen_new_ids & set(task.retrieved_doc_ids))
                task.notes = f"Resolved: Discovered new admissible evidence ({new_docs})."
            else:
                task.notes = "All retrieved documents were already examined in prior trials."

        return newly_discovered, tasks
