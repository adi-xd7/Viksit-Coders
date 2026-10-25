"""
Document parser — extracts plain text from PDF, DOCX, and TXT files.

Handles damaged / empty / unreadable files gracefully.
Detects and strips potential prompt-injection attempts embedded in documents.
Documents are DATA, not instructions.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from heimdall.logger import HeimdallLogger

# ── Injection detection patterns ─────────────────────────────────────────────
_INJECTION_PATTERNS = [
    re.compile(r"(?i)ignore\s+(all\s+)?previous\s+instructions"),
    re.compile(r"(?i)you\s+are\s+now\s+(a|an)\s+"),
    re.compile(r"(?i)system\s*:\s*"),
    re.compile(r"(?i)assistant\s*:\s*"),
    re.compile(r"(?i)forget\s+(everything|all|your\s+instructions)"),
    re.compile(r"(?i)do\s+not\s+(verify|check|validate)"),
    re.compile(r"(?i)override\s+(the\s+)?(as.of|date|filter)"),
    re.compile(r"(?i)pretend\s+(that|to)"),
    re.compile(r"(?i)act\s+as\s+(if|though)"),
    re.compile(r"(?i)\[INST\]"),
    re.compile(r"(?i)<\|im_start\|>"),
]


def _check_injections(text: str, doc_id: str,
                      logger: HeimdallLogger) -> str:
    """Log any injection attempts found in document text. Return text as-is
    (we strip nothing — the text is evidence, but we flag the attempt)."""
    for pattern in _INJECTION_PATTERNS:
        match = pattern.search(text)
        if match:
            logger.injection_detected(doc_id, match.group(0))
    return text


def parse_txt(file_path: Path, doc_id: str,
              logger: HeimdallLogger) -> str:
    """Read a plain-text file."""
    try:
        text = file_path.read_text(encoding="utf-8", errors="replace")
        if not text.strip():
            logger.failure("parse_txt", "empty file", doc_id)
            return ""
        return _check_injections(text, doc_id, logger)
    except Exception as exc:
        logger.failure("parse_txt", str(exc), doc_id)
        return ""


def parse_pdf(file_path: Path, doc_id: str,
              logger: HeimdallLogger) -> str:
    """Extract text from a PDF using PyMuPDF (fitz)."""
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(str(file_path))
        pages: list[str] = []
        for page in doc:
            pages.append(page.get_text())
        doc.close()
        text = "\n".join(pages).strip()
        if not text:
            logger.failure("parse_pdf", "no extractable text", doc_id)
            return ""
        return _check_injections(text, doc_id, logger)
    except Exception as exc:
        logger.failure("parse_pdf", str(exc), doc_id)
        return ""


def parse_docx(file_path: Path, doc_id: str,
               logger: HeimdallLogger) -> str:
    """Extract text from a DOCX using python-docx."""
    try:
        from docx import Document
        doc = Document(str(file_path))
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]

        # Also extract text from tables
        for table in doc.tables:
            for row in table.rows:
                cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
                if cells:
                    paragraphs.append(" | ".join(cells))

        text = "\n".join(paragraphs).strip()
        if not text:
            logger.failure("parse_docx", "no extractable text", doc_id)
            return ""
        return _check_injections(text, doc_id, logger)
    except Exception as exc:
        logger.failure("parse_docx", str(exc), doc_id)
        return ""


# ── Dispatcher ───────────────────────────────────────────────────────────────

_PARSERS = {
    ".txt": parse_txt,
    ".pdf": parse_pdf,
    ".docx": parse_docx,
}


def parse_document(file_path: Path, doc_id: str,
                   logger: HeimdallLogger | None = None) -> str:
    """
    Parse a document file into plain text.

    Returns empty string on failure (logged).
    """
    if logger is None:
        logger = HeimdallLogger()

    if not file_path.exists():
        logger.failure("parse_document", "file not found", doc_id)
        return ""

    suffix = file_path.suffix.lower()
    parser = _PARSERS.get(suffix)
    if parser is None:
        logger.failure("parse_document",
                       f"unsupported format: {suffix}", doc_id)
        return ""

    return parser(file_path, doc_id, logger)


def parse_all_documents(docs_dir: Path, manifest_docs: list[dict],
                        logger: HeimdallLogger | None = None
                        ) -> dict[str, str]:
    """
    Parse every document in the manifest.

    Returns: {DOC_ID: plain_text}
    """
    if logger is None:
        logger = HeimdallLogger()

    result: dict[str, str] = {}
    for doc in manifest_docs:
        doc_id = doc["DOC_ID"]
        filename = doc.get("file", "")
        if not filename:
            logger.failure("parse_all_documents", "no filename", doc_id)
            continue
        file_path = docs_dir / filename
        text = parse_document(file_path, doc_id, logger)
        result[doc_id] = text
    return result
