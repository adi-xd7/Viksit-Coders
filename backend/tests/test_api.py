"""Tests for FastAPI API endpoints and server layer (Part 8)."""

from typing import Generator
from pathlib import Path
from unittest.mock import MagicMock
import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.schemas.case_file import CaseFile
from backend.app.schemas.debate_result import DebateResult
from backend.app.schemas.heimdall_result import HeimdallVerificationResult, PremiseVerification
from backend.app.schemas.odin_result import OdinResult, ClaimRuling
from backend.app.schemas.claim import Claim, ExposureEstimate
from backend.app.schemas.feedback_loop import TrialRecord
from backend.app.schemas.evidence import EvidenceReference
from backend.app.services.case_store import InMemoryCaseStore
from backend.app.services.debate_orchestrator import DebateOrchestrator
from backend.app.services.executive_briefing import ExecutiveBriefingGenerator
from backend.app.routers.cases import get_orchestrator, get_case_store, get_briefing_generator


@pytest.fixture
def isolated_case_store() -> InMemoryCaseStore:
    """Isolated InMemoryCaseStore for each test."""
    return InMemoryCaseStore()


@pytest.fixture
def mock_evidence_ref() -> EvidenceReference:
    return EvidenceReference(
        doc_id="ORV-0016",
        paragraph="P1",
        reliability_tier=1,
        source_name="Realm Trade Ministry",
        publication_date="2026-09-10",
        quote_or_datapoint="The Corridor Agreement expired on 10 September 2026 without renewal.",
    )


@pytest.fixture
def sample_debate_result(mock_evidence_ref: EvidenceReference) -> DebateResult:
    case = CaseFile(
        case_id="CASE-API-TEST",
        question="What is the exposure to the corridor expiry?",
        as_of_date="2027-01-25",
        event_id="E5",
    )
    thor_claim = Claim(
        claim_id="C01",
        agent="thor",
        stance="high_exposure",
        claim_type="sourced_fact",
        statement="Midgard wheat receipts dropped 40%.",
        reasoning="Confirmed by trade receipts.",
        estimates=[
            ExposureEstimate(
                country="Midgard",
                sector="Wheat",
                metric="net_value_loss_pct",
                min_estimate=35.0,
                max_estimate=45.0,
            )
        ],
        citations=[mock_evidence_ref],
    )
    case.claims = [thor_claim]
    heimdall = HeimdallVerificationResult(
        agent="heimdall",
        case_id=case.case_id,
        as_of_date=case.as_of_date,
        is_event_real=True,
        verification_status="verified",
        premises=[
            PremiseVerification(
                premise_id="P1",
                premise="Corridor agreement expired on 2026-09-10.",
                status="verified",
                reasoning="Corroborated by ORV-0016 notice.",
                citations=[mock_evidence_ref],
            )
        ],
        summary="Event verified.",
    )
    odin = OdinResult(
        agent="odin",
        case_id=case.case_id,
        as_of_date=case.as_of_date,
        run_number=1,
        claim_rulings=[
            ClaimRuling(
                claim_id="C01",
                claim_statement="Midgard wheat receipts dropped 40%.",
                proponent="thor",
                ruling="established",
                reasoning="Confirmed by trade receipts.",
                supporting_citations=[mock_evidence_ref],
                adjudicated_range=ExposureEstimate(
                    country="Midgard",
                    sector="Wheat",
                    metric="net_value_loss_pct",
                    min_estimate=35.0,
                    max_estimate=45.0,
                ),
            )
        ],
        established_claims=["C01"],
        contested_claims=[],
        unresolved_disputes=[],
        is_evidence_sufficient=True,
        summary="Trial 1 concluded successfully.",
    )
    t1 = TrialRecord(
        trial_number=1,
        status="success",
        is_evidence_sufficient=True,
        gap_resolution_summary="Adjudicated on Trial 1.",
    )
    return DebateResult(
        case_id=case.case_id,
        as_of_date=case.as_of_date,
        case_file=case,
        status="success",
        heimdall_verification=heimdall,
        odin_adjudication=odin,
        total_trials=1,
        retries_attempted=0,
        max_retries=2,
        loop_stop_reason="evidence_sufficient",
        trial_history=[t1],
    )


@pytest.fixture
def client(
    isolated_case_store: InMemoryCaseStore,
    sample_debate_result: DebateResult,
) -> Generator[TestClient, None, None]:
    """Configured TestClient with isolated dependencies."""
    mock_orchestrator = MagicMock(spec=DebateOrchestrator)
    mock_orchestrator.run_debate.return_value = sample_debate_result

    app.dependency_overrides[get_case_store] = lambda: isolated_case_store
    app.dependency_overrides[get_orchestrator] = lambda: mock_orchestrator
    app.dependency_overrides[get_briefing_generator] = lambda: ExecutiveBriefingGenerator()

    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


# -----------------------------------------------------------------------------
# Test 1: Health Endpoint Returns Expected Response
# -----------------------------------------------------------------------------

def test_health_endpoint_returns_expected_response(client: TestClient):
    """Requirement 1: Health check returns 200 with service metadata and corpus status."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "ragnarok-ps3-courtroom"
    assert data["version"] == "1.0.0"
    assert "timestamp" in data
    assert "corpus_available" in data
    assert data["storage_type"] == "in_memory"

    # Also verify under /api/v1/health prefix
    v1_resp = client.get("/api/v1/health")
    assert v1_resp.status_code == 200
    assert v1_resp.json()["status"] == "healthy"


# -----------------------------------------------------------------------------
# Test 2: Application Imports Without Executing Debate
# -----------------------------------------------------------------------------

def test_app_imports_cleanly_without_active_debate():
    """Requirement 2: Importing app does not execute debates or heavy I/O."""
    from backend.app.main import app as main_app
    assert main_app.title == "RAGNAROK: Supply Chain Disruption Courtroom Analyzer"
    assert main_app.version == "1.0.0"


# -----------------------------------------------------------------------------
# Test 3 & 5: Valid Case Creation and In-Memory Persistence
# -----------------------------------------------------------------------------

def test_valid_case_creation_and_persistence(client: TestClient):
    """Requirement 3 & 5: Valid CaseFile is accepted, returned with 201, and stored in repository."""
    payload = {
        "case_id": "CASE-TEST-01",
        "question": "How exposed is Midgard to corridor expiry?",
        "as_of_date": "2027-01-25",
        "event_id": "E5",
        "is_verified": True,
    }
    response = client.post("/cases", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["case_id"] == "CASE-TEST-01"
    assert data["as_of_date"] == "2027-01-25"
    assert data["event_id"] == "E5"

    # Retrieve from GET /cases/{case_id}
    get_resp = client.get("/cases/CASE-TEST-01")
    assert get_resp.status_code == 200
    assert get_resp.json()["case_id"] == "CASE-TEST-01"

    # List cases
    list_resp = client.get("/cases")
    assert list_resp.status_code == 200
    summaries = list_resp.json()
    assert len(summaries) >= 1
    assert any(s["case_id"] == "CASE-TEST-01" for s in summaries)


# -----------------------------------------------------------------------------
# Test 4: Invalid CaseFile Requests Are Rejected
# -----------------------------------------------------------------------------

def test_invalid_case_requests_are_rejected(client: TestClient):
    """Requirement 4: Bad dates and empty case IDs are rejected with 400 or 422."""
    # Bad date format
    bad_date_payload = {
        "case_id": "CASE-BAD-DATE",
        "question": "Valid question?",
        "as_of_date": "25-01-2027",  # not YYYY-MM-DD
    }
    resp = client.post("/cases", json=bad_date_payload)
    assert resp.status_code in (400, 422)

    # Empty case_id
    empty_id_payload = {
        "case_id": "   ",
        "question": "Valid question?",
        "as_of_date": "2027-01-25",
    }
    resp = client.post("/cases", json=empty_id_payload)
    assert resp.status_code in (400, 422)


# -----------------------------------------------------------------------------
# Test 6 & 7: Debate Endpoint Executes Orchestrator and Returns DebateResult
# -----------------------------------------------------------------------------

def test_debate_endpoint_executes_orchestrator(client: TestClient):
    """Requirement 6 & 7: POST /cases/{case_id}/debate invokes orchestrator and returns DebateResult."""
    # Register case first
    client.post("/cases", json={
        "case_id": "CASE-API-TEST",
        "question": "What is the exposure to the corridor expiry?",
        "as_of_date": "2027-01-25",
        "event_id": "E5",
    })

    # Run debate
    resp = client.post("/cases/CASE-API-TEST/debate", json={"max_retries": 2})
    assert resp.status_code == 200
    data = resp.json()

    assert data["case_id"] == "CASE-API-TEST"
    assert data["status"] == "success"
    assert data["total_trials"] == 1
    assert data["loop_stop_reason"] == "evidence_sufficient"
    assert data["odin_adjudication"] is not None
    assert len(data["odin_adjudication"]["claim_rulings"]) >= 1


# -----------------------------------------------------------------------------
# Test 8: Heimdall Gate Rejection Is Represented Accurately
# -----------------------------------------------------------------------------

def test_heimdall_gate_rejection_represented_accurately(
    client: TestClient,
    isolated_case_store: InMemoryCaseStore,
):
    """Requirement 8: Heimdall premise rejection returns status error with gate reason."""
    client.post("/cases", json={
        "case_id": "CASE-REJECTED",
        "question": "Rumored event question",
        "as_of_date": "2027-01-25",
    })

    rejected_res = DebateResult(
        case_id="CASE-REJECTED",
        as_of_date="2027-01-25",
        case_file=CaseFile(case_id="CASE-REJECTED", question="Q", as_of_date="2027-01-25"),
        status="error",
        failed_stage="heimdall_verification",
        error_message="Pre-debate verification failed: Foundational disruption premises contradicted.",
        loop_stop_reason="heimdall_gate_rejected",
    )

    mock_orch = MagicMock(spec=DebateOrchestrator)
    mock_orch.run_debate.return_value = rejected_res
    app.dependency_overrides[get_orchestrator] = lambda: mock_orch

    resp = client.post("/cases/CASE-REJECTED/debate")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "error"
    assert data["failed_stage"] == "heimdall_verification"
    assert data["loop_stop_reason"] == "heimdall_gate_rejected"


# -----------------------------------------------------------------------------
# Test 9: Insufficient Evidence and Retry Exhaustion Reported Accurately
# -----------------------------------------------------------------------------

def test_retry_exhaustion_reported_accurately(
    client: TestClient,
    mock_evidence_ref: EvidenceReference,
):
    """Requirement 9: Insufficient evidence after max retries is preserved."""
    client.post("/cases", json={
        "case_id": "CASE-EXHAUSTED",
        "question": "Q",
        "as_of_date": "2027-01-25",
    })

    exhausted_res = DebateResult(
        case_id="CASE-EXHAUSTED",
        as_of_date="2027-01-25",
        case_file=CaseFile(case_id="CASE-EXHAUSTED", question="Q", as_of_date="2027-01-25"),
        status="success",
        odin_adjudication=OdinResult(
            agent="odin",
            case_id="CASE-EXHAUSTED",
            as_of_date="2027-01-25",
            is_evidence_sufficient=False,
            summary="Evidence remained insufficient after 3 trials.",
        ),
        total_trials=3,
        retries_attempted=2,
        max_retries=2,
        loop_stop_reason="max_retries_exhausted",
    )

    mock_orch = MagicMock(spec=DebateOrchestrator)
    mock_orch.run_debate.return_value = exhausted_res
    app.dependency_overrides[get_orchestrator] = lambda: mock_orch

    resp = client.post("/cases/CASE-EXHAUSTED/debate")
    assert resp.status_code == 200
    data = resp.json()
    assert data["loop_stop_reason"] == "max_retries_exhausted"
    assert data["odin_adjudication"]["is_evidence_sufficient"] is False


# -----------------------------------------------------------------------------
# Test 10: Agent Failure Does Not Return False Success
# -----------------------------------------------------------------------------

def test_agent_failure_does_not_return_false_success(client: TestClient):
    """Requirement 10: Unexpected orchestrator exception raises 500 error."""
    client.post("/cases", json={
        "case_id": "CASE-CRASH",
        "question": "Q",
        "as_of_date": "2027-01-25",
    })

    mock_orch = MagicMock(spec=DebateOrchestrator)
    mock_orch.run_debate.side_effect = RuntimeError("Fatal internal memory fault")
    app.dependency_overrides[get_orchestrator] = lambda: mock_orch

    resp = client.post("/cases/CASE-CRASH/debate")
    assert resp.status_code == 500
    assert "error" in resp.json()["detail"].lower()


# -----------------------------------------------------------------------------
# Test 11 & 12: Results Retrieval and Unknown Case Handling
# -----------------------------------------------------------------------------

def test_results_endpoint_and_unknown_case(client: TestClient):
    """Requirement 11 & 12: GET /cases/{case_id}/results returns results or 404."""
    # Unknown case
    resp_404 = client.get("/cases/NONEXISTENT/results")
    assert resp_404.status_code == 404

    # Case registered but not debated
    client.post("/cases", json={"case_id": "CASE-NOT-DEBATED", "question": "Q", "as_of_date": "2027-01-25"})
    resp_no_res = client.get("/cases/CASE-NOT-DEBATED/results")
    assert resp_no_res.status_code == 404

    # Debated case
    client.post("/cases", json={"case_id": "CASE-API-TEST", "question": "Q", "as_of_date": "2027-01-25"})
    client.post("/cases/CASE-API-TEST/debate")

    res = client.get("/cases/CASE-API-TEST/results")
    assert res.status_code == 200
    assert res.json()["case_id"] == "CASE-API-TEST"
    assert res.json()["status"] == "success"


def test_missing_briefing_before_debate_returns_404(client: TestClient):
    """Requirement 13: GET /cases/{case_id}/briefing returns 404 if debate has not been executed."""
    client.post("/cases", json={"case_id": "CASE-NO-DEBATE", "question": "Q", "as_of_date": "2027-01-25"})
    resp = client.get("/cases/CASE-NO-DEBATE/briefing")
    assert resp.status_code == 404
    assert "No debate result available" in resp.json()["detail"]


# -----------------------------------------------------------------------------
# Test 13 & 14: Briefing Endpoint and Authoritative Final Adjudication
# -----------------------------------------------------------------------------

def test_briefing_endpoint(client: TestClient):
    """Requirement 13 & 14: GET /cases/{case_id}/briefing returns ExecutiveBriefing."""
    client.post("/cases", json={"case_id": "CASE-API-TEST", "question": "Q", "as_of_date": "2027-01-25"})
    client.post("/cases/CASE-API-TEST/debate")

    resp = client.get("/cases/CASE-API-TEST/briefing")
    assert resp.status_code == 200
    data = resp.json()
    assert data["case_id"] == "CASE-API-TEST"
    assert data["status"] == "completed"
    assert "executive_summary" in data
    assert len(data["exposure_table"]) >= 1
    assert len(data["established_claims"]) >= 1
    assert len(data["cited_sources"]) >= 1


# -----------------------------------------------------------------------------
# Test 15: Trial History Returned in Correct Order
# -----------------------------------------------------------------------------

def test_trial_history_endpoint(client: TestClient):
    """Requirement 15: GET /cases/{case_id}/trials returns chronological trial history."""
    client.post("/cases", json={"case_id": "CASE-API-TEST", "question": "Q", "as_of_date": "2027-01-25"})
    client.post("/cases/CASE-API-TEST/debate")

    resp = client.get("/cases/CASE-API-TEST/trials")
    assert resp.status_code == 200
    trials = resp.json()
    assert len(trials) == 1
    assert trials[0]["trial_number"] == 1
    assert trials[0]["is_evidence_sufficient"] is True


# -----------------------------------------------------------------------------
# Test 16: Response Serialization Preserves Provenance and Rulings
# -----------------------------------------------------------------------------

def test_response_serialization_preserves_provenance(client: TestClient):
    """Requirement 16: Serialized briefing preserves document citations and rulings."""
    client.post("/cases", json={"case_id": "CASE-API-TEST", "question": "Q", "as_of_date": "2027-01-25"})
    client.post("/cases/CASE-API-TEST/debate")

    resp = client.get("/cases/CASE-API-TEST/briefing")
    briefing = resp.json()
    assert any(s["doc_id"] == "ORV-0016" for s in briefing["cited_sources"])
    assert any(c["claim_id"] == "C01" for c in briefing["established_claims"])


# -----------------------------------------------------------------------------
# Test 17: Concurrent / Conflict Request Handling
# -----------------------------------------------------------------------------

def test_conflict_on_duplicate_active_debate(
    client: TestClient,
    isolated_case_store: InMemoryCaseStore,
):
    """Requirement 17: Requesting debate while already running returns 409 Conflict."""
    client.post("/cases", json={"case_id": "CASE-LOCKED", "question": "Q", "as_of_date": "2027-01-25"})

    # Artificially set case as running in store
    isolated_case_store.set_running("CASE-LOCKED", True)

    resp = client.post("/cases/CASE-LOCKED/debate")
    assert resp.status_code == 409
    assert "already currently running" in resp.json()["detail"]


# -----------------------------------------------------------------------------
# Test 18: OpenAPI Generation
# -----------------------------------------------------------------------------

def test_openapi_schema_generation(client: TestClient):
    """Requirement 18: /openapi.json endpoint delivers valid schema with documented endpoints."""
    resp = client.get("/openapi.json")
    assert resp.status_code == 200
    schema = resp.json()
    assert "paths" in schema
    assert "/health" in schema["paths"]
    assert "/cases" in schema["paths"]
    assert "/cases/{case_id}" in schema["paths"]
    assert "/cases/{case_id}/debate" in schema["paths"]
    assert "/cases/{case_id}/results" in schema["paths"]
    assert "/cases/{case_id}/briefing" in schema["paths"]
    assert "/cases/{case_id}/trials" in schema["paths"]


# -----------------------------------------------------------------------------
# Test 19: End-to-End Real Corpus E5 Debate Through API
# -----------------------------------------------------------------------------

def test_official_corpus_e5_e2e_api_integration():
    """Requirement 19: End-to-end debate and briefing through API on dev_pack_E5 corpus."""
    pack_dir = Path("03_Ragnarok Trial of the Nine Realms/dev_pack_E5")
    if not pack_dir.exists():
        pack_dir = Path(__file__).resolve().parents[2] / "03_Ragnarok Trial of the Nine Realms" / "dev_pack_E5"
    if not pack_dir.exists():
        pytest.skip("Official dev_pack_E5 corpus directory not available.")

    # Use clean real TestClient without orchestrator mocks
    real_client = TestClient(app)

    case_payload = {
        "case_id": "CASE-CORPUS-E5-API",
        "question": "As of 25 January 2027, how exposed are Midgard and Tolan to the end of the Orvan corridor agreement?",
        "as_of_date": "2027-01-25",
        "event_id": "E5",
        "is_verified": True,
    }

    # 1. Create case
    c_resp = real_client.post("/cases", json=case_payload)
    assert c_resp.status_code == 201

    # 2. Run debate
    d_resp = real_client.post("/cases/CASE-CORPUS-E5-API/debate", json={"max_retries": 1})
    assert d_resp.status_code == 200
    debate_data = d_resp.json()
    assert debate_data["status"] == "success"
    assert debate_data["total_trials"] >= 1

    # 3. Retrieve results
    r_resp = real_client.get("/cases/CASE-CORPUS-E5-API/results")
    assert r_resp.status_code == 200
    assert r_resp.json()["case_id"] == "CASE-CORPUS-E5-API"

    # 4. Retrieve executive briefing
    b_resp = real_client.get("/cases/CASE-CORPUS-E5-API/briefing")
    assert b_resp.status_code == 200
    briefing_data = b_resp.json()
    assert briefing_data["case_id"] == "CASE-CORPUS-E5-API"
    assert briefing_data["status"] == "completed"
    assert len(briefing_data["exposure_table"]) >= 1

    # 5. Retrieve trials
    t_resp = real_client.get("/cases/CASE-CORPUS-E5-API/trials")
    assert t_resp.status_code == 200
    assert len(t_resp.json()) >= 1
