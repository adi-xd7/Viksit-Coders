import { useState } from "react";
import type { Briefing, Finding } from "../api";
import { Empty, Section } from "../components/layout";
import { ClaimType, Cite, OpenRef, Verdict } from "../components/marks";

function Findings({ items, open }: { items: Finding[]; open: OpenRef }) {
  if (!items.length) return <p className="m-0 border-b border-rule py-2 text-ink-3">None.</p>;
  return (
    <ul className="m-0 list-none p-0">
      {items.map((f) => (
        <li key={f.claim_id} className="border-b border-rule py-2.5">
          <div className="mb-0.5 flex justify-between gap-3 text-xs text-ink-3">
            <span><span className="mono">{f.claim_id}</span> · <ClaimType t={f.claim_type} /></span>
            <Verdict v={f.verdict} />
          </div>
          <p className="m-0">{f.text}</p>
          <div className="mt-1 flex flex-wrap gap-x-2.5">{f.citations.map((c, i) => <Cite key={i} c={c} open={open} label={`${c.row_id ? c.row_id : `${c.doc_id} ${c.paragraph_ref}`}, ${c.pub_date}`} />)}</div>
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

function Sub({ title, children }: { title: string; children: React.ReactNode }) {
  return <div className="mt-5"><h3 className="label m-0 border-b border-rule pb-1.5">{title}</h3>{children}</div>;
}

function download(name: string, text: string, type: string) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], { type }));
  a.download = name;
  a.click();
  URL.revokeObjectURL(a.href);
}

export function BriefingSection({ b, md, open, running }: { b?: Briefing | null; md?: string | null; open: OpenRef; running: boolean }) {
  const [raw, setRaw] = useState(false);
  const btn = "text-[13px] text-ink-2 underline underline-offset-4 hover:text-ink";
  return (
    <Section id="briefing" title="Briefing" right={b ? `${b.status} · ${b.runs_completed} run${b.runs_completed === 1 ? "" : "s"} · as of ${b.as_of}` : undefined}>
      {!b ? <Empty>{running ? "The briefing is written when the trial finishes." : "No briefing was produced for this case. It is written only from Odin's final rulings; a failed case has none."}</Empty> : (
        <>
          <div className="mt-2 flex flex-wrap gap-4">
            <button type="button" className={btn} aria-pressed={raw} onClick={() => setRaw(!raw)}>{raw ? "Show rendered" : "Show Markdown"}</button>
            {md && <button type="button" className={btn} onClick={() => download(`${b.case_id}.md`, md, "text/markdown")}>Export .md</button>}
            <button type="button" className={btn} onClick={() => download(`${b.case_id}.json`, JSON.stringify(b, null, 2), "application/json")}>Export .json</button>
          </div>
          {b.status !== "complete" && (
            <p className="m-0 mt-3 border-l-2 border-rule-2 pl-3 text-ink-2">This briefing is <b className="font-medium text-ink">{b.status}</b>. See missing data and failures below.</p>
          )}
          {raw ? <pre className="mt-3 max-h-[70vh] overflow-auto whitespace-pre-wrap break-words border border-rule bg-paper p-3 font-mono text-xs">{md ?? "No Markdown export was saved for this case."}</pre> : (
            <>
              <Sub title="Executive summary"><p className="m-0 mt-2 max-w-[75ch]">{b.executive_summary}</p></Sub>
              <Sub title="Event verification">
                <p className="m-0 mt-2">{b.event_status} <span className="inline-flex flex-wrap gap-x-2.5">{b.event_citations.map((c, i) => <Cite key={i} c={c} open={open} />)}</span></p>
              </Sub>
              <Sub title="Established findings"><Findings items={b.established} open={open} /></Sub>
              <Sub title="Contested findings"><Findings items={b.contested} open={open} /></Sub>
              <Sub title="Conceded findings"><Findings items={b.conceded} open={open} /></Sub>
              <Sub title="Rejected claims"><Findings items={b.rejected} open={open} /></Sub>
              <Sub title="Exposure"><p className="m-0 mt-2 text-ink-2">Thor's, Loki's and Odin's ranges are in the Exposure view (Odin's range is not an average).</p></Sub>
              <Sub title="Assumptions and uncertainty"><List xs={[...(b.assumptions ?? []), ...(b.uncertainty ?? [])]} /></Sub>
              <Sub title="Next-quarter outlook">
                <p className="m-0 mt-2 max-w-[75ch]">{b.outlook.text}</p>
                <p className="label m-0 mt-2">Assumptions</p><List xs={b.outlook.assumptions} />
              </Sub>
              <Sub title="Missing data and evidence quality"><List xs={[...b.missing_data_notes, ...b.evidence_quality_notes]} /></Sub>
              <Sub title="Traps, corrections and failed operations"><List xs={b.traps_and_failures} /></Sub>
              {b.dropped_citations && b.dropped_citations.length > 0 && <Sub title="Dropped at build time"><List xs={b.dropped_citations} /></Sub>}
              {b.superseded && b.superseded.length > 0 && <Sub title="Superseded claims"><List xs={b.superseded} /></Sub>}
              <Sub title="Sources">
                <ul className="m-0 list-none p-0">
                  {b.sources.map((s) => (
                    <li key={s.doc_id} className="grid grid-cols-[76px_minmax(0,1fr)] gap-x-3 border-b border-rule py-2">
                      <Cite c={{ doc_id: s.doc_id }} open={open} />
                      <span>{s.title} <span className="text-xs text-ink-3">· {s.source_name} · tier {s.reliability_tier ?? "?"} · <span className="num">{s.pub_date}</span></span></span>
                    </li>
                  ))}
                </ul>
              </Sub>
            </>
          )}
        </>
      )}
    </Section>
  );
}
