import { Fragment, useMemo, useState } from "react";
import type { Briefing, LogEvent } from "./api";
import { AGENT_COLOR, Badge, Empty, OpenRef, Section, VerdictChip } from "./ui";

const GROUPS: Record<string, string[] | null> = {
  all: null,
  trial: ["CLAIM", "ATTACK", "DEFENSE", "CONCESSION", "RULING", "PRECHECK", "SUFFICIENCY", "SENDBACK", "BRIEFING"],
  retrieval: ["QUERY", "RETRIEVED", "CASE_FILE", "RESEARCH_PLAN", "NEW_EVIDENCE"],
  memory: ["MEMORY_READ", "MEMORY_WRITE", "MEMORY_APPLIED"],
  "security & clock": ["TRAP_INJECTION", "CLOCK_VIOLATION_BLOCKED"],
  "limits & errors": ["LIMIT_HIT", "ERROR"],
  stages: ["STAGE", "RUN_START", "RUN_END"],
};

const ROW_TONE: Record<string, string> = {
  TRAP_INJECTION: "bg-rose-50", CLOCK_VIOLATION_BLOCKED: "bg-rose-50", MEMORY_APPLIED: "bg-violet-100",
  MEMORY_READ: "bg-violet-50", MEMORY_WRITE: "bg-violet-50", NEW_EVIDENCE: "bg-yellow-50", SENDBACK: "bg-yellow-50",
  LIMIT_HIT: "bg-amber-50", ERROR: "bg-amber-50", RULING: "bg-indigo-50",
};

function RunComparison({ b, events, open }: { b?: Briefing | null; events: LogEvent[]; open: OpenRef }) {
  const runs = b?.runs ?? [];
  const found = events.filter((e) => e.type === "NEW_EVIDENCE" && e.payload?.phase === "found");
  const effect = events.find((e) => e.type === "NEW_EVIDENCE" && e.payload?.phase === "effect");
  const sendbacks = events.filter((e) => e.type === "SENDBACK");
  if (runs.length < 2 && !found.length && !sendbacks.length)
    return <Empty>Only one investigation run{runs.length ? "" : " so far"}: no send-back, so no run comparison.</Empty>;
  const claims = [...new Set(runs.flatMap((r) => Object.keys(r.verdicts)))].sort();
  return (
    <div className="space-y-2 text-sm">
      {sendbacks.map((e) => <div key={e.seq} className="rounded bg-yellow-50 p-2"><b>Send-back (run {e.run_number}):</b> {e.summary}</div>)}
      {found.map((e) => (
        <div key={e.seq} className="rounded bg-yellow-50 p-2">
          <b>New evidence in run {e.run_number}:</b> {e.payload.missing}
          <div className="mt-1 flex flex-wrap gap-1">
            {(e.payload.evidence ?? []).map((x: any) => (
              <button key={x.ref} onClick={() => open(x.kind === "trade_row" ? { doc_id: x.doc_id, row_id: x.ref } : { doc_id: x.doc_id, paragraph_ref: x.ref.split("#")[1] })}
                className="rounded bg-yellow-200 px-1 font-mono text-xs hover:bg-yellow-300">NEW {x.ref} ({x.source_type}, T{x.tier}, {x.pub_date})</button>
            ))}
          </div>
        </div>
      ))}
      {effect && <div className="rounded bg-slate-50 p-2 text-xs">effect: {effect.summary}</div>}
      {runs.length > 0 && (
        <table className="text-xs">
          <thead><tr><th className="pr-3 text-left">claim</th>{runs.map((r) => <th key={r.run_number} className="pr-3 text-left">run {r.run_number}</th>)}</tr></thead>
          <tbody>
            {claims.map((c) => (
              <tr key={c}><td className="pr-3 font-mono">{c}</td>
                {runs.map((r) => <td key={r.run_number} className="pr-3">{r.verdicts[c] ? <VerdictChip v={r.verdicts[c] as any} /> : "—"}</td>)}
              </tr>
            ))}
            <tr><td className="pr-3">sufficient</td>{runs.map((r) => <td key={r.run_number}>{r.sufficient == null ? "—" : r.sufficient ? "yes" : "no"}</td>)}</tr>
          </tbody>
        </table>
      )}
    </div>
  );
}

export function TraceView({ events, briefing, open }: { events: LogEvent[]; briefing?: Briefing | null; open: OpenRef }) {
  const [agent, setAgent] = useState("all");
  const [run, setRun] = useState("all");
  const [group, setGroup] = useState("all");
  const [openSeq, setOpenSeq] = useState<number | null>(null);
  const runs = useMemo(() => [...new Set(events.map((e) => e.run_number))].sort(), [events]);
  const shown = events.filter((e) => (agent === "all" || e.agent === agent) && (run === "all" || String(e.run_number) === run)
    && (!GROUPS[group] || GROUPS[group]!.includes(e.type)));
  const count = (types: string[]) => events.filter((e) => types.includes(e.type)).length;
  if (!events.length) return <Empty>No events recorded yet.</Empty>;
  return (
    <div>
      <Section title="Run 1 vs run 2"><RunComparison b={briefing} events={events} open={open} /></Section>
      <div className="mb-2 flex flex-wrap items-center gap-2 text-xs">
        <select value={agent} onChange={(e) => setAgent(e.target.value)} className="rounded border p-1">
          {["all", "heimdall", "thor", "loki", "odin", "system"].map((a) => <option key={a}>{a}</option>)}
        </select>
        <select value={run} onChange={(e) => setRun(e.target.value)} className="rounded border p-1">
          <option value="all">all runs</option>{runs.map((r) => <option key={r} value={String(r)}>run {r}</option>)}
        </select>
        <select value={group} onChange={(e) => setGroup(e.target.value)} className="rounded border p-1">
          {Object.keys(GROUPS).map((g) => <option key={g}>{g}</option>)}
        </select>
        <span className="text-slate-500">{shown.length} of {events.length} events</span>
        <Badge tone="violet">memory {count(GROUPS.memory!)}</Badge>
        <Badge tone="violet">memory changed an action {count(["MEMORY_APPLIED"])}</Badge>
        <Badge tone="red">injection {count(["TRAP_INJECTION"])}</Badge>
        <Badge tone="red">clock blocks {count(["CLOCK_VIOLATION_BLOCKED"])}</Badge>
        <Badge tone="amber">limits {count(["LIMIT_HIT"])}</Badge>
      </div>
      <table className="w-full text-xs">
        <thead><tr className="text-left text-slate-500"><th>#</th><th>time</th><th>run</th><th>agent</th><th>type</th><th>summary</th></tr></thead>
        <tbody>
          {shown.map((e) => (
            <Fragment key={e.seq}>
              <tr onClick={() => setOpenSeq(openSeq === e.seq ? null : e.seq)}
                className={`cursor-pointer border-t align-top hover:bg-slate-100 ${ROW_TONE[e.type] ?? ""}`}>
                <td className="pr-2 font-mono text-slate-400">{e.seq}</td>
                <td className="whitespace-nowrap pr-2 text-slate-500">{e.ts.slice(11, 19)}</td>
                <td className="pr-2">{e.run_number}</td>
                <td className={`pr-2 font-semibold ${AGENT_COLOR[e.agent] ?? ""}`}>{e.agent}</td>
                <td className="pr-2 font-mono">{e.type}</td>
                <td>{e.summary}</td>
              </tr>
              {openSeq === e.seq && (
                <tr><td colSpan={6}>
                  <pre className="max-h-80 overflow-auto whitespace-pre-wrap rounded bg-slate-900 p-2 text-[11px] text-slate-100">
                    {JSON.stringify({ refs: e.refs, payload: e.payload }, null, 2)}
                  </pre>
                </td></tr>
              )}
            </Fragment>
          ))}
        </tbody>
      </table>
    </div>
  );
}
