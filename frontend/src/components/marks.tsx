import type { Agent, Verdict as V } from "../api";
import { cap, citeLabel } from "../lib/format";

/** One shared verdict mark: the shape carries the state (filled, half, hollow grey, red square). */
export function Verdict({ v, run, showLabel = true }: { v: V | "unruled"; run?: number; showLabel?: boolean }) {
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap text-xs text-ink-2">
      <span className={`glyph glyph-${v}`} aria-hidden="true" />
      {showLabel ? <span>{v === "unruled" ? "not ruled" : v}</span> : <span className="sr-only">{v}</span>}
      {run ? <span className="text-ink-3">· run {run}</span> : null}
    </span>
  );
}

export function ClaimType({ t }: { t: "fact" | "inference" }) {
  return <span className="text-xs text-ink-3">{t}</span>;
}

const AGENT_NAME: Record<string, string> = { thor: "Thor", loki: "Loki", odin: "Odin", heimdall: "Heimdall", system: "System", user: "User" };
export const agentName = (a: Agent | string) => AGENT_NAME[a] ?? cap(a);

/** One shared agent mark: Thor solid ink bar, Loki outlined bar, Odin accent bar. */
export function AgentMark({ agent, label = true }: { agent: Agent | string; label?: boolean }) {
  const known = ["thor", "loki", "odin", "heimdall"].includes(agent);
  return (
    <span className="inline-flex items-center gap-2">
      {known && <span className={`mark mark-${agent}`} aria-hidden="true" />}
      {label && <span>{agentName(agent)}</span>}
    </span>
  );
}

export type OpenRef = (r: { doc_id: string; paragraph_ref?: string | null; row_id?: string | null }) => void;

/** A citation link: opens the Evidence view with the document and the cited paragraph or row. */
export function Cite({ c, open, label }: { c: { doc_id: string; paragraph_ref?: string | null; row_id?: string | null; pub_date?: string; quote?: string }; open: OpenRef; label?: string }) {
  return (
    <button type="button" className="cite" onClick={() => open(c)}
      title={c.quote ? `“${c.quote}”${c.pub_date ? ` (${c.pub_date})` : ""}` : c.pub_date}>
      {label ?? citeLabel(c)}
    </button>
  );
}
