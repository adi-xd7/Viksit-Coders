"""Tests for LokiAgent: Round 1 claims, Round 2 attacks, concessions, and failure resilience."""

from pathlib import Path
import pytest
from backend.app.agents.loki import LokiAgent
from backend.app.schemas.case_file import CaseFile
from backend.app.schemas.claim import Claim, ExposureEstimate
from backend.app.schemas.evidence import Document, EvidenceReference
from backend.app.schemas.debate import CrossExamination
from backend.app.services.retrieval import MockRetrievalService, RunemarkCorpusRetrievalService
from backend.app.services.memory import LokiMemoryService
from backend.app.services.logging_service import StructuredLogger


def test_loki_round1_claims_generation(
    mock_retrieval: MockRetrievalService, sample_case_file_round1: CaseFile
):
    """Requirement: Loki independently formulates evidence-backed low-exposure claims."""
    memory = LokiMemoryService()
    agent = LokiAgent(retrieval_service=mock_retrieval, memory_service=memory)

    result = agent.investigate_and_argue(sample_case_file_round1)

    assert result.status == "success"
    assert result.agent == "loki"
    assert len(result.claims) >= 2

    # Check Midgard Wheat claim
    midgard_claim = next((c for c in result.claims if any(e.country == "Midgard" and e.sector == "Wheat" for e in c.estimates)), None)
    assert midgard_claim is not None
    assert midgard_claim.stance == "limited_exposure"
    assert midgard_claim.is_unsupported is False
    assert len(midgard_claim.citations) > 0

    # Verify deterministic estimates
    est = midgard_claim.estimates[0]
    assert est.min_estimate == 35.0
    assert est.max_estimate == 45.0
    assert est.unit == "%"
    assert len(est.assumptions) > 0

    # Verify citations do not violate clock cutoff
    for cit in midgard_claim.citations:
        assert cit.publication_date <= sample_case_file_round1.as_of_date
        assert cit.doc_id in ["ORV-0027", "ORV-0018", "ORV-0050", "ORV-0006", "ORV-0009"]

    # Verify memory recorded examined sources
    examined = memory.get_all_examined_doc_ids(sample_case_file_round1.case_id)
    assert len(examined) > 0


def test_loki_round2_cross_examination_of_thor(
    mock_retrieval: MockRetrievalService, sample_case_file_round2: CaseFile
):
    """Requirement: Loki attacks at least one weak Thor claim in cross-examination."""
    memory = LokiMemoryService()
    agent = LokiAgent(retrieval_service=mock_retrieval, memory_service=memory)

    result = agent.investigate_and_argue(sample_case_file_round2)

    assert result.status == "success"
    assert len(result.attacks) >= 1

    # Attack on THOR-C02 (clock violation) or THOR-C01 (Tier 4 tabloid)
    challenge_types = [a.challenge_type for a in result.attacks]
    assert ("clock_violation" in challenge_types) or ("unreliable_source" in challenge_types)

    attack_targets = [a.target_claim_id for a in result.attacks]
    assert "THOR-C02" in attack_targets or "THOR-C01" in attack_targets


def test_loki_round2_justified_concessions(
    mock_retrieval: MockRetrievalService, sample_case_file_round2: CaseFile
):
    """Requirement: Loki makes justified concessions acknowledging established evidence."""
    memory = LokiMemoryService()
    agent = LokiAgent(retrieval_service=mock_retrieval, memory_service=memory)

    # First run round 1 so Loki has claims in memory
    sample_case_file_round2.round_number = 1
    r1_result = agent.investigate_and_argue(sample_case_file_round2)
    sample_case_file_round2.claims.extend(r1_result.claims)

    # Now run round 2 with Thor's attack
    sample_case_file_round2.round_number = 2
    r2_result = agent.investigate_and_argue(sample_case_file_round2)

    assert len(r2_result.concessions) >= 1
    rail_concession = next((c for c in r2_result.concessions if c.action == "concede"), None)
    assert rail_concession is not None
    assert "rail" in rail_concession.reason.lower()
    assert len(rail_concession.adjusted_estimates) > 0

    # Verify concession was recorded in Loki's private memory
    conceded_ids = memory.get_conceded_claim_ids(sample_case_file_round2.case_id)
    assert rail_concession.target_claim_id in conceded_ids


def test_loki_missing_evidence_unsupported_claim():
    """Requirement: Never fabricate citations; explicitly flag claims as unsupported when evidence is absent."""
    empty_retrieval = MockRetrievalService(documents=[])
    memory = LokiMemoryService()
    agent = LokiAgent(retrieval_service=empty_retrieval, memory_service=memory)

    case_file = CaseFile(
        case_id="CASE-EMPTY",
        question="What is the exposure?",
        as_of_date="2027-01-25",
        round_number=1,
    )
    result = agent.investigate_and_argue(case_file)

    assert result.status == "success"
    assert len(result.claims) == 1
    claim = result.claims[0]
    assert claim.is_unsupported is True
    assert len(claim.citations) == 0
    assert len(result.uncertainties) > 0


def test_loki_retrieval_failure_resilience():
    """Requirement: Return valid structured result without crashing on retrieval failure."""
    failing_retrieval = MockRetrievalService(documents=[], simulate_failure=True)
    memory = LokiMemoryService()
    agent = LokiAgent(retrieval_service=failing_retrieval, memory_service=memory)

    case_file = CaseFile(
        case_id="CASE-FAIL",
        question="What is the exposure?",
        as_of_date="2027-01-25",
        round_number=1,
    )
    result = agent.investigate_and_argue(case_file)

    # Agent returns structured result rather than crashing
    assert result.status in ["partial", "success", "error"]
    assert result.agent == "loki"
    assert result.case_id == "CASE-FAIL"
    assert any("error" in u.lower() or "retrieval failure" in u.lower() for u in result.uncertainties)


def test_loki_end_to_end_with_real_runemark():
    """Integration test: Loki executing against real Runemark dev_pack_E5 corpus."""
    pack_dir = Path("03_Ragnarok Trial of the Nine Realms/dev_pack_E5")
    if not pack_dir.exists():
        pack_dir = Path(__file__).resolve().parents[2] / "03_Ragnarok Trial of the Nine Realms" / "dev_pack_E5"
    if not pack_dir.exists():
        pytest.skip("Official dev pack not available")

    real_retrieval = RunemarkCorpusRetrievalService(pack_dir=str(pack_dir))
    memory = LokiMemoryService()
    logger = StructuredLogger(agent_name="loki")
    agent = LokiAgent(retrieval_service=real_retrieval, memory_service=memory, logger_service=logger)

    case_file = CaseFile(
        case_id="CASE-E5-REAL",
        question="As of 25 January 2027, how exposed are Midgard and Tolan to the end of the Orvan corridor agreement?",
        as_of_date="2027-01-25",
        round_number=1,
        run_number=1,
    )

    result = agent.investigate_and_argue(case_file)

    assert result.status == "success"
    assert len(result.claims) >= 2

    # Check that real citations point to real documents in the manifest
    for claim in result.claims:
        for cit in claim.citations:
            assert cit.doc_id in real_retrieval.index
            assert cit.publication_date <= "2027-01-25"

    # Verify structured logs captured searches and claims
    events = logger.get_events(case_id="CASE-E5-REAL")
    assert len(events) > 0
    event_types = [e["event_type"] for e in events]
    assert "search" in event_types
    assert "claim_submitted" in event_types


def test_loki_round2_integration_with_real_runemark():
    """Requirement 10: Run Loki Round 2 adversarial debate against real Runemark dev_pack_E5 corpus."""
    pack_dir = Path("03_Ragnarok Trial of the Nine Realms/dev_pack_E5")
    if not pack_dir.exists():
        pack_dir = Path(__file__).resolve().parents[2] / "03_Ragnarok Trial of the Nine Realms" / "dev_pack_E5"
    if not pack_dir.exists():
        pytest.skip("Official dev pack not available")

    real_retrieval = RunemarkCorpusRetrievalService(pack_dir=str(pack_dir))
    memory = LokiMemoryService()
    logger = StructuredLogger(agent_name="loki")
    agent = LokiAgent(retrieval_service=real_retrieval, memory_service=memory, logger_service=logger)

    case_file = CaseFile(
        case_id="CASE-E5-ROUND2-REAL",
        question="As of 25 January 2027, how exposed are Midgard and Tolan to the end of the Orvan corridor agreement?",
        as_of_date="2027-01-25",
        round_number=2,
        run_number=1,
    )
    # Add Loki's prior claim and Thor's counter-claim citing retracted tabloid ORV-0028
    case_file.claims.append(Claim(
        claim_id="LOKI-C01",
        agent="loki",
        stance="limited_exposure",
        claim_type="inference",
        statement="Midgard wheat exposure is bounded at 35%-45% by rail and Vanir.",
        reasoning="Alternative flows mitigate maritime shortfall.",
        confidence=0.85,
        estimates=[ExposureEstimate(country="Midgard", sector="Wheat", metric="net_value_loss_pct", min_estimate=35.0, max_estimate=45.0, unit="%")],
        citations=[EvidenceReference(doc_id="ORV-0027", paragraph="P6", quote_or_datapoint="Vanir wheat delivery USD 38.5M")]
    ))
    case_file.claims.append(Claim(
        claim_id="THOR-C01",
        agent="thor",
        stance="high_exposure",
        claim_type="inference",
        statement="Total collapse in trade.",
        reasoning="Panic in market.",
        confidence=0.9,
        estimates=[ExposureEstimate(country="Midgard", sector="Wheat", metric="net_value_loss_pct", min_estimate=80.0, max_estimate=90.0, unit="%")],
        citations=[EvidenceReference(doc_id="ORV-0028", paragraph="P1", reliability_tier=4, quote_or_datapoint="FAMINE FEAR")]
    ))
    case_file.attacks.append(CrossExamination(
        challenge_id="THOR-X01",
        challenger="thor",
        target_claim_id="LOKI-C01",
        challenge_type="unsupported_inference",
        objection="Ravik Rail Link has capacity limits and cannot fully replace sea freight.",
        reasoning="ORV-0001 shows rail is only a partial substitute.",
        counter_citations=[]
    ))

    result = agent.investigate_and_argue(case_file)

    assert result.status == "success"
    assert len(result.attacks) >= 1
    # Check that Loki attacks Thor's reliance on retracted tabloid ORV-0028
    tabloid_attack = next((a for a in result.attacks if a.target_claim_id == "THOR-C01"), None)
    assert tabloid_attack is not None

    # Check that Loki concedes partially to rail limits and adjusts exposure
    assert len(result.concessions) >= 1
    concession = result.concessions[0]
    assert concession.action == "concede"
    assert concession.adjusted_estimates[0].min_estimate == 35.0
    assert concession.adjusted_estimates[0].max_estimate == 45.0


def test_loki_never_cites_retracted_source_for_affirmative_claims(mock_retrieval: MockRetrievalService):
    """Requirement 6: Ensure retracted or contradicted sources (e.g. ORV-0043) are excluded from Loki claims."""
    # Inject retracted document into mock retrieval
    retracted_doc = Document(
        doc_id="ORV-0043",
        event_id="E5",
        title="Corridor renewed",
        source_name="Midgard Times",
        source_type="news",
        reliability_tier=2,
        pub_date="2026-09-09",
        country="Midgard",
        sector="Wheat",
        format="TXT",
        content="False corridor renewal announcement",
        paragraphs={"P1": "False renewal"}
    )
    mock_retrieval.add_document(retracted_doc)

    agent = LokiAgent(retrieval_service=mock_retrieval)
    # Extract citations explicitly requesting ORV-0043
    citations = agent._extract_citations_for_docs(
        docs=[retracted_doc],
        target_doc_ids=["ORV-0043"],
        as_of_date="2027-01-25"
    )
    # Must be filtered out
    assert len(citations) == 0
