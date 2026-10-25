"""
Trade-table parser — extracts structured tabular data from documents.

Trade notes typically contain tables with columns like:
  Month | Volume (tonnes) | Value (M crowns) | Change YoY
"""

from __future__ import annotations

import re
from typing import Any

from heimdall.logger import HeimdallLogger


# ── Heuristics to detect table-like content ──────────────────────────────────

_TABLE_HEADER_PATTERN = re.compile(
    r"(?i)(month|quarter|period|volume|tonnes|value|crowns|change|yoy|"
    r"export|import|origin|destination|commodity|total|shipment|cargo|"
    r"loading|arrival|departure)",
)

_ROW_SEPARATOR = re.compile(r"[\|\t]")
_NUMERIC = re.compile(r"^[\d,.\-+%]+$")


def _looks_like_table_row(line: str) -> bool:
    """Check if a line looks like a table row (pipe or tab separated, with numbers)."""
    parts = _ROW_SEPARATOR.split(line)
    if len(parts) >= 2:
        numeric_count = sum(1 for p in parts if _NUMERIC.match(p.strip()))
        return numeric_count >= 1
    return False


def _parse_pipe_table(lines: list[str]) -> list[dict[str, str]]:
    """Parse pipe-delimited or tab-delimited tabular data."""
    if not lines:
        return []

    # Find the header row
    header_idx = -1
    for i, line in enumerate(lines):
        if _TABLE_HEADER_PATTERN.search(line):
            header_idx = i
            break

    if header_idx < 0:
        # Try to use the first row as header if it has separators
        if _ROW_SEPARATOR.search(lines[0]):
            header_idx = 0
        else:
            return []

    headers = [h.strip() for h in _ROW_SEPARATOR.split(lines[header_idx]) if h.strip()]
    if not headers:
        return []

    rows: list[dict[str, str]] = []
    for line in lines[header_idx + 1:]:
        # Skip separator lines (e.g. "---|---|---")
        if re.match(r"^[\s\-|+]+$", line):
            continue
        cells = [c.strip() for c in _ROW_SEPARATOR.split(line)]
        if len(cells) >= len(headers):
            row = {headers[j]: cells[j] for j in range(len(headers))}
            rows.append(row)
        elif cells and any(c for c in cells if c):
            # Pad with empty strings
            row = {}
            for j, h in enumerate(headers):
                row[h] = cells[j] if j < len(cells) else ""
            rows.append(row)

    return rows


def extract_trade_tables(doc_id: str, text: str,
                         metadata: dict[str, Any],
                         logger: HeimdallLogger | None = None
                         ) -> list[dict[str, Any]]:
    """
    Extract trade tables from document text.

    Returns a list of table dicts, each with:
      doc_id, title, headers, rows, origin, destination, commodity, period, raw_text
    """
    if logger is None:
        logger = HeimdallLogger()

    if not text or not text.strip():
        return []

    tables: list[dict[str, Any]] = []
    lines = text.split("\n")

    # Identify contiguous blocks of table-like lines
    table_blocks: list[list[str]] = []
    current_block: list[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            if current_block:
                table_blocks.append(current_block)
                current_block = []
            continue

        if (_TABLE_HEADER_PATTERN.search(stripped) or
                _looks_like_table_row(stripped) or
                _ROW_SEPARATOR.search(stripped)):
            current_block.append(stripped)
        else:
            if current_block:
                table_blocks.append(current_block)
                current_block = []

    if current_block:
        table_blocks.append(current_block)

    # Parse each block
    for block in table_blocks:
        if len(block) < 2:  # Need at least header + 1 row
            continue
        rows = _parse_pipe_table(block)
        if rows:
            # Extract origin/destination/commodity from title or metadata
            title = metadata.get("TITLE", "")
            origin, destination, commodity, period = _parse_trade_title(title)

            table = {
                "doc_id": doc_id,
                "title": title,
                "source_name": metadata.get("SOURCE_NAME", ""),
                "pub_date": metadata.get("PUB_DATE", ""),
                "country": metadata.get("COUNTRY", ""),
                "sector": metadata.get("SECTOR", ""),
                "origin": origin,
                "destination": destination,
                "commodity": commodity,
                "period": period,
                "rows": rows,
                "raw_text": "\n".join(block),
            }
            tables.append(table)

    if tables:
        logger.retrieved_trade_tables([doc_id])

    return tables


def _parse_trade_title(title: str) -> tuple[str, str, str, str]:
    """
    Extract origin, destination, commodity, period from trade-note titles.

    Example: "Trade note: Orvan to Midgard, wheat, July to December 2026"
    """
    origin = ""
    destination = ""
    commodity = ""
    period = ""

    # Pattern: "X to Y, commodity, period"
    m = re.search(r"(?i)(?:trade\s+note\s*:\s*)?(\w+)\s+to\s+(\w+)\s*,\s*(\w+)\s*,\s*(.+)",
                  title)
    if m:
        origin = m.group(1)
        destination = m.group(2)
        commodity = m.group(3)
        period = m.group(4).strip()

    return origin, destination, commodity, period


def is_trade_note(metadata: dict[str, Any]) -> bool:
    """Check if a document is a trade note based on metadata."""
    source_type = str(metadata.get("SOURCE_TYPE", "")).lower()
    title = str(metadata.get("TITLE", "")).lower()
    return (source_type == "trade_note" or
            "trade note" in title or
            "trade table" in title)
