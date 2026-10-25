"""
Case File builder — constructs the structured Case File from Heimdall's
retrieval and verification outputs.

The Case File is the ONLY artifact Heimdall shares with the courtroom.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

import config
from heimdall.logger import HeimdallLogger
from interfaces.case_file_schema import (
    CaseFile, EventInfo, RetrievedDocument, TradeTable, VerificationResult,
)


class CaseFileBuilder:
    """Construct and update Case Files."""

    def __init__(self, manifest: dict[str, Any],
                 logger: HeimdallLogger | None = None):
        self.manifest = manifest
        self.logger = logger or HeimdallLogger()

    def create(
        self,
        question: str,
        as_of_date: str,
        search_results: list[dict[str, Any]],
        trade_tables: list[dict[str, Any]],
        verification: VerificationResult,
        doc_texts: dict[str, str],
        search_round: int = 1,
    ) -> CaseFile:
        """Build a new CaseFile from Heimdall's outputs."""
        now = datetime.now(timezone.utc).isoformat()

        # Extract event info from question and manifest
        event = self._extract_event_info(question, verification)

        # Build document list
        documents = self._build_documents(search_results, doc_texts)

        # Build trade table list
        tt_list = self._build_trade_tables(trade_tables)

        case_file = CaseFile(
            question=question,
            as_of_date=as_of_date,
            created_at=now,
            updated_at=now,
            search_round=search_round,
            event=event,
            documents=documents,
            trade_tables=tt_list,
            verification=verification,
            metadata={
                "pack": self.manifest.get("pack", ""),
                "total_docs_in_corpus": self.manifest.get("count", 0),
                "docs_retrieved": len(documents),
                "trade_tables_found": len(tt_list),
            },
        )

        self.logger.case_file_created(question, search_round)
        return case_file

    def update(self, case_file: CaseFile,
               new_results: list[dict[str, Any]],
               new_trade_tables: list[dict[str, Any]],
               new_verification: VerificationResult | None,
               doc_texts: dict[str, str],
               search_round: int) -> CaseFile:
        """Update an existing CaseFile with new evidence from re-search."""
        # Add new documents (avoid duplicates)
        existing_ids = {d.doc_id for d in case_file.documents}
        new_docs = self._build_documents(new_results, doc_texts)
        for doc in new_docs:
            if doc.doc_id not in existing_ids:
                case_file.documents.append(doc)

        # Add new trade tables
        existing_tt_ids = {t.doc_id for t in case_file.trade_tables}
        new_tts = self._build_trade_tables(new_trade_tables)
        for tt in new_tts:
            if tt.doc_id not in existing_tt_ids:
                case_file.trade_tables.append(tt)

        # Update verification if provided
        if new_verification:
            case_file.verification = new_verification

        case_file.search_round = search_round
        case_file.updated_at = datetime.now(timezone.utc).isoformat()
        case_file.metadata["docs_retrieved"] = len(case_file.documents)
        case_file.metadata["trade_tables_found"] = len(case_file.trade_tables)

        self.logger.case_file_updated("re-search", search_round)
        return case_file

    # ── Internal helpers ─────────────────────────────────────────────────

    def _extract_event_info(self, question: str,
                            verification: VerificationResult) -> EventInfo:
        """Extract structured event info from the question and manifest."""
        event_id = self.manifest.get("event_id", "")
        event_name = self.manifest.get("name", "")

        # Extract countries from the question
        countries = self._extract_entities(
            question,
            ["Midgard", "Tolan", "Orvan", "Asgard", "Ravik", "Utgard",
             "Valhalla", "Dorin", "Ymir", "Ketra", "Vanir", "Solvar"],
        )

        # Extract sectors
        sectors = self._extract_entities(
            question,
            ["wheat", "maize", "grain", "general"],
        )

        # Extract other useful entities
        entities = self._extract_entities(
            question,
            ["corridor", "agreement", "exposure", "trade", "port",
             "export", "import", "shipment"],
        )

        return EventInfo(
            event_id=event_id,
            name=event_name,
            description=question,
            countries=countries,
            sectors=sectors,
            entities=entities,
        )

    @staticmethod
    def _extract_entities(text: str, candidates: list[str]) -> list[str]:
        """Find which candidate strings appear in the text."""
        text_lower = text.lower()
        return [c for c in candidates if c.lower() in text_lower]

    def _build_documents(self, search_results: list[dict[str, Any]],
                         doc_texts: dict[str, str]) -> list[RetrievedDocument]:
        """Convert search result dicts into RetrievedDocument objects."""
        docs = []
        for result in search_results:
            doc_id = result["doc_id"]
            meta = result.get("metadata", {})

            # Get snippet (first 300 chars of the chunk text)
            snippet = result.get("text", "")[:300]

            reliability = int(meta.get("RELIABILITY", 4))

            doc = RetrievedDocument(
                doc_id=doc_id,
                title=meta.get("TITLE", ""),
                source_name=meta.get("SOURCE_NAME", ""),
                source_type=meta.get("SOURCE_TYPE", ""),
                reliability=reliability,
                pub_date=meta.get("PUB_DATE", ""),
                country=meta.get("COUNTRY", ""),
                sector=meta.get("SECTOR", ""),
                event_id=meta.get("EVENT_ID", ""),
                file_name=meta.get("file", ""),
                relevance_score=result.get("score", 0.0),
                snippet=snippet,
                is_unreliable=reliability >= config.UNRELIABLE_TIER,
                unreliability_reason=(
                    f"Tier-{reliability} source"
                    if reliability >= config.UNRELIABLE_TIER else ""
                ),
            )
            docs.append(doc)
        return docs

    @staticmethod
    def _build_trade_tables(
        raw_tables: list[dict[str, Any]]
    ) -> list[TradeTable]:
        """Convert raw trade-table dicts into TradeTable objects."""
        tables = []
        for t in raw_tables:
            tt = TradeTable(
                doc_id=t.get("doc_id", ""),
                title=t.get("title", ""),
                source_name=t.get("source_name", ""),
                pub_date=t.get("pub_date", ""),
                country=t.get("country", ""),
                sector=t.get("sector", ""),
                origin=t.get("origin", ""),
                destination=t.get("destination", ""),
                commodity=t.get("commodity", ""),
                period=t.get("period", ""),
                rows=t.get("rows", []),
                raw_text=t.get("raw_text", ""),
            )
            tables.append(tt)
        return tables
