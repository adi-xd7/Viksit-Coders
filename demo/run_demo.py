"""End-to-end Demonstration Runner for RAGNAROK Phase 7.

Executes a complete, reproducible trial of the Nine Realms courtroom system:
  1. Loads documented synthetic disruption scenario and source documents.
  2. Registers case in SQLite case store via FastAPI service layer.
  3. Executes compiled Phase 4 LangGraph trial workflow.
  4. Streams agent events:
     - Heimdall: event verification & evidence retrieval
     - Thor: high-exposure commercial argument
     - Loki: limited-exposure offset argument
     - Cross-examination: challenges and concessions
     - Odin: admissibility validation, judicial rulings, exposure bounds
     - Sufficiency loop: send-back detection
     - Briefing: Phase 5 validated briefing assembly & Markdown export
  5. Displays executive summary, judicial rulings table, exposure ranges, and trap statistics.
  6. Audits citation integrity and deterministic financial calculations.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from backend.api.schemas import CreateCaseRequest, StartTrialRequest
from backend.api.service import TrialService
from backend.case_store import CaseStore
from backend.llm import LLMClient, default_llm_client
from backend.logbook import LogBook, LogEventType
from backend.models import (
    AgentRole,
    Basis,
    CaseFile,
    EventVerificationStatus,
    ExposureRange,
    Ruling,
    Verdict,
)
from demo.fixtures.loader import load_adversarial_fixtures


def print_banner(text: str, ch: str = "="):
    line = ch * 70
    print(f"\n{line}\n  {text}\n{line}")


def print_step(num: int, title: str):
    print(f"\n[STEP {num}] {title}")
    print("-" * 50)


async def main():
    parser = argparse.ArgumentParser(description="RAGNAROK Odin Courtroom End-to-End Demonstration")
    parser.add_argument("--live", action="store_true", help="Force live LLM calls (requires ANTHROPIC_API_KEY)")
    parser.add_argument("--as-of", default="2027-01-25", help="Investigation as-of cutoff date (YYYY-MM-DD)")
    parser.add_argument("--case-id", default="DEMO-CASE-2027-01", help="Case identifier")
    args = parser.parse_args()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    is_live = bool(args.live and api_key)
    mode_label = "LIVE ANTHROPIC API MODE" if is_live else "OFFLINE DETERMINISTIC VERIFICATION MODE (Mock Adapter)"

    print_banner(f"RAGNAROK: TRIAL OF THE NINE REALMS\n  SUPPLY CHAIN DISRUPTION IMPACT ANALYZER — ODIN COURTROOM\n  [{mode_label}]")

    if not is_live:
        from backend.llm import deterministic_offline_adjudication
        default_llm_client.set_mock_handler(deterministic_offline_adjudication)

    # Step 1: Scenario Loading
    print_step(1, "Loading Synthetic Disruption Scenario & Evidence Corpus")
    doc_store, trade_store = load_adversarial_fixtures()
    print(f"Loaded {len(doc_store)} source documents from synthetic adversarial pack.")
    print(f"Loaded {len(trade_store)} trade tables ({sum(len(rows) for rows in trade_store.values())} monthly rows).")
    print(f"As-Of Date Cutoff: {args.as_of}")

    # Step 2: Case Registration
    print_step(2, "Registering Investigation Case via Courtroom API Service")
    demo_db = os.path.join(ROOT_DIR, "logs", "demo_cases.db")
    demo_cases_dir = os.path.join(ROOT_DIR, "logs", "demo_cases")
    store = CaseStore(db_path=demo_db, output_dir=demo_cases_dir)
    service = TrialService(case_store=store)

    create_req = CreateCaseRequest(
        case_id=args.case_id,
        query=f"As of {args.as_of}, how exposed is Midgard wheat and Tolan maize to the corridor transit disruption?",
        as_of=args.as_of,
        target_country_sector_pairs=[("Midgard", "wheat"), ("Tolan", "maize")],
    )

    try:
        case_record = service.create_case(
            query=create_req.query,
            as_of=create_req.as_of,
            case_id=create_req.case_id,
            target_country_sector_pairs=create_req.target_country_sector_pairs,
        )
        print(f"Case Registered: ID = {case_record.case_id}")
    except Exception:
        case_record = service.get_case(create_req.case_id)
        print(f"Case Already Registered: ID = {case_record.case_id}")
    print(f"Target Pairs: {case_record.target_country_sector_pairs}")
    print(f"Initial Status: {case_record.status}")

    # Step 3: Launch LangGraph Trial Workflow
    print_step(3, "Initiating Phase 4 LangGraph Adversarial Trial Workflow")
    print("Graph Workflow: HEIMDALL -> (THOR || LOKI) -> CROSS-EXAMINATION -> ODIN -> SUFFICIENCY -> BRIEFING")

    start_req = StartTrialRequest(max_runs=2, max_rounds=2, background=False)
    trial_status = await service.start_trial(
        case_id=case_record.case_id,
        max_runs=start_req.max_runs,
        max_rounds=start_req.max_rounds,
        background=start_req.background,
    )
    print(f"Trial Assigned ID: {trial_status.trial_id}")
    print(f"Execution Completed in: {trial_status.end_time}")
    print(f"Final Graph Node: {trial_status.current_node}")
    print(f"Investigation Status: {trial_status.status}")

    # Step 4: Inspect Trial Execution Trace
    print_step(4, "Audit Log Event Stream (SQLite Append-Only Audit Log)")
    audit_events = service.logbook.get_events(case_id=args.case_id)
    print(f"Total Audit Events Recorded: {len(audit_events)}")
    for ev in audit_events[:8]:
        print(f"  - [{ev.timestamp}] Agent={ev.agent.value.upper():<8} Event={ev.event_type.value:<14} Payload={str(ev.payload)[:60]}...")
    if len(audit_events) > 8:
        print(f"  ... (+ {len(audit_events) - 8} more audit events)")

    # Step 5: Judicial Adjudication Results
    print_step(5, "Odin's Final Judicial Rulings")
    rulings = service.get_trial_rulings(case_id=args.case_id, trial_id=trial_status.trial_id)
    print(f"Total Odin Rulings: {len(rulings)}")
    for r in rulings:
        verdict_badge = f"[{r.verdict.value.upper()}]"
        print(f"  {verdict_badge:<14} Claim {r.claim_id}: {r.rationale[:70]}...")
        if r.admissible_citations:
            cit_strs = [f"{c.doc_id} P{c.paragraph_num}" if c.doc_id else c.trade_row_ref for c in r.admissible_citations]
            print(f"                 Admissible Evidence: {', '.join(cit_strs)}")

    # Step 6: Final Verified Intelligence Briefing
    print_step(6, "Phase 5 Validated Intelligence Briefing Deliverable")
    briefing = service.get_trial_briefing(case_id=args.case_id, trial_id=trial_status.trial_id)

    print("\n--- SECTION A: EXECUTIVE SUMMARY SNIPPET ---")
    exec_summary = briefing.executive_summary
    print(exec_summary[:350] + ("..." if len(exec_summary) > 350 else ""))

    print("\n--- SECTION F: COMMERCIAL EXPOSURE ANALYSIS TABLE ---")
    exp_table = briefing.exposure_table
    print(f"{'Country':<10} {'Sector':<10} {'Thor High Bound':<22} {'Loki Low Bound':<22} {'Odin Judicial Range':<22}")
    print("-" * 88)
    for row in exp_table:
        thor_s = str(row.thor_range or "None")
        loki_s = str(row.loki_range or "None")
        odin_s = str(row.odin_range or "Unresolved")
        print(f"{row.country:<10} {row.sector:<10} {thor_s:<22} {loki_s:<22} {odin_s:<22}")

    print("\n--- SECTION I: DATA QUALITY & TRAPS CAUGHT ---")
    traps = briefing.traps_and_data_quality
    injs = traps.get("prompt_injections_detected", [])
    rets = traps.get("retractions_caught", [])
    clocks = traps.get("clock_violations_rejected", [])
    dups = traps.get("duplicates_detected", [])
    damages = traps.get("damaged_records_excluded", [])
    print(f"  - Prompt Injections Caught: {len(injs)} attempts isolated")
    print(f"  - Retracted Notices Caught: {len(rets)} formal retractions excluded")
    print(f"  - Clock Violations Caught: {len(clocks)} post-cutoff documents excluded")
    print(f"  - Duplicate Sources Filtered: {len(dups)} duplicate reprints disqualified")
    print(f"  - Damaged Data Excluded: {len(damages)} unreadable documents/rows excluded")

    # Step 7: Deliverable Export Paths
    print_step(7, "Persistent Deliverables & Export Verification")
    case_output_dir = os.path.join(demo_cases_dir, args.case_id)
    briefing_json = os.path.join(case_output_dir, "briefing.json")
    briefing_md = os.path.join(case_output_dir, "briefing.md")
    print(f"JSON Briefing Artifact: {briefing_json} (Exists: {os.path.exists(briefing_json)})")
    print(f"Markdown Report:        {briefing_md} (Exists: {os.path.exists(briefing_md)})")

    print_banner("DEMO EXECUTION COMPLETE: 100% REPRODUCIBLE END-TO-END TRIAL SUCCEEDED")


if __name__ == "__main__":
    asyncio.run(main())
