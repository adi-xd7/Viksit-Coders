"""Tests for the Multi-Trial Sufficiency Feedback Loop (Part 6B)."""

import pytest
from pathlib import Path
from unittest.mock import MagicMock

from backend.app.schemas.evidence import Document
from backend.app.schemas.case_file import CaseFile
from backend.app.schemas.thor_result import ThorResult
from backend.app.schemas.odin_result import ClaimRuling, OdinResult
from backend.app.schemas.feedback_loop import TargetedRetrievalTask
from backend.app.agents.odin import OdinAgent
from backend.app.agents.thor import ThorAgent
from backend.app.services.retrieval import MockRetrievalService, RunemarkCorpusRetrievalService
from backend.app.services.debate_orchestrator import DebateOrchestrator
from backend.app.services.feedback_loop import SufficiencyFeedbackEngine
from backend.app.services.memory import LokiMemoryService
from backend.app.services.thor_memory import ThorMemoryService


@pytest.fixture
def feedback_mock_documents() -> list[Document]:
    """Rich set of synthetic mock documents for feedback loop testing."""
    return [
        Document(
            doc_id="ORV-0016",
            event_id="E5",
            title="Corridor Agreement expires with no renewal",
            source_name="Realm Trade Ministry",
            source_type="official_notice",
            reliability_tier=1,
            pub_date="2026-09-10",
            country="Realm",
            sector="Wheat",
            format="PDF",
            content=(
                "Notice from Realm Trade Ministry. The Corridor Agreement expired on 10 September 2026. "
                "Talks on renewal ended without agreement."
            ),
            paragraphs={
                "P1": "Notice from the Realm Trade Ministry. The Corridor Agreement expired on 10 September 2026.",
                "P2": "Talks on renewal ended without agreement. No replacement arrangement has been signed."
            }
        ),
        Document(
            doc_id="ORV-0007",
            event_id="E5",
            title="MOCK: Port strike commences",
            source_name="Asgard Herald",
            source_type="newspaper",
            reliability_tier=3,
            pub_date="2026-10-22",
            country="Orvan",
            sector="Wheat",
            format="TXT",
            content="Port strike at Orvan Grain Port commenced 14 September 2026.",
            paragraphs={"P3": "Ship loadings dropped by more than 50%."}
        ),
        Document(
            doc_id="ORV-0021",
            event_id="E5",
            title="MOCK: Corvan Grain October report",
            source_name="Corvan Grain",
            source_type="company_statement",
            reliability_tier=2,
            pub_date="2026-11-04",
            country="Orvan",
            sector="Wheat",
            format="TXT",
            content="Corvan Grain reported October loadings down 62% year over year.",
            paragraphs={"P1": "Loadings fell 62% year over year."}
        ),
        Document(
            doc_id="ORV-0009",
            event_id="E5",
            title="Midgard wheat trade note",
            source_name="Realm Trade Ministry",
            source_type="trade_note",
            reliability_tier=1,
            pub_date="2027-01-19",
            country="Midgard",
            sector="Wheat",
            format="TXT",
            content="Midgard direct wheat receipts fell from USD 260.4M in 2025-Q4 to USD 103.9M in 2026-Q4 (down 60.1%).",
            paragraphs={
                "P5": "2025-Q4 imports were USD 260.4M.",
                "P7": "2026-Q4 imports were USD 103.9M.",
                "P11": "Net value loss was 60.1% due to corridor disruption.",
            }
        ),
        Document(
            doc_id="ORV-0027",
            event_id="E5",
            title="Vanir to Midgard trade note",
            source_name="Realm Trade Ministry",
            source_type="trade_note",
            reliability_tier=1,
            pub_date="2027-01-22",
            country="Midgard",
            sector="Wheat",
            format="TXT",
            content=(
                "Vanir to Midgard wheat shipments surged in Nov-Dec 2026. "
                "November value was USD 38.5M and volume 96,000 tonnes."
            ),
            paragraphs={"P6": "In November 2026, the value was USD 38.5M and volume 96,000 tonnes."}
        ),
        Document(
            doc_id="ORV-0046",
            event_id="E5",
            title="MOCK: Tolan wheat trade note",
            source_name="Realm Trade Ministry",
            source_type="trade_note",
            reliability_tier=1,
            pub_date="2027-01-20",
            country="Tolan",
            sector="Wheat",
            format="TXT",
            content=(
                "MOCK Tolan wheat imports fell from USD 115.8M in 2025-Q4 to USD 46.2M in 2026-Q4. "
                "Vanir replacement was smaller than the gap."
            ),
            paragraphs={
                "P5": "2025-Q4 imports were USD 115.8M.",
                "P7": "2026-Q4 imports were USD 46.2M.",
                "P14": (
                    "Tolan buyers replaced part of the lost volume with wheat from Vanir, "
                    "but the replacement was smaller than the gap."
                )
            }
        ),
        Document(
            doc_id="ORV-0001",
            event_id="E5",
            title="Vantro Trading rail capacity limit",
            source_name="Vantro Trading",
            source_type="company_statement",
            reliability_tier=2,
            pub_date="2026-10-20",
            country="Ravik",
            sector="Wheat",
            format="DOCX",
            content="The rail link can take only a fraction of normal port sea volume.",
            paragraphs={
                "P2": "The rail link can take only a fraction of the volume that normally leaves Orvan Grain Port by sea."
            }
        ),
        Document(
            doc_id="ORV-0050",
            event_id="E5",
            title="Ravik rail expansion note",
            source_name="Harbour Review",
            source_type="trade_press",
            reliability_tier=2,
            pub_date="2026-10-25",
            country="Ravik",
            sector="Wheat",
            format="TXT",
            content="Ravik rail link expanded grain freight traffic by +54% over USD 25M base.",
            paragraphs={"P2": "Rail freight expanded 54% over USD 25M base."}
        ),
    ]


@pytest.fixture
def sample_case_file() -> CaseFile:
    """Standard verified CaseFile."""
    return CaseFile(
        case_id="CASE-FEEDBACK-LOOP-TEST",
        question="As of 25 January 2027, how exposed are Midgard and Tolan to the end of the Orvan corridor agreement?",
        as_of_date="2027-01-25",
        is_verified=True,
        event_id="E5",
        round_number=1,
        run_number=1,
    )


# -----------------------------------------------------------------------------
# Test 1: Sufficient Evidence on First Trial Stops Immediately
# -----------------------------------------------------------------------------

def test_sufficient_evidence_first_trial_stops_immediately(
    feedback_mock_documents: list[Document],
    sample_case_file: CaseFile,
    tmp_path: Path,
):
    """Requirement: When Odin finds evidence sufficient on Trial 1, stop without retries."""
    retrieval = MockRetrievalService(documents=feedback_mock_documents)
    orchestrator = DebateOrchestrator(
        retrieval_service=retrieval,
        loki_memory=LokiMemoryService(storage_path=str(tmp_path / "lm.json")),
        thor_memory=ThorMemoryService(storage_path=str(tmp_path / "tm.json")),
        max_retries=2,
    )

    result = orchestrator.run_debate(sample_case_file)

    assert result.status == "success"
    assert result.total_trials == 1
    assert result.retries_attempted == 0
    assert result.loop_stop_reason == "evidence_sufficient"
    assert len(result.trial_history) == 1
    assert result.trial_history[0].trial_number == 1
    assert result.trial_history[0].is_evidence_sufficient is True


class PhasedMockRetrievalService(MockRetrievalService):
    """Mock retrieval service that dynamically reveals retry documents during targeted searches."""
    def __init__(self, initial_docs: list[Document], retry_docs: list[Document]):
        super().__init__(documents=initial_docs)
        self.retry_docs = {d.doc_id: d for d in retry_docs}
        self.enabled_retry = False

    def search(self, query: str, as_of_date: str, filters=None, limit=10):
        # Reveal retry docs when a targeted feedback loop query is received
        if self.enabled_retry or "direct wheat trade note" in query or "Stmt" in query:
            self.enabled_retry = True
            for doc in self.retry_docs.values():
                self.documents[doc.doc_id] = doc
        return super().search(query, as_of_date, filters, limit)


# -----------------------------------------------------------------------------
# Test 2: Insufficient Evidence with Actionable Gaps Triggers Targeted Retry
# -----------------------------------------------------------------------------

def test_insufficient_evidence_with_actionable_gaps_triggers_targeted_retry(
    feedback_mock_documents: list[Document],
    sample_case_file: CaseFile,
    tmp_path: Path,
):
    """Requirement: When evidence is insufficient on Trial 1 and new evidence is found, run Trial 2."""
    initial_docs = [d for d in feedback_mock_documents if d.doc_id not in ("ORV-0009", "ORV-0027")]
    retry_docs = [d for d in feedback_mock_documents if d.doc_id in ("ORV-0009", "ORV-0027")]
    retrieval = PhasedMockRetrievalService(initial_docs=initial_docs, retry_docs=retry_docs)

    # Mock Odin to report insufficient on Trial 1, but sufficient on Trial 2
    mock_odin = MagicMock(spec=OdinAgent)

    trial1_odin = OdinResult(
        agent="odin",
        case_id=sample_case_file.case_id,
        as_of_date=sample_case_file.as_of_date,
        run_number=1,
        adjudication_status="completed",
        claim_rulings=[
            ClaimRuling(
                claim_id="THOR-C01",
                claim_statement="Midgard direct wheat receipts fell from USD 260.4M in 2025-Q4 to USD 103.9M in 2026-Q4",
                proponent="thor",
                claim_type="sourced_fact",
                ruling="contested",
                confidence=0.3,
                reasoning="Claim THOR-C01 lacks admissible supporting evidence: Zero citations provided.",
                evidence_gaps=["Claim THOR-C01 lacks admissible supporting evidence: trade note missing."],
            )
        ],
        established_claims=[],
        contested_claims=["THOR-C01"],
        conceded_claims=[],
        unresolved_disputes=[],
        evidence_limitations=["Claim THOR-C01 lacks admissible supporting evidence: trade note missing."],
        evidence_examined=["ORV-0016"],
        is_evidence_sufficient=False,
        summary="Trial 1 Insufficient.",
    )

    trial2_odin = OdinResult(
        agent="odin",
        case_id=sample_case_file.case_id,
        as_of_date=sample_case_file.as_of_date,
        run_number=2,
        adjudication_status="completed",
        claim_rulings=[
            ClaimRuling(
                claim_id="THOR-C01",
                claim_statement="Midgard direct wheat receipts fell from USD 260.4M in 2025-Q4 to USD 103.9M in 2026-Q4",
                proponent="thor",
                claim_type="sourced_fact",
                ruling="established",
                confidence=0.95,
                reasoning="Established as sourced fact by ORV-0009.",
                evidence_gaps=[],
            )
        ],
        established_claims=["THOR-C01"],
        contested_claims=[],
        conceded_claims=[],
        unresolved_disputes=[],
        evidence_limitations=[],
        evidence_examined=["ORV-0016", "ORV-0009"],
        is_evidence_sufficient=True,
        summary="Trial 2 Sufficient.",
    )

    mock_odin.adjudicate_debate.side_effect = [trial1_odin, trial2_odin]

    orchestrator = DebateOrchestrator(
        retrieval_service=retrieval,
        odin_agent=mock_odin,
        loki_memory=LokiMemoryService(storage_path=str(tmp_path / "lm.json")),
        thor_memory=ThorMemoryService(storage_path=str(tmp_path / "tm.json")),
        max_retries=2,
    )

    result = orchestrator.run_debate(sample_case_file)

    assert result.status == "success"
    assert result.total_trials == 2
    assert result.retries_attempted == 1
    assert result.loop_stop_reason == "evidence_sufficient"
    assert len(result.trial_history) == 2
    assert result.trial_history[0].is_evidence_sufficient is False
    assert result.trial_history[1].is_evidence_sufficient is True
    assert len(result.trial_history[0].targeted_tasks_generated) >= 1
    assert len(result.trial_history[0].new_evidence_discovered) >= 1


# -----------------------------------------------------------------------------
# Test 3: Successful Retry Causes Re-adjudication by Odin
# -----------------------------------------------------------------------------

def test_successful_retry_causes_readjudication(
    feedback_mock_documents: list[Document],
    sample_case_file: CaseFile,
    tmp_path: Path,
):
    """Requirement: Odin is re-invoked on the updated debate deliverable on Trial 2."""
    initial_docs = [d for d in feedback_mock_documents if d.doc_id not in ("ORV-0009", "ORV-0027")]
    retry_docs = [d for d in feedback_mock_documents if d.doc_id in ("ORV-0009", "ORV-0027")]
    retrieval = PhasedMockRetrievalService(initial_docs=initial_docs, retry_docs=retry_docs)

    mock_odin = MagicMock(spec=OdinAgent)
    mock_odin.adjudicate_debate.side_effect = [
        OdinResult(
            agent="odin", case_id=sample_case_file.case_id, as_of_date=sample_case_file.as_of_date,
            run_number=1, adjudication_status="completed", claim_rulings=[
                ClaimRuling(
                    claim_id="THOR-C01", claim_statement="Midgard receipts drop",
                    proponent="thor", ruling="contested", reasoning="Lacks evidence.",
                    evidence_gaps=["Need Midgard wheat trade note receipts."],
                )
            ],
            established_claims=[], contested_claims=["THOR-C01"], conceded_claims=[],
            unresolved_disputes=[], evidence_limitations=["Need Midgard receipts."],
            evidence_examined=[], is_evidence_sufficient=False, summary="Trial 1",
        ),
        OdinResult(
            agent="odin", case_id=sample_case_file.case_id, as_of_date=sample_case_file.as_of_date,
            run_number=2, adjudication_status="completed", claim_rulings=[
                ClaimRuling(
                    claim_id="THOR-C01", claim_statement="Midgard receipts drop",
                    proponent="thor", ruling="established", reasoning="Verified by ORV-0009.",
                )
            ],
            established_claims=["THOR-C01"], contested_claims=[], conceded_claims=[],
            unresolved_disputes=[], evidence_limitations=[],
            evidence_examined=["ORV-0009"], is_evidence_sufficient=True, summary="Trial 2",
        ),
    ]

    orchestrator = DebateOrchestrator(
        retrieval_service=retrieval,
        odin_agent=mock_odin,
        loki_memory=LokiMemoryService(storage_path=str(tmp_path / "lm.json")),
        thor_memory=ThorMemoryService(storage_path=str(tmp_path / "tm.json")),
        max_retries=2,
    )

    result = orchestrator.run_debate(sample_case_file)

    assert mock_odin.adjudicate_debate.call_count == 2
    assert result.odin_adjudication is not None
    assert result.odin_adjudication.run_number == 2
    assert result.odin_adjudication.is_evidence_sufficient is True


# -----------------------------------------------------------------------------
# Test 4: Continued Insufficiency Stops at Configured Maximum Budget
# -----------------------------------------------------------------------------

def test_continued_insufficiency_stops_at_configured_maximum(
    feedback_mock_documents: list[Document],
    sample_case_file: CaseFile,
    tmp_path: Path,
):
    """Requirement: The retry budget is never exceeded. Stop when retries reach max_retries."""
    initial_docs = [d for d in feedback_mock_documents if d.doc_id not in ("ORV-0009", "ORV-0027")]
    retry_docs = [d for d in feedback_mock_documents if d.doc_id in ("ORV-0009", "ORV-0027")]
    retrieval = PhasedMockRetrievalService(initial_docs=initial_docs, retry_docs=retry_docs)

    mock_odin = MagicMock(spec=OdinAgent)

    # Always returns insufficient
    def make_insufficient_result(debate_res):
        run_no = getattr(debate_res, "run_number", 1) or 1
        return OdinResult(
            agent="odin", case_id=sample_case_file.case_id, as_of_date=sample_case_file.as_of_date,
            run_number=run_no, adjudication_status="completed",
            claim_rulings=[
                ClaimRuling(
                    claim_id="THOR-C01", claim_statement="Midgard direct wheat receipts drop",
                    proponent="thor", ruling="contested", reasoning="Continuous gap.",
                    evidence_gaps=["Unresolved gap in wheat data."],
                )
            ],
            established_claims=[], contested_claims=["THOR-C01"], conceded_claims=[],
            unresolved_disputes=[], evidence_limitations=["Unresolved gap."],
            evidence_examined=[], is_evidence_sufficient=False, summary=f"Trial {run_no}",
        )

    mock_odin.adjudicate_debate.side_effect = make_insufficient_result

    orchestrator = DebateOrchestrator(
        retrieval_service=retrieval,
        odin_agent=mock_odin,
        loki_memory=LokiMemoryService(storage_path=str(tmp_path / "lm.json")),
        thor_memory=ThorMemoryService(storage_path=str(tmp_path / "tm.json")),
        max_retries=1,  # Only 1 additional retry allowed (total 2 trials)
    )

    result = orchestrator.run_debate(sample_case_file)

    # Max retries was 1, so total trials must be 2 (Trial 1 + 1 retry)
    assert result.total_trials == 2
    assert result.retries_attempted == 1
    assert result.loop_stop_reason == "max_retries_exhausted"
    assert result.odin_adjudication is not None
    assert result.odin_adjudication.is_evidence_sufficient is False


# -----------------------------------------------------------------------------
# Test 5: Retry Exhaustion Preserves is_evidence_sufficient = False
# -----------------------------------------------------------------------------

def test_retry_exhaustion_preserves_insufficiency_flag(
    feedback_mock_documents: list[Document],
    sample_case_file: CaseFile,
    tmp_path: Path,
):
    """Requirement: Exhausting the retry budget must NEVER falsely claim evidence is sufficient."""
    mock_odin = MagicMock(spec=OdinAgent)
    mock_odin.adjudicate_debate.return_value = OdinResult(
        agent="odin", case_id=sample_case_file.case_id, as_of_date=sample_case_file.as_of_date,
        run_number=1, adjudication_status="completed",
        claim_rulings=[], established_claims=[], contested_claims=["C01"], conceded_claims=[],
        unresolved_disputes=[], evidence_limitations=["Data missing."],
        evidence_examined=[], is_evidence_sufficient=False, summary="Insufficient",
    )

    orchestrator = DebateOrchestrator(
        retrieval_service=MockRetrievalService(documents=feedback_mock_documents),
        odin_agent=mock_odin,
        loki_memory=LokiMemoryService(storage_path=str(tmp_path / "lm.json")),
        thor_memory=ThorMemoryService(storage_path=str(tmp_path / "tm.json")),
        max_retries=2,
    )

    result = orchestrator.run_debate(sample_case_file)

    assert result.loop_stop_reason in ("max_retries_exhausted", "no_actionable_gaps", "no_new_evidence")
    if result.odin_adjudication:
        assert result.odin_adjudication.is_evidence_sufficient is False


# -----------------------------------------------------------------------------
# Test 6: No Actionable Gaps Stops Early Without Redundant Retries
# -----------------------------------------------------------------------------

def test_no_actionable_gaps_stops_without_redundant_retries(
    feedback_mock_documents: list[Document],
    sample_case_file: CaseFile,
    tmp_path: Path,
):
    """Requirement: If no actionable queries can be formed, stop with no_actionable_gaps."""
    mock_odin = MagicMock(spec=OdinAgent)
    # Odin reports insufficient, but has empty rulings, empty limitations, empty disputes
    mock_odin.adjudicate_debate.return_value = OdinResult(
        agent="odin", case_id=sample_case_file.case_id, as_of_date=sample_case_file.as_of_date,
        run_number=1, adjudication_status="completed",
        claim_rulings=[], established_claims=[], contested_claims=[], conceded_claims=[],
        unresolved_disputes=[], evidence_limitations=[],
        evidence_examined=[], is_evidence_sufficient=False, summary="Insufficient with no gaps",
    )

    orchestrator = DebateOrchestrator(
        retrieval_service=MockRetrievalService(documents=feedback_mock_documents),
        odin_agent=mock_odin,
        loki_memory=LokiMemoryService(storage_path=str(tmp_path / "lm.json")),
        thor_memory=ThorMemoryService(storage_path=str(tmp_path / "tm.json")),
        max_retries=2,
    )

    result = orchestrator.run_debate(sample_case_file)

    assert result.total_trials == 1
    assert result.retries_attempted == 0
    assert result.loop_stop_reason == "no_actionable_gaps"


# -----------------------------------------------------------------------------
# Test 7: No New Admissible Evidence Stops with no_new_evidence
# -----------------------------------------------------------------------------

def test_no_new_evidence_triggers_no_progress_stop(
    feedback_mock_documents: list[Document],
    sample_case_file: CaseFile,
    tmp_path: Path,
):
    """Requirement: When targeted search discovers no new documents, stop early."""
    # Docs include Heimdall foundational docs, but lack ORV-0009 / ORV-0027
    sparse_docs = [d for d in feedback_mock_documents if d.doc_id not in ("ORV-0009", "ORV-0027")]
    retrieval = MockRetrievalService(documents=sparse_docs)

    mock_odin = MagicMock(spec=OdinAgent)
    mock_odin.adjudicate_debate.return_value = OdinResult(
        agent="odin", case_id=sample_case_file.case_id, as_of_date=sample_case_file.as_of_date,
        run_number=1, adjudication_status="completed",
        claim_rulings=[
            ClaimRuling(
                claim_id="THOR-C01", claim_statement="Midgard wheat receipts drop",
                proponent="thor", ruling="contested", reasoning="Lacks receipts evidence.",
                evidence_gaps=["Midgard receipts drop lacks evidence."],
            )
        ],
        established_claims=[], contested_claims=["THOR-C01"], conceded_claims=[],
        unresolved_disputes=[], evidence_limitations=["Midgard receipts drop lacks evidence."],
        evidence_examined=["ORV-0016"], is_evidence_sufficient=False, summary="Trial 1",
    )

    orchestrator = DebateOrchestrator(
        retrieval_service=retrieval,
        odin_agent=mock_odin,
        loki_memory=LokiMemoryService(storage_path=str(tmp_path / "lm.json")),
        thor_memory=ThorMemoryService(storage_path=str(tmp_path / "tm.json")),
        max_retries=2,
    )

    result = orchestrator.run_debate(sample_case_file)

    # Stopped on Trial 1 because targeted query found nothing new
    assert result.total_trials == 1
    assert result.retries_attempted == 0
    assert result.loop_stop_reason == "no_new_evidence"


# -----------------------------------------------------------------------------
# Test 8: Inadmissible, Retracted, or Post-Cutoff Evidence Rejected
# -----------------------------------------------------------------------------

def test_inadmissible_retracted_or_post_cutoff_cannot_establish_claim(
    sample_case_file: CaseFile,
):
    """Requirement: Targeted retrieval excludes post-cutoff and retracted documents."""
    inadmissible_docs = [
        Document(
            doc_id="ORV-0043",  # Retracted
            event_id="E5", title="Renewed", source_name="Whisper", source_type="press",
            reliability_tier=3, pub_date="2026-09-09", country="Orvan", sector="Wheat", format="TXT",
            content="Renewed corridor.", paragraphs={"P1": "Renewed."}
        ),
        Document(
            doc_id="ORV-0014",  # Post cutoff (2027-02-11 > 2027-01-25)
            event_id="E5", title="Future talks", source_name="Raven Wire", source_type="wire",
            reliability_tier=2, pub_date="2027-02-11", country="Realm", sector="Wheat", format="TXT",
            content="Future talks.", paragraphs={"P1": "Future talks."}
        ),
        Document(
            doc_id="ORV-0026",  # Tier 4 tabloid
            event_id="E5", title="Rumor", source_name="Saga Chat", source_type="social",
            reliability_tier=4, pub_date="2026-09-18", country="Orvan", sector="Wheat", format="TXT",
            content="All sunk.", paragraphs={"P1": "All sunk."}
        ),
    ]

    retrieval = MockRetrievalService(documents=inadmissible_docs)
    engine = SufficiencyFeedbackEngine(retrieval_service=retrieval)

    task = TargetedRetrievalTask(
        task_id="TASK-TEST",
        target_gap="Need corridor renewal notice",
        query="Corridor renewed ORV-0043 rumor ORV-0026",
    )

    new_evidence, updated_tasks = engine.execute_targeted_retrieval(
        tasks=[task],
        as_of_date="2027-01-25",
        examined_doc_ids=set(),
    )

    # All three documents must be rejected!
    assert len(new_evidence) == 0
    assert len(updated_tasks[0].admissible_citations) == 0
    assert len(updated_tasks[0].inadmissible_citations) >= 2


# -----------------------------------------------------------------------------
# Test 9: Non-Recoverable Validation Errors Do Not Trigger Retries
# -----------------------------------------------------------------------------

def test_non_recoverable_validation_errors_do_not_trigger_retries(
    feedback_mock_documents: list[Document],
    tmp_path: Path,
):
    """Requirement: Malformed case files exit immediately without retries."""
    retrieval = MockRetrievalService(documents=feedback_mock_documents)
    orchestrator = DebateOrchestrator(
        retrieval_service=retrieval,
        loki_memory=LokiMemoryService(storage_path=str(tmp_path / "lm.json")),
        thor_memory=ThorMemoryService(storage_path=str(tmp_path / "tm.json")),
        max_retries=2,
    )

    invalid_case = CaseFile(
        case_id="INVALID-CASE",
        question="Q",
        as_of_date="INVALID-DATE-FORMAT",
    )

    result = orchestrator.run_debate(invalid_case)

    assert result.status == "error"
    assert result.failed_stage == "validation"
    assert result.loop_stop_reason == "validation_failure"
    assert result.total_trials == 0
    assert result.retries_attempted == 0


# -----------------------------------------------------------------------------
# Test 10: Non-Recoverable Heimdall Rejection Does Not Trigger Retries
# -----------------------------------------------------------------------------

def test_non_recoverable_heimdall_rejection_does_not_trigger_retries(
    sample_case_file: CaseFile,
    tmp_path: Path,
):
    """Requirement: If Heimdall rejects the foundational event, debate stops with 0 retries."""
    # Empty corpus -> Heimdall cannot verify premises
    retrieval = MockRetrievalService(documents=[])
    orchestrator = DebateOrchestrator(
        retrieval_service=retrieval,
        loki_memory=LokiMemoryService(storage_path=str(tmp_path / "lm.json")),
        thor_memory=ThorMemoryService(storage_path=str(tmp_path / "tm.json")),
        max_retries=2,
    )

    result = orchestrator.run_debate(sample_case_file)

    assert result.status == "error"
    assert result.failed_stage == "heimdall_verification"
    assert result.loop_stop_reason == "heimdall_gate_rejected"
    assert result.retries_attempted == 0


# -----------------------------------------------------------------------------
# Test 11: Agent Exceptions Preserve Earlier Completed Results
# -----------------------------------------------------------------------------

def test_agent_exceptions_preserve_earlier_completed_results(
    feedback_mock_documents: list[Document],
    sample_case_file: CaseFile,
    tmp_path: Path,
):
    """Requirement: If an agent throws an exception on Trial 2, Trial 1 outputs are preserved."""
    failing_thor = MagicMock(spec=ThorAgent)

    # Trial 1: Thor succeeds
    thor_r1_success = ThorResult(
        agent="thor", case_id=sample_case_file.case_id, as_of_date=sample_case_file.as_of_date,
        round_number=1, run_number=1, claims=[], attacks=[], concessions=[],
        uncertainties=[], memory_used=[], search_log=[], status="success", error_message=None,
    )
    # Trial 2: Thor raises exception
    failing_thor.investigate_and_argue.side_effect = [
        thor_r1_success,  # Trial 1 Round 1
        thor_r1_success,  # Trial 1 Round 2
        RuntimeError("Database lock on Trial 2"),  # Trial 2 Round 1
    ]

    mock_odin = MagicMock(spec=OdinAgent)
    mock_odin.adjudicate_debate.return_value = OdinResult(
        agent="odin", case_id=sample_case_file.case_id, as_of_date=sample_case_file.as_of_date,
        run_number=1, adjudication_status="completed",
        claim_rulings=[
            ClaimRuling(
                claim_id="THOR-C01", claim_statement="Midgard wheat receipts drop",
                proponent="thor", ruling="contested", reasoning="Lacks receipts.",
                evidence_gaps=["Need trade note receipts."],
            )
        ],
        established_claims=[], contested_claims=["THOR-C01"], conceded_claims=[],
        unresolved_disputes=[], evidence_limitations=["Need trade note receipts."],
        evidence_examined=["ORV-0016"], is_evidence_sufficient=False, summary="Trial 1",
    )

    initial_docs = [d for d in feedback_mock_documents if d.doc_id not in ("ORV-0009", "ORV-0027")]
    retry_docs = [d for d in feedback_mock_documents if d.doc_id in ("ORV-0009", "ORV-0027")]
    retrieval = PhasedMockRetrievalService(initial_docs=initial_docs, retry_docs=retry_docs)
    orchestrator = DebateOrchestrator(
        retrieval_service=retrieval,
        thor_agent=failing_thor,
        odin_agent=mock_odin,
        loki_memory=LokiMemoryService(storage_path=str(tmp_path / "lm.json")),
        thor_memory=ThorMemoryService(storage_path=str(tmp_path / "tm.json")),
        max_retries=2,
    )

    result = orchestrator.run_debate(sample_case_file)

    assert result.status in ("partial", "error")
    assert result.loop_stop_reason == "agent_failure"
    # Trial 1 is preserved in trial_history[0]!
    assert len(result.trial_history) == 2
    assert result.trial_history[0].trial_number == 1
    assert result.trial_history[0].status == "success"
    assert result.trial_history[1].trial_number == 2
    assert result.trial_history[1].status in ("partial", "error")


# -----------------------------------------------------------------------------
# Test 12: Previous Trial Deliverables Not Overwritten
# -----------------------------------------------------------------------------

def test_previous_trial_deliverables_not_overwritten(
    feedback_mock_documents: list[Document],
    sample_case_file: CaseFile,
    tmp_path: Path,
):
    """Requirement: Earlier trial results are preserved in TrialRecord with distinct objects."""
    mock_odin = MagicMock(spec=OdinAgent)
    mock_odin.adjudicate_debate.side_effect = [
        OdinResult(
            agent="odin", case_id=sample_case_file.case_id, as_of_date=sample_case_file.as_of_date,
            run_number=1, adjudication_status="completed",
            claim_rulings=[
                ClaimRuling(
                    claim_id="C01", claim_statement="Midgard direct wheat receipts drop",
                    proponent="thor", ruling="contested", reasoning="R1",
                    evidence_gaps=["Need Midgard wheat receipts."]
                )
            ],
            established_claims=[], contested_claims=["C01"], conceded_claims=[],
            unresolved_disputes=[], evidence_limitations=["Need Midgard wheat receipts."],
            evidence_examined=["ORV-0016"], is_evidence_sufficient=False, summary="Trial 1",
        ),
        OdinResult(
            agent="odin", case_id=sample_case_file.case_id, as_of_date=sample_case_file.as_of_date,
            run_number=2, adjudication_status="completed",
            claim_rulings=[
                ClaimRuling(
                    claim_id="C01", claim_statement="Midgard direct wheat receipts drop",
                    proponent="thor", ruling="established", reasoning="R2"
                )
            ],
            established_claims=["C01"], contested_claims=[], conceded_claims=[],
            unresolved_disputes=[], evidence_limitations=[],
            evidence_examined=["ORV-0016", "ORV-0009"], is_evidence_sufficient=True, summary="Trial 2",
        ),
    ]

    initial_docs = [d for d in feedback_mock_documents if d.doc_id not in ("ORV-0009", "ORV-0027")]
    retry_docs = [d for d in feedback_mock_documents if d.doc_id in ("ORV-0009", "ORV-0027")]
    retrieval = PhasedMockRetrievalService(initial_docs=initial_docs, retry_docs=retry_docs)
    orchestrator = DebateOrchestrator(
        retrieval_service=retrieval,
        odin_agent=mock_odin,
        loki_memory=LokiMemoryService(storage_path=str(tmp_path / "lm.json")),
        thor_memory=ThorMemoryService(storage_path=str(tmp_path / "tm.json")),
        max_retries=2,
    )

    result = orchestrator.run_debate(sample_case_file)

    assert len(result.trial_history) == 2
    t1 = result.trial_history[0]
    t2 = result.trial_history[1]

    assert t1.trial_number == 1
    assert t2.trial_number == 2
    assert t1.is_evidence_sufficient is False
    assert t2.is_evidence_sufficient is True
    assert t1.odin_adjudication is not None and t1.odin_adjudication.run_number == 1
    assert t2.odin_adjudication is not None and t2.odin_adjudication.run_number == 2


# -----------------------------------------------------------------------------
# Test 13: Official Runemark Corpus E5 End-to-End Integration
# -----------------------------------------------------------------------------

def test_official_corpus_e5_feedback_loop_integration(
    tmp_path: Path,
):
    """Requirement: End-to-end feedback loop test against official dev_pack_E5 corpus."""
    pack_dir = Path("03_Ragnarok Trial of the Nine Realms/dev_pack_E5")
    if not pack_dir.exists():
        pack_dir = Path(__file__).resolve().parents[2] / "03_Ragnarok Trial of the Nine Realms" / "dev_pack_E5"
    if not pack_dir.exists():
        pytest.skip("Official dev_pack_E5 corpus directory not available.")

    retrieval = RunemarkCorpusRetrievalService(str(pack_dir))
    orchestrator = DebateOrchestrator(
        retrieval_service=retrieval,
        loki_memory=LokiMemoryService(storage_path=str(tmp_path / "lm.json")),
        thor_memory=ThorMemoryService(storage_path=str(tmp_path / "tm.json")),
        max_retries=2,
    )

    case_file = CaseFile(
        case_id="CASE-CORPUS-FEEDBACK-E5",
        question="As of 25 January 2027, how exposed are Midgard and Tolan to the end of the Orvan corridor agreement?",
        as_of_date="2027-01-25",
        is_verified=True,
        event_id="E5",
    )

    result = orchestrator.run_debate(case_file)

    assert result.status == "success"
    assert result.total_trials >= 1
    assert result.loop_stop_reason in ("evidence_sufficient", "no_actionable_gaps", "max_retries_exhausted", "no_new_evidence")
    assert len(result.trial_history) >= 1
    assert result.odin_adjudication is not None
    assert result.odin_adjudication.adjudication_status == "completed"
