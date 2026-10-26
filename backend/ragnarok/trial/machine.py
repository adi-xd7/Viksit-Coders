"""The trial state machine (explicit; no planner node).

    HEIMDALL -> THOR || LOKI -> CROSS_EXAMINATION -> ODIN -> BRIEFING -> DONE
    ODIN -> HEIMDALL_RESEARCH -> THOR || LOKI -> ...   (send-back: run n+1, bounded by MAX_RUNS)
    HEIMDALL_RESEARCH -> BRIEFING  (no genuinely new evidence: incomplete briefing from the last rulings)
    HEIMDALL -> STOPPED            (event disproved: the trial stops, the user is told why)
    THOR || LOKI -> ODIN           (one advocate failed, or nothing new to cross-examine)
    THOR || LOKI -> BRIEFING       (run n >= 2 only: both advocates failed; last rulings stand)
    any -> FAILED                  (unrecoverable error; completed work is kept and reported)
    any -> PAUSED                  (every model's daily quota used up; resumable after the reset, nothing lost)

Resume: a Trial created with the case ID of an earlier, unfinished attempt replays
the finished steps from the case's own LLM response cache (no API requests); tool
calls are re-run deterministically, memory recalls return what that attempt saw, and
lessons it already wrote are not reinforced twice.

Transitions are checked against ALLOWED in code, and BRIEFING additionally needs a
completed Odin ruling (no briefing is ever produced from unruled claims). Agent
output never selects the next stage: the send-back is decided here from Odin's
structured sufficiency verdict, the run limit and the novelty check on Heimdall's
new evidence.
"""

from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any

from ragnarok.agents.advocates import CrossExam, Submission, run_attacks, run_brief, run_responses, run_revision
from ragnarok.agents.common import AgentEnv, CaseContext
from ragnarok.agents.heimdall import (
    HeimdallOutcome,
    SendBackOutcome,
    render_case_file,
    render_new_evidence,
    run_heimdall,
    run_sendback_research,
)
from ragnarok.agents.odin import OdinResult, run_odin
from ragnarok.briefing.build import build_briefing
from ragnarok.config import Settings, get_settings
from ragnarok.llm.client import Backend, LimitHit, LLMClient, LLMError, ModelPool, QuotaPause, ResponseCache, TokenLedger
from ragnarok.memory.lessons import (
    Masker,
    advocate_lessons,
    heimdall_case_lessons,
    heimdall_research_lessons,
    heimdall_sendback_lessons,
    odin_lessons,
)
from ragnarok.models import (
    AgentName,
    CaseFile,
    Claim,
    EventStatus,
    LogEvent,
    LogEventType,
    Ruling,
    RunSummary,
    SendBack,
)
from ragnarok.retrieval.service import RetrievalService
from ragnarok.store.db import Store


class Stage(StrEnum):
    START = "START"
    HEIMDALL = "HEIMDALL"
    ADVOCATES = "THOR_LOKI"
    CROSS_EXAM = "CROSS_EXAMINATION"
    ODIN = "ODIN"
    RESEARCH = "HEIMDALL_RESEARCH"
    BRIEFING = "BRIEFING"
    DONE = "DONE"
    STOPPED = "STOPPED"
    FAILED = "FAILED"
    PAUSED = "PAUSED"


ALLOWED: dict[Stage, set[Stage]] = {
    Stage.START: {Stage.HEIMDALL},
    Stage.HEIMDALL: {Stage.ADVOCATES, Stage.STOPPED, Stage.FAILED},
    Stage.ADVOCATES: {Stage.CROSS_EXAM, Stage.ODIN, Stage.BRIEFING, Stage.FAILED},
    Stage.CROSS_EXAM: {Stage.ODIN, Stage.FAILED},
    Stage.ODIN: {Stage.BRIEFING, Stage.RESEARCH, Stage.FAILED},
    Stage.RESEARCH: {Stage.ADVOCATES, Stage.BRIEFING, Stage.FAILED},
    Stage.BRIEFING: {Stage.DONE},
}
THOR, LOKI = AgentName.THOR, AgentName.LOKI
OPP = {THOR: LOKI, LOKI: THOR}


class IllegalTransition(RuntimeError):
    pass


@dataclass
class RunRecord:
    run_number: int
    case_file: CaseFile
    submissions: dict[str, Submission] = field(default_factory=dict)
    cross_exam: CrossExam = field(default_factory=CrossExam)
    odin: OdinResult | None = None
    ruled_claims: list[Claim] = field(default_factory=list)
    research: SendBackOutcome | None = None  # Heimdall's send-back research that opened this run
    sendback: SendBack | None = None  # the send-back issued at the end of this run
    effect: dict | None = None  # effect of this run's new evidence (run >= 2)
    notes: list[str] = field(default_factory=list)


@dataclass
class TrialResult:
    case_id: str
    stage: Stage
    history: list[str]
    case_dir: Path
    heimdall: HeimdallOutcome | None = None
    submissions: dict[str, Submission] = field(default_factory=dict)  # latest run
    cross_exam: CrossExam | None = None  # all runs
    odin: OdinResult | None = None  # the rulings the briefing is built from
    briefing_md: str | None = None
    notes: list[str] = field(default_factory=list)  # failures and unchallenged sides, reported honestly
    usage: dict[str, Any] = field(default_factory=dict)
    stop_reason: str | None = None
    runs: list[RunRecord] = field(default_factory=list)
    superseded: dict[str, str] = field(default_factory=dict)  # earlier claim -> why it is no longer active
    briefing_status: str | None = None

    @property
    def runs_completed(self) -> int:
        return sum(1 for r in self.runs if r.odin is not None)


def new_case_id(question: str, as_of: date) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    h = hashlib.sha256(f"{question}|{as_of}|{ts}".encode()).hexdigest()[:6]
    return f"case-{ts}-{h}"


def merge_cx(into: CrossExam, cx: CrossExam) -> None:
    into.attacks += cx.attacks
    into.defenses += cx.defenses
    into.concessions += cx.concessions
    into.invalid_defenses += cx.invalid_defenses
    into.unanswered += cx.unanswered
    into.failures += cx.failures
    into.rejected_attacks += cx.rejected_attacks


def cx_view(cx: CrossExam, ids: set[str], failures: list[str]) -> CrossExam:
    """The cross-examination record relevant to the claims being ruled."""
    att = [a for a in cx.attacks if a.target_claim_id in ids]
    aid = {a.attack_id for a in att}
    return CrossExam(attacks=att, defenses=[d for d in cx.defenses if d.claim_id in ids],
                     concessions=[k for k in cx.concessions if k.claim_id in ids],
                     invalid_defenses=[i for i in cx.invalid_defenses if i.claim_id in ids],
                     unanswered=[u for u in cx.unanswered if u in aid], failures=list(failures),
                     rejected_attacks=list(cx.rejected_attacks))


class Trial:
    def __init__(self, question: str, as_of: date, store: Store, settings: Settings | None = None,
                 backend: Backend | None = None, service: RetrievalService | None = None, case_id: str | None = None) -> None:
        self.settings = settings or get_settings()
        self.store = store
        self.service = service or RetrievalService(store, self.settings)
        self.case_id = case_id or new_case_id(question, as_of)
        self.ledger = TokenLedger(self.settings.max_tokens_per_agent, self.settings.max_tokens_per_case,
                                  call_limit=self.settings.max_llm_calls_per_case)
        # an earlier attempt of the same case (same case ID) -> this run resumes it
        self.attempt = 1 + sum(1 for e in store.events(self.case_id) if e.type == LogEventType.RUN_START)
        cache = (ResponseCache(store.path, self.case_id, reading=self.attempt > 1)
                 if self.settings.llm_response_cache else None)
        self.llm = LLMClient(self.settings, self.ledger, backend, on_event=self._llm_event, cache=cache,
                             context=lambda: {"stage": self.stage.value, "run": self.ctx.run_number},
                             pool=ModelPool(store.path, scope=self.settings.key_fingerprint))
        self.paused_until: datetime | None = None
        self.ctx = CaseContext(case_id=self.case_id, question=question, as_of=as_of, settings=self.settings, llm=self.llm)
        self.stage = Stage.START
        self.case_dir = self.settings.cases_dir / self.case_id
        self.result = TrialResult(case_id=self.case_id, stage=self.stage, history=[], case_dir=self.case_dir)
        self.envs: dict[AgentName, AgentEnv] = {}
        self.cx_all = CrossExam()
        self.active: list[Claim] = []  # claims Odin rules on in the current run
        self.final: RunRecord | None = None  # the last run whose rulings completed
        self.pending_sendback: SendBack | None = None
        self.start_seq = 0  # seq of this attempt's RUN_START (set in run())

    # ------------------------------------------------------------ helpers ---

    def _usage(self) -> dict[str, Any]:
        return {"tokens": self.ledger.snapshot(), "tool_calls": dict(self.ctx.tool_calls),
                "evidence_refs": len(self.ctx.evidence), "runs": self.result.runs_completed,
                "llm_calls": {"used": self.ledger.calls_used, "limit": self.ledger.call_limit,
                              "cached": len(self.ledger.records) - self.ledger.calls_used}}

    def _llm_event(self, kind: str, agent: AgentName, summary: str, payload: dict) -> None:
        type_ = {"cache_hit": LogEventType.LLM_CACHE_HIT, "model_switch": LogEventType.MODEL_SWITCH}.get(kind, LogEventType.ERROR)
        with Store(self.store.path) as s:  # own connection: may be called from an advocate thread
            s.append_event(LogEvent(case_id=self.case_id, run_number=self.ctx.run_number, agent=agent,
                                    type=type_, summary=summary[:500], payload={"llm": kind, **payload}))

    def log(self, type_: LogEventType, summary: str, payload: dict | None = None, refs: list[str] | None = None,
            agent: AgentName = AgentName.SYSTEM) -> None:
        self.store.append_event(LogEvent(case_id=self.case_id, run_number=self.ctx.run_number, agent=agent, type=type_,
                                         summary=summary[:500], payload=payload or {}, refs=refs or []))

    def note(self, msg: str, run: RunRecord | None = None) -> None:
        self.result.notes.append(msg[:300])
        if run is not None:
            run.notes.append(msg[:300])

    def go(self, nxt: Stage, why: str = "") -> None:
        if nxt not in ALLOWED.get(self.stage, set()):
            raise IllegalTransition(f"{self.stage} -> {nxt} is not an allowed transition")
        if nxt == Stage.BRIEFING and self.final is None:
            raise IllegalTransition("no briefing without a completed set of Odin rulings")
        if nxt == Stage.RESEARCH and (self.pending_sendback is None or self.ctx.run_number > self.settings.max_runs):
            raise IllegalTransition("a second run needs Odin's send-back and must stay within MAX_RUNS")
        if nxt == Stage.ADVOCATES and self.stage == Stage.RESEARCH and not self.result.runs[-1].research:
            raise IllegalTransition("run n >= 2 needs Heimdall's research first")
        self.log(LogEventType.STAGE, f"{self.stage.value} -> {nxt.value}{': ' + why if why else ''}",
                 {"from": self.stage.value, "to": nxt.value, "run": self.ctx.run_number})
        self.stage = nxt
        self.result.stage = nxt
        self.result.history.append(nxt.value)
        self.save()

    def env(self, agent: AgentName) -> AgentEnv:
        if agent not in self.envs:
            svc = self.service if agent in (AgentName.HEIMDALL, AgentName.ODIN) else self.service.fork()
            self.envs[agent] = AgentEnv(self.ctx, agent, svc)
        return self.envs[agent]

    def _fail(self, agent: AgentName, exc: Exception, what: str) -> str:
        kind = LogEventType.LIMIT_HIT if isinstance(exc, LimitHit) else LogEventType.ERROR
        msg = f"{agent.value} failed during {what} (run {self.ctx.run_number}): {exc}"
        self.log(kind, msg[:500], {"exception": type(exc).__name__}, agent=agent)
        self.note(msg)
        return msg

    def _remember(self, agent: AgentName, drafts) -> None:
        if not self.settings.memory_enabled or not drafts:
            return
        try:
            self.env(agent).remember(drafts)
        except Exception as exc:  # noqa: BLE001 - memory must never break a trial; record it
            self.log(LogEventType.ERROR, f"memory write for {agent.value} failed: {exc}"[:500], agent=agent)

    # ---------------------------------------------------------------- run ---

    def run(self, stop_after: Stage | None = None) -> TrialResult:
        self.stop_after = stop_after
        self.case_dir.mkdir(parents=True, exist_ok=True)
        self.service.index.refresh(store=self.store)
        resumed = self.attempt > 1
        self.start_seq = self.store.append_event(LogEvent(
            case_id=self.case_id, run_number=self.ctx.run_number, agent=AgentName.SYSTEM, type=LogEventType.RUN_START,
            summary=(f"trial {'resumed (attempt ' + str(self.attempt) + ')' if resumed else 'started'}: "
                     f"{self.ctx.question} (as of {self.ctx.as_of})")[:500],
            payload={"question": self.ctx.question, "as_of": self.ctx.as_of.isoformat(), "attempt": self.attempt,
                     "resume": resumed, "config": self.settings.public_summary()}))
        if resumed:
            self._prepare_replay()
        try:
            self._run(stop_after)
        except IllegalTransition:
            raise
        except QuotaPause as exc:  # not a failure: everything done so far is kept and replays on resume
            self.paused_until = exc.resume_after
            self.note(f"paused: {exc}. Resume the case after that time; finished steps replay without API requests")
            self.log(LogEventType.LIMIT_HIT, f"case paused at {self.stage.value}: {exc}",
                     {"what": "daily model quota", "resume_after": exc.resume_after.isoformat(), "models": exc.models,
                      "stage": self.stage.value})
            self.stage = Stage.PAUSED
            self.result.stage = Stage.PAUSED
            self.result.history.append(Stage.PAUSED.value)
        except Exception as exc:  # noqa: BLE001 - never fabricate success; record and stop
            self.note(f"trial failed: {type(exc).__name__}: {exc}")
            self.log(LogEventType.ERROR, f"trial failed: {type(exc).__name__}: {exc}"[:500])
            if self.stage not in (Stage.FAILED, Stage.DONE, Stage.STOPPED):
                self.stage = Stage.FAILED
                self.result.stage = Stage.FAILED
                self.result.history.append(Stage.FAILED.value)
        finally:
            self.result.usage = self._usage()
            if self.stage == Stage.FAILED:
                self._limitation_report()
            summ = self.ledger.call_summary()
            self.log(LogEventType.LLM_USAGE, f"{summ['calls_used']} model request(s) (limit {summ['calls_limit']}), "
                     f"{summ['repairs']} repair(s), {summ['cached_replays']} replayed from the case cache; by agent "
                     + ", ".join(f"{k} {v}" for k, v in summ["by_agent"].items()), summ)
            self.log(LogEventType.RUN_END, f"trial ended at {self.stage.value} after {self.result.runs_completed} "
                     f"completed run(s)", {"usage": self.result.usage})
            self.save(final=True)
            for e in self.envs.values():
                if e.service is not self.service:
                    e.service.store.close()
        return self.result

    def _prepare_replay(self) -> None:
        """Resume: what the latest earlier attempt recalled (per agent, run and purpose, in
        order) and which lessons any earlier attempt already wrote."""
        evs = [e for e in self.store.events(self.case_id) if e.seq < self.start_seq]
        starts = [e.seq for e in evs if e.type == LogEventType.RUN_START]
        last = max(starts) if starts else 0
        self.ctx.replay_before_seq = self.start_seq
        for e in evs:
            p = e.payload
            if e.type == LogEventType.MEMORY_READ and e.seq > last and "purpose" in p and "stages" in p:
                self.ctx.replay_recalls.setdefault((e.agent.value, e.run_number, p["purpose"]), []).append(p.get("memory", []))
            elif e.type == LogEventType.MEMORY_WRITE:
                mid = (p.get("memory") or {}).get("memory_id") or p.get("memory_id")
                if mid:
                    self.ctx.replay_writes.add((e.agent.value, e.run_number, mid))
        self.log(LogEventType.STAGE, f"resuming case {self.case_id} (attempt {self.attempt}): finished steps replay from "
                 "the case's response cache", {"attempt": self.attempt, "replay_recalls": len(self.ctx.replay_recalls),
                                               "replay_writes": len(self.ctx.replay_writes)})

    def _run(self, stop_after: Stage | None) -> None:
        self.go(Stage.HEIMDALL)
        try:
            h = run_heimdall(self.env(AgentName.HEIMDALL))
        except (LLMError, LimitHit) as exc:
            self._fail(AgentName.HEIMDALL, exc, "investigation")
            self.go(Stage.FAILED, "Heimdall could not build the Case File")
            return
        self.result.heimdall = h
        self.masker = Masker.for_case(self.store, h.case_file)
        self._remember(AgentName.HEIMDALL, heimdall_case_lessons(self.case_id, h.case_file))
        if h.case_file.event_status == EventStatus.DISPROVED:
            self.result.stop_reason = (f"Heimdall found the event disproved as of {self.ctx.as_of}: "
                                       f"{h.case_file.event_verification_notes}")
            self.go(Stage.STOPPED, "event disproved; no trial on a disproved event")
            return
        if stop_after == Stage.HEIMDALL:
            return
        run = RunRecord(run_number=1, case_file=h.case_file)
        self.result.runs.append(run)
        while True:
            outcome = self._trial_run(run, stop_after)
            if outcome != "ruled":
                return  # failed, stopped early, or finished with the last rulings (briefing written)
            nxt = self._after_odin(run)
            if nxt is None:
                break
            run = nxt
            if run.research is None or not run.research.has_new_evidence:
                break  # research failed or found nothing genuinely new: briefing from the last rulings
        self._briefing(advance=self.stage != Stage.BRIEFING)

    # ------------------------------------------------------ one trial run ---

    def _trial_run(self, run: RunRecord, stop_after: Stage | None) -> str:
        n = run.run_number
        self.go(Stage.ADVOCATES, f"run {n}")
        case_text = render_case_file(run.case_file)
        if n == 1:
            seeds = self.result.heimdall.seeds if self.result.heimdall else []
            jobs = {a: (lambda a=a: run_brief(self.env(a), case_text, seeds, run.case_file.trade_table_ids))
                    for a in (THOR, LOKI)}
        else:
            verdicts = {r.claim_id: r.verdict.value for r in self.final.odin.rulings}
            new_text = render_new_evidence(run.research)
            refs = [e["ref"] for e in run.research.new_evidence]
            jobs = {a: (lambda a=a: run_revision(self.env(a), case_text, [c for c in self.active if c.agent == a],
                                                 verdicts, new_text, refs)) for a in (THOR, LOKI)}
        subs = self._parallel(jobs, "brief" if n == 1 else f"run {n} reconsideration",
                              default=lambda a, msg: Submission(failed=msg))
        run.submissions = {a.value: s for a, s in subs.items()}
        self.result.submissions = run.submissions
        failed = {a for a, s in subs.items() if s.failed}

        if n == 1:
            ok = {a for a in (THOR, LOKI) if subs[a].claims}
            if not ok:
                self.note("both advocates failed: no claims to try", run)
                self.go(Stage.FAILED, "both advocates failed")
                return "failed"
            self.active = [c for a in (THOR, LOKI) for c in subs[a].claims]
        else:
            for a in (THOR, LOKI):
                if subs[a].failed:
                    self.note(f"{a.value} could not reconsider in run {n} ({subs[a].failed}); its earlier claims stand "
                              "unchanged", run)
            if failed == {THOR, LOKI}:
                self.note(f"both advocates failed in run {n}; the briefing uses the run {self.final.run_number} rulings", run)
                self.go(Stage.BRIEFING, f"both advocates failed in run {n}")
                self._briefing(advance=False)
                return "finished"
            for a in (THOR, LOKI):
                s = subs[a]
                for k in s.withdrawn:
                    self.result.superseded[k.claim_id] = f"withdrawn by {a.value} in run {n}: {k.reason}"
                for new, old in s.revises.items():
                    self.result.superseded[old] = f"revised in run {n} by {new}"
                self.cx_all.concessions += s.withdrawn
            self.active = [c for c in self.active if c.claim_id not in self.result.superseded] + [
                c for a in (THOR, LOKI) for c in subs[a].claims]
        if stop_after == Stage.ADVOCATES:
            return "stopped"

        new_claims = {a: subs[a].claims for a in (THOR, LOKI)}
        cx = run.cross_exam
        if n == 1 and failed:
            f = failed.copy().pop()
            msg = f"{f.value} failed ({subs[f].failed}); {OPP[f].value}'s claims went unchallenged"
            self.note(msg, run)
            cx.failures.append(msg)
            merge_cx(self.cx_all, cx)
            self.go(Stage.ODIN, msg)
        elif not [a for a in (THOR, LOKI) if a not in failed and new_claims[OPP[a]]]:
            for a in failed:
                if new_claims[OPP[a]]:
                    self.note(f"{a.value} failed in run {n}; {OPP[a].value}'s run-{n} claims went unchallenged", run)
            msg = f"run {n}: no new or revised claims that can be cross-examined"
            cx.failures.append(msg)
            self.go(Stage.ODIN, msg)
        else:
            for a in failed:
                if new_claims[OPP[a]]:
                    self.note(f"{a.value} failed in run {n}; {OPP[a].value}'s run-{n} claims went unchallenged", run)
            self.go(Stage.CROSS_EXAM, f"run {n}")
            self._cross_exam(run, case_text, new_claims, failed)
            merge_cx(self.cx_all, cx)
        if stop_after == Stage.CROSS_EXAM:
            return "stopped"

        if self.stage != Stage.ODIN:
            self.go(Stage.ODIN, f"run {n}")
        ids = {c.claim_id for c in self.active}
        view = cx_view(self.cx_all, ids, cx.failures + [m for m in run.notes if m not in cx.failures])
        to_rule, standing = list(self.active), []
        if n >= 2 and self.settings.delta_run:  # only new / revised claims are ruled; earlier rulings of the rest stand
            prior = {x.claim_id: x for x in self.final.odin.rulings}
            standing = [(c, prior[c.claim_id]) for c in self.active if c.run_number < n and c.claim_id in prior]
            held = {c.claim_id for c, _ in standing}
            to_rule = [c for c in self.active if c.claim_id not in held]
            self.note(f"run {n}: Odin rules on the {len(to_rule)} new or revised claim(s); the earlier rulings of "
                      f"{len(standing)} unchanged claim(s) stand", run)
        try:
            odin = run_odin(self.env(AgentName.ODIN), run.case_file, to_rule, view, run.notes, self._run_history(run),
                            standing=standing)
        except (LLMError, LimitHit) as exc:
            self._fail(AgentName.ODIN, exc, "judgment")
            if self.final is None:
                self.go(Stage.FAILED, "Odin could not rule; no briefing is produced from unruled claims")
                return "failed"
            self.note(f"Odin could not reassess in run {n}; the briefing uses the run {self.final.run_number} rulings", run)
            self.go(Stage.BRIEFING, f"Odin failed in run {n}")
            self._briefing(advance=False)
            return "finished"
        run.odin = odin
        run.ruled_claims = list(self.active)
        self.final = run
        self.result.odin = odin
        self.result.cross_exam = self.cx_all
        self._write_lessons(run, view)
        if n >= 2:
            self._log_effect(run)
        self.save()
        return "ruled"

    def _cross_exam(self, run: RunRecord, case_text: str, new_claims: dict[AgentName, list[Claim]],
                    failed: set[AgentName]) -> None:
        n = run.run_number
        cx = run.cross_exam
        own = {a: [c for c in self.active if c.agent == a] for a in (THOR, LOKI)}
        targets = dict(new_claims)
        counts = {THOR: 0, LOKI: 0}
        for rnd in range(1, self.settings.max_cross_exam_rounds + 1):
            attackers = [a for a in (THOR, LOKI) if a not in failed and targets[OPP[a]]]
            if not attackers:
                break
            res = self._parallel(
                {a: (lambda a=a: run_attacks(self.env(a), case_text, own[a], targets[OPP[a]], rnd, counts[a]))
                 for a in attackers}, f"cross-examination attacks (round {rnd})",
                default=lambda a, msg: ([], [{"reason": msg}]))
            round_attacks = []
            for a, (atts, rej) in res.items():
                cx.attacks += atts
                cx.rejected_attacks += rej
                counts[a] += len(atts)
                round_attacks += atts
                if not atts and rnd == 1:
                    msg = (f"{a.value} made no valid cross-examination attack; {OPP[a].value}'s claims went unchallenged"
                           + (f" in run {n}" if n > 1 else ""))
                    cx.failures.append(msg)
                    self.note(msg, run)
                    self.log(LogEventType.ERROR, msg, agent=a)
            on = {a: [x for x in round_attacks if x.target_agent == a] for a in (THOR, LOKI)}
            self._parallel({a: (lambda a=a: run_responses(self.env(a), case_text, own[a], on[a], cx))
                            for a in (THOR, LOKI) if on[a]},
                           f"cross-examination responses (round {rnd})", default=lambda a, msg: cx.failures.append(msg))
            # the two advocates answer in parallel threads: put their records in a fixed order (by attack ID) so the
            # record, the saved files and Odin's prompt do not depend on thread timing (a resumed case must replay
            # exactly the same prompts)
            cx.defenses.sort(key=lambda d: d.attack_id)
            cx.concessions.sort(key=lambda k: (k.attack_id or "", k.concession_id))
            cx.invalid_defenses.sort(key=lambda i: i.attack_id)
            cx.unanswered.sort()
            ids = {x.attack_id for x in round_attacks}
            defended = {d.claim_id for d in cx.defenses if d.attack_id in ids}
            targets = {a: [c for c in own[a] if c.claim_id in defended] for a in (THOR, LOKI)}
            if not defended:
                break
            if rnd == self.settings.max_cross_exam_rounds:
                self.log(LogEventType.LIMIT_HIT, f"cross-examination round limit reached ({rnd}/"
                         f"{self.settings.max_cross_exam_rounds} per run); {len(defended)} claim(s) defended in the last "
                         "round were not re-attacked", {"what": "cross-exam rounds", "used": rnd,
                                                        "limit": self.settings.max_cross_exam_rounds}, sorted(defended))

    # ------------------------------------------------- send-back decision ---

    def _after_odin(self, run: RunRecord) -> RunRecord | None:
        """Decide (in code) between the briefing and a send-back; run the send-back research.
        Returns the next run, or None to write the briefing now."""
        o = run.odin
        n = run.run_number
        if o.sufficient:
            return None
        if not o.missing:
            self.note(f"Odin judged the evidence insufficient after run {n} but named no specific missing evidence; "
                      "no send-back is possible, so the briefing is labelled incomplete", run)
            return None
        if n >= self.settings.max_runs:
            msg = (f"run limit reached ({n}/{self.settings.max_runs}): Odin still judges the evidence insufficient; "
                   "the briefing is labelled incomplete")
            self.log(LogEventType.LIMIT_HIT, msg, {"what": "runs", "used": n, "limit": self.settings.max_runs},
                     agent=AgentName.ODIN)
            self.note(msg, run)
            return None
        sb = SendBack(sendback_id=f"SB-{n}", run_number=n, reason=o.sufficiency_reason or "evidence insufficient",
                      missing=o.missing)
        run.sendback = sb
        self.pending_sendback = sb
        self.log(LogEventType.SENDBACK, f"Odin sends the case back after run {n}: {len(sb.missing)} missing item(s): "
                 + " | ".join(m.description[:80] for m in sb.missing), {"sendback": sb.model_dump(mode="json")},
                 agent=AgentName.ODIN)
        self._remember(AgentName.HEIMDALL, heimdall_sendback_lessons(self.masker, self.case_id, n, sb.missing))

        seen = set().union(*(e.retrieved for e in self.envs.values()))
        seen = {r for r in seen if not r.startswith("CALC-")}
        earlier = {e.payload["query_norm"] for e in self.store.events(self.case_id)
                   if e.type == LogEventType.QUERY and e.payload.get("query_norm") and e.seq >= self.start_seq}
        self.ctx.run_number = n + 1
        nxt = RunRecord(run_number=n + 1, case_file=run.case_file)
        self.result.runs.append(nxt)
        self.go(Stage.RESEARCH, f"send-back {sb.sendback_id}: run {n + 1}")
        self.pending_sendback = None
        try:
            out = run_sendback_research(self.env(AgentName.HEIMDALL), run.case_file, sb, earlier, seen)
        except (LLMError, LimitHit) as exc:
            self._fail(AgentName.HEIMDALL, exc, "send-back research")
            self.note(f"Heimdall's run {n + 1} research failed; the briefing uses the run {n} rulings and is incomplete", nxt)
            self.go(Stage.BRIEFING, f"Heimdall failed in run {n + 1}")
            return None
        nxt.research = out
        nxt.case_file = out.case_file
        self._remember(AgentName.HEIMDALL, heimdall_research_lessons(
            self.masker, self.store, self.case_id, n + 1,
            [{"description": it.description, "queries": it.queries, "new_refs": it.new_refs,
              "new_doc_ids": it.new_doc_ids} for it in out.items]))
        if not out.has_new_evidence:
            msg = (f"run {n + 1}: Heimdall's targeted searches found no genuinely new relevant evidence (code check: no "
                   f"cited ref outside run 1-{n} evidence and its duplicates); advocates and Odin were not re-run and the "
                   f"briefing (from the run {n} rulings) is labelled incomplete")
            self.note(msg, nxt)
            self.log(LogEventType.ERROR, msg, {"items": [it.__dict__ for it in out.items]}, agent=AgentName.HEIMDALL)
            self._remember(AgentName.ODIN, odin_lessons(self.case_id, n + 1, [], {"new_evidence": 0}))
            self.go(Stage.BRIEFING, "no genuinely new evidence")
        return nxt

    def _run_history(self, run: RunRecord) -> str:
        if run.run_number == 1:
            return ""
        lines = []
        for r in self.result.runs:
            if r.odin is not None:
                lines.append(f"Run {r.run_number} rulings: " + "; ".join(f"{x.claim_id} {x.verdict.value}" for x in r.odin.rulings))
                lines += [f"  run {r.run_number} range {e.country}/{e.sector}: {e.low}..{e.high} {e.unit}" for e in r.odin.ranges]
                lines += [f"  run {r.run_number} range {i['country']}/{i['sector']}: insufficient" for i in r.odin.insufficient]
            if r.sendback:
                lines.append(f"Send-back after run {r.run_number}: " + " | ".join(m.description for m in r.sendback.missing))
            if r.research:
                lines.append(f"Run {r.run_number} new evidence: "
                             + (", ".join(e["ref"] for e in r.research.new_evidence) or "none"))
        lines += [f"Superseded: {k} ({v})" for k, v in self.result.superseded.items()]
        return "\n".join(lines)

    def _log_effect(self, run: RunRecord) -> None:
        prev = next(r for r in reversed(self.result.runs) if r.odin is not None and r.run_number < run.run_number)
        new_refs = {e["ref"] for e in run.research.new_evidence}
        pv = {x.claim_id: x.verdict.value for x in prev.odin.rulings}
        cur = {x.claim_id: x.verdict.value for x in run.odin.rulings}
        claims = {c.claim_id: c for c in run.ruled_claims}
        citing = [cid for cid, c in claims.items()
                  if any((x.row_id or f"{x.doc_id}#{x.paragraph_ref}") in new_refs for x in c.citations)]
        changed_verdicts = {cid: f"{pv[cid]} -> {v}" for cid, v in cur.items() if cid in pv and pv[cid] != v}
        revised = {old: f"{pv.get(old, '?')} -> {new}: {cur.get(new, 'unruled')}" for new, old in
                   ((c.claim_id, c.revises_claim_id) for c in run.ruled_claims if c.revises_claim_id)}

        def ranges(o: OdinResult) -> dict:
            d = {f"{e.country}/{e.sector}".lower(): f"{e.low}..{e.high} {e.unit}" for e in o.ranges}
            d.update({f"{i['country']}/{i['sector']}".lower(): "insufficient" for i in o.insufficient})
            return d
        pr, cr = ranges(prev.odin), ranges(run.odin)
        changed_ranges = {k: f"{pr.get(k, 'none')} -> {v}" for k, v in cr.items() if pr.get(k) != v}
        eff = {"new_evidence": len(new_refs), "claims_citing_new_evidence": {c: cur.get(c) for c in citing},
               "verdict_changes": changed_verdicts, "revised": revised, "range_changes": changed_ranges,
               "sufficiency": {"before": prev.odin.sufficient, "after": run.odin.sufficient},
               "changed": len(changed_verdicts) + len(revised) + len(changed_ranges) + len(citing)}
        run.effect = eff
        self.log(LogEventType.NEW_EVIDENCE, f"effect of run {run.run_number} new evidence: {len(citing)} claim(s) cite it, "
                 f"{len(changed_verdicts)} verdict change(s), {len(revised)} revised claim(s), {len(changed_ranges)} "
                 f"range change(s); sufficiency {prev.odin.sufficient} -> {run.odin.sufficient}",
                 {"phase": "effect", **eff}, sorted(new_refs) + citing, agent=AgentName.ODIN)
        self._remember(AgentName.ODIN, odin_lessons(self.case_id, run.run_number, [], eff))

    def _write_lessons(self, run: RunRecord, view: CrossExam) -> None:
        o = run.odin
        for a in (THOR, LOKI):
            self._remember(a, advocate_lessons(self.store, self.masker, a, self.case_id, run.run_number, run.ruled_claims,
                                               o.rulings, o.prechecks, view))
        self._remember(AgentName.ODIN, odin_lessons(self.case_id, run.run_number, o.guards, None))

    # ----------------------------------------------------------- briefing ---

    def _briefing(self, advance: bool = True) -> None:
        if advance:
            self.go(Stage.BRIEFING)
        fin = self.final
        odin = fin.odin
        claims = fin.ruled_claims
        ids = {c.claim_id for c in claims}
        concessions = {c.claim_id: c for c in self.cx_all.concessions if c.claim_id in ids}
        traps = [e.summary for e in self.store.events(self.case_id) if e.type == LogEventType.TRAP_INJECTION
                 and e.seq >= self.start_seq]
        runs = []
        for r in self.result.runs:
            runs.append(RunSummary(
                run_number=r.run_number, claims=[c.claim_id for c in r.ruled_claims],
                verdicts={x.claim_id: x.verdict.value for x in r.odin.rulings} if r.odin else {},
                sufficient=r.odin.sufficient if r.odin else None,
                sufficiency_reason=r.odin.sufficiency_reason if r.odin else "",
                sendback_missing=[m.description for m in r.sendback.missing] if r.sendback else [],
                new_evidence=[e["ref"] for e in r.research.new_evidence] if r.research else [],
                note=" | ".join(r.notes)[:1000]))
        # a claim its own author withdrew in a later run is a concession: it is reported under the conceded
        # findings with its last ruling and the reason; a claim replaced by a revision stays "superseded"
        withdrawn: list[tuple[Claim, Ruling | None, str]] = []
        for cid, why in self.result.superseded.items():
            if cid in ids or not why.startswith("withdrawn"):
                continue
            for r in reversed(self.result.runs):
                c = next((x for x in r.ruled_claims if x.claim_id == cid), None)
                if c is not None:
                    withdrawn.append((c, next((x for x in (r.odin.rulings if r.odin else []) if x.claim_id == cid), None), why))
                    break
        gone = {c.claim_id for c, _, _ in withdrawn}
        superseded = [f"{k}: {v}" for k, v in self.result.superseded.items() if k not in ids and k not in gone]
        briefing, md, dropped = build_briefing(
            self.store, fin.case_file, claims, odin, concessions, self.result.notes, sorted(set(traps)),
            runs_completed=self.result.runs_completed, runs=runs, superseded=superseded, final_run=fin.run_number,
            calc=self.service.calculator(self.ctx.as_of), withdrawn=withdrawn)
        for d in dropped:
            self.log(LogEventType.ERROR, f"briefing check dropped {d['where']}: {d['ref']} ({'; '.join(d['issues'])})"[:500],
                     {"briefing_check": d}, [d["ref"]], agent=AgentName.ODIN)
        self.result.odin = odin
        self.result.briefing_md = md
        self.result.briefing_status = briefing.status
        (self.case_dir / "briefing.md").write_text(md, encoding="utf-8")
        (self.case_dir / "briefing.json").write_text(briefing.model_dump_json(indent=2), encoding="utf-8")
        self.log(LogEventType.BRIEFING, f"briefing written ({briefing.status}, {self.result.runs_completed} run(s), rulings "
                 f"of run {fin.run_number}): {len(briefing.established)} established, {len(briefing.contested)} contested, "
                 f"{len(briefing.conceded)} conceded, {len(briefing.rejected)} rejected",
                 {"status": briefing.status, "final_run": fin.run_number}, agent=AgentName.ODIN)
        self.go(Stage.DONE)

    def _limitation_report(self) -> None:
        """When no briefing can be produced: say exactly what was and was not done."""
        r = self.result
        L = [f"# Limitation report - case {self.case_id}", "", f"**Question:** {self.ctx.question}  ",
             f"**As of:** {self.ctx.as_of}  ", f"**Outcome:** FAILED at stage path {' -> '.join(r.history)}", "",
             "No briefing was produced. No verdicts, ranges or findings were invented.", "", "## What completed", ""]
        if r.heimdall:
            cf = r.heimdall.case_file
            L.append(f"- Heimdall built the Case File: event {cf.event_status.value}; {len(cf.trade_table_ids)} trade table(s).")
        for run in r.runs:
            for a, s in run.submissions.items():
                L.append(f"- Run {run.run_number}: {a} submitted {len(s.claims)} claim(s)"
                         + (f" (failed: {s.failed})" if s.failed else ""))
            if run.odin:
                L.append(f"- Run {run.run_number}: Odin ruled on {len(run.odin.rulings)} claim(s).")
        if not r.heimdall:
            L.append("- Nothing: the investigation failed before the Case File was built.")
        L += ["", "## What failed", ""] + [f"- {n}" for n in r.notes or ["(no failure message recorded)"]]
        L += ["", "All recorded events are in events.jsonl."]
        (self.case_dir / "limitations.md").write_text("\n".join(L) + "\n", encoding="utf-8")

    def _parallel(self, jobs: dict[AgentName, Any], what: str, default) -> dict[AgentName, Any]:
        out: dict[AgentName, Any] = {}
        if not jobs:
            return out
        with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
            futs = {a: pool.submit(fn) for a, fn in jobs.items()}
            for a, f in futs.items():
                try:
                    out[a] = f.result()
                except (LLMError, LimitHit) as exc:
                    out[a] = default(a, self._fail(a, exc, what))
        return out

    # ------------------------------------------------------------ persist ---

    @staticmethod
    def _cx_json(cx: CrossExam) -> dict:
        return {"attacks": [a.model_dump(mode="json") for a in cx.attacks],
                "defenses": [x.model_dump(mode="json") for x in cx.defenses],
                "concessions": [x.model_dump(mode="json") for x in cx.concessions],
                "invalid_defenses": [x.__dict__ | {"agent": x.agent.value} for x in cx.invalid_defenses],
                "unanswered": cx.unanswered, "failures": cx.failures, "rejected_attacks": cx.rejected_attacks}

    @staticmethod
    def _odin_json(o: OdinResult) -> dict:
        return {"rulings": [x.model_dump(mode="json") for x in o.rulings],
                "odin_ranges": [x.model_dump(mode="json") for x in o.ranges],
                "insufficient": o.insufficient, "sufficient": o.sufficient, "sufficiency_reason": o.sufficiency_reason,
                "missing": [m.model_dump(mode="json") for m in o.missing],
                "prechecks": {k: v.__dict__ for k, v in o.prechecks.items()}, "guards": o.guards, "unruled": o.unruled}

    def save(self, final: bool = False) -> None:
        d = self.case_dir
        d.mkdir(parents=True, exist_ok=True)
        r = self.result

        def dump(path: Path, obj: Any) -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(obj, indent=2, default=str), encoding="utf-8")

        dump(d / "state.json", {"case_id": r.case_id, "question": self.ctx.question, "as_of": self.ctx.as_of,
                                "stage": r.stage.value, "history": r.history, "run_number": self.ctx.run_number,
                                "runs_completed": r.runs_completed, "max_runs": self.settings.max_runs,
                                "stop_after": getattr(self, "stop_after", None),
                                "briefing_status": r.briefing_status, "notes": r.notes, "stop_reason": r.stop_reason,
                                "superseded": r.superseded, "usage": self._usage(), "attempt": self.attempt,
                                "paused_until": self.paused_until.isoformat() if self.paused_until else None})
        dump(d / "llm_calls.json", {"summary": self.ledger.call_summary(), "calls": list(self.ledger.records)})
        if r.heimdall:
            dump(d / "case_file.json", (self.final.case_file if self.final else r.heimdall.case_file).model_dump(mode="json"))
            dump(d / "heimdall_report.json", {"report": r.heimdall.report.model_dump(mode="json"), "dropped": r.heimdall.dropped})
        for run in r.runs:
            rd = d / f"run-{run.run_number}"
            dump(rd / "case_file.json", run.case_file.model_dump(mode="json"))
            if run.submissions:
                dump(rd / "claims.json", {a: {"claims": [c.model_dump(mode="json") for c in s.claims],
                                              "withdrawn": [k.model_dump(mode="json") for k in s.withdrawn],
                                              "revises": s.revises, "rejected_in_code": s.rejected, "failed": s.failed}
                                          for a, s in run.submissions.items()})
            dump(rd / "cross_exam.json", self._cx_json(run.cross_exam))
            if run.odin:
                dump(rd / "rulings.json", self._odin_json(run.odin) | {"ruled_claims": [c.claim_id for c in run.ruled_claims]})
            if run.sendback:
                dump(rd / "sendback.json", run.sendback.model_dump(mode="json"))
            if run.research:
                dump(rd / "research.json", {"items": [it.__dict__ for it in run.research.items],
                                            "new_evidence": run.research.new_evidence,
                                            "refused_queries": run.research.refused_queries,
                                            "still_missing": run.research.still_missing})
            if run.effect:
                dump(rd / "new_evidence_effect.json", run.effect)
        if r.runs and r.runs[0].submissions:
            claims = {c.claim_id: c for run in r.runs for s in run.submissions.values() for c in s.claims}
            dump(d / "claims.json", {"active": [c.claim_id for c in (self.final.ruled_claims if self.final else self.active)],
                                     "superseded": r.superseded,
                                     "claims": [c.model_dump(mode="json") for c in claims.values()]})
            dump(d / "cross_exam.json", self._cx_json(self.cx_all))
        if self.final:
            dump(d / "rulings.json", self._odin_json(self.final.odin) | {"run_number": self.final.run_number})
        dump(d / "evidence_refs.json", {a.value: sorted(e.retrieved) for a, e in self.envs.items()})
        if final:
            dump(d / "config.json", self.settings.public_summary())
            dump(d / "memory.json", {a.value: [json.loads(m.model_dump_json()) for m in e.memory.all()]
                                     for a, e in self.envs.items()})
            self.store.export_jsonl(d / "events.jsonl", self.case_id)
