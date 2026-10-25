import type { Claim, Estimate, ExposureRow } from "./api";
import { Empty } from "./ui";

const COLORS: Record<string, string> = { thor: "bg-orange-400", loki: "bg-emerald-500", odin: "bg-indigo-600" };

/** From the briefing's exposure table when it exists; while the trial runs, from the advocates' submitted estimates. */
export function exposureRows(table: ExposureRow[] | undefined, claims: Claim[]): { rows: ExposureRow[]; live: boolean } {
  if (table && table.length) return { rows: table, live: false };
  const m = new Map<string, ExposureRow>();
  for (const c of claims) {
    const e = c.exposure;
    if (!e) continue;
    const k = `${e.country}|${e.sector}`;
    const row = m.get(k) ?? { country: e.country, sector: e.sector, thor: null, loki: null, odin: null, note: "", unavailable: {} };
    if (c.agent === "thor" || c.agent === "loki") row[c.agent] = e;
    m.set(k, row);
  }
  return { rows: [...m.values()], live: true };
}

function Bar({ who, e, max, why }: { who: string; e: Estimate | null; max: number; why?: string }) {
  return (
    <div className="flex items-center gap-2 text-xs">
      <span className="w-10 font-semibold capitalize">{who}</span>
      <div className="relative h-4 flex-1 rounded bg-slate-100">
        {e && (
          <div className={`absolute top-0 h-4 rounded ${COLORS[who]}`}
            style={{ left: `${(Math.min(Math.abs(e.low), Math.abs(e.high)) / max) * 100}%`,
                     width: `${Math.max(1, (Math.abs(Math.abs(e.high) - Math.abs(e.low)) / max) * 100)}%` }} />
        )}
      </div>
      <span className="w-56 text-right">
        {e ? `${e.low.toLocaleString()} – ${e.high.toLocaleString()} ${e.unit}` : <i className="text-slate-500">unavailable{why ? `: ${why}` : ""}</i>}
      </span>
    </div>
  );
}

export function ExposureView({ table, claims }: { table?: ExposureRow[]; claims: Claim[] }) {
  const { rows, live } = exposureRows(table, claims);
  if (!rows.length) return <Empty>No exposure estimates yet.</Empty>;
  return (
    <div className="space-y-3">
      {live && <div className="text-xs text-amber-700">Live view: advocates' submitted estimates. Odin's ranges appear with the briefing.</div>}
      {rows.map((r) => {
        const es = [r.thor, r.loki, r.odin].filter(Boolean) as Estimate[];
        const max = Math.max(1, ...es.map((e) => Math.max(Math.abs(e.low), Math.abs(e.high)))) * 1.05;
        const units = new Set(es.map((e) => e.unit));
        return (
          <div key={`${r.country}-${r.sector}`} className="rounded border bg-white p-3">
            <div className="mb-2 flex items-baseline gap-2">
              <h4 className="font-semibold">{r.country} / {r.sector}</h4>
              <span className="text-xs text-slate-500">{r.note}</span>
              {units.size > 1 && <span className="text-xs text-rose-700">units differ: {[...units].join(", ")} (bars not comparable)</span>}
            </div>
            <div className="space-y-1">
              {(["thor", "loki", "odin"] as const).map((w) => <Bar key={w} who={w} e={r[w]} max={max} why={r.unavailable?.[w]} />)}
            </div>
            <div className="mt-2 space-y-0.5 text-xs text-slate-600">
              {(["thor", "loki", "odin"] as const).map((w) => r[w] && (
                <div key={w}>
                  <b className="capitalize">{w}:</b> {r[w]!.metric} — {r[w]!.metric_definition}. Unit {r[w]!.unit}, period {r[w]!.period}
                  {r[w]!.denominator ? `, denominator ${r[w]!.denominator}` : ""}; confidence {r[w]!.confidence}; calcs {r[w]!.calculation_ids.join(", ")}
                </div>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}
