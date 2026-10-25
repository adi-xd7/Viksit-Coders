import { useEffect, useMemo, useRef, useState } from "react";
import { api, Attack, CaseStatus, Claim, Concession, Defense, EVENT_TYPES, LogEvent, Ruling } from "./api";

/** Live state of one case: its status (GET /cases/{id}) and its real audit events (SSE, polling fallback). */
export function useCase(caseId: string | null) {
  const [status, setStatus] = useState<CaseStatus | null>(null);
  const [events, setEvents] = useState<LogEvent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [transport, setTransport] = useState<"sse" | "polling" | "idle">("idle");
  const seen = useRef<Set<number>>(new Set());
  const lastSeq = useRef(0);

  const add = (evs: LogEvent[]) => {
    const fresh = evs.filter((e) => !seen.current.has(e.seq));
    if (!fresh.length) return;
    fresh.forEach((e) => {
      seen.current.add(e.seq);
      lastSeq.current = Math.max(lastSeq.current, e.seq);
    });
    setEvents((prev) => [...prev, ...fresh].sort((a, b) => a.seq - b.seq));
  };

  // status: poll while running, fetch once more when it finishes
  useEffect(() => {
    setStatus(null);
    setEvents([]);
    setError(null);
    seen.current = new Set();
    lastSeq.current = 0;
    if (!caseId) return;
    let stop = false;
    let timer: number | undefined;
    const tick = async () => {
      try {
        const s = await api.getCase(caseId);
        if (stop) return;
        setStatus(s);
        setError(null);
        if (s.status === "running") timer = window.setTimeout(tick, 3000);
      } catch (e: any) {
        if (stop) return;
        setError(e.message);
        timer = window.setTimeout(tick, 5000);
      }
    };
    tick();
    return () => {
      stop = true;
      window.clearTimeout(timer);
    };
  }, [caseId]);

  // events: EventSource with named events; on error fall back to polling
  useEffect(() => {
    if (!caseId) return;
    let closed = false;
    let pollTimer: number | undefined;
    const poll = async () => {
      setTransport("polling");
      try {
        add(await api.eventsOnce(caseId, lastSeq.current));
      } catch {
        /* keep polling */
      }
      if (!closed) pollTimer = window.setTimeout(poll, 3000);
    };
    if (typeof EventSource === "undefined") {
      poll();
      return () => {
        closed = true;
        window.clearTimeout(pollTimer);
      };
    }
    const es = new EventSource(`/cases/${encodeURIComponent(caseId)}/events?after=0`);
    setTransport("sse");
    const onEvent = (m: MessageEvent) => {
      try {
        add([JSON.parse(m.data)]);
      } catch {
        /* ignore */
      }
    };
    EVENT_TYPES.forEach((t) => es.addEventListener(t, onEvent as EventListener));
    es.addEventListener("end", () => {
      es.close();
      setTransport("idle");
    });
    es.onerror = () => {
      if (es.readyState === EventSource.CLOSED || !closed) {
        es.close();
        if (!closed) poll();
      }
    };
    return () => {
      closed = true;
      es.close();
      window.clearTimeout(pollTimer);
    };
  }, [caseId]);

  // when the stream reports the end of the trial, refresh the status/results once
  const ended = latestAttempt(events).some((e) => e.type === "RUN_END");
  useEffect(() => {
    if (ended && caseId) api.getCase(caseId).then(setStatus).catch(() => undefined);
  }, [ended, caseId]);

  const trial = useMemo(() => deriveTrial(events), [events]);
  return { status, events, error, transport, trial, loaded: status !== null || error !== null };
}

export interface CalcRecord {
  calc_id: string;
  operation: string;
  formula: string;
  result: number | null;
  unit: string;
  inputs: { row_id?: string | null }[];
  parameters?: Record<string, any>;
  excluded_rows?: Record<string, string>;
  complete?: boolean;
  notes?: string;
}

export interface TrialState {
  claims: Claim[];
  attacks: Attack[];
  defenses: Defense[];
  concessions: Concession[];
  rulings: Record<string, Ruling[]>; // claim -> rulings in run order
  invalidDefenses: LogEvent[];
  retrievedDocs: Map<string, { runs: Set<number>; agents: Set<string> }>;
  runs: number[];
  // further facts read from recorded events (latest attempt)
  caseFile: any | null; // last CASE_FILE payload
  maxRuns: number | null; // from RUN_START config
  sendbacks: LogEvent[];
  sufficiency: LogEvent[];
  newEvidence: LogEvent[]; // NEW_EVIDENCE phase=found
  effect: LogEvent | null; // NEW_EVIDENCE phase=effect
  researchPlans: LogEvent[];
  memoryApplied: LogEvent[];
  memoryReads: number;
  blockedDocs: Map<string, string>; // doc -> summary of the CLOCK_VIOLATION_BLOCKED event
  refsByRun: Map<number, Set<string>>; // distinct retrieved paragraphs/rows per run
  calcs: Map<string, CalcRecord>;
  attempt: number;
  ended: boolean; // RUN_END recorded in the latest attempt
  liveFeed: { doc_id: string; seq: number; ts: string; agent: string; run: number; refs: string[] }[]; // first retrieval per document
}

/** Events of the latest attempt: a resumed case re-records its replayed steps after a new RUN_START. */
export function latestAttempt(events: LogEvent[]): LogEvent[] {
  let start = 0;
  events.forEach((e, i) => {
    if (e.type === "RUN_START") start = i;
  });
  return events.slice(start);
}

/** Trial objects come straight from the recorded CLAIM / ATTACK / DEFENSE / CONCESSION / RULING events
 * (of the latest attempt, so a resumed case is not shown twice). */
export function deriveTrial(all: LogEvent[]): TrialState {
  const events = latestAttempt(all);
  const claims = new Map<string, Claim>();
  const attacks: Attack[] = [];
  const defenses: Defense[] = [];
  const concessions: Concession[] = [];
  const rulings: Record<string, Ruling[]> = {};
  const invalidDefenses: LogEvent[] = [];
  const retrievedDocs = new Map<string, { runs: Set<number>; agents: Set<string> }>();
  const runs = new Set<number>();
  const st: Omit<TrialState, "claims" | "attacks" | "defenses" | "concessions" | "rulings" | "invalidDefenses" |
    "retrievedDocs" | "runs"> = {
    caseFile: null, maxRuns: null, sendbacks: [], sufficiency: [], newEvidence: [], effect: null, researchPlans: [],
    memoryApplied: [], memoryReads: 0, blockedDocs: new Map(), refsByRun: new Map(), calcs: new Map(),
    attempt: all.filter((e) => e.type === "RUN_START").length || 1, ended: false, liveFeed: [],
  };
  const fed = new Map<string, TrialState["liveFeed"][number]>();
  for (const e of events) {
    if (e.run_number > 0) runs.add(e.run_number);
    const p = e.payload ?? {};
    if (e.type === "CLAIM" && p.claim) claims.set(p.claim.claim_id, p.claim);
    else if (e.type === "ATTACK" && p.attack) attacks.push(p.attack);
    else if (e.type === "DEFENSE" && p.defense) defenses.push(p.defense);
    else if (e.type === "CONCESSION" && p.concession) concessions.push(p.concession);
    else if (e.type === "RULING" && p.ruling) (rulings[p.ruling.claim_id] ??= []).push(p.ruling);
    else if (e.type === "ERROR" && /^defense of .* invalid/.test(e.summary)) invalidDefenses.push(e);
    else if (e.type === "CASE_FILE" && p.case_file) st.caseFile = p.case_file;
    else if (e.type === "RUN_START") st.maxRuns = p.config?.max_runs ?? null;
    else if (e.type === "RUN_END") st.ended = true;
    else if (e.type === "SENDBACK") st.sendbacks.push(e);
    else if (e.type === "SUFFICIENCY") st.sufficiency.push(e);
    else if (e.type === "NEW_EVIDENCE" && p.phase === "found") st.newEvidence.push(e);
    else if (e.type === "NEW_EVIDENCE" && p.phase === "effect") st.effect = e;
    else if (e.type === "RESEARCH_PLAN") st.researchPlans.push(e);
    else if (e.type === "MEMORY_APPLIED") st.memoryApplied.push(e);
    else if (e.type === "MEMORY_READ") st.memoryReads += 1;
    else if (e.type === "CLOCK_VIOLATION_BLOCKED") e.refs.forEach((r) => st.blockedDocs.set(r.split("#")[0], e.summary));
    if (e.type === "RETRIEVED" && p.calc?.calc_id) st.calcs.set(p.calc.calc_id, p.calc);
    if (e.type === "RETRIEVED" && ["heimdall", "thor", "loki", "odin"].includes(e.agent)) {
      const set = st.refsByRun.get(e.run_number) ?? new Set<string>();
      for (const ref of e.refs) {
        if (ref.startsWith("CALC-")) continue;
        set.add(ref);
        const doc = ref.split("#")[0];
        const r = retrievedDocs.get(doc) ?? { runs: new Set<number>(), agents: new Set<string>() };
        r.runs.add(e.run_number);
        r.agents.add(e.agent);
        retrievedDocs.set(doc, r);
        const f = fed.get(doc);
        if (!f) fed.set(doc, { doc_id: doc, seq: e.seq, ts: e.ts, agent: e.agent, run: e.run_number, refs: [ref] });
        else if (!f.refs.includes(ref) && f.refs.length < 6) f.refs.push(ref);
      }
      st.refsByRun.set(e.run_number, set);
    }
  }
  st.liveFeed = [...fed.values()].sort((a, b) => b.seq - a.seq);
  return { claims: [...claims.values()], attacks, defenses, concessions, rulings, invalidDefenses, retrievedDocs,
    runs: [...runs].sort((a, b) => a - b), ...st };
}

/** The latest ruling of a claim (rulings are recorded per run). */
export function latestRuling(t: TrialState, claimId: string): Ruling | undefined {
  const rs = t.rulings[claimId];
  return rs ? rs[rs.length - 1] : undefined;
}
