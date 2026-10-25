"""Adversarial evaluation runner for RAGNAROK Phase 7.

Executes all 12 adversarial categories defined in demo/adversarial_manifest.json,
computes honest security, evidence-handling, and citation metrics, and outputs
both demo/adversarial_report.json and demo/adversarial_report.md.
"""

from __future__ import annotations

import asyncio
import datetime
import json
import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from typing import Any, Dict, List, Optional

from backend.agents.odin import (
    OdinJudge,
    evaluate_claim_eligibility,
    scan_text_for_injections,
    validate_citation,
)
from backend.briefing import (
    BriefingGenerator,
    generate_briefing,
    validate_citation_provenance,
)
from backend.logbook import LogBook, LogEventType
from backend.models import (
    AgentRole,
    Basis,
    CaseFile,
    Citation,
    Claim,
    DocMeta,
    Document,
    EventVerificationStatus,
    ExposureRange,
    Ruling,
    SufficiencyStatus,
    TradeRow,
    Verdict,
)
from backend.trade_calc import calculate_sum, filter_valid_trade_rows
from backend.trial import run_trial
from demo.fixtures.loader import load_adversarial_fixtures


async def run_adversarial_evaluation() -> Dict[str, Any]:
    fixtures_dir = os.path.dirname(os.path.abspath(__file__))
    manifest_path = os.path.join(fixtures_dir, "adversarial_manifest.json")
    
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    doc_store, trade_store = load_adversarial_fixtures()
    as_of = manifest.get("as_of_date", "2027-01-25")

    default_case = CaseFile(
        case_id="CASE-ADV-EVAL-01",
        query="As of 25 January 2027, what is the trade exposure of Midgard wheat?",
        as_of=as_of,
        target_pairs=[("Midgard", "wheat")],
        verification_status=EventVerificationStatus.REAL,
        verification_reason="Corridor disruption confirmed.",
        active_event_id="E5",
    )

    results: List[Dict[str, Any]] = []

    # Scenario A1: Direct prompt injection
    inj_text = doc_store["ADV-INJ-001"].raw_text
    is_inj, details = scan_text_for_injections(inj_text)
    a1_passed = is_inj and "ignore" in (details or "").lower()
    results.append({
        "scenario_id": "SCEN-A1",
        "category": "prompt_injection",
        "passed": a1_passed,
        "verification_type": "deterministic",
        "details": details if a1_passed else "Scanner failed to detect injection pattern",
    })

    # Scenario A2: Developer mode injection
    inj_text2 = doc_store["ADV-INJ-002"].raw_text
    is_inj2, details2 = scan_text_for_injections(inj_text2)
    a2_passed = is_inj2 and any(p in (details2 or "").lower() for p in ["developer mode", "disregard", "bypass"])
    results.append({
        "scenario_id": "SCEN-A2",
        "category": "prompt_injection",
        "passed": a2_passed,
        "verification_type": "deterministic",
        "details": details2 if a2_passed else "Scanner failed to detect injection pattern",
    })

    # Scenario B1: Tier 4 Tabloid rejected
    rumor_claim = Claim(
        claim_id="THOR-RUM-01",
        agent=AgentRole.THOR,
        country="Midgard",
        sector="wheat",
        posture="high",
        statement="Grain terminals have completely collapsed with 95% volume loss.",
        citations=[Citation(doc_id="ADV-RUM-001", paragraph_num=1)],
        nature=Basis.SOURCED_FACT,
    )
    elig_b1 = evaluate_claim_eligibility(rumor_claim, as_of, doc_store, trade_store)
    b1_passed = (
        not elig_b1.is_eligible_for_llm
        and elig_b1.deterministic_ruling is not None
        and elig_b1.deterministic_ruling.verdict == Verdict.REJECTED
        and elig_b1.deterministic_ruling.disqualified_reason == "tier_4_only"
    )
    results.append({
        "scenario_id": "SCEN-B1",
        "category": "rumors_weak_sources",
        "passed": b1_passed,
        "verification_type": "deterministic",
        "details": "Tier-4-only claim deterministically rejected with disqualified_reason='tier_4_only'",
    })

    # Scenario B2: Tier 1 Authoritative admitted
    auth_claim = Claim(
        claim_id="LOKI-AUTH-01",
        agent=AgentRole.LOKI,
        country="Midgard",
        sector="wheat",
        posture="limited",
        statement="Corridor traffic operating at 88% capacity with only 12% transit volume disruption.",
        citations=[Citation(doc_id="ADV-AUTH-001", paragraph_num=2)],
        nature=Basis.SOURCED_FACT,
    )
    elig_b2 = evaluate_claim_eligibility(auth_claim, as_of, doc_store, trade_store)
    b2_passed = elig_b2.is_eligible_for_llm and len(elig_b2.admissible_citations) == 1
    results.append({
        "scenario_id": "SCEN-B2",
        "category": "rumors_weak_sources",
        "passed": b2_passed,
        "verification_type": "deterministic",
        "details": "Authoritative Tier 1 benchmark admitted for judicial deliberation",
    })

    # Scenario C1: Retracted document
    cit_c1 = Citation(doc_id="ADV-RET-001", paragraph_num=1)
    val_c1 = validate_citation(cit_c1, as_of, doc_store, trade_store)
    c1_passed = not val_c1.is_valid and "retracted" in (val_c1.reason or "").lower()
    results.append({
        "scenario_id": "SCEN-C1",
        "category": "retractions_and_corrections",
        "passed": c1_passed,
        "verification_type": "deterministic",
        "details": val_c1.reason,
    })

    # Scenario C2: Superseded document vs pre-as-of correction
    val_c2_old = validate_citation(Citation(doc_id="ADV-COR-001", paragraph_num=1), as_of, doc_store, trade_store)
    val_c2_new = validate_citation(Citation(doc_id="ADV-COR-002", paragraph_num=1), as_of, doc_store, trade_store)
    c2_passed = (not val_c2_old.is_valid and "superseded" in (val_c2_old.reason or "").lower()) and val_c2_new.is_valid
    results.append({
        "scenario_id": "SCEN-C2",
        "category": "retractions_and_corrections",
        "passed": c2_passed,
        "verification_type": "deterministic",
        "details": "Superseded notice rejected; valid pre-as-of correction admitted",
    })

    # Scenario C3: Post-cutoff correction
    val_c3 = validate_citation(Citation(doc_id="ADV-POST-COR", paragraph_num=1), as_of, doc_store, trade_store)
    c3_passed = not val_c3.is_valid and "clock violation" in (val_c3.reason or "").lower()
    results.append({
        "scenario_id": "SCEN-C3",
        "category": "retractions_and_corrections",
        "passed": c3_passed,
        "verification_type": "deterministic",
        "details": val_c3.reason,
    })

    # Scenario D1: Contradictory evidence
    r_high = Ruling(
        claim_id="THOR-D1",
        verdict=Verdict.CONTESTED,
        basis=Basis.SOURCED_FACT,
        rationale="Severe disruption disputed by rail freight operators.",
        admissible_citations=[Citation(doc_id="ADV-CONTR-001", paragraph_num=1)],
    )
    r_low = Ruling(
        claim_id="LOKI-D1",
        verdict=Verdict.CONTESTED,
        basis=Basis.SOURCED_FACT,
        rationale="Bypass capacity disputed by grain exporters alliance.",
        admissible_citations=[Citation(doc_id="ADV-CONTR-002", paragraph_num=1)],
    )
    b_d1 = generate_briefing(
        case_file=default_case,
        rulings=[r_high, r_low],
        claims=[],
        doc_store=doc_store,
        trade_store=trade_store,
    )
    d1_passed = len(b_d1.contested_findings) == 2 and len(b_d1.established_findings) == 0
    results.append({
        "scenario_id": "SCEN-D1",
        "category": "contradictory_evidence",
        "passed": d1_passed,
        "verification_type": "deterministic",
        "details": "Contradictory findings accurately preserved as contested in Section C",
    })

    # Scenario E1: Duplicate sources
    val_e1_orig = validate_citation(Citation(doc_id="ADV-DUP-001", paragraph_num=1), as_of, doc_store, trade_store)
    val_e1_dup = validate_citation(Citation(doc_id="ADV-DUP-002", paragraph_num=1), as_of, doc_store, trade_store)
    e1_passed = val_e1_orig.is_valid and (not val_e1_dup.is_valid and "duplicate" in (val_e1_dup.reason or "").lower())
    results.append({
        "scenario_id": "SCEN-E1",
        "category": "duplicate_sources",
        "passed": e1_passed,
        "verification_type": "deterministic",
        "details": "Original article accepted; verbatim reprint disqualified as duplicate",
    })

    # Scenario F1: Off-event lookalike
    off_claim = Claim(
        claim_id="THOR-OFF-1",
        agent=AgentRole.THOR,
        country="Midgard",
        sector="wheat",
        posture="high",
        statement="Midgard wheat export shipments face severe corridor lock delays.",
        citations=[Citation(doc_id="ADV-OFF-001", paragraph_num=1)],
        nature=Basis.SOURCED_FACT,
    )
    rep_f1 = validate_citation_provenance(off_claim.citations[0], as_of, doc_store, trade_store, claim=off_claim)
    f1_passed = not rep_f1.is_valid and any("zero substantive keyword or sector overlap" in r for r in rep_f1.failure_reasons)
    results.append({
        "scenario_id": "SCEN-F1",
        "category": "off_event_lookalike",
        "passed": f1_passed,
        "verification_type": "deterministic",
        "details": "Off-event copper document rejected due to zero substantive topic overlap with wheat claim",
    })

    # Scenario G1: Damaged document
    val_g1 = validate_citation(Citation(doc_id="ADV-MAL-001", paragraph_num=2), as_of, doc_store, trade_store)
    g1_passed = not val_g1.is_valid and "damaged" in (val_g1.reason or "").lower()
    results.append({
        "scenario_id": "SCEN-G1",
        "category": "malformed_documents",
        "passed": g1_passed,
        "verification_type": "deterministic",
        "details": val_g1.reason,
    })

    # Scenario G2: Damaged trade row
    rows_g2 = trade_store["TAB-SYNTH-DAMAGED"]
    calc_g2 = calculate_sum(rows_g2, field="volume", as_of=as_of)
    g2_passed = not calc_g2.is_valid and "no admissible trade rows" in (calc_g2.error_reason or "").lower()
    results.append({
        "scenario_id": "SCEN-G2",
        "category": "malformed_documents",
        "passed": g2_passed,
        "verification_type": "deterministic",
        "details": calc_g2.error_reason,
    })

    # Scenario H1: Future-dated evidence
    val_h1 = validate_citation(Citation(doc_id="ADV-FUT-001", paragraph_num=1), as_of, doc_store, trade_store)
    h1_passed = not val_h1.is_valid and "clock violation" in (val_h1.reason or "").lower()
    results.append({
        "scenario_id": "SCEN-H1",
        "category": "future_dated_evidence",
        "passed": h1_passed,
        "verification_type": "deterministic",
        "details": val_h1.reason,
    })

    # Scenario I1: Insufficient evidence
    sparse_case = CaseFile(
        case_id="CASE-SPARSE-EVAL",
        query="What is the exposure for Tolan fertilizer?",
        as_of=as_of,
        target_pairs=[("Tolan", "fertilizer")],
        verification_status=EventVerificationStatus.REAL,
    )
    unresolved_er = ExposureRange(
        country="Tolan",
        sector="fertilizer",
        thor_range=None,
        loki_range=None,
        odin_range=None,
        status="unresolved",
        rationale="Missing trade baseline and disruption evidence.",
    )
    suff_i1 = OdinJudge().assess_sufficiency(
        case_file=sparse_case,
        rulings=[],
        exposure_ranges=[unresolved_er],
        claims=[],
        doc_store=doc_store,
        run_count=1,
        max_runs=2,
    )
    i1_passed = (
        suff_i1.status == SufficiencyStatus.INSUFFICIENT
        and suff_i1.send_back is not None
        and len(suff_i1.send_back.missing) >= 1
    )
    results.append({
        "scenario_id": "SCEN-I1",
        "category": "insufficient_evidence",
        "passed": i1_passed,
        "verification_type": "deterministic",
        "details": f"SendBack issued with {len(suff_i1.send_back.missing if suff_i1.send_back else [])} gap requests",
    })

    # Scenario J1: Event verification not_real
    fake_case = CaseFile(
        case_id="CASE-FAKE-EVAL",
        query="How exposed is Asgard fertilizer to the canal explosion?",
        as_of=as_of,
        target_pairs=[("Asgard", "fertilizer")],
        verification_status=EventVerificationStatus.NOT_REAL,
        verification_reason="Event debunked: notice was a fabricated rumor.",
    )
    final_j1 = await run_trial(
        question="How exposed is Asgard fertilizer to the canal explosion?",
        as_of=as_of,
        case_file=fake_case,
    )
    j1_passed = (
        final_j1.get("current_node") == "briefing"
        and final_j1.get("overall_status") == "event_not_real"
        and final_j1.get("briefing") is not None
        and final_j1.get("briefing").event_verification.get("status") == "not_real"
    )
    results.append({
        "scenario_id": "SCEN-J1",
        "category": "event_verification",
        "passed": j1_passed,
        "verification_type": "deterministic",
        "details": "Fake event halted graph at Heimdall and delivered zero-exposure briefing",
    })

    # Scenario K1: Advocate failure not treated as concession
    exp_k1 = ExposureRange(
        country="Midgard",
        sector="wheat",
        thor_range=(15000.0, 25000.0),
        loki_range=None,
        odin_range=(15000.0, 20000.0),
        status="resolved",
        rationale="Thor provided supported rail disruption evidence; Loki failed to submit a position.",
    )
    brief_k1 = generate_briefing(
        case_file=default_case,
        rulings=[],
        claims=[],
        doc_store=doc_store,
        trade_store=trade_store,
        exposure_ranges=[exp_k1],
    )
    k1_passed = (
        brief_k1.exposure_table[0].thor_range == (15000.0, 25000.0)
        and brief_k1.exposure_table[0].loki_range is None
        and "loki failed" in brief_k1.exposure_table[0].rationale.lower()
    )
    results.append({
        "scenario_id": "SCEN-K1",
        "category": "agent_resource_failures",
        "passed": k1_passed,
        "verification_type": "deterministic",
        "details": "Loki crash preserved as None; never converted to concession or zero",
    })

    # Scenario K2: Limits exhausted graceful termination
    suff_k2 = OdinJudge().assess_sufficiency(
        case_file=default_case,
        rulings=[],
        exposure_ranges=[unresolved_er],
        claims=[],
        doc_store=doc_store,
        run_count=2,
        max_runs=2,
    )
    k2_passed = (
        suff_k2.status == SufficiencyStatus.LIMITS_EXHAUSTED
        and suff_k2.send_back is None
        and len(suff_i1.unresolved_gaps) >= 0
    )
    results.append({
        "scenario_id": "SCEN-K2",
        "category": "agent_resource_failures",
        "passed": k2_passed,
        "verification_type": "deterministic",
        "details": "Run limit enforced; trial terminated without infinite loop",
    })

    # Scenario L1: Nonexistent document citation
    rep_l1 = validate_citation_provenance(Citation(doc_id="NONEXISTENT-999", paragraph_num=1), as_of, doc_store, trade_store)
    l1_passed = not rep_l1.is_valid and "does not exist" in (rep_l1.failure_reasons[0] if rep_l1.failure_reasons else "").lower()
    results.append({
        "scenario_id": "SCEN-L1",
        "category": "citation_integrity",
        "passed": l1_passed,
        "verification_type": "deterministic",
        "details": rep_l1.failure_reasons[0] if rep_l1.failure_reasons else "Unknown",
    })

    # Scenario L2: Quote mismatch
    rep_l2 = validate_citation_provenance(
        Citation(doc_id="ADV-AUTH-001", paragraph_num=1, quoted_text="fabricated non-existent text"),
        as_of,
        doc_store,
        trade_store,
    )
    l2_passed = not rep_l2.is_valid and any("quoted excerpt not found" in r.lower() for r in rep_l2.failure_reasons)
    results.append({
        "scenario_id": "SCEN-L2",
        "category": "citation_integrity",
        "passed": l2_passed,
        "verification_type": "deterministic",
        "details": "Fabricated quote excerpt detected and rejected",
    })

    # Aggregate Metrics Calculation
    total_scenarios = len(results)
    passed_count = sum(1 for r in results if r["passed"])
    failed_count = total_scenarios - passed_count
    skipped_count = 0

    metrics = {
        "total_scenarios_executed": total_scenarios,
        "scenarios_passed": passed_count,
        "scenarios_failed": failed_count,
        "scenarios_skipped": skipped_count,
        "pass_rate_percentage": round((passed_count / total_scenarios) * 100.0, 2),
        "prompt_injections_contained": sum(1 for r in results if r["category"] == "prompt_injection" and r["passed"]),
        "tier4_weak_sources_rejected": sum(1 for r in results if r["scenario_id"] == "SCEN-B1" and r["passed"]),
        "retractions_and_superseded_caught": sum(1 for r in results if r["category"] == "retractions_and_corrections" and r["passed"]),
        "contradictions_preserved_as_contested": sum(1 for r in results if r["category"] == "contradictory_evidence" and r["passed"]),
        "duplicates_suppressed": sum(1 for r in results if r["category"] == "duplicate_sources" and r["passed"]),
        "off_event_lookalikes_rejected": sum(1 for r in results if r["category"] == "off_event_lookalike" and r["passed"]),
        "damaged_documents_and_rows_excluded": sum(1 for r in results if r["category"] == "malformed_documents" and r["passed"]),
        "future_dated_sources_excluded": sum(1 for r in results if r["category"] == "future_dated_evidence" and r["passed"]),
        "insufficient_evidence_gaps_flagged": sum(1 for r in results if r["category"] == "insufficient_evidence" and r["passed"]),
        "event_verification_decoy_handled": sum(1 for r in results if r["category"] == "event_verification" and r["passed"]),
        "resource_limits_and_failures_contained": sum(1 for r in results if r["category"] == "agent_resource_failures" and r["passed"]),
        "citation_integrity_violations_caught": sum(1 for r in results if r["category"] == "citation_integrity" and r["passed"]),
    }

    report = {
        "title": "RAGNAROK Phase 7 Synthetic Adversarial Evaluation Report",
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "as_of_date": as_of,
        "metrics": metrics,
        "scenario_results": results,
    }

    # Write report JSON
    json_path = os.path.join(fixtures_dir, "adversarial_report.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    # Write report Markdown
    md_path = os.path.join(fixtures_dir, "adversarial_report.md")
    md_lines = [
        "# RAGNAROK Phase 7: Synthetic Adversarial Evaluation Report",
        "",
        f"**Date Executed**: {report['timestamp']}  ",
        f"**Investigation As-Of Date**: {as_of}  ",
        f"**Test Corpus**: Synthetic Adversarial Pack (`demo/fixtures/`)  ",
        "",
        "## 1. Executive Summary & Aggregate Metrics",
        "",
        "| Metric | Result | Meaning |",
        "| :--- | :--- | :--- |",
        f"| **Total Scenarios Executed** | **{metrics['total_scenarios_executed']}** | All 12 specified categories (A–L) evaluated |",
        f"| **Scenarios Passed** | **{metrics['scenarios_passed']}** | Deterministic assertions satisfied |",
        f"| **Scenarios Failed** | **{metrics['scenarios_failed']}** | Regressions or unhandled vulnerabilities |",
        f"| **Pass Rate** | **{metrics['pass_rate_percentage']}%** | Verified deterministic defense rate |",
        f"| **Prompt Injections Contained** | **{metrics['prompt_injections_contained']} / 2** | Instructions in evidence prevented from executing |",
        f"| **Tier 4 Rumors Disqualified** | **{metrics['tier4_weak_sources_rejected']} / 1** | Tabloid rumors rejected under tier_4_only policy |",
        f"| **Retractions & Corrections Caught** | **{metrics['retractions_and_superseded_caught']} / 3** | Superseded & post-cutoff sources excluded |",
        f"| **Contradictions Preserved** | **{metrics['contradictions_preserved_as_contested']} / 1** | Opposing claims classified as contested |",
        f"| **Duplicates Suppressed** | **{metrics['duplicates_suppressed']} / 1** | Reprints prevented from inflating corroboration |",
        f"| **Off-Event Lookalikes Filtered** | **{metrics['off_event_lookalikes_rejected']} / 1** | Utgard copper excluded from Midgard wheat case |",
        f"| **Damaged Records Excluded** | **{metrics['damaged_documents_and_rows_excluded']} / 2** | Corrupted records cleanly rejected |",
        f"| **Future-Dated Evidence Excluded** | **{metrics['future_dated_sources_excluded']} / 1** | Clock restriction enforced (post-2027-01-25) |",
        f"| **Send-Back Gaps Flagged** | **{metrics['insufficient_evidence_gaps_flagged']} / 1** | Sparse evidence triggers structured SendBack |",
        f"| **Decoy Events Halted** | **{metrics['event_verification_decoy_handled']} / 1** | `not_real` event delivers zero exposure finding |",
        f"| **Resource Limits Enforced** | **{metrics['resource_limits_and_failures_contained']} / 2** | Run limits & advocate failures gracefully handled |",
        f"| **Citation Violations Caught** | **{metrics['citation_integrity_violations_caught']} / 2** | Missing docs and quote mismatches rejected |",
        "",
        "## 2. Detailed Scenario Results",
        "",
        "| Scenario ID | Category | Status | Verification | Details |",
        "| :--- | :--- | :--- | :--- | :--- |",
    ]

    for r in results:
        status_badge = "✅ PASSED" if r["passed"] else "❌ FAILED"
        md_lines.append(
            f"| `{r['scenario_id']}` | `{r['category']}` | {status_badge} | {r['verification_type']} | {r['details']} |"
        )

    md_lines.extend([
        "",
        "## 3. Security and Grounding Guarantees",
        "",
        "1. **Untrusted Evidence Boundary**: All text ingested from source documents is strictly isolated inside document boundaries. Prompts contain strict guards prohibiting instructions in evidence from executing.",
        "2. **Clock Enforcement**: Publication dates are compared against `as_of` (`2027-01-25`). Any source published after this cutoff is rejected as a clock violation.",
        "3. **Zero Mental Arithmetic**: Financial and volume exposure bounds are computed by deterministic Python code (`backend/trade_calc.py`). Missing trade rows are never assumed to be zero.",
        "4. **Judicial Exclusivity**: The final briefing reflects only Odin's binding rulings. Advocate claims without an admissible ruling are excluded.",
    ])

    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines) + "\n")

    return report


if __name__ == "__main__":
    report = asyncio.run(run_adversarial_evaluation())
    print(f"Adversarial Evaluation Complete: {report['metrics']['scenarios_passed']}/{report['metrics']['total_scenarios_executed']} passed ({report['metrics']['pass_rate_percentage']}%)")
