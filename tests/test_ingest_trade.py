"""Trade data: prose and fixed layouts, row validation, no silent repair. Synthetic data."""

from __future__ import annotations

import pytest

from ragnarok.ingest.trade import parse_money, parse_period, parse_trade_tables, parse_volume
from ragnarok.models import DocMeta, Document, Paragraph, ParserInfo, RowStatus

SHA = "b" * 64


def doc(paras: list[str], *, text: str | None = None, sector: str = "grain", doc_id: str = "TST-0100") -> Document:
    ps = [Paragraph(ref=f"P{i + 1}", ordinal=i, text=t) for i, t in enumerate(paras)]
    meta = DocMeta(doc_id=doc_id, event_id="EVQ", title="Trade note: Alpha to Beta, grain, 2030", source_name="M",
                   source_type="trade_note", reliability_tier=1, pub_date="2030-08-01", sector=sector, country="Beta")
    return Document(meta=meta, paragraphs=ps, text=text if text is not None else "\n\n".join(paras),
                    file_sha256=SHA, parser=ParserInfo(parser="text"), pack_id="p")


def row(month: str, year: int, value: str = "USD 10.0M", volume: str = "1,000 tonnes") -> str:
    return f"In {month} {year}, the value was {value} and the volume was {volume}."


PROSE_OK = ["Route: Alpha to Beta, grain."] + [row(m, 2030) for m in ("January", "February", "March")] + ["A closing note."]


def by_period(table):
    return {r.period: r for r in table.rows}


# --------------------------------------------------------------- prose ---


def test_prose_rows_parsed_with_refs_units_and_route():
    (t,) = parse_trade_tables(doc(PROSE_OK), {})
    assert (t.origin, t.destination, t.sector, t.layout, t.unit) == ("Alpha", "Beta", "grain", "prose", "USD M")
    assert [r.row_id for r in t.rows] == ["TST-0100#R1", "TST-0100#R2", "TST-0100#R3"]
    r = t.rows[0]
    assert (r.period, r.value, r.currency, r.volume, r.volume_unit, r.paragraph_ref, r.status) == \
        ("2030-01", 10.0, "USD", 1000.0, "tonnes", "P2", RowStatus.VALID)
    assert r.raw_text == PROSE_OK[1]


def test_non_trade_document_has_no_table():
    assert parse_trade_tables(doc(["Prices rose in March.", "In March 2030, rail use increased."]), {}) == []


def test_prose_missing_value_stays_none():
    t, = parse_trade_tables(doc(PROSE_OK[:2] + [row("February", 2030, value="not reported")] + PROSE_OK[3:]), {})
    r = by_period(t)["2030-02"]
    assert r.status == RowStatus.MISSING_VALUE and r.value is None and r.damage_reason


def test_prose_bad_number_not_repaired():
    t, = parse_trade_tables(doc(PROSE_OK[:2] + [row("February", 2030, value="USD 1O.5M")] + PROSE_OK[3:]), {})
    r = by_period(t)["2030-02"]
    assert r.status == RowStatus.BAD_NUMBER and r.value is None and "1O.5" in r.damage_reason


def test_prose_repeated_identical_row_invalidates_the_copy_only():
    paras = PROSE_OK[:3] + [PROSE_OK[2]] + PROSE_OK[3:]
    t, = parse_trade_tables(doc(paras), {})
    feb = [r for r in t.rows if r.period == "2030-02"]
    assert [r.status for r in feb] == [RowStatus.VALID, RowStatus.DUPLICATE_ROW]


def test_prose_conflicting_repeat_invalidates_both():
    paras = PROSE_OK[:3] + [row("February", 2030, value="USD 99.0M")] + PROSE_OK[3:]
    t, = parse_trade_tables(doc(paras), {})
    feb = [r for r in t.rows if r.period == "2030-02"]
    assert all(r.status == RowStatus.DUPLICATE_ROW for r in feb) and "different values" in feb[0].damage_reason


def test_prose_cut_off_last_row():
    paras = PROSE_OK[:3] + ["In March 2030, the value was USD 10.0M and the vol"]
    t, = parse_trade_tables(doc(paras), {})
    assert by_period(t)["2030-03"].status == RowStatus.TRUNCATED


def test_prose_identical_to_previous_month_is_warning_not_invalid():
    paras = [PROSE_OK[0], row("January", 2030), row("February", 2030), row("March", 2030, value="USD 11.0M")]
    t, = parse_trade_tables(doc(paras), {})
    feb = by_period(t)["2030-02"]
    assert feb.status == RowStatus.VALID and "identical" in feb.warnings[0]


def test_prose_commodity_from_content_beats_wrong_sector_metadata():
    t, = parse_trade_tables(doc(PROSE_OK, sector="rice"), {})
    assert t.sector == "grain"
    assert any(f.kind.value == "metadata_conflict" for f in t.damage_flags)


def test_prose_period_gap_flagged():
    paras = [PROSE_OK[0], row("January", 2030), row("March", 2030)]
    t, = parse_trade_tables(doc(paras), {})
    assert any("2030-02" in f.detail for f in t.damage_flags)


def test_year_on_year_layout_is_not_a_gap_but_missing_comparison_month_is():
    months = ("July", "August", "September")
    ok = [PROSE_OK[0]] + [row(m, 2030) for m in months] + [row(m, 2029) for m in months]
    t, = parse_trade_tables(doc(ok), {})
    assert not any("lacks" in f.detail or "gap" in f.detail for f in t.damage_flags)
    short = ok[:-1]  # 2029-09 missing
    t2, = parse_trade_tables(doc(short), {})
    assert any("2029-09" in f.detail for f in t2.damage_flags)


# --------------------------------------------------------------- fixed ---

FIXED = """DOC_ID: TST-0200
---
TABLE_ID: TT-TST-9
COUNTRY_PAIR: Gamma -> Alpha
SECTOR: fuel
UNIT: USD M; tonnes
PERIOD: 2030-01..2030-04
EVENT_ID: EVQ

ROW  PERIOD   VALUE_USD_M  VOLUME_TONNES
{rows}"""


def fixed(rows: str) -> Document:
    text = FIXED.format(rows=rows)
    return doc([], text=text, sector="fuel", doc_id="TST-0200")


def test_fixed_layout_header_columns_rows():
    t, = parse_trade_tables(fixed(
        "1    2030-01  12.5         30,000\n2    2030-02  12.0         29,000\n"
        "3    2030-03  11.5         28,000\n4    2030-04  11.0         27,000\n"), {})
    assert (t.table_id, t.origin, t.destination, t.sector, t.layout) == ("TT-TST-9", "Gamma", "Alpha", "fuel", "fixed")
    assert [r.row_id for r in t.rows] == [f"TT-TST-9#R{i}" for i in (1, 2, 3, 4)]
    assert all(r.status == RowStatus.VALID for r in t.rows)
    assert (t.rows[0].value, t.rows[0].currency, t.rows[0].volume) == (12.5, "USD", 30000.0)
    assert not t.damage_flags


def test_fixed_missing_value_cell_is_not_filled_from_next_column():
    t, = parse_trade_tables(fixed(
        "1    2030-01  12.5         30,000\n2    2030-02               29,000\n"
        "3    2030-03  11.5         28,000\n4    2030-04  11.0         27,000\n"), {})
    r = by_period(t)["2030-02"]
    assert r.status == RowStatus.MISSING_VALUE and r.value is None and r.volume == 29000.0


def test_fixed_bad_number_repeated_row_and_cut_off():
    t, = parse_trade_tables(fixed(
        "1    2030-01  12.5         30,000\n2    2030-02  1z.0         29,000\n"
        "2    2030-02  1z.0         29,000\n3    2030-03  11.5\n"), {})
    statuses = [(r.row_id, r.status) for r in t.rows]
    assert statuses[1] == ("TT-TST-9#R2", RowStatus.BAD_NUMBER)
    assert statuses[2][1] == RowStatus.DUPLICATE_ROW and statuses[2][0] == "TT-TST-9#R4"  # unique, deterministic id
    assert statuses[3] == ("TT-TST-9#R3", RowStatus.TRUNCATED)
    assert any("2030-04" in f.detail and f.kind.value == "truncated" for f in t.damage_flags)


def test_fixed_last_row_cut_inside_a_number_is_not_valid():
    # "27,000" cut to "27": every cell is there, but the row is not plausible
    t, = parse_trade_tables(fixed(
        "1    2030-01  12.5         30,000\n2    2030-02  12.0         29,000\n"
        "3    2030-03  11.5         28,000\n4    2030-04  11.0         27"), {})
    r = by_period(t)["2030-04"]
    assert r.status == RowStatus.TRUNCATED and "cut off" in r.damage_reason
    assert any(f.kind.value == "truncated" for f in t.damage_flags)


def test_fixed_garbled_middle_row_is_bad_number_and_normal_tables_stay_valid():
    t, = parse_trade_tables(fixed(
        "1    2030-01  12.5         30,000\n2    2030-02  1250         29,000\n"
        "3    2030-03  11.5         28,000\n4    2030-04  11.0         27,000\n"), {})
    assert by_period(t)["2030-02"].status == RowStatus.BAD_NUMBER
    ok, = parse_trade_tables(fixed(  # a real fall (value and volume move together) is not an outlier
        "1    2030-01  12.5         30,000\n2    2030-02  4.0          9,500\n"
        "3    2030-03  2.5          6,100\n4    2030-04  11.0         27,000\n"), {})
    assert all(r.status == RowStatus.VALID for r in ok.rows)


def test_declared_period_with_several_ranges():
    text = FIXED.replace("PERIOD: 2030-01..2030-04", "PERIOD: 2029-01..2029-02; 2030-01..2030-02").format(rows=(
        "1    2029-01  12.5         30,000\n2    2029-02  12.0         29,000\n3    2030-01  11.5         28,000\n"))
    t, = parse_trade_tables(doc([], text=text, sector="fuel", doc_id="TST-0201"), {})
    assert any("2030-02" in f.detail and f.kind.value == "truncated" for f in t.damage_flags)
    assert not any(f.kind.value == "bad_metadata" for f in t.damage_flags)


@pytest.mark.parametrize("sep", ["|", "\t", ","])
def test_fixed_delimited_variants(sep):
    lines = [sep.join(["row", "period", "value", "volume"]),
             sep.join(["1", "2030-01", "12.5", "30000"]), sep.join(["2", "2030-02", "", "29000"])]
    text = "DOC_ID: X\n---\nTABLE_ID: TT-D\nCOUNTRY_PAIR: A to B\nUNIT: USD M\n\n" + "\n".join(lines)
    t, = parse_trade_tables(doc([], text=text), {})
    assert [r.status for r in t.rows] == [RowStatus.VALID, RowStatus.MISSING_VALUE]
    assert (t.origin, t.destination) == ("A", "B")


def test_fixed_without_currency_is_not_usable():
    text = "DOC_ID: X\n---\nTABLE_ID: TT-N\n\nROW PERIOD VALUE VOLUME\n1 2030-01 12.5 30000\n"
    t, = parse_trade_tables(doc([], text=text), {})
    assert t.rows[0].status != RowStatus.VALID
    assert any("currency" in f.detail for f in t.damage_flags)


# ------------------------------------------------------- value parsing ---


@pytest.mark.parametrize("tok,val,cur,problem", [
    ("USD 90.0M", 90.0, "USD", None), ("USD 1.2bn", 1200.0, "USD", None), ("$5 million", 5.0, "USD", None),
    ("USD 250K", 0.25, "USD", None), ("USD 1,234.5M", 1234.5, "USD", None),
    ("n/a", None, None, "missing"), ("—", None, None, "missing"),
])
def test_parse_money_ok(tok, val, cur, problem):
    m = parse_money(tok)
    assert (m.value, m.currency, m.problem) == (val, cur, problem)


@pytest.mark.parametrize("tok", ["USD 9O.0M", "USD 12..5M", "USD -3.0M", "USD 1,2,3M", "abc", "USD 5"])
def test_parse_money_bad(tok):
    m = parse_money(tok)
    assert m.value is None and m.problem and m.problem != "missing"


@pytest.mark.parametrize("tok,val,unit", [("250,000 tonnes", 250000.0, "tonnes"), ("250k tonnes", 250000.0, "tonnes"),
                                          ("12 mt", 12.0, "mt"), ("1.5 million tonnes", 1500000.0, "tonnes")])
def test_parse_volume(tok, val, unit):
    v = parse_volume(tok)
    assert (v.value, v.unit, v.problem) == (val, unit, None)


@pytest.mark.parametrize("tok,p", [("2030-07", "2030-07"), ("2030/7", "2030-07"), ("Jul 2030", "2030-07"),
                                   ("July 2030", "2030-07"), ("07/2030", "2030-07"), ("2030-13", None), ("Q3", None)])
def test_parse_period(tok, p):
    assert parse_period(tok) == p
