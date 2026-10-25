"""Unit and integration tests for Thor, Loki, and Cross-Examination."""

from __future__ import annotations

import pytest
from typing import Dict, List

from backend.agents.cross_exam import CrossExaminationOrchestrator
from backend.agents.loki import LokiAgent
from backend.agents.thor import ThorAgent
from backend.llm import LLMClient
from backend.logbook import LogBook
from backend.memory import MemoryStore
from backend.models import (
    AgentRole,
    Basis,
    CaseFile,
    Citation,
    Claim,
    DocMeta,
    Document,
    EventVerificationStatus,
    TradeRow,
)


@pytest.fixture
def advocates_setup(tmp_path):
    output_dir = str(tmp_path / "cases")
    db_path = str(tmp_path / "logbook.db")
    logbook = LogBook(db_path=db_path, jsonl_path=str(tmp_path / "audit.jsonl"))
    memory_store = MemoryStore()
    llm = LLMClient()

    thor = ThorAgent(llm_client=llm, logbook=logbook, memory_store=memory_store)
    loki = LokiAgent(llm_client=llm, logbook=logbook, memory_store=memory_store)
    cross_exam = CrossExaminationOrchestrator(thor_agent=thor, loki_agent=loki)

    # Sample admissible document and trade store
    doc_store = {
        "ORV-0001": Document(
            meta=DocMeta(DOC_ID="ORV-0001", PUB_DATE="2027-01-10", RELIABILITY=2, COUNTRY="Midgard", SECTOR="wheat"),
            paragraphs={1: "Official notice: corridor transit ended.", 2: "Port index fell to 40 indicating severe bulk shipping deficit."},
            raw_text="Official notice: corridor transit ended. Port index fell to 40 indicating severe bulk shipping deficit.",
        ),
        "ORV-0002": Document(
            meta=DocMeta(DOC_ID="ORV-0002", PUB_DATE="2027-01-12", RELIABILITY=2, COUNTRY="Midgard", SECTOR="wheat"),
            paragraphs={1: "Rail loadings through Ravik provide substitute capacity offset.", 2: "Domestic grain stores cushion immediate impact."},
            raw_text="Rail loadings through Ravik provide substitute capacity offset. Domestic grain stores cushion immediate impact.",
        ),
    }

    trade_store = {
        "TAB-MIDGARD": [
            TradeRow(table_id="TAB-MIDGARD", row_num=1, country_pair="Orvan-Midgard", sector="wheat", month="2026-07", value=90000000.0, volume=250000.0, unit="tonnes"),
            TradeRow(table_id="TAB-MIDGARD", row_num=2, country_pair="Orvan-Midgard", sector="wheat", month="2026-08", value=96000000.0, volume=267000.0, unit="tonnes"),
            TradeRow(table_id="TAB-MIDGARD", row_num=3, country_pair="Orvan-Midgard", sector="wheat", month="2026-11", value=35000000.0, volume=86000.0, unit="tonnes"),
            TradeRow(table_id="TAB-MIDGARD", row_num=4, country_pair="Orvan-Midgard", sector="wheat", month="2026-12", value=34000000.0, volume=83000.0, unit="tonnes"),
        ]
    }

    case_file = CaseFile(
        case_id="CASE-ADV-01",
        query="Midgard wheat exposure",
        as_of="2027-01-25",
        target_pairs=[("Midgard", "wheat")],
        verification_status=EventVerificationStatus.REAL,
    )

    return {
        "thor": thor,
        "loki": loki,
        "cross_exam": cross_exam,
        "doc_store": doc_store,
        "trade_store": trade_store,
        "case_file": case_file,
        "logbook": logbook,
        "memory_store": memory_store,
        "llm": llm,
    }


def test_thor_generates_high_exposure_claims(advocates_setup):
    """Test that Thor generates structured claims with posture='high' and deterministic bounds."""
    thor: ThorAgent = advocates_setup["thor"]
    claims = thor.generate_claims(
        case_file=advocates_setup["case_file"],
        doc_store=advocates_setup["doc_store"],
        trade_store=advocates_setup["trade_store"],
    )

    assert len(claims) >= 1
    c = claims[0]
    assert c.agent == AgentRole.THOR
    assert c.posture == "high"
    assert c.estimate_low is not None and c.estimate_high is not None
    assert c.estimate_low > 20.0
    assert len(c.citations) >= 1
    assert any(cit.doc_id == "ORV-0001" or "TAB" in cit.doc_id for cit in c.citations)


def test_loki_generates_limited_exposure_claims(advocates_setup):
    """Test that Loki generates structured claims with posture='limited' and mitigation rationale."""
    loki: LokiAgent = advocates_setup["loki"]
    claims = loki.generate_claims(
        case_file=advocates_setup["case_file"],
        doc_store=advocates_setup["doc_store"],
        trade_store=advocates_setup["trade_store"],
    )

    assert len(claims) >= 1
    c = claims[0]
    assert c.agent == AgentRole.LOKI
    assert c.posture == "limited"
    assert c.estimate_low is not None and c.estimate_high is not None
    assert c.estimate_high <= 30.0
    assert "substitute" in c.statement.lower() or "rail" in c.statement.lower() or "offset" in c.statement.lower()


def test_cross_examination_reciprocal_attacks_and_defenses(advocates_setup):
    """Test reciprocal cross-examination between Thor and Loki."""
    thor: ThorAgent = advocates_setup["thor"]
    loki: LokiAgent = advocates_setup["loki"]
    cross_exam: CrossExaminationOrchestrator = advocates_setup["cross_exam"]

    thor_claims = thor.generate_claims(
        case_file=advocates_setup["case_file"],
        doc_store=advocates_setup["doc_store"],
        trade_store=advocates_setup["trade_store"],
    )
    loki_claims = loki.generate_claims(
        case_file=advocates_setup["case_file"],
        doc_store=advocates_setup["doc_store"],
        trade_store=advocates_setup["trade_store"],
    )

    attacks, defenses, concessions = cross_exam.conduct_cross_examination(
        thor_claims=thor_claims,
        loki_claims=loki_claims,
        doc_store=advocates_setup["doc_store"],
        case_id="CASE-ADV-01",
    )

    assert len(attacks) >= 2
    assert any(a.attacker == AgentRole.THOR for a in attacks)
    assert any(a.attacker == AgentRole.LOKI for a in attacks)
    assert len(defenses) + len(concessions) >= 2


def test_cross_examination_degraded_modes(advocates_setup):
    """Test that provider failure is NOT treated as a concession."""
    cross_exam: CrossExaminationOrchestrator = advocates_setup["cross_exam"]
    thor_claims = [
        Claim(claim_id="T1", agent=AgentRole.THOR, country="Midgard", sector="wheat", posture="high", statement="Thor claim")
    ]
    loki_claims = [
        Claim(claim_id="L1", agent=AgentRole.LOKI, country="Midgard", sector="wheat", posture="limited", statement="Loki claim")
    ]

    # If Thor failed, Loki claims stand unchallenged; zero automatic concessions
    attacks, defenses, concessions = cross_exam.conduct_cross_examination(
        thor_claims=thor_claims,
        loki_claims=loki_claims,
        doc_store=advocates_setup["doc_store"],
        thor_failed=True,
    )
    assert len(concessions) == 0
    assert len(attacks) == 0
