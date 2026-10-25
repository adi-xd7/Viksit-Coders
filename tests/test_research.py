"""
Test 9: Re-search producing new evidence.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from heimdall.memory import HeimdallMemory


class TestResearch:
    """Test that re-search returns new/different evidence."""

    def test_memory_records_searches(self, memory):
        """Memory should track search history."""
        memory.record_search("query1", ["DOC-001", "DOC-002"],
                             search_round=1)
        assert memory.get_search_count() == 1
        assert "DOC-001" in memory.get_previously_returned_doc_ids()
        assert "DOC-002" in memory.get_previously_returned_doc_ids()

    def test_memory_accumulates_doc_ids(self, memory):
        """Returned doc IDs should accumulate across searches."""
        memory.record_search("q1", ["DOC-001"], search_round=1)
        memory.record_search("q2", ["DOC-002"], search_round=2)
        prev = memory.get_previously_returned_doc_ids()
        assert "DOC-001" in prev
        assert "DOC-002" in prev

    def test_memory_no_duplicate_ids(self, memory):
        """Same doc ID in two searches should not duplicate."""
        memory.record_search("q1", ["DOC-001"], search_round=1)
        memory.record_search("q2", ["DOC-001"], search_round=2)
        prev = memory.get_previously_returned_doc_ids()
        assert prev.count("DOC-001") == 1

    def test_query_reformulations_tracked(self, memory):
        """Reformulations should be recorded."""
        memory.record_reformulation("original", "reformulated version")
        past = memory.get_past_queries()
        assert "reformulated version" in past

    def test_memory_persists(self, tmp_path, logger):
        """Memory should survive reload."""
        path = tmp_path / "persist_test.json"
        m1 = HeimdallMemory(path=path, logger=logger)
        m1.record_search("q", ["D1"], search_round=1)

        # New instance from same file
        m2 = HeimdallMemory(path=path, logger=logger)
        assert "D1" in m2.get_previously_returned_doc_ids()

    def test_memory_reset(self, memory):
        """Reset should clear all data."""
        memory.record_search("q", ["D1"], search_round=1)
        memory.reset()
        assert memory.get_search_count() == 0
        assert memory.get_previously_returned_doc_ids() == []
