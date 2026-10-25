"""Deterministic trade calculations engine.

Enforces strict input validation, provenance tracking, exclusion of damaged/late rows,
and zero mental arithmetic by LLMs.
"""

from __future__ import annotations

import math
from typing import List, Optional, Sequence, Tuple
from pydantic import BaseModel, Field

from backend.models import TradeRow


class CalculationResult(BaseModel):
    operation: str
    result: Optional[float] = None
    percentage: Optional[float] = None
    unit: str = "tons"
    is_valid: bool = True
    error_reason: Optional[str] = None
    input_row_refs: List[str] = Field(default_factory=list)
    formula: str = ""


def filter_valid_trade_rows(
    rows: Sequence[TradeRow],
    as_of: Optional[str] = None,
    expected_unit: Optional[str] = None,
) -> Tuple[List[TradeRow], List[str]]:
    """Filters trade rows for eligibility, excluding damaged, post-cutoff, or incompatible rows.
    
    Returns:
        (valid_rows, exclusion_reasons)
    """
    valid_rows: List[TradeRow] = []
    exclusion_reasons: List[str] = []
    seen_keys = set()

    for r in rows:
        row_ref = f"{r.table_id}#{r.row_num}"

        # 1. Damaged row exclusion
        if r.is_damaged:
            exclusion_reasons.append(f"Row {row_ref} excluded: damaged ({r.damage_reason or 'corrupt'})")
            continue

        # 2. Clock restriction (row month cannot exceed as_of date)
        if as_of and r.month:
            # Month format YYYY-MM, as_of format YYYY-MM-DD
            as_of_month = as_of[:7]
            if r.month > as_of_month:
                exclusion_reasons.append(f"Row {row_ref} excluded: post-cutoff month {r.month} > as_of {as_of_month}")
                continue

        # 3. Duplicate row exclusion
        dedup_key = (r.table_id, r.row_num, r.country_pair, r.sector, r.month)
        if dedup_key in seen_keys:
            exclusion_reasons.append(f"Row {row_ref} excluded: duplicate entry for {r.country_pair} {r.month}")
            continue
        seen_keys.add(dedup_key)

        # 4. Unit compatibility
        if expected_unit and r.unit and r.unit.lower() != expected_unit.lower():
            exclusion_reasons.append(f"Row {row_ref} excluded: incompatible unit '{r.unit}' != expected '{expected_unit}'")
            continue

        valid_rows.append(r)

    return valid_rows, exclusion_reasons


def calculate_sum(
    rows: Sequence[TradeRow],
    field: str = "volume",
    expected_unit: Optional[str] = None,
    as_of: Optional[str] = None,
) -> CalculationResult:
    """Calculates sum of specified field across eligible rows."""
    valid_rows, exclusions = filter_valid_trade_rows(rows, as_of=as_of, expected_unit=expected_unit)
    if not valid_rows:
        return CalculationResult(
            operation="sum",
            is_valid=False,
            error_reason=f"No admissible trade rows available to calculate sum. Exclusions: {'; '.join(exclusions)}",
        )

    row_refs = [f"{r.table_id}#{r.row_num}" for r in valid_rows]
    unit = valid_rows[0].unit

    total = 0.0
    for r in valid_rows:
        val = getattr(r, field, None)
        if val is None:
            return CalculationResult(
                operation="sum",
                is_valid=False,
                error_reason=f"Missing value for field '{field}' in row {r.table_id}#{r.row_num}. Missing values cannot be assumed zero.",
                input_row_refs=row_refs,
            )
        if not math.isfinite(val):
            return CalculationResult(
                operation="sum",
                is_valid=False,
                error_reason=f"Non-finite value '{val}' in row {r.table_id}#{r.row_num}",
                input_row_refs=row_refs,
            )
        total += float(val)

    return CalculationResult(
        operation="sum",
        result=round(total, 4),
        unit=unit,
        is_valid=True,
        input_row_refs=row_refs,
        formula=f"sum({', '.join([str(getattr(r, field)) for r in valid_rows])})",
    )


def calculate_period_change(
    baseline_row: TradeRow,
    current_row: TradeRow,
    field: str = "volume",
    as_of: Optional[str] = None,
) -> CalculationResult:
    """Calculates period-over-period absolute and percentage change between two trade rows."""
    valid_rows, exclusions = filter_valid_trade_rows([baseline_row, current_row], as_of=as_of)
    if len(valid_rows) < 2:
        return CalculationResult(
            operation="period_change",
            is_valid=False,
            error_reason=f"Incomplete comparison period: {'; '.join(exclusions) or 'one or both rows invalid'}",
        )

    r_base, r_curr = valid_rows[0], valid_rows[1]
    ref_base = f"{r_base.table_id}#{r_base.row_num}"
    ref_curr = f"{r_curr.table_id}#{r_curr.row_num}"
    row_refs = [ref_base, ref_curr]

    if r_base.unit.lower() != r_curr.unit.lower():
        return CalculationResult(
            operation="period_change",
            is_valid=False,
            error_reason=f"Incompatible units: {r_base.unit} ({ref_base}) vs {r_curr.unit} ({ref_curr})",
            input_row_refs=row_refs,
        )

    val_base = getattr(r_base, field, None)
    val_curr = getattr(r_curr, field, None)

    if val_base is None or val_curr is None:
        return CalculationResult(
            operation="period_change",
            is_valid=False,
            error_reason="One or both comparison periods have missing values.",
            input_row_refs=row_refs,
        )

    if not (math.isfinite(val_base) and math.isfinite(val_curr)):
        return CalculationResult(
            operation="period_change",
            is_valid=False,
            error_reason="Non-finite values present in comparison periods.",
            input_row_refs=row_refs,
        )

    delta = val_curr - val_base

    if val_base == 0.0:
        return CalculationResult(
            operation="period_change",
            result=round(delta, 4),
            percentage=None,
            unit=r_base.unit,
            is_valid=False,
            error_reason="Zero denominator: baseline period value is 0.0; percentage change undefined.",
            input_row_refs=row_refs,
            formula=f"{val_curr} - {val_base}",
        )

    pct_change = (delta / val_base) * 100.0

    return CalculationResult(
        operation="period_change",
        result=round(delta, 4),
        percentage=round(pct_change, 2),
        unit=r_base.unit,
        is_valid=True,
        input_row_refs=row_refs,
        formula=f"(({val_curr} - {val_base}) / {val_base}) * 100",
    )


def calculate_yoy_growth(
    prior_year_rows: Sequence[TradeRow],
    current_year_rows: Sequence[TradeRow],
    field: str = "volume",
    as_of: Optional[str] = None,
) -> CalculationResult:
    """Calculates Year-over-Year (YoY) growth between two equivalent aggregations."""
    sum_prior = calculate_sum(prior_year_rows, field=field, as_of=as_of)
    sum_curr = calculate_sum(current_year_rows, field=field, as_of=as_of)

    if not sum_prior.is_valid or not sum_curr.is_valid:
        return CalculationResult(
            operation="yoy_growth",
            is_valid=False,
            error_reason=f"Cannot compute YoY growth: prior sum error ({sum_prior.error_reason}) or current sum error ({sum_curr.error_reason})",
            input_row_refs=sum_prior.input_row_refs + sum_curr.input_row_refs,
        )

    if sum_prior.unit.lower() != sum_curr.unit.lower():
        return CalculationResult(
            operation="yoy_growth",
            is_valid=False,
            error_reason=f"Incompatible units between years: {sum_prior.unit} vs {sum_curr.unit}",
        )

    v_prior = sum_prior.result
    v_curr = sum_curr.result

    if v_prior == 0.0:
        return CalculationResult(
            operation="yoy_growth",
            result=round(v_curr - v_prior, 4),
            percentage=None,
            is_valid=False,
            error_reason="Zero denominator in prior year baseline.",
            input_row_refs=sum_prior.input_row_refs + sum_curr.input_row_refs,
        )

    delta = v_curr - v_prior
    pct_change = (delta / v_prior) * 100.0

    return CalculationResult(
        operation="yoy_growth",
        result=round(delta, 4),
        percentage=round(pct_change, 2),
        unit=sum_curr.unit,
        is_valid=True,
        input_row_refs=sum_prior.input_row_refs + sum_curr.input_row_refs,
        formula=f"(({v_curr} - {v_prior}) / {v_prior}) * 100",
    )


def calculate_substitute_offset(
    gross_exposure: float,
    offset_amount: float,
    unit: str = "k_tons",
    row_refs: Optional[List[str]] = None,
) -> CalculationResult:
    """Nets substitute route capacity / cargo rerouting from gross exposure."""
    if not (math.isfinite(gross_exposure) and math.isfinite(offset_amount)):
        return CalculationResult(
            operation="offset_netting",
            is_valid=False,
            error_reason="Non-finite input values in offset calculation.",
        )

    if offset_amount < 0.0:
        return CalculationResult(
            operation="offset_netting",
            is_valid=False,
            error_reason="Offset gain cannot be negative.",
        )

    net_exposure = max(0.0, gross_exposure - offset_amount)
    return CalculationResult(
        operation="offset_netting",
        result=round(net_exposure, 4),
        unit=unit,
        is_valid=True,
        input_row_refs=row_refs or [],
        formula=f"max(0.0, {gross_exposure} - {offset_amount})",
    )


def calculate_exposure_bounds(
    baseline_volume: float,
    drop_pct_range: Tuple[float, float],
    offset_volume: float = 0.0,
    unit: str = "k_tons",
    row_refs: Optional[List[str]] = None,
) -> Tuple[CalculationResult, Tuple[float, float]]:
    """Calculates low and high exposure bounds deterministically from baseline and drop percentages."""
    low_pct, high_pct = drop_pct_range
    if low_pct > high_pct:
        low_pct, high_pct = high_pct, low_pct

    gross_low = baseline_volume * (low_pct / 100.0)
    gross_high = baseline_volume * (high_pct / 100.0)

    net_low = max(0.0, gross_low - offset_volume)
    net_high = max(0.0, gross_high - offset_volume)

    res = CalculationResult(
        operation="exposure_bounds",
        result=round(net_high, 4),
        unit=unit,
        is_valid=True,
        input_row_refs=row_refs or [],
        formula=f"[{baseline_volume} * {low_pct}%, {baseline_volume} * {high_pct}%] - {offset_volume}",
    )
    return res, (round(net_low, 2), round(net_high, 2))
