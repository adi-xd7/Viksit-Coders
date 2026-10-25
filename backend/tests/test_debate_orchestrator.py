"""Tests for the Multi-Agent Debate Orchestrator (Part 5A)."""

import pytest
from pathlib import Path
from unittest.mock import MagicMock

from backend.app.schemas.evidence import Document, EvidenceReference
from backend.app.schemas.claim import Claim, ExposureEstimate
from backend.app.schemas.debate import CrossExamination, Concession
from backend.app.schemas.case_file import CaseFile
from backend.app.schemas.debate_result import DebateResult
from backend.app.schemas.loki_result import LokiResult
from backend.app.schemas.thor_result import ThorResult
from backend.app.services.retrieval import MockRetrievalService, RunemarkCorpusRetrievalService
from backend.app.services.memory import LokiMemoryService
from backend.app.services.thor_memory import ThorMemoryService
from backend.app.agents.loki import LokiAgent
from backend.app.agents.thor import ThorAgent
from backend.app.services.debate_orchestrator import DebateOrchestrator


@pytest.fixture
def orchestrator_mock_documents() -> list[Document]:
    """Rich set of synthetic mock documents allowing both Loki and Thor to find grounded evidence."""
    return [
        Document(
            doc_id="ORV-0027",
            event_id="E5",
            title="MOCK: Vanir to Midgard trade note",
            source_name="Realm Trade Ministry",
            source_type="trade_note",
            reliability_tier=1,
            pub_date="2027-01-22",
            country="Midgard",
            sector="Wheat",
            format="TXT",
            content="MOCK Vanir to Midgard wheat shipments surged in Nov-Dec. In November 2026, value was USD 38.5M and volume 96,000 tonnes.",
            paragraphs={"P6": "In November 2026, the value was USD 38.5M and the volume was 96,000 tonnes."}
        ),
        Document(
            doc_id="ORV-0044",
            event_id="E5",
            title="MOCK: Vanir to Tolan trade note",
            source_name="Cargo Weekly",
            source_type="trade_note",
            reliability_tier=2,
            pub_date="2027-01-22",
            country="Tolan",
            sector="Wheat",
            format="DOCX",
            content="MOCK Vanir to Tolan wheat trade replacement. Tolan buyers replaced part of lost volume with wheat from Vanir.",
            paragraphs={"P2": "In July 2026, the value was USD 20.0M and volume 54,000 tonnes."}
        ),
        Document(
            doc_id="ORV-0042",
            event_id="E5",
            title="MOCK: Anchor Marine Tolan Harbour update",
            source_name="Anchor Marine",
            source_type="company_statement",
            reliability_tier=2,
            pub_date="2026-11-25",
            country="Tolan",
            sector="Wheat",
            format="TXT",
            content="MOCK Tolan Harbour handling extra wheat cargoes from Vanir to replace Orvan supply.",
            paragraphs={"P1": "Anchor Marine says Tolan Harbour is handling more wheat cargoes from Vanir."}
        ),
        Document(
            doc_id="ORV-0030",
            event_id="E5",
            title="MOCK: Midgard Maize trade note",
            source_name="Realm Trade Ministry",
            source_type="trade_note",
            reliability_tier=1,
            pub_date="2027-01-20",
            country="Midgard",
            sector="Wheat",
            format="TXT",
            content="MOCK Midgard maize receipts held up in October 2026 at USD 62.1M due to delayed delivery terms before dropping.",
            paragraphs={
                "P5": "October 2026 imports were USD 62.1M.",
                "P14": "Contract terms deferred delivery, buffering October volumes."
            }
        ),
        Document(
            doc_id="ORV-0018",
            event_id="E5",
            title="MOCK: Regional grain transport model",
            source_name="Ledger Analytics",
            source_type="analyst_report",
            reliability_tier=3,
            pub_date="2026-11-12",
            country="Orvan",
            sector="Wheat",
            format="TXT",
            content="MOCK Macro model indicates net value loss is cushioned to 40% due to rail links and Vanir substitution.",
            paragraphs={"P8": "Net value loss modeled at 35% to 45%."}
        ),
        Document(
            doc_id="ORV-0050",
            event_id="E5",
            title="MOCK: Ravik rail expansion note",
            source_name="Harbour Review",
            source_type="trade_press",
            reliability_tier=2,
            pub_date="2026-10-25",
            country="Ravik",
            sector="Wheat",
            format="TXT",
            content="MOCK Ravik rail link expanded grain traffic by +54% over USD 25M base.",
            paragraphs={"P2": "Rail freight expanded 54% over USD 25M base."}
        ),
        Document(
            doc_id="ORV-0001",
            event_id="E5",
            title="MOCK: Vantro Trading rail capacity limit",
            source_name="Vantro Trading",
            source_type="company_statement",
            reliability_tier=2,
            pub_date="2026-10-20",
            country="Ravik",
            sector="Wheat",
            format="DOCX",
            content="Vantro Trading says rail is only a partial substitute. The rail link can take only a fraction of normal port sea volume.",
            paragraphs={
                "P1": "Vantro shifted some Orvan wheat to Ravik rail.",
                "P2": "The rail link can take only a fraction of the volume that normally leaves Orvan Grain Port by sea.",
                "P3": "Rail cannot replace lost sea volumes."
            }
        ),
        Document(
            doc_id="ORV-0009",
            event_id="E5",
            title="MOCK: Midgard wheat trade note",
            source_name="Realm Trade Ministry",
            source_type="trade_note",
            reliability_tier=1,
            pub_date="2027-01-19",
            country="Midgard",
            sector="Wheat",
            format="TXT",
            content="MOCK Midgard direct wheat receipts fell from USD 260.4M in 2025-Q4 to USD 103.9M in 2026-Q4 (down 60.1%).",
            paragraphs={
                "P5": "2025-Q4 imports were USD 260.4M.",
                "P7": "2026-Q4 imports were USD 103.9M.",
                "P11": "Net value loss was 60.1%."
            }
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
            content="MOCK Tolan wheat imports fell from USD 115.8M in 2025-Q4 to USD 46.2M in 2026-Q4. Vanir replacement was smaller than the gap.",
            paragraphs={
                "P5": "2025-Q4 imports were USD 115.8M.",
                "P7": "2026-Q4 imports were USD 46.2M.",
                "P14": "Tolan buyers replaced part of the lost volume with wheat from Vanir, but the replacement was smaller than the gap."
            }
        ),
        Document(
            doc_id="ORV-0016",
            event_id="E5",
            title="MOCK: Corridor agreement expiration notice",
            source_name="Realm Trade Ministry",
            source_type="official_notice",
            reliability_tier=1,
            pub_date="2026-09-12",
            country="Orvan",
            sector="Wheat",
            format="TXT",
            content="Corridor Agreement expired on 10 September 2026 without extension.",
            paragraphs={"P1": "Corridor Agreement expired on 10 September 2026 without extension."}
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
            doc_id="ORV-0016",
            event_id="E5",
            title="MOCK: Corridor Agreement expires with no renewal",
            source_name="Realm Trade Ministry",
            source_type="official_notice",
            reliability_tier=1,
            pub_date="2026-09-10",
            country="Realm",
            sector="Wheat",
            format="PDF",
            content="Notice from Realm Trade Ministry. The Corridor Agreement expired on 10 September 2026. Talks on renewal ended without agreement.",
            paragraphs={
                "P1": "Notice from the Realm Trade Ministry. The Corridor Agreement expired on 10 September 2026.",
                "P2": "Talks on renewal ended without agreement. No replacement arrangement has been signed."
            }
        ),
    ]


@pytest.fixture
def sample_debate_case_file() -> CaseFile:
    """A standard verified CaseFile for debate orchestration testing."""
    return CaseFile(
        case_id="CASE-E5-ORCHESTRATION-TEST",
        question="As of 25 January 2027, how exposed are Midgard and Tolan to the end of the Orvan corridor agreement?",
        as_of_date="2027-01-25",
        is_verified=True,
        event_id="E5",
        round_number=1,
        run_number=1,
        claims=[],
        attacks=[],
        concessions=[],
    )


# -----------------------------------------------------------------------------
# Test 1: Successful Full Sequence with Correct Call Order
# -----------------------------------------------------------------------------

def test_debate_successful_full_sequence_call_order(
    orchestrator_mock_documents: list[Document],
    sample_debate_case_file: CaseFile,
    tmp_path: Path,
):
    """Requirement: The orchestrator coordinates agents in a deterministic sequence across R1 and R2."""
    retrieval = MockRetrievalService(documents=orchestrator_mock_documents)
    loki_mem = LokiMemoryService(storage_path=str(tmp_path / "loki_mem.json"))
    thor_mem = ThorMemoryService(storage_path=str(tmp_path / "thor_mem.json"))

    orchestrator = DebateOrchestrator(
        retrieval_service=retrieval,
        loki_memory=loki_mem,
        thor_memory=thor_mem,
    )

    result = orchestrator.run_debate(sample_debate_case_file)

    assert result.status == "success"
    assert result.failed_stage is None
    assert result.error_message is None

    # Verify all expected stages executed in strict chronological order, starting with Heimdall verification and concluding with Odin adjudication
    expected_stages = [
        "validation",
        "heimdall_verification",
        "loki_round1",
        "thor_round1",
        "loki_round2",
        "thor_round2",
        "odin_adjudication",
    ]
    assert result.stages_executed == expected_stages

    # Verify Heimdall verification deliverable preserved
    assert result.heimdall_verification is not None
    assert result.heimdall_verification.is_event_real is True
    assert result.heimdall_verification.verification_status == "verified"

    # Verify Odin judicial adjudication deliverable preserved
    assert result.odin_adjudication is not None
    assert result.odin_adjudication.adjudication_status == "completed"
    assert len(result.odin_adjudication.claim_rulings) >= 1

    # Verify structured deliverables preserved
    assert result.loki_round1 is not None
    assert result.thor_round1 is not None
    assert result.loki_round2 is not None
    assert result.thor_round2 is not None


    # Verify both Loki and Thor submitted Round 1 claims
    assert len(result.loki_round1.claims) >= 1
    assert len(result.thor_round1.claims) >= 1

    # Verify Round 2 cross-examination attacks were launched
    assert len(result.case_file.attacks) >= 1
    assert any(a.challenger == "thor" for a in result.case_file.attacks)

    # Verify final CaseFile state
    assert result.case_file.round_number == 2
    assert len(result.case_file.claims) == len(result.loki_round1.claims) + len(result.thor_round1.claims)


# -----------------------------------------------------------------------------
# Test 2: Loki's Round 1 Result is Passed into Thor's Round 2 Workflow
# -----------------------------------------------------------------------------

def test_loki_r1_passed_to_thor_r2_cross_examination(
    orchestrator_mock_documents: list[Document],
    sample_debate_case_file: CaseFile,
    tmp_path: Path,
):
    """Requirement: Thor attacks real Loki claims supplied from Loki's Round 1 analysis."""
    retrieval = MockRetrievalService(documents=orchestrator_mock_documents)
    orchestrator = DebateOrchestrator(
        retrieval_service=retrieval,
        loki_memory=LokiMemoryService(storage_path=str(tmp_path / "loki_m.json")),
        thor_memory=ThorMemoryService(storage_path=str(tmp_path / "thor_m.json")),
    )

    result = orchestrator.run_debate(sample_debate_case_file)

    assert result.loki_round1 is not None
    assert result.thor_round2 is not None
    loki_claim_ids = {c.claim_id for c in result.loki_round1.claims}
    thor_attacks = [a for a in result.thor_round2.attacks if a.challenger == "thor"]

    # Verify Thor attacked real Loki claims
    assert len(thor_attacks) >= 1
    for attack in thor_attacks:
        assert attack.target_claim_id in loki_claim_ids


# -----------------------------------------------------------------------------
# Test 3: Thor's Round 1 Result is Passed to Loki's Round 2 Workflow
# -----------------------------------------------------------------------------

def test_thor_r1_passed_to_loki_r2_cross_examination(
    orchestrator_mock_documents: list[Document],
    sample_debate_case_file: CaseFile,
    tmp_path: Path,
):
    """Requirement: Loki attacks real Thor claims supplied from Thor's Round 1 analysis."""
    retrieval = MockRetrievalService(documents=orchestrator_mock_documents)
    orchestrator = DebateOrchestrator(
        retrieval_service=retrieval,
        loki_memory=LokiMemoryService(storage_path=str(tmp_path / "loki_m.json")),
        thor_memory=ThorMemoryService(storage_path=str(tmp_path / "thor_m.json")),
    )

    result = orchestrator.run_debate(sample_debate_case_file)

    assert result.thor_round1 is not None
    assert result.loki_round2 is not None
    thor_claim_ids = {c.claim_id for c in result.thor_round1.claims}
    loki_attacks = [a for a in result.loki_round2.attacks if a.challenger == "loki"]

    assert len(loki_attacks) >= 1
    for attack in loki_attacks:
        assert attack.target_claim_id in thor_claim_ids


# -----------------------------------------------------------------------------
# Test 4: Cross-Examination and Concessions Assembled with Provenance
# -----------------------------------------------------------------------------

def test_cross_examination_and_concessions_assembled_with_provenance(
    orchestrator_mock_documents: list[Document],
    sample_debate_case_file: CaseFile,
    tmp_path: Path,
):
    """Requirement: Final DebateResult preserves all claim IDs, citations, paragraphs, and provenance."""
    retrieval = MockRetrievalService(documents=orchestrator_mock_documents)
    orchestrator = DebateOrchestrator(
        retrieval_service=retrieval,
        loki_memory=LokiMemoryService(storage_path=str(tmp_path / "loki_m.json")),
        thor_memory=ThorMemoryService(storage_path=str(tmp_path / "thor_m.json")),
    )

    result = orchestrator.run_debate(sample_debate_case_file)

    # Check claim provenance
    for claim in result.claims:
        assert claim.claim_id.startswith(("LOKI-C", "THOR-C"))
        for cit in claim.citations:
            assert cit.doc_id.startswith("ORV-")
            assert cit.reliability_tier in [1, 2, 3, 4]

    # Check attack provenance
    for attack in result.attacks:
        assert attack.challenge_id.startswith(("LOKI-X", "THOR-X"))
        assert attack.target_claim_id.startswith(("LOKI-C", "THOR-C"))

    # Check concession structure
    for conc in result.concessions:
        assert conc.concession_id.startswith(("LOKI-CON", "THOR-CON"))
        assert conc.action in ["concede", "defend", "adjust_range"]


# -----------------------------------------------------------------------------
# Test 5: Loki Failure is Recorded and Thor Not Presented as Full Debate
# -----------------------------------------------------------------------------

def test_loki_failure_recorded_and_debate_stops(
    sample_debate_case_file: CaseFile,
):
    """Requirement: If Loki fails during Round 1, record failure explicitly and do not claim full debate."""
    failing_loki = MagicMock(spec=LokiAgent)
    failing_loki.investigate_and_argue.side_effect = RuntimeError("Simulated Loki crash on database timeout.")
    failing_loki.memory = LokiMemoryService()

    valid_thor = MagicMock(spec=ThorAgent)
    valid_thor.memory = ThorMemoryService()

    orchestrator = DebateOrchestrator(
        loki_agent=failing_loki,
        thor_agent=valid_thor,
    )

    result = orchestrator.run_debate(sample_debate_case_file)

    assert result.status == "error"
    assert result.failed_stage == "loki_round1"
    assert result.error_message is not None
    assert "Simulated Loki crash" in result.error_message
    assert result.loki_round1 is None
    assert result.thor_round1 is None
    assert "thor_round1" not in result.stages_executed
    assert valid_thor.investigate_and_argue.call_count == 0


# -----------------------------------------------------------------------------
# Test 6: Thor Failure Preserves Loki's Completed Result
# -----------------------------------------------------------------------------

def test_thor_failure_preserves_loki_completed_result(
    orchestrator_mock_documents: list[Document],
    sample_debate_case_file: CaseFile,
    tmp_path: Path,
):
    """Requirement: If Thor fails in Round 1, preserve Loki's completed Round 1 result and claims."""
    real_loki = LokiAgent(
        retrieval_service=MockRetrievalService(documents=orchestrator_mock_documents),
        memory_service=LokiMemoryService(storage_path=str(tmp_path / "loki_m.json")),
    )

    failing_thor = MagicMock(spec=ThorAgent)
    failing_thor.investigate_and_argue.side_effect = RuntimeError("Thor worker thread memory exhaustion.")
    failing_thor.memory = ThorMemoryService(storage_path=str(tmp_path / "thor_m.json"))

    orchestrator = DebateOrchestrator(
        loki_agent=real_loki,
        thor_agent=failing_thor,
    )

    result = orchestrator.run_debate(sample_debate_case_file)

    assert result.status == "partial"
    assert result.failed_stage == "thor_round1"
    assert result.error_message is not None
    assert "Thor worker thread memory exhaustion" in result.error_message

    # Loki result is preserved intact
    assert result.loki_round1 is not None
    assert len(result.loki_round1.claims) >= 1
    assert result.thor_round1 is None
    assert "loki_round1" in result.stages_executed
    assert "thor_round1" not in result.stages_executed


# -----------------------------------------------------------------------------
# Test 7: Malformed Input Handled Gracefully
# -----------------------------------------------------------------------------

def test_malformed_input_handled_gracefully(
    orchestrator_mock_documents: list[Document],
):
    """Requirement: Handle missing, malformed, or empty inputs without crashing."""
    retrieval = MockRetrievalService(documents=orchestrator_mock_documents)
    orchestrator = DebateOrchestrator(retrieval_service=retrieval)

    # 1. None CaseFile
    r1 = orchestrator.run_debate(None)  # type: ignore
    assert r1.status == "error"
    assert r1.failed_stage == "validation"
    assert r1.error_message is not None
    assert "None" in r1.error_message

    # 2. Missing case_id
    bad_cf1 = CaseFile(case_id="", question="Question", as_of_date="2027-01-25")
    r2 = orchestrator.run_debate(bad_cf1)
    assert r2.status == "error"
    assert r2.failed_stage == "validation"
    assert r2.error_message is not None
    assert "case_id" in r2.error_message

    # 3. Invalid as_of_date format
    bad_cf2 = CaseFile(case_id="CASE-1", question="Question", as_of_date="invalid-date-format")
    r3 = orchestrator.run_debate(bad_cf2)
    assert r3.status == "error"
    assert r3.failed_stage == "validation"
    assert r3.error_message is not None
    assert "as_of_date" in r3.error_message


# -----------------------------------------------------------------------------
# Test 8: Case ID and As-Of-Date Preserved Across All Deliverables
# -----------------------------------------------------------------------------

def test_case_id_and_as_of_date_preserved(
    orchestrator_mock_documents: list[Document],
    sample_debate_case_file: CaseFile,
    tmp_path: Path,
):
    """Requirement: The target case_id and as_of_date are consistently maintained across the workflow."""
    retrieval = MockRetrievalService(documents=orchestrator_mock_documents)
    orchestrator = DebateOrchestrator(
        retrieval_service=retrieval,
        loki_memory=LokiMemoryService(storage_path=str(tmp_path / "loki_m.json")),
        thor_memory=ThorMemoryService(storage_path=str(tmp_path / "thor_m.json")),
    )

    result = orchestrator.run_debate(sample_debate_case_file)

    assert result.case_id == "CASE-E5-ORCHESTRATION-TEST"
    assert result.as_of_date == "2027-01-25"
    assert result.case_file.case_id == "CASE-E5-ORCHESTRATION-TEST"
    assert result.case_file.as_of_date == "2027-01-25"
    assert result.loki_round1 is not None
    assert result.thor_round1 is not None
    assert result.loki_round1.case_id == "CASE-E5-ORCHESTRATION-TEST"
    assert result.thor_round1.case_id == "CASE-E5-ORCHESTRATION-TEST"


# -----------------------------------------------------------------------------
# Test 9: Loki and Thor Memory Services Must Not Be Shared
# -----------------------------------------------------------------------------

def test_loki_and_thor_memory_isolation_enforced():
    """Requirement: Loki and Thor memory services must be separate instances (NFR 1, NFR 6)."""
    retrieval = MockRetrievalService(documents=[])
    shared_memory = LokiMemoryService()

    # Create agents that mistakenly share the exact same memory instance
    loki = LokiAgent(retrieval_service=retrieval, memory_service=shared_memory)
    thor = ThorAgent(retrieval_service=retrieval, memory_service=shared_memory)  # type: ignore

    with pytest.raises(ValueError, match="separate, isolated memory service instances"):
        DebateOrchestrator(loki_agent=loki, thor_agent=thor)


# -----------------------------------------------------------------------------
# Test 10: No Stage is Executed Twice
# -----------------------------------------------------------------------------

def test_no_stage_silently_executed_twice(
    orchestrator_mock_documents: list[Document],
    sample_debate_case_file: CaseFile,
    tmp_path: Path,
):
    """Requirement: Each orchestration stage must execute exactly once per debate run."""
    retrieval = MockRetrievalService(documents=orchestrator_mock_documents)
    orchestrator = DebateOrchestrator(
        retrieval_service=retrieval,
        loki_memory=LokiMemoryService(storage_path=str(tmp_path / "loki_m.json")),
        thor_memory=ThorMemoryService(storage_path=str(tmp_path / "thor_m.json")),
    )

    result = orchestrator.run_debate(sample_debate_case_file)

    stages = result.stages_executed
    assert len(stages) == len(set(stages)), "Stage duplicated in execution log!"
    assert stages == [
        "validation",
        "heimdall_verification",
        "loki_round1",
        "thor_round1",
        "loki_round2",
        "thor_round2",
        "odin_adjudication",
    ]




# -----------------------------------------------------------------------------
# Test 11: Schema-Valid and Deterministic Output
# -----------------------------------------------------------------------------

def test_deterministic_debate_output(
    orchestrator_mock_documents: list[Document],
    sample_debate_case_file: CaseFile,
    tmp_path: Path,
):
    """Requirement: Identical inputs produce deterministic debate outputs."""
    retrieval = MockRetrievalService(documents=orchestrator_mock_documents)

    orch1 = DebateOrchestrator(
        retrieval_service=retrieval,
        loki_memory=LokiMemoryService(storage_path=str(tmp_path / "loki1.json")),
        thor_memory=ThorMemoryService(storage_path=str(tmp_path / "thor1.json")),
    )
    orch2 = DebateOrchestrator(
        retrieval_service=retrieval,
        loki_memory=LokiMemoryService(storage_path=str(tmp_path / "loki2.json")),
        thor_memory=ThorMemoryService(storage_path=str(tmp_path / "thor2.json")),
    )

    r1 = orch1.run_debate(sample_debate_case_file)
    r2 = orch2.run_debate(sample_debate_case_file)

    assert r1.status == r2.status == "success"
    assert len(r1.claims) == len(r2.claims)
    assert len(r1.attacks) == len(r2.attacks)
    assert len(r1.concessions) == len(r2.concessions)

    # Claim IDs and statements match
    assert [c.claim_id for c in r1.claims] == [c.claim_id for c in r2.claims]
    assert [a.challenge_id for a in r1.attacks] == [a.challenge_id for a in r2.attacks]


# -----------------------------------------------------------------------------
# Test 12: Official Runemark Corpus Integration
# -----------------------------------------------------------------------------

def test_official_runemark_corpus_debate_integration(
    tmp_path: Path,
):
    """Integration test: Verify end-to-end debate orchestration on real dev_pack_E5 corpus."""
    pack_dir = Path("03_Ragnarok Trial of the Nine Realms/dev_pack_E5")
    if not pack_dir.exists():
        pack_dir = Path(__file__).resolve().parents[2] / "03_Ragnarok Trial of the Nine Realms" / "dev_pack_E5"
    if not pack_dir.exists():
        pytest.skip("Official dev_pack_E5 not found")

    corpus = RunemarkCorpusRetrievalService(pack_dir=str(pack_dir))
    orchestrator = DebateOrchestrator(
        retrieval_service=corpus,
        loki_memory=LokiMemoryService(storage_path=str(tmp_path / "loki_real.json")),
        thor_memory=ThorMemoryService(storage_path=str(tmp_path / "thor_real.json")),
    )

    case_file = CaseFile(
        case_id="CASE-E5-OFFICIAL-DEBATE",
        question="As of 25 January 2027, how exposed are Midgard and Tolan to the end of the Orvan corridor agreement?",
        as_of_date="2027-01-25",
        is_verified=True,
        event_id="E5",
        round_number=1,
    )

    result = orchestrator.run_debate(case_file)

    assert result.status == "success"
    assert result.failed_stage is None
    assert len(result.claims) >= 4
    assert len(result.attacks) >= 2
    assert len(result.concessions) >= 1

    # Verify both agents participated in claims, attacks, and concessions
    agents_claiming = {c.agent for c in result.claims}
    assert "loki" in agents_claiming
    assert "thor" in agents_claiming

    challengers = {a.challenger for a in result.attacks}
    assert "loki" in challengers
    assert "thor" in challengers

    conceding_agents = {c.agent for c in result.concessions}
    assert "thor" in conceding_agents or "loki" in conceding_agents
