import type { Attack, Claim, Verdict as V } from "../api";
import { Empty, Section } from "../components/layout";
import { AgentMark, agentName, ClaimType, Cite, OpenRef, Verdict } from "../components/marks";
import { latestRuling, type TrialState } from "../useCase";

const VERDICTS: V[] = ["established", "contested", "conceded", "rejected"];

/** Heimdall's Case File: the event check (with its reasons and citations) and what the trial is about. */
function CaseFileSection({ cf, open }: { cf: any; open: OpenRef }) {
  const status: string = cf.event_status ?? "unknown";
  const row = (label: string, value: React.ReactNode) => (
    <div className="grid grid-cols-1 gap-x-4 border-b border-rule py-2 sm:grid-cols-[150px_minmax(0,1fr)]">
      <span className="text-ink-3">{label}</span><span className="min-w-0">{value}</span>
    </div>
  );
  const list = (xs?: string[]) => (xs && xs.length ? xs.join(", ") : <span className="text-ink-3">none listed</span>);
  return (
    <Section title="Case file" right={`Heimdall${cf.run_number > 1 ? ` · updated for run ${cf.run_number}` : ""}`} className="mt-0 mb-6">
      {row("Event", (
        <span>
          <b className={`font-medium ${status === "disproved" ? "text-bad" : ""}`}>{status}</b>
          {cf.event_verification_notes ? <span className="text-ink-2"> · {cf.event_verification_notes}</span> : null}
          {(cf.event_citations ?? []).length > 0 && (
            <span className="ml-1 inline-flex flex-wrap gap-x-2.5">{cf.event_citations.map((c: any, i: number) => <Cite key={i} c={c} open={open} />)}</span>
          )}
        </span>
      ))}
      {row("Countries · sectors", <span>{list(cf.countries)} · {list(cf.sectors)}</span>)}
      {(cf.related_countries ?? []).length > 0 && row("Related countries", list(cf.related_countries))}
      {(cf.routes ?? []).length > 0 && row("Routes", list(cf.routes))}
      {row("Trade tables", (cf.trade_table_ids ?? []).length
        ? <span className="mono break-words">{cf.trade_table_ids.join(", ")}</span> : <span className="text-ink-3">none found</span>)}
      {row("Key documents", (cf.evidence_doc_ids ?? []).length
        ? <span className="flex flex-wrap gap-x-2.5">{cf.evidence_doc_ids.map((d: string) => <Cite key={d} c={{ doc_id: d }} open={open} />)}</span>
        : <span className="text-ink-3">none listed</span>)}
      {(cf.corrections ?? []).length > 0 && row("Corrections, rumours", (
        <ul className="m-0 list-disc pl-4 text-ink-2">{cf.corrections.map((c: string, i: number) => <li key={i}>{c}</li>)}</ul>
      ))}
      {row("Missing data", (cf.missing_data ?? []).length
        ? <ul className="m-0 list-disc pl-4 text-ink-2">{cf.missing_data.map((m: string, i: number) => <li key={i}>{m}</li>)}</ul>
        : <span className="text-ink-3">none listed</span>)}
    </Section>
  );
}

function ClaimRow({ c, t, open }: { c: Claim; t: TrialState; open: OpenRef }) {
  const rs = t.rulings[c.claim_id] ?? [];
  const latest = rs[rs.length - 1];
  const withdrawn = t.concessions.find((k) => k.claim_id === c.claim_id && !k.attack_id);
  const revisedBy = t.claims.find((x) => x.revises_claim_id === c.claim_id);
  const inactive = Boolean(withdrawn || revisedBy);
  const notes = [
    c.revises_claim_id ? `Revises ${c.revises_claim_id}.` : "",
    revisedBy ? `Superseded by ${revisedBy.claim_id} in run ${revisedBy.run_number}.` : "",
    withdrawn ? `Withdrawn in run ${withdrawn.run_number}: ${withdrawn.reason}` : "",
  ].filter(Boolean);
  return (
    <li className={`border-b border-rule py-3 ${inactive ? "text-ink-2" : ""}`}>
      <div className="mb-0.5 flex justify-between gap-3 text-xs text-ink-3">
        <span><span className="mono">{c.claim_id}</span> · <ClaimType t={c.claim_type} />
          {c.country ? ` · ${c.country}${c.sector ? ` / ${c.sector}` : ""}` : ""}</span>
        {latest ? <Verdict v={latest.verdict} run={rs.length > 1 ? latest.run_number : undefined} />
          : <Verdict v="unruled" />}
      </div>
      <p className="m-0 mb-1.5">{c.text}</p>
      {c.citations.length > 0 && (
        <div className="flex flex-wrap gap-x-2.5 gap-y-1">
          {c.citations.map((x, i) => <Cite key={i} c={x} open={open} />)}
          {(c.exposure?.calculation_ids ?? c.calculation_ids ?? []).slice(0, 4).map((id: string) => (
            <span key={id} className="mono text-ink-3" title="calculation record">{id.slice(0, 11)}</span>
          ))}
        </div>
      )}
      {notes.map((n, i) => <p key={i} className="m-0 mt-1 text-xs text-ink-3">{n}</p>)}
    </li>
  );
}

function Side({ agent, claims, t, open }: { agent: "thor" | "loki"; claims: Claim[]; t: TrialState; open: OpenRef }) {
  return (
    <div className="min-w-0">
      <div className="flex items-baseline justify-between border-b border-ink pb-2">
        <strong className="font-semibold"><AgentMark agent={agent} /></strong>
        <span className="text-ink-3">{agent === "thor" ? "High exposure" : "Limited exposure"}</span>
      </div>
      {claims.length ? <ul aria-label={`${agentName(agent)} claims`} className="m-0 list-none p-0">{claims.map((c) => <ClaimRow key={c.claim_id} c={c} t={t} open={open} />)}</ul>
        : <Empty>No claims recorded from {agentName(agent)}.</Empty>}
    </div>
  );
}

function XRow({ a, t, open, finished }: { a: Attack; t: TrialState; open: OpenRef; finished: boolean }) {
  const defense = t.defenses.filter((d) => d.attack_id === a.attack_id);
  const concession = t.concessions.filter((c) => c.attack_id === a.attack_id);
  const invalid = t.invalidDefenses.filter((e) => e.refs.includes(a.attack_id));
  const target = t.claims.find((c) => c.claim_id === a.target_claim_id);
  const defender = target?.agent ?? (a.attacker === "thor" ? "loki" : "thor");
  const rulingsInRun = (t.rulings[a.target_claim_id] ?? []).filter((r) => r.run_number >= a.run_number);
  const ruling = rulingsInRun[0] ?? latestRuling(t, a.target_claim_id);
  return (
    <li className="grid grid-cols-1 gap-2 border-b border-rule py-3.5 md:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)_minmax(0,0.9fr)] md:gap-6">
      <div className="min-w-0">
        <div><span className="font-semibold">{agentName(a.attacker)}</span> on <span className="mono">{a.target_claim_id}</span>
          <span className="mono ml-2 text-ink-3">{a.attack_id}{a.round_number > 1 ? ` · round ${a.round_number}` : ""}</span></div>
        <p className="m-0 mt-0.5 text-ink-2">{a.objection}</p>
        {a.evidence_gap && <p className="m-0 mt-1 text-[13px] text-ink-3">Evidence gap: {a.evidence_gap}</p>}
        {a.counter_evidence.length > 0 && (
          <div className="mt-1 flex flex-wrap gap-x-2.5">{a.counter_evidence.map((c, i) => <Cite key={i} c={c} open={open} />)}</div>
        )}
      </div>
      <div className="min-w-0">
        <span className="label md:hidden">Response</span>
        {defense.map((d) => (
          <p key={d.defense_id} className="m-0">
            <span className="font-semibold">{agentName(d.defender)}</span> defends with new evidence{" "}
            {d.new_evidence.map((c, i) => <span key={i}><Cite c={c} open={open} />{" "}</span>)}
            <span className="text-ink-2">{d.argument}</span>
          </p>
        ))}
        {concession.map((c) => (
          <p key={c.concession_id} className="m-0">
            <span className="font-semibold">{agentName(c.agent)}</span> concedes{c.partial ? " in part" : ""}.{" "}
            <span className="text-ink-2">{c.reason}</span>
            {c.revised_claim_text && <span className="mt-1 block text-[13px] text-ink-3">Revised claim: {c.revised_claim_text}</span>}
          </p>
        ))}
        {invalid.map((e) => (
          <p key={e.seq} className="m-0">
            <span className="font-semibold">{agentName(defender)}</span> brings no new evidence. <span className="text-ink-2">Claim stays undefended.</span>
          </p>
        ))}
        {!defense.length && !concession.length && !invalid.length && (
          <p className="m-0 text-ink-2">{finished ? <>No response recorded. <b className="font-medium text-ink">Undefended.</b></> : "Awaiting a response."}</p>
        )}
      </div>
      <div className="min-w-0">
        <span className="label md:hidden">Odin</span>
        {ruling ? (
          <>
            <Verdict v={ruling.verdict} run={ruling.run_number !== a.run_number ? ruling.run_number : undefined} />
            <p className="m-0 mt-0.5 text-[13px] text-ink-2">{ruling.rationale}</p>
          </>
        ) : <p className="m-0 text-ink-3">{finished ? "No ruling recorded." : "Not ruled yet."}</p>}
      </div>
    </li>
  );
}

export function TrialView({ t, open, question, finished, caseFile, notes }: {
  t: TrialState; open: OpenRef; question?: string; finished: boolean; caseFile?: any; notes?: string[];
}) {
  const counts = Object.fromEntries(VERDICTS.map((v) => [v, 0])) as Record<V, number>;
  for (const c of t.claims) {
    const r = latestRuling(t, c.claim_id);
    if (r) counts[r.verdict] += 1;
  }
  const ruled = VERDICTS.reduce((n, v) => n + counts[v], 0);
  const thor = t.claims.filter((c) => c.agent === "thor");
  const loki = t.claims.filter((c) => c.agent === "loki");
  return (
    <>
      {question && <p className="m-0 mb-5 max-w-[68ch] text-ink-2">{question}</p>}
      {(t.caseFile ?? caseFile) && <CaseFileSection cf={t.caseFile ?? caseFile} open={open} />}
      {notes && notes.length > 0 && (
        <div className="mb-6 border-l-2 border-rule-2 pl-3 text-[13px] text-ink-2" role="note" aria-label="Trial notes">
          <div className="label mb-1">Trial notes</div>
          {notes.map((n, i) => <p key={i} className="m-0">{n}</p>)}
        </div>
      )}
      <div className="mb-1 flex flex-wrap gap-x-[18px] gap-y-1 text-xs text-ink-2" aria-label="Rulings summary">
        {VERDICTS.map((v) => (
          <span key={v} className="inline-flex items-center gap-1.5"><span className={`glyph glyph-${v}`} aria-hidden="true" />
            <span><span className="num">{counts[v]}</span> {v}</span></span>
        ))}
        {t.claims.length > ruled && <span className="text-ink-3">{t.claims.length - ruled} not ruled</span>}
      </div>
      {!t.claims.length ? <div className="mt-5"><Empty>{finished ? "No claims were recorded in this case." : "No claims yet. They appear here as Thor and Loki submit them."}</Empty></div> : (
        <div className="mt-5 grid grid-cols-1 gap-x-9 gap-y-6 md:grid-cols-2">
          <Side agent="thor" claims={thor} t={t} open={open} />
          <Side agent="loki" claims={loki} t={t} open={open} />
        </div>
      )}
      <Section title="Cross-examination" right="Each defense brings new evidence or concedes">
        <div className="label hidden grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)_minmax(0,0.9fr)] gap-6 pb-1.5 pt-2.5 md:grid">
          <span>Attack</span><span>Response</span><span>Odin</span>
        </div>
        {t.attacks.length ? <ul className="m-0 list-none p-0">{t.attacks.map((a) => <XRow key={a.attack_id} a={a} t={t} open={open} finished={finished} />)}</ul>
          : <Empty>{finished ? "No cross-examination attack was recorded in this case." : "No attacks yet."}</Empty>}
      </Section>
    </>
  );
}
