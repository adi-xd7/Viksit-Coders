"""Unit tests for deterministic trade calculations, provenance, and validation."""

import pytest
from backend.models import TradeRow
from backend.trade_calc import (
    calculate_exposure_bounds,
    calculate_period_change,
    calculate_substitute_offset,
    calculate_sum,
    calculate_yoy_growth,
    filter_valid_trade_rows,
)


@pytest.fixture
def valid_rows():
    return [
        TradeRow(
            table_id="TAB-GRAIN",
            row_num=1,
            country_pair="Midgard-Tolan",
            sector="wheat",
            month="2026-10",
            volume=100.0,
            value=40.0,
            unit="k_tons",
        ),
        TradeRow(
            table_id="TAB-GRAIN",
            row_num=2,
            country_pair="Midgard-Tolan",
            sector="wheat",
            month="2026-11",
            volume=120.0,
            value=48.0,
            unit="k_tons",
        ),
        TradeRow(
            table_id="TAB-GRAIN",
            row_num=3,
            country_pair="Midgard-Tolan",
            sector="wheat",
            month="2026-12",
            volume=110.0,
            value=44.0,
            unit="k_tons",
        ),
    ]


def test_valid_summation(valid_rows):
    res = calculate_sum(valid_rows, field="volume")
    assert res.is_valid is True
    assert res.result == 330.0
    assert res.unit == "k_tons"
    assert res.input_row_refs == ["TAB-GRAIN#1", "TAB-GRAIN#2", "TAB-GRAIN#3"]
    assert "sum(" in res.formula


def test_period_change_and_yoy_growth(valid_rows):
    # Period change between row 1 and row 2 (100 -> 120 = +20%)
    res = calculate_period_change(valid_rows[0], valid_rows[1], field="volume")
    assert res.is_valid is True
    assert res.result == 20.0
    assert res.percentage == 20.0
    assert res.input_row_refs == ["TAB-GRAIN#1", "TAB-GRAIN#2"]

    # YoY growth with same periods
    yoy = calculate_yoy_growth([valid_rows[0]], [valid_rows[1]], field="volume")
    assert yoy.is_valid is True
    assert yoy.result == 20.0
    assert yoy.percentage == 20.0


def test_zero_denominator_handled():
    r_zero = TradeRow(table_id="TAB-01", row_num=1, country_pair="A-B", sector="oil", month="2026-01", volume=0.0)
    r_target = TradeRow(table_id="TAB-01", row_num=2, country_pair="A-B", sector="oil", month="2026-02", volume=50.0)
    res = calculate_period_change(r_zero, r_target, field="volume")
    assert res.is_valid is False
    assert "Zero denominator" in res.error_reason
    assert res.result == 50.0
    assert res.percentage is None


def test_missing_comparison_period_and_damaged_rows():
    r1 = TradeRow(table_id="TAB-01", row_num=1, country_pair="A-B", sector="oil", month="2026-01", volume=100.0)
    r2_damaged = TradeRow(
        table_id="TAB-01", row_num=2, country_pair="A-B", sector="oil", month="2026-02", volume=None, is_damaged=True
    )
    res = calculate_period_change(r1, r2_damaged, field="volume")
    assert res.is_valid is False
    assert "Incomplete comparison period" in res.error_reason


def test_missing_value_not_treated_as_zero():
    # If a row has volume=None, calculate_sum must fail, NOT assume zero
    r_missing = TradeRow(table_id="TAB-01", row_num=1, country_pair="A-B", sector="oil", month="2026-01", volume=None)
    res = calculate_sum([r_missing], field="volume")
    assert res.is_valid is False
    assert "Missing value" in res.error_reason


def test_incompatible_units():
    r_tons = TradeRow(table_id="TAB-01", row_num=1, country_pair="A-B", sector="oil", month="2026-01", volume=100.0, unit="tons")
    r_bbl = TradeRow(table_id="TAB-01", row_num=2, country_pair="A-B", sector="oil", month="2026-02", volume=100.0, unit="barrels")
    res = calculate_period_change(r_tons, r_bbl, field="volume")
    assert res.is_valid is False
    assert "Incompatible units" in res.error_reason


def test_non_finite_values():
    r_inf = TradeRow(table_id="TAB-01", row_num=1, country_pair="A-B", sector="oil", month="2026-01", volume=float("inf"))
    res = calculate_sum([r_inf], field="volume")
    assert res.is_valid is False
    assert "Non-finite" in res.error_reason


def test_duplicate_and_post_as_of_rows_excluded():
    r1 = TradeRow(table_id="TAB-01", row_num=1, country_pair="A-B", sector="wheat", month="2026-05", volume=50.0)
    r1_dup = TradeRow(table_id="TAB-01", row_num=1, country_pair="A-B", sector="wheat", month="2026-05", volume=50.0)
    r_late = TradeRow(table_id="TAB-01", row_num=2, country_pair="A-B", sector="wheat", month="2027-02", volume=80.0)

    # Filter with as_of="2027-01-25"
    valid, exclusions = filter_valid_trade_rows([r1, r1_dup, r_late], as_of="2027-01-25")
    assert len(valid) == 1
    assert valid[0].month == "2026-05"
    assert any("duplicate" in e for e in exclusions)
    assert any("post-cutoff" in e for e in exclusions)


def test_substitute_offset_and_exposure_bounds():
    # 500 tons baseline, drop range [20%, 40%], offset 30 tons
    calc, bounds = calculate_exposure_bounds(
        baseline_volume=500.0,
        drop_pct_range=(20.0, 40.0),
        offset_volume=30.0,
        unit="k_tons",
    )
    assert calc.is_valid is True
    # 500 * 0.20 = 100 - 30 = 70.0
    # 500 * 0.40 = 200 - 30 = 170.0
    assert bounds == (70.0, 170.0)

    # Negative offset rejected
    offset_neg = calculate_substitute_offset(gross_exposure=100.0, offset_amount=-10.0)
    assert offset_neg.is_valid is False
    assert "cannot be negative" in offset_neg.error_reason
