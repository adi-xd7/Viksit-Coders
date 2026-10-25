"""The trial state machine (explicit; no planner node).

    HEIMDALL -> THOR || LOKI -> CROSS_EXAMINATION -> ODIN -> BRIEFING -> DONE
    HEIMDALL -> STOPPED            (event disproved: the trial stops, the user is told why)
    THOR || LOKI -> ODIN           (only when one advocate failed: its opponent goes unchallenged)
    any -> FAILED                  (unrecoverable error; completed work is kept and reported)

Transitions are checked against ALLOWED in code. Agent output never selects the
next stage; only Heimdall's verification status (disproved) and agent failures
change the path, and both are evaluated by this module.
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

from ragnarok.agents.advocates import CrossExam, Submission, run_attacks, run_brief, run_responses
from ragnarok.agents.common import AgentEnv, CaseContext
from ragnarok.agents.heimdall import HeimdallOutcome, render_case_file, run_heimdall
from ragnarok.agents.odin import OdinResult, run_odin
from ragnarok.briefing.build import build_briefing
from ragnarok.config import Settings, get_settings
from ragnarok.llm.client import Backend, LimitHit, LLMClient, LLMError, TokenLedger
from ragnarok.models import AgentName, EventStatus, LogEvent, LogEventType
from ragnarok.retrieval.service import RetrievalService
from ragnarok.store.db import Store


class Stage(StrEnum):
    START = "START"
    HEIMDALL = "HEIMDALL"
    ADVOCATES = "THOR_LOKI"
    CROSS_EXAM = "CROSS_EXAMINATION"
    ODIN = "ODIN"
    BRIEFING = "BRIEFING"
    DONE = "DONE"
    STOPPED = "STOPPED"
    FAILED = "FAILED"


ALLOWED: dict[Stage, set[Stage]] = {
    Stage.START: {Stage.HEIMDALL},
    Stage.HEIMDALL: {Stage.ADVOCATES, Stage.STOPPED, Stage.FAILED},
    Stage.ADVOCATES: {Stage.CROSS_EXAM, Stage.ODIN, Stage.FAILED},
    Stage.CROSS_EXAM: {Stage.ODIN, Stage.FAILED},
    Stage.ODIN: {Stage.BRIEFING, Stage.FAILED},
    Stage.BRIEFING: {Stage.DONE},
}


class IllegalTransition(RuntimeError):
    pass


@dataclass
class TrialResult:
    case_id: str
    stage: Stage
    history: list[str]
    case_dir: Path
    heimdall: HeimdallOutcome | None = None
    submissions: dict[str, Submission] = field(default_factory=dict)
    cross_exam: CrossExam | None = None
    odin: OdinResult | None = None
    briefing_md: str | None = None
    notes: list[str] = field(default_factory=list)  # failures and unchallenged sides, reported honestly
    usage: dict[str, Any] = field(default_factory=dict)
    stop_reason: str | None = None


def new_case_id(question: str, as_of: date) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    h = hashlib.sha256(f"{question}|{as_of}|{ts}".encode()).hexdigest()[:6]
    return f"case-{ts}-{h}"


class Trial:
    def __init__(self, question: str, as_of: date, store: Store, settings: Settings | None = None,
                 backend: Backend | None = None, service: RetrievalService | None = None, case_id: str | None = None) -> None:
        self.settings = settings or get_settings()
        self.store = store
        self.service = service or RetrievalService(store, self.settings)
        self.case_id = case_id or new_case_id(question, as_of)
        self.ledger = TokenLedger(self.settings.max_tokens_per_agent, self.settings.max_tokens_per_case)
        self.llm = LLMClient(self.settings, self.ledger, backend, on_event=self._llm_event)
        self.ctx = CaseContext(case_id=self.case_id, question=question, as_of=as_of, settings=self.settings, llm=self.llm)
        self.stage = Stage.START
        self.case_dir = self.settings.cases_dir / self.case_id
        self.result = TrialResult(case_id=self.case_id, stage=self.stage, history=[], case_dir=self.case_dir)
        self.envs: dict[AgentName, AgentEnv] = {}

    # ------------------------------------------------------------ helpers ---

    def _llm_event(self, kind: str, agent: AgentName, summary: str, payload: dict) -> None:
        with Store(self.store.path) as s:  # own connection: may be called from an advocate thread
            s.append_event(LogEvent(case_id=self.case_id, run_number=self.ctx.run_number, agent=agent,
                                    type=LogEventType.ERROR, summary=summary[:500], payload={"llm": kind, **payload}))

    def log(self, type_: LogEventType, summary: str, payload: dict | None = None, refs: list[str] | None = None,
            agent: AgentName = AgentName.SYSTEM) -> None:
        self.store.append_event(LogEvent(case_id=self.case_id, run_number=self.ctx.run_number, agent=agent, type=type_,
                                         summary=summary[:500], payload=payload or {}, refs=refs or []))

    def go(self, nxt: Stage, why: str = "") -> None:
        if nxt not in ALLOWED.get(self.stage, set()):
            raise IllegalTransition(f"{self.stage} -> {nxt} is not an allowed transition")
        self.log(LogEventType.STAGE, f"{self.stage.value} -> {nxt.value}{': ' + why if why else ''}",
                 {"from": self.stage.value, "to": nxt.value})
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
        msg = f"{agent.value} failed during {what}: {exc}"
        self.log(kind, msg[:500], {"exception": type(exc).__name__}, agent=agent)
        self.result.notes.append(msg[:300])
        return msg

    # ---------------------------------------------------------------- run ---

    def run(self, stop_after: Stage | None = None) -> TrialResult:
        self.case_dir.mkdir(parents=True, exist_ok=True)
        self.service.index.refresh(store=self.store)
        self.log(LogEventType.RUN_START, f"trial started: {self.ctx.question} (as of {self.ctx.as_of})",
                 {"question": self.ctx.question, "as_of": self.ctx.as_of.isoformat(), "config": self.settings.public_summary()})
        try:
            self._run(stop_after)
        except IllegalTransition:
            raise
        except Exception as exc:  # noqa: BLE001 - never fabricate success; record and stop
            self.result.notes.append(f"trial failed: {type(exc).__name__}: {exc}"[:300])
            self.log(LogEventType.ERROR, f"trial failed: {type(exc).__name__}: {exc}"[:500])
            if self.stage not in (Stage.FAILED, Stage.DONE, Stage.STOPPED):
                self.stage = Stage.FAILED
                self.result.stage = Stage.FAILED
                self.result.history.append(Stage.FAILED.value)
        finally:
            self.result.usage = {"tokens": self.ledger.snapshot(), "tool_calls": dict(self.ctx.tool_calls)}
            self.log(LogEventType.RUN_END, f"trial ended at {self.stage.value}", {"usage": self.result.usage})
            self.save(final=True)
            for a, e in self.envs.items():
                if e.service is not self.service:
                    e.service.store.close()
        return self.result

    def _run(self, stop_after: Stage | None) -> None:
        # HEIMDALL
        self.go(Stage.HEIMDALL)
        try:
            h = run_heimdall(self.env(AgentName.HEIMDALL))
        except (LLMError, LimitHit) as exc:
            self._fail(AgentName.HEIMDALL, exc, "investigation")
            self.go(Stage.FAILED, "Heimdall could not build the Case File")
            return
        self.result.heimdall = h
        if h.case_file.event_status == EventStatus.DISPROVED:
            self.result.stop_reason = (f"Heimdall found the event disproved as of {self.ctx.as_of}: "
                                       f"{h.case_file.event_verification_notes}")
            self.go(Stage.STOPPED, "event disproved; no trial on a disproved event")
            return
        if stop_after == Stage.HEIMDALL:
            return

        # THOR || LOKI
        self.go(Stage.ADVOCATES)
        case_text = render_case_file(h.case_file)
        subs = self._parallel({a: (lambda a=a: run_brief(self.env(a), case_text)) for a in (AgentName.THOR, AgentName.LOKI)},
                              "brief", default=lambda a, msg: Submission(failed=msg))
        self.result.submissions = {a.value: s for a, s in subs.items()}
        ok = {a for a, s in subs.items() if s.claims}
        if not ok:
            self.result.notes.append("both advocates failed: no claims to try")
            self.go(Stage.FAILED, "both advocates failed")
            return
        if stop_after == Stage.ADVOCATES:
            return

        cx = CrossExam()
        self.result.cross_exam = cx
        thor, loki = AgentName.THOR, AgentName.LOKI
        if ok == {thor, loki}:
            self.go(Stage.CROSS_EXAM)
            claims = {a: subs[a].claims for a in (thor, loki)}
            opp = {thor: loki, loki: thor}
            attacks = self._parallel(
                {a: (lambda a=a: run_attacks(self.env(a), case_text, claims[a], claims[opp[a]])) for a in (thor, loki)},
                "cross-examination attacks", default=lambda a, msg: ([], [{"reason": msg}]))
            for a, (atts, rej) in attacks.items():
                cx.attacks += atts
                cx.rejected_attacks += rej
                if not atts:
                    note = f"{a.value} made no valid cross-examination attack; {opp[a].value}'s claims went unchallenged"
                    cx.failures.append(note)
                    self.result.notes.append(note)
                    self.log(LogEventType.ERROR, note, agent=a)
            on = {a: [x for x in cx.attacks if x.target_agent == a] for a in (thor, loki)}
            self._parallel({a: (lambda a=a: run_responses(self.env(a), case_text, claims[a], on[a], cx)) for a in (thor, loki)},
                           "cross-examination responses", default=lambda a, msg: cx.failures.append(msg))
        else:
            failed = ({thor, loki} - ok).pop()
            note = f"{failed.value} failed ({subs[failed].failed}); {ok.copy().pop().value}'s claims went unchallenged"
            self.result.notes.append(note)
            cx.failures.append(note)
            self.go(Stage.ODIN, note)
        if stop_after == Stage.CROSS_EXAM:
            return

        # ODIN
        if self.stage != Stage.ODIN:
            self.go(Stage.ODIN)
        all_claims = [c for a in (thor, loki) for c in subs[a].claims]
        try:
            odin = run_odin(self.env(AgentName.ODIN), h.case_file, all_claims, cx, self.result.notes)
        except (LLMError, LimitHit) as exc:
            self._fail(AgentName.ODIN, exc, "judgment")
            self.go(Stage.FAILED, "Odin could not rule; no briefing is produced from unruled claims")
            return
        self.result.odin = odin

        # BRIEFING
        self.go(Stage.BRIEFING)
        traps = [f"{e.summary}" for e in self.store.events(self.case_id) if e.type == LogEventType.TRAP_INJECTION]
        briefing, md = build_briefing(self.store, h.case_file, all_claims, odin, {c.claim_id: c for c in cx.concessions},
                                      self.result.notes, sorted(set(traps)))
        self.result.briefing_md = md
        (self.case_dir / "briefing.md").write_text(md, encoding="utf-8")
        (self.case_dir / "briefing.json").write_text(briefing.model_dump_json(indent=2), encoding="utf-8")
        self.log(LogEventType.BRIEFING, f"briefing written ({briefing.status}): {len(briefing.established)} established, "
                 f"{len(briefing.contested)} contested, {len(briefing.conceded)} conceded, {len(briefing.rejected)} rejected",
                 {"status": briefing.status}, agent=AgentName.ODIN)
        self.go(Stage.DONE)

    def _parallel(self, jobs: dict[AgentName, Any], what: str, default) -> dict[AgentName, Any]:
        out: dict[AgentName, Any] = {}
        with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
            futs = {a: pool.submit(fn) for a, fn in jobs.items()}
            for a, f in futs.items():
                try:
                    out[a] = f.result()
                except (LLMError, LimitHit) as exc:
                    out[a] = default(a, self._fail(a, exc, what))
        return out

    # ------------------------------------------------------------ persist ---

    def save(self, final: bool = False) -> None:
        d = self.case_dir
        d.mkdir(parents=True, exist_ok=True)
        r = self.result

        def dump(name: str, obj: Any) -> None:
            (d / name).write_text(json.dumps(obj, indent=2, default=str), encoding="utf-8")

        dump("state.json", {"case_id": r.case_id, "question": self.ctx.question, "as_of": self.ctx.as_of,
                            "stage": r.stage.value, "history": r.history, "notes": r.notes, "stop_reason": r.stop_reason,
                            "usage": r.usage})
        if r.heimdall:
            dump("case_file.json", r.heimdall.case_file.model_dump(mode="json"))
            dump("heimdall_report.json", {"report": r.heimdall.report.model_dump(mode="json"), "dropped": r.heimdall.dropped})
        if r.submissions:
            dump("claims.json", {a: {"claims": [c.model_dump(mode="json") for c in s.claims], "rejected_in_code": s.rejected,
                                     "failed": s.failed} for a, s in r.submissions.items()})
        if r.cross_exam:
            cx = r.cross_exam
            dump("cross_exam.json", {"attacks": [a.model_dump(mode="json") for a in cx.attacks],
                                     "defenses": [x.model_dump(mode="json") for x in cx.defenses],
                                     "concessions": [x.model_dump(mode="json") for x in cx.concessions],
                                     "invalid_defenses": [x.__dict__ | {"agent": x.agent.value} for x in cx.invalid_defenses],
                                     "unanswered": cx.unanswered, "failures": cx.failures,
                                     "rejected_attacks": cx.rejected_attacks})
        if r.odin:
            o = r.odin
            dump("rulings.json", {"rulings": [x.model_dump(mode="json") for x in o.rulings],
                                  "odin_ranges": [x.model_dump(mode="json") for x in o.ranges],
                                  "insufficient": o.insufficient, "sufficient": o.sufficient,
                                  "sufficiency_reason": o.sufficiency_reason,
                                  "missing": [m.model_dump(mode="json") for m in o.missing],
                                  "prechecks": {k: v.__dict__ for k, v in o.prechecks.items()},
                                  "guards": o.guards, "unruled": o.unruled})
        evidence = {a.value: sorted(e.retrieved) for a, e in self.envs.items()}
        dump("evidence_refs.json", evidence)
        if final:
            dump("config.json", self.settings.public_summary())
            self.store.export_jsonl(d / "events.jsonl", self.case_id)
