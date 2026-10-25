"""Adapters and interfaces for Heimdall, Thor, Loki, and Cross-Examination.

Provides clean integration boundaries allowing teammate implementations to dock
seamlessly into the trial graph while providing robust default adapters and test doubles.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from backend.models import (
    AgentRole,
    Attack,
    Basis,
    CaseFile,
    Citation,
    Claim,
    Concession,
    Defense,
    DocMeta,
    Document,
    EventVerificationStatus,
    SendBack,
    TradeRow,
)
from backend.llm import LLMClient, default_llm_client

logger = logging.getLogger("adapters")


def hash_content(content: str) -> str:
    """Computes a stable SHA-256 hash for content novelty tracking."""
    normalized = re.sub(r"\s+", " ", content).strip().lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


class HeimdallAdapter:
    """Gatekeeper and investigator adapter.
    
    Parses questions, establishes as-of dates, verifies events,
    retrieves initial evidence, and conducts re-search upon send-back.
    """

    def __init__(
        self,
        dev_pack_dir: Optional[str] = None,
        llm_client: Optional[LLMClient] = None,
        verification_override: Optional[EventVerificationStatus] = None,
        simulate_failure: bool = False,
    ):
        self.dev_pack_dir = dev_pack_dir or os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "dev_pack_E5"
        )
        self.llm_client = llm_client or default_llm_client
        self.verification_override = verification_override
        self.simulate_failure = simulate_failure
        self._manifest_data: Optional[Dict[str, Any]] = None

    def _load_manifest(self) -> Dict[str, Any]:
        if self._manifest_data is None:
            manifest_path = os.path.join(self.dev_pack_dir, "manifest.json")
            if os.path.exists(manifest_path):
                with open(manifest_path, "r", encoding="utf-8") as f:
                    self._manifest_data = json.load(f)
            else:
                self._manifest_data = {"documents": []}
        return self._manifest_data

    def parse_question(self, question: str, as_of: Optional[str] = None) -> CaseFile:
        """Parses user question into structured CaseFile with target country-sector pairs."""
        # Date extraction: search for explicit YYYY-MM-DD or default to 2027-01-25
        found_date = as_of
        if not found_date:
            m = re.search(r"(\d{4}-\d{2}-\d{2})", question)
            if m:
                found_date = m.group(1)
            elif "25 january 2027" in question.lower() or "2027-01-25" in question:
                found_date = "2027-01-25"
            else:
                found_date = "2027-01-25"

        # Country extraction
        countries: List[str] = []
        for c in ["Midgard", "Tolan", "Utgard", "Asgard", "Vanaheim"]:
            if c.lower() in question.lower():
                countries.append(c)
        if not countries:
            countries = ["Midgard", "Tolan"]

        # Sector extraction
        sectors: List[str] = []
        for s in ["wheat", "maize", "grain", "fertilizer", "shipping"]:
            if s.lower() in question.lower():
                sectors.append(s)
        if not sectors:
            sectors = ["wheat", "maize"]

        target_pairs = [(c, s) for c in countries for s in sectors]

        # Verification status check
        v_status = self.verification_override or EventVerificationStatus.REAL
        v_reason = (
            "Disruption event confirmed by official notices."
            if v_status == EventVerificationStatus.REAL
            else "Event could not be verified."
        )

        return CaseFile(
            case_id="CASE-E5-001",
            query=question,
            as_of=found_date,
            target_pairs=target_pairs,
            verification_status=v_status,
            verification_reason=v_reason,
            active_event_id="E5",
        )

    def retrieve_evidence(
        self,
        case_file: CaseFile,
        send_back: Optional[SendBack] = None,
        previous_evidence_ids: Optional[Set[str]] = None,
        previous_evidence_hashes: Optional[Dict[str, str]] = None,
    ) -> Tuple[Dict[str, Document], Dict[str, List[TradeRow]], List[str], Dict[str, str]]:
        """Retrieves evidence for the trial, tracking genuinely new qualifying evidence."""
        if self.simulate_failure:
            raise RuntimeError("Heimdall retrieval failed: simulated upstream connection error.")

        prev_ids = previous_evidence_ids or set()
        prev_hashes = previous_evidence_hashes or {}

        doc_store: Dict[str, Document] = {}
        trade_store: Dict[str, List[TradeRow]] = {}
        evidence_hashes: Dict[str, str] = {}

        manifest = self._load_manifest()
        docs_meta = {d["DOC_ID"]: d for d in manifest.get("documents", [])}

        # Initial baseline evidence (Run 1)
        if not send_back:
            # Event verification and initial profile documents
            sample_docs = ["ATL-0001", "ATL-0002", "ATL-0005", "ORV-0001", "ORV-0007"]
            for doc_id in sample_docs:
                if doc_id in docs_meta:
                    m = docs_meta[doc_id]
                    paragraphs = {
                        1: f"Official record {doc_id} discussing {m.get('SECTOR', 'trade')} in {m.get('COUNTRY', 'the region')}.",
                        2: f"Corridor traffic disrupted as of early January 2027 for grain shipments.",
                    }
                    raw_text = "\n".join(paragraphs.values())
                    doc_store[doc_id] = Document(
                        meta=DocMeta(
                            DOC_ID=doc_id,
                            PUB_DATE=m.get("PUB_DATE", "2027-01-10"),
                            RELIABILITY=int(m.get("RELIABILITY", 2)),
                            COUNTRY=m.get("COUNTRY", "general"),
                            SECTOR=m.get("SECTOR", "general"),
                            SOURCE_NAME=m.get("SOURCE_NAME", "Official Bulletin"),
                        ),
                        paragraphs=paragraphs,
                        raw_text=raw_text,
                    )
                    evidence_hashes[doc_id] = hash_content(raw_text)

            # Baseline trade data for Midgard & Tolan wheat/maize
            trade_store["TAB-WHEAT-MIDGARD"] = [
                TradeRow(
                    table_id="TAB-WHEAT-MIDGARD",
                    row_num=1,
                    country_pair="Midgard-Utgard",
                    sector="wheat",
                    month="2026-11",
                    volume=50000.0,
                    value=15000000.0,
                    unit="tons",
                ),
                TradeRow(
                    table_id="TAB-WHEAT-MIDGARD",
                    row_num=2,
                    country_pair="Midgard-Utgard",
                    sector="wheat",
                    month="2026-12",
                    volume=55000.0,
                    value=16500000.0,
                    unit="tons",
                ),
            ]
            for r in trade_store["TAB-WHEAT-MIDGARD"]:
                r_key = f"{r.table_id}#{r.row_num}"
                evidence_hashes[r_key] = hash_content(f"{r.country_pair} {r.month} {r.volume}")

        else:
            # Re-search responding to send_back (Run 2+)
            # Retrieve specific documents addressing missing items
            sendback_docs = ["ORV-0015", "ORV-0020", "ORV-0035"]
            for doc_id in sendback_docs:
                if doc_id in docs_meta and doc_id not in prev_ids:
                    m = docs_meta[doc_id]
                    paragraphs = {
                        1: f"Corroborating report {doc_id} resolving gap: verified grain throughput and substitute capacity.",
                        2: f"Alternative rail corridors provide substitute capacity offset of 10000 tons.",
                    }
                    raw_text = "\n".join(paragraphs.values())
                    h = hash_content(raw_text)
                    if h not in prev_hashes.values():
                        doc_store[doc_id] = Document(
                            meta=DocMeta(
                                DOC_ID=doc_id,
                                PUB_DATE=m.get("PUB_DATE", "2027-01-18"),
                                RELIABILITY=int(m.get("RELIABILITY", 2)),
                                COUNTRY=m.get("COUNTRY", "Midgard"),
                                SECTOR=m.get("SECTOR", "wheat"),
                                SOURCE_NAME=m.get("SOURCE_NAME", "Corridor Authority"),
                            ),
                            paragraphs=paragraphs,
                            raw_text=raw_text,
                        )
                        evidence_hashes[doc_id] = h

            # Add missing trade baseline for Tolan maize if requested
            t_key = "TAB-MAIZE-TOLAN"
            if t_key not in prev_ids:
                trade_store[t_key] = [
                    TradeRow(
                        table_id=t_key,
                        row_num=1,
                        country_pair="Tolan-Utgard",
                        sector="maize",
                        month="2026-12",
                        volume=30000.0,
                        value=8000000.0,
                        unit="tons",
                    )
                ]
                r_key = f"{t_key}#1"
                evidence_hashes[r_key] = hash_content(f"Tolan-Utgard 2026-12 30000.0")

        # Determine which evidence is genuinely newly added
        new_ids = [eid for eid in evidence_hashes if eid not in prev_ids]
        return doc_store, trade_store, new_ids, evidence_hashes


class ThorAdapter:
    """High-exposure advocate adapter.
    
    Argues the strongest evidence-backed case for high exposure.
    """

    def __init__(self, llm_client: Optional[LLMClient] = None, simulate_failure: bool = False):
        self.llm_client = llm_client or default_llm_client
        self.simulate_failure = simulate_failure

    def generate_claims(
        self,
        case_file: CaseFile,
        doc_store: Dict[str, Document],
        trade_store: Optional[Dict[str, List[TradeRow]]] = None,
        round_num: int = 1,
    ) -> List[Claim]:
        """Generates high exposure claims backed by citations and trade data."""
        if self.simulate_failure:
            raise RuntimeError("Thor advocate failed: simulated provider error.")

        self.llm_client.record_tool_call(AgentRole.THOR.value)

        claims = []
        for country, sector in case_file.target_pairs[:2]:
            doc_id = next((d for d in doc_store if doc_store[d].meta.RELIABILITY <= 2), "ORV-0001")
            t_ref = None
            if trade_store:
                for tid, rows in trade_store.items():
                    if country.lower() in tid.lower() or sector.lower() in tid.lower():
                        t_ref = f"{tid}#1"
                        break

            cits = [Citation(doc_id=doc_id, paragraph_num=2)]
            if t_ref:
                cits.append(Citation(doc_id=t_ref.split("#")[0], trade_row_ref=t_ref))

            claim = Claim(
                claim_id=f"THOR-C{len(claims)+1}-{country[:3].upper()}-{sector[:3].upper()}",
                agent=AgentRole.THOR,
                country=country,
                sector=sector,
                posture="high",
                statement=f"Severe supply disruption for {country} {sector}: imports halted by 35% to 50% due to corridor closure.",
                estimate_low=35.0,
                estimate_high=50.0,
                unit="%",
                citations=cits,
                nature=Basis.SOURCED_FACT,
            )
            claims.append(claim)

        return claims


class LokiAdapter:
    """Limited-exposure advocate adapter.
    
    Argues the strongest evidence-backed case for limited exposure or substitute offsets.
    """

    def __init__(self, llm_client: Optional[LLMClient] = None, simulate_failure: bool = False):
        self.llm_client = llm_client or default_llm_client
        self.simulate_failure = simulate_failure

    def generate_claims(
        self,
        case_file: CaseFile,
        doc_store: Dict[str, Document],
        trade_store: Optional[Dict[str, List[TradeRow]]] = None,
        round_num: int = 1,
    ) -> List[Claim]:
        """Generates limited exposure claims backed by citations and substitute offsets."""
        if self.simulate_failure:
            raise RuntimeError("Loki advocate failed: simulated provider error.")

        self.llm_client.record_tool_call(AgentRole.LOKI.value)

        claims = []
        for country, sector in case_file.target_pairs[:2]:
            doc_id = next((d for d in doc_store if doc_store[d].meta.RELIABILITY <= 3), "ATL-0001")
            cits = [Citation(doc_id=doc_id, paragraph_num=1)]

            claim = Claim(
                claim_id=f"LOKI-C{len(claims)+1}-{country[:3].upper()}-{sector[:3].upper()}",
                agent=AgentRole.LOKI,
                country=country,
                sector=sector,
                posture="limited",
                statement=f"Disruption for {country} {sector} is limited to 10% to 20% due to domestic stocks and substitute rail capacity offset.",
                estimate_low=10.0,
                estimate_high=20.0,
                unit="%",
                citations=cits,
                nature=Basis.INFERENCE,
            )
            claims.append(claim)

        return claims


class CrossExamAdapter:
    """Cross-examination adapter.
    
    Manages reciprocal attacks, defenses, concessions, and degraded modes.
    """

    def __init__(self):
        pass

    def conduct_cross_examination(
        self,
        thor_claims: List[Claim],
        loki_claims: List[Claim],
        doc_store: Dict[str, Document],
        thor_failed: bool = False,
        loki_failed: bool = False,
    ) -> Tuple[List[Attack], List[Defense], List[Concession]]:
        """Conducts structured cross-examination between advocates with degraded mode handling."""
        attacks: List[Attack] = []
        defenses: List[Defense] = []
        concessions: List[Concession] = []

        # Degraded mode: if both failed
        if thor_failed and loki_failed:
            return attacks, defenses, concessions

        # Degraded mode: if Thor failed, Loki's claims stand unchallenged
        if thor_failed:
            logger.info("Thor advocate failed; Loki's claims stand unchallenged.")
            return attacks, defenses, concessions

        # Degraded mode: if Loki failed, Thor's claims stand unchallenged
        if loki_failed:
            logger.info("Loki advocate failed; Thor's claims stand unchallenged.")
            return attacks, defenses, concessions

        # Normal mode: Thor attacks Loki's first claim
        if thor_claims and loki_claims:
            target_loki = loki_claims[0]
            att_thor = Attack(
                attack_id=f"ATT-THOR-1",
                attacker=AgentRole.THOR,
                target_claim_id=target_loki.claim_id,
                argument=f"Loki underestimates impact: substitute routes are congested and lack sufficient rolling stock.",
                counter_citations=thor_claims[0].citations[:1],
            )
            attacks.append(att_thor)

            # Loki defends with evidence or concession
            def_loki = Defense(
                defense_id=f"DEF-LOKI-1",
                attack_id=att_thor.attack_id,
                defender=AgentRole.LOKI,
                argument=f"Rolling stock shortages are seasonal; alternative routes retain validated capacity.",
                new_citations=target_loki.citations,
            )
            defenses.append(def_loki)

            # Loki attacks Thor's first claim
            target_thor = thor_claims[0]
            att_loki = Attack(
                attack_id=f"ATT-LOKI-1",
                attacker=AgentRole.LOKI,
                target_claim_id=target_thor.claim_id,
                argument=f"Thor's 50% upper bound conflates gross disruption with net exposure, ignoring existing inventories.",
                counter_citations=loki_claims[0].citations[:1],
            )
            attacks.append(att_loki)

            # Thor defends
            def_thor = Defense(
                defense_id=f"DEF-THOR-1",
                attack_id=att_loki.attack_id,
                defender=AgentRole.THOR,
                argument=f"Inventories in Midgard only cover 14 days, insufficient to prevent acute deficit.",
                new_citations=target_thor.citations,
            )
            defenses.append(def_thor)

        return attacks, defenses, concessions
