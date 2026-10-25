import { Fragment, useState } from "react";
import type { Briefing, LogEvent } from "../api";
import { Empty, Filters, Section } from "../components/layout";
import { agentName, Cite, OpenRef } from "../components/marks";
import type { TrialState } from "../useCase";
import { BriefingLink } from "./BriefingView";

// Model-request bookkeeping is not shown on the dashboard (no call or token meters).
const HIDDEN = new Set(["LLM_USAGE", "LLM_CACHE_HIT"]);
const GROUPS: [string, string, (t: string) => boolean][] = [
  ["all", "All", () => true],
  ["QUERY", "QUERY", (t) => t === "QUERY"],
  ["RETRIEVED", "RETRIEVED", (t) => t === "RETRIEVED"],
  ["MEMORY", "MEMORY_*", (t) => t.startsWith("MEMORY_")],
  ["TRAP_INJECTION", "TRAP_INJECTION", (t) => t === "TRAP_INJECTION"],
  ["CLOCK_VIOLATION_BLOCKED", "CLOCK_VIOLATION_BLOCKED", (t) => t === "CLOCK_VIOLATION_BLOCKED"],
  ["LIMIT_HIT", "LIMIT_HIT", (t) => t === "LIMIT_HIT"],
  ["MODEL_SWITCH", "MODEL_SWITCH", (t) => t === "MODEL_SWITCH"],
  ["ERROR", "ERROR", (t) => t === "ERROR"],
  ["trial", "Trial", (t) => ["CLAIM", "ATTACK", "DEFENSE", "CONCESSION", "RULING", "PRECHECK", "SUFFICIENCY", "SENDBACK", "NEW_EVIDENCE", "BRIEFING"].includes(t)],
  ["stages", "Stages", (t) => ["STAGE", "RUN_START", "RUN_END", "CASE_FILE", "RESEARCH_PLAN"].includes(t)],
];
const PAGE = 60;

function SendBack({ t }: { t: TrialState }) {
  if (!t.sendbacks.length) return <Empty>{t.ended ? "No send-back: Odin did not send this case back for more evidence." : "No send-back recorded yet."}</Empty>;
  return (
    <>
      {t.sendbacks.map((e) => {
        const sb = e.payload.sendback ?? {};
        return (
          <div key={e.seq} className="border-b border-rule py-3">
            <div className="mono text-ink-3">{sb.sendback_id ?? "send-back"} · end of run {sb.run_number ?? e.run_number}</div>
            <p className="m-0 mt-1 max-w-[70ch]">{sb.reason ?? e.summary}</p>
            {(sb.missing ?? []).length > 0 && (
              <ol className="m-0 mt-2 list-decimal pl-5 text-ink-2">
                {sb.missing.map((m: any, i: number) => <li key={i}>{m.description}<span className="text-ink-3"> · {m.why_needed}</span></li>)}
              </ol>
            )}
          </div>
        );
      })}
      {t.researchPlans.filter((e) => e.agent === "heimdall" && e.payload.sendback_id).map((e) => (
        <div key={e.seq} className="border-b border-rule py-3">
          <div className="label">Heimdall's new targeted queries · run {e.run_number}</div>
          <ul className="m-0 mt-1 list-none p-0">
            {(e.payload.searches ?? []).map((s: any, i: number) => (
              <li key={i} className="mono break-words">search "{s.query}"{filtersText(s)}</li>
            ))}
            {(e.payload.refused ?? []).map((s: any, i: number) => (
              <li key={`r${i}`} className="mono break-words text-ink-3">refused "{s.query}" ({s.reason})</li>
            ))}
          </ul>
        </div>
      ))}
    </>
  );
}

function filtersText(s: any): string {
  const parts = Object.entries({ country: s.countries, sector: s.sectors, event_id: s.event_ids, source_type: s.source_types })
    .filter(([, v]) => Array.isArray(v) && v.length).map(([k, v]) => `${k}=${(v as string[]).join(",")}`);
  if (s.max_reliability) parts.push(`max_tier=${s.max_reliability}`);
  return parts.length ? ` · ${parts.join(" · ")}` : "";
}

function Memory({ t }: { t: TrialState }) {
  if (!t.memoryApplied.length) {
    return <Empty>No recorded memory changed an agent's action in this case
      {t.memoryReads ? ` (${t.memoryReads} memory read${t.memoryReads === 1 ? "" : "s"} logged, none changed a plan)` : " (no memory reads logged)"}.</Empty>;
  }
  return (
    <>
      {t.memoryApplied.map((e) => {
        const p = e.payload;
        const used = (p.memory_used ?? []) as { memory_id: string; lesson: string }[];
        return (
          <div key={e.seq} className="grid grid-cols-1 gap-4 border-b border-rule py-3 md:grid-cols-2 md:gap-7">
            <div className="border-l-2 border-rule-2 pl-3">
              <div className="label">{agentName(e.agent)}, before memory · run {e.run_number}</div>
              {p.original_action ? (
                <ul className="m-0 mt-1.5 list-none p-0">{p.original_action.map((a: string, i: number) => (
                  <li key={i} className={`mono break-words ${(p.removed ?? []).includes(a) ? "text-ink-3 line-through" : ""}`}>{a}</li>))}</ul>
              ) : <p className="m-0 mt-1.5 text-ink-2">No no-memory plan was recorded; the change is as stated by the agent.</p>}
            </div>
            <div className="border-l-2 border-accent pl-3">
              <div className="label text-accent">{agentName(e.agent)}, after reading {used.map((u) => u.memory_id).join(", ") || "its memory"}</div>
              <ul className="m-0 mt-1.5 list-none p-0">{(p.changed_action ?? []).map((a: string, i: number) => (
                <li key={i} className={`mono break-words ${(p.added ?? []).includes(a) ? "text-accent" : ""}`}>{a}</li>))}</ul>
              {used.map((u) => <p key={u.memory_id} className="m-0 mt-1 text-xs text-ink-3">{u.memory_id}: {u.lesson}</p>)}
              {p.agent_stated_effect && <p className="m-0 mt-1 text-xs text-ink-3">Agent's account: {p.agent_stated_effect}</p>}
            </div>
          </div>
        );
      })}
    </>
  );
}

function RunTable({ t, briefing, open, status }: { t: TrialState; briefing?: Briefing | null; open: OpenRef; status?: string | null }) {
  const runs = t.runs.filter((r) => r > 0);
  if (!runs.length) return <Empty>No run recorded yet.</Empty>;
  const seen = new Set<string>();
  const evid = runs.map((r) => {
    const refs = t.refsByRun.get(r) ?? new Set<string>();
    const fresh = [...refs].filter((x) => !seen.has(x)).length;
    refs.forEach((x) => seen.add(x));
    return r === runs[0] ? `${refs.size} passages and rows` : `${refs.size}, of which ${fresh} not retrieved before`;
  });
  const suff = (r: number) => {
    const e = t.sufficiency.filter((x) => x.run_number === r).pop();
    return e ? (/INSUFFICIENT/.test(e.summary) ? "Insufficient" : "Sufficient") : "Not assessed";
  };
  const ranges = t.effect?.payload?.range_changes as Record<string, string> | undefined;
  const last = runs[runs.length - 1];
  const td = "border-b border-rule py-2.5 pr-3 align-top";
  return (
    <div className="overflow-x-auto">
      <table className="mt-2 w-full border-collapse">
        <thead><tr><th className="label border-b border-ink py-2 pr-3 text-left" />{runs.map((r) => <th key={r} className="label border-b border-ink py-2 pr-3 text-left">Run {r}</th>)}</tr></thead>
        <tbody>
          <tr><td className={`${td} w-[30%] text-ink-2`}>Evidence retrieved</td>{evid.map((x, i) => <td key={i} className={td}>{x}</td>)}</tr>
          <tr><td className={`${td} text-ink-2`}>New evidence from Heimdall</td>{runs.map((r) => {
            const ev = t.newEvidence.filter((e) => e.run_number === r).flatMap((e) => e.payload.evidence ?? []);
            return <td key={r} className={td}>{ev.length ? <span className="flex flex-wrap gap-x-2.5">{ev.map((x: any) => (
              <Cite key={x.ref} c={x.kind === "trade_row" ? { doc_id: x.doc_id, row_id: x.ref } : { doc_id: x.doc_id, paragraph_ref: x.ref.split("#")[1] }} open={open} />
            ))}</span> : <span className="text-ink-3">None</span>}</td>;
          })}</tr>
          <tr><td className={`${td} text-ink-2`}>Claims</td>{runs.map((r) => {
            const n = t.claims.filter((c) => c.run_number === r).length;
            const w = t.concessions.filter((k) => !k.attack_id && k.run_number === r).length;
            const rev = t.claims.filter((c) => c.run_number === r && c.revises_claim_id).length;
            return <td key={r} className={td}><span className="num">{n}</span> new{rev ? `, ${rev} revising earlier claims` : ""}{w ? `, ${w} withdrawn` : ""}</td>;
          })}</tr>
          <tr><td className={`${td} text-ink-2`}>Odin's sufficiency</td>{runs.map((r) => <td key={r} className={td}>{suff(r)}</td>)}</tr>
          {ranges && Object.entries(ranges).map(([pair, change]) => {
            const [before, after] = change.split(" -> ");
            return (
              <tr key={pair}><td className={`${td} text-ink-2`}>{pair}, Odin</td>
                {runs.map((r) => <td key={r} className={`${td} num text-xs`}>{r === last ? after : r === last - 1 ? before : ""}</td>)}</tr>
            );
          })}
          <tr><td className={`${td} text-ink-2`}>Briefing status</td>{runs.map((r) => (
            <td key={r} className={td}>{r === last ? (briefing?.status ? briefing.status[0].toUpperCase() + briefing.status.slice(1) : status === "running" ? "Not issued yet" : "None produced")
              : <span className="text-ink-3">Not issued (sent back)</span>}</td>
          ))}</tr>
        </tbody>
      </table>
      {t.effect && <p className="m-0 mt-2 text-xs text-ink-3">{t.effect.summary}</p>}
      {runs.length === 1 && <p className="m-0 mt-2 text-xs text-ink-3">One run only: there is no second run to compare.</p>}
    </div>
  );
}

function Events({ events }: { events: LogEvent[] }) {
  const [group, setGroup] = useState("all");
  const [openSeq, setOpenSeq] = useState<number | null>(null);
  const [limit, setLimit] = useState(PAGE);
  const visible = events.filter((e) => !HIDDEN.has(e.type));
  const test = GROUPS.find(([k]) => k === group)![2];
  const shown = visible.filter((e) => test(e.type));
  return (
    <>
      <div className="mt-2">
        <Filters label="Event types" value={group} onChange={(g) => { setGroup(g); setLimit(PAGE); }}
          options={GROUPS.map(([k, label]) => [k, `${label} ${visible.filter((e) => GROUPS.find(([g]) => g === k)![2](e.type)).length}`] as [string, string])} />
      </div>
      {!shown.length ? <Empty>No events of this type were recorded.</Empty> : (
        <ul className="m-0 list-none p-0">
          {shown.slice(0, limit).map((e) => {
            const tone = e.type.startsWith("MEMORY") ? "text-accent" : ["TRAP_INJECTION", "CLOCK_VIOLATION_BLOCKED", "ERROR", "LIMIT_HIT"].includes(e.type) ? "text-bad" : "";
            // MODEL_SWITCH stays neutral: switching model is expected behaviour, not an error
            return (
              <Fragment key={e.seq}>
                <li>
                  <button type="button" aria-expanded={openSeq === e.seq} onClick={() => setOpenSeq(openSeq === e.seq ? null : e.seq)}
                    className="grid w-full grid-cols-[minmax(0,1fr)] items-baseline gap-x-3.5 border-b border-rule py-2 text-left hover:bg-paper sm:grid-cols-[150px_90px_minmax(0,1fr)]">
                    <span className={`font-mono text-[11.5px] ${tone}`}><span className="text-ink-3">{e.seq} · r{e.run_number} · </span>{e.type}</span>
                    <span className="hidden text-ink-2 sm:inline">{agentName(e.agent)}</span>
                    <span className="min-w-0 break-words">{e.summary}</span>
                  </button>
                </li>
                {openSeq === e.seq && (
                  <li><pre className="m-0 max-h-80 overflow-auto whitespace-pre-wrap break-words border-b border-rule bg-paper p-2 font-mono text-[11px]">
                    {JSON.stringify({ ts: e.ts, refs: e.refs, payload: e.payload }, null, 2)}</pre></li>
                )}
              </Fragment>
            );
          })}
        </ul>
      )}
      {shown.length > limit && (
        <button type="button" className="mt-2 text-[13px] text-ink-2 underline underline-offset-4 hover:text-ink" onClick={() => setLimit(limit + PAGE)}>
          Show {Math.min(PAGE, shown.length - limit)} more of {shown.length - limit}
        </button>
      )}
    </>
  );
}

export function TraceView({ t, events, briefing, open, status, onBriefing }: {
  t: TrialState; events: LogEvent[]; briefing?: Briefing | null; open: OpenRef; status?: string | null; onBriefing: () => void;
}) {
  return (
    <>
      <Section title="Odin's send-back" className="mt-0"><SendBack t={t} /></Section>
      <Section title="Memory: before and after"><Memory t={t} /></Section>
      <Section title={t.runs.filter((r) => r > 0).length > 1 ? "Run 1 against run 2" : "Runs"}><RunTable t={t} briefing={briefing} open={open} status={status} /></Section>
      <Section title="Events" right="Recorded, not simulated"><Events events={events} /></Section>
      <BriefingLink onOpen={onBriefing} />
    </>
  );
}
