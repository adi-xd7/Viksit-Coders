import { useEffect, useMemo, useState } from "react";
import type { Citation } from "../api";
import { Empty, Filters, Section } from "../components/layout";
import { AgentMark, agentName, ClaimType, Cite, type OpenRef, Verdict } from "../components/marks";
import { buildMap, focusOf, type MapEdge, type MapLayout, type MapNode, responseTo } from "../lib/argmap";
import type { TrialState } from "../useCase";

type Side = "both" | "thor" | "loki";

const RESPONSE_LABEL = {
  defense: "Defends with new evidence",
  concession: "Concedes",
  withdrawal: "Withdrawn",
  undefended: "Undefended",
  awaiting: "Awaiting a response",
} as const;
// node headers are one line: short forms
const RESPONSE_SHORT = { ...RESPONSE_LABEL, defense: "Defends", awaiting: "Awaiting" } as const;

/** One curve from the right edge of `a` to the left edge of `b` (a revision: a short drop between stacked claims). */
function path(a: MapNode, b: MapNode, kind: MapEdge["kind"]): string {
  if (kind === "revises") {
    const x = a.x + 12;
    return `M${x},${a.y + a.h} L${x},${b.y}`;
  }
  const x1 = a.x + a.w, y1 = a.y + a.h / 2, x2 = b.x, y2 = b.y + b.h / 2;
  const dx = Math.max(18, (x2 - x1) / 2);
  return `M${x1},${y1} C${x1 + dx},${y1} ${x2 - dx},${y2} ${x2},${y2}`;
}

const EDGE_STYLE: Record<MapEdge["kind"], { stroke: string; on: string; width: number; dash?: string }> = {
  cites: { stroke: "var(--rule-2)", on: "var(--ink-3)", width: 1 },
  attacks: { stroke: "var(--ink-3)", on: "var(--ink)", width: 1.25 },
  responds: { stroke: "var(--rule-2)", on: "var(--ink-2)", width: 1 },
  rules: { stroke: "var(--accent-line)", on: "var(--accent)", width: 1 },
  counter: { stroke: "var(--ink-3)", on: "var(--ink-2)", width: 1, dash: "3 3" },
  new: { stroke: "var(--ink-3)", on: "var(--ink-2)", width: 1, dash: "3 3" },
  revises: { stroke: "var(--ink-3)", on: "var(--ink-2)", width: 1, dash: "2 3" },
};

function Edges({ m, focus }: { m: MapLayout; focus: Set<string> | null }) {
  const byId = useMemo(() => new Map(m.nodes.map((n) => [n.id, n])), [m]);
  return (
    <svg className="pointer-events-none absolute inset-0" width={m.width} height={m.height} aria-hidden="true">
      <defs>
        {(["off", "on"] as const).map((s) => (
          <marker key={s} id={`am-arrow-${s}`} viewBox="0 0 8 8" refX="8" refY="4" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M0,0 L8,4 L0,8 z" style={{ fill: s === "on" ? "var(--ink)" : "var(--ink-3)" }} />
          </marker>
        ))}
      </defs>
      {m.edges.map((e) => {
        const a = byId.get(e.from), b = byId.get(e.to);
        if (!a || !b) return null;
        const on = !!focus && focus.has(e.from) && focus.has(e.to);
        // counter-evidence and defense evidence links cross the claims column: drawn only for the selection
        if ((e.kind === "counter" || e.kind === "new") && !on) return null;
        const s = EDGE_STYLE[e.kind];
        return (
          <path key={e.id} d={path(a, b, e.kind)} fill="none" stroke={on ? s.on : s.stroke}
            strokeWidth={on ? s.width + 0.5 : s.width} strokeDasharray={s.dash}
            opacity={focus && !on ? 0.25 : 1}
            markerStart={e.kind === "attacks" ? `url(#am-arrow-${on ? "on" : "off"})` : undefined} />
        );
      })}
    </svg>
  );
}

function NodeBody({ n }: { n: MapNode }) {
  const top = "flex min-w-0 items-center gap-1.5 overflow-hidden whitespace-nowrap text-[11px] text-ink-3";
  const line = "truncate text-xs text-ink";
  if (n.kind === "doc") {
    return (
      <span className="flex min-w-0 items-baseline justify-between gap-1.5">
        <span className="mono truncate text-ink">{n.doc}</span>
        <span className="num shrink-0 text-[10.5px] text-ink-3">{n.refs!.length}</span>
      </span>
    );
  }
  if (n.kind === "claim") {
    const c = n.claim!;
    return (
      <>
        <span className={top}>
          <span className={`mark mark-${c.agent}`} style={{ width: 12 }} aria-hidden="true" />
          <span className="mono shrink-0 text-ink">{c.claim_id}</span>
          <span className="truncate">· {c.claim_type}{c.country ? ` · ${c.country}${c.sector ? ` / ${c.sector}` : ""}` : ""}</span>
        </span>
        <span className={`${line} ${n.inactive ? "text-ink-2" : ""}`}>{c.text}</span>
      </>
    );
  }
  if (n.kind === "attack") {
    const a = n.attack!;
    return (
      <>
        <span className={top}>
          <span className={`mark mark-${a.attacker}`} style={{ width: 12 }} aria-hidden="true" />
          <span className="text-ink">{agentName(a.attacker)}</span>
          <span className="mono truncate">{a.attack_id}{a.round_number > 1 ? ` · r${a.round_number}` : ""}</span>
        </span>
        <span className={line}>{a.objection}</span>
      </>
    );
  }
  if (n.kind === "response") {
    const k = n.response!;
    const who = n.defense?.defender ?? n.concession?.agent;
    const text = n.defense?.argument ?? n.concession?.reason ??
      (k === "undefended" ? "No new evidence brought; the claim stays undefended." : "No response recorded yet.");
    return (
      <>
        <span className={top}>
          {who && <span className={`mark mark-${who}`} style={{ width: 12 }} aria-hidden="true" />}
          <span className={k === "undefended" ? "font-medium text-ink" : "text-ink"}>
            {RESPONSE_SHORT[k]}{k === "concession" && n.concession?.partial ? " in part" : ""}
          </span>
          {n.defense && <span className="ml-auto shrink-0">+{n.defense.new_evidence.length} new</span>}
        </span>
        <span className="truncate text-xs text-ink-2">{text}</span>
      </>
    );
  }
  const r = n.ruling;
  return (
    <>
      <span className="flex items-center"><Verdict v={r?.verdict ?? "unruled"} run={r && r.run_number > 1 ? r.run_number : undefined} /></span>
      <span className="truncate text-xs text-ink-2">{r ? r.rationale : "No ruling recorded."}</span>
    </>
  );
}

function nodeLabel(n: MapNode): string {
  switch (n.kind) {
    case "doc": return `Document ${n.doc}, ${n.refs!.length} cited paragraph(s) or row(s)`;
    case "claim": return `${agentName(n.claim!.agent)} claim ${n.claim!.claim_id}: ${n.claim!.text}`;
    case "attack": return `${agentName(n.attack!.attacker)} attack ${n.attack!.attack_id} on ${n.attack!.target_claim_id}: ${n.attack!.objection}`;
    case "response": return `${RESPONSE_LABEL[n.response!]}: ${n.defense?.argument ?? n.concession?.reason ?? ""}`;
    default: return `Odin's ruling on ${n.lane}: ${n.ruling?.verdict ?? "not ruled"}`;
  }
}

function MapNodeButton({ n, focus, selected, onSelect, onHover }: {
  n: MapNode; focus: Set<string> | null; selected: boolean; onSelect: (id: string) => void; onHover: (id: string | null) => void;
}) {
  const dim = focus && !focus.has(n.id);
  const dashed = n.kind === "response" && (n.response === "undefended" || n.response === "awaiting");
  const bad = n.kind === "ruling" && n.ruling?.verdict === "rejected";
  const tone = selected ? "border-accent bg-accent-wash"
    : bad ? "border-bad bg-sheet"
    : n.inactive ? "border-rule-2 bg-paper"
    : n.kind === "ruling" ? "border-accent-line bg-sheet"
    : "border-rule-2 bg-sheet";
  return (
    <button type="button" aria-pressed={selected} aria-label={nodeLabel(n)} title={nodeLabel(n)}
      onClick={(e) => { e.stopPropagation(); onSelect(n.id); }}
      onMouseEnter={() => onHover(n.id)} onMouseLeave={() => onHover(null)} onFocus={() => onHover(n.id)} onBlur={() => onHover(null)}
      className={`absolute flex flex-col justify-center gap-0.5 overflow-hidden rounded-sm border px-2 text-left transition-opacity duration-100 hover:border-ink-3
        ${dashed ? "border-dashed" : ""} ${tone} ${dim ? "opacity-30" : ""}`}
      style={{ left: n.x, top: n.y, width: n.w, height: n.h }}>
      <NodeBody n={n} />
    </button>
  );
}

const cites = (xs: Citation[], open: OpenRef) => xs.length > 0 && (
  <span className="flex flex-wrap gap-x-2.5 gap-y-1">{xs.map((c, i) => <Cite key={i} c={c} open={open} />)}</span>
);

/** The whole exchange around one claim, as text: claim, citations, attacks and responses, Odin's rulings. */
function LaneDetail({ claimId, t, open, finished, run }: { claimId: string; t: TrialState; open: OpenRef; finished: boolean; run: number | "all" }) {
  const c = t.claims.find((x) => x.claim_id === claimId);
  if (!c) return null;
  const attacks = t.attacks.filter((a) => a.target_claim_id === claimId && (run === "all" || a.run_number === run));
  const withdrawn = t.concessions.filter((k) => k.claim_id === claimId && !k.attack_id);
  const revisedBy = t.claims.find((x) => x.revises_claim_id === claimId);
  const rulings = t.rulings[claimId] ?? [];
  return (
    <div className="grid grid-cols-1 gap-6 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-ink-3">
          <span className="inline-flex items-center gap-1.5"><AgentMark agent={c.agent} /> · <span className="mono">{c.claim_id}</span> ·
            <ClaimType t={c.claim_type} />{c.country ? ` · ${c.country}${c.sector ? ` / ${c.sector}` : ""}` : ""} · run {c.run_number}</span>
        </div>
        <p className="m-0 mt-1.5">{c.text}</p>
        <div className="mt-1.5">{cites(c.citations, open)}</div>
        {c.revises_claim_id && <p className="m-0 mt-1.5 text-xs text-ink-3">Revises {c.revises_claim_id}.</p>}
        {revisedBy && <p className="m-0 mt-1.5 text-xs text-ink-3">Superseded by {revisedBy.claim_id} in run {revisedBy.run_number}.</p>}
        {withdrawn.map((k) => <p key={k.concession_id} className="m-0 mt-1.5 text-xs text-ink-3">Withdrawn in run {k.run_number}: {k.reason}</p>)}
        <h3 className="label m-0 mt-4 border-b border-rule pb-1">Odin</h3>
        {rulings.length ? rulings.map((r) => (
          <div key={r.ruling_id} className="border-b border-rule py-2">
            <Verdict v={r.verdict} run={r.run_number} />
            <p className="m-0 mt-0.5 text-[13px] text-ink-2">{r.rationale}</p>
            {r.citation_issues.length > 0 && <p className="m-0 mt-0.5 text-xs text-bad">Citation issues: {r.citation_issues.join("; ")}</p>}
          </div>
        )) : <p className="m-0 py-2 text-ink-3">{finished ? "No ruling recorded." : "Not ruled yet."}</p>}
      </div>
      <div className="min-w-0">
        <h3 className="label m-0 border-b border-rule pb-1">Cross-examination</h3>
        {!attacks.length && <p className="m-0 py-2 text-ink-2">{finished ? "No attack on this claim was recorded." : "No attack yet."}</p>}
        {attacks.map((a) => {
          const r = responseTo(t, a, finished);
          return (
            <div key={a.attack_id} className="border-b border-rule py-2.5">
              <div className="text-xs text-ink-3"><AgentMark agent={a.attacker} /> · <span className="mono">{a.attack_id}</span>
                {a.round_number > 1 ? ` · round ${a.round_number}` : ""} · run {a.run_number}</div>
              <p className="m-0 mt-0.5">{a.objection}</p>
              {a.evidence_gap && <p className="m-0 mt-0.5 text-[13px] text-ink-3">Evidence gap: {a.evidence_gap}</p>}
              <div className="mt-1">{cites(a.counter_evidence, open)}</div>
              <p className="m-0 mt-1.5 text-[13px]">
                <span className="font-medium">{RESPONSE_LABEL[r.kind]}{r.concession?.partial ? " in part" : ""}.</span>{" "}
                <span className="text-ink-2">{r.defense?.argument ?? r.concession?.reason ?? ""}</span>
              </p>
              {r.defense && <div className="mt-1">{cites(r.defense.new_evidence, open)}</div>}
              {r.concession?.revised_claim_text && <p className="m-0 mt-1 text-[13px] text-ink-3">Revised claim: {r.concession.revised_claim_text}</p>}
            </div>
          );
        })}
      </div>
    </div>
  );
}

/** Every use of one document in the trial: who cited which paragraph or row, and for what. */
function DocDetail({ doc, m, open }: { doc: string; m: MapLayout; open: OpenRef }) {
  const uses: { who: string; what: string; c: Citation }[] = [];
  for (const n of m.nodes) {
    const add = (xs: Citation[], who: string, what: string) => xs.filter((c) => c.doc_id === doc).forEach((c) => uses.push({ who, what, c }));
    if (n.kind === "claim") add(n.claim!.citations, agentName(n.claim!.agent), `cites it in ${n.claim!.claim_id}`);
    if (n.kind === "attack") add(n.attack!.counter_evidence, agentName(n.attack!.attacker), `uses it against ${n.attack!.target_claim_id} (${n.attack!.attack_id})`);
    if (n.kind === "response" && n.defense) add(n.defense.new_evidence, agentName(n.defense.defender), `brings it as new evidence for ${n.defense.claim_id}`);
  }
  return (
    <div>
      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
        <span className="mono text-[13px]">{doc}</span>
        <button type="button" className="text-[13px] text-accent underline underline-offset-4" onClick={() => open({ doc_id: doc })}>Open the document</button>
      </div>
      <ul className="m-0 mt-2 list-none p-0">
        {uses.map((u, i) => (
          <li key={i} className="grid grid-cols-1 gap-x-4 border-b border-rule py-2 sm:grid-cols-[minmax(0,240px)_minmax(0,1fr)]">
            <span><span className="font-medium">{u.who}</span> <span className="text-ink-2">{u.what}</span></span>
            <span className="min-w-0"><Cite c={u.c} open={open} />{u.c.quote ? <span className="text-[13px] text-ink-2"> “{u.c.quote}”</span> : null}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function ArgumentMapView({ t, open, finished }: { t: TrialState; open: OpenRef; finished: boolean }) {
  const runs = t.runs.filter((r) => r > 0);
  const [run, setRun] = useState("all");
  const [side, setSide] = useState<Side>("both");
  const [sel, setSel] = useState<string | null>(null);
  const [hover, setHover] = useState<string | null>(null);
  const runOpt: number | "all" = run === "all" ? "all" : Number(run);
  const m = useMemo(() => buildMap(t, { run: runOpt, side, finished }), [t, runOpt, side, finished]);
  const selected = m.nodes.find((n) => n.id === sel) ?? null;
  const focus = focusOf(m, hover ?? (selected ? selected.id : null));

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setSel(null);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  if (!t.claims.length) {
    return <Empty>{finished ? "No claims were recorded in this case, so there is nothing to map." : "No claims yet. The map grows as Thor and Loki submit claims and attack each other."}</Empty>;
  }
  const count = (k: MapNode["kind"]) => m.nodes.filter((n) => n.kind === k).length;
  const responses = m.nodes.filter((n) => n.kind === "response");
  const stats: [number, string, string][] = [
    [count("doc"), "document cited", "documents cited"], [count("claim"), "claim", "claims"], [count("attack"), "attack", "attacks"],
    [responses.filter((n) => n.response === "defense").length, "defense", "defenses"],
    [responses.filter((n) => n.response === "concession" || n.response === "withdrawal").length, "concession", "concessions"],
    [m.nodes.filter((n) => n.kind === "ruling" && n.ruling).length, "ruling", "rulings"],
  ];
  const empty = !count("claim");

  return (
    <>
      <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-2">
        <Filters label="Side" value={side} onChange={(v) => { setSide(v); setSel(null); }}
          options={[["both", "Both sides"], ["thor", "Thor's claims"], ["loki", "Loki's claims"]]} />
        {runs.length > 1 && (
          <Filters label="Run" value={run} onChange={(v) => { setRun(v); setSel(null); }}
            options={[["all", "All runs"], ...runs.map((r) => [String(r), `Run ${r}`] as [string, string])]} />
        )}
      </div>
      <p className="m-0 mt-2 text-xs text-ink-2" aria-label="Map summary">
        {stats.map(([n, one, many], i) => <span key={many}>{i ? " · " : ""}<span className="num">{n}</span> {n === 1 ? one : many}</span>)}
      </p>
      <div className="mt-2 flex flex-wrap items-center gap-x-5 gap-y-1 text-xs text-ink-2" aria-label="Legend">
        <span><AgentMark agent="thor" /></span><span><AgentMark agent="loki" /></span><span><AgentMark agent="odin" /></span>
        <span className="inline-flex items-center gap-1.5"><svg width="26" height="8" aria-hidden="true"><path d="M2,4 L26,4" stroke="var(--ink-3)" strokeWidth="1.25" /><path d="M0,4 L7,0.5 L7,7.5 z" fill="var(--ink-3)" /></svg>attacks</span>
        <span className="inline-flex items-center gap-1.5"><svg width="26" height="8" aria-hidden="true"><path d="M0,4 L26,4" stroke="var(--ink-3)" strokeDasharray="3 3" /></svg>counter or new evidence (for the selection)</span>
        <span className="inline-flex items-center gap-1.5"><span className="inline-block h-3 w-5 rounded-sm border border-dashed border-ink-3" aria-hidden="true" />undefended</span>
      </div>

      {empty ? (
        <div className="mt-4"><Empty>{runOpt !== "all"
          ? `No claims or rulings were recorded in run ${runOpt}${side === "both" ? "" : ` for ${agentName(side)}`}.${t.effect ? ` ${t.effect.summary}` : ""}`
          : `No claims from ${agentName(side)} were recorded.`}</Empty></div>
      ) : (
      <div className="mt-4 overflow-x-auto pb-2" onClick={() => setSel(null)}>
        <div style={{ width: m.width }} className="mx-auto">
          <div className="relative h-6" aria-hidden="true">
            {m.cols.map((c) => <span key={c.key} className="label absolute top-0" style={{ left: c.x, width: c.w }}>{c.label}</span>)}
          </div>
          <div className="relative border-t border-ink" style={{ height: m.height + 8 }} role="group" aria-label="Argument map">
            <div className="absolute inset-x-0 top-2 bottom-0">
              {m.bands.map((b) => (
                <div key={b.agent} className="pointer-events-none absolute flex items-center justify-between gap-3 border-b border-rule text-xs"
                  style={{ left: m.cols[1].x, width: m.width - m.cols[1].x, top: b.y + 2, height: 20 }}>
                  <span className="font-medium"><AgentMark agent={b.agent} /></span>
                  <span className="text-ink-3">{b.agent === "thor" ? "High exposure" : "Limited exposure"} · {b.claims} claim{b.claims === 1 ? "" : "s"}</span>
                </div>
              ))}
              <Edges m={m} focus={focus} />
              {m.nodes.map((n) => (
                <MapNodeButton key={n.id} n={n} focus={focus} selected={sel === n.id} onHover={setHover}
                  onSelect={(id) => setSel(sel === id ? null : id)} />
              ))}
            </div>
          </div>
        </div>
      </div>
      )}

      <Section title={selected ? (selected.kind === "doc" ? "Selected document" : `Selected: claim ${selected.lane}`) : "Selected"}
        right={selected ? "Esc to clear" : undefined} className="mt-6">
        <div className="pt-3">
          {!selected ? <p className="m-0 text-ink-2">Select a claim, attack, response, ruling or document to read the whole exchange around it. Hover to trace its links.</p>
            : selected.kind === "doc" ? <DocDetail doc={selected.doc!} m={m} open={open} />
            : <LaneDetail claimId={selected.lane!} t={t} open={open} finished={finished} run={runOpt} />}
        </div>
      </Section>
    </>
  );
}
