// API client + types. Everything shown in the UI comes from these endpoints; nothing is simulated.

export type Agent = "heimdall" | "thor" | "loki" | "odin" | "system" | "user";
export type Verdict = "established" | "contested" | "conceded" | "rejected";

export interface LogEvent {
  seq: number;
  case_id: string;
  run_number: number;
  ts: string;
  agent: Agent;
  type: string;
  summary: string;
  payload: Record<string, any>;
  refs: string[];
}

export interface Citation {
  doc_id: string;
  paragraph_ref: string | null;
  row_id: string | null;
  pub_date: string;
  quote: string;
}

export interface Estimate {
  agent: Agent;
  country: string;
  sector: string;
  metric: string;
  metric_definition: string;
  unit: string;
  period: string;
  denominator: string | null;
  low: number;
  high: number;
  trade_row_refs: string[];
  calculation_ids: string[];
  assumptions: string[];
  missing_data: string[];
  confidence: string;
  uncertainty_note: string;
}

export interface Claim {
  claim_id: string;
  run_number: number;
  agent: Agent;
  text: string;
  country: string | null;
  sector: string | null;
  claim_type: "fact" | "inference";
  citations: Citation[];
  assumptions: string[];
  exposure: Estimate | null;
  limitations: string[];
  revises_claim_id?: string | null;
}

export interface Attack {
  attack_id: string;
  run_number: number;
  round_number: number;
  attacker: Agent;
  target_claim_id: string;
  objection: string;
  counter_evidence: Citation[];
  evidence_gap: string | null;
  why_it_matters: string;
}

export interface Defense {
  defense_id: string;
  attack_id: string;
  claim_id: string;
  defender: Agent;
  argument: string;
  new_evidence: Citation[];
  run_number: number;
}

export interface Concession {
  concession_id: string;
  claim_id: string;
  attack_id: string | null;
  agent: Agent;
  reason: string;
  partial: boolean;
  revised_claim_text: string | null;
  run_number: number;
}

export interface Ruling {
  ruling_id: string;
  run_number: number;
  claim_id: string;
  verdict: Verdict;
  claim_type: "fact" | "inference";
  rationale: string;
  citations_valid: boolean;
  citation_issues: string[];
}

export interface ExposureRow {
  country: string;
  sector: string;
  thor: Estimate | null;
  loki: Estimate | null;
  odin: Estimate | null;
  unavailable?: Record<string, string>;
  note: string;
}

export interface Finding {
  claim_id: string;
  ruling_id: string;
  verdict: Verdict;
  claim_type: "fact" | "inference";
  text: string;
  citations: Citation[];
}

export interface RunSummary {
  run_number: number;
  claims: string[];
  verdicts: Record<string, string>;
  sufficient: boolean | null;
  sufficiency_reason: string;
  sendback_missing: string[];
  new_evidence: string[];
  note: string;
}

export interface Briefing {
  case_id: string;
  as_of: string;
  status: "complete" | "partial" | "incomplete";
  runs_completed: number;
  executive_summary: string;
  event_status: string;
  event_citations: Citation[];
  established: Finding[];
  contested: Finding[];
  conceded: Finding[];
  rejected: Finding[];
  exposure_table: ExposureRow[];
  outlook: { text: string; assumptions: string[] };
  sources: { doc_id: string; title: string; pub_date: string; pub_time: string | null; source_name: string; reliability_tier: number | null }[];
  missing_data_notes: string[];
  evidence_quality_notes: string[];
  traps_and_failures: string[];
  assumptions?: string[];
  uncertainty?: string[];
  dropped_citations?: string[];
  runs?: RunSummary[];
  superseded?: string[];
}

export interface CaseStatus {
  case_id: string;
  status: "running" | "complete" | "partial" | "failed";
  stage: string;
  briefing_status?: string | null;
  question?: string;
  as_of?: string;
  history?: string[];
  runs_completed?: number;
  notes?: string[];
  stop_reason?: string | null;
  limitations?: string;
  results?: {
    briefing: Briefing | null;
    briefing_markdown: string | null;
    case_file: any;
    claims: any;
    cross_exam: any;
    rulings: any;
    runs: string[];
  };
}

export interface FeedItem {
  doc_id: string;
  title: string;
  pub_date: string;
  pub_time: string | null;
  source_name: string;
  source_type: string;
  reliability_tier: number | null;
  country: string | null;
  sector: string | null;
  badges: {
    tier: number | null;
    damaged: string[];
    notices: string[];
    injection: string[];
    corrects: string[];
    corrected_by: string[];
    duplicate_of: string[];
    near_duplicate_of: string[];
  };
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function json<T>(r: Response): Promise<T> {
  if (!r.ok) {
    let detail = r.statusText;
    try {
      const b = await r.json();
      detail = typeof b.detail === "string" ? b.detail : JSON.stringify(b.detail ?? b);
    } catch {
      /* not json */
    }
    throw new ApiError(r.status, `${r.status}: ${detail}`);
  }
  return r.json() as Promise<T>;
}

export const api = {
  health: () => fetch("/api/health").then((r) => json<any>(r)),
  createCase: (question: string, as_of: string) =>
    fetch("/cases", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ question, as_of }) })
      .then((r) => json<{ case_id: string }>(r)),
  getCase: (id: string) => fetch(`/cases/${encodeURIComponent(id)}`).then((r) => json<CaseStatus>(r)),
  feed: (as_of: string) => fetch(`/feed?as_of=${as_of}&limit=1000`).then((r) => json<{ items: FeedItem[]; withheld_after_as_of: number }>(r)),
  doc: (doc_id: string, case_id: string) => fetch(`/docs/${encodeURIComponent(doc_id)}?case_id=${case_id}`).then((r) => json<any>(r)),
  table: (table_id: string, case_id: string) => fetch(`/trade/${encodeURIComponent(table_id)}?case_id=${case_id}`).then((r) => json<any>(r)),
  // fallback when EventSource is unavailable: fetch the stored events after `after` and parse the SSE text
  eventsOnce: async (id: string, after: number): Promise<LogEvent[]> => {
    const r = await fetch(`/cases/${encodeURIComponent(id)}/events?follow=false&after=${after}`);
    if (!r.ok) throw new ApiError(r.status, `${r.status}: events`);
    return parseSse(await r.text());
  },
};

export function parseSse(text: string): LogEvent[] {
  const out: LogEvent[] = [];
  for (const block of text.split("\n\n")) {
    const data = block.split("\n").find((l) => l.startsWith("data: "));
    const ev = block.split("\n").find((l) => l.startsWith("event: "));
    if (!data || ev === "event: end") continue;
    try {
      const e = JSON.parse(data.slice(6));
      if (e && typeof e.seq === "number") out.push(e);
    } catch {
      /* ignore malformed block */
    }
  }
  return out;
}

export const EVENT_TYPES = [
  "QUERY", "RETRIEVED", "CLAIM", "ATTACK", "DEFENSE", "CONCESSION", "RULING", "SENDBACK", "MEMORY_READ", "MEMORY_WRITE",
  "MEMORY_APPLIED", "TRAP_INJECTION", "CLOCK_VIOLATION_BLOCKED", "LIMIT_HIT", "ERROR", "INGEST", "DAMAGED_INPUT",
  "RUN_START", "RUN_END", "BRIEFING", "CASE_FILE", "STAGE", "SUFFICIENCY", "PRECHECK", "RESEARCH_PLAN", "NEW_EVIDENCE",
];

/** Row IDs are "<table_id>#R<n>"; returns [table_id, row_id]. */
export function splitRow(row_id: string): [string, string] {
  const i = row_id.lastIndexOf("#");
  return [row_id.slice(0, i), row_id];
}
