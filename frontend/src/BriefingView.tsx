import { useState } from "react";
import type { Briefing, Finding } from "./api";
import { ExposureView } from "./ExposureView";
import { Badge, Cite, Empty, OpenRef, Section, TypeTag, VerdictChip } from "./ui";

function Findings({ items, open }: { items: Finding[]; open: OpenRef }) {
  if (!items.length) return <div className="text-sm italic text-slate-400">None.</div>;
  return (
    <ul className="space-y-1">
      {items.map((f) => (
        <li key={f.claim_id} className="rounded bg-white p-2 text-sm ring-1 ring-slate-200">
          <span className="font-mono text-xs font-semibold">{f.claim_id}</span> <VerdictChip v={f.verdict} /> <TypeTag t={f.claim_type} />{" "}
          {f.text} {f.citations.map((c, i) => <Cite key={i} c={c} open={open} />)}
        </li>
      ))}
    </ul>
  );
}

const List = ({ xs }: { xs?: string[] }) =>
  xs && xs.length ? <ul className="list-disc pl-5 text-sm">{xs.map((x, i) => <li key={i}>{x}</li>)}</ul>
    : <div className="text-sm italic text-slate-400">None recorded.</div>;

export function BriefingView({ b, md, open }: { b: Briefing | null | undefined; md?: string | null; open: OpenRef }) {
  const [raw, setRaw] = useState(false);
  if (!b) return <Empty>No briefing yet. It is written after Odin's final rulings (failed cases have none).</Empty>;
  const download = (name: string, text: string, type: string) => {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([text], { type }));
    a.download = name;
    a.click();
  };
  const tone = b.status === "complete" ? "green" : "amber";
  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Badge tone={tone}>{b.status.toUpperCase()}</Badge>
        <span className="text-sm text-slate-600">runs completed: {b.runs_completed} · as of {b.as_of}</span>
        <span className="ml-auto flex gap-2 text-xs">
          <button className="rounded border px-2 py-1" onClick={() => setRaw(!raw)}>{raw ? "Rendered" : "Markdown"}</button>
          {md && <button className="rounded border px-2 py-1" onClick={() => download(`${b.case_id}.md`, md, "text/markdown")}>Export .md</button>}
          <button className="rounded border px-2 py-1" onClick={() => download(`${b.case_id}.json`, JSON.stringify(b, null, 2), "application/json")}>Export .json</button>
        </span>
      </div>
      {b.status !== "complete" && (
        <div className="mb-3 rounded border border-amber-300 bg-amber-50 p-2 text-sm text-amber-900">
          This briefing is <b>{b.status}</b>: see missing data and failures below.
        </div>
      )}
      {raw ? <pre className="whitespace-pre-wrap rounded bg-white p-3 text-xs ring-1 ring-slate-200">{md}</pre> : (
        <>
          <Section title="Executive summary"><p className="text-sm">{b.executive_summary}</p></Section>
          <Section title="Event verification">
            <div className="text-sm"><Badge tone="dark">{b.event_status}</Badge>{" "}
              {b.event_citations.map((c, i) => <Cite key={i} c={c} open={open} />)}</div>
          </Section>
          <Section title="Established findings"><Findings items={b.established} open={open} /></Section>
          <Section title="Contested findings"><Findings items={b.contested} open={open} /></Section>
          <Section title="Conceded findings"><Findings items={b.conceded} open={open} /></Section>
          <Section title="Rejected claims"><Findings items={b.rejected} open={open} /></Section>
          <Section title="Exposure (Thor / Loki / Odin — Odin's range is not an average)"><ExposureView table={b.exposure_table} claims={[]} /></Section>
          <Section title="Assumptions and uncertainty"><List xs={[...(b.assumptions ?? []), ...(b.uncertainty ?? [])]} /></Section>
          <Section title="Next-quarter outlook">
            <p className="text-sm">{b.outlook.text}</p>
            <div className="mt-1 text-xs font-semibold text-slate-600">Assumptions</div><List xs={b.outlook.assumptions} />
          </Section>
          <Section title="Missing data and evidence quality"><List xs={[...b.missing_data_notes, ...b.evidence_quality_notes]} /></Section>
          <Section title="Traps, corrections and failed operations"><List xs={b.traps_and_failures} /></Section>
          {b.dropped_citations && b.dropped_citations.length > 0 && (
            <Section title="Dropped at build time (failed citation / provenance check)"><List xs={b.dropped_citations} /></Section>
          )}
          {b.superseded && b.superseded.length > 0 && <Section title="Superseded claims"><List xs={b.superseded} /></Section>}
          <Section title="Sources">
            <ul className="text-sm">
              {b.sources.map((s) => (
                <li key={s.doc_id}>
                  <button className="font-mono text-xs text-indigo-700 hover:underline" onClick={() => open({ doc_id: s.doc_id })}>{s.doc_id}</button>{" "}
                  {s.title} — {s.source_name} (tier {s.reliability_tier}), {s.pub_date}{s.pub_time ? ` ${s.pub_time.slice(0, 5)}` : ""}
                </li>
              ))}
            </ul>
          </Section>
        </>
      )}
    </div>
  );
}
