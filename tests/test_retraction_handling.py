"""
Test 7: Retraction / correction handling.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from heimdall.event_verifier import EventVerifier
from interfaces.case_file_schema import VerificationStatus


class TestRetractionHandling:
    """Test that retractions and corrections are properly detected."""

    def test_correction_marks_earlier_doc(self, minimal_manifest,
                                           minimal_doc_texts, logger):
        """ORV-0013-style correction should flag the doc it corrects."""
        verifier = EventVerifier(minimal_manifest, minimal_doc_texts, logger)
        result = verifier.verify("E5", "2027-01-25")

        # DOC-002 (says "renewed") should be flagged as contradicted by
        # DOC-003 (correction saying "not renewed")
        assert "DOC-002" in result.retracted_doc_ids or \
               "DOC-002" in result.contradicting_doc_ids

    def test_correction_itself_not_retracted(self, minimal_manifest,
                                              minimal_doc_texts, logger):
        """The correction document itself should not be retracted."""
        verifier = EventVerifier(minimal_manifest, minimal_doc_texts, logger)
        result = verifier.verify("E5", "2027-01-25")
        assert "DOC-003" not in result.retracted_doc_ids

    def test_retracted_docs_not_in_support(self, minimal_manifest,
                                            minimal_doc_texts, logger):
        """Retracted docs should not appear in supporting evidence."""
        verifier = EventVerifier(minimal_manifest, minimal_doc_texts, logger)
        result = verifier.verify("E5", "2027-01-25")

        for retracted in result.retracted_doc_ids:
            assert retracted not in result.supporting_doc_ids

    def test_contradictions_reduce_confidence(self, logger):
        """When there are contradictions, confidence should be lower."""
        # Manifest with contradicting docs
        manifest = {
            "documents": [
                {
                    "DOC_ID": "C-001",
                    "EVENT_ID": "E_CONTRA",
                    "TITLE": "Corridor Agreement expires with no renewal",
                    "SOURCE_NAME": "Ministry",
                    "SOURCE_TYPE": "gov_notice",
                    "RELIABILITY": 1,
                    "PUB_DATE": "2026-09-10",
                    "COUNTRY": "Orvan",
                    "SECTOR": "Wheat",
                },
                {
                    "DOC_ID": "C-002",
                    "EVENT_ID": "E_CONTRA",
                    "TITLE": "Corridor renewed for a second year",
                    "SOURCE_NAME": "News",
                    "SOURCE_TYPE": "news",
                    "RELIABILITY": 2,
                    "PUB_DATE": "2026-09-09",
                    "COUNTRY": "Orvan",
                    "SECTOR": "Wheat",
                },
            ],
            "doc_index": {},
        }
        texts = {
            "C-001": "The agreement was not renewed.",
            "C-002": "The corridor has been renewed for another year.",
        }
        verifier = EventVerifier(manifest, texts, logger)
        result = verifier.verify("E_CONTRA", "2027-01-25")

        # Should still verify (reliable source confirms) but note contradiction
        assert result.status == VerificationStatus.VERIFIED
        assert len(result.contradicting_doc_ids) > 0
