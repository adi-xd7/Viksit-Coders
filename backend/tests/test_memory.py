"""Tests for LokiMemoryService: case isolation, query deduplication, provenance, and persistence."""

import tempfile
from pathlib import Path
from backend.app.services.memory import LokiMemoryService


def test_query_deduplication():
    """Requirement: NFR5 compliance: never send the same search query twice."""
    memory = LokiMemoryService()
    case_id = "CASE-E5"

    query = "Vanir Midgard wheat substitute"

    # First attempt: fresh query returns True
    assert memory.record_query(case_id, query) is True
    assert memory.has_query_been_run(case_id, query) is True

    # Case-insensitive duplicate check: returns False
    assert memory.record_query(case_id, "vanir midgard wheat substitute") is False
    assert memory.record_query(case_id, "  Vanir Midgard wheat substitute  ") is False

    # Different query for same case returns True
    assert memory.record_query(case_id, "Ravik rail link capacity") is True


def test_case_isolation():
    """Requirement: Loki's memory must be strictly isolated between different cases."""
    memory = LokiMemoryService()

    case_a = "CASE-E5-ORVAN"
    case_b = "CASE-E6-SUEZ"

    # Record queries and sources in Case A
    memory.record_query(case_a, "wheat substitution")
    memory.record_examined_sources(case_a, ["ORV-0027", "ORV-0050"])
    memory.record_lesson(case_a, "lesson_wheat", "Wheat is cushioned", 0.85, ["ORV-0027"])
    memory.record_concession(case_a, "LOKI-CON01", "LOKI-C01", "Rail is partial")

    # Verify Case B is completely empty and unpolluted by Case A
    assert memory.has_query_been_run(case_b, "wheat substitution") is False
    assert memory.get_all_examined_doc_ids(case_b) == []
    assert len(memory.get_lessons(case_b)) == 0
    assert memory.get_conceded_claim_ids(case_b) == set()

    # Verify Case A retained its memory
    assert memory.has_query_been_run(case_a, "wheat substitution") is True
    assert memory.get_all_examined_doc_ids(case_a) == ["ORV-0027", "ORV-0050"]
    assert "lesson_wheat" in memory.get_lessons(case_a)
    assert "LOKI-C01" in memory.get_conceded_claim_ids(case_a)


def test_memory_persistence():
    """Requirement: Private memory can persist to disk and reload cleanly."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage_file = Path(tmpdir) / "loki_mem.json"

        # Instance 1: write data
        mem1 = LokiMemoryService(storage_path=str(storage_file))
        mem1.record_query("CASE-PERSIST", "persisted query")
        mem1.record_examined_sources("CASE-PERSIST", ["ORV-0001", "ORV-0002"])
        mem1.record_lesson("CASE-PERSIST", "key1", "Important lesson", 0.9, ["ORV-0001"])

        # Instance 2: reload from same disk file
        mem2 = LokiMemoryService(storage_path=str(storage_file))
        assert mem2.has_query_been_run("CASE-PERSIST", "persisted query") is True
        assert mem2.get_all_examined_doc_ids("CASE-PERSIST") == ["ORV-0001", "ORV-0002"]
        lessons = mem2.get_lessons("CASE-PERSIST")
        assert "key1" in lessons
        assert lessons["key1"].statement == "Important lesson"
        assert lessons["key1"].confidence == 0.9
