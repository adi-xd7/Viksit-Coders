import { useState } from "react";
import type { CaseStatus } from "../api";
import { fmtDate, fmtTime } from "../lib/format";
import { VIEW_LABEL, VIEWS, type View } from "../lib/route";
import type { TrialState } from "../useCase";
import { CaseForm } from "./CaseForm";
import { UploadForm } from "./UploadDialog";
import type { IngestSummary } from "../api";
import { Dialog, DialogContent, DialogTrigger } from "./ui/dialog";

const STAGE_LABEL: Record<string, string> = {
  START: "starting", HEIMDALL: "Heimdall", THOR_LOKI: "Thor and Loki", CROSS_EXAMINATION: "cross-examination",
  ODIN: "Odin", HEIMDALL_RESEARCH: "Heimdall's new research", BRIEFING: "briefing", DONE: "done", STOPPED: "stopped",
  FAILED: "failed",
};

/** "Partial briefing · run 2 of 2" etc., from the case status and recorded events only. */
export function runStatusText(status: CaseStatus | null, t: TrialState): { text: string; bad: boolean } {
  if (!status) return { text: "", bad: false };
  const run = t.runs.length ? Math.max(...t.runs) : 0;
  const runs = run ? ` · run ${run}${t.maxRuns ? ` of ${t.maxRuns}` : ""}` : "";
  const b = status.results?.briefing?.status ?? status.briefing_status;
  if (status.status === "running") return { text: `Running · ${STAGE_LABEL[status.stage] ?? status.stage}${runs}`, bad: false };
  if (status.status === "paused") {
    return { text: `Paused · daily model quota${runs}${status.paused_until ? ` · resumes after ${fmtTime(status.paused_until)}` : ""}`, bad: false };
  }
  if (status.status === "failed") {
    const at = (status.history ?? []).filter((h) => h !== "FAILED").pop() ?? status.stage;
    const interrupted = status.stage !== "FAILED";
    return { text: `${interrupted ? "Interrupted" : "Failed"} at ${STAGE_LABEL[at] ?? at}${runs} · no briefing`, bad: true };
  }
  if (status.stage === "STOPPED") return { text: `Stopped${status.stop_reason ? ": event disproved" : ""}`, bad: false };
  if (b) return { text: `${b[0].toUpperCase()}${b.slice(1)} briefing${runs}`, bad: false };
  return { text: `Finished without a briefing${runs}`, bad: false };
}

export function TopBar({ status, caseId, trial, onCase, onIngested }: {
  status: CaseStatus | null; caseId: string | null; trial: TrialState; onCase: (id: string) => void;
  onIngested: (r: IngestSummary) => void;
}) {
  const [open, setOpen] = useState(false);
  const [upload, setUpload] = useState(false);
  const btn = "no-print rounded-sm border border-rule-2 px-2.5 py-1 text-[13px] hover:bg-paper";
  const rs = runStatusText(status, trial);
  return (
    <header className="no-print flex min-h-12 flex-wrap items-center gap-x-5 gap-y-2 border-b border-rule px-4 py-2.5 md:px-5">
      <span className="font-semibold tracking-[-0.01em]">Ragnarok</span>
      {caseId && <span className="mono break-all text-ink-2">{caseId}</span>}
      {status?.as_of && <span className="text-ink-2">As of {fmtDate(status.as_of)}</span>}
      <span className="hidden flex-1 md:block" />
      {rs.text && <span className={rs.bad ? "font-medium text-bad" : "text-ink-2"} aria-live="polite">{rs.text}</span>}
      <Dialog open={upload} onOpenChange={setUpload}>
        <DialogTrigger className={btn}>Add documents</DialogTrigger>
        <DialogContent title="Add documents" description="Ingest a new event pack or loose documents into the index.">
          <UploadForm onDone={onIngested} />
        </DialogContent>
      </Dialog>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogTrigger className={`${btn} border-ink bg-ink text-sheet hover:bg-ink/90`}>Ask a question</DialogTrigger>
        <DialogContent title="Ask a question" description="Start an investigation, or open a saved case.">
          <CaseForm running={status?.status === "running"} onCase={(id) => { setOpen(false); onCase(id); }} />
        </DialogContent>
      </Dialog>
    </header>
  );
}

type StageState = "done" | "now" | "todo" | "failed";
interface PipeStage { key: string; title: string; detail: string; state: StageState }

const ORDER = ["HEIMDALL", "THOR_LOKI", "CROSS_EXAMINATION", "ODIN", "BRIEFING"];

export function pipeline(status: CaseStatus | null, t: TrialState): PipeStage[] {
  const cf = t.caseFile;
  const ruled = Object.keys(t.rulings).length;
  const b = status?.results?.briefing?.status ?? status?.briefing_status;
  const history = status?.history ?? [];
  const stage = status?.stage ?? "";
  const failedAt = status?.status === "failed" ? (history.filter((h) => h !== "FAILED").pop() ?? stage) : null;
  const pausedAt = status?.status === "paused" ? (history.filter((h) => h !== "PAUSED").pop() ?? "") : "";
  const cur = (stage === "PAUSED" ? pausedAt : stage) === "HEIMDALL_RESEARCH" ? "HEIMDALL" : stage === "PAUSED" ? pausedAt : stage;
  const items: [string, string, string][] = [
    ["HEIMDALL", "Heimdall", cf ? `Case file, ${(cf.evidence_doc_ids ?? []).length} documents, ${(cf.trade_table_ids ?? []).length} trade tables`
      : "No case file yet"],
    ["THOR_LOKI", "Thor and Loki", `${t.claims.length} claim${t.claims.length === 1 ? "" : "s"}`],
    ["CROSS_EXAMINATION", "Cross-examination", `${t.attacks.length} attack${t.attacks.length === 1 ? "" : "s"}`],
    ["ODIN", "Odin", `${ruled} ruling${ruled === 1 ? "" : "s"}${t.sendbacks.length ? `, ${t.sendbacks.length} send-back${t.sendbacks.length === 1 ? "" : "s"}` : ""}`],
    ["BRIEFING", "Briefing", b ? b[0].toUpperCase() + b.slice(1) : status?.status === "failed" ? "Not produced" : "Not issued"],
  ];
  return items.map(([key, title, detail]) => {
    let state: StageState = history.includes(key) ? "done" : "todo";
    if (key === "CROSS_EXAMINATION" && !history.includes(key) && history.includes("ODIN")) state = "todo";
    if ((status?.status === "running" || status?.status === "paused") && key === cur) state = "now";
    if (failedAt && (key === failedAt || (failedAt === "HEIMDALL_RESEARCH" && key === "HEIMDALL"))) state = "failed";
    if (key === "BRIEFING" && b) state = b === "complete" ? "done" : "now";
    return { key, title, detail, state };
  }).sort((a, b2) => ORDER.indexOf(a.key) - ORDER.indexOf(b2.key));
}

const TICK: Record<StageState, string> = {
  done: "rounded-full bg-ink",
  now: "rounded-full border-[1.5px] border-accent",
  todo: "rounded-full border-[1.5px] border-rule-2",
  failed: "rounded-[1px] bg-bad",
};

export function Rail({ view, onView, stages }: { view: View; onView: (v: View) => void; stages: PipeStage[] | null }) {
  return (
    <aside className="no-print flex flex-col gap-0 border-b border-rule px-3 py-2 md:gap-[22px] md:border-b-0 md:border-r md:px-3 md:py-4">
      <nav aria-label="Views" className="flex flex-row gap-px overflow-x-auto md:flex-col">
        {VIEWS.map((v) => (
          <button key={v} type="button" aria-current={view === v ? "page" : undefined} onClick={() => onView(v)}
            className={`whitespace-nowrap rounded-sm px-2.5 py-1.5 text-left ${view === v ? "bg-paper font-medium text-ink" : "text-ink-2 hover:bg-paper hover:text-ink"}`}>
            {VIEW_LABEL[v]}
          </button>
        ))}
      </nav>
      {stages && (
        <div className="hidden flex-col px-2.5 md:flex" aria-label="Pipeline">
          <div className="label mb-1.5">Pipeline</div>
          <ol className="m-0 list-none p-0">
            {stages.map((s) => (
              <li key={s.key} className="grid grid-cols-[14px_1fr] gap-2 py-[5px] text-xs text-ink-2">
                <span className={`mt-1.5 h-[7px] w-[7px] ${TICK[s.state]}`} aria-hidden="true" />
                <span>
                  <b className={`font-medium ${s.state === "failed" ? "text-bad" : "text-ink"}`}>{s.title}</b>
                  <span className="sr-only"> ({s.state === "now" ? "current" : s.state})</span>
                  <br />{s.detail}
                </span>
              </li>
            ))}
          </ol>
        </div>
      )}
    </aside>
  );
}
