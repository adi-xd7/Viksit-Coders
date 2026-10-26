import type { Attack, Claim, Concession, Defense, Ruling } from "../api";
import type { TrialState } from "../useCase";

/** Argument map layout: one lane per claim, read left to right as
 *  evidence → claim → attacks on it → each response → Odin's ruling.
 *  Built only from the case's recorded trial objects; positions are plain numbers (px). */

export type NodeKind = "doc" | "claim" | "attack" | "response" | "ruling";
export type ResponseKind = "defense" | "concession" | "withdrawal" | "undefended" | "awaiting";
export type EdgeKind = "cites" | "attacks" | "responds" | "rules" | "counter" | "new" | "revises";

export interface MapNode {
  id: string;
  kind: NodeKind;
  lane: string | null; // claim ID of the node's lane; null for documents
  x: number;
  y: number;
  w: number;
  h: number;
  claim?: Claim;
  attack?: Attack;
  defense?: Defense;
  concession?: Concession;
  ruling?: Ruling;
  response?: ResponseKind;
  inactive?: boolean; // claim withdrawn or superseded by a revision
  doc?: string;
  refs?: string[]; // documents: the distinct paragraphs / rows cited
}

export interface MapEdge {
  id: string;
  from: string;
  to: string;
  kind: EdgeKind;
}

export interface MapColumn {
  key: NodeKind;
  label: string;
  x: number;
  w: number;
}

export interface MapLayout {
  nodes: MapNode[];
  edges: MapEdge[];
  cols: MapColumn[];
  bands: { agent: "thor" | "loki"; y: number; claims: number }[];
  width: number;
  height: number;
}

export interface MapOptions {
  run: number | "all";
  side: "both" | "thor" | "loki";
  finished: boolean;
}

const COL_SPEC: [NodeKind, string, number][] = [
  ["doc", "Evidence", 112],
  ["claim", "Claims", 200],
  ["attack", "Attacks", 168],
  ["response", "Responses", 156],
  ["ruling", "Odin", 120],
];
const GAP = 36;
const SLOT = 58; // one attack (and its response) per slot
const NODE_H = 46;
const DOC_H = 26;
const DOC_STEP = DOC_H + 8;
const BAND_HEAD = 30;
const LANE_GAP = 10;
const BAND_GAP = 18;

export const MAP_COLS: MapColumn[] = (() => {
  let x = 0;
  return COL_SPEC.map(([key, label, w]) => {
    const c = { key, label, x, w };
    x += w + GAP;
    return c;
  });
})();
export const MAP_WIDTH = MAP_COLS[MAP_COLS.length - 1].x + MAP_COLS[MAP_COLS.length - 1].w;

const natural = (a: string, b: string) => a.localeCompare(b, undefined, { numeric: true });
const col = (k: NodeKind) => MAP_COLS.find((c) => c.key === k)!;

/** The ruling shown for a claim: the run's own ruling, else the latest one up to that run. */
export function rulingFor(t: TrialState, claimId: string, run: number | "all"): Ruling | undefined {
  const rs = t.rulings[claimId] ?? [];
  if (run === "all") return rs[rs.length - 1];
  return rs.filter((r) => r.run_number === run).pop() ?? rs.filter((r) => r.run_number <= run).pop();
}

/** How an attack was answered (one response per attack: a concession wins over a defense). */
export function responseTo(t: TrialState, a: Attack, finished: boolean):
  { kind: ResponseKind; defense?: Defense; concession?: Concession } {
  const concession = t.concessions.find((c) => c.attack_id === a.attack_id);
  if (concession) return { kind: "concession", concession };
  const defense = t.defenses.find((d) => d.attack_id === a.attack_id);
  if (defense) return { kind: "defense", defense };
  if (t.invalidDefenses.some((e) => e.refs.includes(a.attack_id))) return { kind: "undefended" };
  return { kind: finished ? "undefended" : "awaiting" };
}

export function buildMap(t: TrialState, o: MapOptions): MapLayout {
  const inRun = (c: Claim) => o.run === "all" || c.run_number === o.run || (t.rulings[c.claim_id] ?? []).some((r) => r.run_number === o.run);
  const chosen = t.claims.filter((c) => (c.agent === "thor" || c.agent === "loki") && inRun(c) && (o.side === "both" || c.agent === o.side));
  const ids = new Set(chosen.map((c) => c.claim_id));
  const revisedBy = new Map<string, Claim[]>();
  for (const c of chosen) {
    if (c.revises_claim_id && ids.has(c.revises_claim_id)) revisedBy.set(c.revises_claim_id, [...(revisedBy.get(c.revises_claim_id) ?? []), c]);
  }

  const nodes: MapNode[] = [];
  const edges: MapEdge[] = [];
  const bands: MapLayout["bands"] = [];
  const C = { claim: col("claim"), attack: col("attack"), response: col("response"), ruling: col("ruling") };
  let y = 0;

  for (const agent of ["thor", "loki"] as const) {
    const roots = chosen.filter((c) => c.agent === agent && !(c.revises_claim_id && ids.has(c.revises_claim_id)))
      .sort((a, b) => a.run_number - b.run_number || natural(a.claim_id, b.claim_id));
    if (!roots.length) continue;
    // a revision sits directly under the claim it revises
    const ordered: Claim[] = [];
    const visit = (c: Claim) => {
      ordered.push(c);
      (revisedBy.get(c.claim_id) ?? []).sort((a, b) => natural(a.claim_id, b.claim_id)).forEach(visit);
    };
    roots.forEach(visit);
    bands.push({ agent, y, claims: ordered.length });
    y += BAND_HEAD;

    for (const c of ordered) {
      const lane = c.claim_id;
      const attacks = t.attacks.filter((a) => a.target_claim_id === lane && (o.run === "all" || a.run_number === o.run))
        .sort((a, b) => a.run_number - b.run_number || a.round_number - b.round_number || natural(a.attack_id, b.attack_id));
      const withdrawals = t.concessions.filter((k) => k.claim_id === lane && !k.attack_id && (o.run === "all" || k.run_number === o.run));
      const slots = Math.max(1, attacks.length + withdrawals.length);
      const laneH = slots * SLOT;
      const mid = (h: number) => y + (laneH - h) / 2;
      const inactive = t.concessions.some((k) => k.claim_id === lane && !k.attack_id) || t.claims.some((x) => x.revises_claim_id === lane);
      const claimId = `claim:${lane}`;
      nodes.push({ id: claimId, kind: "claim", lane, x: C.claim.x, y: mid(NODE_H), w: C.claim.w, h: NODE_H, claim: c, inactive });
      const ruling = rulingFor(t, lane, o.run);
      const rulingId = `ruling:${lane}`;
      nodes.push({ id: rulingId, kind: "ruling", lane, x: C.ruling.x, y: mid(NODE_H), w: C.ruling.w, h: NODE_H, ruling });
      if (c.revises_claim_id && ids.has(c.revises_claim_id)) {
        edges.push({ id: `rev:${lane}`, from: `claim:${c.revises_claim_id}`, to: claimId, kind: "revises" });
      }

      attacks.forEach((a, i) => {
        const sy = y + i * SLOT + (SLOT - NODE_H) / 2;
        const aid = `attack:${a.attack_id}`;
        const rid = `response:${a.attack_id}`;
        const r = responseTo(t, a, o.finished);
        nodes.push({ id: aid, kind: "attack", lane, x: C.attack.x, y: sy, w: C.attack.w, h: NODE_H, attack: a });
        nodes.push({ id: rid, kind: "response", lane, x: C.response.x, y: sy, w: C.response.w, h: NODE_H, attack: a,
          response: r.kind, defense: r.defense, concession: r.concession });
        edges.push({ id: `atk:${a.attack_id}`, from: claimId, to: aid, kind: "attacks" });
        edges.push({ id: `rsp:${a.attack_id}`, from: aid, to: rid, kind: "responds" });
        edges.push({ id: `rul:${a.attack_id}`, from: rid, to: rulingId, kind: "rules" });
      });
      withdrawals.forEach((k, j) => {
        const sy = y + (attacks.length + j) * SLOT + (SLOT - NODE_H) / 2;
        const rid = `response:${k.concession_id}`;
        nodes.push({ id: rid, kind: "response", lane, x: C.response.x, y: sy, w: C.response.w, h: NODE_H, response: "withdrawal", concession: k });
        edges.push({ id: `wd:${k.concession_id}`, from: claimId, to: rid, kind: "responds" });
        edges.push({ id: `wdr:${k.concession_id}`, from: rid, to: rulingId, kind: "rules" });
      });
      if (!attacks.length && !withdrawals.length) edges.push({ id: `rul:${lane}`, from: claimId, to: rulingId, kind: "rules" });
      y += laneH + LANE_GAP;
    }
    y += BAND_GAP;
  }
  const lanesBottom = Math.max(0, y - LANE_GAP - BAND_GAP);

  // documents: one node per document, placed level with what cites it
  const links = new Map<string, { to: string; kind: EdgeKind; ref: string }[]>();
  const link = (doc: string, to: string, kind: EdgeKind, ref: string) => {
    const l = links.get(doc) ?? [];
    if (!l.some((x) => x.to === to && x.kind === kind)) l.push({ to, kind, ref });
    else l.push({ to: "", kind, ref }); // same node, another paragraph: keep the ref, no extra edge
    links.set(doc, l);
  };
  const refOf = (c: { doc_id: string; paragraph_ref: string | null; row_id: string | null }) =>
    c.row_id ? c.row_id.replace(/^.*#/, "") : c.paragraph_ref ?? "";
  for (const n of nodes) {
    if (n.kind === "claim") n.claim!.citations.forEach((c) => link(c.doc_id, n.id, "cites", refOf(c)));
    if (n.kind === "attack") n.attack!.counter_evidence.forEach((c) => link(c.doc_id, n.id, "counter", refOf(c)));
    if (n.kind === "response" && n.defense) n.defense.new_evidence.forEach((c) => link(c.doc_id, n.id, "new", refOf(c)));
  }
  const centre = new Map(nodes.map((n) => [n.id, n.y + n.h / 2]));
  const D = col("doc");
  const docs = [...links.entries()].map(([doc, ls]) => {
    const real = ls.filter((l) => l.to);
    const w = real.map((l) => (l.kind === "cites" ? 1 : 0.4));
    const want = real.reduce((s, l, i) => s + centre.get(l.to)! * w[i], 0) / Math.max(1e-9, w.reduce((a, b) => a + b, 0)) - DOC_H / 2;
    return { doc, ls: real, refs: [...new Set(ls.map((l) => l.ref).filter(Boolean))].sort(natural), want };
  }).sort((a, b) => a.want - b.want || natural(a.doc, b.doc));
  // no overlaps: push down, then pull back up from the bottom if the column ran past the lanes
  const ys = docs.map((d) => d.want);
  for (let i = 0; i < ys.length; i++) ys[i] = Math.max(ys[i], i ? ys[i - 1] + DOC_STEP : 0, 0);
  const floor = Math.max(lanesBottom, ys.length * DOC_STEP) - DOC_H;
  for (let i = ys.length - 1; i >= 0; i--) ys[i] = Math.min(ys[i], i === ys.length - 1 ? floor : ys[i + 1] - DOC_STEP);
  for (let i = 0; i < ys.length; i++) ys[i] = Math.max(ys[i], i ? ys[i - 1] + DOC_STEP : 0);
  docs.forEach((d, i) => {
    const id = `doc:${d.doc}`;
    nodes.push({ id, kind: "doc", lane: null, x: D.x, y: ys[i], w: D.w, h: DOC_H, doc: d.doc, refs: d.refs });
    d.ls.forEach((l, j) => edges.push({ id: `${l.kind}:${d.doc}:${l.to}:${j}`, from: id, to: l.to, kind: l.kind }));
  });

  const height = Math.max(lanesBottom, ...nodes.map((n) => n.y + n.h), 0);
  return { nodes, edges, cols: MAP_COLS, bands, width: MAP_WIDTH, height };
}

/** Everything connected to one node: its whole lane (claim, attacks, responses, ruling) and the
 *  documents those cite; for a document, every lane that uses it. Null when nothing is in focus. */
export function focusOf(m: MapLayout, id: string | null): Set<string> | null {
  if (!id) return null;
  const n = m.nodes.find((x) => x.id === id);
  if (!n) return null;
  const byId = new Map(m.nodes.map((x) => [x.id, x]));
  const lanes = new Set<string>();
  if (n.kind === "doc") m.edges.filter((e) => e.from === id).forEach((e) => lanes.add(byId.get(e.to)?.lane ?? ""));
  else lanes.add(n.lane!);
  const set = new Set<string>([id]);
  for (const x of m.nodes) if (x.lane && lanes.has(x.lane)) set.add(x.id);
  if (n.kind !== "doc") for (const e of m.edges) if (e.from.startsWith("doc:") && set.has(e.to)) set.add(e.from);
  return set;
}
