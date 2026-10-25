import { useState, type ReactNode } from "react";
import type { Briefing, Estimate, ExposureRow, Finding } from "../api";
import { Empty, Section } from "../components/layout";
import { AgentMark, ClaimType, Cite, OpenRef, Verdict } from "../components/marks";
import { fmtDate, fmtNum } from "../lib/format";

type Times = Map<string, string>; // doc ID -> "YYYY-MM-DD HH:MM" from the briefing's source list

function stamp(times: Times, c: { doc_id: string; pub_date?: string }): string {
  return times.get(c.doc_id) ?? c.pub_date ?? "";
}

function Findings({ items, open, times }: { items: Finding[]; open: OpenRef; times: Times }) {
  if (!items.length) return <p className="m-0 border-b border-rule py-2 text-ink-3">None.</p>;
  return (
    <ul className="m-0 list-none p-0">
      {items.map((f) => (
        <li key={f.claim_id} className="break-inside-avoid border-b border-rule py-2.5">
          <div className="mb-0.5 flex justify-between gap-3 text-xs text-ink-3">
            <span><span className="mono">{f.claim_id}</span> · <ClaimType t={f.claim_type} /></span>
            <Verdict v={f.verdict} />
          </div>
          <p className="m-0">{f.text}</p>
          <div className="mt-1 flex flex-wrap gap-x-2.5">
            {f.citations.map((c, i) => (
              <Cite key={i} c={c} open={open} label={`[${c.row_id ? c.row_id.replace("#", " ") : `${c.doc_id} ${c.paragraph_ref}`}, ${stamp(times, c)}]`} />
            ))}
          </div>
        </li>
      ))}
    </ul>
  );
}

function List({ xs }: { xs?: string[] }) {
  return xs && xs.length
    ? <ul className="m-0 mt-2 list-disc pl-5 text-ink-2">{xs.map((x, i) => <li key={i}>{x}</li>)}</ul>
    : <p className="m-0 mt-2 text-ink-3">None recorded.</p>;
}

function Sub({ title, children }: { title: string; children: ReactNode }) {
  return <div className="mt-6 break-inside-avoid"><h3 className="label m-0 border-b border-rule pb-1.5">{title}</h3>{children}</div>;
}

function Range({ e, why }: { e: Estimate | null; why?: string }) {
  if (!e) return <span className="text-xs text-ink-3">no estimate{why ? `: ${why}` : ""}</span>;
  return <span className="num whitespace-nowrap text-[13px]">{fmtNum(e.low)} – {fmtNum(e.high)}</span>;
}

/** The exposure table of the briefing: low and high per country and sector, Thor / Loki / Odin side by side. */
function ExposureTable({ rows, open }: { rows: ExposureRow[]; open: OpenRef }) {
  if (!rows.length) return <p className="m-0 mt-2 text-ink-3">No exposure rows.</p>;
  const units = [...new Set(rows.flatMap((r) => [r.thor, r.loki, r.odin]).filter(Boolean).map((e) => e!.unit))];
  const th = "label border-b border-ink py-2 pr-3 text-left align-bottom";
  const td = "border-b border-rule py-2 pr-3 align-top";
  return (
    <div className="mt-2 overflow-x-auto">
      <table className="w-full min-w-[640px] border-collapse">
        <thead>
          <tr>
            <th className={th}>Country / sector</th>
            {(["thor", "loki", "odin"] as const).map((w) => <th key={w} className={th}><AgentMark agent={w} /> <span className="ml-1">low – high</span></th>)}
            <th className={th}>Metric · unit · period</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const e = r.odin ?? r.thor ?? r.loki;
            return (
              <tr key={`${r.country}-${r.sector}`} className="break-inside-avoid">
                <td className={td}><div className="font-medium">{r.country}</div><div className="text-ink-2">{r.sector}</div></td>
                {(["thor", "loki", "odin"] as const).map((w) => <td key={w} className={td}><Range e={r[w]} why={r.unavailable?.[w]} /></td>)}
                <td className={`${td} text-[13px] text-ink-2`}>
                  {e ? <>{e.metric} · {e.unit} · {e.period}{e.denominator && !/^(none|n\/?a|null)$/i.test(e.denominator.trim()) ? ` · per ${e.denominator}` : ""}</> : <span className="text-ink-3">{r.note || "no estimate"}</span>}
                  {e && e.trade_row_refs.length > 0 && (
                    <div className="mt-0.5 flex flex-wrap gap-x-2">{e.trade_row_refs.slice(0, 4).map((id) => (
                      <Cite key={id} c={{ doc_id: id.split("#")[0], row_id: id }} open={open} />))}{e.trade_row_refs.length > 4 && <span className="text-xs text-ink-3">+{e.trade_row_refs.length - 4} rows</span>}</div>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {units.length > 1 && <p className="m-0 mt-1 text-xs text-bad">Rows use different units ({units.join(", ")}); compare within a row only.</p>}
      <p className="m-0 mt-1 text-xs text-ink-3">Odin's range is built from evidence and calculation records, never an average of the two sides.
        Trade exposure is not a loss estimate; missing estimates are missing data, not zero.</p>
    </div>
  );
}

function download(name: string, text: string, type: string) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], { type }));
  a.download = name;
  a.click();
  URL.revokeObjectURL(a.href);
}

export function BriefingView({ b, md, open, running, question, notes }: {
  b?: Briefing | null; md?: string | null; open: OpenRef; running: boolean; question?: string; notes?: string[];
}) {
  const [raw, setRaw] = useState(false);
  if (!b) {
    return <Empty>{running ? "The briefing is written when the trial finishes." : "No briefing was produced for this case. It is written only from Odin's final rulings; a failed or paused case has none yet."}</Empty>;
  }
  const times: Times = new Map(b.sources.map((s) => [s.doc_id, `${s.pub_date}${s.pub_time ? ` ${String(s.pub_time).slice(0, 5)}` : ""}`]));
  const btn = "text-[13px] text-ink-2 underline underline-offset-4 hover:text-ink";
  return (
    <article aria-label="Briefing">
      <div className="no-print flex flex-wrap gap-4">
        <button type="button" className={btn} onClick={() => { setRaw(false); setTimeout(() => window.print(), 50); }}>Save as PDF</button>
        {md && <button type="button" className={btn} onClick={() => download(`${b.case_id}.md`, md, "text/markdown")}>Export .md</button>}
        <button type="button" className={btn} onClick={() => download(`${b.case_id}.json`, JSON.stringify(b, null, 2), "application/json")}>Export .json</button>
        <button type="button" className={btn} aria-pressed={raw} onClick={() => setRaw(!raw)}>{raw ? "Show rendered" : "Show Markdown"}</button>
      </div>
      {/* print header: what the PDF is about */}
      <header className="print-only mb-4 border-b border-ink pb-2">
        <div className="text-[18px] font-semibold">Ragnarok briefing</div>
        {question && <div className="mt-1">{question}</div>}
        <div className="mono mt-1 text-ink-2">{b.case_id} · as of {fmtDate(b.as_of)} · status {b.status} · {b.runs_completed} run{b.runs_completed === 1 ? "" : "s"}</div>
      </header>
      <p className="m-0 mt-3 text-ink-2">
        Status <b className={`font-medium ${b.status === "complete" ? "text-ink" : "text-bad"}`}>{b.status}</b> · as of {fmtDate(b.as_of)} · {b.runs_completed} investigation run{b.runs_completed === 1 ? "" : "s"}
        {b.status !== "complete" && <> · this briefing is not complete; see missing data and failures below.</>}
      </p>
      {raw ? <pre className="mt-3 max-h-[70vh] overflow-auto whitespace-pre-wrap break-words border border-rule bg-paper p-3 font-mono text-xs">{md ?? "No Markdown export was saved for this case."}</pre> : (
        <>
          <Sub title="Executive summary"><p className="m-0 mt-2 max-w-[75ch]">{b.executive_summary}</p></Sub>
          <Sub title="Event verification">
            <p className="m-0 mt-2">Heimdall: the event is <b className="font-medium">{b.event_status}</b>.{" "}
              <span className="inline-flex flex-wrap gap-x-2.5">{b.event_citations.map((c, i) => <Cite key={i} c={c} open={open} label={`[${c.doc_id} ${c.paragraph_ref ?? ""}, ${stamp(times, c)}]`} />)}</span></p>
          </Sub>
          <Sub title="Exposure table"><ExposureTable rows={b.exposure_table} open={open} /></Sub>
          <Sub title="Established findings"><Findings items={b.established} open={open} times={times} /></Sub>
          <Sub title="Contested findings"><Findings items={b.contested} open={open} times={times} /></Sub>
          <Sub title="Conceded findings"><Findings items={b.conceded} open={open} times={times} /></Sub>
          <Sub title="Rejected claims"><Findings items={b.rejected} open={open} times={times} /></Sub>
          <Sub title="Next-quarter outlook">
            <p className="m-0 mt-2 max-w-[75ch]">{b.outlook.text}</p>
            <p className="label m-0 mt-3">Assumptions</p><List xs={b.outlook.assumptions} />
          </Sub>
          <Sub title="Assumptions and uncertainty"><List xs={[...(b.assumptions ?? []), ...(b.uncertainty ?? [])]} /></Sub>
          <Sub title="Missing data and evidence quality"><List xs={[...b.missing_data_notes, ...b.evidence_quality_notes]} /></Sub>
          <Sub title="Traps, corrections and failed operations"><List xs={[...b.traps_and_failures, ...(notes ?? []).filter((n) => !b.traps_and_failures.includes(n))]} /></Sub>
          {b.dropped_citations && b.dropped_citations.length > 0 && <Sub title="Dropped at build time (failed citation check)"><List xs={b.dropped_citations} /></Sub>}
          {b.superseded && b.superseded.length > 0 && <Sub title="Superseded claims"><List xs={b.superseded} /></Sub>}
          <Sub title="Sources">
            <ul className="m-0 list-none p-0">
              {b.sources.map((s) => (
                <li key={s.doc_id} className="grid grid-cols-[76px_minmax(0,1fr)] gap-x-3 border-b border-rule py-2">
                  <Cite c={{ doc_id: s.doc_id }} open={open} />
                  <span>{s.title} <span className="text-xs text-ink-3">· {s.source_name} · tier {s.reliability_tier ?? "?"} ·{" "}
                    <span className="num">{s.pub_date}{s.pub_time ? ` ${String(s.pub_time).slice(0, 5)}` : ""}</span> · Runemark</span></span>
                </li>
              ))}
            </ul>
            <p className="m-0 mt-1 text-xs text-ink-3">Every source is a Runemark document; no off-Runemark source was used.</p>
          </Sub>
        </>
      )}
    </article>
  );
}

export function BriefingLink({ onOpen }: { onOpen: () => void }) {
  return (
    <Section title="Briefing">
      <p className="m-0 mt-2 text-ink-2">The final briefing has its own view.{" "}
        <button type="button" className="text-accent underline underline-offset-4" onClick={onOpen}>Open the briefing</button></p>
    </Section>
  );
}
