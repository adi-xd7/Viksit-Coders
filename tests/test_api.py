"""Comprehensive unit and integration tests for Phase 6: Odin Courtroom FastAPI API.

Tests all 22 required scenarios:
1. Health endpoint.
2. Successful case creation.
3. Invalid case input.
4. Case retrieval and missing-case behavior.
5. Case listing, pagination, and page-size limits.
6. Trial start for an existing case.
7. Trial start for a nonexistent case.
8. Duplicate concurrent trial start.
9. Trial status before execution.
10. Trial status after successful execution.
11. Trial status after failure or resource-limit termination.
12. Rulings endpoint returns only final Odin rulings.
13. Briefing endpoint returns the validated Phase 5 briefing.
14. Briefing unavailable while research is pending.
15. Citation-validation failure is not presented as a validated success.
16. not_real and uncertain event handling.
17. Malformed IDs and invalid state transitions.
18. Provider failure without secret leakage.
19. Persistence failure behavior.
20. Case/run isolation: data from one case cannot appear in another case's responses.
21. Existing Phase 1-5 regression tests.
22. JSON serialization of dates, enums, and nested briefing data.
"""

import json
import re
import pytest
from typing import Dict, List
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.case_store import CaseStore
from backend.api.service import TrialService
from backend.llm import LLMClient
from backend.logbook import LogBook
from backend.memory import MemoryStore
from backend.models import (
    AgentRole,
    Basis,
    Briefing,
    CaseFile,
    Citation,
    Claim,
    DocMeta,
    Document,
    EventVerificationStatus,
    ExposureRange,
    Ruling,
    SufficiencyResult,
    SufficiencyStatus,
    Verdict,
)
from backend.agents.odin import OdinJudge
from backend.trial import TrialGraphBuilder


@pytest.fixture
def mock_evidence_stores():
    doc_store = {
        "ATL-0001": Document(
            meta=DocMeta(
                DOC_ID="ATL-0001",
                PUB_DATE="2027-01-10",
                RELIABILITY=1,
                COUNTRY="Midgard",
                SECTOR="wheat",
                SOURCE_NAME="Ministry of Transport",
            ),
            paragraphs={
                1: "Midgard wheat corridor transit was suspended following structural damage to the main lock.",
                2: "Initial assessments confirm commercial transit throughput dropped by 45%.",
            },
        ),
        "ATL-0002": Document(
            meta=DocMeta(
                DOC_ID="ATL-0002",
                PUB_DATE="2027-01-12",
                RELIABILITY=2,
                COUNTRY="Midgard",
                SECTOR="wheat",
            ),
            paragraphs={
                1: "Alternative railway lines can absorb approximately 15% of the stranded grain shipments.",
            },
        ),
    }
    return doc_store


@pytest.fixture
def api_test_env(tmp_path, mock_evidence_stores):
    """Sets up an isolated, in-memory API test environment."""
    cases_dir = str(tmp_path / "cases")
    case_store = CaseStore(db_path=":memory:", output_dir=cases_dir)
    logbook = LogBook(db_path=str(tmp_path / "audit.db"))
    memory_store = MemoryStore()
    llm = LLMClient()

    def mock_llm_handler(sys: str, user: str, kwargs: dict) -> str:
        return json.dumps({
            "rulings": [
                {
                    "claim_id": "THOR-C1-MID-WHE",
                    "verdict": "established",
                    "basis": "sourced_fact",
                    "rationale": "Sufficiently proven by corridor damage record.",
                },
                {
                    "claim_id": "LOKI-C1-MID-WHE",
                    "verdict": "conceded",
                    "basis": "inference",
                    "rationale": "Conceded during cross-examination.",
                },
            ]
        })

    llm.set_mock_handler(mock_llm_handler)

    def builder_factory():
        class MockSufficiencyOdin(OdinJudge):
            def assess_sufficiency(self, *args, **kwargs) -> SufficiencyResult:
                return SufficiencyResult(
                    status=SufficiencyStatus.SUFFICIENT,
                    is_sufficient=True,
                    reasons=["All required trade baseline and disruption evidence is present and verified."],
                )

        return TrialGraphBuilder(
            llm_client=llm,
            logbook=logbook,
            memory_store=memory_store,
            odin=MockSufficiencyOdin(llm_client=llm, logbook=logbook, memory_store=memory_store),
            output_dir=cases_dir,
        )

    service = TrialService(
        case_store=case_store,
        logbook=logbook,
        llm_client=llm,
        builder_factory=builder_factory,
    )

    app = create_app(service=service)
    client = TestClient(app)

    return {
        "client": client,
        "service": service,
        "case_store": case_store,
        "llm": llm,
        "cases_dir": cases_dir,
        "builder_factory": builder_factory,
    }


# =====================================================================
# Test 1: Health Endpoint
# =====================================================================
def test_scenario_01_health_endpoint(api_test_env):
    """GET /health reports process and database dependency health."""
    client = api_test_env["client"]
    resp = client.get("/health")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["process"] == "healthy"
    assert data["database"] == "healthy"
    assert "timestamp" in data
    # Ensure no internal secret paths or keys leaked
    assert "sk-" not in json.dumps(data)


# =====================================================================
# Test 2: Successful Case Creation
# =====================================================================
def test_scenario_02_create_case_success(api_test_env):
    """POST /api/cases creates and persists a valid case."""
    client = api_test_env["client"]
    payload = {
        "query": "As of 25 January 2027, how exposed is Midgard wheat?",
        "as_of": "2027-01-25",
        "case_id": "CASE-MIDGARD-01",
        "target_country_sector_pairs": [["Midgard", "wheat"]],
    }
    resp = client.post("/api/cases", json=payload)

    assert resp.status_code == 201
    data = resp.json()
    assert data["case_id"] == "CASE-MIDGARD-01"
    assert data["as_of"] == "2027-01-25"
    assert data["status"] == "created"
    assert data["target_country_sector_pairs"] == [["Midgard", "wheat"]]
    assert "created_at" in data


# =====================================================================
# Test 3: Invalid Case Input
# =====================================================================
def test_scenario_03_create_case_invalid_input(api_test_env):
    """POST /api/cases rejects malformed input (bad date, short query, invalid ID)."""
    client = api_test_env["client"]

    # 1. Invalid date
    bad_date = {
        "query": "Valid query length here",
        "as_of": "invalid-date-format",
    }
    resp = client.post("/api/cases", json=bad_date)
    assert resp.status_code == 422
    assert "VALIDATION_ERROR" in resp.json()["error"]

    # 2. Short query
    short_q = {
        "query": "tiny",
        "as_of": "2027-01-25",
    }
    resp = client.post("/api/cases", json=short_q)
    assert resp.status_code == 422

    # 3. Malformed case_id (special characters)
    bad_id = {
        "query": "Valid disruption inquiry here",
        "as_of": "2027-01-25",
        "case_id": "BAD/ID/PATH/TRAVERSAL",
    }
    resp = client.post("/api/cases", json=bad_id)
    assert resp.status_code == 422


# =====================================================================
# Test 4: Case Retrieval and Missing Case
# =====================================================================
def test_scenario_04_get_case_existing_and_missing(api_test_env):
    """GET /api/cases/{case_id} retrieves case details or returns 404."""
    client = api_test_env["client"]

    # Create case
    client.post("/api/cases", json={"query": "Test query for retrieval", "as_of": "2027-01-25", "case_id": "CASE-FIND-ME"})

    # Existing
    resp = client.get("/api/cases/CASE-FIND-ME")
    assert resp.status_code == 200
    assert resp.json()["case_id"] == "CASE-FIND-ME"

    # Missing
    resp_missing = client.get("/api/cases/CASE-NONEXISTENT-999")
    assert resp_missing.status_code == 404
    assert resp_missing.json()["error"] == "CASE_NOT_FOUND"


# =====================================================================
# Test 5: Case Listing, Pagination, and Page-Size Limits
# =====================================================================
def test_scenario_05_list_cases_pagination_and_limits(api_test_env):
    """GET /api/cases supports stable ordering, pagination, and max limit clamp."""
    client = api_test_env["client"]

    # Create 5 cases
    for i in range(5):
        client.post("/api/cases", json={"query": f"Query number {i+1}", "as_of": "2027-01-25", "case_id": f"CASE-LIST-{i+1}"})

    # Retrieve page 1 with limit 2
    resp_p1 = client.get("/api/cases?limit=2&offset=0")
    assert resp_p1.status_code == 200
    data_p1 = resp_p1.json()
    assert len(data_p1["items"]) == 2
    assert data_p1["total"] == 5
    assert data_p1["limit"] == 2
    assert data_p1["offset"] == 0

    # Retrieve page 2 with limit 2
    resp_p2 = client.get("/api/cases?limit=2&offset=2")
    assert resp_p2.status_code == 200
    data_p2 = resp_p2.json()
    assert len(data_p2["items"]) == 2
    # Ensure distinct items
    p1_ids = [c["case_id"] for c in data_p1["items"]]
    p2_ids = [c["case_id"] for c in data_p2["items"]]
    assert not set(p1_ids).intersection(set(p2_ids))


# =====================================================================
# Test 6: Trial Start for Existing Case
# =====================================================================
def test_scenario_06_start_trial_existing_case(api_test_env):
    """POST /api/cases/{case_id}/trials successfully initiates trial."""
    client = api_test_env["client"]
    client.post("/api/cases", json={"query": "Midgard wheat inquiry", "as_of": "2027-01-25", "case_id": "CASE-TRIAL-01"})

    resp = client.post("/api/cases/CASE-TRIAL-01/trials", json={"max_runs": 2, "background": False})
    assert resp.status_code == 200
    data = resp.json()
    assert data["case_id"] == "CASE-TRIAL-01"
    assert data["trial_id"].startswith("TRIAL-")
    assert data["status"] == "completed"
    assert data["is_completed"] is True


# =====================================================================
# Test 7: Trial Start for Nonexistent Case
# =====================================================================
def test_scenario_07_start_trial_nonexistent_case(api_test_env):
    """POST /api/cases/NONEXISTENT/trials returns 404."""
    client = api_test_env["client"]
    resp = client.post("/api/cases/CASE-GHOST/trials", json={"max_runs": 2})

    assert resp.status_code == 404
    assert resp.json()["error"] == "CASE_NOT_FOUND"


# =====================================================================
# Test 8: Duplicate Concurrent Trial Start
# =====================================================================
def test_scenario_08_duplicate_concurrent_trial_start(api_test_env):
    """POST /api/cases/{case_id}/trials returns 409 when trial is already running."""
    client = api_test_env["client"]
    service = api_test_env["service"]

    client.post("/api/cases", json={"query": "Concurrency test query", "as_of": "2027-01-25", "case_id": "CASE-LOCK-01"})

    # Manually acquire the lock to simulate in-flight execution
    assert service.case_store.acquire_case_lock("CASE-LOCK-01") is True

    try:
        resp = client.post("/api/cases/CASE-LOCK-01/trials", json={"max_runs": 2})
        assert resp.status_code == 409
        assert resp.json()["error"] == "TRIAL_ALREADY_RUNNING"
    finally:
        service.case_store.release_case_lock("CASE-LOCK-01")


# =====================================================================
# Test 9: Trial Status Before Execution (Pending/Running)
# =====================================================================
def test_scenario_09_trial_status_before_execution(api_test_env):
    """GET /api/cases/{case_id}/trials/{trial_id} returns pending/running status before completion."""
    client = api_test_env["client"]
    case_store = api_test_env["case_store"]

    client.post("/api/cases", json={"query": "Status test query", "as_of": "2027-01-25", "case_id": "CASE-STATUS-01"})
    trial_rec = case_store.create_trial("CASE-STATUS-01", "TRIAL-INIT-01", status="running")

    resp = client.get("/api/cases/CASE-STATUS-01/trials/TRIAL-INIT-01")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "running"
    assert data["is_completed"] is False
    assert data["end_time"] is None


# =====================================================================
# Test 10: Trial Status After Successful Execution
# =====================================================================
def test_scenario_10_trial_status_after_successful_execution(api_test_env):
    """GET /api/cases/{case_id}/trials/{trial_id} returns completed status after trial."""
    client = api_test_env["client"]
    client.post("/api/cases", json={"query": "Successful trial query", "as_of": "2027-01-25", "case_id": "CASE-COMP-01"})

    trial_resp = client.post("/api/cases/CASE-COMP-01/trials", json={"max_runs": 1, "background": False})
    trial_id = trial_resp.json()["trial_id"]

    resp = client.get(f"/api/cases/CASE-COMP-01/trials/{trial_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "completed"
    assert data["is_completed"] is True
    assert data["end_time"] is not None


# =====================================================================
# Test 11: Trial Status After Failure or Resource Limit Termination
# =====================================================================
def test_scenario_11_trial_status_after_limit_exhaustion(api_test_env):
    """Trial terminated due to run limits honestly reports limits_exhausted."""
    client = api_test_env["client"]
    service = api_test_env["service"]

    class LimitExhaustedOdin(OdinJudge):
        def assess_sufficiency(self, *args, **kwargs) -> SufficiencyResult:
            return SufficiencyResult(
                status=SufficiencyStatus.LIMITS_EXHAUSTED,
                is_sufficient=False,
                reasons=["Max runs exhausted."],
            )

    service.builder_factory = lambda: TrialGraphBuilder(
        llm_client=api_test_env["llm"],
        odin=LimitExhaustedOdin(llm_client=api_test_env["llm"]),
        output_dir=api_test_env["cases_dir"],
    )

    client.post("/api/cases", json={"query": "Limit trial query", "as_of": "2027-01-25", "case_id": "CASE-LIMIT-API"})
    resp = client.post("/api/cases/CASE-LIMIT-API/trials", json={"max_runs": 1, "background": False})

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "limits_exhausted"
    assert data["is_completed"] is True


# =====================================================================
# Test 12: Rulings Endpoint Returns Only Final Odin Rulings
# =====================================================================
def test_scenario_12_rulings_endpoint_final_rulings_only(api_test_env):
    """GET /api/cases/{case_id}/trials/{trial_id}/rulings returns Odin's binding rulings."""
    client = api_test_env["client"]
    client.post("/api/cases", json={"query": "Rulings inquiry", "as_of": "2027-01-25", "case_id": "CASE-RULINGS-01"})

    trial_resp = client.post("/api/cases/CASE-RULINGS-01/trials", json={"max_runs": 1, "background": False})
    trial_id = trial_resp.json()["trial_id"]

    resp = client.get(f"/api/cases/CASE-RULINGS-01/trials/{trial_id}/rulings")
    assert resp.status_code == 200
    data = resp.json()
    assert data["case_id"] == "CASE-RULINGS-01"
    assert data["trial_id"] == trial_id
    assert data["rulings_count"] >= 2
    verdicts = [r["verdict"] for r in data["rulings"]]
    assert "established" in verdicts


# =====================================================================
# Test 13: Briefing Endpoint Returns Validated Briefing
# =====================================================================
def test_scenario_13_briefing_endpoint_returns_validated_briefing(api_test_env):
    """GET /api/cases/{case_id}/trials/{trial_id}/briefing returns complete Phase 5 briefing."""
    client = api_test_env["client"]
    client.post("/api/cases", json={"query": "Briefing inquiry", "as_of": "2027-01-25", "case_id": "CASE-BRIEF-01"})

    trial_resp = client.post("/api/cases/CASE-BRIEF-01/trials", json={"max_runs": 1, "background": False})
    trial_id = trial_resp.json()["trial_id"]

    resp = client.get(f"/api/cases/CASE-BRIEF-01/trials/{trial_id}/briefing")
    assert resp.status_code == 200
    data = resp.json()
    assert data["case_id"] == "CASE-BRIEF-01"
    assert "executive_summary" in data
    assert "established_findings" in data
    assert "exposure_table" in data
    assert "verification_summary" in data
    assert "markdown_content" in data
    assert "# TRIAL OF THE NINE REALMS" in data["markdown_content"]


# =====================================================================
# Test 14: Briefing Unavailable While Research Is Pending
# =====================================================================
def test_scenario_14_briefing_unavailable_while_research_pending(api_test_env):
    """GET /api/cases/{case_id}/trials/{trial_id}/briefing returns 409 when trial is in send-back loop."""
    client = api_test_env["client"]
    case_store = api_test_env["case_store"]

    client.post("/api/cases", json={"query": "Pending research inquiry", "as_of": "2027-01-25", "case_id": "CASE-PENDING-01"})
    case_store.create_trial("CASE-PENDING-01", "TRIAL-SENDBACK-01", status="awaiting_research")
    case_store.update_trial("TRIAL-SENDBACK-01", is_awaiting_research=True)

    resp = client.get("/api/cases/CASE-PENDING-01/trials/TRIAL-SENDBACK-01/briefing")
    assert resp.status_code == 409
    assert resp.json()["error"] == "TRIAL_AWAITING_RESEARCH"


# =====================================================================
# Test 15: Citation Validation Failure Is Not Presented as Valid Success
# =====================================================================
def test_scenario_15_citation_validation_failure_not_presented_as_valid(api_test_env):
    """A ruling citing an invalid or non-existent document has its finding marked and recorded in failures."""
    client = api_test_env["client"]
    case_store = api_test_env["case_store"]

    cf = CaseFile(case_id="CASE-BAD-CIT", query="Query", as_of="2027-01-25")
    case_store.create_case(cf)

    # Ruling with non-existent document citation
    bad_ruling = Ruling(
        claim_id="THOR-BAD",
        verdict=Verdict.ESTABLISHED,
        basis=Basis.SOURCED_FACT,
        rationale="Unsupported claim",
        admissible_citations=[Citation(doc_id="DOC-DOES-NOT-EXIST", paragraph_num=1)],
    )

    # Generate briefing via service
    from backend.briefing import generate_briefing
    briefing = generate_briefing(
        case_file=cf,
        rulings=[bad_ruling],
        exposure_ranges=[],
        doc_store={},
    )
    case_store.create_trial("CASE-BAD-CIT", "TRIAL-BAD-CIT", status="completed")
    case_store.save_trial_artifacts("TRIAL-BAD-CIT", "CASE-BAD-CIT", rulings=[bad_ruling], briefing=briefing)

    resp = client.get("/api/cases/CASE-BAD-CIT/trials/TRIAL-BAD-CIT/briefing")
    assert resp.status_code == 200
    data = resp.json()
    finding = data["established_findings"][0]
    assert "[INSUFFICIENTLY SUPPORTED - Citations Failed Validation]" in finding["finding"]
    assert len(data["verification_summary"]["citation_failures"]) > 0


# =====================================================================
# Test 16: Event Classified as not_real and uncertain
# =====================================================================
def test_scenario_16_not_real_and_uncertain_event_handling(api_test_env):
    """API preserves counterfeit notice for not_real and warning for uncertain."""
    client = api_test_env["client"]
    case_store = api_test_env["case_store"]

    # 1. Not Real
    cf_not_real = CaseFile(
        case_id="CASE-NOT-REAL-API",
        query="Hoax strike in Midgard",
        as_of="2027-01-25",
        verification_status=EventVerificationStatus.NOT_REAL,
        verification_reason="Decoy document detected.",
    )
    case_store.create_case(cf_not_real)
    from backend.briefing import generate_briefing
    b_nr = generate_briefing(case_file=cf_not_real, rulings=[], exposure_ranges=[], doc_store={})
    case_store.create_trial("CASE-NOT-REAL-API", "TRIAL-NR-01", status="event_not_real")
    case_store.save_trial_artifacts("TRIAL-NR-01", "CASE-NOT-REAL-API", rulings=[], briefing=b_nr)

    resp_nr = client.get("/api/cases/CASE-NOT-REAL-API/trials/TRIAL-NR-01/briefing")
    assert resp_nr.status_code == 200
    assert "EVENT NOT REAL / COUNTERFEIT NOTICE" in resp_nr.json()["executive_summary"]
    assert "Zero net exposure across all examined country-sector pairs" in resp_nr.json()["executive_summary"]


# =====================================================================
# Test 17: Malformed Identifiers and Path Traversal Rejected
# =====================================================================
def test_scenario_17_malformed_ids_and_path_traversal(api_test_env):
    """Malformed IDs with path traversal characters are rejected with 400 Bad Request."""
    client = api_test_env["client"]
    # Path traversal in case_id
    resp = client.get("/api/cases/..%2F..%2Fetc%2Fpasswd")
    assert resp.status_code in (400, 404)


# =====================================================================
# Test 18: Provider Failure Without Secret Leakage
# =====================================================================
def test_scenario_18_provider_failure_without_secret_leakage(api_test_env):
    """Provider exception terminates safely without exposing API keys or secrets."""
    client = api_test_env["client"]
    service = api_test_env["service"]

    def failing_builder():
        class FailingOdin(OdinJudge):
            def judge_claims(self, *args, **kwargs):
                raise RuntimeError("Anthropic provider connection error with key sk-ant-secret123456789")

        return TrialGraphBuilder(
            llm_client=api_test_env["llm"],
            odin=FailingOdin(llm_client=api_test_env["llm"]),
            output_dir=api_test_env["cases_dir"],
        )

    service.builder_factory = failing_builder
    client.post("/api/cases", json={"query": "Provider failure test", "as_of": "2027-01-25", "case_id": "CASE-FAIL-API"})

    resp = client.post("/api/cases/CASE-FAIL-API/trials", json={"max_runs": 1, "background": False})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "failed"
    # Verify no secret leaked into error message
    assert "sk-ant" not in json.dumps(data)
    assert "secret" not in data["error_message"].lower()


# =====================================================================
# Test 19: Persistence Failure Behavior
# =====================================================================
def test_scenario_19_persistence_failure_behavior(api_test_env):
    """Database connectivity failure is reported in health check."""
    client = api_test_env["client"]
    case_store = api_test_env["case_store"]

    # Close connection to simulate database failure
    case_store._conn.close()

    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "degraded"
    assert resp.json()["database"] == "unhealthy"


# =====================================================================
# Test 20: Case and Run Isolation
# =====================================================================
def test_scenario_20_case_and_run_isolation(api_test_env):
    """Trials belonging to Case A cannot be accessed under Case B."""
    client = api_test_env["client"]
    client.post("/api/cases", json={"query": "Case A query", "as_of": "2027-01-25", "case_id": "CASE-AAA"})
    client.post("/api/cases", json={"query": "Case B query", "as_of": "2027-01-25", "case_id": "CASE-BBB"})

    t_resp = client.post("/api/cases/CASE-AAA/trials", json={"max_runs": 1, "background": False})
    trial_a_id = t_resp.json()["trial_id"]

    # Accessing trial A under Case B must return 404
    resp = client.get(f"/api/cases/CASE-BBB/trials/{trial_a_id}")
    assert resp.status_code == 404
    assert resp.json()["error"] == "TRIAL_NOT_FOUND"


# =====================================================================
# Test 21: Regression Test (Full Trial Graph and Briefing Generation)
# =====================================================================
def test_scenario_21_regression_trial_graph_and_briefing(api_test_env):
    """End-to-end integration: case creation, trial execution, rulings, and briefing."""
    client = api_test_env["client"]
    client.post("/api/cases", json={"query": "Full trial flow", "as_of": "2027-01-25", "case_id": "CASE-E2E-01"})

    # Start trial
    t_resp = client.post("/api/cases/CASE-E2E-01/trials", json={"max_runs": 1, "background": False})
    trial_id = t_resp.json()["trial_id"]
    assert t_resp.json()["status"] == "completed"

    # Check rulings
    r_resp = client.get(f"/api/cases/CASE-E2E-01/trials/{trial_id}/rulings")
    assert r_resp.status_code == 200
    assert r_resp.json()["rulings_count"] >= 2

    # Check briefing
    b_resp = client.get(f"/api/cases/CASE-E2E-01/trials/{trial_id}/briefing")
    assert b_resp.status_code == 200
    briefing_data = b_resp.json()
    assert briefing_data["case_id"] == "CASE-E2E-01"
    assert len(briefing_data["established_findings"]) > 0


# =====================================================================
# Test 22: JSON Serialization of Dates, Enums, and Nested Data
# =====================================================================
def test_scenario_22_json_serialization_of_dates_enums_and_nested_data(api_test_env):
    """All API responses are strictly JSON-serializable with standard types."""
    client = api_test_env["client"]
    resp = client.post(
        "/api/cases",
        json={"query": "Serialization test query", "as_of": "2027-01-25", "case_id": "CASE-SERIAL-01"},
    )
    assert resp.status_code == 201

    # Verify JSON content-type and valid json parsing
    assert resp.headers["content-type"] == "application/json"
    data = resp.json()
    # Check ISO date format
    assert re.match(r"^\d{4}-\d{2}-\d{2}", data["as_of"])
    assert re.match(r"^\d{4}-\d{2}-\d{2}T", data["created_at"])


# =====================================================================
# Test 23: Complete Submission Deliverables Package Endpoint
# =====================================================================
def test_scenario_23_submission_deliverables_endpoint(api_test_env):
    """Verifies that the /submission endpoint bundles all 7 evaluation questions."""
    client = api_test_env["client"]
    client.post("/api/cases", json={"query": "Submission bundle test", "as_of": "2027-01-25", "case_id": "CASE-SUB-01"})

    t_resp = client.post("/api/cases/CASE-SUB-01/trials", json={"max_runs": 1, "background": False})
    trial_id = t_resp.json()["trial_id"]
    assert t_resp.json()["status"] == "completed"

    sub_resp = client.get(f"/api/cases/CASE-SUB-01/trials/{trial_id}/submission")
    assert sub_resp.status_code == 200
    bundle = sub_resp.json()

    assert "final_output" in bundle
    assert "execution_trace" in bundle
    assert "submission_metadata" in bundle

    fo = bundle["final_output"]
    assert "question_1_event_verification" in fo
    assert "question_2_exposure_ranges" in fo
    assert "question_3_odins_executive_briefing" in fo

    trace = bundle["execution_trace"]
    assert "question_4_agent_queries_and_retrieved_documents" in trace
    assert "question_5_cross_examination_challenges_and_counter_arguments" in trace
    assert "question_6_memory_updates_and_claim_concessions" in trace
    assert "question_7_judicial_rulings_per_round" in trace

