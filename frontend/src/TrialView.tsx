import type { Attack, Claim } from "./api";
import type { TrialState } from "./useCase";
import { AGENT_COLOR, Badge, Cite, Empty, OpenRef, TypeTag, VerdictChip } from "./ui";

function Thread({ a, t, open }: { a: Attack; t: TrialState; open: OpenRef }) {
  const defense = t.defenses.filter((d) => d.attack_id === a.attack_id);
  const concession = t.concessions.filter((c) => c.attack_id === a.attack_id);
  const invalid = t.invalidDefenses.filter((e) => e.refs.includes(a.attack_id));
  return (
    <div className="ml-3 mt-1 border-l-2 border-slate-200 pl-2 text-xs">
      <div>
        <span className={`font-semibold ${AGENT_COLOR[a.attacker]}`}>{a.attacker}</span> attacks ({a.attack_id}
        {a.round_number > 1 ? `, round ${a.round_number}` : ""}): {a.objection}
        <div className="text-slate-500">why it matters: {a.why_it_matters}</div>
        {a.evidence_gap && <div className="text-slate-500">evidence gap: {a.evidence_gap}</div>}
        {a.counter_evidence.map((c, i) => <Cite key={i} c={c} open={open} />)}
      </div>
      {defense.map((d) => (
        <div key={d.defense_id} className="mt-1 rounded bg-emerald-50 p-1">
          <b className={AGENT_COLOR[d.defender]}>{d.defender}</b> defends with new evidence: {d.argument}
          {d.new_evidence.map((c, i) => <Cite key={i} c={c} open={open} />)}
        </div>
      ))}
      {concession.map((c) => (
        <div key={c.concession_id} className="mt-1 rounded bg-sky-50 p-1">
          <b className={AGENT_COLOR[c.agent]}>{c.agent}</b> concedes ({c.partial ? "partial" : "full"}): {c.reason}
          {c.revised_claim_text && <div className="text-slate-600">revised claim: {c.revised_claim_text}</div>}
        </div>
      ))}
      {invalid.map((e) => <div key={e.seq} className="mt-1 rounded bg-rose-50 p-1 text-rose-800">invalid defense: {e.summary}</div>)}
      {!defense.length && !concession.length && !invalid.length && (
        <div className="mt-1 italic text-slate-400">no response recorded (yet)</div>
      )}
    </div>
  );
}

function ClaimCard({ c, t, open }: { c: Claim; t: TrialState; open: OpenRef }) {
  const rs = t.rulings[c.claim_id] ?? [];
  const latest = rs[rs.length - 1];
  const withdrawn = t.concessions.find((k) => k.claim_id === c.claim_id && !k.attack_id);
  const revisedBy = t.claims.find((x) => x.revises_claim_id === c.claim_id);
  return (
    <div className={`rounded border bg-white p-2 text-sm ${revisedBy || withdrawn ? "opacity-60" : ""}`}>
      <div className="flex flex-wrap items-center gap-1">
        <span className="font-mono text-xs font-semibold">{c.claim_id}</span>
        <TypeTag t={c.claim_type} />
        {c.country && <Badge>{c.country}/{c.sector}</Badge>}
        {c.revises_claim_id && <Badge tone="violet">revises {c.revises_claim_id}</Badge>}
        {revisedBy && <Badge tone="slate">superseded by {revisedBy.claim_id}</Badge>}
        {withdrawn && <Badge tone="slate">withdrawn in run {withdrawn.run_number}</Badge>}
        <span className="ml-auto flex gap-1">{rs.map((r) => <VerdictChip key={r.ruling_id + r.run_number} v={r.verdict} run={rs.length > 1 ? r.run_number : undefined} />)}</span>
      </div>
      <p className="mt-1">{c.text}</p>
      <div className="mt-1">{c.citations.map((x, i) => <Cite key={i} c={x} open={open} />)}</div>
      {c.exposure && (
        <div className="mt-1 text-xs text-slate-600">
          estimate: {c.exposure.low} – {c.exposure.high} {c.exposure.unit} · {c.exposure.metric} ({c.exposure.period})
        </div>
      )}
      {c.assumptions.length > 0 && <div className="mt-1 text-xs text-slate-500">assumptions: {c.assumptions.join("; ")}</div>}
      {latest && (
        <div className="mt-1 rounded bg-slate-50 p-1 text-xs text-slate-700">
          <b className="text-indigo-700">Odin</b> ({latest.claim_type}): {latest.rationale}
        </div>
      )}
      {t.attacks.filter((a) => a.target_claim_id === c.claim_id).map((a) => <Thread key={a.attack_id} a={a} t={t} open={open} />)}
    </div>
  );
}

export function TrialView({ t, open }: { t: TrialState; open: OpenRef }) {
  if (!t.claims.length) return <Empty>No claims recorded yet. Claims appear here as Thor and Loki submit them.</Empty>;
  const counts = Object.values(t.rulings).map((r) => r[r.length - 1].verdict);
  const tally = ["established", "contested", "conceded", "rejected"].map((v) => `${counts.filter((x) => x === v).length} ${v}`);
  return (
    <div>
      <div className="mb-2 text-xs text-slate-600">
        {t.claims.length} claims · {t.attacks.length} attacks · {t.defenses.length} defenses · {t.concessions.length} concessions
        · rulings: {tally.join(", ")}
      </div>
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        {(["thor", "loki"] as const).map((a) => (
          <div key={a}>
            <h3 className={`mb-1 font-semibold ${AGENT_COLOR[a]}`}>
              {a === "thor" ? "Thor — high exposure" : "Loki — limited exposure"}
            </h3>
            <div className="space-y-2">
              {t.claims.filter((c) => c.agent === a).map((c) => <ClaimCard key={c.claim_id} c={c} t={t} open={open} />)}
              {!t.claims.some((c) => c.agent === a) && <Empty>No claims from {a}.</Empty>}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
