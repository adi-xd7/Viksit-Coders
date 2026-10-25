"""
Test 1: Valid event verification.
Test 2: Fake / rumoured event detection.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from heimdall.event_verifier import EventVerifier
from interfaces.case_file_schema import VerificationStatus


class TestValidEventVerification:
    """Test that a real event (E5) is correctly verified."""

    def test_e5_verified_with_reliable_sources(self, minimal_manifest,
                                                minimal_doc_texts, logger):
        verifier = EventVerifier(minimal_manifest, minimal_doc_texts, logger)
        result = verifier.verify("E5", "2027-01-25")

        assert result.status == VerificationStatus.VERIFIED
        assert result.confidence > 0.0
        assert len(result.supporting_doc_ids) > 0
        assert "DOC-001" in result.supporting_doc_ids

    def test_verified_event_has_confidence(self, minimal_manifest,
                                           minimal_doc_texts, logger):
        verifier = EventVerifier(minimal_manifest, minimal_doc_texts, logger)
        result = verifier.verify("E5", "2027-01-25")
        assert 0.0 < result.confidence <= 1.0

    def test_verified_event_has_reason(self, minimal_manifest,
                                       minimal_doc_texts, logger):
        verifier = EventVerifier(minimal_manifest, minimal_doc_texts, logger)
        result = verifier.verify("E5", "2027-01-25")
        assert result.reason  # non-empty reason string


class TestFakeEventDetection:
    """Test that fake/rumoured events are caught."""

    def test_nonexistent_event_detected(self, minimal_manifest,
                                         minimal_doc_texts, logger):
        verifier = EventVerifier(minimal_manifest, minimal_doc_texts, logger)
        result = verifier.verify("E999", "2027-01-25")

        assert result.status == VerificationStatus.FAKE
        assert result.confidence == 0.0
        assert "no documents" in result.reason.lower() or "not found" in result.reason.lower()

    def test_event_only_in_unreliable_sources(self, logger):
        """Event that only appears in tier-4 tabloid — should flag as fake."""
        manifest = {
            "documents": [
                {
                    "DOC_ID": "FAKE-001",
                    "EVENT_ID": "E_FAKE",
                    "TITLE": "CATASTROPHE! Everything destroyed!",
                    "SOURCE_NAME": "Daily Roar",
                    "SOURCE_TYPE": "tabloid",
                    "RELIABILITY": 4,
                    "PUB_DATE": "2026-10-05",
                    "COUNTRY": "Midgard",
                    "SECTOR": "Wheat",
                },
            ],
            "doc_index": {},
        }
        doc_texts = {
            "FAKE-001": "CATASTROPHE! Everything is destroyed! The world is ending!",
        }
        verifier = EventVerifier(manifest, doc_texts, logger)
        result = verifier.verify("E_FAKE", "2027-01-25")

        assert result.status == VerificationStatus.FAKE
        assert len(result.fake_indicators) > 0

    def test_single_social_post_flagged(self, logger):
        """Single social media post about event — should be flagged."""
        manifest = {
            "documents": [
                {
                    "DOC_ID": "SOCIAL-001",
                    "EVENT_ID": "E_RUMOUR",
                    "TITLE": "Port is gone!",
                    "SOURCE_NAME": "Saga Chat",
                    "SOURCE_TYPE": "social_post",
                    "RELIABILITY": 4,
                    "PUB_DATE": "2026-09-15",
                    "COUNTRY": "Orvan",
                    "SECTOR": "Wheat",
                },
            ],
            "doc_index": {},
        }
        doc_texts = {"SOCIAL-001": "Orvan port is gone. Just heard it."}
        verifier = EventVerifier(manifest, doc_texts, logger)
        result = verifier.verify("E_RUMOUR", "2027-01-25")

        assert result.status == VerificationStatus.FAKE
        assert any("social_post" in fi for fi in result.fake_indicators)
