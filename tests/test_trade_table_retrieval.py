"""
Test 4: Trade-table retrieval and parsing.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from heimdall.retrieval.trade_table_parser import (
    extract_trade_tables, is_trade_note, _parse_trade_title,
)


class TestTradeTableRetrieval:
    """Test trade-table extraction from documents."""

    def test_is_trade_note_by_source_type(self):
        """trade_note source_type should be detected."""
        meta = {"SOURCE_TYPE": "trade_note", "TITLE": "Something"}
        assert is_trade_note(meta)

    def test_is_trade_note_by_title(self):
        """Title containing 'trade note' should be detected."""
        meta = {"SOURCE_TYPE": "news", "TITLE": "Trade note: X to Y"}
        assert is_trade_note(meta)

    def test_not_trade_note(self):
        """Regular news article should not be a trade note."""
        meta = {"SOURCE_TYPE": "news", "TITLE": "Port holds ships"}
        assert not is_trade_note(meta)

    def test_parse_trade_title(self):
        """Parse origin, destination, commodity, period from title."""
        origin, dest, commodity, period = _parse_trade_title(
            "Trade note: Orvan to Midgard, wheat, July to December 2026"
        )
        assert origin == "Orvan"
        assert dest == "Midgard"
        assert commodity == "wheat"
        assert "July" in period

    def test_extract_tables_from_pipe_delimited(self, logger):
        """Extract a simple pipe-delimited table."""
        text = """
Trade note: Orvan to Midgard, wheat, July to December 2026

Month | Volume (tonnes) | Value (M crowns)
July  | 12000          | 4.8
Aug   | 11500          | 4.6
Sep   | 3200           | 1.3
Oct   | 2800           | 1.1
Nov   | 2500           | 1.0
Dec   | 2200           | 0.9
"""
        meta = {
            "DOC_ID": "TEST-001",
            "TITLE": "Trade note: Orvan to Midgard, wheat, July to December 2026",
            "SOURCE_NAME": "Test",
            "PUB_DATE": "2027-01-19",
            "COUNTRY": "Midgard",
            "SECTOR": "Wheat",
        }
        tables = extract_trade_tables("TEST-001", text, meta, logger)
        assert len(tables) > 0
        assert tables[0]["origin"] == "Orvan"
        assert tables[0]["destination"] == "Midgard"
        assert len(tables[0]["rows"]) >= 3

    def test_empty_document_returns_no_tables(self, logger):
        """Empty document should return no tables."""
        tables = extract_trade_tables("EMPTY-001", "", {}, logger)
        assert tables == []

    def test_no_tables_in_prose(self, logger):
        """Prose without table structure should return no tables."""
        text = ("The grain corridor has been a vital trade link. "
                "Without it, shipments drop significantly. "
                "Millers in Midgard are looking for alternatives.")
        tables = extract_trade_tables("PROSE-001", text, {}, logger)
        assert tables == []
