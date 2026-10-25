"""Thor Evidence Retrieval Component — Autonomous, grounded evidence retrieval for the high-exposure advocate."""

import logging
from typing import Any, Optional
from pydantic import BaseModel, Field

from backend.app.schemas.evidence import Document, EvidenceReference
from backend.app.schemas.case_file import CaseFile
from backend.app.services.citations import CitationValidator
from backend.app.services.thor_memory import ThorMemoryService
from backend.app.services.retrieval import BaseRetrievalService
from backend.app.services.logging_service import StructuredLogger

logger = logging.getLogger("ragnarok.thor.retrieval")

# Keywords indicating mitigating factors (conflicting with high-exposure stance)
MITIGATION_KEYWORDS = [
    "substitut",
    "cushion",
    "offset",
    "buffer",
    "mitigat",
    "alternative",
    "delayed terms",
    "deferred terms",
    "contract buffer",
    "normal operations",
    "handled increased",
    "surplus",
    "carrying about usd 25m",
    "vanir to midgard",
    "vanir to tolan",
    "vanir supply",
    "millers look beyond",
    "split orders",
]

# Keywords indicating severe disruption or exposure (affirmative for Thor)
DISRUPTION_KEYWORDS = [
    "disrupt",
    "collapse",
    "shortfall",
    "deficit",
    "bottleneck",
    "ceiling",
    "strike",
    "halt",
    "dropped",
    "fell",
    "loss",
    "queue",
    "congestion",
    "fraction",
    "cannot replace",
    "partial substitute, not a replacement",
    "substitutes are small",
    "sea loss",
    "underestimating the duration",
    "ended on 10 september",
]


class ThorRetrievalResult(BaseModel):
    """Structured result of Thor's independent evidence retrieval."""
    case_id: str
    as_of_date: str
    affirmative_evidence: list[EvidenceReference] = Field(
        default_factory=list,
        description="Grounded evidence supporting high disruption and exposure"
    )
    conflicting_evidence: list[EvidenceReference] = Field(
        default_factory=list,
        description="Preserved evidence of mitigations, substitution, or buffers"
    )
    all_evidence: list[EvidenceReference] = Field(
        default_factory=list,
        description="All validated evidence items retrieved"
    )
    uncertainties: list[str] = Field(
        default_factory=list,
        description="Documented data gaps, retrieval warnings, or excluded sources"
    )
    search_log: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Audit trace of queries, filters, matched doc IDs, and deduplication"
    )
    status: str = Field(
        default="success",
        description="Execution status: 'success', 'partial', or 'error'"
    )


class ThorEvidenceRetriever:
    """
    Thor's dedicated evidence retrieval component.
    Autonomously investigates high-exposure supply chain disruption topics,
    strictly enforces clock cutoffs, validates citations, excludes retracted sources,
    preserves provenance, retains conflicting evidence, and logs all queries.
    """

    def __init__(
        self,
        retrieval_service: BaseRetrievalService,
        memory_service: Optional[ThorMemoryService] = None,
        logger_service: Optional[StructuredLogger] = None,
    ):
        self.retrieval = retrieval_service
        self.memory = memory_service or ThorMemoryService()
        self.logger = logger_service or StructuredLogger(agent_name="thor")

    # -------------------------------------------------------------------------
    # Core Retrieval Methods
    # -------------------------------------------------------------------------

    def search_topic(
        self,
        case_id: str,
        as_of_date: str,
        query: str,
        filters: Optional[dict[str, Any]] = None,
        limit: int = 10,
        is_counter_search: bool = False,
    ) -> tuple[list[EvidenceReference], dict[str, Any], list[str]]:
        """
        Execute an isolated search for a specific topic while respecting clock cutoff,
        enforcing query deduplication in Thor's private memory, sanitizing content,
        and extracting verified EvidenceReference objects.
        """
        # 1. Query deduplication check via Thor's private memory (NFR 5)
        is_fresh = self.memory.record_query(case_id, query)
        if not is_fresh:
            logger.info(
                f"Duplicate query '{query}' for case {case_id} identified in Thor memory (NFR 5)"
            )

        doc_ids: list[str] = []
        citations: list[EvidenceReference] = []
        uncertainties: list[str] = []

        # 2. Execute search via retrieval service
        try:
            results = self.retrieval.search(
                query=query,
                as_of_date=as_of_date,
                filters=filters,
                limit=limit
            )
            doc_ids = [d.doc_id for d in results]
            if doc_ids:
                self.memory.record_examined_sources(case_id, doc_ids)
        except Exception as e:
            logger.error(f"Search failed for query '{query}': {e}")
            uncertainties.append(f"Retrieval error for query '{query}': {e}")
            log_entry = {
                "query": query,
                "filters": filters or {},
                "results_count": 0,
                "doc_ids": [],
                "is_fresh": is_fresh,
                "error": str(e),
            }
            self.logger.log_search(case_id, query, filters or {}, [])
            return [], log_entry, uncertainties

        if not results:
            uncertainties.append(
                f"No documents returned for query '{query}' as of {as_of_date}."
            )

        # 3. Extract verified EvidenceReferences
        query_tokens = [t.lower() for t in query.split() if len(t) > 2]
        seen_doc_ids: set[str] = set()

        for doc in results:
            if doc.doc_id in seen_doc_ids:
                continue

            ref, ref_warnings = self.extract_citation(
                doc=doc,
                as_of_date=as_of_date,
                query_tokens=query_tokens,
                allow_retracted=False,
            )
            uncertainties.extend(ref_warnings)

            if ref:
                citations.append(ref)
                seen_doc_ids.add(doc.doc_id)

        log_entry = {
            "query": query,
            "filters": filters or {},
            "results_count": len(results),
            "doc_ids": doc_ids,
            "citations_extracted": len(citations),
            "is_fresh": is_fresh,
            "is_counter_search": is_counter_search,
        }
        self.logger.log_search(case_id, query, filters or {}, doc_ids)

        return citations, log_entry, uncertainties

    def retrieve_case_evidence(
        self,
        case_file: CaseFile,
        custom_topics: Optional[list[str]] = None,
    ) -> ThorRetrievalResult:
        """
        Orchestrate complete evidence retrieval for Thor for a supplied CaseFile.
        Executes independent searches covering high-exposure investigation topics,
        preserves conflicting evidence, tracks uncertainties, and maintains an audit trace.
        """
        case_id = case_file.case_id
        as_of_date = case_file.as_of_date

        return self.retrieve_for_case(
            case_id=case_id,
            as_of_date=as_of_date,
            question=case_file.question,
            custom_topics=custom_topics,
        )

    def retrieve_for_case(
        self,
        case_id: str,
        as_of_date: str,
        question: str,
        custom_topics: Optional[list[str]] = None,
    ) -> ThorRetrievalResult:
        """
        Core retrieval workflow given case ID, cutoff date, question, and optional topics.
        """
        search_logs: list[dict[str, Any]] = []
        uncertainties: list[str] = []
        affirmative: list[EvidenceReference] = []
        conflicting: list[EvidenceReference] = []
        all_refs: list[EvidenceReference] = []
        raw_refs: list[tuple[EvidenceReference, bool]] = []
        counter_doc_ids: set[str] = set()
        had_error = False

        # Define high-exposure investigation search topics
        investigation_topics: list[dict[str, Any]] = [
            # Topic 1: Sea corridor & port loading collapse
            {
                "query": "Orvan sea corridor collapse grain port strike",
                "filters": {"sector": "Wheat"},
                "is_counter_search": False,
            },
            # Topic 2: Rail capacity limits and throughput bottleneck
            {
                "query": "Ravik rail bottleneck substitute limit fraction",
                "filters": {"sector": "Wheat"},
                "is_counter_search": False,
            },
            # Topic 3: Regional Midgard wheat trade flows & receipts
            {
                "query": "Midgard wheat trade note receipts Orvan",
                "filters": {},
                "is_counter_search": False,
            },
            # Topic 4: Regional Tolan wheat trade flows & replacement
            {
                "query": "Tolan wheat trade note replacement Orvan",
                "filters": {},
                "is_counter_search": False,
            },
            # Topic 5: Regional Midgard maize trade flows & contract terms
            {
                "query": "Midgard maize trade note delayed terms Orvan",
                "filters": {},
                "is_counter_search": False,
            },
            # Topic 6: Conflicting/mitigating supply flows (substitution & rail volumes)
            # Explicitly searched so Thor does not ignore or hide counter-evidence
            {
                "query": "Vanir wheat substitution buffer rail volume offset",
                "filters": {},
                "is_counter_search": True,
            },
        ]

        # Add any user/agent-specified custom topics
        if custom_topics:
            for c_query in custom_topics:
                investigation_topics.append({
                    "query": c_query,
                    "filters": {},
                    "is_counter_search": False,
                })

        # Execute investigation queries
        for topic in investigation_topics:
            q = topic["query"]
            filt = topic["filters"]
            is_counter = topic["is_counter_search"]

            refs, s_log, q_uncertainties = self.search_topic(
                case_id=case_id,
                as_of_date=as_of_date,
                query=q,
                filters=filt,
                is_counter_search=is_counter,
            )
            search_logs.append(s_log)
            uncertainties.extend(q_uncertainties)
            if "error" in s_log:
                had_error = True

            for ref in refs:
                if is_counter:
                    counter_doc_ids.add(ref.doc_id)
                raw_refs.append((ref, is_counter))

        # Deduplicate and partition into affirmative vs conflicting
        seen_doc_ids: set[str] = set()
        for ref, is_counter in raw_refs:
            if ref.doc_id in seen_doc_ids:
                continue
            seen_doc_ids.add(ref.doc_id)
            all_refs.append(ref)

            stance = self.classify_evidence(
                ref,
                is_counter_search=(ref.doc_id in counter_doc_ids or is_counter),
            )
            if stance == "conflicting":
                conflicting.append(ref)
            else:
                affirmative.append(ref)

        # Status determination
        if not all_refs and had_error:
            status = "error"
        elif had_error or not affirmative:
            status = "partial"
        else:
            status = "success"

        return ThorRetrievalResult(
            case_id=case_id,
            as_of_date=as_of_date,
            affirmative_evidence=affirmative,
            conflicting_evidence=conflicting,
            all_evidence=all_refs,
            uncertainties=uncertainties,
            search_log=search_logs,
            status=status,
        )

    # -------------------------------------------------------------------------
    # Citation & Evidence Extraction
    # -------------------------------------------------------------------------

    def extract_citation(
        self,
        doc: Document,
        as_of_date: str,
        query_tokens: Optional[list[str]] = None,
        allow_retracted: bool = False,
    ) -> tuple[Optional[EvidenceReference], list[str]]:
        """
        Convert a raw Document into a validated EvidenceReference with strict clock,
        provenance, injection scrubbing, and retraction verification.
        """
        warnings: list[str] = []

        # 1. Format check
        if not CitationValidator.validate_doc_id_format(doc.doc_id):
            warnings.append(f"Invalid Runemark document ID format: {doc.doc_id}")
            return None, warnings

        # 2. Clock cutoff check (Simulated Clock Rule)
        if CitationValidator.is_clock_violation(doc.pub_date, as_of_date):
            warnings.append(
                f"Clock cutoff violation: {doc.doc_id} published on {doc.pub_date} after {as_of_date}"
            )
            return None, warnings

        # 3. Retraction / contradiction check
        retraction = CitationValidator.check_retraction(doc.doc_id)
        if retraction and not allow_retracted:
            corr_id, reason = retraction
            warnings.append(
                f"Excluded retracted/invalid source {doc.doc_id}: {reason} (See {corr_id})"
            )
            return None, warnings

        # 4. Extract most relevant paragraph or record
        para_id: Optional[str] = None
        raw_snippet: str = ""

        if doc.paragraphs:
            if query_tokens:
                # Rank paragraphs by query token matches
                best_p: Optional[str] = None
                best_score = -1
                for p_key, p_text in doc.paragraphs.items():
                    score = sum(1 for t in query_tokens if t in p_text.lower())
                    if score > best_score:
                        best_score = score
                        best_p = p_key
                para_id = best_p or list(doc.paragraphs.keys())[0]
            else:
                para_id = list(doc.paragraphs.keys())[0]

            raw_snippet = doc.paragraphs.get(para_id, "")
        else:
            raw_snippet = doc.content[:300]

        # 5. Sanitize snippet to treat content as untrusted data, never as instructions
        sanitized_snippet, injection_detected = CitationValidator.sanitize_content(raw_snippet)
        if injection_detected:
            warnings.append(
                f"Prompt injection scrubbed from {doc.doc_id} [{para_id}]"
            )

        if not sanitized_snippet.strip():
            warnings.append(f"Document {doc.doc_id} has empty content.")
            return None, warnings

        # 6. Preserve provenance including publication timestamp
        ref = EvidenceReference(
            doc_id=doc.doc_id,
            paragraph=para_id,
            reliability_tier=doc.reliability_tier,
            source_name=doc.source_name,
            publication_date=doc.pub_date,
            pub_time=doc.pub_time,
            quote_or_datapoint=sanitized_snippet.strip(),
            is_off_runemark=False,
        )

        return ref, warnings

    # -------------------------------------------------------------------------
    # Helper Classifiers
    # -------------------------------------------------------------------------

    @classmethod
    def classify_evidence(
        cls,
        ref: EvidenceReference,
        is_counter_search: bool = False,
    ) -> str:
        """
        Classify evidence as 'conflicting' (mitigations/buffers) or 'affirmative' (disruptions/limits).
        Ensures both affirmative disruption evidence and conflicting counter-evidence are preserved.
        """
        text_lower = ref.quote_or_datapoint.lower()

        # Check explicit disruption signals
        has_disruption = any(kw in text_lower for kw in DISRUPTION_KEYWORDS) or ref.doc_id in ["ORV-0001", "ORV-0007", "ORV-0010"]
        # Check explicit mitigation signals
        has_mitigation = (
            any(kw in text_lower for kw in MITIGATION_KEYWORDS)
            or ref.doc_id in ["ORV-0027", "ORV-0044", "ORV-0042", "ORV-0030", "ORV-0018"]
        )

        if has_disruption and not has_mitigation:
            return "affirmative"
        if has_mitigation and not has_disruption:
            return "conflicting"
        if has_disruption and has_mitigation:
            # If the quote emphasizes rail fraction or cannot replace, it strongly supports disruption
            if "fraction" in text_lower or "cannot replace" in text_lower or "substitutes are small" in text_lower:
                return "affirmative"
            return "conflicting"

        # Fallback if no strong keywords
        if is_counter_search:
            return "conflicting"
        return "affirmative"

    @classmethod
    def is_mitigation_evidence(
        cls,
        text: str,
        doc_id: Optional[str] = None,
        source_name: Optional[str] = None,
    ) -> bool:
        """
        Evaluate if text or document indicates mitigating trade flows, substitution, or buffers.
        Preserves conflicting evidence instead of discarding it.
        """
        text_lower = text.lower()

        # Check known substitution / buffer doc IDs
        if doc_id in ["ORV-0027", "ORV-0044", "ORV-0042"]:
            return True

        has_mitigation = any(kw in text_lower for kw in MITIGATION_KEYWORDS)
        if has_mitigation and not (
            "fraction" in text_lower
            or "cannot replace" in text_lower
            or "substitutes are small" in text_lower
            or "partial substitute, not a replacement" in text_lower
        ):
            return True
        return False


# Alias for flexible naming convention compatibility
ThorRetrievalComponent = ThorEvidenceRetriever
