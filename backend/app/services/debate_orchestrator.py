"""Multi-Agent Debate Orchestrator coordinating Loki and Thor in adversarial debate."""

import logging
from typing import Optional
from datetime import datetime

from backend.app.schemas.evidence import EvidenceReference
from backend.app.schemas.case_file import CaseFile
from backend.app.schemas.debate_result import DebateResult
from backend.app.schemas.heimdall_result import HeimdallVerificationResult
from backend.app.schemas.odin_result import OdinResult
from backend.app.schemas.feedback_loop import TrialRecord
from backend.app.agents.loki import LokiAgent
from backend.app.agents.thor import ThorAgent
from backend.app.agents.heimdall import HeimdallAgent
from backend.app.agents.odin import OdinAgent
from backend.app.services.retrieval import BaseRetrievalService
from backend.app.services.memory import LokiMemoryService
from backend.app.services.thor_memory import ThorMemoryService
from backend.app.services.feedback_loop import SufficiencyFeedbackEngine
from backend.app.services.logging_service import StructuredLogger

logger = logging.getLogger("ragnarok.orchestrator")


class DebateOrchestrator:
    """
    Coordinates the multi-agent courtroom debate between Loki (Low-Exposure Advocate)
    and Thor (High-Exposure Advocate) across Round 1 (Advocacy) and Round 2 (Cross-Examination & Concessions),
    with an evidence-sufficiency feedback loop driven by Odin's judicial rulings.

    Deterministic sequence per trial:
      1. Validation of case file & clock parameters.
      2. Heimdall Pre-Debate Evidence Verification Gate.
      3. Loki Round 1 (Low-Exposure Advocacy).
      4. Thor Round 1 (High-Exposure Advocacy).
      5. Loki Round 2 (Cross-Examination of Thor's claims).
      6. Thor Round 2 (Cross-Examination of Loki's claims & Formal Concessions).
      7. Odin Final Judicial Adjudication Engine.
      8. Sufficiency feedback evaluation: Stop if sufficient, or execute targeted retrieval retry if gaps remain.
    """

    def __init__(
        self,
        retrieval_service: Optional[BaseRetrievalService] = None,
        loki_agent: Optional[LokiAgent] = None,
        thor_agent: Optional[ThorAgent] = None,
        heimdall_agent: Optional[HeimdallAgent] = None,
        odin_agent: Optional[OdinAgent] = None,
        feedback_engine: Optional[SufficiencyFeedbackEngine] = None,
        loki_memory: Optional[LokiMemoryService] = None,
        thor_memory: Optional[ThorMemoryService] = None,
        logger_service: Optional[StructuredLogger] = None,
        enable_heimdall: bool = True,
        enable_odin: bool = True,
        max_retries: int = 2,
    ):
        self.logger = logger_service or StructuredLogger(agent_name="orchestrator")
        self.enable_heimdall = enable_heimdall
        self.enable_odin = enable_odin
        self.max_retries = max(0, max_retries)
        self.retrieval_service = retrieval_service

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

        # 3. Initialize or assign HeimdallAgent
        if heimdall_agent is not None:
            self.heimdall_agent: Optional[HeimdallAgent] = heimdall_agent
        elif enable_heimdall and retrieval_service is not None:
            self.heimdall_agent = HeimdallAgent(
                retrieval_service=retrieval_service,
                logger_service=StructuredLogger(agent_name="heimdall"),
            )
        elif enable_heimdall and getattr(self.loki_agent, "retrieval", None) is not None:
            self.heimdall_agent = HeimdallAgent(
                retrieval_service=self.loki_agent.retrieval,
                logger_service=StructuredLogger(agent_name="heimdall"),
            )
        else:
            self.heimdall_agent = None

        # 4. Initialize or assign OdinAgent
        if odin_agent is not None:
            self.odin_agent: Optional[OdinAgent] = odin_agent
        elif enable_odin:
            rs = retrieval_service or getattr(self.loki_agent, "retrieval", None)
            self.odin_agent = OdinAgent(
                retrieval_service=rs,
                logger_service=StructuredLogger(agent_name="odin"),
            )
        else:
            self.odin_agent = None

        # 5. Initialize SufficiencyFeedbackEngine (Part 6B)
        rs = retrieval_service or getattr(self.loki_agent, "retrieval", None)
        self.feedback_engine = feedback_engine or SufficiencyFeedbackEngine(
            retrieval_service=rs,
            logger_service=StructuredLogger(agent_name="feedback_loop"),
        )

        # 6. Enforce that Loki and Thor do NOT share the same memory instance (NFR 1, NFR 6)
        if hasattr(self.loki_agent, "memory") and hasattr(self.thor_agent, "memory"):
            if self.loki_agent.memory is self.thor_agent.memory:
                raise ValueError(
                    "Loki and Thor must have separate, isolated memory service instances. "
                    "Sharing memory instances violates courtroom adversary rules."
                )

    # -------------------------------------------------------------------------
    # Core Orchestration Sequence
    # -------------------------------------------------------------------------
    def _execute_single_trial(
        self,
        case_file: CaseFile,
        run_number: int = 1,
        targeted_evidence: Optional[list[EvidenceReference]] = None,
    ) -> DebateResult:
        """
        Execute a single deterministic multi-agent debate trial across stages 1 through 7.
        """
        stages_executed: list[str] = ["validation"]
        executed_stages: set[str] = {"validation"}

        # Work on a coordinated copy with the assigned trial run_number
        active_case_file = case_file.model_copy(deep=True)
        active_case_file.run_number = run_number
        case_id = active_case_file.case_id
        as_of_date = active_case_file.as_of_date
        run_no = run_number

        # Register newly discovered targeted evidence in advocate memories if present
        if targeted_evidence:
            doc_ids = [ref.doc_id for ref in targeted_evidence]
            if hasattr(self.loki_agent, "memory"):
                self.loki_agent.memory.record_examined_sources(case_id, doc_ids)
            if hasattr(self.thor_agent, "memory"):
                self.thor_agent.memory.record_examined_sources(case_id, doc_ids)

        self.logger.log_event("trial_started", case_id, {
            "as_of_date": as_of_date,
            "run_number": run_no,
            "question": active_case_file.question,
        })

        # ---------------------------------------------------------------------
        # Stage 0: Heimdall Pre-Debate Evidence Verification Gate
        # ---------------------------------------------------------------------
        heimdall_res: Optional[HeimdallVerificationResult] = None
        if self.enable_heimdall:
            stage_name = "heimdall_verification"
            if stage_name in executed_stages:
                raise RuntimeError(f"Duplicate stage execution prevented: {stage_name} already executed.")

            try:
                heimdall_res = self.pre_debate_verify(active_case_file)
            except Exception as e:
                logger.exception(f"Heimdall verification execution error on case {case_id}: {e}")
                return DebateResult(
                    case_id=case_id,
                    as_of_date=as_of_date,
                    run_number=run_no,
                    status="error",
                    failed_stage=stage_name,
                    error_message=f"Heimdall verification execution error: {e}",
                    case_file=active_case_file,
                    stages_executed=stages_executed,
                )

            executed_stages.add(stage_name)
            stages_executed.append(stage_name)
            active_case_file.is_verified = heimdall_res.is_event_real

            if heimdall_res.verification_status == "error":
                return DebateResult(
                    case_id=case_id,
                    as_of_date=as_of_date,
                    run_number=run_no,
                    status="error",
                    failed_stage=stage_name,
                    error_message=heimdall_res.error_message or "Heimdall verification failed with error",
                    heimdall_verification=heimdall_res,
                    case_file=active_case_file,
                    stages_executed=stages_executed,
                )

            if not heimdall_res.is_event_real:
                if heimdall_res.verification_status == "contradicted":
                    err_msg = (
                        f"Pre-debate verification failed: Foundational disruption event is contradicted "
                        f"({', '.join(heimdall_res.contradicted_premises)})"
                    )
                else:
                    err_msg = (
                        f"Pre-debate verification failed: Foundational disruption premises could not be verified "
                        f"({', '.join(heimdall_res.unverified_premises)})"
                    )
                return DebateResult(
                    case_id=case_id,
                    as_of_date=as_of_date,
                    run_number=run_no,
                    status="error",
                    failed_stage=stage_name,
                    error_message=err_msg,
                    heimdall_verification=heimdall_res,
                    case_file=active_case_file,
                    stages_executed=stages_executed,
                )

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
                heimdall_verification=heimdall_res,
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
                heimdall_verification=heimdall_res,
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
                heimdall_verification=heimdall_res,
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
                heimdall_verification=heimdall_res,
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
                heimdall_verification=heimdall_res,
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
                heimdall_verification=heimdall_res,
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
                heimdall_verification=heimdall_res,
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
                heimdall_verification=heimdall_res,
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
        # Final Assembly of CaseFile
        # ---------------------------------------------------------------------
        active_case_file.round_number = 2

        # ---------------------------------------------------------------------
        # Stage 6: Odin Final Judicial Adjudication Engine
        # ---------------------------------------------------------------------
        odin_res: Optional[OdinResult] = None
        if self.enable_odin:
            stage_name = "odin_adjudication"
            if stage_name in executed_stages:
                raise RuntimeError(f"Duplicate stage execution prevented: {stage_name} already executed.")

            # Create an intermediate DebateResult representing the completed debate rounds
            intermediate_result = DebateResult(
                case_id=case_id,
                as_of_date=as_of_date,
                run_number=run_no,
                status="success",
                failed_stage=None,
                error_message=None,
                heimdall_verification=heimdall_res,
                loki_round1=loki_r1,
                thor_round1=thor_r1,
                loki_round2=loki_r2,
                thor_round2=thor_r2,
                case_file=active_case_file,
                stages_executed=list(stages_executed),
            )

            try:
                odin_res = self.post_debate_adjudicate(intermediate_result)
            except Exception as e:
                logger.exception(f"Odin adjudication execution error on case {case_id}: {e}")
                return DebateResult(
                    case_id=case_id,
                    as_of_date=as_of_date,
                    run_number=run_no,
                    status="partial",
                    failed_stage=stage_name,
                    error_message=f"Odin adjudication execution error: {e}",
                    heimdall_verification=heimdall_res,
                    loki_round1=loki_r1,
                    thor_round1=thor_r1,
                    loki_round2=loki_r2,
                    thor_round2=thor_r2,
                    case_file=active_case_file,
                    stages_executed=stages_executed,
                )

            if odin_res is not None and getattr(odin_res, "adjudication_status", None) == "error":
                return DebateResult(
                    case_id=case_id,
                    as_of_date=as_of_date,
                    run_number=run_no,
                    status="partial",
                    failed_stage=stage_name,
                    error_message=odin_res.error_message or "Odin adjudication returned error status",
                    heimdall_verification=heimdall_res,
                    loki_round1=loki_r1,
                    thor_round1=thor_r1,
                    loki_round2=loki_r2,
                    thor_round2=thor_r2,
                    odin_adjudication=odin_res,
                    case_file=active_case_file,
                    stages_executed=stages_executed,
                )

            executed_stages.add(stage_name)
            stages_executed.append(stage_name)

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
            heimdall_verification=heimdall_res,
            loki_round1=loki_r1,
            thor_round1=thor_r1,
            loki_round2=loki_r2,
            thor_round2=thor_r2,
            odin_adjudication=odin_res,
            case_file=active_case_file,
            stages_executed=stages_executed,
        )

    def run_debate(
        self,
        case_file: CaseFile,
        max_retries: Optional[int] = None,
    ) -> DebateResult:
        """
        Execute the deterministic multi-agent debate sequence with evidence-sufficiency feedback loop (Part 6B).

        Retry policy:
          max_retries: The maximum number of additional retry attempts after the initial trial (Trial 1).
          Default: self.max_retries (default: 2). Maximum total trials executed is 1 + max_retries (default: 3).

        Stop conditions:
          - 'evidence_sufficient': Odin determines admissible evidence establishes claims without fatal gaps.
          - 'max_retries_exhausted': Retry budget reached with remaining gaps.
          - 'no_actionable_gaps': No actionable targeted tasks could be formed from gaps.
          - 'no_new_evidence': Targeted retrieval yielded no new admissible documents.
          - 'validation_failure': Input CaseFile failed validation (non-recoverable).
          - 'heimdall_gate_rejected': Foundational event contradicted or unverified by Heimdall (non-recoverable).
          - 'agent_failure': Agent execution exception occurred (non-recoverable).
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
                total_trials=0,
                retries_attempted=0,
                max_retries=self.max_retries if max_retries is None else max(0, max_retries),
                loop_stop_reason="validation_failure",
                trial_history=[],
            )

        effective_max_retries = self.max_retries if max_retries is None else max(0, max_retries)
        trial_history: list[TrialRecord] = []
        examined_doc_ids: set[str] = set()
        active_cf = case_file.model_copy(deep=True)
        retries_attempted = 0
        trial_num = 1
        loop_stop_reason: Optional[str] = None
        last_trial_res: Optional[DebateResult] = None
        current_targeted_evidence: list[EvidenceReference] = []

        while True:
            # Execute single trial
            active_cf.run_number = trial_num
            trial_res = self._execute_single_trial(
                case_file=active_cf,
                run_number=trial_num,
                targeted_evidence=current_targeted_evidence if current_targeted_evidence else None,
            )
            last_trial_res = trial_res

            # Accumulate examined doc ids from trial results
            for cl in trial_res.case_file.claims:
                for c in cl.citations:
                    examined_doc_ids.add(c.doc_id)
            for atk in trial_res.case_file.attacks:
                for c in atk.counter_citations:
                    examined_doc_ids.add(c.doc_id)

            odin_res = trial_res.odin_adjudication
            is_suff = bool(odin_res.is_evidence_sufficient) if odin_res else False
            gaps = list(odin_res.evidence_limitations) if odin_res else []
            disputes = list(odin_res.unresolved_disputes) if odin_res else []

            trial_rec = TrialRecord(
                trial_number=trial_num,
                status=trial_res.status,
                failed_stage=trial_res.failed_stage,
                error_message=trial_res.error_message,
                heimdall_verification=trial_res.heimdall_verification,
                loki_round1=trial_res.loki_round1,
                thor_round1=trial_res.thor_round1,
                loki_round2=trial_res.loki_round2,
                thor_round2=trial_res.thor_round2,
                odin_adjudication=odin_res,
                is_evidence_sufficient=is_suff,
                evidence_gaps_identified=gaps,
                unresolved_disputes=disputes,
                targeted_tasks_generated=[],
                new_evidence_discovered=[],
                gap_resolution_summary=None,
            )
            trial_history.append(trial_rec)

            # Check for non-recoverable error in this trial
            if trial_res.status == "error":
                if trial_res.failed_stage == "heimdall_verification":
                    loop_stop_reason = "heimdall_gate_rejected"
                    trial_rec.gap_resolution_summary = "Non-recoverable: Heimdall foundational verification rejected the event."
                elif trial_res.failed_stage == "validation":
                    loop_stop_reason = "validation_failure"
                    trial_rec.gap_resolution_summary = "Non-recoverable: Case validation failed."
                else:
                    loop_stop_reason = "agent_failure"
                    trial_rec.gap_resolution_summary = f"Non-recoverable: Agent execution error in {trial_res.failed_stage}."
                break

            # If trial status is partial due to an agent error, treat as non-recoverable agent failure
            fatal_stages = ("thor_round1", "loki_round2", "thor_round2", "odin_adjudication")
            if trial_res.status == "partial" and trial_res.failed_stage in fatal_stages:
                loop_stop_reason = "agent_failure"
                trial_rec.gap_resolution_summary = f"Execution stopped: Failure in stage {trial_res.failed_stage}."
                break

            # Evidence is SUFFICIENT: stop immediately!
            if is_suff:
                loop_stop_reason = "evidence_sufficient"
                trial_rec.gap_resolution_summary = (
                    "Evidence is sufficient: All material claims established without disqualifying gaps."
                )
                break

            # Evidence is INSUFFICIENT: check if retry budget is exhausted
            if retries_attempted >= effective_max_retries:
                loop_stop_reason = "max_retries_exhausted"
                trial_rec.gap_resolution_summary = (
                    f"Retry budget exhausted ({retries_attempted}/{effective_max_retries} retries). "
                    "Evidence remains insufficient."
                )
                break

            # Odin missing or empty: cannot formulate tasks
            if odin_res is None:
                loop_stop_reason = "no_actionable_gaps"
                trial_rec.gap_resolution_summary = "Loop terminated: No Odin adjudication available to formulate gap queries."
                break

            # Formulate targeted retrieval tasks from Odin's gaps
            tasks = self.feedback_engine.analyze_gaps(
                odin_result=odin_res,
                case_file=trial_res.case_file,
                trial_number=trial_num + 1,
            )
            trial_rec.targeted_tasks_generated = tasks

            if not tasks:
                loop_stop_reason = "no_actionable_gaps"
                trial_rec.gap_resolution_summary = "Loop terminated: No actionable evidence gaps remain to investigate."
                break

            # Execute targeted retrieval
            new_evidence, updated_tasks = self.feedback_engine.execute_targeted_retrieval(
                tasks=tasks,
                as_of_date=trial_res.as_of_date,
                examined_doc_ids=examined_doc_ids,
            )
            trial_rec.new_evidence_discovered = new_evidence
            trial_rec.targeted_tasks_generated = updated_tasks

            # No-progress check
            if not new_evidence:
                loop_stop_reason = "no_new_evidence"
                trial_rec.gap_resolution_summary = (
                    "Loop terminated: Targeted search returned no meaningful new admissible evidence."
                )
                break

            # New evidence discovered! Advance to next trial
            retries_attempted += 1
            trial_num += 1
            current_targeted_evidence = new_evidence
            for ne in new_evidence:
                examined_doc_ids.add(ne.doc_id)
            trial_rec.gap_resolution_summary = (
                f"Progress: Discovered {len(new_evidence)} new admissible document(s) "
                f"({', '.join(ne.doc_id for ne in new_evidence)}). Advancing to Trial {trial_num}."
            )

            # Carry forward state into next trial's CaseFile
            active_cf = trial_res.case_file.model_copy(deep=True)
            active_cf.run_number = trial_num

        assert last_trial_res is not None
        final_deliverable = last_trial_res.model_copy(deep=True)
        final_deliverable.total_trials = len(trial_history)
        final_deliverable.retries_attempted = retries_attempted
        final_deliverable.max_retries = effective_max_retries
        final_deliverable.loop_stop_reason = loop_stop_reason
        final_deliverable.trial_history = trial_history
        return final_deliverable

    # Alias for API consistency
    orchestrate_debate = run_debate

    # -------------------------------------------------------------------------
    # Clean Integration Hooks for Future Phases (Heimdall & Odin)
    # -------------------------------------------------------------------------

    def pre_debate_verify(
        self,
        case_file: CaseFile,
        custom_premises: Optional[list[str]] = None,
    ) -> HeimdallVerificationResult:
        """
        Integration hook executing Heimdall pre-debate evidence verification.
        Verifies foundational disruption events and material factual premises.
        """
        if self.heimdall_agent is not None:
            return self.heimdall_agent.verify_case(case_file, custom_premises=custom_premises)

        is_ver = getattr(case_file, "is_verified", True)
        return HeimdallVerificationResult(
            case_id=case_file.case_id,
            as_of_date=case_file.as_of_date,
            event_id=case_file.event_id,
            is_event_real=is_ver,
            verification_status="verified" if is_ver else "unverified",
            summary="Heimdall agent not configured; defaulted from case_file.is_verified.",
        )

    def post_debate_adjudicate(self, debate_result: DebateResult) -> Optional[OdinResult]:
        """
        Integration hook executing Odin final judicial adjudication engine (Part 6A).
        Consumes the completed debate deliverables and issues structured rulings.
        """
        if self.odin_agent is not None:
            return self.odin_agent.adjudicate_debate(debate_result)
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
