"""Multi-Agent Debate Orchestrator coordinating Loki and Thor in adversarial debate."""

import logging
from typing import Optional, Any
from datetime import datetime

from backend.app.schemas.case_file import CaseFile
from backend.app.schemas.debate_result import DebateResult
from backend.app.schemas.loki_result import LokiResult
from backend.app.schemas.thor_result import ThorResult
from backend.app.agents.loki import LokiAgent
from backend.app.agents.thor import ThorAgent
from backend.app.services.retrieval import BaseRetrievalService
from backend.app.services.memory import LokiMemoryService
from backend.app.services.thor_memory import ThorMemoryService
from backend.app.services.logging_service import StructuredLogger

logger = logging.getLogger("ragnarok.orchestrator")


class DebateOrchestrator:
    """
    Coordinates the multi-agent courtroom debate between Loki (Low-Exposure Advocate)
    and Thor (High-Exposure Advocate) across Round 1 (Advocacy) and Round 2 (Cross-Examination & Concessions).

    Deterministic sequence:
      1. Validation of case file & clock parameters.
      2. Loki Round 1 (Low-Exposure Advocacy).
      3. Thor Round 1 (High-Exposure Advocacy).
      4. Loki Round 2 (Cross-Examination of Thor's claims).
      5. Thor Round 2 (Cross-Examination of Loki's claims & Formal Concessions).
      6. Assembly of final CaseFile and structured DebateResult.
    """

    def __init__(
        self,
        retrieval_service: Optional[BaseRetrievalService] = None,
        loki_agent: Optional[LokiAgent] = None,
        thor_agent: Optional[ThorAgent] = None,
        loki_memory: Optional[LokiMemoryService] = None,
        thor_memory: Optional[ThorMemoryService] = None,
        logger_service: Optional[StructuredLogger] = None,
    ):
        self.logger = logger_service or StructuredLogger(agent_name="orchestrator")

        # 1. Initialize or assign LokiAgent
        if loki_agent is not None:
            self.loki_agent = loki_agent
        elif retrieval_service is not None:
            self.loki_agent = LokiAgent(
                retrieval_service=retrieval_service,
                memory_service=loki_memory or LokiMemoryService(),
                logger_service=StructuredLogger(agent_name="loki"),
            )
        else:
            raise ValueError("Either retrieval_service or both loki_agent and thor_agent must be provided.")

        # 2. Initialize or assign ThorAgent
        if thor_agent is not None:
            self.thor_agent = thor_agent
        elif retrieval_service is not None:
            self.thor_agent = ThorAgent(
                retrieval_service=retrieval_service,
                memory_service=thor_memory or ThorMemoryService(),
                logger_service=StructuredLogger(agent_name="thor"),
            )
        else:
            raise ValueError("Either retrieval_service or both loki_agent and thor_agent must be provided.")

        # 3. Enforce that Loki and Thor do NOT share the same memory instance (NFR 1, NFR 6)
        if hasattr(self.loki_agent, "memory") and hasattr(self.thor_agent, "memory"):
            if self.loki_agent.memory is self.thor_agent.memory:
                raise ValueError(
                    "Loki and Thor must have separate, isolated memory service instances. "
                    "Sharing memory instances violates courtroom adversary rules."
                )

    # -------------------------------------------------------------------------
    # Core Orchestration Sequence
    # -------------------------------------------------------------------------

    def run_debate(self, case_file: CaseFile) -> DebateResult:
        """
        Execute the deterministic multi-agent debate sequence.
        Returns a structured DebateResult containing agent outputs and the final CaseFile.
        """
        # 1. Validate basic case input
        val_err = self._validate_case_file(case_file)
        if val_err:
            logger.error(f"Debate orchestration validation failed: {val_err}")
            fallback_id = getattr(case_file, "case_id", None) or "INVALID_CASE"
            fallback_date = getattr(case_file, "as_of_date", None) or "1970-01-01"
            safe_cf = CaseFile(
                case_id=fallback_id if isinstance(fallback_id, str) and fallback_id else "INVALID_CASE",
                question=getattr(case_file, "question", "") or "",
                as_of_date=fallback_date if isinstance(fallback_date, str) and fallback_date else "1970-01-01",
            )
            return DebateResult(
                case_id=safe_cf.case_id,
                as_of_date=safe_cf.as_of_date,
                run_number=getattr(case_file, "run_number", 1) or 1,
                status="error",
                failed_stage="validation",
                error_message=val_err,
                case_file=safe_cf,
                stages_executed=[],
            )

        stages_executed: list[str] = ["validation"]
        executed_stages: set[str] = {"validation"}

        # Work on a coordinated copy to keep caller state intact
        active_case_file = case_file.model_copy(deep=True)
        case_id = active_case_file.case_id
        as_of_date = active_case_file.as_of_date
        run_no = active_case_file.run_number

        self.logger.log_event("debate_started", case_id, {
            "as_of_date": as_of_date,
            "run_number": run_no,
            "question": active_case_file.question,
        })

        # ---------------------------------------------------------------------
        # Stage 1: Loki Round 1 (Low-Exposure Advocacy)
        # ---------------------------------------------------------------------
        stage_name = "loki_round1"
        if stage_name in executed_stages:
            raise RuntimeError(f"Duplicate stage execution prevented: {stage_name} already executed.")

        cf_l1 = active_case_file.model_copy(deep=True)
        cf_l1.round_number = 1

        try:
            loki_r1 = self.loki_agent.investigate_and_argue(cf_l1)
        except Exception as e:
            logger.exception(f"Loki Round 1 failed on case {case_id}: {e}")
            return DebateResult(
                case_id=case_id,
                as_of_date=as_of_date,
                run_number=run_no,
                status="error",
                failed_stage=stage_name,
                error_message=f"Loki Round 1 execution error: {e}",
                case_file=active_case_file,
                stages_executed=stages_executed,
            )

        if getattr(loki_r1, "status", None) == "error":
            return DebateResult(
                case_id=case_id,
                as_of_date=as_of_date,
                run_number=run_no,
                status="error",
                failed_stage=stage_name,
                error_message=loki_r1.error_message or "Loki Round 1 returned error status",
                loki_round1=loki_r1,
                case_file=active_case_file,
                stages_executed=stages_executed,
            )

        executed_stages.add(stage_name)
        stages_executed.append(stage_name)

        # Merge Loki's Round 1 claims into active_case_file
        for claim in (loki_r1.claims or []):
            if not any(c.claim_id == claim.claim_id for c in active_case_file.claims):
                active_case_file.claims.append(claim)

        # ---------------------------------------------------------------------
        # Stage 2: Thor Round 1 (High-Exposure Advocacy)
        # ---------------------------------------------------------------------
        stage_name = "thor_round1"
        if stage_name in executed_stages:
            raise RuntimeError(f"Duplicate stage execution prevented: {stage_name} already executed.")

        cf_t1 = active_case_file.model_copy(deep=True)
        cf_t1.round_number = 1

        try:
            thor_r1 = self.thor_agent.investigate_and_argue(cf_t1)
        except Exception as e:
            logger.exception(f"Thor Round 1 failed on case {case_id}: {e}")
            return DebateResult(
                case_id=case_id,
                as_of_date=as_of_date,
                run_number=run_no,
                status="partial",
                failed_stage=stage_name,
                error_message=f"Thor Round 1 execution error: {e}",
                loki_round1=loki_r1,
                case_file=active_case_file,
                stages_executed=stages_executed,
            )

        if getattr(thor_r1, "status", None) == "error":
            return DebateResult(
                case_id=case_id,
                as_of_date=as_of_date,
                run_number=run_no,
                status="partial",
                failed_stage=stage_name,
                error_message=thor_r1.error_message or "Thor Round 1 returned error status",
                loki_round1=loki_r1,
                thor_round1=thor_r1,
                case_file=active_case_file,
                stages_executed=stages_executed,
            )

        executed_stages.add(stage_name)
        stages_executed.append(stage_name)

        # Merge Thor's Round 1 claims into active_case_file
        for claim in (thor_r1.claims or []):
            if not any(c.claim_id == claim.claim_id for c in active_case_file.claims):
                active_case_file.claims.append(claim)

        # ---------------------------------------------------------------------
        # Stage 3: Loki Round 2 (Cross-Examination of Thor)
        # ---------------------------------------------------------------------
        stage_name = "loki_round2"
        if stage_name in executed_stages:
            raise RuntimeError(f"Duplicate stage execution prevented: {stage_name} already executed.")

        cf_l2 = active_case_file.model_copy(deep=True)
        cf_l2.round_number = 2

        try:
            loki_r2 = self.loki_agent.investigate_and_argue(cf_l2)
        except Exception as e:
            logger.exception(f"Loki Round 2 failed on case {case_id}: {e}")
            return DebateResult(
                case_id=case_id,
                as_of_date=as_of_date,
                run_number=run_no,
                status="partial",
                failed_stage=stage_name,
                error_message=f"Loki Round 2 execution error: {e}",
                loki_round1=loki_r1,
                thor_round1=thor_r1,
                case_file=active_case_file,
                stages_executed=stages_executed,
            )

        if getattr(loki_r2, "status", None) == "error":
            return DebateResult(
                case_id=case_id,
                as_of_date=as_of_date,
                run_number=run_no,
                status="partial",
                failed_stage=stage_name,
                error_message=loki_r2.error_message or "Loki Round 2 returned error status",
                loki_round1=loki_r1,
                thor_round1=thor_r1,
                loki_round2=loki_r2,
                case_file=active_case_file,
                stages_executed=stages_executed,
            )

        executed_stages.add(stage_name)
        stages_executed.append(stage_name)

        # Merge Loki's Round 2 attacks and concessions into active_case_file
        for attack in (loki_r2.attacks or []):
            if not any(a.challenge_id == attack.challenge_id for a in active_case_file.attacks):
                active_case_file.attacks.append(attack)
        for conc in (loki_r2.concessions or []):
            if not any(c.concession_id == conc.concession_id for c in active_case_file.concessions):
                active_case_file.concessions.append(conc)

        # ---------------------------------------------------------------------
        # Stage 4: Thor Round 2 (Cross-Examination of Loki & Formal Concessions)
        # ---------------------------------------------------------------------
        stage_name = "thor_round2"
        if stage_name in executed_stages:
            raise RuntimeError(f"Duplicate stage execution prevented: {stage_name} already executed.")

        cf_t2 = active_case_file.model_copy(deep=True)
        cf_t2.round_number = 2

        try:
            thor_r2 = self.thor_agent.investigate_and_argue(
                case_file=cf_t2,
                loki_result=loki_r1,
                loki_attacks=loki_r2.attacks,
            )
        except Exception as e:
            logger.exception(f"Thor Round 2 failed on case {case_id}: {e}")
            return DebateResult(
                case_id=case_id,
                as_of_date=as_of_date,
                run_number=run_no,
                status="partial",
                failed_stage=stage_name,
                error_message=f"Thor Round 2 execution error: {e}",
                loki_round1=loki_r1,
                thor_round1=thor_r1,
                loki_round2=loki_r2,
                case_file=active_case_file,
                stages_executed=stages_executed,
            )

        if getattr(thor_r2, "status", None) == "error":
            return DebateResult(
                case_id=case_id,
                as_of_date=as_of_date,
                run_number=run_no,
                status="partial",
                failed_stage=stage_name,
                error_message=thor_r2.error_message or "Thor Round 2 returned error status",
                loki_round1=loki_r1,
                thor_round1=thor_r1,
                loki_round2=loki_r2,
                thor_round2=thor_r2,
                case_file=active_case_file,
                stages_executed=stages_executed,
            )

        executed_stages.add(stage_name)
        stages_executed.append(stage_name)

        # Merge Thor's Round 2 attacks and concessions into active_case_file
        for attack in (thor_r2.attacks or []):
            if not any(a.challenge_id == attack.challenge_id for a in active_case_file.attacks):
                active_case_file.attacks.append(attack)
        for conc in (thor_r2.concessions or []):
            if not any(c.concession_id == conc.concession_id for c in active_case_file.concessions):
                active_case_file.concessions.append(conc)

        # ---------------------------------------------------------------------
        # Stage 5: Follow-up Loki Concessions Closure
        # ---------------------------------------------------------------------
        thor_attacks_on_loki = [a for a in thor_r2.attacks if a.challenger == "thor"]
        if thor_attacks_on_loki and not any(c.agent == "loki" for c in active_case_file.concessions):
            cf_loki_conc = active_case_file.model_copy(deep=True)
            cf_loki_conc.round_number = 2
            try:
                loki_conc = self.loki_agent._formulate_concessions(cf_loki_conc)
                for conc in loki_conc:
                    if not any(c.concession_id == conc.concession_id for c in active_case_file.concessions):
                        active_case_file.concessions.append(conc)
                if loki_r2 and hasattr(loki_r2, "concessions"):
                    loki_r2.concessions.extend(loki_conc)
            except Exception as e:
                logger.warning(f"Loki concessions follow-up evaluation exception: {e}")

        # ---------------------------------------------------------------------
        # Final Assembly
        # ---------------------------------------------------------------------
        active_case_file.round_number = 2

        self.logger.log_event("debate_completed", case_id, {
            "status": "success",
            "claims_count": len(active_case_file.claims),
            "attacks_count": len(active_case_file.attacks),
            "concessions_count": len(active_case_file.concessions),
            "stages_count": len(stages_executed),
        })

        return DebateResult(
            case_id=case_id,
            as_of_date=as_of_date,
            run_number=run_no,
            status="success",
            failed_stage=None,
            error_message=None,
            loki_round1=loki_r1,
            thor_round1=thor_r1,
            loki_round2=loki_r2,
            thor_round2=thor_r2,
            case_file=active_case_file,
            stages_executed=stages_executed,
        )

    # Alias for API consistency
    orchestrate_debate = run_debate

    # -------------------------------------------------------------------------
    # Clean Integration Hooks for Future Phases (Heimdall & Odin)
    # -------------------------------------------------------------------------

    def pre_debate_verify(self, case_file: CaseFile) -> bool:
        """Integration hook for Heimdall verification (Part 5B)."""
        return getattr(case_file, "is_verified", True)

    def post_debate_adjudicate(self, debate_result: DebateResult) -> Optional[dict]:
        """Integration hook for Odin judicial ruling (Part 6)."""
        return None

    # -------------------------------------------------------------------------
    # Helper Validation
    # -------------------------------------------------------------------------

    def _validate_case_file(self, case_file: Optional[CaseFile]) -> Optional[str]:
        """Validate CaseFile integrity before commencing debate."""
        if case_file is None:
            return "CaseFile is None."
        if not hasattr(case_file, "case_id") or not case_file.case_id or not isinstance(case_file.case_id, str):
            return "CaseFile missing valid case_id string."
        if not hasattr(case_file, "as_of_date") or not case_file.as_of_date or not isinstance(case_file.as_of_date, str):
            return "CaseFile missing valid as_of_date string."

        date_str = case_file.as_of_date.strip().split("T")[0].split(" ")[0]
        try:
            datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            return f"Invalid as_of_date format: '{case_file.as_of_date}'. Expected YYYY-MM-DD."

        return None
