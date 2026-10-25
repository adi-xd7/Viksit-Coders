"""Trade data parsing: prose trade notes and fixed-layout text tables.

Prose layout (one paragraph per month):
    [P1] Route: <origin> to <destination>, <commodity>.
    [P2] In July 2026, the value was USD 90.0M and the volume was 250,000 tonnes.
Fixed layout (PS 4.2): a header (table ID, country pair, sector, unit, period,
event ID), one line of column names, then one row per month with the row number
in the first column.

Every row is validated. Invalid rows keep status != valid, a damage_reason and
their raw text; values are never repaired and missing values never become zero.
Monetary values are stored in millions of the stated currency (unit "USD M").
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass

from ragnarok.ingest.metadata import MONTHS, TABLE_KEYS, key_value
from ragnarok.models import DamageFlag, DamageKind, Document, Paragraph, RowStatus, TradeRow, TradeTable

PROSE_PROVENANCE = "prose-v1"
FIXED_PROVENANCE = "fixed-v1"

_MISSING_TOKENS = {"", "-", "--", "—", "–", "n/a", "na", "nan", "null", "none", "missing", "unknown", "unavailable",
                   "not reported", "not available", "withheld", "?", "tbd", "..", "..."}
_NUM = r"[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
_STRICT_NUM = re.compile(rf"^{_NUM}$")
_SCALE = {"": None, "m": 1.0, "mn": 1.0, "mln": 1.0, "million": 1.0, "millions": 1.0,
          "b": 1000.0, "bn": 1000.0, "billion": 1000.0, "k": 0.001, "thousand": 0.001}
_VOL_SCALE = {"": 1.0, "k": 1e3, "thousand": 1e3, "m": 1e6, "mn": 1e6, "million": 1e6}
_CURRENCY_SYMBOLS = {"$": "USD", "€": "EUR", "£": "GBP"}

_ROUTE = re.compile(r"^\s*route\s*:\s*(?P<origin>.+?)\s+(?:to|->|→|=>)\s+(?P<dest>.+?)\s*,\s*(?P<commodity>[^,]+?)\s*\.?\s*$", re.I)
_TITLE_ROUTE = re.compile(r"(?P<origin>[A-Z][\w'\- ]*?)\s+to\s+(?P<dest>[A-Z][\w'\- ]*?)\s*,\s*(?P<commodity>[A-Za-z][\w\- ]*?)\s*(?:,|$)")
_MONTH_NAMES = "|".join(sorted(MONTHS, key=len, reverse=True))
_PROSE_ROW = re.compile(rf"^\s*in\s+(?P<month>{_MONTH_NAMES})\.?\s+(?P<year>\d{{4}})\s*,", re.I)
_PROSE_VALUE = re.compile(r"\bvalue\s+(?:was|of|is|at)\s+(?P<val>.*?)(?=\s+and\s+(?:the\s+)?volume\b|[;]|\.\s*$|$)", re.I)
_PROSE_VOLUME = re.compile(r"\bvolume\s+(?:was|of|is|at)\s+(?P<vol>.*?)\s*(?:[.;]\s*)?$", re.I)


@dataclass
class Money:
    value: float | None
    currency: str | None
    problem: str | None  # None => readable; "missing" => explicit missing; otherwise a bad-number reason


def parse_money(token: str, default_currency: str | None = None, default_scale: float | None = None) -> Money:
    t = " ".join(token.strip().split())
    if t.casefold().rstrip(".") in _MISSING_TOKENS:
        return Money(None, default_currency, "missing")
    m = re.fullmatch(rf"(?P<cur>[A-Z]{{3}}|[$€£])?\s*(?P<num>\S+?)\s*(?P<scale>[A-Za-z]+)?\.?", t)
    if not m:
        return Money(None, default_currency, f"value {token.strip()!r} is not a number")
    cur = m.group("cur")
    cur = _CURRENCY_SYMBOLS.get(cur, cur) if cur else default_currency
    num = m.group("num")
    scale_word = (m.group("scale") or "").lower()
    if not _STRICT_NUM.match(num):
        return Money(None, cur, f"value {token.strip()!r} is not a number")
    if scale_word not in _SCALE:
        return Money(None, cur, f"value {token.strip()!r} has an unknown unit {scale_word!r}")
    scale = _SCALE[scale_word] if scale_word else default_scale
    if scale is None:
        return Money(None, cur, f"value {token.strip()!r} has no scale (e.g. M) and the table states none")
    value = float(num.replace(",", "")) * scale
    if value < 0:
        return Money(None, cur, f"value {token.strip()!r} is negative")
    if cur is None:
        return Money(None, None, f"value {token.strip()!r} states no currency")
    return Money(round(value, 6), cur, None)


@dataclass
class Volume:
    value: float | None
    unit: str | None
    problem: str | None


def parse_volume(token: str, default_unit: str | None = None) -> Volume:
    t = " ".join(token.strip().split())
    if t.casefold().rstrip(".") in _MISSING_TOKENS:
        return Volume(None, default_unit, "missing")
    m = re.fullmatch(
        r"(?P<num>[^\sA-Za-z]+)(?P<k>[kK](?=\s|$))?\s*(?:(?P<scale>thousand|million|mn)\s+)?(?P<unit>[A-Za-z][A-Za-z ]*?)?\.?",
        t, re.I,
    )
    if not m or not _STRICT_NUM.match(m.group("num")):
        return Volume(None, default_unit, f"volume {token.strip()!r} is not a number")
    scale_word = "k" if m.group("k") else (m.group("scale") or "").lower()
    v = float(m.group("num").replace(",", "")) * _VOL_SCALE[scale_word]
    if v < 0:
        return Volume(None, default_unit, f"volume {token.strip()!r} is negative")
    unit = (m.group("unit") or default_unit or "").lower() or None
    return Volume(round(v, 6), unit, None)


def parse_period(token: str) -> str | None:
    t = token.strip()
    if m := re.fullmatch(r"(\d{4})[-/.](\d{1,2})(?:[-/.]\d{1,2})?", t):
        y, mo = int(m.group(1)), int(m.group(2))
    elif m := re.fullmatch(r"(\d{1,2})[-/.](\d{4})", t):
        y, mo = int(m.group(2)), int(m.group(1))
    elif m := re.fullmatch(r"([A-Za-z]+)\.?[\s\-]+(\d{4})", t):
        y, mo = int(m.group(2)), MONTHS.get(m.group(1).lower(), 0)
    elif m := re.fullmatch(r"(\d{4})\s+([A-Za-z]+)", t):
        y, mo = int(m.group(1)), MONTHS.get(m.group(2).lower(), 0)
    else:
        return None
    return f"{y:04d}-{mo:02d}" if 1 <= mo <= 12 and 1900 <= y <= 2200 else None


def _months_between(a: str, b: str) -> list[str]:
    ya, ma = map(int, a.split("-"))
    yb, mb = map(int, b.split("-"))
    out = []
    while (ya, ma) <= (yb, mb):
        out.append(f"{ya:04d}-{ma:02d}")
        ma += 1
        if ma == 13:
            ya, ma = ya + 1, 1
    return out


def _parse_period_range(text: str) -> list[str] | None:
    parts = re.split(r"\s*(?:\.\.|–|—|\bto\b|/|\s-\s)\s*", text.strip(), maxsplit=1)
    if len(parts) == 2:
        a, b = parse_period(parts[0]), parse_period(parts[1])
        if a and b and a <= b:
            return _months_between(a, b)
    one = parse_period(text)
    return [one] if one else None


def _clean_name(s: str) -> str:
    return " ".join(s.strip().strip(".").split())


# --------------------------------------------------------------------------- #
# Shared row building and table-level validation
# --------------------------------------------------------------------------- #


@dataclass
class _RawRow:
    row_number: int
    period: str | None
    paragraph_ref: str | None
    raw_text: str
    value: Money
    volume: Volume
    status: RowStatus | None = None
    reason: str | None = None


def _status_for(r: _RawRow) -> tuple[RowStatus, str | None]:
    if r.status is not None:
        return r.status, r.reason
    if r.period is None:
        return RowStatus.MALFORMED, f"period could not be read from {r.raw_text[:60]!r}"
    if r.value.problem == "missing":
        return RowStatus.MISSING_VALUE, "value is missing"
    if r.value.problem:
        return RowStatus.BAD_NUMBER, r.value.problem
    if r.volume.problem and r.volume.problem != "missing":
        return RowStatus.BAD_NUMBER, r.volume.problem
    return RowStatus.VALID, None


def _finish_table(
    table_id: str, doc: Document, origin: str, destination: str, sector: str, unit: str | None,
    layout: str, provenance: str, raw_rows: list[_RawRow], flags: list[DamageFlag],
    expected_periods: list[str] | None = None,
) -> TradeTable:
    rows: list[TradeRow] = []
    used_numbers: set[int] = set()
    # A repeated row number keeps a unique, deterministic row ID: it is numbered
    # after the highest row number in the table (its raw text keeps the original).
    next_spare = max((r.row_number for r in raw_rows), default=0) + 1
    by_period: dict[str, list[int]] = {}
    for r in raw_rows:
        status, reason = _status_for(r)
        row_number = r.row_number
        if row_number in used_numbers:
            status, reason = RowStatus.DUPLICATE_ROW, f"row number {r.row_number} repeated; stored as R{next_spare}"
            row_number, next_spare = next_spare, next_spare + 1
        used_numbers.add(row_number)
        warnings: list[str] = []
        if r.volume.problem == "missing" and status == RowStatus.VALID:
            warnings.append("volume is missing (left empty)")
        rows.append(TradeRow(
            row_id=f"{table_id}#R{row_number}", table_id=table_id, source_doc_id=doc.meta.doc_id,
            row_number=row_number, paragraph_ref=r.paragraph_ref, origin=origin, destination=destination,
            sector=sector, period=r.period,
            value=None if status == RowStatus.MISSING_VALUE else r.value.value,
            currency=r.value.currency, volume=r.volume.value, volume_unit=r.volume.unit,
            status=status, damage_reason=reason, raw_text=r.raw_text, provenance=provenance, warnings=warnings,
        ))
        if r.period:
            by_period.setdefault(r.period, []).append(len(rows) - 1)

    # Repeated periods: an exact repeat invalidates the later copy; conflicting
    # repeats invalidate every copy because we cannot tell which one is right.
    for period, idxs in by_period.items():
        if len(idxs) < 2:
            continue
        values = {(rows[i].value, rows[i].volume) for i in idxs}
        refs = ", ".join(rows[i].row_id for i in idxs)
        targets = idxs[1:] if len(values) == 1 else idxs
        why = (f"period {period} repeated with identical values ({refs})" if len(values) == 1
               else f"period {period} appears {len(idxs)} times with different values ({refs})")
        for i in targets:
            prior = rows[i].damage_reason
            rows[i] = rows[i].model_copy(update={"status": RowStatus.DUPLICATE_ROW,
                                                 "damage_reason": f"{prior}; {why}" if prior else why})

    # Same value and volume as the previous calendar month: suspicious, not invalid.
    by_p = {r.period: r for r in rows if r.period and r.status == RowStatus.VALID}
    for r in rows:
        if r.status != RowStatus.VALID or not r.period:
            continue
        y, m = map(int, r.period.split("-"))
        prev = f"{y - (m == 1):04d}-{12 if m == 1 else m - 1:02d}"
        p = by_p.get(prev)
        if p and p.value == r.value and p.volume == r.volume:
            r.warnings.append(f"value and volume identical to {prev} ({p.row_id}); possible repeated row")

    # Period coverage.
    periods = sorted({r.period for r in rows if r.period})
    if expected_periods:
        missing = [p for p in expected_periods if p not in periods]
        if missing:
            tail = missing == expected_periods[len(expected_periods) - len(missing):]
            kind = DamageKind.TRUNCATED if tail else DamageKind.MALFORMED
            flags.append(DamageFlag(kind=kind, detail=f"no rows for declared periods: {', '.join(missing)}"
                                    + (" (table cut off)" if tail else "")))
    else:
        by_year: dict[int, set[int]] = {}
        for p in periods:
            y, m = map(int, p.split("-"))
            by_year.setdefault(y, set()).add(m)
        for y, ms in sorted(by_year.items()):
            gaps = [f"{y:04d}-{m:02d}" for m in range(min(ms), max(ms) + 1) if m not in ms]
            if gaps:
                flags.append(DamageFlag(kind=DamageKind.MALFORMED, detail=f"period gap: no rows for {', '.join(gaps)}"))
        # A series with chronological gaps compares the same months across years
        # (e.g. Jul-Dec of two years); then every year should have the months
        # all the other years have.
        continuous = bool(periods) and periods == _months_between(periods[0], periods[-1])
        if len(by_year) > 1 and not continuous:
            for y, ms in sorted(by_year.items()):
                others = [v for k, v in by_year.items() if k != y]
                lacking = sorted(set.intersection(*others) - ms)
                if lacking:
                    flags.append(DamageFlag(kind=DamageKind.MALFORMED, detail=(
                        f"{y} lacks months the other years have: {', '.join(f'{y:04d}-{m:02d}' for m in lacking)}")))
    invalid = [r for r in rows if r.status != RowStatus.VALID]
    if invalid:
        flags.append(DamageFlag(kind=DamageKind.MALFORMED, detail=f"{len(invalid)} of {len(rows)} rows invalid"))
    return TradeTable(
        table_id=table_id, source_doc_id=doc.meta.doc_id, origin=origin, destination=destination,
        sector=sector, unit=unit, event_id=doc.meta.event_id, layout=layout, rows=rows, damage_flags=flags,
    )


def _sector_check(doc: Document, commodity: str | None, flags: list[DamageFlag]) -> str:
    meta_sector = (doc.meta.sector or "").lower() or None
    if commodity:
        c = commodity.lower()
        if meta_sector and meta_sector not in {c, "general"} and c not in meta_sector:
            flags.append(DamageFlag(kind=DamageKind.METADATA_CONFLICT, detail=(
                f"table content says commodity {c!r} but document metadata SECTOR is {meta_sector!r}; content used")))
        return c
    return meta_sector or "unknown"


# --------------------------------------------------------------------------- #
# Prose layout
# --------------------------------------------------------------------------- #


def _prose_row(p: Paragraph, n: int, is_last: bool) -> _RawRow | None:
    m = _PROSE_ROW.match(p.text)
    if not m or "value" not in p.text.lower():
        return None
    period = parse_period(f"{m.group('month')} {m.group('year')}")
    vm = _PROSE_VALUE.search(p.text)
    wm = _PROSE_VOLUME.search(p.text)
    value = parse_money(vm.group("val")) if vm else Money(None, None, "missing")
    volume = parse_volume(wm.group("vol")) if wm else Volume(None, None, "missing")
    row = _RawRow(row_number=n, period=period, paragraph_ref=p.ref, raw_text=p.text, value=value, volume=volume)
    ends_ok = p.text.rstrip().endswith((".", ";"))
    if not ends_ok and (is_last or not wm):
        row.status, row.reason = RowStatus.TRUNCATED, "row text is cut off"
    return row


def parse_prose_table(doc: Document) -> TradeTable | None:
    paras = doc.paragraphs
    candidates = [p for p in paras if _PROSE_ROW.match(p.text) and "value" in p.text.lower()]
    route_p = next((p for p in paras if _ROUTE.match(p.text)), None)
    if len(candidates) < 2 and not (route_p and candidates):
        return None
    flags: list[DamageFlag] = []
    origin = destination = commodity = None
    if route_p:
        rm = _ROUTE.match(route_p.text)
        origin, destination, commodity = _clean_name(rm["origin"]), _clean_name(rm["dest"]), _clean_name(rm["commodity"])
    elif tm := _TITLE_ROUTE.search(doc.meta.title):
        origin, destination, commodity = _clean_name(tm["origin"]), _clean_name(tm["dest"]), _clean_name(tm["commodity"])
        flags.append(DamageFlag(kind=DamageKind.MALFORMED, detail="no Route line; route read from the title"))
    if not origin or not destination:
        flags.append(DamageFlag(kind=DamageKind.MALFORMED, detail="route (origin/destination) not stated"))
    sector = _sector_check(doc, commodity, flags)
    last_ref = paras[-1].ref if paras else None
    raw_rows = []
    for p in candidates:
        r = _prose_row(p, len(raw_rows) + 1, p.ref == last_ref)
        if r:
            raw_rows.append(r)
    return _finish_table(
        table_id=doc.meta.doc_id, doc=doc, origin=origin or "unknown", destination=destination or (doc.meta.country or "unknown"),
        sector=sector, unit="USD M" if any(r.value.currency == "USD" for r in raw_rows) else None,
        layout="prose", provenance=PROSE_PROVENANCE, raw_rows=raw_rows, flags=flags,
    )


# --------------------------------------------------------------------------- #
# Fixed layout
# --------------------------------------------------------------------------- #

_COL_ROW = {"row", "#", "no", "no.", "n", "nr", "row_no", "rowno", "row_number", "row#", "r"}
_COL_PERIOD = {"period", "month", "date", "yyyy-mm", "yyyymm"}


def _col_kind(name: str) -> str | None:
    n = name.strip().lower().replace(" ", "_")
    if n in _COL_ROW:
        return "row"
    if n in _COL_PERIOD or n.startswith("period") or n.startswith("month"):
        return "period"
    if n.startswith(("value", "val", "usd", "trade_value")):
        return "value"
    if n.startswith(("volume", "vol", "qty", "quantity", "tonnes", "weight")):
        return "volume"
    return None


_WS_TOKEN = {"  ": re.compile(r"\S+(?: \S+)*"), " ": re.compile(r"\S+")}


def _split_cells(line: str, delim: str) -> list[str]:
    if delim == "|":
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
    elif delim in {",", ";"}:
        cells = [c.strip() for c in next(csv.reader(io.StringIO(line), delimiter=delim), [])]
    elif delim == "\t":
        cells = [c.strip() for c in line.split("\t")]
    else:
        cells = [m.group(0) for m in _WS_TOKEN[delim].finditer(line)]
    return cells


def _row_cells(line: str, column_line: str, delim: str, n_cols: int) -> tuple[list[str | None], int]:
    """Cells of a row, one per column (None = empty), and the raw cell count.

    Whitespace-aligned tables lose empty cells when split, so tokens are placed in
    the column whose name they overlap horizontally; an empty value cell stays
    empty instead of being filled by the next column's number.
    """
    if delim not in _WS_TOKEN:
        cells: list[str | None] = [c if c != "" else None for c in _split_cells(line, delim)]
        count = len(cells)
        return (cells + [None] * n_cols)[:n_cols] if count <= n_cols else cells, count
    tokens = list(_WS_TOKEN[delim].finditer(line))
    cols = list(_WS_TOKEN[delim].finditer(column_line))
    if len(tokens) >= len(cols) or len(cols) != n_cols:
        return [m.group(0) for m in tokens], len(tokens)
    placed: list[list[str]] = [[] for _ in cols]
    for t in tokens:
        def score(i: int) -> tuple[int, float]:
            c = cols[i]
            overlap = max(0, min(t.end(), c.end()) - max(t.start(), c.start()))
            return overlap, -abs((t.start() + t.end()) / 2 - (c.start() + c.end()) / 2)
        placed[max(range(len(cols)), key=score)].append(t.group(0))
    return [" ".join(p) if p else None for p in placed], len(tokens)


def _detect_columns(line: str) -> tuple[str, list[str]] | None:
    for delim in ("|", "\t", ";", ",", "  ", " "):
        if delim not in line and delim != " ":
            continue
        cells = _split_cells(line, delim)
        kinds = [_col_kind(c) for c in cells]
        known = len(cells) - kinds.count(None)
        if (3 <= len(cells) <= 12 and known >= 3 and known * 2 >= len(cells)
                and "value" in kinds and ("period" in kinds or "row" in kinds)):
            return delim, cells
    return None


def _unit_scale(unit_text: str | None) -> tuple[str | None, float | None]:
    if not unit_text:
        return None, None
    u = unit_text.strip()
    cur_m = re.search(r"\b([A-Z]{3})\b|([$€£])", u) or re.search(r"\b(usd|eur|gbp)\b", u, re.I)
    cur = None
    if cur_m:
        cur = cur_m.group(1).upper() if cur_m.group(1) else _CURRENCY_SYMBOLS.get(cur_m.group(2))
    sm = re.search(r"\b(m|mn|mln|million|millions|b|bn|billion|k|thousand)\b", u, re.I)
    scale = _SCALE[sm.group(1).lower()] if sm else (1e-6 if cur else None)
    return cur, scale


def parse_fixed_table(doc: Document, header: dict[str, str]) -> TradeTable | None:
    lines = doc.text.split("\n")
    col_idx = None
    for i, line in enumerate(lines):
        if _detect_columns(line):
            nxt = next((ln for ln in lines[i + 1:] if ln.strip() and not re.fullmatch(r"[\s\-=+|:]+", ln)), "")
            if re.match(r"^\s*\|?\s*\d+\b", nxt):  # a column line is followed by a numbered row
                col_idx = i
                break
    if col_idx is None:
        return None
    delim, columns = _detect_columns(lines[col_idx])  # type: ignore[misc]
    kinds = [_col_kind(c) for c in columns]
    row_lines: list[tuple[int, str]] = []
    trailing: list[str] = []
    for j in range(col_idx + 1, len(lines)):
        ln = lines[j]
        if not ln.strip() or re.fullmatch(r"[\s\-=+|:]+", ln):
            continue
        if re.match(r"^\s*\|?\s*\d+\b", ln):
            row_lines.append((j, ln))
        else:
            trailing.append(ln.strip())
    if not row_lines:
        return None

    flags: list[DamageFlag] = []
    if trailing:
        flags.append(DamageFlag(kind=DamageKind.MALFORMED, detail=f"{len(trailing)} non-row line(s) after the column line ignored"))
    # Table header: the document header plus any KEY: value lines before the
    # column line (a table's own header block overrides document-level keys).
    h = dict(header)
    for ln in lines[:col_idx]:
        kv = key_value(ln)
        if kv and kv[0] in TABLE_KEYS + ("SECTOR", "EVENT_ID"):
            h[kv[0]] = kv[1]
    table_id = h.get("TABLE_ID") or doc.meta.doc_id
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.\-]{0,63}", table_id):
        flags.append(DamageFlag(kind=DamageKind.BAD_METADATA, detail=f"TABLE_ID {table_id!r} unusable; document ID used"))
        table_id = doc.meta.doc_id
    origin = h.get("ORIGIN") or h.get("EXPORTER") or h.get("FROM")
    destination = h.get("DESTINATION") or h.get("IMPORTER") or h.get("TO")
    if (not origin or not destination) and h.get("COUNTRY_PAIR"):
        parts = re.split(r"\s*(?:->|→|=>|\bto\b|/|–|—|\s-\s|-|>)\s*", h["COUNTRY_PAIR"].strip(), maxsplit=1)
        if len(parts) == 2:
            origin, destination = origin or parts[0], destination or parts[1]
    if not origin or not destination:
        flags.append(DamageFlag(kind=DamageKind.MALFORMED, detail="country pair not stated in the table header"))
    commodity = h.get("COMMODITY") or h.get("SECTOR")
    sector = (commodity or doc.meta.sector or "unknown").strip().lower()
    unit_text = h.get("UNIT") or h.get("UNITS") or ""
    value_col = columns[kinds.index("value")]
    currency, scale = _unit_scale(unit_text)
    col_cur, col_scale = _unit_scale(value_col.replace("_", " "))
    currency = currency or col_cur or (h.get("CURRENCY") or "").strip().upper() or None
    scale = scale if scale is not None else col_scale
    vol_unit = None
    if vm := re.search(r"\b(tonnes|tons|t|kg|units|teu|barrels|bbl|mt)\b", unit_text + " " + " ".join(columns), re.I):
        vol_unit = vm.group(1).lower()
    expected = _parse_period_range(h["PERIOD"]) if h.get("PERIOD") else None
    if h.get("PERIOD") and expected is None:
        flags.append(DamageFlag(kind=DamageKind.BAD_METADATA, detail=f"PERIOD {h['PERIOD']!r} unreadable"))

    raw_rows: list[_RawRow] = []
    column_line = lines[col_idx]
    for k, (_line_no, ln) in enumerate(row_lines):
        cells, count = _row_cells(ln, column_line, delim, len(columns))
        is_last = k == len(row_lines) - 1
        cell = {kind: (cells[i] if i < len(cells) else None) for i, kind in enumerate(kinds) if kind}
        rn_txt = (cell.get("row") or cells[0] or "").strip()
        row_number = int(rn_txt) if rn_txt.isdigit() and int(rn_txt) >= 1 else k + 1
        period = parse_period(cell["period"]) if cell.get("period") else None
        money = parse_money(cell["value"], currency, scale) if cell.get("value") is not None else Money(None, currency, "missing")
        vol = parse_volume(cell["volume"], vol_unit) if cell.get("volume") is not None else Volume(None, vol_unit, "missing")
        r = _RawRow(row_number=row_number, period=period, paragraph_ref=None, raw_text=ln.strip(), value=money, volume=vol)
        trailing_empty = bool(cells) and cells[-1] is None
        if not rn_txt.isdigit():
            r.status, r.reason = RowStatus.MALFORMED, f"row number {rn_txt!r} is not an integer"
        elif count > len(columns):
            r.status, r.reason = RowStatus.MALFORMED, f"row has {count} cells for {len(columns)} columns"
        elif is_last and trailing_empty:
            r.status, r.reason = RowStatus.TRUNCATED, f"last row has {count} of {len(columns)} cells (table cut off)"
        raw_rows.append(r)
    if h.get("ROWS", "").strip().isdigit() and int(h["ROWS"]) != len(raw_rows):
        flags.append(DamageFlag(kind=DamageKind.TRUNCATED if int(h["ROWS"]) > len(raw_rows) else DamageKind.MALFORMED,
                                detail=f"header declares {h['ROWS']} rows, found {len(raw_rows)}"))
    numbers = [r.row_number for r in raw_rows]
    if numbers != list(range(numbers[0], numbers[0] + len(numbers))):
        flags.append(DamageFlag(kind=DamageKind.MALFORMED, detail="row numbers are not consecutive"))
    if currency is None:
        flags.append(DamageFlag(kind=DamageKind.BAD_METADATA, detail="currency/unit of values not stated; values not usable"))
    return _finish_table(
        table_id=table_id, doc=doc, origin=_clean_name(origin or "unknown"), destination=_clean_name(destination or doc.meta.country or "unknown"),
        sector=sector, unit=f"{currency} M" if currency else (unit_text or None),
        layout="fixed", provenance=FIXED_PROVENANCE, raw_rows=raw_rows, flags=flags, expected_periods=expected,
    )


def parse_trade_tables(doc: Document, header: dict[str, str]) -> list[TradeTable]:
    """Detect and parse the trade table(s) in a document; [] when it has none."""
    if not doc.text.strip():
        return []
    fixed = parse_fixed_table(doc, header)
    if fixed is not None:
        return [fixed]
    prose = parse_prose_table(doc)
    return [prose] if prose is not None else []

