import { useMemo, useState } from "react";
import type { Claim, Estimate, ExposureRow } from "../api";
import { Empty } from "../components/layout";
import { AgentMark, agentName, Cite, OpenRef } from "../components/marks";
import { fmtNum } from "../lib/format";
import { linearScale, type Scale } from "../lib/scale";
import type { CalcRecord, TrialState } from "../useCase";

const WHO = ["thor", "loki", "odin"] as const;
type Who = (typeof WHO)[number];

/** From the briefing's exposure table when it exists; while the trial runs, from the advocates' submitted estimates. */
export function exposureRows(table: ExposureRow[] | undefined, claims: Claim[]): { rows: ExposureRow[]; live: boolean } {
  if (table && table.length) return { rows: table, live: false };
  const m = new Map<string, ExposureRow>();
  for (const c of claims) {
    const e = c.exposure;
    if (!e || (c.agent !== "thor" && c.agent !== "loki")) continue;
    const k = `${e.country}|${e.sector}`.toLowerCase();
    const row = m.get(k) ?? { country: e.country, sector: e.sector, thor: null, loki: null, odin: null, note: "", unavailable: {} };
    row[c.agent] = e;
    m.set(k, row);
  }
  return { rows: [...m.values()], live: true };
}

const ests = (r: ExposureRow) => WHO.map((w) => r[w]).filter(Boolean) as Estimate[];
const rowKey = (r: ExposureRow) => `${r.country}|${r.sector}`;
const uniq = <T,>(xs: T[]) => [...new Set(xs)];

/** Why an agent has no estimate for a row: the recorded reason, else the row note. */
function reason(r: ExposureRow, w: Who): string {
  return r.unavailable?.[w] || "no estimate recorded";
}

function Line({ w, e, scale, why }: { w: Who; e: Estimate | null; scale: Scale; why: string }) {
  const lo = e ? Math.min(e.low, e.high) : 0;
  const hi = e ? Math.max(e.low, e.high) : 0;
  return (
    <div className="grid grid-cols-[32px_minmax(0,1fr)_92px] items-center gap-x-2 sm:grid-cols-[36px_minmax(0,1fr)_116px] sm:gap-x-3">
      <span className="text-[11px] text-ink-3">{agentName(w)}</span>
      <div className="track" aria-hidden="true">
        {scale.ticks.map((t) => <span key={t} className="absolute inset-y-0 w-px bg-rule" style={{ left: `${scale.pos(t)}%` }} />)}
        {e && (
          <span className={`absolute ${w === "odin" ? "top-px h-2 bg-accent" : w === "thor" ? "top-0.5 h-1.5 bg-ink" : "top-0.5 h-1.5 border-[1.5px] border-ink bg-sheet"}`}
            style={{ left: `${scale.pos(lo)}%`, width: `max(${scale.pos(hi) - scale.pos(lo)}%, 3px)` }} />
        )}
        {!e && <span className="absolute inset-x-0 top-1 border-t border-dashed border-rule-2" />}
      </div>
      <span className={`text-right text-[11px] sm:text-xs ${e ? "num" : "text-ink-3"}`}>
        {e ? `${fmtNum(e.low)} – ${fmtNum(e.high)}` : "no estimate"}
        <span className="sr-only">{e ? ` ${e.unit}` : `: ${why}`}</span>
      </span>
    </div>
  );
}

function CalcList({ ids, calcs }: { ids: string[]; calcs: Map<string, CalcRecord> }) {
  const [openId, setOpenId] = useState<string | null>(null);
  return (
    <ul className="m-0 list-none p-0">
      {ids.map((id) => {
        const c = calcs.get(id);
        return (
          <li key={id}>
            <button type="button" className="cite" aria-expanded={openId === id} onClick={() => setOpenId(openId === id ? null : id)}>{id}</button>
            {openId === id && (
              <div className="mb-2 mt-1 border-l-2 border-rule-2 pl-2 text-xs text-ink-2">
                {c ? (
                  <>
                    <div><span className="mono">{c.operation}</span> = <span className="num">{c.result ?? "no result"}</span> {c.unit}</div>
                    <div className="mono break-words">{c.formula}</div>
                    <div>rows: <span className="mono break-words">{c.inputs.map((i) => i.row_id).filter(Boolean).join(", ")}</span></div>
                    {c.excluded_rows && Object.keys(c.excluded_rows).length > 0 && (
                      <div className="text-bad">excluded: {Object.entries(c.excluded_rows).map(([k, v]) => `${k}: ${v}`).join("; ")}</div>
                    )}
                  </>
                ) : "This calculation record is not among the case's recorded events."}
              </div>
            )}
          </li>
        );
      })}
    </ul>
  );
}

function Detail({ r, open, calcs }: { r: ExposureRow; open: OpenRef; calcs: Map<string, CalcRecord> }) {
  const es = WHO.map((w) => [w, r[w]] as const).filter(([, e]) => e) as [Who, Estimate][];
  const rows = uniq(es.flatMap(([, e]) => e.trade_row_refs));
  const calcIds = uniq(es.flatMap(([, e]) => e.calculation_ids));
  const missing = uniq(es.flatMap(([, e]) => e.missing_data));
  return (
    <div className="mt-5 grid grid-cols-1 gap-4 border-t border-rule pt-4 md:grid-cols-3 md:gap-7">
      <div className="min-w-0">
        <h3 className="label m-0 mb-1.5">Metric</h3>
        {es.length ? es.map(([w, e]) => (
          <div key={w} className="mb-2 text-ink-2">
            <div className="text-xs text-ink"><AgentMark agent={w} /></div>
            <p className="m-0">{e.metric_definition || e.metric}</p>
            <p className="m-0 text-xs text-ink-3">
              Unit {e.unit} · period {e.period}{e.denominator ? ` · denominator ${e.denominator}` : ""} · confidence {e.confidence}
            </p>
          </div>
        )) : <p className="m-0 text-ink-2">No estimate for this pair. {r.note}</p>}
      </div>
      <div className="min-w-0">
        <h3 className="label m-0 mb-1.5">Assumptions</h3>
        {es.some(([, e]) => e.assumptions.length) ? (
          <ul className="m-0 list-disc pl-4 text-ink-2">
            {es.flatMap(([w, e]) => e.assumptions.map((a, i) => <li key={`${w}${i}`}>{a} <span className="text-xs text-ink-3">({agentName(w)})</span></li>))}
          </ul>
        ) : <p className="m-0 text-ink-2">None stated.</p>}
        <h3 className="label m-0 mb-1.5 mt-3">Missing data</h3>
        {missing.length || WHO.some((w) => !r[w]) ? (
          <ul className="m-0 list-disc pl-4 text-ink-2">
            {missing.map((m, i) => <li key={i}>{m}</li>)}
            {WHO.filter((w) => !r[w]).map((w) => <li key={w}>{agentName(w)}: {reason(r, w)}</li>)}
          </ul>
        ) : <p className="m-0 text-ink-2">None recorded.</p>}
      </div>
      <div className="min-w-0">
        <h3 className="label m-0 mb-1.5">Evidence and calculations</h3>
        {rows.length ? (
          <div className="flex flex-col items-start">
            {rows.map((id) => <Cite key={id} c={{ doc_id: id.split("#")[0], row_id: id }} open={open} />)}
          </div>
        ) : <p className="m-0 text-ink-2">No trade rows.</p>}
        {calcIds.length > 0 && <div className="mt-2"><CalcList ids={calcIds} calcs={calcs} /></div>}
        {r.note && <p className="m-0 mt-2 text-xs text-ink-3">{r.note}</p>}
      </div>
    </div>
  );
}

/** The header of a chart group, read from its estimates (never from literals). */
function headline(group: ExposureRow[]): string {
  const es = group.flatMap(ests);
  const metrics = uniq(es.map((e) => e.metric));
  const periods = uniq(es.map((e) => e.period));
  const unit = uniq(es.map((e) => e.unit)).join(", ");
  if (metrics.length === 1 && periods.length === 1) return `${metrics[0]} · ${unit} · ${periods[0]}`;
  return `Unit ${unit}. The estimates use ${metrics.length === 1 ? `one metric (${metrics[0]})` : `${metrics.length} metric definitions`} and ${periods.length === 1 ? `one period (${periods[0]})` : `${periods.length} periods`}; select a row for each definition.`;
}

export function ExposureView({ table, t, open, finished }: { table?: ExposureRow[]; t: TrialState; open: OpenRef; finished: boolean }) {
  const { rows, live } = exposureRows(table, t.claims);
  const [sel, setSel] = useState<string | null>(null);
  // one shared scale per unit: values in different units are never drawn on the same axis
  const groups = useMemo(() => {
    const m = new Map<string, ExposureRow[]>();
    for (const r of rows) {
      const units = uniq(ests(r).map((e) => e.unit));
      const k = units.length === 1 ? units[0] : units.length ? "mixed" : "none";
      m.set(k, [...(m.get(k) ?? []), r]);
    }
    return [...m.entries()].sort(([a], [b]) => Number(a === "none") - Number(b === "none") || a.localeCompare(b));
  }, [rows]);
  if (!rows.length) return <Empty>{finished ? "No exposure estimates were recorded in this case." : "No exposure estimates yet. They appear as Thor and Loki submit claims with estimates."}</Empty>;
  const selected = rows.find((r) => rowKey(r) === sel) ?? rows.find((r) => ests(r).length) ?? rows[0];

  return (
    <>
      <div className="flex flex-wrap items-center gap-5 text-xs text-ink-2">
        {WHO.map((w) => <span key={w}><AgentMark agent={w} label={false} /> <span className="ml-1">{w === "odin" ? "Odin, built from evidence" : agentName(w)}</span></span>)}
      </div>
      {live && <p className="m-0 mt-3 text-[13px] text-ink-2">Live view: Thor's and Loki's submitted estimates. Odin's ranges appear with the briefing.</p>}
      {groups.map(([unit, group]) => {
        const es = group.flatMap(ests);
        const scale = linearScale(es.flatMap((e) => [e.low, e.high]));
        const drawable = unit !== "none" && unit !== "mixed";
        return (
          <div key={unit} className="mt-5">
            {drawable && <p className="m-0 text-[13px] text-ink-2">{headline(group)}</p>}
            {unit === "mixed" && <p className="m-0 text-[13px] text-bad">These rows mix units; their estimates are listed without a shared axis.</p>}
            {drawable && (
              <div className="grid grid-cols-1 gap-5 px-2 pt-2.5 md:grid-cols-[132px_minmax(0,1fr)]" aria-hidden="true">
                <div className="hidden md:block" />
                <div className="grid grid-cols-[32px_minmax(0,1fr)_92px] gap-2 sm:grid-cols-[36px_minmax(0,1fr)_116px] sm:gap-3">
                  <span />
                  <div className="relative h-4 font-mono text-[11px] text-ink-3">
                    {scale.ticks.map((tk, i) => (
                      <span key={tk} className="absolute" style={{ left: `${scale.pos(tk)}%`, transform: i === 0 ? "none" : i === scale.ticks.length - 1 ? "translateX(-100%)" : "translateX(-50%)" }}>{tk}</span>
                    ))}
                  </div>
                </div>
              </div>
            )}
            <ul className="m-0 mt-2 list-none p-0">
              {group.map((r) => {
                const has = ests(r).length > 0;
                const on = rowKey(selected) === rowKey(r);
                return (
                  <li key={rowKey(r)}>
                    <button type="button" aria-pressed={on} onClick={() => setSel(rowKey(r))}
                      className={`grid w-full grid-cols-1 items-start gap-2 border-b border-rule px-2 py-3.5 text-left md:grid-cols-[132px_minmax(0,1fr)] md:gap-5 ${on ? "bg-accent-wash" : "hover:bg-paper"}`}>
                      <div><div className="font-medium">{r.country}</div><div className="text-ink-2">{r.sector}</div></div>
                      {has && drawable ? (
                        <div className="flex flex-col gap-[7px]">
                          {WHO.map((w) => <Line key={w} w={w} e={r[w]} scale={scale} why={reason(r, w)} />)}
                        </div>
                      ) : has ? (
                        <div className="text-[13px] text-ink-2">
                          {WHO.map((w) => <div key={w}>{agentName(w)}: {r[w] ? <span className="num">{fmtNum(r[w]!.low)} – {fmtNum(r[w]!.high)} {r[w]!.unit}</span> : "no estimate"}</div>)}
                        </div>
                      ) : (
                        <div className="border border-dashed border-rule-2 px-2.5 py-2 text-[13px] text-ink-2">
                          No estimate. {r.note || Object.entries(r.unavailable ?? {}).map(([w, why]) => `${agentName(w)}: ${why}`).join(". ")
                            || "No reason recorded."} This is missing data, not zero.
                        </div>
                      )}
                    </button>
                  </li>
                );
              })}
            </ul>
          </div>
        );
      })}
      <Detail r={selected} open={open} calcs={t.calcs} />
    </>
  );
}
