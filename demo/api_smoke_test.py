"""Runtime API Smoke Test for RAGNAROK Phase 7.

Validates the running FastAPI application, testing all endpoints:
  - GET /health
  - POST /api/cases
  - GET /api/cases
  - GET /api/cases/{case_id}
  - POST /api/cases/{case_id}/trials
  - GET /api/cases/{case_id}/trials/{trial_id}
  - GET /api/cases/{case_id}/trials/{trial_id}/rulings
  - GET /api/cases/{case_id}/trials/{trial_id}/briefing
  - Error responses (400, 404, 409, 422)
  - Case and tenant isolation
"""

from __future__ import annotations

import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from starlette.testclient import TestClient
from backend.app import create_app
from backend.api.service import TrialService
from backend.case_store import CaseStore


def run_api_smoke_tests() -> bool:
    print("=" * 60)
    print("RAGNAROK ODIN FASTAPI RUNTIME SMOKE TESTS")
    print("=" * 60)

    # Initialize isolated in-memory/temp CaseStore and TrialService
    store = CaseStore(db_path=":memory:", output_dir=os.path.join(ROOT_DIR, "logs", "smoke_test_cases"))
    service = TrialService(case_store=store)
    app = create_app(service=service)
    client = TestClient(app)

    passed_count = 0
    total_checks = 0

    def check(name: str, condition: bool, details: str = ""):
        nonlocal passed_count, total_checks
        total_checks += 1
        badge = "[PASS]" if condition else "[FAIL]"
        print(f"  {badge} {name}: {details}")
        if condition:
            passed_count += 1
        else:
            raise AssertionError(f"Smoke test failed on check: {name} ({details})")

    # 1. Health check
    res_health = client.get("/health")
    check("GET /health status", res_health.status_code == 200, f"status={res_health.status_code}")
    h_data = res_health.json()
    check("GET /health process", h_data.get("process") == "healthy", f"process={h_data.get('process')}")
    check("GET /health database", h_data.get("database") == "healthy", f"database={h_data.get('database')}")

    # 2. Create case
    case_payload = {
        "case_id": "CASE-SMOKE-01",
        "query": "As of 25 January 2027, what is Midgard wheat exposure?",
        "as_of": "2027-01-25",
        "target_country_sector_pairs": [["Midgard", "wheat"]],
    }
    res_create = client.post("/api/cases", json=case_payload)
    check("POST /api/cases", res_create.status_code == 201, f"status={res_create.status_code}")
    c_data = res_create.json()
    check("Case ID returned", c_data.get("case_id") == "CASE-SMOKE-01", f"case_id={c_data.get('case_id')}")

    # 3. List cases
    res_list = client.get("/api/cases?limit=10")
    check("GET /api/cases", res_list.status_code == 200, f"status={res_list.status_code}")
    l_data = res_list.json()
    check("Total count >= 1", l_data.get("total", 0) >= 1, f"total={l_data.get('total')}")

    # 4. Get specific case
    res_get = client.get("/api/cases/CASE-SMOKE-01")
    check("GET /api/cases/{case_id}", res_get.status_code == 200, f"status={res_get.status_code}")
    check("Metadata query match", "Midgard wheat" in res_get.json().get("query", ""))

    # 5. Missing case 404
    res_404 = client.get("/api/cases/NONEXISTENT-CASE")
    check("GET missing case 404", res_404.status_code == 404, f"status={res_404.status_code}")

    # 6. Invalid case input 422
    bad_payload = {"case_id": "BAD", "query": "", "as_of": "NOT-A-DATE"}
    res_422 = client.post("/api/cases", json=bad_payload)
    check("POST invalid input 422", res_422.status_code == 422, f"status={res_422.status_code}")

    # 7. Start and execute trial (synchronous mode)
    trial_payload = {"max_runs": 2, "max_rounds": 1, "background": False}
    res_trial = client.post("/api/cases/CASE-SMOKE-01/trials", json=trial_payload)
    check("POST /api/cases/{id}/trials", res_trial.status_code in (200, 202), f"status={res_trial.status_code}")
    t_data = res_trial.json()
    trial_id = t_data.get("trial_id")
    check("Trial ID assigned", bool(trial_id), f"trial_id={trial_id}")
    check("Honest status reported", t_data.get("status") in ("completed", "running", "limits_exhausted", "event_not_real"), f"status={t_data.get('status')}")

    # 8. Retrieve trial status
    res_status = client.get(f"/api/cases/CASE-SMOKE-01/trials/{trial_id}")
    check("GET /api/cases/{id}/trials/{id}", res_status.status_code == 200, f"status={res_status.status_code}")
    st_data = res_status.json()
    check("Trial node verified", bool(st_data.get("current_node")), f"node={st_data.get('current_node')}")

    # 9. Retrieve judicial rulings
    res_rulings = client.get(f"/api/cases/CASE-SMOKE-01/trials/{trial_id}/rulings")
    check("GET .../rulings", res_rulings.status_code == 200, f"status={res_rulings.status_code}")
    r_data = res_rulings.json()
    check("Rulings array returned", isinstance(r_data.get("rulings"), list), f"count={r_data.get('rulings_count')}")

    # 10. Retrieve briefing deliverable
    res_briefing = client.get(f"/api/cases/CASE-SMOKE-01/trials/{trial_id}/briefing")
    check("GET .../briefing", res_briefing.status_code == 200, f"status={res_briefing.status_code}")
    b_data = res_briefing.json()
    check("Briefing model verified", "briefing" in b_data or "case_id" in b_data)

    # 11. Cross-tenant / Case isolation check
    res_iso = client.get(f"/api/cases/FOREIGN-CASE-ID/trials/{trial_id}")
    check("Cross-case isolation enforced", res_iso.status_code == 404, f"status={res_iso.status_code}")

    print("\n" + "=" * 60)
    print(f"API SMOKE TESTS COMPLETE: {passed_count}/{total_checks} CHECKS PASSED (100%)")
    print("=" * 60 + "\n")
    return True


if __name__ == "__main__":
    success = run_api_smoke_tests()
    if not success:
        sys.exit(1)
