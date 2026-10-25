"""Tests for ThorResult schema and ThorMemoryService: isolation, deduplication, and persistence."""

import tempfile
from pathlib import Path
import pytest
from backend.app.schemas.thor_result import ThorResult
from backend.app.schemas.claim import Claim, ExposureEstimate
from backend.app.schemas.evidence import EvidenceReference
from backend.app.schemas.debate import CrossExamination, Concession
from backend.app.services.thor_memory import ThorMemoryService
from backend.app.services.memory import LokiMemoryService


def test_thor_result_schema_defaults_and_serialization():
    """Verify ThorResult schema validation, field defaults, and JSON serialization."""
    result = ThorResult(
        case_id="CASE-E5-THOR",
        as_of_date="2027-01-25",
        round_number=1,
        run_number=1,
    )

    assert result.agent == "thor"
    assert result.status == "success"
    assert result.case_id == "CASE-E5-THOR"
    assert result.as_of_date == "2027-01-25"
    assert result.round_number == 1
    assert result.run_number == 1
    assert result.claims == []
    assert result.attacks == []
    assert result.concessions == []
    assert result.uncertainties == []
    assert result.error_message is None

    # Populate with Thor-specific high-exposure claim
    est = ExposureEstimate(
        country="Midgard",
        sector="Wheat",
        metric="net_value_loss_pct",
        min_estimate=75.0,
        max_estimate=85.0,
        unit="%",
        period="2026-Q4",
        assumptions=["Rail capacity is bottlenecked", "Vanir parcels are insufficient"],
    )
    ref = EvidenceReference(
        doc_id="ORV-0009",
        paragraph="P2",
        reliability_tier=1,
        source_name="Realm Trade Ministry",
        publication_date="2027-01-19",
        pub_time="10:00",
        quote_or_datapoint="Orvan sea loadings dropped sharply.",
    )
    claim = Claim(
        claim_id="THOR-C01",
        agent="thor",
        stance="high_exposure",
        claim_type="inference",
        statement="Midgard wheat commercial exposure exceeds 75% due to maritime collapse.",
        reasoning="Orvan sea loadings dropped by over 60% with limited rail offset.",
        confidence=0.88,
        estimates=[est],
        citations=[ref],
    )
    result.claims.append(claim)
    result.search_log.append({"query": "Orvan maritime collapse", "matched": 5})
    result.memory_used.append("maritime_collapse_lesson")

    # Roundtrip serialization
    dumped = result.model_dump()
    assert dumped["agent"] == "thor"
    assert len(dumped["claims"]) == 1
    assert dumped["claims"][0]["claim_id"] == "THOR-C01"

    reloaded = ThorResult.model_validate(dumped)
    assert reloaded.case_id == result.case_id
    assert len(reloaded.claims) == 1
    assert reloaded.claims[0].estimates[0].min_estimate == 75.0


def test_thor_and_loki_memory_isolation():
    """Requirement: Thor's private memory must be completely isolated from Loki's memory (NFR 1, NFR 6)."""
    thor_mem = ThorMemoryService()
    loki_mem = LokiMemoryService()

    case_id = "CASE-E5"

    # 1. Thor records data
    thor_mem.record_query(case_id, "Orvan port congestion maritime insurance")
    thor_mem.record_examined_sources(case_id, ["ORV-0009", "ORV-0001"])
    thor_mem.record_lesson(
        case_id=case_id,
        key="thor_rail_bottleneck",
        statement="Ravik rail cannot replace sea freight volumes.",
        confidence=0.90,
        provenance_doc_ids=["ORV-0001"],
    )
    thor_mem.record_concession(
        case_id=case_id,
        concession_id="THOR-CON01",
        claim_id="THOR-C01",
        reason="Acknowledged partial Vanir imports.",
        adjusted_range="65%-75%",
    )

    # 2. Loki records data
    loki_mem.record_query(case_id, "Vanir wheat substitution volume")
    loki_mem.record_examined_sources(case_id, ["ORV-0027"])
    loki_mem.record_lesson(
        case_id=case_id,
        key="loki_wheat_cushion",
        statement="Vanir wheat cushioned Midgard.",
        confidence=0.85,
        provenance_doc_ids=["ORV-0027"],
    )

    # 3. Verify Thor's memory does NOT leak into Loki
    assert loki_mem.has_query_been_run(case_id, "Orvan port congestion maritime insurance") is False
    assert "ORV-0009" not in loki_mem.get_all_examined_doc_ids(case_id)
    assert "ORV-0001" not in loki_mem.get_all_examined_doc_ids(case_id)
    assert "thor_rail_bottleneck" not in loki_mem.get_lessons(case_id)
    assert "THOR-C01" not in loki_mem.get_conceded_claim_ids(case_id)

    # 4. Verify Loki's memory does NOT leak into Thor
    assert thor_mem.has_query_been_run(case_id, "Vanir wheat substitution volume") is False
    assert "ORV-0027" not in thor_mem.get_all_examined_doc_ids(case_id)
    assert "loki_wheat_cushion" not in thor_mem.get_lessons(case_id)


def test_thor_case_isolation():
    """Requirement: Memories must be strictly isolated between distinct cases."""
    thor_mem = ThorMemoryService()

    case_1 = "CASE-E5-ORVAN"
    case_2 = "CASE-E6-SUEZ"

    thor_mem.record_query(case_1, "wheat disruption Orvan")
    thor_mem.record_examined_sources(case_1, ["ORV-0009", "ORV-0050"])
    thor_mem.record_lesson(case_1, "lesson_e5", "Orvan high exposure", 0.9, ["ORV-0009"])
    thor_mem.record_concession(case_1, "THOR-CON01", "THOR-C01", "Conceded on siding limits")

    # Verify case_2 is completely pristine
    assert thor_mem.has_query_been_run(case_2, "wheat disruption Orvan") is False
    assert thor_mem.get_all_examined_doc_ids(case_2) == []
    assert thor_mem.get_lessons(case_2) == {}
    assert thor_mem.get_conceded_claim_ids(case_2) == set()

    # Verify case_1 retains all data
    assert thor_mem.has_query_been_run(case_1, "wheat disruption Orvan") is True
    assert thor_mem.get_all_examined_doc_ids(case_1) == ["ORV-0009", "ORV-0050"]
    assert "lesson_e5" in thor_mem.get_lessons(case_1)
    assert "THOR-C01" in thor_mem.get_conceded_claim_ids(case_1)


def test_thor_query_deduplication():
    """Requirement: NFR 5 compliance: deduplicate queries case-insensitively and strip whitespace."""
    thor_mem = ThorMemoryService()
    case_id = "CASE-DEDUP"

    query = "Orvan grain corridor port paralysis"

    # First execution is fresh
    assert thor_mem.record_query(case_id, query) is True
    assert thor_mem.has_query_been_run(case_id, query) is True

    # Duplicate variations return False
    assert thor_mem.record_query(case_id, "orvan grain corridor port paralysis") is False
    assert thor_mem.record_query(case_id, "  ORVAN GRAIN CORRIDOR PORT PARALYSIS  ") is False

    # Different query for same case returns True
    assert thor_mem.record_query(case_id, "Rail link siding bottleneck") is True


def test_thor_memory_persistence():
    """Requirement: Test persistence across ThorMemoryService instances using isolated file storage."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage_path = Path(tmpdir) / "thor_memory.json"

        # Instance 1 writes
        mem1 = ThorMemoryService(storage_path=str(storage_path))
        mem1.record_query("CASE-PERSIST", "persisted thor query")
        mem1.record_examined_sources("CASE-PERSIST", ["ORV-0001", "ORV-0009"])
        mem1.record_lesson("CASE-PERSIST", "key_thor", "High exposure proven", 0.95, ["ORV-0009"])
        mem1.record_concession("CASE-PERSIST", "THOR-CON01", "THOR-C01", "Adjusted range", "65%-75%")

        assert storage_path.exists()

        # Instance 2 loads from disk
        mem2 = ThorMemoryService(storage_path=str(storage_path))
        assert mem2.has_query_been_run("CASE-PERSIST", "persisted thor query") is True
        assert mem2.get_all_examined_doc_ids("CASE-PERSIST") == ["ORV-0001", "ORV-0009"]
        lessons = mem2.get_lessons("CASE-PERSIST")
        assert "key_thor" in lessons
        assert lessons["key_thor"].statement == "High exposure proven"
        assert lessons["key_thor"].confidence == 0.95
        assert "THOR-C01" in mem2.get_conceded_claim_ids("CASE-PERSIST")
