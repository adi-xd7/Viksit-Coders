"""Cross-Examination Orchestrator.

Coordinates structured reciprocal cross-examination between Thor and Loki:
attacks, defenses, explicit concessions, and degraded modes when an advocate fails.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from backend.agents.adapters import CrossExamAdapter
from backend.agents.loki import LokiAgent
from backend.agents.thor import ThorAgent
from backend.models import (
    AgentRole,
    Attack,
    Claim,
    Concession,
    Defense,
    Document,
)

logger = logging.getLogger("cross_exam")


class CrossExaminationOrchestrator(CrossExamAdapter):
    """Manages structured cross-examination between Thor and Loki."""

    def __init__(
        self,
        thor_agent: Optional[ThorAgent] = None,
        loki_agent: Optional[LokiAgent] = None,
    ):
        super().__init__()
        self.thor_agent = thor_agent or ThorAgent()
        self.loki_agent = loki_agent or LokiAgent()

    def conduct_cross_examination(
        self,
        thor_claims: List[Claim],
        loki_claims: List[Claim],
        doc_store: Dict[str, Document],
        case_id: str = "CASE-DEFAULT",
        thor_failed: bool = False,
        loki_failed: bool = False,
    ) -> Tuple[List[Attack], List[Defense], List[Concession]]:
        """Conducts structured cross-examination, preserving degraded modes if an advocate failed."""
        attacks: List[Attack] = []
        defenses: List[Defense] = []
        concessions: List[Concession] = []

        # Degraded modes: advocate failure is NEVER an automatic concession
        if thor_failed and loki_failed:
            logger.warning("Both advocates failed; cross-examination omitted.")
            return attacks, defenses, concessions

        if thor_failed:
            logger.info("Thor advocate failed; Loki's claims stand unchallenged.")
            return attacks, defenses, concessions

        if loki_failed:
            logger.info("Loki advocate failed; Thor's claims stand unchallenged.")
            return attacks, defenses, concessions

        # 1. Thor attacks Loki's claims
        if thor_claims and loki_claims:
            thor_attacks = self.thor_agent.generate_attacks(loki_claims, doc_store, case_id)
            attacks.extend(thor_attacks)

            # Loki responds to Thor's attacks
            loki_claims_map = {c.claim_id: c for c in loki_claims}
            for att in thor_attacks:
                target_claim = loki_claims_map.get(att.target_claim_id)
                if target_claim:
                    defense, concession = self.loki_agent.defend_or_concede(att, target_claim, doc_store, case_id)
                    if defense:
                        defenses.append(defense)
                    if concession:
                        concessions.append(concession)

            # 2. Loki attacks Thor's claims
            loki_attacks = self.loki_agent.generate_attacks(thor_claims, doc_store, case_id)
            attacks.extend(loki_attacks)

            # Thor responds to Loki's attacks
            thor_claims_map = {c.claim_id: c for c in thor_claims}
            for att in loki_attacks:
                target_claim = thor_claims_map.get(att.target_claim_id)
                if target_claim:
                    defense = self.thor_agent.defend(att, target_claim, doc_store, case_id)
                    defenses.append(defense)

        return attacks, defenses, concessions
