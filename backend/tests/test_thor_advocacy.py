"""Tests for Thor Round 1 Evidence-Based Advocacy Core (Part 3B)."""

import pytest
from pathlib import Path

from backend.app.schemas.evidence import Document, EvidenceReference
from backend.app.schemas.claim import Claim, ExposureEstimate
from backend.app.schemas.case_file import CaseFile
from backend.app.schemas.thor_result import ThorResult
from backend.app.services.retrieval import MockRetrievalService, RunemarkCorpusRetrievalService
from backend.app.services.thor_memory import ThorMemoryService
from backend.app.services.citations import CitationValidator
from backend.app.agents.thor import ThorAgent
from backend.app.agents.thor_retrieval import ThorEvidenceRetriever


@pytest.fixture
def thor_advocacy_mock_documents(mock_documents: list[Document]) -> list[Document]:
    """Extend base mock documents with complete high-exposure disruption items for Thor advocacy."""
    docs = list(mock_documents)

    # 1. ORV-0001 (Rail bottleneck statement)
    docs.append(
        Document(
            doc_id="ORV-0001",
            event_id="E5",
            title="MOCK: Vantro Trading rail statement",
            source_name="Vantro Trading",
            source_type="company_statement",
            reliability_tier=2,
            pub_date="2026-10-20",
            pub_time="09:50",
            country="Ravik",
            sector="Wheat",
            format="DOCX",
            content="Vantro Trading: rail is a partial substitute, not a replacement. The rail link can take only a fraction of the volume that normally leaves Orvan Grain Port by sea.",
            paragraphs={
                "P1": "Vantro Trading has shifted part of its Orvan wheat business to the Ravik Rail Link while sea loadings remain disrupted.",
                "P2": "The company says the rail link can take only a fraction of the volume that normally leaves Orvan Grain Port by sea.",
                "P3": "Rail is a useful bridge for contracted cargoes, but it will not cover the lost sea volumes.",
            }
        )
    )

    # 2. ORV-0007 (Sea loss is real)
    docs.append(
        Document(
            doc_id="ORV-0007",
            event_id="E5",
            title="MOCK: Sea loss is real",
            source_name="Asgard Herald",
            source_type="analyst_note",
            reliability_tier=3,
            pub_date="2026-10-22",
            pub_time="08:20",
            country="Orvan",
            sector="Wheat",
            format="TXT",
            content="Orvan wheat: the sea loss is real, the substitutes are small. The corridor agreement ended on 10 September and port strike began on 14 September. Port index collapsed.",
            paragraphs={
                "P1": "We think the market is still underestimating the duration of the Orvan sea disruption.",
                "P2": "The corridor agreement ended on 10 September and the port strike began on 14 September. Port index collapsed to 40.",
                "P3": "On our numbers, the four main sea routes could lose half to three-fifths of their value in the fourth quarter.",
            }
        )
    )

    # 3. ORV-0009 (Orvan to Midgard wheat trade note)
    docs.append(
        Document(
            doc_id="ORV-0009",
            event_id="E5",
            title="MOCK: Trade note: Orvan to Midgard, wheat",
            source_name="Realm Trade Ministry",
            source_type="trade_note",
            reliability_tier=1,
            pub_date="2027-01-19",
            pub_time="10:00",
            country="Midgard",
            sector="Wheat",
            format="TXT",
            content="Orvan to Midgard wheat trade receipts dropped sharply. July USD 90.0M, August USD 96.1M, October USD 34.5M, November USD 35.3M, December USD 34.1M.",
            paragraphs={
                "P5": "In October 2026, the value was USD 34.5M and the volume was 84,000 tonnes.",
                "P6": "In November 2026, the value was USD 35.3M and the volume was 86,000 tonnes.",
                "P7": "In December 2026, the value was USD 34.1M and the volume was 83,000 tonnes.",
                "P11": "In October 2025, the value was USD 86.8M and the volume was 241,000 tonnes.",
                "P12": "In November 2025, the value was USD 88.6M and the volume was 246,000 tonnes.",
                "P13": "In December 2025, the value was USD 85.0M and the volume was 236,000 tonnes.",
                "P14": "December was the weakest month of the half-year.",
            }
        )
    )

    # 4. ORV-0046 (Orvan to Tolan wheat trade note)
    docs.append(
        Document(
            doc_id="ORV-0046",
            event_id="E5",
            title="MOCK: Trade note: Orvan to Tolan, wheat",
            source_name="Cargo Weekly",
            source_type="trade_note",
            reliability_tier=2,
            pub_date="2027-01-20",
            pub_time="11:15",
            country="Tolan",
            sector="Wheat",
            format="TXT",
            content="Orvan to Tolan wheat trade receipts fell by 60%. October USD 15.4M, November USD 15.8M, December USD 15.0M. Tolan buyers replaced part of lost volume with Vanir wheat but replacement was smaller than the gap.",
            paragraphs={
                "P5": "In October 2026, the value was USD 15.4M and the volume was 39,000 tonnes.",
                "P6": "In November 2026, the value was USD 15.8M and the volume was 40,000 tonnes.",
                "P7": "In December 2026, the value was USD 15.0M and the volume was 38,000 tonnes.",
                "P11": "In October 2025, the value was USD 38.5M and the volume was 110,000 tonnes.",
                "P12": "In November 2025, the value was USD 39.5M and the volume was 113,000 tonnes.",
                "P13": "In December 2025, the value was USD 37.8M and the volume was 108,000 tonnes.",
                "P14": "Tolan buyers replaced part of the lost volume with wheat from Vanir, but the replacement was smaller than the gap.",
            }
        )
    )

    # 5. ORV-0016 (Corridor expires without renewal)
    docs.append(
        Document(
            doc_id="ORV-0016",
            event_id="E5",
            title="MOCK: Corridor Agreement expires with no renewal",
            source_name="Realm Trade Ministry",
            source_type="gov_notice",
            reliability_tier=1,
            pub_date="2026-09-10",
            pub_time="17:45",
            country="Orvan",
            sector="Wheat",
            format="TXT",
            content="Notice from Realm Trade Ministry. The Corridor Agreement expired on 10 September 2026. Talks on renewal ended without agreement.",
            paragraphs={
                "P1": "Notice from the Realm Trade Ministry. The Corridor Agreement expired on 10 September 2026.",
                "P2": "Talks on renewal ended without agreement. No replacement arrangement has been signed.",
            }
        )
    )

    # 6. ORV-0021 (Corvan Grain October sea shipments down 62%)
    docs.append(
        Document(
            doc_id="ORV-0021",
            event_id="E5",
            title="MOCK: Corvan Grain October sea shipments down 62%",
            source_name="Cargo Weekly",
            source_type="trade_press",
            reliability_tier=2,
            pub_date="2026-11-12",
            pub_time="10:30",
            country="Orvan",
            sector="Wheat",
            format="TXT",
            content="Corvan Grain reports October sea shipments down 62% on last year. Rail capacity cannot replace the sea route.",
            paragraphs={
                "P1": "Corvan Grain reports that its sea shipments of wheat and maize in October 2026 were 62% below the same month a year earlier.",
                "P2": "The fall follows the end of the Corridor Agreement on 10 September and the strike at Orvan Grain Port.",
                "P3": "Rail capacity is limited and cannot replace the sea route.",
            }
        )
    )

    return docs


@pytest.fixture
def thor_mock_retrieval_service(thor_advocacy_mock_documents: list[Document]) -> MockRetrievalService:
    return MockRetrievalService(documents=thor_advocacy_mock_documents)


@pytest.fixture
def thor_agent(thor_mock_retrieval_service: MockRetrievalService, tmp_path: Path) -> ThorAgent:
    mem = ThorMemoryService(storage_path=str(tmp_path / "thor_advocacy_mem.json"))
    return ThorAgent(retrieval_service=thor_mock_retrieval_service, memory_service=mem)


# =============================================================================
# Unit Tests
# =============================================================================

def test_thor_round1_claims_generation_schema_valid(thor_agent: ThorAgent, sample_case_file_round1: CaseFile):
    """Requirement: Formulate valid, document-grounded ThorResult with Round 1 high-exposure claims."""
    result = thor_agent.investigate_and_argue(sample_case_file_round1)

    assert isinstance(result, ThorResult)
    assert result.agent == "thor"
    assert result.case_id == sample_case_file_round1.case_id
    assert result.round_number == 1
    assert result.run_number == 1
    assert result.status == "success"
    assert len(result.claims) >= 3

    # All claims must belong to thor and have high_exposure stance
    for claim in result.claims:
        assert claim.agent == "thor"
        assert claim.stance == "high_exposure"
        assert claim.claim_id.startswith("THOR-C")
        assert len(claim.statement) > 10
        assert len(claim.reasoning) > 20
        assert 0.0 <= claim.confidence <= 1.0


def test_claims_traceable_to_evidence_provenance(thor_agent: ThorAgent, sample_case_file_round1: CaseFile):
    """Requirement: Every grounded claim must trace to valid EvidenceReference objects preserving provenance."""
    result = thor_agent.investigate_and_argue(sample_case_file_round1)

    grounded_claims = [c for c in result.claims if not c.is_unsupported]
    assert len(grounded_claims) >= 3

    for claim in grounded_claims:
        assert len(claim.citations) > 0, f"Claim {claim.claim_id} lacks citations"
        for cit in claim.citations:
            assert CitationValidator.validate_doc_id_format(cit.doc_id)
            assert cit.reliability_tier is not None
            assert 1 <= cit.reliability_tier <= 4
            assert cit.source_name is not None
            assert cit.publication_date is not None
            assert len(cit.quote_or_datapoint.strip()) > 0
            # Timestamp preserved where available
            if cit.doc_id == "ORV-0001":
                assert cit.pub_time == "09:50"


def test_as_of_date_enforcement(thor_agent: ThorAgent, sample_case_file_round1: CaseFile):
    """Requirement: Strictly enforce simulated clock cutoff; no post-dated evidence in Round 1 claims."""
    result = thor_agent.investigate_and_argue(sample_case_file_round1)
    as_of = sample_case_file_round1.as_of_date

    for claim in result.claims:
        for cit in claim.citations:
            assert cit.publication_date is not None and not CitationValidator.is_clock_violation(cit.publication_date, as_of), (
                f"Clock violation detected in {cit.doc_id} ({cit.publication_date} > {as_of})"
            )
            assert cit.doc_id != "ORV-0014", "Post-dated doc ORV-0014 must never be cited"


def test_conflicting_evidence_acknowledged_and_retained(thor_agent: ThorAgent, sample_case_file_round1: CaseFile):
    """Requirement: Material conflicting evidence (Vanir substitution, buffers) must be preserved and addressed."""
    result = thor_agent.investigate_and_argue(sample_case_file_round1)

    # Check that Midgard Wheat claim addresses Vanir replacement
    c2 = next((c for c in result.claims if c.claim_id == "THOR-C02"), None)
    assert c2 is not None
    assert "vanir" in c2.reasoning.lower() or "substitution" in c2.reasoning.lower()
    # Check that Tolan Wheat claim addresses Vanir gap
    c3 = next((c for c in result.claims if c.claim_id == "THOR-C03"), None)
    assert c3 is not None
    assert "smaller than the gap" in c3.reasoning.lower() or "replaced part" in c3.reasoning.lower()


def test_no_invented_numerical_estimate_when_evidence_is_insufficient(
    thor_agent: ThorAgent, sample_case_file_round1: CaseFile
):
    """Requirement: Do not invent numbers; Tolan maize lacks trade notes and must be explicitly unsupported."""
    result = thor_agent.investigate_and_argue(sample_case_file_round1)

    tolan_maize_claim = next((c for c in result.claims if c.claim_id == "THOR-C05"), None)
    assert tolan_maize_claim is not None
    assert tolan_maize_claim.is_unsupported is True
    assert len(tolan_maize_claim.estimates) == 0
    assert len(tolan_maize_claim.citations) == 0
    assert any("Tolan maize" in u and "insufficient" in u for u in result.uncertainties)


def test_empty_retrieval_handling(tmp_path: Path, sample_case_file_round1: CaseFile):
    """Requirement: Handle zero retrieval results gracefully without fabricating claims."""
    empty_retrieval = MockRetrievalService(documents=[])
    mem = ThorMemoryService(storage_path=str(tmp_path / "empty_thor_mem.json"))
    agent = ThorAgent(retrieval_service=empty_retrieval, memory_service=mem)

    result = agent.investigate_and_argue(sample_case_file_round1)

    assert result.status in ["partial", "error"]
    assert len(result.claims) > 0
    assert all(c.is_unsupported for c in result.claims)
    assert any("Total retrieval failure" in u for u in result.uncertainties)


def test_retrieval_failure_handling(thor_mock_retrieval_service: MockRetrievalService, tmp_path: Path, sample_case_file_round1: CaseFile):
    """Requirement: Handle retrieval backend errors without crashing."""
    thor_mock_retrieval_service.simulate_failure = True
    mem = ThorMemoryService(storage_path=str(tmp_path / "fail_thor_mem.json"))
    agent = ThorAgent(retrieval_service=thor_mock_retrieval_service, memory_service=mem)

    result = agent.investigate_and_argue(sample_case_file_round1)

    assert result.status in ["partial", "error"]
    assert any("Retrieval error" in u for u in result.uncertainties)


def test_invalid_retracted_evidence_not_used(thor_agent: ThorAgent, sample_case_file_round1: CaseFile):
    """Requirement: Retracted/contradicted sources (e.g. ORV-0043) must never be cited in affirmative claims."""
    result = thor_agent.investigate_and_argue(sample_case_file_round1)

    all_citations = [cit for claim in result.claims for cit in claim.citations]
    cited_ids = [c.doc_id for c in all_citations]
    assert "ORV-0043" not in cited_ids


def test_determinism_and_case_memory_isolation(thor_agent: ThorAgent, sample_case_file_round1: CaseFile):
    """Requirement: Thor produces deterministic results and enforces case-specific memory isolation."""
    result1 = thor_agent.investigate_and_argue(sample_case_file_round1)
    result2 = thor_agent.investigate_and_argue(sample_case_file_round1)

    # Deterministic output check
    assert len(result1.claims) == len(result2.claims)
    for c1, c2 in zip(result1.claims, result2.claims):
        assert c1.claim_id == c2.claim_id
        assert c1.statement == c2.statement
        assert c1.confidence == c2.confidence

    # Memory case isolation check
    case_a = "CASE-ISOLATION-A"
    case_b = "CASE-ISOLATION-B"
    thor_agent.memory.record_lesson(case_a, "lesson_a", "Lesson A", 0.9, ["ORV-0001"])
    thor_agent.memory.record_lesson(case_b, "lesson_b", "Lesson B", 0.8, ["ORV-0009"])

    lessons_a = thor_agent.memory.get_lessons(case_a)
    lessons_b = thor_agent.memory.get_lessons(case_b)
    assert "lesson_a" in lessons_a
    assert "lesson_a" not in lessons_b
    assert "lesson_b" in lessons_b
    assert "lesson_b" not in lessons_a


# =============================================================================
# Integration Test with Official Runemark dev_pack_E5
# =============================================================================

def test_official_runemark_corpus_thor_advocacy_integration(sample_case_file_round1: CaseFile, tmp_path: Path):
    """Integration test: Verify ThorAgent Round 1 against official dev_pack_E5 corpus."""
    pack_dir = Path("03_Ragnarok Trial of the Nine Realms/dev_pack_E5")
    if not pack_dir.exists():
        pack_dir = Path(__file__).resolve().parents[2] / "03_Ragnarok Trial of the Nine Realms" / "dev_pack_E5"
    if not pack_dir.exists():
        pytest.skip("Official dev_pack_E5 not found")

    corpus = RunemarkCorpusRetrievalService(pack_dir=str(pack_dir))
    mem = ThorMemoryService(storage_path=str(tmp_path / "thor_real_advocacy_mem.json"))
    agent = ThorAgent(retrieval_service=corpus, memory_service=mem)

    result = agent.investigate_and_argue(sample_case_file_round1)

    assert result.status == "success"
    assert len(result.claims) >= 4

    # Verify Claim 1 (Orvan sea corridor collapse)
    c1 = next((c for c in result.claims if c.claim_id == "THOR-C01"), None)
    assert c1 is not None
    assert any(c.doc_id == "ORV-0001" for c in c1.citations)
    assert any(c.doc_id == "ORV-0007" for c in c1.citations)

    # Verify Claim 2 (Midgard wheat)
    c2 = next((c for c in result.claims if c.claim_id == "THOR-C02"), None)
    assert c2 is not None
    assert any(c.doc_id == "ORV-0009" for c in c2.citations)

    # Verify Claim 3 (Tolan wheat)
    c3 = next((c for c in result.claims if c.claim_id == "THOR-C03"), None)
    assert c3 is not None
    assert any(c.doc_id == "ORV-0046" for c in c3.citations)

    # Verify Claim 4 (Midgard maize)
    c4 = next((c for c in result.claims if c.claim_id == "THOR-C04"), None)
    assert c4 is not None
    assert any(c.doc_id == "ORV-0030" for c in c4.citations)

    # Verify Claim 5 (Tolan maize data gap acknowledged)
    c5 = next((c for c in result.claims if c.claim_id == "THOR-C05"), None)
    assert c5 is not None
    assert c5.is_unsupported is True
    assert len(c5.estimates) == 0
