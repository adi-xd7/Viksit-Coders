"""LangGraph trial state machine and send-back loop orchestration.

Implements the required courtroom workflow:
HEIMDALL -> THOR & LOKI (in parallel) -> CROSS-EXAMINATION -> ODIN -> SUFFICIENCY CHECK -> (SEND-BACK to HEIMDALL or READY_FOR_BRIEFING).
"""

from __future__ import annotations

import argparse
import datetime
import json
import logging
import os
import sys
from typing import Any, Dict, List, Optional, Set, Tuple

from langgraph.graph import END, START, StateGraph

from backend.models import (
    AgentRole,
    CaseFile,
    Claim,
    DocMeta,
    Document,
    EventVerificationStatus,
    ExposureRange,
    LogEventType,
    Ruling,
    SendBack,
    SufficiencyResult,
    SufficiencyStatus,
    TradeRow,
    Verdict,
)
from backend.agents.adapters import (
    CrossExamAdapter,
    HeimdallAdapter,
    LokiAdapter,
    ThorAdapter,
)
from backend.agents.odin import OdinJudge
from backend.llm import (
    BudgetExceededError,
    LLMClient,
    MAX_ROUNDS,
    MAX_RUNS,
    MAX_TOKENS_PER_CASE,
    MAX_TOOL_CALLS_PER_AGENT,
    ToolCallLimitExceededError,
    default_llm_client,
)
from backend.logbook import LogBook, default_logbook, redact_secrets
from backend.memory import MemoryStore, default_memory_store
from backend.trial_state import TrialState

logger = logging.getLogger("trial")


def persist_run_snapshot(state: TrialState, output_dir: str = "logs/cases") -> str:
    """Persists a complete, secret-redacted JSON snapshot of the completed run."""
    case_id = state.get("case_id", "CASE-UNKNOWN")
    run_num = state.get("run_count", 1)

    case_dir = os.path.join(output_dir, case_id)
    try:
        os.makedirs(case_dir, exist_ok=True)
        snapshot_path = os.path.join(case_dir, f"run_{run_num}.json")

        case_file_dict = (
            state["case_file"].model_dump() if state.get("case_file") else None
        )
        claims_list = [c.model_dump() for c in state.get("claims", [])]
        attacks_list = [a.model_dump() for a in state.get("attacks", [])]
        defenses_list = [d.model_dump() for d in state.get("defenses", [])]
        concessions_list = [c.model_dump() for c in state.get("concessions", [])]
        rulings_list = [r.model_dump() for r in state.get("rulings", [])]
        ranges_list = [er.model_dump() for er in state.get("exposure_ranges", [])]
        suff_dict = (
            state["sufficiency_result"].model_dump()
            if state.get("sufficiency_result")
            else None
        )
        sendback_dict = (
            state["send_back"].model_dump() if state.get("send_back") else None
        )

        snapshot_payload = {
            "case_id": case_id,
            "as_of": state.get("as_of", ""),
            "run_num": run_num,
            "case_file": case_file_dict,
            "evidence_ids": list(state.get("evidence_ids", [])),
            "evidence_hashes": state.get("evidence_hashes", {}),
            "claims": claims_list,
            "attacks": attacks_list,
            "defenses": defenses_list,
            "concessions": concessions_list,
            "rulings": rulings_list,
            "exposure_ranges": ranges_list,
            "sufficiency_result": suff_dict,
            "send_back": sendback_dict,
            "token_usage": state.get("token_usage", 0),
            "tool_call_counts": state.get("tool_call_counts", {}),
            "overall_status": state.get("overall_status", "unknown"),
            "incomplete_reason": state.get("incomplete_reason"),
            "errors": state.get("errors", []),
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }

        safe_snapshot = redact_secrets(snapshot_payload)

        with open(snapshot_path, "w", encoding="utf-8") as f:
            json.dump(safe_snapshot, f, indent=2, default=str)

        return snapshot_path
    except Exception as e:
        raise RuntimeError(f"Failed to persist run snapshot for case {case_id} run {run_num}: {e}") from e


class TrialGraphBuilder:
    """Builds and compiles the LangGraph StateGraph trial state machine."""

    def __init__(
        self,
        heimdall: Optional[HeimdallAdapter] = None,
        thor: Optional[ThorAdapter] = None,
        loki: Optional[LokiAdapter] = None,
        cross_exam: Optional[CrossExamAdapter] = None,
        odin: Optional[OdinJudge] = None,
        llm_client: Optional[LLMClient] = None,
        logbook: Optional[LogBook] = None,
        memory_store: Optional[MemoryStore] = None,
        output_dir: str = "logs/cases",
    ):
        self.llm_client = llm_client or default_llm_client
        self.logbook = logbook or default_logbook
        self.memory_store = memory_store or default_memory_store
        self.output_dir = output_dir

        self.heimdall = heimdall or HeimdallAdapter(llm_client=self.llm_client)
        self.thor = thor or ThorAdapter(llm_client=self.llm_client)
        self.loki = loki or LokiAdapter(llm_client=self.llm_client)
        self.cross_exam = cross_exam or CrossExamAdapter()
        self.odin = odin or OdinJudge(
            llm_client=self.llm_client,
            logbook=self.logbook,
            memory_store=self.memory_store,
        )

    def node_heimdall(self, state: TrialState) -> Dict[str, Any]:
        """Node A: Heimdall gatekeeper, event verification, and research."""
        question = state.get("question", "")
        as_of = state.get("as_of", "2027-01-25")
        run_count = state.get("run_count", 1)
        send_back = state.get("send_back")

        try:
            # Parse question and establish CaseFile if not already present
            case_file = state.get("case_file")
            if case_file is None or run_count == 1:
                case_file = self.heimdall.parse_question(question, as_of)

            prev_ids = set(state.get("previous_evidence_ids", []))
            prev_hashes = dict(state.get("previous_evidence_hashes", {}))

            # Retrieve evidence (initial or re-search upon send-back)
            doc_store, trade_store, new_ids, evidence_hashes = self.heimdall.retrieve_evidence(
                case_file=case_file,
                send_back=send_back,
                previous_evidence_ids=prev_ids,
                previous_evidence_hashes=prev_hashes,
            )

            # Merge with existing stores
            existing_docs = dict(state.get("doc_store", {}))
            existing_docs.update(doc_store)
            existing_trade = dict(state.get("trade_store", {}))
            existing_trade.update(trade_store)

            all_ids = list(set(state.get("evidence_ids", []) + list(doc_store.keys()) + [f"{r.table_id}#{r.row_num}" for rows in trade_store.values() for r in rows]))
            all_hashes = dict(state.get("evidence_hashes", {}))
            all_hashes.update(evidence_hashes)

            # Check new-evidence requirement on Run 2+
            new_count = len(new_ids)
            incomplete_reason = None
            overall_status = state.get("overall_status", "in_progress")

            if run_count > 1 and new_count == 0:
                overall_status = "incomplete"
                incomplete_reason = "Send-back research produced no qualifying new admissible evidence for missing gaps."
                self.logbook.log(
                    event_type=LogEventType.LIMIT_HIT,
                    agent=AgentRole.HEIMDALL,
                    case_id=case_file.case_id,
                    payload={"reason": incomplete_reason, "run_num": run_count},
                    run_num=run_count,
                )

            # Check event verification status
            if case_file.verification_status == EventVerificationStatus.NOT_REAL:
                overall_status = "event_not_real"
                incomplete_reason = "Disruption event verified as NOT REAL. Trial terminated prior to advocate hearings."

            return {
                "case_file": case_file,
                "case_id": case_file.case_id,
                "event_verification": case_file.verification_status,
                "doc_store": existing_docs,
                "trade_store": existing_trade,
                "evidence_ids": all_ids,
                "evidence_hashes": all_hashes,
                "new_evidence_count": new_count,
                "overall_status": overall_status,
                "incomplete_reason": incomplete_reason,
                "current_node": "heimdall",
            }
        except Exception as e:
            logger.error(f"Heimdall node error: {e}")
            return {
                "overall_status": "error",
                "incomplete_reason": f"Heimdall failure: {str(e)}",
                "errors": state.get("errors", []) + [str(e)],
                "current_node": "heimdall",
            }

    def node_thor(self, state: TrialState) -> Dict[str, Any]:
        """Node B1: Thor high-exposure advocate (executes in parallel with Loki)."""
        case_file = state["case_file"]
        doc_store = state.get("doc_store", {})
        trade_store = state.get("trade_store", {})
        round_count = state.get("round_count", 1)

        try:
            claims = self.thor.generate_claims(
                case_file=case_file,
                doc_store=doc_store,
                trade_store=trade_store,
                round_num=round_count,
            )
            for c in claims:
                self.logbook.log(
                    event_type=LogEventType.CLAIM,
                    agent=AgentRole.THOR,
                    case_id=case_file.case_id,
                    payload={"claim_id": c.claim_id, "statement": c.statement, "posture": c.posture},
                    run_num=state.get("run_count", 1),
                    round_num=round_count,
                )
            return {"thor_claims": claims, "thor_failed": False}
        except Exception as e:
            logger.error(f"Thor advocate error: {e}")
            self.logbook.log(
                event_type=LogEventType.ERROR,
                agent=AgentRole.THOR,
                case_id=case_file.case_id,
                payload={"error": str(e)},
                run_num=state.get("run_count", 1),
            )
            return {"thor_claims": [], "thor_failed": True, "errors": state.get("errors", []) + [f"Thor failed ({type(e).__name__}): {e}"]}

    def node_loki(self, state: TrialState) -> Dict[str, Any]:
        """Node B2: Loki limited-exposure advocate (executes in parallel with Thor)."""
        case_file = state["case_file"]
        doc_store = state.get("doc_store", {})
        trade_store = state.get("trade_store", {})
        round_count = state.get("round_count", 1)

        try:
            claims = self.loki.generate_claims(
                case_file=case_file,
                doc_store=doc_store,
                trade_store=trade_store,
                round_num=round_count,
            )
            for c in claims:
                self.logbook.log(
                    event_type=LogEventType.CLAIM,
                    agent=AgentRole.LOKI,
                    case_id=case_file.case_id,
                    payload={"claim_id": c.claim_id, "statement": c.statement, "posture": c.posture},
                    run_num=state.get("run_count", 1),
                    round_num=round_count,
                )
            return {"loki_claims": claims, "loki_failed": False}
        except Exception as e:
            logger.error(f"Loki advocate error: {e}")
            self.logbook.log(
                event_type=LogEventType.ERROR,
                agent=AgentRole.LOKI,
                case_id=case_file.case_id,
                payload={"error": str(e)},
                run_num=state.get("run_count", 1),
            )
            return {"loki_claims": [], "loki_failed": True, "errors": state.get("errors", []) + [f"Loki failed ({type(e).__name__}): {e}"]}

    def node_cross_exam(self, state: TrialState) -> Dict[str, Any]:
        """Node C: Cross-examination merging parallel advocate outputs."""
        thor_claims = state.get("thor_claims", [])
        loki_claims = state.get("loki_claims", [])
        thor_failed = state.get("thor_failed", False)
        loki_failed = state.get("loki_failed", False)
        case_file = state["case_file"]
        doc_store = state.get("doc_store", {})

        # Merge disjoint advocate claims safely
        all_claims = list(thor_claims) + list(loki_claims)

        attacks, defenses, concessions = self.cross_exam.conduct_cross_examination(
            thor_claims=thor_claims,
            loki_claims=loki_claims,
            doc_store=doc_store,
            thor_failed=thor_failed,
            loki_failed=loki_failed,
        )

        for a in attacks:
            self.logbook.log(
                event_type=LogEventType.ATTACK,
                agent=a.attacker,
                case_id=case_file.case_id,
                payload={"attack_id": a.attack_id, "target_claim_id": a.target_claim_id, "argument": a.argument},
                run_num=state.get("run_count", 1),
                round_num=state.get("round_count", 1),
            )
        for d in defenses:
            self.logbook.log(
                event_type=LogEventType.DEFENSE,
                agent=d.defender,
                case_id=case_file.case_id,
                payload={"defense_id": d.defense_id, "attack_id": d.attack_id, "argument": d.argument},
                run_num=state.get("run_count", 1),
                round_num=state.get("round_count", 1),
            )
        for c in concessions:
            self.logbook.log(
                event_type=LogEventType.CONCESSION,
                agent=c.agent,
                case_id=case_file.case_id,
                payload={"concession_id": c.concession_id, "claim_id": c.claim_id, "rationale": c.rationale},
                run_num=state.get("run_count", 1),
                round_num=state.get("round_count", 1),
            )

        return {
            "claims": all_claims,
            "attacks": attacks,
            "defenses": defenses,
            "concessions": concessions,
            "current_node": "cross_exam",
        }

    async def node_odin(self, state: TrialState) -> Dict[str, Any]:
        """Node D: Judicial evaluation of all claims by Odin."""
        case_file = state["case_file"]
        claims = state.get("claims", [])
        doc_store = state.get("doc_store", {})
        trade_store = state.get("trade_store", {})
        attacks = state.get("attacks", [])
        defenses = state.get("defenses", [])
        concessions = state.get("concessions", [])
        run_count = state.get("run_count", 1)
        round_count = state.get("round_count", 1)

        rulings = await self.odin.judge_claims(
            case_file=case_file,
            claims=claims,
            doc_store=doc_store,
            trade_store=trade_store,
            attacks=attacks,
            defenses=defenses,
            concessions=concessions,
            run_num=run_count,
            round_num=round_count,
        )

        return {
            "rulings": rulings,
            "token_usage": self.llm_client.total_tokens_used,
            "tool_call_counts": dict(self.llm_client.tool_call_counts),
            "current_node": "odin",
        }

    def node_sufficiency(self, state: TrialState) -> Dict[str, Any]:
        """Node E: Exposure range derivation, sufficiency check, and snapshot persistence."""
        case_file = state["case_file"]
        claims = state.get("claims", [])
        rulings = state.get("rulings", [])
        doc_store = state.get("doc_store", {})
        trade_store = state.get("trade_store", {})
        run_count = state.get("run_count", 1)
        max_runs = state.get("max_runs", MAX_RUNS)

        # 1. Derive evidence-grounded exposure ranges
        exposure_ranges = self.odin.derive_exposure_ranges(
            case_file=case_file,
            claims=claims,
            rulings=rulings,
            trade_store=trade_store,
        )

        # 2. Assess trial sufficiency
        suff_res = self.odin.assess_sufficiency(
            case_file=case_file,
            rulings=rulings,
            claims=claims,
            exposure_ranges=exposure_ranges,
            doc_store=doc_store,
            trade_store=trade_store,
            run_count=run_count,
            max_runs=max_runs,
        )

        overall_status = "in_progress"
        incomplete_reason = None
        send_back = None

        if suff_res.status == SufficiencyStatus.SUFFICIENT:
            overall_status = "ready_for_briefing"
        elif suff_res.status == SufficiencyStatus.LIMITS_EXHAUSTED:
            overall_status = "terminated_limits_exhausted"
            incomplete_reason = f"Trial run limit reached ({run_count} of {max_runs})."
        elif suff_res.status == SufficiencyStatus.INSUFFICIENT:
            if run_count < max_runs and self.llm_client.total_tokens_used < MAX_TOKENS_PER_CASE:
                overall_status = "send_back_loop"
                send_back = suff_res.send_back
            else:
                overall_status = "incomplete"
                incomplete_reason = f"Evidence insufficient and run limit reached ({run_count} of {max_runs})."

        # Update updated state view for snapshot
        updated_state = dict(state)
        updated_state.update({
            "exposure_ranges": exposure_ranges,
            "sufficiency_result": suff_res,
            "send_back": send_back,
            "overall_status": overall_status,
            "incomplete_reason": incomplete_reason,
            "token_usage": self.llm_client.total_tokens_used,
            "tool_call_counts": dict(self.llm_client.tool_call_counts),
        })

        # 3. Persist run snapshot
        snapshot_path = persist_run_snapshot(updated_state, output_dir=self.output_dir)

        # 4. Prepare state for next run if sending back
        run_history_item = {
            "run_num": run_count,
            "snapshot_path": snapshot_path,
            "rulings_count": len(rulings),
            "sufficiency_status": suff_res.status.value,
            "token_usage": self.llm_client.total_tokens_used,
        }

        updates: Dict[str, Any] = {
            "exposure_ranges": exposure_ranges,
            "sufficiency_result": suff_res,
            "send_back": send_back,
            "overall_status": overall_status,
            "incomplete_reason": incomplete_reason,
            "persisted_snapshot_path": snapshot_path,
            "run_history": state.get("run_history", []) + [run_history_item],
            "previous_evidence_ids": list(state.get("evidence_ids", [])),
            "previous_evidence_hashes": dict(state.get("evidence_hashes", {})),
            "current_node": "sufficiency",
        }

        if overall_status == "send_back_loop":
            updates["run_count"] = run_count + 1

        return updates

    def build_graph(self) -> StateGraph:
        """Constructs and wires the StateGraph workflow."""
        builder = StateGraph(TrialState)

        # Add nodes
        builder.add_node("heimdall", self.node_heimdall)
        builder.add_node("thor", self.node_thor)
        builder.add_node("loki", self.node_loki)
        builder.add_node("cross_exam", self.node_cross_exam)
        builder.add_node("odin", self.node_odin)
        builder.add_node("sufficiency", self.node_sufficiency)

        # Edges from START to Heimdall
        builder.add_edge(START, "heimdall")

        # Conditional branching from Heimdall
        def route_after_heimdall(state: TrialState) -> List[str] | str:
            status = state.get("overall_status", "")
            if status in ("event_not_real", "incomplete", "error"):
                return END
            # Parallel fan-out to Thor and Loki
            return ["thor", "loki"]

        builder.add_conditional_edges(
            "heimdall",
            route_after_heimdall,
            {
                "thor": "thor",
                "loki": "loki",
                END: END,
            },
        )

        # Parallel fan-in: both Thor and Loki route to Cross-Exam
        builder.add_edge("thor", "cross_exam")
        builder.add_edge("loki", "cross_exam")

        # Cross-Exam to Odin
        builder.add_edge("cross_exam", "odin")

        # Odin to Sufficiency
        builder.add_edge("odin", "sufficiency")

        # Conditional branching from Sufficiency
        def route_after_sufficiency(state: TrialState) -> str:
            status = state.get("overall_status", "")
            if status == "send_back_loop":
                return "heimdall"
            return END

        builder.add_conditional_edges(
            "sufficiency",
            route_after_sufficiency,
            {
                "heimdall": "heimdall",
                END: END,
            },
        )

        return builder.compile()


async def run_trial(
    question: str,
    as_of: str = "2027-01-25",
    max_runs: int = MAX_RUNS,
    max_rounds: int = MAX_ROUNDS,
    builder: Optional[TrialGraphBuilder] = None,
) -> TrialState:
    """Convenience runner to execute a trial through the compiled LangGraph workflow."""
    active_builder = builder or TrialGraphBuilder()
    graph = active_builder.build_graph()

    initial_state: TrialState = {
        "question": question,
        "as_of": as_of,
        "run_count": 1,
        "max_runs": max_runs,
        "round_count": 1,
        "max_rounds": max_rounds,
        "previous_evidence_ids": [],
        "previous_evidence_hashes": {},
        "run_history": [],
        "errors": [],
        "overall_status": "in_progress",
    }

    final_state = await graph.ainvoke(initial_state)
    return final_state


def main():
    """CLI terminal entry point: python -m backend.trial "<question>" --as-of 2027-01-25"""
    import asyncio

    parser = argparse.ArgumentParser(
        description="Trial of the Nine Realms: Autonomous Courtroom Supply Chain Disruption Analyzer"
    )
    parser.add_argument("question", type=str, help="Target question or disruption inquiry")
    parser.add_argument(
        "--as-of",
        dest="as_of",
        type=str,
        default="2027-01-25",
        help="Cutoff as-of date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--max-runs",
        dest="max_runs",
        type=int,
        default=MAX_RUNS,
        help="Maximum trial send-back runs",
    )

    args = parser.parse_args()

    print("======================================================================")
    print(" TRIAL OF THE NINE REALMS — ODIN COURTROOM TRIAL")
    print("======================================================================")
    print(f"Question: {args.question}")
    print(f"As-of Date: {args.as_of}")
    print("----------------------------------------------------------------------")

    state = asyncio.run(run_trial(question=args.question, as_of=args.as_of, max_runs=args.max_runs))

    print("\n--- TRIAL EXECUTION SUMMARY ---")
    case_file = state.get("case_file")
    if case_file:
        print(f"Case ID: {case_file.case_id}")
        print(f"Event Verification: {case_file.verification_status.value.upper()}")
        print(f"Verification Reason: {case_file.verification_reason}")
    print(f"Runs Executed: {state.get('run_count', 1)} (Max: {state.get('max_runs', 3)})")
    print(f"Claims Evaluated: {len(state.get('claims', []))}")
    print(f"Rulings Produced: {len(state.get('rulings', []))}")

    ranges = state.get("exposure_ranges", [])
    if ranges:
        print("\n--- EXPOSURE RANGES ---")
        for r in ranges:
            odin_str = f"[{r.odin_range[0]}, {r.odin_range[1]}]" if r.odin_range else "UNRESOLVED"
            print(f"- {r.country} ({r.sector}): Status={r.status.upper()} | Odin Range={odin_str}")

    print("\n--- FINAL TRIAL STATUS ---")
    status = state.get("overall_status", "unknown").upper()
    print(f"Status: {status}")
    if state.get("incomplete_reason"):
        print(f"Reason: {state.get('incomplete_reason')}")

    if state.get("persisted_snapshot_path"):
        print(f"\nPersisted Run Snapshot: {state.get('persisted_snapshot_path')}")
    print("======================================================================")


if __name__ == "__main__":
    main()
