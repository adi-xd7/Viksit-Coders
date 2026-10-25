"""Tests for Odin Final Judicial Adjudication Engine (Part 6A)."""

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
from backend.app.schemas.heimdall_result import HeimdallVerificationResult, PremiseVerification
from backend.app.schemas.odin_result import ClaimRuling, OdinResult
from backend.app.agents.odin import OdinAgent
from backend.app.agents.loki import LokiAgent
from backend.app.agents.thor import ThorAgent
from backend.app.services.retrieval import MockRetrievalService, RunemarkCorpusRetrievalService
from backend.app.services.debate_orchestrator import DebateOrchestrator
from backend.app.services.memory import LokiMemoryService
from backend.app.services.thor_memory import ThorMemoryService


@pytest.fixture
def odin_mock_documents() -> list[Document]:
    """Rich set of synthetic mock documents for Odin adjudication tests."""
    return [
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
                "P11": "Net value loss was 60.1% due to the corridor disruption.",
            }
        ),
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
            content="Notice from Realm Trade Ministry. The Corridor Agreement expired on 10 September 2026. Talks on renewal ended without agreement.",
            paragraphs={
                "P1": "Notice from the Realm Trade Ministry. The Corridor Agreement expired on 10 September 2026.",
                "P2": "Talks on renewal ended without agreement. No replacement arrangement has been signed."
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
            content="Vanir to Midgard wheat shipments surged in Nov-Dec 2026. November value was USD 38.5M and volume 96,000 tonnes.",
            paragraphs={"P6": "In November 2026, the value was USD 38.5M and volume 96,000 tonnes."}
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
            paragraphs={"P2": "The rail link can take only a fraction of the volume that normally leaves Orvan Grain Port by sea."}
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
        Document(
            doc_id="ORV-0043",
            event_id="E5",
            title="Orvan grain corridor renewed for a second year",
            source_name="Trade Whisper",
            source_type="press_report",
            reliability_tier=3,
            pub_date="2026-09-09",
            country="Orvan",
            sector="Wheat",
            format="TXT",
            content="Corridor renewed for a second year.",
            paragraphs={"P1": "Corridor renewed for a second year."}
        ),
        Document(
            doc_id="ORV-0014",
            event_id="E5",
            title="New corridor talks to open after Orvan request",
            source_name="Raven Wire",
            source_type="wire_service",
            reliability_tier=2,
            pub_date="2027-02-11",
            country="Realm",
            sector="Wheat",
            format="TXT",
            content="New talks scheduled for late February.",
            paragraphs={"P1": "New talks scheduled for late February."}
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
            doc_id="ORV-0026",
            event_id="E5",
            title="Sources: every grain ship sunk",
            source_name="Saga Chat",
            source_type="social_post",
            reliability_tier=4,
            pub_date="2026-09-18",
            country="Orvan",
            sector="Wheat",
            format="TXT",
            content="Every single grain ship sunk in harbor! Famine guaranteed!",
            paragraphs={"P1": "Every single grain ship sunk in harbor! Famine guaranteed!"}
        ),
    ]


@pytest.fixture
def sample_completed_debate_result() -> DebateResult:
    """Fixture providing a completed multi-agent debate deliverable."""
    case_file = CaseFile(
        case_id="CASE-E5-ODIN-TEST",
        question="As of 25 January 2027, how exposed are Midgard and Tolan to the end of the Orvan corridor agreement?",
        as_of_date="2027-01-25",
        is_verified=True,
        event_id="E5",
        round_number=2,
        run_number=1,
    )

    # 1. Uncontested, well-supported claim by Thor
    claim_thor_supported = Claim(
        claim_id="THOR-C01",
        agent="thor",
        stance="high_exposure",
        claim_type="sourced_fact",
        statement="Midgard direct wheat receipts collapsed by 60.1% year over year in 2026-Q4.",
        reasoning="Official Trade Ministry note ORV-0009 proves receipts fell from USD 260.4M to USD 103.9M.",
        confidence=0.92,
        estimates=[
            ExposureEstimate(
                country="Midgard",
                sector="Wheat",
                metric="net_value_loss_pct",
                min_estimate=55.0,
                max_estimate=65.0,
                unit="%",
                period="2026-Q4",
            )
        ],
        citations=[
            EvidenceReference(
                doc_id="ORV-0009",
                paragraph="P11",
                reliability_tier=1,
                source_name="Realm Trade Ministry",
                publication_date="2027-01-19",
                quote_or_datapoint="Net value loss was 60.1% due to the corridor disruption.",
            )
        ],
        is_unsupported=False,
    )

    # 2. Materially contested dispute on rail substitution
    claim_loki_rail = Claim(
        claim_id="LOKI-C03",
        agent="loki",
        stance="limited_exposure",
        claim_type="inference",
        statement="Ravik rail expansion substantially cushions the corridor disruption.",
        reasoning="Harbour Review ORV-0050 confirms rail traffic expanded by +54%.",
        confidence=0.82,
        estimates=[
            ExposureEstimate(
                country="Midgard",
                sector="Wheat",
                metric="net_value_loss_pct",
                min_estimate=30.0,
                max_estimate=45.0,
                unit="%",
                period="2026-Q4",
            )
        ],
        citations=[
            EvidenceReference(
                doc_id="ORV-0050",
                paragraph="P2",
                reliability_tier=2,
                source_name="Harbour Review",
                publication_date="2026-10-25",
                quote_or_datapoint="Rail freight expanded 54% over USD 25M base.",
            )
        ],
        is_unsupported=False,
    )

    # 3. Flawed claim by Thor that was formally conceded under Loki cross-examination
    claim_thor_exaggerated = Claim(
        claim_id="THOR-C02",
        agent="thor",
        stance="high_exposure",
        claim_type="inference",
        statement="Total commercial wheat loss across the region exceeds 85%.",
        reasoning="Aggregated port shutdown will paralyze all regional grain transit.",
        confidence=0.85,
        estimates=[
            ExposureEstimate(
                country="Midgard",
                sector="Wheat",
                metric="net_value_loss_pct",
                min_estimate=80.0,
                max_estimate=90.0,
                unit="%",
                period="2026-Q4",
            )
        ],
        citations=[
            EvidenceReference(
                doc_id="ORV-0026",
                paragraph="P1",
                reliability_tier=4,
                source_name="Saga Chat",
                publication_date="2026-09-18",
                quote_or_datapoint="Every single grain ship sunk in harbor! Famine guaranteed!",
            )
        ],
        is_unsupported=False,
    )

    case_file.claims = [claim_thor_supported, claim_loki_rail, claim_thor_exaggerated]

    # Attacks: Thor attacks Loki's rail claim with counter-evidence
    attack_on_rail = CrossExamination(
        challenge_id="THOR-X01",
        challenger="thor",
        target_claim_id="LOKI-C03",
        challenge_type="contradiction",
        objection="Vantro Trading statement proves rail can absorb only a fraction of normal port sea volume.",
        reasoning="ORV-0001 documents physical throughput bottlenecks preventing rail from replacing lost maritime volume.",
        counter_citations=[
            EvidenceReference(
                doc_id="ORV-0001",
                paragraph="P2",
                reliability_tier=2,
                source_name="Vantro Trading",
                publication_date="2026-10-20",
                quote_or_datapoint="The rail link can take only a fraction of the volume that normally leaves Orvan Grain Port by sea.",
            )
        ],
    )

    # Attack on Thor's exaggerated claim by Loki
    attack_on_exaggerated = CrossExamination(
        challenge_id="LOKI-X01",
        challenger="loki",
        target_claim_id="THOR-C02",
        challenge_type="unreliable_source",
        objection="Claim relies on uncorroborated Tier 4 rumor blog ORV-0026.",
        reasoning="ORV-0026 is an unverified blog post unsupported by official trade ministry bulletins.",
        counter_citations=[
            EvidenceReference(
                doc_id="ORV-0016",
                paragraph="P1",
                reliability_tier=1,
                source_name="Realm Trade Ministry",
                publication_date="2026-09-10",
                quote_or_datapoint="Notice from the Realm Trade Ministry. The Corridor Agreement expired on 10 September 2026.",
            )
        ],
    )

    case_file.attacks = [attack_on_rail, attack_on_exaggerated]

    # Concessions: Thor concedes on THOR-C02
    thor_concession = Concession(
        concession_id="THOR-CON01",
        agent="thor",
        target_challenge_id="LOKI-X01",
        target_claim_id="THOR-C02",
        action="concede",
        reason="Conceded: ORV-0026 is a low-credibility Tier 4 source. Withdrawing the 85% regional loss assertion.",
        adjusted_estimates=[],
        defence_citations=[],
    )

    case_file.concessions = [thor_concession]

    heimdall_ver = HeimdallVerificationResult(
        case_id=case_file.case_id,
        as_of_date=case_file.as_of_date,
        event_id=case_file.event_id,
        is_event_real=True,
        verification_status="verified",
        summary="Heimdall Gate: Disruption verified.",
    )

    return DebateResult(
        case_id=case_file.case_id,
        as_of_date=case_file.as_of_date,
        run_number=1,
        status="success",
        heimdall_verification=heimdall_ver,
        case_file=case_file,
        stages_executed=[
            "validation",
            "heimdall_verification",
            "loki_round1",
            "thor_round1",
            "loki_round2",
            "thor_round2",
        ],
    )


# -----------------------------------------------------------------------------
# Test 1: Supported Claim Correctly Classified as Established
# -----------------------------------------------------------------------------

def test_odin_adjudicates_supported_claim_as_established(
    sample_completed_debate_result: DebateResult,
):
    """Requirement: A claim supported by admissible Tier 1 evidence is classified as established."""
    odin = OdinAgent()
    result = odin.adjudicate_debate(sample_completed_debate_result)

    assert result.adjudication_status == "completed"
    assert "THOR-C01" in result.established_claims

    ruling = next(r for r in result.claim_rulings if r.claim_id == "THOR-C01")
    assert ruling.ruling == "established"
    assert ruling.confidence >= 0.88
    assert ruling.claim_type == "sourced_fact"
    assert any(c.doc_id == "ORV-0009" for c in ruling.supporting_citations)
    assert "Tier 1" in ruling.reasoning


# -----------------------------------------------------------------------------
# Test 2: Materially Disputed Claim Remains Contested
# -----------------------------------------------------------------------------

def test_odin_adjudicates_materially_disputed_claim_as_contested(
    sample_completed_debate_result: DebateResult,
):
    """Requirement: A materially disputed claim with balanced evidence remains contested."""
    odin = OdinAgent()
    result = odin.adjudicate_debate(sample_completed_debate_result)

    assert "LOKI-C03" in result.contested_claims

    ruling = next(r for r in result.claim_rulings if r.claim_id == "LOKI-C03")
    assert ruling.ruling == "contested"
    assert ruling.confidence <= 0.65
    assert len(ruling.supporting_citations) >= 1
    assert len(ruling.contradicting_citations) >= 1
    # Both sides' citations preserved
    assert any(c.doc_id == "ORV-0050" for c in ruling.supporting_citations)
    assert any(c.doc_id == "ORV-0001" for c in ruling.contradicting_citations)
    assert len(result.unresolved_disputes) >= 1


# -----------------------------------------------------------------------------
# Test 3: Explicit Concessions Preserved and Correctly Attributed
# -----------------------------------------------------------------------------

def test_odin_preserves_explicit_concessions_with_attribution(
    sample_completed_debate_result: DebateResult,
):
    """Requirement: Explicit concessions are classified as conceded and attributed to the agent."""
    odin = OdinAgent()
    result = odin.adjudicate_debate(sample_completed_debate_result)

    assert "THOR-C02" in result.conceded_claims

    ruling = next(r for r in result.claim_rulings if r.claim_id == "THOR-C02")
    assert ruling.ruling == "conceded"
    assert ruling.is_conceded is True
    assert ruling.conceded_by == "thor"
    assert "Withdrawing the 85% regional loss assertion" in ruling.reasoning


# -----------------------------------------------------------------------------
# Test 4: Concession Does Not Automatically Establish Opposing Claim
# -----------------------------------------------------------------------------

def test_concession_does_not_automatically_establish_opposing_claim(
    sample_completed_debate_result: DebateResult,
):
    """Requirement: A concession records withdrawal, but does not prove the opponent's counter-claim."""
    odin = OdinAgent()
    result = odin.adjudicate_debate(sample_completed_debate_result)

    ruling = next(r for r in result.claim_rulings if r.claim_id == "THOR-C02")
    assert "does not automatically establish" in ruling.reasoning.lower()


# -----------------------------------------------------------------------------
# Test 5: Unsupported Claims Are Not Incorrectly Marked Established
# -----------------------------------------------------------------------------

def test_unsupported_claim_not_marked_established(
    sample_completed_debate_result: DebateResult,
):
    """Requirement: Claims lacking admissible evidence cannot be classified as established."""
    unsupported_claim = Claim(
        claim_id="LOKI-UNSUPPORTED",
        agent="loki",
        stance="limited_exposure",
        claim_type="inference",
        statement="Secret emergency grain reserves will replace 100% of the loss.",
        reasoning="Rumors suggest hidden reserves exist.",
        confidence=0.30,
        citations=[],
        is_unsupported=True,
    )
    sample_completed_debate_result.case_file.claims.append(unsupported_claim)

    odin = OdinAgent()
    result = odin.adjudicate_debate(sample_completed_debate_result)

    assert "LOKI-UNSUPPORTED" not in result.established_claims
    assert "LOKI-UNSUPPORTED" in result.contested_claims

    ruling = next(r for r in result.claim_rulings if r.claim_id == "LOKI-UNSUPPORTED")
    assert ruling.ruling == "contested"
    assert ruling.confidence <= 0.35
    assert "lacks admissible evidentiary foundation" in ruling.reasoning


# -----------------------------------------------------------------------------
# Test 6: Retracted and Inadmissible Evidence Cannot Support Established Ruling
# -----------------------------------------------------------------------------

def test_retracted_and_inadmissible_evidence_rejected(
    sample_completed_debate_result: DebateResult,
):
    """Requirement: Retracted decoys like ORV-0043 cannot substantiate an established ruling."""
    decoy_claim = Claim(
        claim_id="THOR-DECOY",
        agent="thor",
        stance="high_exposure",
        claim_type="sourced_fact",
        statement="The corridor agreement was renewed for a second year.",
        reasoning="Report in ORV-0043 claims renewal.",
        confidence=0.80,
        citations=[
            EvidenceReference(
                doc_id="ORV-0043",
                paragraph="P1",
                reliability_tier=3,
                source_name="Trade Whisper",
                publication_date="2026-09-09",
                quote_or_datapoint="Corridor renewed for a second year.",
            )
        ],
        is_unsupported=False,
    )
    sample_completed_debate_result.case_file.claims.append(decoy_claim)

    odin = OdinAgent()
    result = odin.adjudicate_debate(sample_completed_debate_result)

    assert "THOR-DECOY" not in result.established_claims
    ruling = next(r for r in result.claim_rulings if r.claim_id == "THOR-DECOY")
    assert ruling.ruling == "contested"
    assert ruling.discrepancy_notes is not None
    assert "Retracted/discredited decoy: ORV-0043" in ruling.discrepancy_notes


# -----------------------------------------------------------------------------
# Test 7: As-of-Date Clock Cutoff Enforced
# -----------------------------------------------------------------------------

def test_as_of_date_filtering_enforced(
    sample_completed_debate_result: DebateResult,
):
    """Requirement: Citations published after as_of_date are clock violations and inadmissible."""
    future_claim = Claim(
        claim_id="LOKI-FUTURE",
        agent="loki",
        stance="limited_exposure",
        claim_type="sourced_fact",
        statement="Talks on reopening will resolve the disruption in late February.",
        reasoning="Wire report in ORV-0014.",
        confidence=0.85,
        citations=[
            EvidenceReference(
                doc_id="ORV-0014",
                paragraph="P1",
                reliability_tier=2,
                source_name="Raven Wire",
                publication_date="2027-02-11",
                quote_or_datapoint="New talks scheduled for late February.",
            )
        ],
        is_unsupported=False,
    )
    sample_completed_debate_result.case_file.claims.append(future_claim)

    odin = OdinAgent()
    result = odin.adjudicate_debate(sample_completed_debate_result)

    assert "LOKI-FUTURE" not in result.established_claims
    ruling = next(r for r in result.claim_rulings if r.claim_id == "LOKI-FUTURE")
    assert ruling.ruling == "contested"
    assert ruling.discrepancy_notes is not None
    assert "Clock cutoff violation" in ruling.discrepancy_notes


# -----------------------------------------------------------------------------
# Test 8: Supporting and Contradicting Citations Retain Full Provenance
# -----------------------------------------------------------------------------

def test_provenance_preservation_in_rulings(
    sample_completed_debate_result: DebateResult,
):
    """Requirement: Document IDs, paragraphs, tiers, dates, and quotes retain full provenance."""
    odin = OdinAgent()
    result = odin.adjudicate_debate(sample_completed_debate_result)

    ruling = next(r for r in result.claim_rulings if r.claim_id == "THOR-C01")
    assert len(ruling.supporting_citations) == 1
    cit = ruling.supporting_citations[0]
    assert cit.doc_id == "ORV-0009"
    assert cit.paragraph == "P11"
    assert cit.reliability_tier == 1
    assert cit.publication_date == "2027-01-19"
    assert "60.1%" in cit.quote_or_datapoint


# -----------------------------------------------------------------------------
# Test 9: Contradictory Evidence Preserved in Final Ruling
# -----------------------------------------------------------------------------

def test_contradictory_evidence_preserved_in_final_ruling(
    sample_completed_debate_result: DebateResult,
):
    """Requirement: Contradictory evidence is retained side-by-side in rulings."""
    odin = OdinAgent()
    result = odin.adjudicate_debate(sample_completed_debate_result)

    ruling = next(r for r in result.claim_rulings if r.claim_id == "LOKI-C03")
    assert len(ruling.supporting_citations) >= 1
    assert len(ruling.contradicting_citations) >= 1
    # Both supporting ORV-0050 and counter ORV-0001 are present
    assert any(c.doc_id == "ORV-0050" for c in ruling.supporting_citations)
    assert any(c.doc_id == "ORV-0001" for c in ruling.contradicting_citations)


# -----------------------------------------------------------------------------
# Test 10: Missing or Malformed Inputs Handled Explicitly
# -----------------------------------------------------------------------------

def test_missing_or_malformed_inputs_handled_explicitly():
    """Requirement: Explicit handling of None or failed debate inputs."""
    odin = OdinAgent()

    # 1. None debate result raises ValueError
    with pytest.raises(ValueError, match="DebateResult cannot be None"):
        odin.adjudicate_debate(None)  # type: ignore

    # 2. Failed debate status halts adjudication
    failed_debate = DebateResult(
        case_id="CASE-FAILED",
        as_of_date="2027-01-25",
        status="error",
        failed_stage="heimdall_verification",
        error_message="Core event contradicted.",
        case_file=CaseFile(case_id="CASE-FAILED", question="Q", as_of_date="2027-01-25"),
    )
    res = odin.adjudicate_debate(failed_debate)
    assert res.adjudication_status == "error"
    assert res.error_message is not None and "Debate terminated with error" in res.error_message


# -----------------------------------------------------------------------------
# Test 11: Odin Invoked Only After Required Debate Stages Complete
# -----------------------------------------------------------------------------

def test_odin_invoked_only_after_required_stages(
    odin_mock_documents: list[Document],
    tmp_path: Path,
):
    """Requirement: Odin runs as stage 6, after all debate rounds and concessions complete."""
    retrieval = MockRetrievalService(documents=odin_mock_documents)
    orchestrator = DebateOrchestrator(
        retrieval_service=retrieval,
        loki_memory=LokiMemoryService(storage_path=str(tmp_path / "lm.json")),
        thor_memory=ThorMemoryService(storage_path=str(tmp_path / "tm.json")),
    )

    case_file = CaseFile(
        case_id="CASE-CALL-ORDER-TEST",
        question="As of 25 January 2027, how exposed are Midgard and Tolan to the end of the Orvan corridor agreement?",
        as_of_date="2027-01-25",
        is_verified=True,
        event_id="E5",
    )

    result = orchestrator.run_debate(case_file)

    assert result.status == "success"
    # Stage order must be strictly maintained
    expected = [
        "validation",
        "heimdall_verification",
        "loki_round1",
        "thor_round1",
        "loki_round2",
        "thor_round2",
        "odin_adjudication",
    ]
    assert result.stages_executed == expected


# -----------------------------------------------------------------------------
# Test 12: Odin Result Preserved in Final DebateResult and CaseFile
# -----------------------------------------------------------------------------

def test_odin_result_preserved_in_debate_result_and_case_file(
    odin_mock_documents: list[Document],
    tmp_path: Path,
):
    """Requirement: Odin's result is saved in DebateResult.odin_adjudication and CaseFile.judicial_rulings."""
    retrieval = MockRetrievalService(documents=odin_mock_documents)
    orchestrator = DebateOrchestrator(
        retrieval_service=retrieval,
        loki_memory=LokiMemoryService(storage_path=str(tmp_path / "lm.json")),
        thor_memory=ThorMemoryService(storage_path=str(tmp_path / "tm.json")),
    )

    case_file = CaseFile(
        case_id="CASE-DELIVERABLE-PRESERVATION",
        question="As of 25 January 2027, how exposed are Midgard and Tolan to the end of the Orvan corridor agreement?",
        as_of_date="2027-01-25",
        is_verified=True,
        event_id="E5",
    )

    result = orchestrator.run_debate(case_file)

    assert result.odin_adjudication is not None
    assert isinstance(result.odin_adjudication, OdinResult)
    assert result.odin_adjudication.adjudication_status == "completed"
    assert len(result.odin_adjudication.claim_rulings) >= 1
    # Check CaseFile.judicial_rulings is also populated
    assert len(result.case_file.judicial_rulings) == len(result.odin_adjudication.claim_rulings)


# -----------------------------------------------------------------------------
# Test 13: Odin Failure Preserves Completed Prior Results
# -----------------------------------------------------------------------------

def test_odin_failure_preserves_completed_prior_results(
    odin_mock_documents: list[Document],
    tmp_path: Path,
):
    """Requirement: If Odin fails, record failure stage without losing prior debate deliverables."""
    retrieval = MockRetrievalService(documents=odin_mock_documents)
    failing_odin = MagicMock(spec=OdinAgent)
    failing_odin.adjudicate_debate.side_effect = RuntimeError("Simulated Odin database timeout.")

    orchestrator = DebateOrchestrator(
        retrieval_service=retrieval,
        odin_agent=failing_odin,
        loki_memory=LokiMemoryService(storage_path=str(tmp_path / "lm.json")),
        thor_memory=ThorMemoryService(storage_path=str(tmp_path / "tm.json")),
    )

    case_file = CaseFile(
        case_id="CASE-ODIN-FAIL-TEST",
        question="As of 25 January 2027, how exposed are Midgard and Tolan to the end of the Orvan corridor agreement?",
        as_of_date="2027-01-25",
        is_verified=True,
        event_id="E5",
    )

    result = orchestrator.run_debate(case_file)

    assert result.status == "partial"
    assert result.failed_stage == "odin_adjudication"
    assert result.error_message is not None
    assert "Simulated Odin database timeout" in result.error_message
    # Prior deliverables are preserved!
    assert result.heimdall_verification is not None
    assert result.loki_round1 is not None
    assert result.thor_round1 is not None
    assert result.loki_round2 is not None
    assert result.thor_round2 is not None
    assert len(result.case_file.claims) >= 1


# -----------------------------------------------------------------------------
# Test 14: No Fabricated Evidence or Citations Produced
# -----------------------------------------------------------------------------

def test_no_fabricated_evidence_or_citations(
    sample_completed_debate_result: DebateResult,
):
    """Requirement: Odin must strictly preserve and cite existing document IDs without fabrication."""
    odin = OdinAgent()
    result = odin.adjudicate_debate(sample_completed_debate_result)

    # Valid corpus doc IDs in this test
    valid_doc_ids = {"ORV-0009", "ORV-0016", "ORV-0050", "ORV-0001", "ORV-0026"}
    for ruling in result.claim_rulings:
        for cit in ruling.supporting_citations:
            assert cit.doc_id in valid_doc_ids
        for cit in ruling.contradicting_citations:
            assert cit.doc_id in valid_doc_ids


# -----------------------------------------------------------------------------
# Test 15: Real Official Runemark Corpus E5 Integration
# -----------------------------------------------------------------------------

def test_official_corpus_e5_odin_integration():
    """Requirement: Integration test with real official dev_pack_E5 corpus."""
    pack_dir = Path("03_Ragnarok Trial of the Nine Realms/dev_pack_E5")
    if not pack_dir.exists():
        pytest.skip("dev_pack_E5 corpus directory not available in environment.")

    real_retrieval = RunemarkCorpusRetrievalService(pack_dir=str(pack_dir))
    orchestrator = DebateOrchestrator(retrieval_service=real_retrieval)

    case_file = CaseFile(
        case_id="CASE-E5-REAL-ODIN-INTEGRATION",
        question="As of 25 January 2027, how exposed are Midgard and Tolan to the end of the Orvan corridor agreement?",
        as_of_date="2027-01-25",
        is_verified=True,
        event_id="E5",
    )

    result = orchestrator.run_debate(case_file)

    assert result.status == "success"
    assert result.odin_adjudication is not None
    assert result.odin_adjudication.adjudication_status == "completed"
    assert len(result.odin_adjudication.claim_rulings) >= 2
    assert len(result.odin_adjudication.established_claims) >= 1
    # Check that summary is generated
    assert "=== ODIN FINAL JUDICIAL RULING ===" in result.odin_adjudication.summary
