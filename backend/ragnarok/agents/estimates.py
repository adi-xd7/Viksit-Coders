"""Code checks that tie every estimate bound to a deterministic calculation record."""

from __future__ import annotations

from ragnarok.models import CalculationRecord
from ragnarok.store.db import Store

_UNITS = {"usd m": "USD M", "usd million": "USD M", "usd mn": "USD M", "percent": "percent", "%": "percent",
          "pct": "percent", "tonnes": "tonnes", "tons": "tonnes", "t": "tonnes"}


def norm_unit(u: str) -> str:
    return _UNITS.get(u.strip().lower(), u.strip())


def load_calcs(store: Store, calc_ids: list[str]) -> tuple[dict[str, CalculationRecord], list[str]]:
    recs, problems = {}, []
    for cid in calc_ids:
        raw = store.get_calculation_json(cid)
        if raw is None:
            problems.append(f"calc {cid} does not exist")
            continue
        recs[cid] = CalculationRecord.model_validate_json(raw)
    return recs, problems


def _close(a: float, b: float) -> bool:
    return abs(a - b) <= max(1e-6, 1e-4 * max(abs(a), abs(b)))


def bound_problems(store: Store, low: float | None, high: float | None, unit: str, calc_ids: list[str],
                   allowed_calc_ids: set[str] | None = None) -> list[str]:
    """Each bound must equal |result| of a referenced, complete calc record in the same unit."""
    problems: list[str] = []
    if low is None or high is None:
        return ["low and high are required (or mark the estimate as insufficient evidence)"]
    if low > high:
        problems.append(f"low {low} is greater than high {high}")
    if not calc_ids:
        return problems + ["no calc_ids: estimate numbers must come from trade_calc records"]
    recs, problems_load = load_calcs(store, calc_ids)
    problems += problems_load
    if allowed_calc_ids is not None:
        problems += [f"calc {c} was not produced or received in this case by this agent" for c in calc_ids
                     if c in recs and c not in allowed_calc_ids]
    usable = {c: r for c, r in recs.items() if r.result is not None and r.complete}
    problems += [f"calc {c} has no complete result ({r.notes or 'rows excluded'})" for c, r in recs.items() if c not in usable]
    u = norm_unit(unit)
    same_unit = [r for r in usable.values() if norm_unit(r.unit) == u]
    if usable and not same_unit:
        problems.append(f"unit {unit!r} does not match the calc records' units {sorted({r.unit for r in usable.values()})}")
    for name, v in (("low", low), ("high", high)):
        if not any(_close(abs(v), abs(r.result)) for r in same_unit):  # type: ignore[arg-type]
            options = ", ".join(f"{r.calc_id}={r.result}" for r in same_unit) or "none"
            problems.append(f"{name} bound {v} does not equal the result of any cited calc record in {unit} ({options})")
    return problems


def calc_row_refs(store: Store, calc_ids: list[str]) -> list[str]:
    recs, _ = load_calcs(store, calc_ids)
    return sorted({i.row_id for r in recs.values() for i in r.inputs if i.row_id})
