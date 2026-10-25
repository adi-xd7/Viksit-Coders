"""Deterministic trade arithmetic over row references.

Rules:
- Inputs are row IDs. Rows are resolved through the retrieval service's as_of
  gate; rows that are invalid, missing, out of window or of the wrong unit are
  excluded with a recorded reason.
- Missing never becomes zero. With `require_complete=True` (the default) any
  exclusion makes the result None. With `require_complete=False` the result is
  computed over the usable rows and the record is marked complete=False.
- Every record keeps its inputs (row ID, label, value), the excluded rows, the
  formula, unit, as_of and a deterministic calc_id, so `verify` can recompute it.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import date

from ragnarok.models import CalcInput, CalculationRecord, RowStatus, TradeRow

RowResolver = Callable[[list[str], date], tuple[list[TradeRow], dict[str, str]]]
FIELDS = ("value", "volume")
ROUND = 6


def _calc_id(operation: str, payload: dict) -> str:
    blob = json.dumps({"op": operation, **payload}, sort_keys=True, default=str)
    return "CALC-" + hashlib.sha256(blob.encode()).hexdigest()[:16]


def _prior_period(period: str, years: int = 1) -> str:
    y, m = map(int, period.split("-"))
    return f"{y - years:04d}-{m:02d}"


class TradeCalculator:
    def __init__(self, resolve: RowResolver, as_of: date) -> None:
        self.resolve = resolve
        self.as_of = as_of

    # ------------------------------------------------------------ helpers ---

    def _usable(self, row_ids: list[str], field: str) -> tuple[list[TradeRow], dict[str, str], str | None]:
        if field not in FIELDS:
            raise ValueError(f"field must be one of {FIELDS}")
        seen: set[str] = set()
        excluded: dict[str, str] = {}
        ordered: list[str] = []
        for rid in row_ids:
            if rid in seen:
                excluded[rid] = "row listed more than once (counted once)"
                continue
            seen.add(rid)
            ordered.append(rid)
        rows, withheld = self.resolve(ordered, self.as_of)
        excluded.update(withheld)
        usable: list[TradeRow] = []
        units: set[str] = set()
        for r in rows:
            v = getattr(r, field)
            if r.status != RowStatus.VALID:
                excluded[r.row_id] = f"invalid row ({r.status.value}: {r.damage_reason})"
            elif v is None:
                excluded[r.row_id] = f"{field} is missing"
            else:
                usable.append(r)
                units.add(self._unit(r, field))
        if len(units) > 1:
            first = self._unit(usable[0], field)
            for r in list(usable):
                if self._unit(r, field) != first:
                    excluded[r.row_id] = f"unit {self._unit(r, field)} differs from {first}"
                    usable.remove(r)
        unit = self._unit(usable[0], field) if usable else None
        return usable, excluded, unit

    @staticmethod
    def _unit(r: TradeRow, field: str) -> str:
        return f"{r.currency} M" if field == "value" else (r.volume_unit or "units")

    def _record(self, operation: str, inputs: list[CalcInput], result: float | None, unit: str, formula: str,
                excluded: dict[str, str], requested: int, require_complete: bool, parameters: dict | None = None,
                notes: str = "", request: dict | None = None) -> CalculationRecord:
        complete = not excluded
        if excluded and require_complete:
            result = None
            notes = (notes + " " if notes else "") + "No result: required rows were excluded (missing is not zero)."
        elif excluded:
            notes = (notes + " " if notes else "") + f"Partial: computed over {len(inputs)} usable row(s); see excluded_rows."
        if result is not None:
            result = round(result, ROUND)
        params = dict(parameters or {})
        params["require_complete"] = str(require_complete).lower()
        if request is not None:  # the exact call, so `verify` can replay it
            params["request"] = json.dumps(request, sort_keys=True)
        payload = {"inputs": [i.model_dump() for i in inputs], "params": params, "excluded": excluded,
                   "as_of": self.as_of.isoformat()}
        if not inputs:  # CalculationRecord needs at least one input; record the request instead
            inputs = [CalcInput(row_id=None, label="no usable rows", value=None)]
            result = None
        return CalculationRecord(
            calc_id=_calc_id(operation, payload), operation=operation, inputs=inputs, parameters=params, result=result,
            unit=unit, formula=formula, excluded_rows=excluded, notes=notes.strip(), as_of=self.as_of,
            rows_requested=requested, complete=complete,
        )

    @staticmethod
    def _inputs(rows: list[TradeRow], field: str, prefix: str = "") -> list[CalcInput]:
        return [CalcInput(row_id=r.row_id, label=f"{prefix}{r.origin}->{r.destination} {r.sector} {r.period} {field}",
                          value=getattr(r, field)) for r in rows]

    # --------------------------------------------------------- operations ---

    def sum(self, row_ids: list[str], field: str = "value", require_complete: bool = True) -> CalculationRecord:
        rows, excl, unit = self._usable(row_ids, field)
        total = sum(getattr(r, field) for r in rows) if rows else None
        return self._record("sum", self._inputs(rows, field), total, unit or "", f"sum({field} over rows)", excl,
                            len(row_ids), require_complete, {"field": field},
                            request={"method": "sum", "args": {"row_ids": row_ids, "field": field, "require_complete": require_complete}})

    def mean(self, row_ids: list[str], field: str = "value", require_complete: bool = True) -> CalculationRecord:
        rows, excl, unit = self._usable(row_ids, field)
        avg = sum(getattr(r, field) for r in rows) / len(rows) if rows else None
        return self._record("mean", self._inputs(rows, field), avg, unit or "", f"sum({field}) / count (n={len(rows)})",
                            excl, len(row_ids), require_complete, {"field": field},
                            request={"method": "mean", "args": {"row_ids": row_ids, "field": field, "require_complete": require_complete}})

    def _paired(self, current_ids: list[str], prior_ids: list[str], field: str, years: int):
        cur, excl_c, unit_c = self._usable(current_ids, field)
        pri, excl_p, unit_p = self._usable(prior_ids, field)
        excl = {**excl_c, **excl_p}
        if unit_c and unit_p and unit_c != unit_p:
            raise ValueError(f"current and prior rows use different units ({unit_c} vs {unit_p})")
        prior_by = {}
        for r in pri:
            prior_by.setdefault((r.origin.lower(), r.destination.lower(), r.sector.lower(), r.period), r)
        pairs: list[tuple[TradeRow, TradeRow]] = []
        used_prior: set[str] = set()
        for r in cur:
            p = prior_by.get((r.origin.lower(), r.destination.lower(), r.sector.lower(), _prior_period(r.period, years)))
            if p is None:
                excl[r.row_id] = f"no usable comparison row for {_prior_period(r.period, years)}"
            else:
                pairs.append((r, p))
                used_prior.add(p.row_id)
        for r in pri:
            if r.row_id not in used_prior:
                excl[r.row_id] = "comparison row has no matching current row"
        return pairs, excl, unit_c or unit_p or ""

    def yoy_change(self, current_ids: list[str], prior_ids: list[str], field: str = "value", percent: bool = False,
                   years: int = 1, require_complete: bool = True) -> CalculationRecord:
        """Change of the current rows' total versus the same months `years` earlier (same route and sector).

        percent=False -> sum(current) - sum(prior) in the field's unit;
        percent=True  -> 100 * (sum(current) - sum(prior)) / sum(prior); denominator = sum(prior).
        """
        pairs, excl, unit = self._paired(current_ids, prior_ids, field, years)
        cur_sum = sum(getattr(c, field) for c, _ in pairs)
        pri_sum = sum(getattr(p, field) for _, p in pairs)
        inputs = [i for c, p in pairs for i in (self._inputs([c], field, "current ")[0], self._inputs([p], field, "prior ")[0])]
        notes = ""
        if not pairs:
            result = None
        elif percent:
            result = None if pri_sum == 0 else 100 * (cur_sum - pri_sum) / pri_sum
            notes = "Denominator is zero." if pri_sum == 0 else ""
        else:
            result = cur_sum - pri_sum
        op = "yoy_pct_change" if percent else "yoy_change"
        formula = (f"100 * (sum(current {field}) - sum(prior {field})) / sum(prior {field})" if percent
                   else f"sum(current {field}) - sum(prior {field}), months paired {years} year(s) apart")
        return self._record(op, inputs, result, "percent" if percent else unit, formula, excl,
                            len(current_ids) + len(prior_ids), require_complete,
                            {"field": field, "years": years, "denominator": f"sum of prior-period {field}" if percent else "n/a",
                             "current_total": round(cur_sum, ROUND), "prior_total": round(pri_sum, ROUND)}, notes,
                            request={"method": "yoy_change", "args": {"current_ids": current_ids, "prior_ids": prior_ids,
                                     "field": field, "percent": percent, "years": years, "require_complete": require_complete}})

    def share(self, numerator_ids: list[str], denominator_ids: list[str], denominator_label: str, field: str = "value",
              require_complete: bool = True) -> CalculationRecord:
        """100 * sum(numerator) / sum(denominator). The denominator must be described explicitly."""
        if not denominator_label or len(denominator_label.strip()) < 5:
            raise ValueError("share needs an explicit denominator_label describing what the denominator is")
        num, excl_n, unit_n = self._usable(numerator_ids, field)
        den, excl_d, unit_d = self._usable(denominator_ids, field)
        excl = {**excl_n, **excl_d}
        if unit_n and unit_d and unit_n != unit_d:
            raise ValueError(f"numerator and denominator use different units ({unit_n} vs {unit_d})")
        missing_in_den = [r.row_id for r in num if r.row_id not in {d.row_id for d in den}]
        n_sum = sum(getattr(r, field) for r in num)
        d_sum = sum(getattr(r, field) for r in den)
        notes = ""
        result = None if not den or d_sum == 0 else 100 * n_sum / d_sum
        if den and d_sum == 0:
            notes = "Denominator is zero."
        if missing_in_den:
            notes += f" Numerator rows not in the denominator: {', '.join(missing_in_den)}."
        inputs = self._inputs(num, field, "numerator ") + self._inputs(den, field, "denominator ")
        return self._record("share", inputs, result, "percent", f"100 * sum(numerator {field}) / sum(denominator {field})",
                            excl, len(numerator_ids) + len(denominator_ids), require_complete,
                            {"field": field, "denominator": denominator_label.strip(),
                             "numerator_total": round(n_sum, ROUND), "denominator_total": round(d_sum, ROUND)}, notes,
                            request={"method": "share", "args": {"numerator_ids": numerator_ids, "denominator_ids": denominator_ids,
                                     "denominator_label": denominator_label, "field": field, "require_complete": require_complete}})

    def period_change(self, from_id: str, to_id: str, field: str = "value", percent: bool = True) -> CalculationRecord:
        """Change between two rows of the same route (e.g. month over month)."""
        rows, excl, unit = self._usable([from_id, to_id], field)
        by = {r.row_id: r for r in rows}
        a, b = by.get(from_id), by.get(to_id)
        inputs = ([self._inputs([a], field, "from ")[0]] if a else []) + ([self._inputs([b], field, "to ")[0]] if b else [])
        result = None
        notes = ""
        if a and b:
            va, vb = getattr(a, field), getattr(b, field)
            if percent:
                result = None if va == 0 else 100 * (vb - va) / va
                notes = "Denominator is zero." if va == 0 else ""
            else:
                result = vb - va
        return self._record("period_pct_change" if percent else "period_change", inputs, result,
                            "percent" if percent else (unit or ""),
                            f"100 * (to - from) / from ({field})" if percent else f"to - from ({field})", excl, 2, True,
                            {"field": field, "denominator": f"'from' row {field}" if percent else "n/a"}, notes,
                            request={"method": "period_change", "args": {"from_id": from_id, "to_id": to_id, "field": field,
                                     "percent": percent}})

    def net_offset(self, gross_ids: list[str], offset_ids: list[str], field: str = "value",
                   require_complete: bool = True) -> CalculationRecord:
        """sum(gross) - sum(offsets): e.g. exposed flow minus documented substitute flow.
        A negative result is reported as is (offsets exceed the gross), never clipped."""
        gross, excl_g, unit_g = self._usable(gross_ids, field)
        off, excl_o, unit_o = self._usable(offset_ids, field)
        if unit_g and unit_o and unit_g != unit_o:
            raise ValueError(f"gross and offset rows use different units ({unit_g} vs {unit_o})")
        excl = {**excl_g, **excl_o}
        g, o = sum(getattr(r, field) for r in gross), sum(getattr(r, field) for r in off)
        result = g - o if gross else None
        notes = "Offsets exceed the gross amount." if gross and o > g else ""
        inputs = self._inputs(gross, field, "gross ") + self._inputs(off, field, "offset ")
        return self._record("net_offset", inputs, result, unit_g or unit_o or "", f"sum(gross {field}) - sum(offset {field})",
                            excl, len(gross_ids) + len(offset_ids), require_complete,
                            {"field": field, "gross_total": round(g, ROUND), "offset_total": round(o, ROUND)}, notes,
                            request={"method": "net_offset", "args": {"gross_ids": gross_ids, "offset_ids": offset_ids,
                                     "field": field, "require_complete": require_complete}})

    # ------------------------------------------------------------- verify ---

    def verify(self, record: CalculationRecord) -> tuple[bool, str]:
        """Replay a record's own request against the source rows under its own as_of.

        True only if the recomputed record is identical (same calc_id, inputs,
        exclusions and result)."""
        if record.as_of is None or "request" not in record.parameters:
            return False, "record has no as_of or no stored request; cannot be reproduced"
        req = json.loads(str(record.parameters["request"]))
        method = req.get("method")
        if method not in {"sum", "mean", "yoy_change", "share", "period_change", "net_offset"}:
            return False, f"unknown operation {method!r}"
        try:
            again = getattr(TradeCalculator(self.resolve, record.as_of), method)(**req["args"])
        except (ValueError, TypeError) as exc:
            return False, f"recompute failed: {exc}"
        if again == record:
            return True, "recomputed identically from source rows"
        return False, f"mismatch: stored result {record.result}, recomputed {again.result}"
