import { useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError, FeedItem, splitRow } from "../api";
import { Alert, Empty, Filters, Skeleton } from "../components/layout";
import type { OpenRef } from "../components/marks";
import { dayNum, fmtDate, monthLabel } from "../lib/format";
import type { TrialState } from "../useCase";

export interface DocTarget {
  doc_id: string;
  paragraph_ref?: string | null;
  row_id?: string | null;
}

type Filter = "all" | "t12" | "fix" | "bad" | "later";
type Scope = "case" | "window";

function firstRun(t: TrialState, doc: string): number | null {
  const r = t.retrievedDocs.get(doc);
  return r ? Math.min(...r.runs) : null;
}

function docState(i: FeedItem): "corrected" | "flagged" | "damaged" | "normal" {
  if (i.badges.injection.length) return "flagged";
  if (i.badges.corrected_by.length) return "corrected";
  if (i.badges.damaged.length) return "damaged";
  return "normal";
}

function tagOf(i: FeedItem, t: TrialState, newDocs: Set<string>): { text: string; bad: boolean } | null {
  if (i.badges.injection.length) return { text: "Flagged", bad: true };
  if (i.badges.corrected_by.length) return { text: `Corrected by ${i.badges.corrected_by.join(", ")}`, bad: false };
  if (i.badges.damaged.length) return { text: "Damaged", bad: true };
  if (i.badges.corrects.length) return { text: `Corrects ${i.badges.corrects.join(", ")}`, bad: false };
  if (i.badges.duplicate_of.length) return { text: `Duplicate of ${i.badges.duplicate_of.join(", ")}`, bad: false };
  if (newDocs.has(i.doc_id)) return { text: `New in run ${firstRun(t, i.doc_id) ?? 2}`, bad: false };
  const fr = firstRun(t, i.doc_id);
  if (fr && fr > 1) return { text: `Added in run ${fr}`, bad: false };
  return null;
}

function Timeline({ items, asOf, withheld, onPick, selected, retrieved }: {
  items: FeedItem[]; asOf: string; withheld: number; onPick: (id: string) => void; selected?: string; retrieved: Set<string>;
}) {
  const dated = items.filter((i) => Number.isFinite(dayNum(i.pub_date)));
  if (!dated.length) return null;
  const a = dayNum(asOf);
  const floor = a - 366; // the year before the as-of date; older (reference) documents are counted, not drawn
  const older = dated.filter((i) => dayNum(i.pub_date) < floor);
  const near = dated.filter((i) => dayNum(i.pub_date) >= floor);
  const lo0 = Math.min(...near.map((i) => dayNum(i.pub_date)), a);
  const hi0 = Math.max(...near.map((i) => dayNum(i.pub_date)), a);
  const pad = Math.max(10, (hi0 - lo0) * 0.04);
  const lo = lo0 - pad * (older.length ? 4 : 1); // room for the "older" label at the left edge
  const hi = hi0 + pad * (withheld ? 2 : 1);
  const x = (d: number) => ((d - lo) / (hi - lo)) * 100;
  // month ticks generated from the range; thinned so labels never collide
  const start = new Date(lo * 86_400_000);
  const months: { d: number; y: number; m: number }[] = [];
  for (let y = start.getUTCFullYear(), m = start.getUTCMonth() + 1; ; m++) {
    if (m > 11) { m = 0; y++; }
    const d = Date.UTC(y, m, 1) / 86_400_000;
    if (d > hi) break;
    months.push({ d, y, m });
  }
  const every = Math.max(1, Math.ceil(months.length / 9));
  const multiYear = new Set(months.map((mo) => mo.y)).size > 1;
  return (
    <div className="relative mt-3.5 h-14" aria-label={`Publication timeline: ${dated.length} documents (${older.length} older than a year), as of ${fmtDate(asOf)}`} role="img">
      <div className="absolute inset-x-0 top-[30px] h-px bg-rule-2" />
      {months.filter((_, i) => i % every === 0).map((mo) => (
        <span key={mo.d} className="absolute top-9 font-mono text-[11px] text-ink-3" style={{ left: `${x(mo.d)}%` }}>
          {monthLabel(mo.y, mo.m, multiYear && (mo.m === 0 || mo === months[0]))}
        </span>
      ))}
      {older.length > 0 && (
        <span className="absolute -top-px left-0 whitespace-nowrap bg-sheet pr-1 font-mono text-[11px] text-ink-3"
          title={older.map((i) => `${i.doc_id} ${i.pub_date}`).join("\n")}>← {older.length} older</span>
      )}
      {near.map((i) => (
        <span key={i.doc_id} title={`${i.doc_id} · ${i.pub_date} · ${i.title}`} onClick={() => onPick(i.doc_id)}
          className={`tl-doc cursor-pointer is-${docState(i)} ${retrieved.has(i.doc_id) ? "is-retrieved" : "opacity-50"} ${selected === i.doc_id ? "outline outline-2 outline-offset-1 outline-accent" : ""}`}
          style={{ left: `${x(dayNum(i.pub_date))}%` }} />
      ))}
      {withheld > 0 && (
        <span className="hatch absolute top-3 h-[18px] w-1.5" style={{ left: `${(x(a) + 100) / 2}%` }}
          title={`${withheld} document(s) published after the as-of date: withheld`} />
      )}
      <div className="absolute inset-y-0 w-0 border-l border-dashed border-accent" style={{ left: `${x(a)}%` }}>
        <span className={`absolute -top-px whitespace-nowrap bg-sheet px-0.5 text-[11px] text-accent ${x(a) > 80 ? "right-1.5" : "left-1.5"}`}>As of {fmtDate(asOf).replace(/ \d{4}$/, "")}</span>
      </div>
    </div>
  );
}

function Viewer({ target, caseId, cited }: { target: DocTarget | null; caseId: string; cited: Set<string> }) {
  const [doc, setDoc] = useState<any>(null);
  const [table, setTable] = useState<any>(null);
  const [err, setErr] = useState<{ blocked: boolean; msg: string } | null>(null);
  const [original, setOriginal] = useState(false);
  const hl = useRef<HTMLElement | null>(null);
  const box = useRef<HTMLElement | null>(null);

  useEffect(() => {
    setDoc(null); setTable(null); setErr(null); setOriginal(false);
    if (!target) return;
    let stop = false;
    const fail = (e: any) => !stop && setErr({ blocked: e instanceof ApiError && e.status === 403, msg: e.message });
    api.doc(target.doc_id, caseId).then((d) => !stop && setDoc(d)).catch(fail);
    if (target.row_id) api.table(splitRow(target.row_id)[0], caseId).then((tb) => !stop && setTable(tb)).catch(fail);
    return () => { stop = true; };
  }, [target?.doc_id, target?.row_id, caseId]);

  useEffect(() => {
    if (!doc) return;
    // keep the highlighted paragraph in view inside the viewer, and bring the viewer into view on phones
    hl.current?.scrollIntoView({ block: "nearest" });
    if (window.matchMedia("(max-width: 767px)").matches) box.current?.scrollIntoView({ block: "start" });
  }, [doc, table, target?.paragraph_ref, target?.row_id]);

  if (!target) return <p className="m-0 text-ink-2">Select a document to read it here. Citations elsewhere open here too.</p>;
  if (err) return err.blocked
    ? <div><div className="label">Document</div><p className="mono m-0 mt-1">{target.doc_id}</p>
        <p className="m-0 mt-2 text-ink-2">Blocked: published after the as-of date. No content is shown, and no agent received it.</p></div>
    : <Alert tone="bad" title="Document unavailable">{err.msg}</Alert>;
  if (!doc) return <Skeleton rows={4} label="Loading document" />;
  const flagged = (doc.paragraphs ?? []).some((p: any) => p.injection_flagged);
  const highlightRefs = target.paragraph_ref ? new Set([target.paragraph_ref]) : cited;
  return (
    <section ref={box as any} aria-label="Document" aria-live="polite">
      <div className="label">Document</div>
      <h3 className="m-0 mt-0.5 text-[15px] font-semibold leading-snug">{doc.title}</h3>
      <div className="mono text-ink-2">{doc.doc_id} · tier {doc.reliability_tier ?? "?"} · {doc.pub_date}{doc.pub_time ? ` ${String(doc.pub_time).slice(0, 5)}` : ""}</div>
      <div className="text-xs text-ink-3">{doc.source_name} · {doc.source_type}{doc.format ? ` · ${doc.format}` : ""}</div>
      {(doc.relations ?? []).length > 0 && <p className="m-0 mt-2 text-ink-2">{doc.relations.join(". ")}.</p>}
      {(doc.damage ?? []).length > 0 && <p className="m-0 mt-2 text-bad">Damaged: {doc.damage.join("; ")}. Kept for provenance.</p>}
      {flagged && (
        <button type="button" aria-pressed={original} onClick={() => setOriginal(!original)}
          className="mt-2 border-b-[1.5px] border-transparent text-[13px] text-ink-2 hover:text-ink aria-pressed:border-ink aria-pressed:text-ink">
          {original ? "Showing original text (as ingested)" : "Show original text of flagged paragraphs"}
        </button>
      )}
      <div className="mt-3">
        {(doc.paragraphs ?? []).map((p: any) => {
          const on = highlightRefs.has(p.ref);
          return (
            <div key={p.ref} id={p.anchor} ref={target.paragraph_ref === p.ref ? (el) => { hl.current = el; } : undefined}
              className={`grid grid-cols-[30px_minmax(0,1fr)] gap-1.5 border-b border-rule py-2 ${p.injection_flagged ? "bg-bad-wash px-2" : ""}`}>
              <span className="pt-0.5 font-mono text-[11px] text-ink-3">{p.ref}</span>
              <span>
                <span className={`${on ? "bg-hl" : ""} ${p.injection_flagged ? "text-bad" : ""}`}>
                  {original && p.original_text ? p.original_text : p.text}
                </span>
                {p.injection_flagged && <span className="mt-1 block text-xs text-bad">Suspicious span. Kept as evidence text, withheld as instruction. No agent acts on it.</span>}
              </span>
            </div>
          );
        })}
        {!(doc.paragraphs ?? []).length && <p className="m-0 text-ink-3">No text available.</p>}
      </div>
      {target.row_id && (
        <div className="mt-4">
          <div className="label border-b border-ink pb-1.5">Trade table {splitRow(target.row_id)[0]}</div>
          {!table ? <Skeleton rows={2} label="Loading trade rows" /> : (
            <div className="overflow-x-auto">
              <table className="w-full border-collapse text-xs">
                <thead><tr className="text-left text-ink-3">{["Row", "Period", "Value", "Volume", "Status"].map((h) => <th key={h} className="label py-1.5 pr-3">{h}</th>)}</tr></thead>
                <tbody>
                  {table.rows.map((r: any) => {
                    const on = r.row_id === target.row_id;
                    return (
                      <tr key={r.row_id} ref={on ? (el) => { hl.current = el; } : undefined}
                        className={`border-b border-rule ${on ? "bg-hl" : ""} ${r.status !== "valid" ? "text-bad" : ""}`}>
                        <td className="mono py-1.5 pr-3">{r.row_id.split("#").pop()}</td>
                        <td className="num pr-3">{r.period ?? "missing"}</td>
                        <td className="num pr-3">{r.value != null ? `${r.value} ${r.currency} M` : "missing"}</td>
                        <td className="num pr-3">{r.volume != null ? `${r.volume} ${r.volume_unit}` : "missing"}</td>
                        <td className="pr-3">{r.status}{r.damage_reason ? `: ${r.damage_reason}` : ""}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
      {highlightRefs.size > 0 && <p className="m-0 mt-2.5 text-xs text-ink-3">
        {target.paragraph_ref || target.row_id ? "Highlighted: the cited passage." : "Highlighted text is cited in this case."}</p>}
    </section>
  );
}

export function EvidenceView({ asOf, caseId, t, target, open }: {
  asOf?: string; caseId: string; t: TrialState; target: DocTarget | null; open: OpenRef;
}) {
  const [items, setItems] = useState<FeedItem[] | null>(null);
  const [withheld, setWithheld] = useState(0);
  const [err, setErr] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [scope, setScope] = useState<Scope>("case");

  useEffect(() => {
    if (!asOf) return;
    setItems(null); setErr(null);
    api.feed(asOf).then((f) => { setItems(f.items); setWithheld(f.withheld_after_as_of); }).catch((e) => setErr(e.message));
  }, [asOf]);

  // paragraphs/rows cited anywhere in the case, per document (for the viewer's highlight)
  const citedByDoc = useMemo(() => {
    const m = new Map<string, Set<string>>();
    const add = (c: { doc_id: string; paragraph_ref: string | null }) => {
      if (!c.paragraph_ref) return;
      m.set(c.doc_id, (m.get(c.doc_id) ?? new Set()).add(c.paragraph_ref));
    };
    t.claims.forEach((c) => c.citations.forEach(add));
    t.attacks.forEach((a) => a.counter_evidence.forEach(add));
    t.defenses.forEach((d) => d.new_evidence.forEach(add));
    return m;
  }, [t.claims, t.attacks, t.defenses]);
  const newDocs = useMemo(() => new Set(t.newEvidence.flatMap((e) => (e.payload.evidence ?? []).map((x: any) => x.doc_id))), [t.newEvidence]);
  const retrieved = useMemo(() => new Set(t.retrievedDocs.keys()), [t.retrievedDocs]);

  if (!asOf) return <Skeleton rows={5} label="Loading case" />;
  if (err) return <Alert tone="bad" title="Evidence feed unavailable">{err}</Alert>;
  if (!items) return <Skeleton rows={6} label="Loading evidence" />;

  const scoped = scope === "case" ? items.filter((i) => retrieved.has(i.doc_id)) : items;
  const pass = (i: FeedItem) => filter === "all" ? true
    : filter === "t12" ? (i.reliability_tier ?? 9) <= 2
    : filter === "fix" ? i.badges.corrects.length > 0 || i.badges.corrected_by.length > 0
    : filter === "bad" ? i.badges.injection.length > 0 || i.badges.damaged.length > 0
    : newDocs.has(i.doc_id) || (firstRun(t, i.doc_id) ?? 1) > 1;
  const shown = scoped.filter(pass);
  const blocked = [...t.blockedDocs.keys()].filter((d) => !items.some((i) => i.doc_id === d));
  const pick = (doc_id: string) => open({ doc_id });

  return (
    <>
      <Timeline items={scoped} asOf={asOf} withheld={withheld} onPick={pick} selected={target?.doc_id} retrieved={retrieved} />
      <p className="m-0 mt-1 text-xs text-ink-3">
        {retrieved.size} retrieved in this case · {items.length} published on or before the as-of date · {withheld} withheld after it
        {blocked.length ? ` · ${blocked.length} blocked request${blocked.length === 1 ? "" : "s"} logged` : ""}
      </p>
      <div className="mt-5 grid grid-cols-1 gap-8 md:grid-cols-[minmax(0,1fr)_minmax(0,340px)]">
        <div className="min-w-0">
          <div className="mb-1.5 flex flex-wrap items-baseline justify-between gap-x-6 gap-y-2">
            <Filters label="Filter documents" value={filter} onChange={setFilter}
              options={[["all", "All"], ["t12", "Tier 1 and 2"], ["fix", "Corrections"], ["bad", "Damaged or flagged"], ["later", "Added in run 2+"]]} />
            <Filters label="Which documents" value={scope} onChange={setScope}
              options={[["case", "Retrieved"], ["window", "All before as-of"]]} />
          </div>
          {shown.length || (filter === "bad" && blocked.length) ? (
            <ul className="m-0 list-none p-0">
              {shown.map((i) => {
                const tag = tagOf(i, t, newDocs);
                const on = target?.doc_id === i.doc_id;
                return (
                  <li key={i.doc_id}>
                    <button type="button" aria-pressed={on} onClick={() => pick(i.doc_id)}
                      className={`grid w-full grid-cols-[76px_minmax(0,1fr)] items-baseline gap-x-3 border-b border-rule px-2 py-2.5 text-left sm:grid-cols-[76px_minmax(0,1fr)_auto] ${on ? "bg-accent-wash" : "hover:bg-paper"}`}>
                      <span className="mono">{i.doc_id}</span>
                      <span className="truncate">{i.title}</span>
                      <span className="col-start-2 whitespace-nowrap text-xs text-ink-3 sm:col-start-auto">
                        {tag && <span className={tag.bad ? "text-bad" : ""}>{tag.text} · </span>}T{i.reliability_tier ?? "?"} · <span className="num">{i.pub_date}</span>
                      </span>
                    </button>
                  </li>
                );
              })}
              {filter === "bad" && blocked.map((d) => (
                <li key={d}>
                  <button type="button" aria-pressed={target?.doc_id === d} onClick={() => pick(d)}
                    className="grid w-full grid-cols-[76px_minmax(0,1fr)] gap-x-3 border-b border-rule px-2 py-2.5 text-left hover:bg-paper">
                    <span className="mono">{d}</span><span className="text-ink-2">Blocked request: published after the as-of date</span>
                  </button>
                </li>
              ))}
            </ul>
          ) : <Empty>{scope === "case" && !retrieved.size ? "No documents retrieved yet." : "No documents match this filter."}</Empty>}
        </div>
        <aside className="min-w-0 border-t border-rule pt-4 md:border-l md:border-t-0 md:pl-7 md:pt-0">
          <Viewer target={target} caseId={caseId} cited={target ? citedByDoc.get(target.doc_id) ?? new Set() : new Set()} />
        </aside>
      </div>
    </>
  );
}
