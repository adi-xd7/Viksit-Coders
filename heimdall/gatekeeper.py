"""
Heimdall – Gatekeeper: the main orchestrator.

Accepts a disruption question, searches Runemark, verifies the event,
and produces a structured Case File for the courtroom.

Heimdall does NOT:
  - Debate exposure (that's Thor / Loki)
  - Render judgments (that's Odin)
  - Act as a central planner
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import config
from heimdall.logger import HeimdallLogger
from heimdall.memory import HeimdallMemory
from heimdall.manifest_loader import load_manifest
from heimdall.document_parser import parse_all_documents
from heimdall.retrieval.index_builder import IndexBuilder
from heimdall.retrieval.hybrid_search import HybridSearchEngine
from heimdall.retrieval.trade_table_parser import (
    extract_trade_tables, is_trade_note,
)
from heimdall.event_verifier import EventVerifier
from heimdall.case_file import CaseFileBuilder
from interfaces.case_file_schema import CaseFile, VerificationStatus


class Gatekeeper:
    """
    Heimdall — the Gatekeeper of the RAGNAROK courtroom.

    Usage:
        gatekeeper = Gatekeeper()
        case_file = gatekeeper.investigate("As of 25 Jan 2027, how exposed ...")
        # Odin sends it back:
        case_file = gatekeeper.reinvestigate(case_file, reason="Need more evidence")
    """

    def __init__(self, manifest_path: Path | None = None,
                 docs_dir: Path | None = None,
                 logger: HeimdallLogger | None = None,
                 memory: HeimdallMemory | None = None):
        self.logger = logger or HeimdallLogger()
        self.memory = memory or HeimdallMemory(logger=self.logger)

        # Load manifest
        self.manifest = load_manifest(manifest_path)
        self.docs_dir = docs_dir or config.DOCS_DIR
        self.as_of_date = self.manifest.get("as_of", "2027-01-25")

        # Parse all documents
        self.logger.info("Parsing all documents from corpus")
        self.doc_texts = parse_all_documents(
            self.docs_dir, self.manifest["documents"], self.logger)
        self.logger.info(f"Parsed {len(self.doc_texts)} documents",
                         non_empty=sum(1 for v in self.doc_texts.values() if v))

        # Build or load indices
        self.index_builder = IndexBuilder(self.logger)
        if not self.index_builder.load():
            self.logger.info("Building indices from scratch")
            doc_metadata = {
                d["DOC_ID"]: d for d in self.manifest["documents"]
            }
            self.index_builder.build(self.doc_texts, doc_metadata)

        # Initialize search engine
        self.search_engine = HybridSearchEngine(self.index_builder,
                                                 self.logger)

        # Initialize other components
        self.verifier = EventVerifier(self.manifest, self.doc_texts,
                                      self.logger)
        self.case_builder = CaseFileBuilder(self.manifest, self.logger)

    # ── Main entry points ────────────────────────────────────────────────

    def investigate(self, question: str,
                    as_of_date: str | None = None) -> CaseFile:
        """
        Primary investigation: accept a question, search, verify, return Case File.

        This is the first-round entry point.
        """
        as_of = as_of_date or self._extract_as_of_date(question) or self.as_of_date
        self.logger.query(question, as_of, search_round=1)

        # 1. Extract search parameters from the question
        params = self._extract_search_params(question)

        # 2. Search for relevant documents
        search_results = self.search_engine.search(
            query=question,
            top_k=config.HYBRID_TOP_K,
            as_of_date=as_of,
            country=params.get("country"),
            sector=params.get("sector"),
        )

        # Also do a broad search without country/sector filter
        broad_results = self.search_engine.search(
            query=question,
            top_k=config.HYBRID_TOP_K,
            as_of_date=as_of,
        )

        # Merge results (dedup by doc_id)
        all_results = self._merge_results(search_results, broad_results)

        # 3. Record in memory
        doc_ids = [r["doc_id"] for r in all_results]
        self.memory.record_search(question, doc_ids, search_round=1,
                                  filters=params)

        # 4. Extract trade tables
        trade_tables = self._extract_all_trade_tables(as_of)

        # 5. Verify the event
        event_id = self.manifest.get("event_id", "")
        verification = self.verifier.verify(event_id, as_of)

        # 6. Build Case File
        if verification.status == VerificationStatus.FAKE:
            self.logger.info("Event verification FAILED — not starting trial",
                             status=verification.status)

        case_file = self.case_builder.create(
            question=question,
            as_of_date=as_of,
            search_results=all_results,
            trade_tables=trade_tables,
            verification=verification,
            doc_texts=self.doc_texts,
            search_round=1,
        )

        return case_file

    def reinvestigate(self, case_file: CaseFile,
                      reason: str = "") -> CaseFile:
        """
        Re-search: called when Odin sends the case back for more evidence.

        Must return NEW/ADDITIONAL evidence, not the same results.
        """
        search_round = case_file.search_round + 1
        self.logger.research(reason, search_round,
                              self.memory.get_previously_returned_doc_ids())

        # Get previously returned doc IDs to exclude
        previous_ids = self.memory.get_previously_returned_doc_ids()

        # Reformulate queries for broader search
        reformulations = self._reformulate_query(case_file.question)

        all_new_results: list[dict[str, Any]] = []
        for query in reformulations:
            self.memory.record_reformulation(case_file.question, query)

            # Search with exclusions
            results = self.search_engine.search(
                query=query,
                top_k=config.HYBRID_TOP_K,
                as_of_date=case_file.as_of_date,
                exclude_doc_ids=previous_ids,
            )
            all_new_results = self._merge_results(all_new_results, results)

        # Also try with relaxed filters (different sector, broader scope)
        relaxed = self.search_engine.search(
            query=case_file.question,
            top_k=config.HYBRID_TOP_K,
            as_of_date=case_file.as_of_date,
            exclude_doc_ids=previous_ids,
        )
        all_new_results = self._merge_results(all_new_results, relaxed)

        # Record new results
        new_ids = [r["doc_id"] for r in all_new_results]
        self.memory.record_search(
            f"re-search: {reason}", new_ids,
            search_round=search_round,
        )

        # Extract new trade tables
        new_trade_tables = self._extract_all_trade_tables(
            case_file.as_of_date, exclude_doc_ids=set(
                t.doc_id for t in case_file.trade_tables))

        # Re-verify (might find new evidence)
        event_id = self.manifest.get("event_id", "")
        new_verification = self.verifier.verify(
            event_id, case_file.as_of_date)

        # Update Case File
        updated = self.case_builder.update(
            case_file=case_file,
            new_results=all_new_results,
            new_trade_tables=new_trade_tables,
            new_verification=new_verification,
            doc_texts=self.doc_texts,
            search_round=search_round,
        )

        return updated

    # ── Query analysis ───────────────────────────────────────────────────

    def _extract_as_of_date(self, question: str) -> str | None:
        """Try to extract an as-of date from the question text."""
        # Pattern: "as of DD Month YYYY" or "as of YYYY-MM-DD"
        patterns = [
            r"as\s+of\s+(\d{1,2})\s+(January|February|March|April|May|June|"
            r"July|August|September|October|November|December)\s+(\d{4})",
            r"as\s+of\s+(\d{4}-\d{2}-\d{2})",
        ]
        for pattern in patterns:
            m = re.search(pattern, question, re.IGNORECASE)
            if m:
                groups = m.groups()
                if len(groups) == 3:
                    day, month_name, year = groups
                    month_names = {
                        "january": "01", "february": "02", "march": "03",
                        "april": "04", "may": "05", "june": "06",
                        "july": "07", "august": "08", "september": "09",
                        "october": "10", "november": "11", "december": "12",
                    }
                    month = month_names.get(month_name.lower(), "01")
                    return f"{year}-{month}-{int(day):02d}"
                elif len(groups) == 1:
                    return groups[0]
        return None

    def _extract_search_params(self, question: str) -> dict[str, str]:
        """Extract metadata filter parameters from the question."""
        params: dict[str, str] = {}
        question_lower = question.lower()

        # Countries
        countries = ["Midgard", "Tolan", "Orvan", "Asgard", "Ravik",
                     "Utgard", "Valhalla", "Dorin", "Ymir", "Ketra",
                     "Vanir", "Solvar"]
        mentioned = [c for c in countries if c.lower() in question_lower]
        if len(mentioned) == 1:
            params["country"] = mentioned[0]
        # If multiple countries mentioned, don't filter by country
        # (let the search find docs for all)

        # Sectors
        sectors = ["wheat", "maize", "grain"]
        for s in sectors:
            if s in question_lower:
                params["sector"] = s.capitalize()
                break

        return params

    def _reformulate_query(self, original: str) -> list[str]:
        """Generate alternative queries for re-search."""
        reformulations = []

        # Broader version
        reformulations.append(
            f"trade disruption supply chain impact {original}"
        )

        # Focus on specific aspects
        reformulations.append(
            "corridor agreement expiry wheat grain export shipment "
            "Orvan Midgard Tolan"
        )

        reformulations.append(
            "alternative suppliers rail transport substitutes "
            "wheat grain port loading"
        )

        reformulations.append(
            "price impact market adjustment wheat flour bread "
            "import dependence"
        )

        return reformulations

    # ── Trade table extraction ───────────────────────────────────────────

    def _extract_all_trade_tables(
        self, as_of_date: str,
        exclude_doc_ids: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Extract trade tables from all trade-note documents."""
        exclude = exclude_doc_ids or set()
        all_tables: list[dict[str, Any]] = []

        for doc in self.manifest["documents"]:
            doc_id = doc["DOC_ID"]
            if doc_id in exclude:
                continue
            # Respect as-of date
            if doc.get("PUB_DATE", "9999-99-99") > as_of_date:
                continue
            if is_trade_note(doc):
                text = self.doc_texts.get(doc_id, "")
                tables = extract_trade_tables(
                    doc_id, text, doc, self.logger)
                all_tables.extend(tables)

        return all_tables

    # ── Result merging ───────────────────────────────────────────────────

    @staticmethod
    def _merge_results(existing: list[dict], new: list[dict]) -> list[dict]:
        """Merge two result lists, deduplicating by doc_id."""
        seen = {r["doc_id"] for r in existing}
        merged = list(existing)
        for r in new:
            if r["doc_id"] not in seen:
                seen.add(r["doc_id"])
                merged.append(r)
        return merged
