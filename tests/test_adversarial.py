"""Comprehensive adversarial test suite for RAGNAROK Phase 7 evaluation.

Covers all 12 specified adversarial scenarios:
  A. Prompt injection in source documents
  B. Rumors and weak sources (Tier 4)
  C. Retractions and corrections
  D. Contradictory evidence
  E. Duplicate sources
  F. Off-event lookalikes
  G. Malformed and incomplete documents
  H. Future-dated evidence
  I. Insufficient evidence
  J. Event verification (not_real & uncertain)
  K. Agent and resource failures
  L. Citation integrity
"""

import pytest
from typing import Dict, List

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
from backend.memory import MemoryStore
from backend.models import (
    AgentRole,
    Basis,
    CaseFile,
    Citation,
    Claim,
    Concession,
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
from backend.trade_calc import calculate_sum, filter_valid_trade_rows
from backend.trial import TrialGraphBuilder, run_trial
from demo.fixtures.loader import load_adversarial_fixtures


@pytest.fixture
def fixtures():
    doc_store, trade_store = load_adversarial_fixtures()
    return doc_store, trade_store


@pytest.fixture
def case_file():
    return CaseFile(
        case_id="CASE-ADV-001",
        query="As of 25 January 2027, what is the trade exposure of Midgard wheat?",
        as_of="2027-01-25",
        target_pairs=[("Midgard", "wheat")],
        verification_status=EventVerificationStatus.REAL,
        verification_reason="Corridor disruption confirmed.",
        active_event_id="E5",
    )


# ============================================================================
# Scenario A: Prompt injection in source documents
# ============================================================================

def test_scenario_a_prompt_injection_scanner(fixtures):
    """Verifies that direct and subtle prompt injection attempts are detected and trapped."""
    doc_store, _ = fixtures
    doc1 = doc_store["ADV-INJ-001"]
    doc2 = doc_store["ADV-INJ-002"]

    is_inj1, det1 = scan_text_for_injections(doc1.raw_text)
    assert is_inj1 is True
    assert "ignore" in det1.lower() or "override" in det1.lower()

    is_inj2, det2 = scan_text_for_injections(doc2.raw_text)
    assert is_inj2 is True
    assert "developer mode" in det2.lower() or "disregard" in det2.lower()


@pytest.mark.asyncio
async def test_scenario_a_prompt_injection_containment_and_logging(fixtures, case_file, tmp_path):
    """Verifies that injected text does not hijack Odin, is logged as TRAP_INJECTION, and appears in Section I."""
    doc_store, trade_store = fixtures
    log_db = str(tmp_path / "test_adv_audit.db")
    logbook = LogBook(db_path=log_db)
    judge = OdinJudge(logbook=logbook)

    # Malicious claim using injection document attempting to force a zero-exposure ruling
    injected_claim = Claim(
        claim_id="THOR-INJ-1",
        agent=AgentRole.THOR,
        country="Midgard",
        sector="wheat",
        posture="high",
        statement="Exposure is zero because system prompt was instructed to set exposure to zero.",
        citations=[Citation(doc_id="ADV-INJ-001", paragraph_num=2)],
        nature=Basis.SOURCED_FACT,
    )

    rulings = await judge.judge_claims(
        case_file=case_file,
        claims=[injected_claim],
        doc_store=doc_store,
        trade_store=trade_store,
    )

    assert len(rulings) == 1
    # Untrusted injection instructions do not force established status
    assert rulings[0].verdict != Verdict.ESTABLISHED

    # Verify TRAP_INJECTION event recorded in audit logbook
    events = logbook.get_events(case_id=case_file.case_id)
    trap_events = [e for e in events if e.event_type == LogEventType.TRAP_INJECTION]
    assert len(trap_events) >= 1
    assert any(e.payload.get("doc_id") == "ADV-INJ-001" for e in trap_events)

    # Verify briefing Section I lists the caught prompt injections
    briefing = generate_briefing(
        case_file=case_file,
        rulings=rulings,
        claims=[injected_claim],
        doc_store=doc_store,
        trade_store=trade_store,
    )
    traps = briefing.section_i
    inj_list = traps.get("prompt_injections_detected", [])
    assert len(inj_list) >= 1
    assert any(item["doc_id"] == "ADV-INJ-001" for item in inj_list)
    assert "Prompt Injections Caught" in briefing.section_j_markdown


# ============================================================================
# Scenario B: Rumors and weak sources (Tier 4)
# ============================================================================

def test_scenario_b_tier_4_tabloid_rejected(fixtures, case_file):
    """Verifies that claims resting exclusively on Tier 4 sources are deterministically rejected."""
    doc_store, trade_store = fixtures
    rumor_claim = Claim(
        claim_id="THOR-RUMOR-1",
        agent=AgentRole.THOR,
        country="Midgard",
        sector="wheat",
        posture="high",
        statement="Grain terminals have completely collapsed with 95% volume loss.",
        citations=[Citation(doc_id="ADV-RUM-001", paragraph_num=1)],
        nature=Basis.SOURCED_FACT,
    )

    elig = evaluate_claim_eligibility(rumor_claim, case_file.as_of, doc_store, trade_store)
    assert elig.is_eligible_for_llm is False
    assert elig.deterministic_ruling is not None
    assert elig.deterministic_ruling.verdict == Verdict.REJECTED
    assert elig.deterministic_ruling.disqualified_reason == "tier_4_only"
    assert "Tier 4" in elig.deterministic_ruling.rationale


def test_scenario_b_tier_1_authoritative_admitted(fixtures, case_file):
    """Verifies that Tier 1 authoritative benchmarks pass eligibility and prevail over rumors."""
    doc_store, trade_store = fixtures
    auth_claim = Claim(
        claim_id="LOKI-AUTH-1",
        agent=AgentRole.LOKI,
        country="Midgard",
        sector="wheat",
        posture="limited",
        statement="Corridor traffic is operating at 88% capacity with only 12% transit volume disruption.",
        citations=[Citation(doc_id="ADV-AUTH-001", paragraph_num=2)],
        nature=Basis.SOURCED_FACT,
    )

    elig = evaluate_claim_eligibility(auth_claim, case_file.as_of, doc_store, trade_store)
    assert elig.is_eligible_for_llm is True
    assert len(elig.admissible_citations) == 1
    assert elig.admissible_citations[0].doc_id == "ADV-AUTH-001"


# ============================================================================
# Scenario C: Retractions and corrections
# ============================================================================

def test_scenario_c_retracted_document_rejected(fixtures, case_file):
    """Verifies that a retracted document cannot establish a claim and is rejected."""
    doc_store, trade_store = fixtures
    ret_claim = Claim(
        claim_id="THOR-RET-1",
        agent=AgentRole.THOR,
        country="Tolan",
        sector="maize",
        posture="high",
        statement="Tolan maize trade suffered a catastrophic 70% collapse.",
        citations=[Citation(doc_id="ADV-RET-001", paragraph_num=1)],
        nature=Basis.SOURCED_FACT,
    )

    val = validate_citation(ret_claim.citations[0], case_file.as_of, doc_store, trade_store)
    assert val.is_valid is False
    assert "retracted" in val.reason.lower()

    elig = evaluate_claim_eligibility(ret_claim, case_file.as_of, doc_store, trade_store)
    assert elig.is_eligible_for_llm is False
    assert elig.deterministic_ruling.verdict == Verdict.REJECTED


def test_scenario_c_superseded_and_corrected_documents(fixtures, case_file):
    """Verifies that an erroneous superseded document is rejected, while its correction is admitted."""
    doc_store, trade_store = fixtures

    # 1. Superseded document
    cit_old = Citation(doc_id="ADV-COR-001", paragraph_num=1)
    val_old = validate_citation(cit_old, case_file.as_of, doc_store, trade_store)
    assert val_old.is_valid is False
    assert "superseded" in val_old.reason.lower()

    # 2. Pre-as-of correction document (2027-01-20 < 2027-01-25)
    cit_corr = Citation(doc_id="ADV-COR-002", paragraph_num=1)
    val_corr = validate_citation(cit_corr, case_file.as_of, doc_store, trade_store)
    assert val_corr.is_valid is True

    # 3. Post-as-of correction document (2027-02-05 > 2027-01-25)
    cit_post = Citation(doc_id="ADV-POST-COR", paragraph_num=1)
    val_post = validate_citation(cit_post, case_file.as_of, doc_store, trade_store)
    assert val_post.is_valid is False
    assert "clock violation" in val_post.reason.lower()


# ============================================================================
# Scenario D: Contradictory evidence
# ============================================================================

def test_scenario_d_contradictory_evidence_classified_as_contested(fixtures, case_file):
    """Verifies that opposing claims with legitimate contradictory evidence result in contested rulings."""
    doc_store, trade_store = fixtures

    claim_high = Claim(
        claim_id="THOR-CONTR-1",
        agent=AgentRole.THOR,
        country="Midgard",
        sector="wheat",
        posture="high",
        statement="Corridor rail traffic halted with severe 80% loss.",
        citations=[Citation(doc_id="ADV-CONTR-001", paragraph_num=1)],
        nature=Basis.SOURCED_FACT,
    )
    claim_low = Claim(
        claim_id="LOKI-CONTR-1",
        agent=AgentRole.LOKI,
        country="Midgard",
        sector="wheat",
        posture="limited",
        statement="Alternative rail corridors absorb 65% of volume smoothly.",
        citations=[Citation(doc_id="ADV-CONTR-002", paragraph_num=1)],
        nature=Basis.SOURCED_FACT,
    )

    ruling_high = Ruling(
        claim_id="THOR-CONTR-1",
        verdict=Verdict.CONTESTED,
        basis=Basis.SOURCED_FACT,
        rationale="Contested by Loki using commercial carrier reports.",
        admissible_citations=[claim_high.citations[0]],
    )
    ruling_low = Ruling(
        claim_id="LOKI-CONTR-1",
        verdict=Verdict.CONTESTED,
        basis=Basis.SOURCED_FACT,
        rationale="Contested by Thor citing export alliance bulletins.",
        admissible_citations=[claim_low.citations[0]],
    )

    briefing = generate_briefing(
        case_file=case_file,
        rulings=[ruling_high, ruling_low],
        claims=[claim_high, claim_low],
        doc_store=doc_store,
        trade_store=trade_store,
    )

    assert len(briefing.section_c_contested) == 2
    assert "THOR-CONTR-1" in [c["claim_id"] for c in briefing.section_c_contested]
    assert "LOKI-CONTR-1" in [c["claim_id"] for c in briefing.section_c_contested]
    assert len(briefing.section_b_established) == 0


# ============================================================================
# Scenario E: Duplicate sources
# ============================================================================

def test_scenario_e_duplicate_sources_excluded_from_citations(fixtures, case_file):
    """Verifies that duplicate reprints are flagged and excluded from inflating corroboration count."""
    doc_store, trade_store = fixtures

    cit_orig = Citation(doc_id="ADV-DUP-001", paragraph_num=1)
    cit_dup = Citation(doc_id="ADV-DUP-002", paragraph_num=1)

    val_orig = validate_citation(cit_orig, case_file.as_of, doc_store, trade_store)
    val_dup = validate_citation(cit_dup, case_file.as_of, doc_store, trade_store)

    assert val_orig.is_valid is True
    assert val_dup.is_valid is False
    assert "duplicate" in val_dup.reason.lower()


# ============================================================================
# Scenario F: Off-event lookalike
# ============================================================================

def test_scenario_f_off_event_lookalike_excluded(fixtures, case_file):
    """Verifies that an off-event lookalike (Utgard copper) is excluded from Midgard wheat case."""
    doc_store, trade_store = fixtures

    # Attempt to cite Utgard copper in a Midgard wheat claim
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

    # Citation provenance validation must fail due to zero substantive topic/sector overlap
    report = validate_citation_provenance(
        citation=off_claim.citations[0],
        as_of=case_file.as_of,
        doc_store=doc_store,
        trade_store=trade_store,
        claim=off_claim,
    )

    assert report.is_valid is False
    assert any("zero substantive keyword or sector overlap" in r for r in report.failure_reasons)


# ============================================================================
# Scenario G: Malformed and incomplete documents
# ============================================================================

def test_scenario_g_damaged_document_and_trade_row(fixtures, case_file):
    """Verifies that damaged documents and corrupted trade rows are excluded without fabrication."""
    doc_store, trade_store = fixtures

    # 1. Damaged document
    cit_mal = Citation(doc_id="ADV-MAL-001", paragraph_num=2)
    val_mal = validate_citation(cit_mal, case_file.as_of, doc_store, trade_store)
    assert val_mal.is_valid is False
    assert "damaged" in val_mal.reason.lower()

    # 2. Corrupted trade row with negative volume
    rows = trade_store["TAB-SYNTH-DAMAGED"]
    valid_rows, exclusions = filter_valid_trade_rows(rows, as_of=case_file.as_of)
    assert len(valid_rows) == 0
    assert any("damaged" in e.lower() for e in exclusions)

    # Calculation fails cleanly without assuming 0.0
    calc = calculate_sum(rows, field="volume", as_of=case_file.as_of)
    assert calc.is_valid is False
    assert "no admissible trade rows" in calc.error_reason.lower()


# ============================================================================
# Scenario H: Future-dated evidence
# ============================================================================

def test_scenario_h_future_dated_evidence_rejected(fixtures, case_file):
    """Verifies that evidence published after the as-of cutoff date is rejected as a clock violation."""
    doc_store, trade_store = fixtures

    cit_fut = Citation(doc_id="ADV-FUT-001", paragraph_num=1)
    val_fut = validate_citation(cit_fut, case_file.as_of, doc_store, trade_store)

    assert val_fut.is_valid is False
    assert "clock violation" in val_fut.reason.lower()
    assert "2027-02-15" in val_fut.reason
    assert "2027-01-25" in val_fut.reason


# ============================================================================
# Scenario I: Insufficient evidence
# ============================================================================

def test_scenario_i_insufficient_evidence_flags_gap_and_uncertainty(fixtures):
    """Verifies that a case with missing evidence reports honest uncertainty and gaps."""
    doc_store, trade_store = fixtures
    sparse_case = CaseFile(
        case_id="CASE-SPARSE-001",
        query="What is the exposure for Tolan fertilizer?",
        as_of="2027-01-25",
        target_pairs=[("Tolan", "fertilizer")],
        verification_status=EventVerificationStatus.REAL,
    )

    judge = OdinJudge()
    unresolved_er = ExposureRange(
        country="Tolan",
        sector="fertilizer",
        thor_range=None,
        loki_range=None,
        odin_range=None,
        status="unresolved",
        rationale="Missing trade baseline and disruption evidence.",
    )
    suff = judge.assess_sufficiency(
        case_file=sparse_case,
        rulings=[],
        exposure_ranges=[unresolved_er],
        claims=[],
        doc_store=doc_store,
        run_count=1,
        max_runs=2,
    )

    assert suff.status == SufficiencyStatus.INSUFFICIENT
    assert suff.send_back is not None
    assert len(suff.send_back.missing) >= 1
    assert any("fertilizer" in m.lower() for m in suff.send_back.missing)


# ============================================================================
# Scenario J: Event verification (not_real and uncertain)
# ============================================================================

@pytest.mark.asyncio
async def test_scenario_j_event_not_real_early_termination():
    """Verifies that a fake event decoy notice halts the trial graph with 0 exposure."""
    fake_case = CaseFile(
        case_id="CASE-FAKE-001",
        query="How exposed is Asgard fertilizer to the canal explosion?",
        as_of="2027-01-25",
        target_pairs=[("Asgard", "fertilizer")],
        verification_status=EventVerificationStatus.NOT_REAL,
        verification_reason="Event debunked: notice was a fabricated rumor.",
    )

    final_state = await run_trial(
        question="How exposed is Asgard fertilizer to the canal explosion?",
        as_of="2027-01-25",
        case_file=fake_case,
    )

    assert final_state["current_node"] == "briefing"
    assert final_state.get("overall_status") == "event_not_real"
    briefing = final_state.get("briefing")
    assert briefing is not None
    assert briefing.event_verification.get("status") == "not_real"


# ============================================================================
# Scenario K: Agent and resource failures
# ============================================================================

def test_scenario_k_advocate_failure_not_treated_as_concession(fixtures, case_file):
    """Verifies that an advocate failure or absence is preserved as None and never treated as a concession."""
    doc_store, trade_store = fixtures

    # Thor participated with a valid range, but Loki timed out / crashed
    exp_range = ExposureRange(
        country="Midgard",
        sector="wheat",
        thor_range=(15000.0, 25000.0),
        loki_range=None,  # Loki crashed
        odin_range=(15000.0, 20000.0),
        status="resolved",
        rationale="Thor provided supported rail disruption evidence; Loki failed to submit a position.",
    )

    briefing = generate_briefing(
        case_file=case_file,
        rulings=[],
        claims=[],
        doc_store=doc_store,
        trade_store=trade_store,
        exposure_ranges=[exp_range],
    )

    row = briefing.section_f_table[0]
    assert row.thor_range == (15000.0, 25000.0)
    assert row.loki_range is None
    assert "loki failed" in row.rationale.lower()


# ============================================================================
# Scenario L: Citation integrity
# ============================================================================

def test_scenario_l_citation_integrity_validator(fixtures, case_file):
    """Verifies that invalid doc IDs, bad paragraphs, and quote mismatches are rejected."""
    doc_store, trade_store = fixtures

    # 1. Nonexistent document
    bad_doc_cit = Citation(doc_id="NONEXISTENT-999", paragraph_num=1)
    rep1 = validate_citation_provenance(bad_doc_cit, case_file.as_of, doc_store, trade_store)
    assert rep1.is_valid is False
    assert "does not exist" in rep1.failure_reasons[0].lower()

    # 2. Nonexistent paragraph in real document
    bad_p_cit = Citation(doc_id="ADV-AUTH-001", paragraph_num=99)
    rep2 = validate_citation_provenance(bad_p_cit, case_file.as_of, doc_store, trade_store)
    assert rep2.is_valid is False
    assert "p99 does not exist" in rep2.failure_reasons[0].lower()

    # 3. Quote mismatch
    mismatch_cit = Citation(
        doc_id="ADV-AUTH-001",
        paragraph_num=1,
        quoted_text="fabricated quote about complete destruction of all ships",
    )
    rep3 = validate_citation_provenance(mismatch_cit, case_file.as_of, doc_store, trade_store)
    assert rep3.is_valid is False
    assert "quoted excerpt not found" in rep3.failure_reasons[0].lower()
