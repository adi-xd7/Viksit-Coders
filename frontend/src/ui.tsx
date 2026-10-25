import type { ReactNode } from "react";
import type { Citation, Verdict } from "./api";

export type OpenRef = (r: { doc_id: string; paragraph_ref?: string | null; row_id?: string | null }) => void;

const VERDICT: Record<Verdict, string> = {
  established: "bg-emerald-100 text-emerald-800 ring-emerald-300",
  contested: "bg-amber-100 text-amber-800 ring-amber-300",
  conceded: "bg-sky-100 text-sky-800 ring-sky-300",
  rejected: "bg-rose-100 text-rose-800 ring-rose-300",
};

export function VerdictChip({ v, run }: { v: Verdict; run?: number }) {
  return (
    <span className={`inline-block rounded px-1.5 py-0.5 text-xs font-semibold ring-1 ${VERDICT[v]}`}>
      {v}
      {run ? <span className="font-normal opacity-70"> · run {run}</span> : null}
    </span>
  );
}

export function Badge({ children, tone = "slate", title }: { children: ReactNode; tone?: string; title?: string }) {
  const tones: Record<string, string> = {
    slate: "bg-slate-100 text-slate-700",
    red: "bg-rose-100 text-rose-800",
    amber: "bg-amber-100 text-amber-800",
    green: "bg-emerald-100 text-emerald-800",
    blue: "bg-sky-100 text-sky-800",
    violet: "bg-violet-100 text-violet-800",
    dark: "bg-slate-700 text-white",
  };
  return (
    <span title={title} className={`inline-block rounded px-1.5 py-0.5 text-[11px] font-medium ${tones[tone] ?? tones.slate}`}>
      {children}
    </span>
  );
}

export function TierBadge({ tier }: { tier: number | null | undefined }) {
  const tone = tier === 1 ? "green" : tier === 2 ? "blue" : tier === 3 ? "amber" : "red";
  return <Badge tone={tone} title="reliability tier (1 = official, 4 = weak)">T{tier ?? "?"}</Badge>;
}

export function TypeTag({ t }: { t: "fact" | "inference" }) {
  return <Badge tone={t === "fact" ? "dark" : "violet"}>{t}</Badge>;
}

export function Cite({ c, open }: { c: Citation; open: OpenRef }) {
  const loc = c.row_id ?? `${c.doc_id} ${c.paragraph_ref}`;
  return (
    <button
      onClick={() => open(c)}
      title={`“${c.quote}”`}
      className="mx-0.5 rounded bg-indigo-50 px-1 font-mono text-[11px] text-indigo-700 hover:bg-indigo-100"
    >
      [{loc}, {c.pub_date}]
    </button>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="rounded border border-dashed border-slate-300 p-4 text-sm text-slate-500">{children}</div>;
}

export function ErrorBox({ children }: { children: ReactNode }) {
  return <div className="rounded border border-rose-300 bg-rose-50 p-3 text-sm text-rose-800">{children}</div>;
}

export function Loading({ what }: { what: string }) {
  return <div className="animate-pulse p-3 text-sm text-slate-500">Loading {what}…</div>;
}

export function Section({ title, children, right }: { title: string; children: ReactNode; right?: ReactNode }) {
  return (
    <section className="mb-4">
      <div className="mb-1 flex items-center justify-between">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-600">{title}</h3>
        {right}
      </div>
      {children}
    </section>
  );
}

export const AGENT_COLOR: Record<string, string> = {
  heimdall: "text-teal-700",
  thor: "text-orange-700",
  loki: "text-emerald-700",
  odin: "text-indigo-700",
  system: "text-slate-500",
  user: "text-slate-500",
};
