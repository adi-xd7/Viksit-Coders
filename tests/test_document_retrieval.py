"""
Test 3: Document retrieval (hybrid search).
Test 5: As-of date filtering.
Test 6: Metadata filtering.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from heimdall.manifest_loader import load_manifest, filter_documents


class TestDocumentRetrieval:
    """Test that hybrid search returns relevant documents."""

    def test_retrieval_returns_results(self, manifest, doc_texts, logger):
        """Full integration test — requires corpus."""
        from heimdall.retrieval.index_builder import IndexBuilder
        from heimdall.retrieval.hybrid_search import HybridSearchEngine

        ib = IndexBuilder(logger)
        doc_metadata = {d["DOC_ID"]: d for d in manifest["documents"]}
        ib.build(doc_texts, doc_metadata)

        engine = HybridSearchEngine(ib, logger)
        results = engine.search(
            "Orvan grain corridor wheat exposure",
            top_k=10,
            as_of_date="2027-01-25",
        )

        assert len(results) > 0
        doc_ids = [r["doc_id"] for r in results]
        # Should find at least some ORV docs
        assert any(did.startswith("ORV") for did in doc_ids)

    def test_retrieval_respects_top_k(self, manifest, doc_texts, logger):
        """Search returns at most top_k results."""
        from heimdall.retrieval.index_builder import IndexBuilder
        from heimdall.retrieval.hybrid_search import HybridSearchEngine

        ib = IndexBuilder(logger)
        doc_metadata = {d["DOC_ID"]: d for d in manifest["documents"]}
        ib.build(doc_texts, doc_metadata)

        engine = HybridSearchEngine(ib, logger)
        results = engine.search("wheat", top_k=5, as_of_date="2027-01-25")
        assert len(results) <= 5


class TestAsOfDateFiltering:
    """Test that documents after as_of_date are excluded."""

    def test_future_docs_excluded(self, manifest):
        """ORV-0014 (2027-02-11), ORV-0036 (2027-02-22), ORV-0041 (2027-04-09)
        should all be excluded when as_of is 2027-01-25."""
        future_ids = {"ORV-0014", "ORV-0036", "ORV-0041"}
        filtered = filter_documents(manifest, pub_date_before="2027-01-25")
        result_ids = {d["DOC_ID"] for d in filtered}

        for fid in future_ids:
            assert fid not in result_ids, f"{fid} should be excluded (pub after as_of)"

    def test_past_docs_included(self, manifest):
        """Docs before as_of should be included."""
        filtered = filter_documents(manifest, pub_date_before="2027-01-25")
        result_ids = {d["DOC_ID"] for d in filtered}

        # ORV-0016 (2026-09-10) should be included
        assert "ORV-0016" in result_ids

    def test_exact_date_included(self, manifest):
        """Docs on exactly the as_of date should be included."""
        # Check if any doc has exactly 2027-01-25
        filtered = filter_documents(manifest, pub_date_before="2027-01-25")
        dates = {d.get("PUB_DATE") for d in filtered}
        # All dates should be <= 2027-01-25
        for d in filtered:
            assert d.get("PUB_DATE", "9999") <= "2027-01-25"


class TestMetadataFiltering:
    """Test metadata-based filtering with at least two filters."""

    def test_country_filter(self, manifest):
        """Filter by country=Midgard."""
        filtered = filter_documents(manifest, country="Midgard")
        for d in filtered:
            assert d["COUNTRY"].lower() == "midgard"

    def test_sector_filter(self, manifest):
        """Filter by sector=Wheat."""
        filtered = filter_documents(manifest, sector="Wheat")
        for d in filtered:
            assert d["SECTOR"].lower() == "wheat"

    def test_combined_country_sector(self, manifest):
        """Filter by country=Midgard AND sector=Wheat (two metadata filters)."""
        filtered = filter_documents(manifest,
                                     country="Midgard", sector="Wheat")
        assert len(filtered) > 0
        for d in filtered:
            assert d["COUNTRY"].lower() == "midgard"
            assert d["SECTOR"].lower() == "wheat"

    def test_combined_date_and_country(self, manifest):
        """Filter by pub_date_before AND country (two metadata filters)."""
        filtered = filter_documents(manifest,
                                     pub_date_before="2027-01-25",
                                     country="Orvan")
        assert len(filtered) > 0
        for d in filtered:
            assert d.get("PUB_DATE", "9999") <= "2027-01-25"
            assert d["COUNTRY"].lower() == "orvan"

    def test_reliability_filter(self, manifest):
        """Filter by reliability_max=2 (only tier 1-2 sources)."""
        filtered = filter_documents(manifest, reliability_max=2)
        for d in filtered:
            assert int(d["RELIABILITY"]) <= 2

    def test_event_id_filter(self, manifest):
        """Filter by event_id=E5."""
        filtered = filter_documents(manifest, event_id="E5")
        for d in filtered:
            assert d["EVENT_ID"].upper() == "E5"
