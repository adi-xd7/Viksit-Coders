"""Deterministic financial and commercial exposure verification suite.

Verifies:
  1. Financial totals and percentages are calculated purely by deterministic Python code, never by LLM mental math.
  2. Unit and currency integrity (e.g., tons, USD) is preserved and checked.
  3. Missing trade rows or null values are never assumed to be zero.
  4. Invalid numbers (NaN, Inf, negative volume corruption) are detected and rejected.
  5. Exposure ranges are appropriately represented as bounds/estimates rather than fabricated point facts.
  6. Thor's and Loki's partisan claims remain clearly distinguishable from Odin's judicial ruling.
  7. Briefing Section F numbers match deterministic trade calculation outputs.
  8. Rounding and percentage precision conventions are strictly maintained.
"""

import math
import pytest
from backend.briefing import generate_briefing
from backend.models import (
    Basis,
    CaseFile,
    EventVerificationStatus,
    ExposureRange,
    Ruling,
    TradeRow,
    Verdict,
)
from backend.trade_calc import (
    calculate_exposure_bounds,
    calculate_period_change,
    calculate_substitute_offset,
    calculate_sum,
    filter_valid_trade_rows,
)


@pytest.fixture
def clean_trade_rows():
    return [
        TradeRow(
            table_id="TAB-WHEAT",
            row_num=1,
            country_pair="Midgard-Utgard",
            sector="wheat",
            month="2026-11",
            volume=50000.0,
            value=15000000.0,
            unit="tons",
        ),
        TradeRow(
            table_id="TAB-WHEAT",
            row_num=2,
            country_pair="Midgard-Utgard",
            sector="wheat",
            month="2026-12",
            volume=55000.0,
            value=16500000.0,
            unit="tons",
        ),
    ]


def test_deterministic_sum_and_unit_preservation(clean_trade_rows):
    """Verifies that sum calculations preserve units and compute deterministic totals."""
    res_vol = calculate_sum(clean_trade_rows, field="volume", as_of="2027-01-25")
    assert res_vol.is_valid is True
    assert res_vol.result == 105000.0
    assert res_vol.unit == "tons"
    assert len(res_vol.input_row_refs) == 2

    res_val = calculate_sum(clean_trade_rows, field="value", as_of="2027-01-25")
    assert res_val.is_valid is True
    assert res_val.result == 31500000.0
    assert res_val.unit == "tons"  # Unit on row is tons for commodity volume/value table


def test_missing_trade_values_not_assumed_zero():
    """Verifies that missing or null fields in trade rows fail explicitly rather than defaulting to zero."""
    rows_with_none = [
        TradeRow(
            table_id="TAB-MISSING",
            row_num=1,
            country_pair="Midgard-Utgard",
            sector="wheat",
            month="2026-11",
            volume=50000.0,
            value=15000000.0,
            unit="tons",
        ),
        TradeRow(
            table_id="TAB-MISSING",
            row_num=2,
            country_pair="Midgard-Utgard",
            sector="wheat",
            month="2026-12",
            volume=None,  # Missing observation
            value=16500000.0,
            unit="tons",
        ),
    ]

    res = calculate_sum(rows_with_none, field="volume", as_of="2027-01-25")
    assert res.is_valid is False
    assert "missing value" in res.error_reason.lower()
    assert "cannot be assumed zero" in res.error_reason.lower()


def test_invalid_and_corrupt_numeric_inputs_rejected():
    """Verifies that non-finite numbers (NaN, Inf) and damaged rows are rejected."""
    # 1. Damaged row flag
    damaged_rows = [
        TradeRow(
            table_id="TAB-CORRUPT",
            row_num=1,
            country_pair="Midgard-Utgard",
            sector="wheat",
            month="2026-11",
            volume=50000.0,
            value=15000000.0,
            unit="tons",
            is_damaged=True,
            damage_reason="Sensor failure",
        )
    ]
    valid_rows, exclusions = filter_valid_trade_rows(damaged_rows, as_of="2027-01-25")
    assert len(valid_rows) == 0
    assert "damaged" in exclusions[0].lower()

    # 2. Non-finite value
    nan_row = TradeRow(
        table_id="TAB-NAN",
        row_num=1,
        country_pair="Midgard-Utgard",
        sector="wheat",
        month="2026-11",
        volume=float("nan"),
        value=15000000.0,
        unit="tons",
    )
    res_nan = calculate_sum([nan_row], field="volume", as_of="2027-01-25")
    assert res_nan.is_valid is False
    assert "non-finite" in res_nan.error_reason.lower()


def test_incompatible_units_rejected(clean_trade_rows):
    """Verifies that attempting calculations across mismatched units is prevented."""
    mismatched_row = TradeRow(
        table_id="TAB-KG",
        row_num=3,
        country_pair="Midgard-Utgard",
        sector="wheat",
        month="2026-12",
        volume=50000000.0,
        value=15000000.0,
        unit="kg",  # Incompatible with 'tons'
    )

    res = calculate_period_change(clean_trade_rows[0], mismatched_row, field="volume")
    assert res.is_valid is False
    assert "incompatible units" in res.error_reason.lower()


def test_period_change_percentage_and_rounding(clean_trade_rows):
    """Verifies deterministic delta, percentage calculation, and 2-decimal rounding."""
    r_nov = clean_trade_rows[0]  # 50,000 tons
    r_dec = clean_trade_rows[1]  # 55,000 tons

    res = calculate_period_change(r_nov, r_dec, field="volume")
    assert res.is_valid is True
    assert res.result == 5000.0  # +5,000 tons
    assert res.percentage == 10.0  # +10.00%
    assert res.formula == "((55000.0 - 50000.0) / 50000.0) * 100"


def test_exposure_ranges_distinguish_thor_loki_and_odin():
    """Verifies that Thor's high-side argument, Loki's low-side argument, and Odin's bound are distinct."""
    er = ExposureRange(
        country="Midgard",
        sector="wheat",
        thor_range=(18000.0, 26000.0),
        loki_range=(8000.0, 12000.0),
        odin_range=(12000.0, 18000.0),
        status="resolved",
        rationale="Odin established 12,000 - 18,000 based on verified southern rail bypass capacity.",
        trade_row_refs=["TAB-WHEAT#1", "TAB-WHEAT#2"],
    )

    # Distinct bounds check
    assert er.thor_range != er.loki_range
    assert er.thor_range != er.odin_range
    assert er.loki_range != er.odin_range
    assert er.odin_range[0] >= er.loki_range[0]
    assert er.odin_range[1] <= er.thor_range[1]
    assert er.status == "resolved"


def test_briefing_table_matches_deterministic_trade_calc(clean_trade_rows):
    """Verifies that Section F of Briefing accurately reflects the deterministic calculation output."""
    case = CaseFile(
        case_id="CASE-FIN-001",
        query="What is Midgard wheat exposure?",
        as_of="2027-01-25",
        target_pairs=[("Midgard", "wheat")],
        verification_status=EventVerificationStatus.REAL,
    )

    er = ExposureRange(
        country="Midgard",
        sector="wheat",
        thor_range=(15000.0, 25000.0),
        loki_range=(8000.0, 12000.0),
        odin_range=(10000.0, 15000.0),
        status="resolved",
        rationale="Deterministic corridor diversion offset of 10000 tons confirmed.",
        trade_row_refs=["TAB-WHEAT#1", "TAB-WHEAT#2"],
    )

    briefing = generate_briefing(
        case_file=case,
        rulings=[],
        claims=[],
        exposure_ranges=[er],
        doc_store={},
        trade_store={"TAB-WHEAT": clean_trade_rows},
    )

    assert len(briefing.section_f_table) == 1
    row = briefing.section_f_table[0]
    assert row.country == "Midgard"
    assert row.sector == "wheat"
    assert row.thor_range == (15000.0, 25000.0)
    assert row.loki_range == (8000.0, 12000.0)
    assert row.odin_range == (10000.0, 15000.0)
    assert "TAB-WHEAT#1" in row.trade_row_refs
    assert "TAB-WHEAT#2" in row.trade_row_refs


def test_deterministic_exposure_bounds_and_substitute_offset():
    """Verifies deterministic exposure bound formulas and substitute offset netting."""
    # Baseline 100,000 tons, disruption range 20% to 40%, alternative rail offset 10,000 tons
    res, bounds = calculate_exposure_bounds(
        baseline_volume=100000.0,
        drop_pct_range=(20.0, 40.0),
        offset_volume=10000.0,
        unit="tons",
    )
    assert res.is_valid is True
    # 20% of 100,000 = 20,000 - 10,000 offset = 10,000
    # 40% of 100,000 = 40,000 - 10,000 offset = 30,000
    assert bounds == (10000.0, 30000.0)

    # Offset netting
    res_offset = calculate_substitute_offset(gross_exposure=25000.0, offset_amount=7000.0, unit="tons")
    assert res_offset.is_valid is True
    assert res_offset.result == 18000.0

