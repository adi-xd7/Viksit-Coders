"""Comprehensive unit and integration tests for Phase 5: Odin Briefing Generator.

Tests all 18 mandatory scenarios:
1. Ordinary case containing established, contested, conceded, and rejected rulings.
2. Case with multiple countries and sectors.
3. Case with no exposure data.
4. Case where one advocate failed and the other returned a valid position.
5. Case where both advocates failed or produced no usable exposure estimate.
6. Missing and malformed citations.
7. A citation referencing a nonexistent document.
8. A citation referencing a nonexistent paragraph.
9. An ineligible source published after the as-of date.
10. An evidence paragraph that does not support the associated claim (quote mismatch & zero topic overlap).
11. An event classified as not_real.
12. An event classified as uncertain.
13. A trial stopped by a run or resource limit.
14. A trial awaiting research or send-back.
15. A briefing containing only final Odin rulings, with no unsupported claims copied from advocacy text.
16. An empty or minimal case.
17. A repeated call or graph replay that does not corrupt or duplicate persisted results.
18. A regression test confirming existing Phase 1-4 behavior still passes.
"""

import json
import os
import pytest
from typing import Dict, List

from backend.models import (
    AgentRole,
    Attack,
    Basis,
    Briefing,
    CaseFile,
    Citation,
    Claim,
    Concession,
    Defense,
    DocMeta,
    Document,
    EventVerificationStatus,
    ExposureRange,
    Ruling,
    SufficiencyResult,
    SufficiencyStatus,
    TradeRow,
    Verdict,
)
from backend.briefing import (
    BriefingGenerator,
    generate_briefing,
    parse_citation,
    validate_citation_provenance,
    validate_citation_str,
)
from backend.trial import TrialGraphBuilder, run_trial
from backend.llm import LLMClient
from backend.logbook import LogBook
from backend.memory import MemoryStore


@pytest.fixture
def sample_doc_store() -> Dict[str, Document]:
    return {
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
                1: "Midgard wheat corridor transit was suspended following structural damage to the main canal lock.",
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
                SOURCE_NAME="Agricultural Trade Weekly",
            ),
            paragraphs={
                1: "Secondary railway lines can absorb approximately 15% of the stranded grain shipments.",
                2: "Shippers report rising demurrage fees across Baltic ports.",
            },
        ),
        "ATL-0003-LATE": Document(
            meta=DocMeta(
                DOC_ID="ATL-0003-LATE",
                PUB_DATE="2027-02-05",  # Published after cutoff 2027-01-25
                RELIABILITY=1,
                COUNTRY="Midgard",
                SECTOR="wheat",
            ),
            paragraphs={
                1: "Post-cutoff inspection report dated February 2027.",
            },
        ),
        "ATL-0004-RETRACTED": Document(
            meta=DocMeta(
                DOC_ID="ATL-0004-RETRACTED",
                PUB_DATE="2027-01-14",
                RELIABILITY=3,
            ),
            paragraphs={
                1: "Unverified rumor of total canal collapse.",
            },
            is_retracted=True,
        ),
    }


@pytest.fixture
def sample_trade_store() -> Dict[str, List[TradeRow]]:
    return {
        "TAB-WHEAT": [
            TradeRow(
                table_id="TAB-WHEAT",
                row_num=1,
                country_pair="Midgard-Asgard",
                sector="wheat",
                month="2026-11",
                volume=100.0,
                unit="k_tons",
            ),
            TradeRow(
                table_id="TAB-WHEAT",
                row_num=2,
                country_pair="Midgard-Asgard",
                sector="wheat",
                month="2026-12",
                volume=110.0,
                unit="k_tons",
            ),
            TradeRow(
                table_id="TAB-WHEAT",
                row_num=3,
                country_pair="Midgard-Asgard",
                sector="wheat",
                month="2027-01",
                volume=60.0,
                unit="k_tons",
            ),
        ]
    }


# =====================================================================
# Test 1: Ordinary Case (Established, Contested, Conceded, Rejected)
# =====================================================================
def test_scenario_01_ordinary_case_all_verdicts(sample_doc_store, sample_trade_store):
    """Ordinary case containing established, contested, conceded, and rejected rulings."""
    cf = CaseFile(
        case_id="CASE-FULL-01",
        query="Disruption to Midgard wheat corridor",
        as_of="2027-01-25",
        verification_status=EventVerificationStatus.REAL,
    )

    claims = [
        Claim(
            claim_id="C-EST-1",
            agent=AgentRole.THOR,
            country="Midgard",
            sector="wheat",
            posture="high",
            statement="Canal lock damage reduced transit throughput by 45%.",
            citations=[Citation(doc_id="ATL-0001", paragraph_num=2)],
        ),
        Claim(
            claim_id="C-CON-1",
            agent=AgentRole.THOR,
            country="Midgard",
            sector="wheat",
            posture="high",
            statement="Demurrage penalties will trigger catastrophic systemic defaults.",
            citations=[Citation(doc_id="ATL-0002", paragraph_num=2)],
        ),
        Claim(
            claim_id="C-CNC-1",
            agent=AgentRole.LOKI,
            country="Midgard",
            sector="wheat",
            posture="limited",
            statement="Alternative rail capacity exists for up to 15% offset.",
            citations=[Citation(doc_id="ATL-0002", paragraph_num=1)],
        ),
        Claim(
            claim_id="C-REJ-1",
            agent=AgentRole.THOR,
            country="Midgard",
            sector="wheat",
            posture="high",
            statement="Total canal collapse occurred.",
            citations=[Citation(doc_id="ATL-0004-RETRACTED", paragraph_num=1)],
        ),
    ]

    rulings = [
        Ruling(
            claim_id="C-EST-1",
            verdict=Verdict.ESTABLISHED,
            basis=Basis.SOURCED_FACT,
            rationale="Substantiated by Ministry of Transport Tier 1 report.",
            admissible_citations=[Citation(doc_id="ATL-0001", paragraph_num=2)],
        ),
        Ruling(
            claim_id="C-CON-1",
            verdict=Verdict.CONTESTED,
            basis=Basis.INFERENCE,
            rationale="Disputed: high demurrage noted, but catastrophic default assertion lacks corroboration.",
            admissible_citations=[Citation(doc_id="ATL-0002", paragraph_num=2)],
        ),
        Ruling(
            claim_id="C-CNC-1",
            verdict=Verdict.CONCEDED,
            basis=Basis.SOURCED_FACT,
            rationale="Conceded by Loki based on railway capacity records.",
            admissible_citations=[Citation(doc_id="ATL-0002", paragraph_num=1)],
        ),
        Ruling(
            claim_id="C-REJ-1",
            verdict=Verdict.REJECTED,
            basis=Basis.SOURCED_FACT,
            disqualified_reason="Cited document ATL-0004-RETRACTED was retracted.",
            rationale="Disqualified due to formal retraction.",
            inadmissible_citations=[Citation(doc_id="ATL-0004-RETRACTED", paragraph_num=1)],
        ),
    ]

    exposure_ranges = [
        ExposureRange(
            country="Midgard",
            sector="wheat",
            thor_range=(35.0, 50.0),
            loki_range=(10.0, 20.0),
            odin_range=(30.0, 45.0),
            status="adjudicated",
            rationale="Midgard wheat adjudicated range based on 45% gross disruption less 15% rail offset.",
            established_claim_ids=["C-EST-1"],
            contested_claim_ids=["C-CON-1"],
            conceded_claim_ids=["C-CNC-1"],
            rejected_claim_ids=["C-REJ-1"],
            trade_row_refs=["TAB-WHEAT#1", "TAB-WHEAT#2"],
            assumptions=["Baseline average monthly volume = 105 k_tons"],
        )
    ]

    concessions = [
        Concession(
            concession_id="CONC-1",
            agent=AgentRole.LOKI,
            claim_id="C-CNC-1",
            rationale="Conceded that railway line absorbs up to 15%.",
        )
    ]

    briefing = generate_briefing(
        case_file=cf,
        rulings=rulings,
        exposure_ranges=exposure_ranges,
        doc_store=sample_doc_store,
        trade_store=sample_trade_store,
        claims=claims,
        concessions=concessions,
        overall_status="ready_for_briefing",
    )

    # 1. Executive summary reflects counts and event
    assert "CASE-FULL-01" in briefing.executive_summary
    assert "4 binding rulings" in briefing.executive_summary
    assert "1 established, 1 contested, 1 conceded, 1 rejected" in briefing.executive_summary

    # 2. Sections populated
    assert len(briefing.established_findings) == 1
    assert briefing.established_findings[0]["claim_id"] == "C-EST-1"
    assert "[ATL-0001 P2, 2027-01-10]" in briefing.established_findings[0]["admissible_citations"]

    assert len(briefing.contested_findings) == 1
    assert briefing.contested_findings[0]["claim_id"] == "C-CON-1"

    assert len(briefing.conceded_claims) == 1
    assert briefing.conceded_claims[0]["claim_id"] == "C-CNC-1"
    assert briefing.conceded_claims[0]["conceded_by"] == "Loki"

    assert len(briefing.rejected_claims) == 1
    assert briefing.rejected_claims[0]["claim_id"] == "C-REJ-1"
    assert "retracted" in briefing.rejected_claims[0]["disqualified_reason"]

    # 3. Exposure table
    assert len(briefing.exposure_table) == 1
    assert briefing.exposure_table[0].odin_range == (30.0, 45.0)

    # 4. Markdown includes all sections
    md = briefing.markdown_content
    assert "## A. Executive Summary" in md
    assert "## B. Established Findings" in md
    assert "## C. Contested Findings" in md
    assert "## D. Conceded Findings" in md
    assert "## E. Rejected Findings" in md
    assert "## F. Exposure Analysis Table" in md
    assert "## G. Outlook and Implications" in md
    assert "## H. Verification & Execution Summary" in md
    assert "## I. Sources & Traps Caught" in md


# =====================================================================
# Test 2: Multiple Countries and Sectors
# =====================================================================
def test_scenario_02_multiple_countries_and_sectors(sample_doc_store):
    """Case with multiple countries and sectors properly preserved."""
    cf = CaseFile(
        case_id="CASE-MULTI-02",
        query="Global multi-regional disruption",
        as_of="2027-01-25",
        verification_status=EventVerificationStatus.REAL,
    )

    claims = [
        Claim(
            claim_id="C-MID-WHE",
            agent=AgentRole.THOR,
            country="Midgard",
            sector="wheat",
            posture="high",
            statement="Midgard wheat corridor halted.",
        ),
        Claim(
            claim_id="C-ASG-SEMI",
            agent=AgentRole.THOR,
            country="Asgard",
            sector="semiconductors",
            posture="high",
            statement="Asgard fab fab-out delay.",
        ),
        Claim(
            claim_id="C-VAN-FERT",
            agent=AgentRole.LOKI,
            country="Vanaheim",
            sector="fertilizer",
            posture="limited",
            statement="Vanaheim fertilizer alternative supply available.",
        ),
    ]

    rulings = [
        Ruling(claim_id="C-MID-WHE", verdict=Verdict.ESTABLISHED, basis=Basis.SOURCED_FACT, rationale="Midgard proven."),
        Ruling(claim_id="C-ASG-SEMI", verdict=Verdict.CONTESTED, basis=Basis.INFERENCE, rationale="Asgard contested."),
        Ruling(claim_id="C-VAN-FERT", verdict=Verdict.ESTABLISHED, basis=Basis.SOURCED_FACT, rationale="Vanaheim proven."),
    ]

    exposure_ranges = [
        ExposureRange(country="Midgard", sector="wheat", odin_range=(20.0, 30.0), status="adjudicated"),
        ExposureRange(country="Asgard", sector="semiconductors", odin_range=None, status="unresolved"),
        ExposureRange(country="Vanaheim", sector="fertilizer", odin_range=(5.0, 10.0), status="adjudicated"),
    ]

    briefing = generate_briefing(
        case_file=cf,
        rulings=rulings,
        exposure_ranges=exposure_ranges,
        doc_store=sample_doc_store,
        claims=claims,
    )

    pairs = [(er.country, er.sector) for er in briefing.exposure_table]
    assert ("Midgard", "wheat") in pairs
    assert ("Asgard", "semiconductors") in pairs
    assert ("Vanaheim", "fertilizer") in pairs
    assert len(briefing.exposure_table) == 3


# =====================================================================
# Test 3: No Exposure Data
# =====================================================================
def test_scenario_03_no_exposure_data(sample_doc_store):
    """Case with no exposure data handles gracefully without LLM mental math."""
    cf = CaseFile(
        case_id="CASE-NO-EXP",
        query="Early investigation with zero quantitative trade data",
        as_of="2027-01-25",
        verification_status=EventVerificationStatus.REAL,
    )

    briefing = generate_briefing(
        case_file=cf,
        rulings=[],
        exposure_ranges=[],
        doc_store=sample_doc_store,
    )

    assert briefing.exposure_table == []
    assert "| *(None)* | *(None)* | *(None)* | *(None)* | *(None)* | `UNRESOLVED` | *(None)* |" in briefing.markdown_content


# =====================================================================
# Test 4: One Advocate Failed, Other Succeeded
# =====================================================================
def test_scenario_04_one_advocate_failed(sample_doc_store):
    """Case where Thor failed and Loki returned valid position."""
    cf = CaseFile(case_id="CASE-THOR-FAIL", query="Query", as_of="2027-01-25", verification_status=EventVerificationStatus.REAL)

    er = ExposureRange(
        country="Midgard",
        sector="wheat",
        thor_range=(30.0, 50.0),  # Proposed before Thor crashed
        loki_range=(10.0, 15.0),
        odin_range=None,
        status="unresolved",
    )

    briefing = generate_briefing(
        case_file=cf,
        rulings=[],
        exposure_ranges=[er],
        doc_store=sample_doc_store,
        thor_failed=True,
        loki_failed=False,
    )

    table_er = briefing.exposure_table[0]
    # Thor range must be explicitly None, not fabricated as 0.0 or assumed
    assert table_er.thor_range is None
    assert table_er.loki_range == (10.0, 15.0)
    assert any("Thor advocate failed" in a for a in table_er.assumptions)
    assert briefing.verification_summary["advocate_status"]["thor"] == "failed"
    assert briefing.verification_summary["advocate_status"]["loki"] == "normal"


# =====================================================================
# Test 5: Both Advocates Failed
# =====================================================================
def test_scenario_05_both_advocates_failed(sample_doc_store):
    """Case where both advocates failed or produced no usable estimate."""
    cf = CaseFile(case_id="CASE-BOTH-FAIL", query="Query", as_of="2027-01-25", verification_status=EventVerificationStatus.REAL)

    er = ExposureRange(
        country="Midgard",
        sector="wheat",
        thor_range=None,
        loki_range=None,
        odin_range=None,
        status="unresolved",
    )

    briefing = generate_briefing(
        case_file=cf,
        rulings=[],
        exposure_ranges=[er],
        doc_store=sample_doc_store,
        thor_failed=True,
        loki_failed=True,
    )

    table_er = briefing.exposure_table[0]
    assert table_er.thor_range is None
    assert table_er.loki_range is None
    assert table_er.odin_range is None
    assert briefing.verification_summary["advocate_status"]["thor"] == "failed"
    assert briefing.verification_summary["advocate_status"]["loki"] == "failed"


# =====================================================================
# Test 6: Missing and Malformed Citations
# =====================================================================
def test_scenario_06_missing_and_malformed_citations(sample_doc_store, sample_trade_store):
    """Missing fields and malformed citation strings are caught and flagged."""
    # 1. Empty/malformed strings
    assert parse_citation("") is None
    assert parse_citation("   ") is None
    rep_malformed = validate_citation_str("NOT_A_VALID_CITATION_FORMAT", as_of="2027-01-25", doc_store=sample_doc_store)
    assert not rep_malformed.is_valid
    assert "Malformed citation format" in rep_malformed.failure_reasons[0]

    # 2. Malformed trade row reference
    cit_bad_trade = Citation(doc_id="", trade_row_ref="TAB-WHEAT#notanumber")
    rep_trade = validate_citation_provenance(cit_bad_trade, as_of="2027-01-25", doc_store=sample_doc_store, trade_store=sample_trade_store)
    assert not rep_trade.is_valid
    assert any("Malformed trade row reference" in r for r in rep_trade.failure_reasons)

    # 3. Missing paragraph in citation model
    cit_no_p = Citation(doc_id="ATL-0001", paragraph_num=None)
    rep_p = validate_citation_provenance(cit_no_p, as_of="2027-01-25", doc_store=sample_doc_store)
    assert not rep_p.is_valid
    assert any("missing a specific paragraph reference" in r for r in rep_p.failure_reasons)


# =====================================================================
# Test 7: Nonexistent Document Citation
# =====================================================================
def test_scenario_07_nonexistent_document_citation(sample_doc_store):
    """Citation referencing a nonexistent document fails validation."""
    cit = Citation(doc_id="NONEXISTENT-DOC-999", paragraph_num=1)
    rep = validate_citation_provenance(cit, as_of="2027-01-25", doc_store=sample_doc_store)

    assert not rep.is_valid
    assert any("does not exist in evidence store" in r for r in rep.failure_reasons)


# =====================================================================
# Test 8: Nonexistent Paragraph Citation
# =====================================================================
def test_scenario_08_nonexistent_paragraph_citation(sample_doc_store):
    """Citation referencing a nonexistent paragraph in an existing document fails."""
    cit = Citation(doc_id="ATL-0001", paragraph_num=99)  # ATL-0001 only has P1, P2
    rep = validate_citation_provenance(cit, as_of="2027-01-25", doc_store=sample_doc_store)

    assert not rep.is_valid
    assert any("Paragraph P99 does not exist" in r for r in rep.failure_reasons)


# =====================================================================
# Test 9: Ineligible Source Published After As-of Date (Clock Violation)
# =====================================================================
def test_scenario_09_ineligible_late_source_clock_violation(sample_doc_store):
    """Source published after as-of date fails clock constraint."""
    cit = Citation(doc_id="ATL-0003-LATE", paragraph_num=1)  # Published 2027-02-05
    rep = validate_citation_provenance(cit, as_of="2027-01-25", doc_store=sample_doc_store)

    assert not rep.is_valid
    assert any("Clock violation" in r for r in rep.failure_reasons)


# =====================================================================
# Test 10: Evidence Paragraph Does Not Support Associated Claim
# =====================================================================
def test_scenario_10_evidence_paragraph_does_not_support_claim(sample_doc_store):
    """Paragraph that does not support the claim (quote mismatch or zero topic overlap) is flagged."""
    # 1. Quote mismatch
    cit_quote_mismatch = Citation(
        doc_id="ATL-0001",
        paragraph_num=1,
        quoted_text="fabricated quote not present in paragraph text",
    )
    rep_quote = validate_citation_provenance(cit_quote_mismatch, as_of="2027-01-25", doc_store=sample_doc_store)
    assert not rep_quote.is_valid
    assert any("Quoted excerpt not found" in r for r in rep_quote.failure_reasons)

    # 2. Topic/entity mismatch with claim
    claim_unrelated = Claim(
        claim_id="C-UNRELATED",
        agent=AgentRole.THOR,
        country="Midgard",
        sector="fertilizer",
        posture="high",
        statement="Severe fertilizer shortage across eastern hemisphere factories.",
    )
    # ATL-0001 P1 discusses wheat canal lock damage, zero fertilizer/factory overlap
    cit_topic_mismatch = Citation(doc_id="ATL-0001", paragraph_num=1)
    rep_topic = validate_citation_provenance(
        cit_topic_mismatch,
        as_of="2027-01-25",
        doc_store=sample_doc_store,
        claim=claim_unrelated,
    )
    assert not rep_topic.is_valid
    assert any("lacks supporting content for claim" in r for r in rep_topic.failure_reasons)


# =====================================================================
# Test 11: Event Classified as Not Real
# =====================================================================
def test_scenario_11_event_classified_as_not_real(sample_doc_store):
    """Event verified as not_real results in counterfeit notice and zero net exposure."""
    cf = CaseFile(
        case_id="CASE-DECOY-01",
        query="Rumored transit strike in Midgard",
        as_of="2027-01-25",
        verification_status=EventVerificationStatus.NOT_REAL,
        verification_reason="Official port authority confirmed strike notice was a hoax.",
    )

    briefing = generate_briefing(
        case_file=cf,
        rulings=[],
        exposure_ranges=[],
        doc_store=sample_doc_store,
        overall_status="event_not_real",
    )

    assert "EVENT NOT REAL / COUNTERFEIT NOTICE" in briefing.executive_summary
    assert "No actual commercial trade disruption occurred" in briefing.executive_summary
    assert "Zero net exposure across all examined country-sector pairs" in briefing.executive_summary
    assert briefing.event_verification["status"] == "not_real"


# =====================================================================
# Test 12: Event Classified as Uncertain
# =====================================================================
def test_scenario_12_event_classified_as_uncertain(sample_doc_store):
    """Event classified as uncertain explicitly communicates provisional status."""
    cf = CaseFile(
        case_id="CASE-UNCERTAIN-01",
        query="Unconfirmed seismic event in Vanaheim",
        as_of="2027-01-25",
        verification_status=EventVerificationStatus.UNCERTAIN,
        verification_reason="Awaiting satellite damage assessment verification.",
    )

    ruling = Ruling(
        claim_id="C-UNC-1",
        verdict=Verdict.ESTABLISHED,
        basis=Basis.INFERENCE,
        rationale="Preliminary inference pending satellite verification.",
    )

    briefing = generate_briefing(
        case_file=cf,
        rulings=[ruling],
        exposure_ranges=[],
        doc_store=sample_doc_store,
        overall_status="ready_for_briefing",
    )

    assert "WARNING: Official verification of the disruption event remains UNCERTAIN" in briefing.executive_summary
    assert "provisional and contingent upon formal event confirmation" in briefing.executive_summary


# =====================================================================
# Test 13: Trial Stopped by Run or Resource Limit
# =====================================================================
def test_scenario_13_trial_stopped_by_limit(sample_doc_store):
    """Trial terminated due to budget/run limits clearly indicates incomplete investigation."""
    cf = CaseFile(case_id="CASE-LIMIT-01", query="Query", as_of="2027-01-25", verification_status=EventVerificationStatus.REAL)

    briefing = generate_briefing(
        case_file=cf,
        rulings=[],
        exposure_ranges=[],
        doc_store=sample_doc_store,
        overall_status="terminated_limits_exhausted",
        incomplete_reason="Trial run limit reached (3 of 3).",
        run_count=3,
        max_runs=3,
    )

    assert "The investigation was stopped due to execution/resource limits" in briefing.executive_summary
    assert "Trial run limit reached (3 of 3)" in briefing.executive_summary
    assert briefing.verification_summary["trial_completion_status"] == "terminated_limits_exhausted"


# =====================================================================
# Test 14: Trial Awaiting Research / Send-Back
# =====================================================================
def test_scenario_14_trial_awaiting_research(sample_doc_store):
    """Trial awaiting further research is not falsely reported as fully completed."""
    cf = CaseFile(case_id="CASE-RESEARCH-01", query="Query", as_of="2027-01-25", verification_status=EventVerificationStatus.REAL)

    briefing = generate_briefing(
        case_file=cf,
        rulings=[],
        exposure_ranges=[],
        doc_store=sample_doc_store,
        overall_status="send_back_loop",
        run_count=2,
        max_runs=3,
    )

    assert "The trial is awaiting further research from Heimdall (Send-Back Run 2)" in briefing.executive_summary
    assert briefing.verification_summary["trial_completion_status"] == "send_back_loop"


# =====================================================================
# Test 15: Briefing Derived Strictly From Odin's Final Rulings
# =====================================================================
def test_scenario_15_briefing_contains_only_odin_rulings(sample_doc_store):
    """Unadjudicated advocacy claims are never copied into the briefing findings."""
    cf = CaseFile(case_id="CASE-UNADJUDICATED", query="Query", as_of="2027-01-25", verification_status=EventVerificationStatus.REAL)

    # Thor submitted 5 claims
    claims = [
        Claim(claim_id="C-1", agent=AgentRole.THOR, country="Midgard", sector="wheat", posture="high", statement="Claim 1"),
        Claim(claim_id="C-2", agent=AgentRole.THOR, country="Midgard", sector="wheat", posture="high", statement="Claim 2"),
        Claim(claim_id="C-3", agent=AgentRole.THOR, country="Midgard", sector="wheat", posture="high", statement="Claim 3 (Unadjudicated)"),
        Claim(claim_id="C-4", agent=AgentRole.THOR, country="Midgard", sector="wheat", posture="high", statement="Claim 4 (Unadjudicated)"),
        Claim(claim_id="C-5", agent=AgentRole.THOR, country="Midgard", sector="wheat", posture="high", statement="Claim 5 (Unadjudicated)"),
    ]

    # Odin only ruled on C-1 and C-2
    rulings = [
        Ruling(claim_id="C-1", verdict=Verdict.ESTABLISHED, basis=Basis.SOURCED_FACT, rationale="Claim 1 established"),
        Ruling(claim_id="C-2", verdict=Verdict.REJECTED, basis=Basis.SOURCED_FACT, rationale="Claim 2 rejected"),
    ]

    briefing = generate_briefing(
        case_file=cf,
        rulings=rulings,
        exposure_ranges=[],
        doc_store=sample_doc_store,
        claims=claims,
    )

    all_reported_claim_ids = (
        [f["claim_id"] for f in briefing.established_findings]
        + [f["claim_id"] for f in briefing.contested_findings]
        + [f["claim_id"] for f in briefing.conceded_claims]
        + [f["claim_id"] for f in briefing.rejected_claims]
    )

    assert "C-1" in all_reported_claim_ids
    assert "C-2" in all_reported_claim_ids
    # Claims 3, 4, 5 must NOT appear in any findings section
    assert "C-3" not in all_reported_claim_ids
    assert "C-4" not in all_reported_claim_ids
    assert "C-5" not in all_reported_claim_ids


# =====================================================================
# Test 16: Empty or Minimal Case
# =====================================================================
def test_scenario_16_empty_or_minimal_case():
    """Minimal case with empty stores and zero rulings produces valid schema."""
    cf = CaseFile(case_id="CASE-MINIMAL", query="Minimal", as_of="2027-01-25")

    briefing = generate_briefing(
        case_file=cf,
        rulings=[],
        exposure_ranges=[],
        doc_store={},
    )

    assert isinstance(briefing, Briefing)
    assert briefing.case_id == "CASE-MINIMAL"
    assert briefing.established_findings == []
    assert briefing.contested_findings == []
    assert briefing.conceded_claims == []
    assert briefing.rejected_claims == []
    assert briefing.exposure_table == []
    assert briefing.sources == []
    assert len(briefing.markdown_content) > 50


# =====================================================================
# Test 17: Replay Idempotency / Persistence Preservation
# =====================================================================
def test_scenario_17_replay_idempotency_preservation(tmp_path, sample_doc_store):
    """Replaying node_briefing on state with existing briefing does not overwrite or corrupt."""
    output_dir = str(tmp_path / "cases")
    builder = TrialGraphBuilder(output_dir=output_dir)

    cf = CaseFile(case_id="CASE-REPLAY-01", query="Query", as_of="2027-01-25", verification_status=EventVerificationStatus.REAL)
    ruling = Ruling(claim_id="C-1", verdict=Verdict.ESTABLISHED, basis=Basis.SOURCED_FACT, rationale="Established")

    state_init = {
        "case_file": cf,
        "case_id": "CASE-REPLAY-01",
        "question": "Query",
        "as_of": "2027-01-25",
        "rulings": [ruling],
        "exposure_ranges": [],
        "doc_store": sample_doc_store,
        "overall_status": "ready_for_briefing",
    }

    # First pass: generates and persists
    update_1 = builder.node_briefing(state_init)
    persisted_path = update_1["persisted_briefing_path"]
    assert os.path.exists(persisted_path)
    initial_mtime = os.path.getmtime(persisted_path)

    # Second pass (replay): state includes existing briefing and path
    state_replay = dict(state_init)
    state_replay["briefing"] = update_1["briefing"]
    state_replay["persisted_briefing_path"] = persisted_path

    update_2 = builder.node_briefing(state_replay)
    second_mtime = os.path.getmtime(persisted_path)

    # Verifies reuse of existing persisted briefing without modification
    assert update_2["briefing"] is update_1["briefing"]
    assert initial_mtime == second_mtime


# =====================================================================
# Test 18: Regression Test (Full LangGraph Trial Workflow Execution)
# =====================================================================
@pytest.mark.asyncio
async def test_scenario_18_regression_full_workflow_end_to_end(tmp_path):
    """End-to-end regression confirming Phase 1-4 trial workflow produces briefing."""
    output_dir = str(tmp_path / "cases")
    logbook = LogBook(db_path=str(tmp_path / "audit.db"))
    memory_store = MemoryStore()
    llm = LLMClient()

    def mock_llm(sys: str, user: str, kwargs: dict) -> str:
        return json.dumps({
            "rulings": [
                {
                    "claim_id": "THOR-C1-MID-WHE",
                    "verdict": "established",
                    "basis": "sourced_fact",
                    "rationale": "Directly proven by corridor damage record.",
                },
                {
                    "claim_id": "LOKI-C1-MID-WHE",
                    "verdict": "contested",
                    "basis": "inference",
                    "rationale": "Alternative routing capacity remains contested.",
                },
            ]
        })

    llm.set_mock_handler(mock_llm)

    builder = TrialGraphBuilder(
        llm_client=llm,
        logbook=logbook,
        memory_store=memory_store,
        output_dir=output_dir,
    )

    final_state = await run_trial(
        question="How exposed is Midgard wheat as of 25 January 2027?",
        as_of="2027-01-25",
        max_runs=1,
        builder=builder,
    )

    assert "briefing" in final_state
    briefing = final_state["briefing"]
    assert isinstance(briefing, Briefing)
    assert briefing.case_id is not None
    assert final_state.get("persisted_briefing_path") is not None
    assert os.path.exists(final_state["persisted_briefing_path"])

    # Verify Markdown file was also persisted
    case_dir = os.path.dirname(final_state["persisted_briefing_path"])
    md_path = os.path.join(case_dir, "briefing.md")
    assert os.path.exists(md_path)
    with open(md_path, "r", encoding="utf-8") as f:
        md_text = f.read()
    assert "# TRIAL OF THE NINE REALMS — JUDICIAL INTELLIGENCE BRIEFING" in md_text
