"""Unit and integration tests for Heimdall Gatekeeper and Investigator."""

from __future__ import annotations

import os
import pytest
from typing import Dict, List

from backend.agents.heimdall import HeimdallAgent
from backend.ingestion import IngestionEngine
from backend.llm import LLMClient
from backend.logbook import LogBook
from backend.memory import MemoryStore
from backend.models import (
    CaseFile,
    EventVerificationStatus,
    SendBack,
)
from backend.retrieval import HybridRetrievalEngine


@pytest.fixture
def heimdall_setup(tmp_path):
    output_dir = str(tmp_path / "cases")
    db_path = str(tmp_path / "logbook.db")
    logbook = LogBook(db_path=db_path, jsonl_path=str(tmp_path / "audit.jsonl"))
    memory_store = MemoryStore()
    llm = LLMClient()
    agent = HeimdallAgent(
        llm_client=llm,
        logbook=logbook,
        memory_store=memory_store,
        use_fastembed=False,
    )
    return {
        "agent": agent,
        "logbook": logbook,
        "memory_store": memory_store,
        "llm": llm,
        "output_dir": output_dir,
    }


def test_heimdall_parse_case_extraction(heimdall_setup):
    """Test question parsing for target countries, sectors, and as-of date."""
    agent: HeimdallAgent = heimdall_setup["agent"]
    query = "As of 25 January 2027, how exposed are Midgard and Tolan to the end of the Orvan corridor agreement? Give a low and high range for wheat and maize imports."

    case_file = agent.parse_case(query=query)
    assert case_file.as_of == "2027-01-25"
    assert ("Midgard", "wheat") in case_file.target_pairs
    assert ("Midgard", "maize") in case_file.target_pairs
    assert ("Tolan", "wheat") in case_file.target_pairs
    assert ("Tolan", "maize") in case_file.target_pairs
    assert case_file.verification_status == EventVerificationStatus.REAL
    assert "ORV-" in case_file.verification_reason or "confirmed" in case_file.verification_reason.lower()


def test_heimdall_event_verification_not_real(heimdall_setup):
    """Test that explicit hoax or fabricated event is flagged NOT_REAL."""
    agent: HeimdallAgent = heimdall_setup["agent"]
    case_file = agent.parse_case(
        query="Reported fabricated hoax disruption in Midgard wheat",
        as_of="2027-01-25",
    )
    assert case_file.verification_status == EventVerificationStatus.NOT_REAL
    assert "fabricated" in case_file.verification_reason.lower() or "decoy" in case_file.verification_reason.lower()


def test_heimdall_retrieve_evidence_run1(heimdall_setup):
    """Test initial evidence retrieval for a valid disruption case."""
    agent: HeimdallAgent = heimdall_setup["agent"]
    case_file = CaseFile(
        case_id="TEST-HEIMDALL-1",
        query="Orvan corridor agreement collapse wheat Midgard",
        as_of="2027-01-25",
        target_pairs=[("Midgard", "wheat")],
        verification_status=EventVerificationStatus.REAL,
    )

    doc_store, trade_store, new_ids, hashes = agent.retrieve_evidence(case_file)
    assert len(doc_store) > 0
    assert len(trade_store) > 0
    assert len(new_ids) > 0
    # Confirm as-of date constraint
    for d_id, doc in doc_store.items():
        assert doc.meta.PUB_DATE <= "2027-01-25"


def test_heimdall_send_back_targeted_research(heimdall_setup):
    """Test that send-back re-search queries specifically for requested gaps and tracks novelty."""
    agent: HeimdallAgent = heimdall_setup["agent"]
    case_file = CaseFile(
        case_id="TEST-HEIMDALL-2",
        query="Orvan corridor agreement collapse wheat Midgard",
        as_of="2027-01-25",
        target_pairs=[("Midgard", "wheat")],
        verification_status=EventVerificationStatus.REAL,
    )

    # Initial Run 1
    doc_store_1, trade_store_1, new_ids_1, hashes_1 = agent.retrieve_evidence(case_file)

    # Send-back request from Odin
    send_back = SendBack(
        missing=["alternative rail substitute route offset Ravik Vantro"],
        gap_type="missing_substitute_data",
        target_pairs=[("Midgard", "wheat")],
    )

    doc_store_2, trade_store_2, new_ids_2, hashes_2 = agent.retrieve_evidence(
        case_file=case_file,
        send_back=send_back,
        previous_evidence_ids=set(new_ids_1),
        previous_evidence_hashes=hashes_1,
    )

    # The new evidence IDs must be disjoint from previous evidence IDs
    for nid in new_ids_2:
        assert nid not in set(new_ids_1)


def test_heimdall_memory_recording(heimdall_setup):
    """Test that Heimdall logs audit events and remembers lessons in private memory."""
    agent: HeimdallAgent = heimdall_setup["agent"]
    memory_store: MemoryStore = heimdall_setup["memory_store"]

    case_file = agent.parse_case("As of 2027-01-25, Midgard wheat disruption?")
    lessons = memory_store.recall("heimdall", "case")
    assert len(lessons) > 0
    assert any("Midgard" in str(l) for l in lessons)
