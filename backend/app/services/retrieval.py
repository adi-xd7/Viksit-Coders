"""Retrieval services: Base interface, Mock service for unit tests, and Runemark corpus reader."""

import os
import re
import json
import zipfile
import xml.etree.ElementTree as ET
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Optional
from backend.app.schemas.evidence import Document
from backend.app.services.citations import CitationValidator


class BaseRetrievalService(ABC):
    """Abstract retrieval contract to be shared across all RAGNAROK agents."""

    @abstractmethod
    def search(
        self,
        query: str,
        as_of_date: str,
        filters: Optional[dict[str, Any]] = None,
        limit: int = 10,
    ) -> list[Document]:
        """Search corpus respecting the as-of cutoff date and metadata filters."""
        pass

    @abstractmethod
    def get_document(self, doc_id: str, as_of_date: Optional[str] = None) -> Optional[Document]:
        """Fetch a specific document by its permanent ID."""
        pass


class MockRetrievalService(BaseRetrievalService):
    """
    Clearly labelled mock retrieval service for unit testing.
    Uses mock fixtures with no dependency on local disk paths or external APIs.
    """

    def __init__(self, documents: Optional[list[Document]] = None, simulate_failure: bool = False):
        self.documents: dict[str, Document] = {}
        self.simulate_failure = simulate_failure
        if documents:
            for doc in documents:
                self.documents[doc.doc_id] = doc

    def add_document(self, doc: Document) -> None:
        self.documents[doc.doc_id] = doc

    def search(
        self,
        query: str,
        as_of_date: str,
        filters: Optional[dict[str, Any]] = None,
        limit: int = 10,
    ) -> list[Document]:
        if self.simulate_failure:
            raise ConnectionError("Mock retrieval service simulated network/index failure")

        results = []
        tokens = [t.lower() for t in query.split() if len(t) > 2]
        filters = filters or {}

        for doc in self.documents.values():
            # 1. As-of date enforcement
            if CitationValidator.is_clock_violation(doc.pub_date, as_of_date):
                continue

            # 2. Metadata filtering
            if "country" in filters and filters["country"].lower() != doc.country.lower():
                continue
            if "sector" in filters and filters["sector"].lower() != doc.sector.lower():
                continue
            if "event_id" in filters and filters["event_id"].lower() != doc.event_id.lower():
                continue
            if "min_tier" in filters and doc.reliability_tier > filters["min_tier"]:
                continue

            # 3. Text match
            content_lower = doc.content.lower() + " " + doc.title.lower()
            if not tokens or any(t in content_lower for t in tokens):
                results.append(doc)

        results.sort(key=lambda d: d.doc_id)
        return results[:limit]

    def get_document(self, doc_id: str, as_of_date: Optional[str] = None) -> Optional[Document]:
        if self.simulate_failure:
            raise ConnectionError("Mock retrieval service failure")
        doc = self.documents.get(doc_id)
        if doc and as_of_date and CitationValidator.is_clock_violation(doc.pub_date, as_of_date):
            return None
        return doc


class RunemarkCorpusRetrievalService(BaseRetrievalService):
    """
    Real local retrieval service that indexes and searches dev_pack_E5/docs.
    Handles PDF, TXT (including UTF-16 BOM traps), DOCX, empty files, and metadata headers.
    """

    def __init__(self, pack_dir: str):
        self.pack_dir = Path(pack_dir)
        self.docs_dir = self.pack_dir / "docs"
        self.manifest_path = self.pack_dir / "manifest.json"
        self.index: dict[str, Document] = {}
        self._load_corpus()

    def _load_corpus(self) -> None:
        if not self.docs_dir.exists():
            return

        # 1. Load manifest metadata
        manifest_meta: dict[str, dict[str, Any]] = {}
        if self.manifest_path.exists():
            try:
                with open(self.manifest_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for item in data.get("documents", []):
                        doc_id = item.get("DOC_ID") or item.get("doc_id")
                        if doc_id:
                            manifest_meta[doc_id] = item
            except Exception:
                pass

        # 2. Ingest document files in deterministic sorted order
        for fpath in sorted(self.docs_dir.iterdir()):
            doc_id = fpath.stem
            ext = fpath.suffix.lower()

            try:
                content = self._extract_file_content(fpath, ext)
            except Exception:
                content = ""

            meta = manifest_meta.get(doc_id, {})
            # Header parsing fallback if manifest not available or incomplete
            header_meta = self._parse_header(content)

            title = meta.get("TITLE") or meta.get("title") or header_meta.get("TITLE", doc_id)
            event_id = meta.get("EVENT_ID") or meta.get("event_id") or header_meta.get("EVENT_ID", "NONE")
            source_name = meta.get("SOURCE_NAME") or meta.get("source_name") or header_meta.get("SOURCE_NAME", "Unknown")
            source_type = meta.get("SOURCE_TYPE") or meta.get("source_type") or header_meta.get("SOURCE_TYPE", "news")
            rel_val = meta.get("RELIABILITY") or meta.get("reliability") or header_meta.get("RELIABILITY", 3)
            try:
                reliability = int(rel_val)
            except (ValueError, TypeError):
                reliability = 3
            pub_date = meta.get("PUB_DATE") or meta.get("pub_date") or header_meta.get("PUB_DATE", "2024-01-01")
            pub_time = meta.get("PUB_TIME") or meta.get("pub_time") or header_meta.get("PUB_TIME")
            country = meta.get("COUNTRY") or meta.get("country") or header_meta.get("COUNTRY", "Unknown")
            sector = meta.get("SECTOR") or meta.get("sector") or header_meta.get("SECTOR", "general")
            fmt = ext.replace(".", "").upper()

            # Sanitize content from prompt injections
            sanitized_content, _ = CitationValidator.sanitize_content(content)
            paragraphs = self._extract_paragraphs(sanitized_content)

            self.index[doc_id] = Document(
                doc_id=doc_id,
                event_id=event_id,
                title=title,
                source_name=source_name,
                source_type=source_type,
                reliability_tier=reliability,
                pub_date=pub_date,
                pub_time=pub_time,
                country=country,
                sector=sector,
                language="en",
                format=fmt,
                file_path=str(fpath),
                content=sanitized_content,
                paragraphs=paragraphs,
            )

    def _extract_file_content(self, fpath: Path, ext: str) -> str:
        if ext == ".txt":
            # Handle corrupt/mixed encodings like ORV-0007 (UTF-8 header + UTF-16 body)
            with open(fpath, "rb") as f:
                raw = f.read()
            if not raw:
                return ""
            try:
                return raw.decode("utf-8")
            except UnicodeDecodeError:
                # Check for UTF-16 LE BOM
                if b"\xff\xfe" in raw:
                    idx = raw.find(b"\xff\xfe")
                    header = raw[:idx].decode("utf-8", errors="replace")
                    body = raw[idx + 2:].decode("utf-16le", errors="replace")
                    return header + body
                return raw.decode("latin-1", errors="replace")

        elif ext == ".docx":
            try:
                with zipfile.ZipFile(fpath) as z:
                    xml_content = z.read("word/document.xml")
                    tree = ET.fromstring(xml_content)
                    return "".join(tree.itertext())
            except Exception:
                return ""

        elif ext == ".pdf":
            # Attempt to extract text strings from PDF without external dependency
            with open(fpath, "rb") as f:
                raw = f.read()
            if not raw:
                return ""
            # Extract printable ASCII / text streams
            text_chunks = re.findall(rb"\(([^\)]+)\)", raw)
            if text_chunks:
                decoded = []
                for chunk in text_chunks:
                    try:
                        decoded.append(chunk.decode("latin-1", errors="ignore"))
                    except Exception:
                        pass
                if len(decoded) > 5:
                    return " ".join(decoded)
            return raw.decode("latin-1", errors="ignore")

        return ""

    def _parse_header(self, content: str) -> dict[str, str]:
        meta = {}
        for line in content.splitlines()[:20]:
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip().upper()] = v.strip()
            if line.strip() == "---":
                break
        return meta

    def _extract_paragraphs(self, content: str) -> dict[str, str]:
        paragraphs: dict[str, str] = {}
        pattern = re.compile(r"\[(P\d+)\]\s*(.*?)(?=\[(?:P\d+)\]|\Z)", re.DOTALL)
        for match in pattern.finditer(content):
            p_id = match.group(1)
            p_text = match.group(2).strip()
            paragraphs[p_id] = p_text

        # Fallback if document content has no explicit [P\d+] markers
        if not paragraphs and content.strip():
            body = content.split("---", 1)[-1].strip() if "---" in content else content.strip()
            lines = [line.strip() for line in body.split("\n") if line.strip()]
            for idx, line in enumerate(lines, start=1):
                paragraphs[f"P{idx}"] = line

        return paragraphs

    def search(
        self,
        query: str,
        as_of_date: str,
        filters: Optional[dict[str, Any]] = None,
        limit: int = 10,
    ) -> list[Document]:
        results = []
        tokens = [t.lower() for t in query.split() if len(t) > 2]
        filters = filters or {}

        for doc in self.index.values():
            # 1. As-of date cutoff
            if CitationValidator.is_clock_violation(doc.pub_date, as_of_date):
                continue

            # 2. Metadata filters
            if "country" in filters and filters["country"].lower() != doc.country.lower():
                continue
            if "sector" in filters and filters["sector"].lower() != doc.sector.lower():
                continue
            if "event_id" in filters and filters["event_id"].lower() != doc.event_id.lower():
                continue
            if "max_tier" in filters and doc.reliability_tier > filters["max_tier"]:
                continue

            # 3. Keyword relevance scoring
            content_lower = doc.content.lower() + " " + doc.title.lower()
            matched_count = sum(1 for t in tokens if t in content_lower)
            if not tokens or matched_count > 0:
                results.append((matched_count, doc))

        # Sort by relevance score descending, with stable tie-breaking by doc_id ascending
        results.sort(key=lambda x: (-x[0], x[1].doc_id))
        return [doc for _, doc in results[:limit]]

    def get_document(self, doc_id: str, as_of_date: Optional[str] = None) -> Optional[Document]:
        doc = self.index.get(doc_id)
        if doc and as_of_date and CitationValidator.is_clock_violation(doc.pub_date, as_of_date):
            return None
        return doc
