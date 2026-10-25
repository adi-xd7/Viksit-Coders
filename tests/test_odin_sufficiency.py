"""Unit tests for Odin's exposure range derivation and sufficiency evaluation."""

import pytest
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
from backend.agents.odin import assess_sufficiency, derive_exposure_ranges


@pytest.fixture
def base_case():
    return CaseFile(
        case_id="CASE-SUF-01",
        query="Assess grain exposure for Midgard and Tolan",
        as_of="2027-01-25",
        target_pairs=[("Midgard", "wheat"), ("Tolan", "maize")],
        verification_status=EventVerificationStatus.REAL,
    )


@pytest.fixture
def sample_trade_store():
    return {
        "TAB-WHEAT": [
            TradeRow(
                table_id="TAB-WHEAT",
                row_num=1,
                country_pair="Midgard-Asgard",
                sector="wheat",
                month="2026-10",
                volume=200.0,
                unit="k_tons",
            ),
            TradeRow(
                table_id="TAB-WHEAT",
                row_num=2,
                country_pair="Midgard-Asgard",
                sector="wheat",
                month="2026-11",
                volume=300.0,
                unit="k_tons",
            ),
        ],
        "TAB-MAIZE": [
            TradeRow(
                table_id="TAB-MAIZE",
                row_num=1,
                country_pair="Tolan-Asgard",
                sector="maize",
                month="2026-10",
                volume=150.0,
                unit="k_tons",
            ),
            TradeRow(
                table_id="TAB-MAIZE",
                row_num=2,
                country_pair="Tolan-Asgard",
                sector="maize",
                month="2026-11",
                volume=150.0,
                unit="k_tons",
            ),
        ],
    }


def test_exposure_assessment_both_advocates_with_offsets(base_case, sample_trade_store):
    # Thor argues high exposure (40% - 60% drop)
    c_thor = Claim(
        claim_id="THOR-W1",
        agent=AgentRole.THOR,
        country="Midgard",
        sector="wheat",
        posture="high",
        statement="Orvan corridor closure cuts wheat transit by 40% to 60%.",
        estimate_low=40.0,
        estimate_high=60.0,
        unit="pct",
        citations=[Citation(doc_id="DOC-T1", paragraph_num=1)],
        nature=Basis.SOURCED_FACT,
    )

    # Loki argues limited exposure with substitute rail offset of 50 k_tons
    c_loki = Claim(
        claim_id="LOKI-W1",
        agent=AgentRole.LOKI,
        country="Midgard",
        sector="wheat",
        posture="limited",
        statement="Substitute rail routing provides 50 k_tons offset capacity.",
        estimate_low=50.0,
        estimate_high=50.0,
        unit="k_tons",
        citations=[Citation(doc_id="DOC-L1", paragraph_num=1)],
        nature=Basis.SOURCED_FACT,
    )

    r_thor = Ruling(
        claim_id="THOR-W1",
        verdict=Verdict.ESTABLISHED,
        basis=Basis.SOURCED_FACT,
        rationale="Established by port bulletin.",
    )
    r_loki = Ruling(
        claim_id="LOKI-W1",
        verdict=Verdict.ESTABLISHED,
        basis=Basis.SOURCED_FACT,
        rationale="Established by railway ministry filing.",
    )

    ranges = derive_exposure_ranges(
        case_file=base_case,
        claims=[c_thor, c_loki],
        rulings=[r_thor, r_loki],
        trade_store=sample_trade_store,
    )

    # Target pair 1: Midgard wheat
    er_midgard = next(r for r in ranges if r.country == "Midgard" and r.sector == "wheat")
    assert er_midgard.status == "resolved"
    assert er_midgard.thor_range == (40.0, 60.0)
    assert er_midgard.loki_range == (50.0, 50.0)
    # Total baseline: 200 + 300 = 500 k_tons
    # 40% drop = 200 - 50 offset = 150.0
    # 60% drop = 300 - 50 offset = 250.0
    assert er_midgard.odin_range == (150.0, 250.0)
    assert "offset capacity credited" in er_midgard.assumptions[0].lower()


def test_exposure_assessment_thor_unsupported_loki_supported(base_case, sample_trade_store):
    c_thor = Claim(
        claim_id="THOR-W2",
        agent=AgentRole.THOR,
        country="Midgard",
        sector="wheat",
        posture="high",
        statement="Complete destruction of all wheat infrastructure.",
        estimate_low=90.0,
        estimate_high=100.0,
        unit="pct",
        citations=[Citation(doc_id="TIER4-RUMOR", paragraph_num=1)],
    )
    c_loki = Claim(
        claim_id="LOKI-W2",
        agent=AgentRole.LOKI,
        country="Midgard",
        sector="wheat",
        posture="limited",
        statement="Transit drop is limited to 10% to 15%.",
        estimate_low=10.0,
        estimate_high=15.0,
        unit="pct",
        citations=[Citation(doc_id="OFFICIAL-DOC", paragraph_num=1)],
    )

    r_thor = Ruling(
        claim_id="THOR-W2",
        verdict=Verdict.REJECTED,
        basis=Basis.INFERENCE,
        rationale="Rejected: rests on Tier 4 rumor.",
    )
    r_loki = Ruling(
        claim_id="LOKI-W2",
        verdict=Verdict.ESTABLISHED,
        basis=Basis.SOURCED_FACT,
        rationale="Established by official customs report.",
    )

    ranges = derive_exposure_ranges(
        case_file=base_case,
        claims=[c_thor, c_loki],
        rulings=[r_thor, r_loki],
        trade_store=sample_trade_store,
    )
    er = next(r for r in ranges if r.country == "Midgard")
    assert er.status == "resolved"
    # Odin's range reflects established Loki bounds (10% to 15% of 500 = 50 to 75 k_tons), NOT Thor's rejected 100%
    assert er.odin_range == (50.0, 75.0)


def test_exposure_assessment_loki_unsupported_thor_supported(base_case, sample_trade_store):
    c_thor = Claim(
        claim_id="THOR-W3",
        agent=AgentRole.THOR,
        country="Midgard",
        sector="wheat",
        posture="high",
        statement="Measured wheat transit loss of 25% to 35%.",
        estimate_low=25.0,
        estimate_high=35.0,
        unit="pct",
        citations=[Citation(doc_id="OFFICIAL-DOC-2", paragraph_num=1)],
    )
    c_loki = Claim(
        claim_id="LOKI-W3",
        agent=AgentRole.LOKI,
        country="Midgard",
        sector="wheat",
        posture="limited",
        statement="Zero impact based on retracted statement.",
        estimate_low=0.0,
        estimate_high=0.0,
        unit="pct",
        citations=[Citation(doc_id="DOC-RETRACTED", paragraph_num=1)],
    )

    r_thor = Ruling(
        claim_id="THOR-W3",
        verdict=Verdict.ESTABLISHED,
        basis=Basis.SOURCED_FACT,
        rationale="Established by port traffic monitoring.",
    )
    r_loki = Ruling(
        claim_id="LOKI-W3",
        verdict=Verdict.REJECTED,
        basis=Basis.INFERENCE,
        rationale="Rejected: source was retracted.",
    )

    ranges = derive_exposure_ranges(
        case_file=base_case,
        claims=[c_thor, c_loki],
        rulings=[r_thor, r_loki],
        trade_store=sample_trade_store,
    )
    er = next(r for r in ranges if r.country == "Midgard")
    assert er.status == "resolved"
    # 25% to 35% of 500 = 125 to 175 k_tons
    assert er.odin_range == (125.0, 175.0)


def test_exposure_assessment_both_advocates_unsupported(base_case, sample_trade_store):
    c_thor = Claim(
        claim_id="THOR-W4",
        agent=AgentRole.THOR,
        country="Midgard",
        sector="wheat",
        posture="high",
        statement="Total collapse.",
        estimate_low=80.0,
        estimate_high=100.0,
        citations=[Citation(doc_id="TIER4-1", paragraph_num=1)],
    )
    c_loki = Claim(
        claim_id="LOKI-W4",
        agent=AgentRole.LOKI,
        country="Midgard",
        sector="wheat",
        posture="limited",
        statement="No collapse.",
        estimate_low=0.0,
        estimate_high=5.0,
        citations=[Citation(doc_id="TIER4-2", paragraph_num=1)],
    )
    r_thor = Ruling(claim_id="THOR-W4", verdict=Verdict.REJECTED, basis=Basis.INFERENCE, rationale="Tier 4 only.")
    r_loki = Ruling(claim_id="LOKI-W4", verdict=Verdict.REJECTED, basis=Basis.INFERENCE, rationale="Tier 4 only.")

    ranges = derive_exposure_ranges(
        case_file=base_case,
        claims=[c_thor, c_loki],
        rulings=[r_thor, r_loki],
        trade_store=sample_trade_store,
    )
    er = next(r for r in ranges if r.country == "Midgard")
    assert er.status == "unresolved"
    assert er.odin_range is None
    assert "rejected" in er.rationale


def test_exposure_assessment_no_usable_trade_data(base_case):
    # No trade store supplied for Midgard wheat
    c_thor = Claim(
        claim_id="THOR-NO-TRADE",
        agent=AgentRole.THOR,
        country="Midgard",
        sector="wheat",
        posture="high",
        statement="Severe wheat disruption.",
        citations=[Citation(doc_id="DOC-1", paragraph_num=1)],
    )
    r_thor = Ruling(
        claim_id="THOR-NO-TRADE",
        verdict=Verdict.CONTESTED,
        basis=Basis.INFERENCE,
        rationale="Contested due to conflicting views.",
    )

    ranges = derive_exposure_ranges(
        case_file=base_case,
        claims=[c_thor],
        rulings=[r_thor],
        trade_store=None,
    )
    er = next(r for r in ranges if r.country == "Midgard")
    assert er.status == "unresolved"
    assert er.odin_range is None
    assert "Zero admissible evidence" in er.rationale or "contested" in er.rationale


def test_sufficiency_checker_sufficient_with_disclosed_uncertainties(base_case, sample_trade_store):
    # Both country-sector pairs have resolved ranges
    ranges = [
        ExposureRange(
            country="Midgard",
            sector="wheat",
            thor_range=(100.0, 200.0),
            loki_range=(50.0, 80.0),
            odin_range=(80.0, 150.0),
            status="resolved",
            trade_row_refs=["TAB-WHEAT#1"],
        ),
        ExposureRange(
            country="Tolan",
            sector="maize",
            thor_range=(60.0, 90.0),
            loki_range=(30.0, 40.0),
            odin_range=(45.0, 70.0),
            status="resolved",
            trade_row_refs=["TAB-MAIZE#1"],
        ),
    ]

    rulings = [
        Ruling(claim_id="C1", verdict=Verdict.ESTABLISHED, basis=Basis.SOURCED_FACT, rationale="Fact."),
        Ruling(claim_id="C2", verdict=Verdict.CONTESTED, basis=Basis.INFERENCE, rationale="Unresolved dispute on long-term price effect."),
    ]
    claims = [
        Claim(claim_id="C1", agent=AgentRole.THOR, country="Midgard", sector="wheat", posture="high", statement="Short-term cut."),
        Claim(claim_id="C2", agent=AgentRole.LOKI, country="Midgard", sector="wheat", posture="limited", statement="Long-term price rise."),
    ]

    suf_result = assess_sufficiency(
        case_file=base_case,
        rulings=rulings,
        claims=claims,
        exposure_ranges=ranges,
        doc_store={},
        trade_store=sample_trade_store,
        run_count=1,
        max_runs=3,
    )

    # Contested claims do NOT cause trial to fail if overall evidence is sufficient
    assert suf_result.is_sufficient is True
    assert suf_result.status == SufficiencyStatus.SUFFICIENT
    assert suf_result.send_back is None
    assert len(suf_result.disclosed_uncertainties) == 1
    assert "C2 remains contested" in suf_result.disclosed_uncertainties[0]


def test_sufficiency_checker_missing_baseline_triggers_actionable_sendback(base_case):
    # Tolan maize is unresolved because baseline is missing
    ranges = [
        ExposureRange(
            country="Midgard",
            sector="wheat",
            odin_range=(80.0, 150.0),
            status="resolved",
            trade_row_refs=["TAB-WHEAT#1"],
        ),
        ExposureRange(
            country="Tolan",
            sector="maize",
            odin_range=None,
            status="unresolved",
            trade_row_refs=[],  # No trade rows!
        ),
    ]

    suf_result = assess_sufficiency(
        case_file=base_case,
        rulings=[],
        claims=[],
        exposure_ranges=ranges,
        doc_store={},
        trade_store=None,
        run_count=1,
        max_runs=3,
    )

    assert suf_result.is_sufficient is False
    assert suf_result.status == SufficiencyStatus.INSUFFICIENT
    assert suf_result.send_back is not None
    assert any("pre-cutoff trade baseline" in m and "Tolan" in m for m in suf_result.send_back.missing)
    assert "missing_trade_baseline" in suf_result.send_back.gap_types


def test_sufficiency_checker_unresolved_material_contradiction(base_case):
    # Thor and Loki argue opposite positions on Tolan maize, both contested, leaving range unresolved
    ranges = [
        ExposureRange(
            country="Midgard",
            sector="wheat",
            odin_range=(80.0, 150.0),
            status="resolved",
            trade_row_refs=["TAB-WHEAT#1"],
        ),
        ExposureRange(
            country="Tolan",
            sector="maize",
            odin_range=None,
            status="unresolved",
            trade_row_refs=["TAB-MAIZE#1"],
        ),
    ]

    c_thor = Claim(
        claim_id="TOL-THOR",
        agent=AgentRole.THOR,
        country="Tolan",
        sector="maize",
        posture="high",
        statement="Tolan maize imports are totally cut off.",
    )
    c_loki = Claim(
        claim_id="TOL-LOKI",
        agent=AgentRole.LOKI,
        country="Tolan",
        sector="maize",
        posture="limited",
        statement="Tolan maize imports continue normally via rail.",
    )
    rulings = [
        Ruling(claim_id="TOL-THOR", verdict=Verdict.CONTESTED, basis=Basis.INFERENCE, rationale="Disputed."),
        Ruling(claim_id="TOL-LOKI", verdict=Verdict.CONTESTED, basis=Basis.INFERENCE, rationale="Disputed."),
    ]

    suf_result = assess_sufficiency(
        case_file=base_case,
        rulings=rulings,
        claims=[c_thor, c_loki],
        exposure_ranges=ranges,
        doc_store={},
        trade_store={"TAB-MAIZE": [TradeRow(table_id="TAB-MAIZE", row_num=1, country_pair="Tolan", sector="maize", month="2026-10")]},
        run_count=1,
        max_runs=3,
    )

    assert suf_result.is_sufficient is False
    assert any("resolve material contradiction" in m for m in suf_result.send_back.missing)
    assert "unresolved_contradiction" in suf_result.send_back.gap_types


def test_sufficiency_checker_tier_4_only_rejection_triggers_sendback(base_case):
    ranges = [
        ExposureRange(country="Midgard", sector="wheat", status="resolved", odin_range=(10.0, 20.0), trade_row_refs=["T#1"]),
        ExposureRange(country="Tolan", sector="maize", status="resolved", odin_range=(5.0, 10.0), trade_row_refs=["T#2"]),
    ]
    claim_t4 = Claim(
        claim_id="C-TIER4",
        agent=AgentRole.THOR,
        country="Midgard",
        sector="wheat",
        posture="high",
        statement="Catastrophic port strike spreading to all grain terminals.",
    )
    ruling_t4 = Ruling(
        claim_id="C-TIER4",
        verdict=Verdict.REJECTED,
        basis=Basis.INFERENCE,
        rationale="Rejected: Tier 4 only.",
        disqualified_reason="tier_4_only",
    )

    suf_result = assess_sufficiency(
        case_file=base_case,
        rulings=[ruling_t4],
        claims=[claim_t4],
        exposure_ranges=ranges,
        doc_store={},
        run_count=1,
        max_runs=3,
    )

    assert suf_result.is_sufficient is False
    assert any("Tier 1-3 independent corroboration" in m for m in suf_result.send_back.missing)
    assert "tier_4_only" in suf_result.send_back.gap_types


def test_sufficiency_checker_limits_exhausted_terminates_gracefully(base_case):
    # Even if missing gaps exist, when run_count >= max_runs, must return LIMITS_EXHAUSTED without send_back
    ranges = [
        ExposureRange(country="Midgard", sector="wheat", status="unresolved", odin_range=None),
    ]

    suf_result = assess_sufficiency(
        case_file=base_case,
        rulings=[],
        claims=[],
        exposure_ranges=ranges,
        doc_store={},
        run_count=3,
        max_runs=3,
    )

    assert suf_result.is_sufficient is False
    assert suf_result.status == SufficiencyStatus.LIMITS_EXHAUSTED
    assert suf_result.send_back is None
    assert "limit reached" in suf_result.reasons[0].lower()


def test_sufficiency_checker_event_not_real_terminates_sufficient(base_case):
    base_case.verification_status = EventVerificationStatus.NOT_REAL

    suf_result = assess_sufficiency(
        case_file=base_case,
        rulings=[],
        claims=[],
        exposure_ranges=[],
        doc_store={},
        run_count=1,
        max_runs=3,
    )

    assert suf_result.is_sufficient is True
    assert suf_result.status == SufficiencyStatus.SUFFICIENT
    assert "NOT REAL" in suf_result.reasons[0]


def test_damaged_trade_table_triggers_replacement_sendback(base_case):
    damaged_table = {
        "TAB-CORRUPT": [
            TradeRow(table_id="TAB-CORRUPT", row_num=1, country_pair="Midgard-Tolan", sector="wheat", month="2026-10", is_damaged=True),
            TradeRow(table_id="TAB-CORRUPT", row_num=2, country_pair="Midgard-Tolan", sector="wheat", month="2026-11", is_damaged=True),
        ]
    }
    ranges = [
        ExposureRange(country="Midgard", sector="wheat", status="unresolved", odin_range=None),
    ]

    suf_result = assess_sufficiency(
        case_file=base_case,
        rulings=[],
        claims=[],
        exposure_ranges=ranges,
        doc_store={},
        trade_store=damaged_table,
        run_count=1,
        max_runs=3,
    )

    assert suf_result.is_sufficient is False
    assert any("Replace damaged trade data table 'TAB-CORRUPT'" in m for m in suf_result.send_back.missing)
    assert "damaged_trade_table" in suf_result.send_back.gap_types
