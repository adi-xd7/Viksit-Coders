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
  const ended = events.some((e) => e.type === "RUN_END");
  useEffect(() => {
    if (ended && caseId) api.getCase(caseId).then(setStatus).catch(() => undefined);
  }, [ended, caseId]);

  const trial = useMemo(() => deriveTrial(events), [events]);
  return { status, events, error, transport, trial };
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
}

/** Trial objects come straight from the recorded CLAIM / ATTACK / DEFENSE / CONCESSION / RULING events. */
export function deriveTrial(events: LogEvent[]): TrialState {
  const claims = new Map<string, Claim>();
  const attacks: Attack[] = [];
  const defenses: Defense[] = [];
  const concessions: Concession[] = [];
  const rulings: Record<string, Ruling[]> = {};
  const invalidDefenses: LogEvent[] = [];
  const retrievedDocs = new Map<string, { runs: Set<number>; agents: Set<string> }>();
  const runs = new Set<number>();
  for (const e of events) {
    if (e.run_number > 0) runs.add(e.run_number);
    const p = e.payload ?? {};
    if (e.type === "CLAIM" && p.claim) claims.set(p.claim.claim_id, p.claim);
    else if (e.type === "ATTACK" && p.attack) attacks.push(p.attack);
    else if (e.type === "DEFENSE" && p.defense) defenses.push(p.defense);
    else if (e.type === "CONCESSION" && p.concession) concessions.push(p.concession);
    else if (e.type === "RULING" && p.ruling) (rulings[p.ruling.claim_id] ??= []).push(p.ruling);
    else if (e.type === "ERROR" && /^defense of .* invalid/.test(e.summary)) invalidDefenses.push(e);
    if (e.type === "RETRIEVED" && ["heimdall", "thor", "loki", "odin"].includes(e.agent)) {
      for (const ref of e.refs) {
        if (ref.startsWith("CALC-")) continue;
        const doc = ref.split("#")[0];
        const r = retrievedDocs.get(doc) ?? { runs: new Set<number>(), agents: new Set<string>() };
        r.runs.add(e.run_number);
        r.agents.add(e.agent);
        retrievedDocs.set(doc, r);
      }
    }
  }
  return { claims: [...claims.values()], attacks, defenses, concessions, rulings, invalidDefenses, retrievedDocs,
    runs: [...runs].sort() };
}
