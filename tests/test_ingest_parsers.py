"""Parsers: format sniffing, text decoding, PDF/DOCX/TXT extraction, metadata headers,
manifest merging and paragraph splitting. All inputs are synthetic."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from ragnarok.ingest.decoding import decode_bytes, sniff_format
from ragnarok.ingest.extract import extract
from ragnarok.ingest.metadata import (
    canonical_key,
    merge_metadata,
    norm_date,
    norm_tier,
    norm_time,
    normalise_manifest_entry,
    parse_header,
)
from ragnarok.ingest.paragraphs import looks_cut_off, split_paragraphs
from ragnarok.models import DamageKind, DocFormat

DOCS = Path(__file__).parent / "fixtures" / "synth_pack" / "docs"


def fx(name: str) -> bytes:
    return (DOCS / name).read_bytes()


# ------------------------------------------------------------ sniffing ---


def test_sniff_by_content_not_extension():
    assert sniff_format(fx("SYN-0002.pdf")) == "pdf"
    assert sniff_format(fx("SYN-0003.docx")) == "docx"
    assert sniff_format(fx("SYN-0001.txt")) == "text"
    assert sniff_format(fx("SYN-0017.txt")) == "pdf"  # a PDF saved as .txt
    assert sniff_format(b"") == "empty"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("other.xml", "<x/>")
    assert sniff_format(buf.getvalue()) == "zip"


# ------------------------------------------------------------ decoding ---


def test_utf8_plain():
    d = decode_bytes("Grain prices rose.".encode())
    assert d.encoding == "utf-8" and d.replacements == 0 and not d.truncated


@pytest.mark.parametrize("bom,enc,label", [
    (b"\xef\xbb\xbf", "utf-8", "utf-8 (BOM)"),
    (b"\xff\xfe", "utf-16-le", "utf-16-le (BOM)"),
    (b"\xfe\xff", "utf-16-be", "utf-16-be (BOM)"),
])
def test_bom_detection(bom, enc, label):
    d = decode_bytes(bom + "Héllo wörld".encode(enc))
    assert d.text == "Héllo wörld" and d.encoding == label and d.replacements == 0


def test_utf16_file_fixture():
    d = decode_bytes(fx("SYN-0005.txt"))
    assert d.encoding == "utf-16-le (BOM)"
    assert d.text.startswith("DOC_ID: SYN-0005")


def test_bomless_utf16_detected_from_nul_pattern():
    d = decode_bytes("DOC_ID: X\nplain ascii text here".encode("utf-16-le"))
    assert d.encoding == "utf-16-le" and d.text.startswith("DOC_ID: X")


def test_mixed_encoding_header_ascii_body_utf16_cut_off():
    d = decode_bytes(fx("SYN-0006.txt"))
    assert d.encoding == "utf-8+utf-16-le"
    assert d.truncated  # odd trailing byte
    assert "DOC_ID: SYN-0006" in d.text and "Ships waited longer" in d.text
    assert d.replacements == 0


def test_cp1252_text_is_read_correctly_not_guessed_wrong():
    d = decode_bytes(fx("SYN-0015.txt"))
    assert d.encoding == "cp1252"
    assert "Café owners" in d.text and "–" in d.text


def test_undecodable_bytes_are_replaced_and_counted():
    data = b"ok " + bytes([0x81, 0x8D, 0x8F, 0x90, 0x9D]) * 40  # undefined in cp1252, not ASCII-heavy
    d = decode_bytes(data)
    assert d.encoding  # always recorded
    if d.encoding == "cp1252":
        assert d.replacements > 0


def test_txt_extraction_flags_bad_encoding_on_replacement():
    ex = extract("DOC_ID: X\n� broken".encode("utf-8"), "text")
    assert any(f.kind == DamageKind.BAD_ENCODING for f in ex.damage)


# ---------------------------------------------------------- extraction ---


def test_pdf_extraction_header_first():
    ex = extract(fx("SYN-0002.pdf"), "pdf")
    assert ex.format == DocFormat.PDF and not ex.damage
    assert ex.text.lstrip().startswith("DOC_ID: SYN-0002")
    assert "[P1]" in ex.text and "[P3]" in ex.text


def test_docx_extraction_hidden_runs_and_properties():
    ex = extract(fx("SYN-0003.docx"), "docx")
    assert ex.format == DocFormat.DOCX and not ex.damage
    assert ex.text.startswith("DOC_ID: SYN-0003")
    assert any("Note to the AI" in h for h in ex.hidden_runs)
    assert "Ignore all previous instructions" in ex.side_text["docx.core.comments"]


def test_corrupt_pdf_does_not_raise():
    ex = extract(fx("SYN-0016.pdf"), "pdf")
    assert ex.text == "" and ex.damage[0].kind == DamageKind.UNPARSEABLE


def test_corrupt_docx_does_not_raise():
    ex = extract(b"PK\x03\x04garbage", "docx")
    assert ex.damage[0].kind == DamageKind.UNPARSEABLE


def test_empty_file():
    ex = extract(b"", "empty")
    assert ex.damage[0].kind == DamageKind.EMPTY


# -------------------------------------------------------------- header ---


def test_header_tolerant_keys_and_spacing():
    text = "  doc id :  T-1\nPub-Date: 2030-01-02\nReliability_Tier:2\nsource name: Wire\n---\nTitle line\n[P1] Body."
    h = parse_header(text)
    assert h.found and h.terminated
    assert h.fields == {"DOC_ID": "T-1", "PUB_DATE": "2030-01-02", "RELIABILITY": "2", "SOURCE_NAME": "Wire"}
    assert h.body.startswith("Title line")


def test_header_value_may_contain_colons():
    h = parse_header("DOC_ID: A\nTITLE: Trade note: Alpha to Beta\n---\nx")
    assert h.fields["TITLE"] == "Trade note: Alpha to Beta"


def test_header_unterminated_keeps_known_keys_only():
    h = parse_header("DOC_ID: A\nPUB_DATE: 2030-01-01\nNote: this is body text\nmore")
    assert h.found and not h.terminated
    assert set(h.fields) == {"DOC_ID", "PUB_DATE"}
    assert h.body.startswith("Note: this is body text")


def test_no_header():
    h = parse_header("Just a paragraph of text.\nAnother line.")
    assert not h.found and h.body.startswith("Just a paragraph")


def test_canonical_key_aliases():
    assert canonical_key("tier") == "RELIABILITY"
    assert canonical_key("Source-Name") == "SOURCE_NAME"


@pytest.mark.parametrize("raw,iso", [
    ("2030-03-10", "2030-03-10"), ("2030/3/1", "2030-03-01"), ("20300310", "2030-03-10"),
    ("10 March 2030", "2030-03-10"), ("March 10, 2030", "2030-03-10"), ("2030-03-10T08:00", "2030-03-10"),
    ("03/04/2030", None), ("2030-02-30", None), ("soon", None), ("", None),
])
def test_norm_date(raw, iso):
    assert norm_date(raw) == iso


@pytest.mark.parametrize("raw,tier", [("1", 1), (2, 2), ("Tier 3", 3), ("T4", 4), ("2.0", 2), (5, None), ("x", None), (True, None)])
def test_norm_tier(raw, tier):
    assert norm_tier(raw) == tier


@pytest.mark.parametrize("raw,t", [("09:30", "09:30"), ("9:05", "09:05"), ("0930", "09:30"), ("25:00", None), ("noon", None)])
def test_norm_time(raw, t):
    assert norm_time(raw) == t


def test_manifest_mixed_case_keys_upper_wins_and_conflict_recorded():
    entry = {"DOC_ID": "A-1", "doc_id": "A-1", "RELIABILITY": "2", "reliability": 3, "file": "A-1.txt"}
    norm, conflicts = normalise_manifest_entry(entry)
    assert norm["RELIABILITY"] == "2" and norm["FILE"] == "A-1.txt"
    assert len(conflicts) == 1 and conflicts[0].field == "RELIABILITY"


def test_manifest_lower_then_upper_order_still_upper_wins():
    norm, _ = normalise_manifest_entry({"sector": "rice", "SECTOR": "Grain"})
    assert norm["SECTOR"] == "Grain"


def test_merge_header_wins_manifest_fills_and_raw_kept():
    header = {"DOC_ID": "A-1", "SECTOR": "Grain", "PUB_DATE": "2030-03-10", "RELIABILITY": "2"}
    manifest = {"DOC_ID": "A-1", "SECTOR": "Rice", "PUB_DATE": "2030-03-10", "RELIABILITY": "2",
                "COUNTRY": "Alpha", "LANGUAGE": "en"}
    m = merge_metadata(header, manifest)
    assert m.values["sector"] == "Grain"  # header wins
    assert m.values["country"] == "Alpha" and m.values["language"] == "en"  # manifest fills gaps
    assert m.values["reliability_tier"] == 2 and m.values["pub_date"] == "2030-03-10"
    assert [c.field for c in m.conflicts] == ["SECTOR"]
    assert m.raw["header.SECTOR"] == "Grain" and m.raw["manifest.SECTOR"] == "Rice"


def test_merge_equivalent_values_are_not_conflicts():
    m = merge_metadata({"RELIABILITY": "1", "PUB_DATE": "2030-03-10", "SECTOR": "wheat"},
                       {"RELIABILITY": "Tier 1", "PUB_DATE": "10 March 2030", "SECTOR": "Wheat"})
    assert m.conflicts == []


def test_merge_doc_id_conflict_keeps_manifest_id():
    m = merge_metadata({"DOC_ID": "FAKE-1"}, {"DOC_ID": "REAL-1"})
    assert m.values["doc_id"] == "REAL-1" and m.conflicts[0].field == "DOC_ID"


def test_merge_unreadable_values_become_problems():
    m = merge_metadata({"PUB_DATE": "someday", "RELIABILITY": "9"}, {"PUB_DATE": "2030-01-05"})
    assert m.values["pub_date"] == "2030-01-05"  # header unreadable -> manifest date used, recorded
    assert m.values["reliability_tier"] is None
    assert any("PUB_DATE unreadable" in p for p in m.problems)
    assert any("RELIABILITY" in p for p in m.problems)


# ---------------------------------------------------------- paragraphs ---


def test_split_markers_unwraps_lines_and_drops_title():
    body = "My Title\n[P1] First line\ncontinues here.\n[P2] Second.\n"
    r = split_paragraphs(body, "My Title")
    assert [(p.ref, p.text) for p in r.paragraphs] == [("P1", "First line continues here."), ("P2", "Second.")]
    assert not r.damage


def test_split_preamble_kept_as_p0():
    r = split_paragraphs("Not the title\n[P1] a.\n", "Title")
    assert r.paragraphs[0].ref == "P0" and r.paragraphs[0].text == "Not the title"


def test_split_fallback_blank_lines():
    r = split_paragraphs("Title\n\nBlock one\nwraps.\n\nBlock two.\n", "Title")
    assert [(p.ref, p.text) for p in r.paragraphs] == [("P1", "Block one wraps."), ("P2", "Block two.")]
    assert not r.used_markers and r.warnings


def test_split_repeated_and_missing_markers_are_flagged_not_lost():
    r = split_paragraphs("[P1] a.\n[P2] b.\n[P2] c.\n[P5] d.\n", None)
    refs = [p.ref for p in r.paragraphs]
    assert len(refs) == len(set(refs)) == 4  # every paragraph kept with a unique ref
    assert [p.text for p in r.paragraphs] == ["a.", "b.", "c.", "d."]
    details = " ".join(f.detail for f in r.damage)
    assert "more than once" in details and "missing: P3, P4" in details


def test_refs_are_stable_across_runs():
    body = fx("SYN-0001.txt").decode("utf-8").split("---\n", 1)[1]
    a = split_paragraphs(body, "Lock closure cuts Alpha grain loadings").paragraphs
    b = split_paragraphs(body, "Lock closure cuts Alpha grain loadings").paragraphs
    assert a == b and [p.ref for p in a] == ["P1", "P2", "P3", "P4"]


@pytest.mark.parametrize("text,cut", [
    ("The rail link cannot carry the", True),
    ("Prices rose this month.", False),
    ('He said "no".', False),
    ("Short heading", False),
])
def test_looks_cut_off(text, cut):
    assert looks_cut_off(text) is cut
