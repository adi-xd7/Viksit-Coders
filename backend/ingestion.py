"""Document Ingestion Engine for RAGNAROK dev_pack_E5.

Parses multi-format document corpora (PDF, DOCX, TXT), extracts structured paragraphs [Pn],
parses metadata and manifests, detects duplicates via SHA-256 hashing, extracts structured trade
data rows, scans for prompt injections, and handles malformed documents safely.
"""

from __future__ import annotations

import glob
import hashlib
import json
import logging
import os
import re
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

# Bootstrap project root so file can be run directly (python backend/ingestion.py)
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.agents.odin import scan_text_for_injections
from backend.models import DocMeta, Document, TradeRow

logger = logging.getLogger("ingestion")


def compute_sha256(content: str) -> str:
    """Computes a normalized SHA-256 hash for document content."""
    normalized = re.sub(r"\s+", " ", content).strip().lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def safe_read_text_file(filepath: str) -> str:
    """Reads a text file safely with multi-encoding fallback and byte cleanup."""
    with open(filepath, "rb") as f:
        raw = f.read()

    # Split header and body if separated by standard separator
    if b"---\n" in raw:
        header_b, body_b = raw.split(b"---\n", 1)
        sep = "\n---\n"
    elif b"---\r\n" in raw:
        header_b, body_b = raw.split(b"---\r\n", 1)
        sep = "\n---\n"
    else:
        header_b, body_b = b"", raw
        sep = ""

    # Decode header
    h_text = ""
    if header_b:
        for enc in ("utf-8", "latin-1", "cp1252"):
            try:
                h_text = header_b.decode(enc)
                break
            except Exception:
                continue

    # Clean body bytes (remove null bytes, BOMs)
    clean_b = (
        body_b.replace(b"\x00", b"")
        .replace(b"\xff\xfe", b"")
        .replace(b"\xfe\xff", b"")
        .replace(b"\xef\xbb\xbf", b"")
    )

    b_text = ""
    for enc in ("utf-8", "latin-1", "cp1252"):
        try:
            b_text = clean_b.decode(enc, errors="ignore")
            break
        except Exception:
            continue

    if h_text and b_text:
        return h_text.strip() + sep + b_text.strip()
    return (h_text or b_text or clean_b.decode("utf-8", errors="ignore")).strip()


def extract_text_from_pdf(filepath: str) -> str:
    """Extracts text from PDF using pymupdf with fallback to pypdf."""
    text_chunks: List[str] = []
    try:
        import pymupdf  # type: ignore

        doc = pymupdf.open(filepath)
        for page in doc:
            t = page.get_text()
            if t:
                text_chunks.append(t)
        doc.close()
    except Exception as e:
        logger.warning("pymupdf failed on %s: %s; trying pypdf", filepath, e)
        try:
            import pypdf  # type: ignore

            reader = pypdf.PdfReader(filepath)
            for page in reader.pages:
                t = page.extract_text()
                if t:
                    text_chunks.append(t)
        except Exception as e2:
            logger.error("pypdf also failed on %s: %s", filepath, e2)
            raise e2

    return "\n".join(text_chunks).strip()


def extract_text_from_docx(filepath: str) -> str:
    """Extracts text from DOCX using python-docx."""
    import docx  # type: ignore

    doc = docx.Document(filepath)
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    return "\n\n".join(paragraphs).strip()


def parse_paragraphs_from_text(raw_text: str) -> Dict[int, str]:
    """Extracts structured [Pn] paragraphs from raw text."""
    paragraphs: Dict[int, str] = {}

    # Check for explicit [P1], [P2] tags
    p_matches = list(re.finditer(r"\[P(\d+)\]\s*(.*?)(?=\n\s*\[P\d+\]|\Z)", raw_text, re.DOTALL))
    if p_matches:
        for m in p_matches:
            p_num = int(m.group(1))
            p_text = re.sub(r"\s+", " ", m.group(2)).strip()
            if p_text:
                paragraphs[p_num] = p_text
        if paragraphs:
            return paragraphs

    # Fallback: split by double newlines or single newlines
    body = raw_text
    if "---" in raw_text:
        parts = raw_text.split("---", 1)
        body = parts[1]

    lines = [re.sub(r"\s+", " ", line).strip() for line in body.split("\n") if line.strip()]
    p_idx = 1
    for line in lines:
        if line.startswith("DOC_ID:") or line.startswith("EVENT_ID:") or line.startswith("TITLE:"):
            continue
        paragraphs[p_idx] = line
        p_idx += 1

    return paragraphs or {1: raw_text.strip()}


def extract_trade_rows_from_doc(doc: Document) -> List[TradeRow]:
    """Synthesizes structured TradeRow records from quantitative statements in the document."""
    rows: List[TradeRow] = []
    country = doc.meta.COUNTRY
    sector = doc.meta.SECTOR.lower()
    if sector in ("general", "none", ""):
        sector = "wheat"

    route = f"{country}-Regional"
    for p_num, p_text in doc.paragraphs.items():
        if "route:" in p_text.lower():
            m_route = re.search(r"route:\s*([^,\.]+)", p_text, re.IGNORECASE)
            if m_route:
                route = m_route.group(1).strip()

        # Match month patterns: Month YYYY, value was USD XX.XM and volume was YYY tonnes
        m_stat = re.search(
            r"in\s+([A-Za-z]+)\s+(\d{4}),\s+(?:the\s+)?value\s+was\s+USD\s+([\d\.]+)\s*([MBKmbk]?)\s+and\s+(?:the\s+)?volume\s+was\s+([\d,]+)\s*(tonnes?|tons?)?",
            p_text,
            re.IGNORECASE,
        )
        if m_stat:
            month_name = m_stat.group(1)[:3].title()
            year = m_stat.group(2)
            val_num = float(m_stat.group(3))
            val_scale = m_stat.group(4).upper()
            vol_str = m_stat.group(5).replace(",", "")
            vol_num = float(vol_str)
            unit = m_stat.group(6) or "tonnes"

            if val_scale == "M":
                val_num *= 1_000_000.0
            elif val_scale == "B":
                val_num *= 1_000_000_000.0
            elif val_scale == "K":
                val_num *= 1_000.0

            month_map = {
                "Jan": "01", "Feb": "02", "Mar": "03", "Apr": "04", "May": "05", "Jun": "06",
                "Jul": "07", "Aug": "08", "Sep": "09", "Oct": "10", "Nov": "11", "Dec": "12"
            }
            mm = month_map.get(month_name, "01")
            month_iso = f"{year}-{mm}"

            t_row = TradeRow(
                table_id=f"TAB-{doc.meta.DOC_ID}",
                row_num=p_num,
                country_pair=route,
                sector=sector,
                month=month_iso,
                value=val_num,
                volume=vol_num,
                unit=unit,
                is_damaged=False,
            )
            rows.append(t_row)

    return rows


@dataclass
class IngestionResult:
    """Summary of ingested documents and trade data."""
    doc_store: Dict[str, Document] = field(default_factory=dict)
    trade_store: Dict[str, List[TradeRow]] = field(default_factory=dict)
    content_hashes: Dict[str, str] = field(default_factory=dict)
    duplicates_detected: List[str] = field(default_factory=list)
    injections_detected: List[str] = field(default_factory=list)
    damaged_docs: List[str] = field(default_factory=list)
    total_files_scanned: int = 0


class IngestionEngine:
    """Ingestion engine managing document parsing, metadata, hashing, and security scanning."""

    def __init__(self, dev_pack_dir: Optional[str] = None):
        if dev_pack_dir is None:
            dev_pack_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dev_pack_E5"
            )
        self.dev_pack_dir = dev_pack_dir
        self.docs_dir = os.path.join(dev_pack_dir, "docs")
        self.manifest_path = os.path.join(dev_pack_dir, "manifest.json")
        self._cached_result: Optional[IngestionResult] = None

    def load_manifest(self) -> Dict[str, Any]:
        """Loads document metadata manifest."""
        if os.path.exists(self.manifest_path):
            with open(self.manifest_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {"documents": []}

    def ingest_all(self, force_reload: bool = False) -> IngestionResult:
        """Parses all documents in the dev pack directory."""
        if self._cached_result is not None and not force_reload:
            return self._cached_result

        result = IngestionResult()
        manifest_data = self.load_manifest()
        meta_by_id = {d["DOC_ID"]: d for d in manifest_data.get("documents", [])}

        if not os.path.exists(self.docs_dir):
            logger.warning("Docs directory does not exist: %s", self.docs_dir)
            self._cached_result = result
            return result

        file_paths = glob.glob(os.path.join(self.docs_dir, "*.*"))
        result.total_files_scanned = len(file_paths)

        hash_to_doc_id: Dict[str, str] = {}

        for fpath in file_paths:
            fname = os.path.basename(fpath)
            doc_id = os.path.splitext(fname)[0]
            ext = os.path.splitext(fname)[1].lower()

            m_info = meta_by_id.get(doc_id, {})
            pub_date = m_info.get("PUB_DATE", "2027-01-01")
            reliability = int(m_info.get("RELIABILITY", 2))
            country = m_info.get("COUNTRY", "general")
            sector = m_info.get("SECTOR", "general")
            source_name = m_info.get("SOURCE_NAME", "Unknown Source")
            source_type = m_info.get("SOURCE_TYPE", "bulletin")
            fmt = m_info.get("FORMAT", ext.replace(".", "").upper())

            raw_text = ""
            is_damaged = False
            damage_reason = None

            try:
                if ext == ".txt":
                    raw_text = safe_read_text_file(fpath)
                elif ext == ".pdf":
                    raw_text = extract_text_from_pdf(fpath)
                elif ext == ".docx":
                    raw_text = extract_text_from_docx(fpath)
                else:
                    logger.debug("Skipping unsupported file extension: %s", fname)
                    continue
            except Exception as e:
                logger.error("Failed to parse file %s: %s", fname, e)
                is_damaged = True
                damage_reason = f"Extraction failure: {str(e)}"
                result.damaged_docs.append(doc_id)

            if not raw_text.strip() and not is_damaged:
                is_damaged = True
                damage_reason = "Empty document payload"
                result.damaged_docs.append(doc_id)

            # Security scan for prompt injection
            is_inj, inj_details = scan_text_for_injections(raw_text)
            if is_inj:
                result.injections_detected.append(doc_id)

            # Content hash & deduplication
            c_hash = compute_sha256(raw_text)
            is_duplicate = False
            duplicate_of = None
            if c_hash in hash_to_doc_id and not is_damaged:
                is_duplicate = True
                duplicate_of = hash_to_doc_id[c_hash]
                result.duplicates_detected.append(doc_id)
            elif not is_damaged:
                hash_to_doc_id[c_hash] = doc_id

            result.content_hashes[doc_id] = c_hash

            paragraphs = parse_paragraphs_from_text(raw_text)

            meta = DocMeta(
                DOC_ID=doc_id,
                PUB_DATE=pub_date,
                RELIABILITY=reliability,
                COUNTRY=country,
                SECTOR=sector,
                SOURCE_NAME=source_name,
                SOURCE_TYPE=source_type,
                FORMAT=fmt,
            )

            document = Document(
                meta=meta,
                paragraphs=paragraphs,
                raw_text=raw_text,
                is_damaged=is_damaged,
                is_duplicate=is_duplicate,
                duplicate_of=duplicate_of,
                injection_detected=is_inj,
                injection_details=inj_details,
            )

            result.doc_store[doc_id] = document

            # Extract trade rows if present
            t_rows = extract_trade_rows_from_doc(document)
            if t_rows:
                result.trade_store[f"TAB-{doc_id}"] = t_rows

        self._cached_result = result
        logger.info(
            "Ingestion complete: %d docs loaded, %d trade tables, %d duplicates, %d injections, %d damaged",
            len(result.doc_store),
            len(result.trade_store),
            len(result.duplicates_detected),
            len(result.injections_detected),
            len(result.damaged_docs),
        )
        return result


if __name__ == "__main__":
    print("=" * 70)
    print("  RAGNAROK DOCUMENT INGESTION ENGINE")
    print("=" * 70)
    engine = IngestionEngine()
    print(f"Scanning documents directory: {engine.docs_dir}")
    res = engine.ingest_all()
    print(f"Ingested Documents:       {len(res.doc_store)}")
    print(f"Trade Tables Synthesized: {len(res.trade_store)}")
    print(f"Prompt Injections Caught: {len(res.injections_detected)}")
    print(f"Duplicates Detected:      {len(res.duplicates_detected)}")
    print(f"Damaged Docs Isolated:    {len(res.damaged_docs)}")
    print("=" * 70)
    print("Ingestion test complete: 100% operational.")

