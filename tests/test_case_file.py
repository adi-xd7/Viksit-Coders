"""
Test 10: Correct Case File generation.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from heimdall.case_file import CaseFileBuilder
from interfaces.case_file_schema import (
    CaseFile, VerificationResult, VerificationStatus,
)


class TestCaseFileGeneration:
    """Test that Case Files are correctly structured."""

    def test_case_file_has_required_fields(self, minimal_manifest, logger):
        """Case File must have all required top-level fields."""
        builder = CaseFileBuilder(minimal_manifest, logger)
        verification = VerificationResult(
            status=VerificationStatus.VERIFIED,
            confidence=0.85,
            reason="Test verification",
            supporting_doc_ids=["DOC-001"],
        )
        cf = builder.create(
            question="Test question?",
            as_of_date="2027-01-25",
            search_results=[{
                "doc_id": "DOC-001",
                "text": "Test snippet",
                "score": 0.9,
                "metadata": {
                    "TITLE": "Test", "SOURCE_NAME": "Test",
                    "SOURCE_TYPE": "gov_notice", "RELIABILITY": 1,
                    "PUB_DATE": "2026-09-10", "COUNTRY": "Orvan",
                    "SECTOR": "Wheat", "EVENT_ID": "E5", "file": "t.txt",
                },
            }],
            trade_tables=[],
            verification=verification,
            doc_texts={"DOC-001": "Test text"},
        )

        assert cf.question == "Test question?"
        assert cf.as_of_date == "2027-01-25"
        assert cf.created_at  # non-empty
        assert cf.search_round == 1
        assert cf.event is not None
        assert len(cf.documents) == 1
        assert cf.verification.status == VerificationStatus.VERIFIED

    def test_case_file_serialises_to_json(self, minimal_manifest, logger):
        """Case File must be JSON-serializable."""
        builder = CaseFileBuilder(minimal_manifest, logger)
        verification = VerificationResult(
            status=VerificationStatus.VERIFIED,
            confidence=0.7,
            reason="Confirmed",
            supporting_doc_ids=["DOC-001"],
        )
        cf = builder.create(
            question="Q?", as_of_date="2027-01-25",
            search_results=[], trade_tables=[],
            verification=verification, doc_texts={},
        )

        # Should not raise
        json_str = cf.to_json()
        data = json.loads(json_str)

        assert data["question"] == "Q?"
        assert data["as_of_date"] == "2027-01-25"
        assert data["verification"]["status"] == "verified"

    def test_case_file_roundtrip(self, minimal_manifest, logger):
        """CaseFile → JSON → CaseFile should preserve data."""
        builder = CaseFileBuilder(minimal_manifest, logger)
        verification = VerificationResult(
            status=VerificationStatus.VERIFIED,
            confidence=0.8, reason="Test",
        )
        cf1 = builder.create(
            question="Roundtrip?", as_of_date="2027-01-25",
            search_results=[], trade_tables=[],
            verification=verification, doc_texts={},
        )

        json_str = cf1.to_json()
        cf2 = CaseFile.from_json(json_str)

        assert cf2.question == cf1.question
        assert cf2.as_of_date == cf1.as_of_date
        assert cf2.verification.status == cf1.verification.status

    def test_case_file_update_adds_docs(self, minimal_manifest, logger):
        """Update should add new documents, not replace existing ones."""
        builder = CaseFileBuilder(minimal_manifest, logger)
        verification = VerificationResult(
            status=VerificationStatus.VERIFIED,
            confidence=0.7, reason="Init",
        )

        cf = builder.create(
            question="Q?", as_of_date="2027-01-25",
            search_results=[{
                "doc_id": "DOC-001", "text": "A", "score": 0.9,
                "metadata": {
                    "TITLE": "A", "SOURCE_NAME": "A",
                    "SOURCE_TYPE": "news", "RELIABILITY": 2,
                    "PUB_DATE": "2026-01-01", "COUNTRY": "Orvan",
                    "SECTOR": "Wheat", "EVENT_ID": "E5", "file": "a.txt",
                },
            }],
            trade_tables=[], verification=verification,
            doc_texts={"DOC-001": "Text A"},
        )

        assert len(cf.documents) == 1

        cf = builder.update(
            case_file=cf,
            new_results=[{
                "doc_id": "DOC-002", "text": "B", "score": 0.8,
                "metadata": {
                    "TITLE": "B", "SOURCE_NAME": "B",
                    "SOURCE_TYPE": "news", "RELIABILITY": 2,
                    "PUB_DATE": "2026-02-01", "COUNTRY": "Midgard",
                    "SECTOR": "Wheat", "EVENT_ID": "E5", "file": "b.txt",
                },
            }],
            new_trade_tables=[], new_verification=None,
            doc_texts={"DOC-002": "Text B"},
            search_round=2,
        )

        assert len(cf.documents) == 2
        assert cf.search_round == 2

    def test_case_file_events_extracted(self, minimal_manifest, logger):
        """Event info should be extracted from the question."""
        builder = CaseFileBuilder(minimal_manifest, logger)
        verification = VerificationResult(
            status=VerificationStatus.VERIFIED,
            confidence=0.8, reason="OK",
        )
        cf = builder.create(
            question="How exposed are Midgard and Tolan to the Orvan corridor wheat?",
            as_of_date="2027-01-25",
            search_results=[], trade_tables=[],
            verification=verification, doc_texts={},
        )

        assert "Midgard" in cf.event.countries
        assert "Tolan" in cf.event.countries
        assert "Orvan" in cf.event.countries
        assert "wheat" in [s.lower() for s in cf.event.sectors]
