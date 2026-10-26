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


def normalise_bounds(low: float | None, high: float | None) -> tuple[float | None, float | None, str | None]:
    """Bounds are magnitudes of the calc results (see bound_problems). A model may write a fall as
    negative numbers (low -156.5, high -216.2) or give the bounds in reverse order: same numbers,
    so code puts them as ascending magnitudes and says so. A range that crosses zero is left as is."""
    if low is None or high is None:
        return low, high, None
    if low <= 0 and high <= 0 and (low < 0 or high < 0):
        lo, hi = sorted((abs(low), abs(high)))
        return lo, hi, f"bounds {low}..{high} written as negative changes; taken as magnitudes {lo}..{hi}"
    if low > high >= 0:
        return high, low, f"bounds {low}..{high} were in reverse order; taken as {high}..{low}"
    return low, high, None


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
    matched = {}
    for name, v in (("low", low), ("high", high)):
        matched[name] = [r for r in same_unit if _close(abs(v), abs(r.result))]  # type: ignore[arg-type]
        if not matched[name]:
            options = ", ".join(f"{r.calc_id}={r.result}" for r in same_unit) or "none"
            problems.append(f"{name} bound {v} does not equal the result of any cited calc record in {unit} ({options})")
    if matched["low"] and matched["high"]:
        problems += _metric_problems(low, high, matched["low"], matched["high"])
    return problems


# operations whose sign says the direction of a change (a negative result is a fall); other operations
# are levels (sum, mean, share) or a net remainder (net_offset)
_CHANGE_FAMILY = {"yoy_change": "change", "period_change": "change", "yoy_pct_change": "percent change"}


def _family(op: str) -> str:
    return _CHANGE_FAMILY.get(op, op)


def _metric_problems(low: float, high: float, lo_recs: list, hi_recs: list) -> list[str]:
    """Both bounds must measure one metric: results of the same kind of calculation, read the same way.
    Mixing kinds (a sum of trade values with a year-on-year change), reading a negative net offset as an
    exposure, or joining a fall and a rise into one magnitude range would make the range meaningless."""
    common = {_family(r.operation) for r in lo_recs} & {_family(r.operation) for r in hi_recs}
    if not common:
        kinds = lambda rs: "/".join(sorted({r.operation for r in rs}))  # noqa: E731
        return [f"low {low} is a {kinds(lo_recs)} result and high {high} a {kinds(hi_recs)} result: both bounds must be "
                "results of the same kind of calculation, so the range measures one metric"]
    lo_recs = [r for r in lo_recs if _family(r.operation) in common]
    hi_recs = [r for r in hi_recs if _family(r.operation) in common]
    problems = []
    for name, v, rs in (("low", low, lo_recs), ("high", high, hi_recs)):
        if all(r.operation == "net_offset" and r.result < 0 for r in rs):
            problems.append(f"{name} bound {v} is the size of a negative net offset ({', '.join(r.calc_id for r in rs)}): the "
                            "offsets exceed the gross value, so no net exposure remains; a negative net offset is not an "
                            "exposure of that size")
    change = common <= set(_CHANGE_FAMILY.values())
    if change and low < 0 < high:  # a range across zero is read with its signs: a fall up to a rise
        if not (any(r.result < 0 for r in lo_recs) and any(r.result > 0 for r in hi_recs)):
            problems.append(f"the range {low}..{high} crosses zero, but its bounds do not match a fall and a rise among "
                            "the cited calc results")
    elif change:
        falls = lambda rs: {r.result < 0 for r in rs}  # noqa: E731
        if falls(lo_recs) | falls(hi_recs) == {True, False} and len(falls(lo_recs)) == len(falls(hi_recs)) == 1:
            problems.append(f"one bound is a fall and the other a rise ({low}..{high}): write a range that crosses zero as "
                            "low negative, high positive, or use two changes in the same direction")
    elif low < 0 or high < 0:
        problems.append(f"a {'/'.join(sorted(common))} result is not negative: bounds {low}..{high} must be non-negative")
    return problems


def calc_row_refs(store: Store, calc_ids: list[str]) -> list[str]:
    recs, _ = load_calcs(store, calc_ids)
    return sorted({i.row_id for r in recs.values() for i in r.inputs if i.row_id})
