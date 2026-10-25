import { useEffect, useState } from "react";
import { BriefingView } from "./BriefingView";
import { DocPanel, DocTarget } from "./DocPanel";
import { EvidenceFeed } from "./EvidenceFeed";
import { ExposureView } from "./ExposureView";
import { QuestionPanel } from "./QuestionPanel";
import { TraceView } from "./TraceView";
import { TrialView } from "./TrialView";
import { useCase } from "./useCase";
import { Empty, OpenRef } from "./ui";

const TABS = ["Trial", "Exposure", "Briefing", "Trace"] as const;
type Tab = (typeof TABS)[number];

function caseFromHash(): string | null {
  const m = window.location.hash.match(/case=([A-Za-z0-9-]+)/);
  return m ? m[1] : null;
}

export default function App() {
  const [caseId, setCaseId] = useState<string | null>(caseFromHash());
  const [tab, setTab] = useState<Tab>("Trial");
  const [target, setTarget] = useState<DocTarget | null>(null);
  const { status, events, error, transport, trial } = useCase(caseId);

  useEffect(() => {
    if (caseId) window.history.replaceState(null, "", `#case=${caseId}`);
  }, [caseId]);

  const open: OpenRef = (r) => setTarget({ doc_id: r.doc_id, paragraph_ref: r.paragraph_ref ?? null, row_id: r.row_id ?? null });
  const briefing = status?.results?.briefing ?? null;

  return (
    <div className="min-h-screen">
      <header className="flex items-baseline gap-3 bg-slate-900 px-4 py-2 text-white">
        <h1 className="text-lg font-semibold">Trial of the Nine Realms</h1>
        <span className="text-xs text-slate-300">Heimdall investigates · Thor and Loki argue · Odin rules — every item below is a recorded event</span>
      </header>
      <QuestionPanel status={status} onCase={(id) => { setCaseId(id); setTarget(null); }} transport={transport}
        eventCount={events.length} error={error} />
      {!caseId ? (
        <div className="p-6"><Empty>Ask a question and pick an as-of date to start an investigation, or open a saved case.</Empty></div>
      ) : (
        <div className="grid grid-cols-1 gap-4 p-4 lg:grid-cols-[360px_1fr]">
          <div className="max-h-[calc(100vh-180px)] overflow-y-auto">
            <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-600">Evidence feed</h2>
            <EvidenceFeed asOf={status?.as_of} trial={trial} open={open} />
          </div>
          <div>
            <nav className="mb-3 flex gap-1 border-b">
              {TABS.map((t) => (
                <button key={t} onClick={() => setTab(t)}
                  className={`-mb-px border-b-2 px-3 py-1.5 text-sm ${tab === t ? "border-indigo-600 font-semibold text-indigo-700" : "border-transparent text-slate-600"}`}>
                  {t}
                </button>
              ))}
            </nav>
            {tab === "Trial" && <TrialView t={trial} open={open} />}
            {tab === "Exposure" && <ExposureView table={briefing?.exposure_table} claims={trial.claims} />}
            {tab === "Briefing" && (
              status?.status === "running" ? <Empty>The briefing is written when the trial finishes.</Empty>
                : <BriefingView b={briefing} md={status?.results?.briefing_markdown} open={open} />
            )}
            {tab === "Trace" && <TraceView events={events} briefing={briefing} open={open} />}
            {status?.limitations && (
              <pre className="mt-4 whitespace-pre-wrap rounded border border-rose-300 bg-rose-50 p-3 text-xs">{status.limitations}</pre>
            )}
          </div>
        </div>
      )}
      {target && caseId && <DocPanel target={target} caseId={caseId} onClose={() => setTarget(null)} />}
    </div>
  );
}
