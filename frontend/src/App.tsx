import { useEffect, useState } from "react";
import { CaseForm } from "./components/CaseForm";
import { Alert, Skeleton, ViewHead } from "./components/layout";
import type { OpenRef } from "./components/marks";
import { pipeline, Rail, TopBar } from "./components/Shell";
import { useRoute, VIEW_LABEL } from "./lib/route";
import { useCase } from "./useCase";
import { EvidenceView, type DocTarget } from "./views/EvidenceView";
import { ExposureView } from "./views/ExposureView";
import { TraceView } from "./views/TraceView";
import { TrialView } from "./views/TrialView";

const INTRO: Record<string, string> = {
  exposure: "Low and high estimates per country and sector on one shared scale. Trade exposure is not a loss estimate.",
  evidence: "Documents by publication date. Anything after the as-of date is blocked in code and logged.",
  trace: "What Odin sent back, what changed between runs and why, and every recorded event.",
};

export default function App() {
  const [route, go] = useRoute();
  const { caseId, view } = route;
  const [target, setTarget] = useState<DocTarget | null>(null);
  const { status, events, error, trial, loaded } = useCase(caseId);

  useEffect(() => setTarget(null), [caseId]);
  useEffect(() => {
    document.title = caseId ? `${VIEW_LABEL[view]} · ${caseId} · Ragnarok` : "Ragnarok";
  }, [caseId, view]);

  // every citation opens the Evidence view with the document and the cited paragraph or row
  const open: OpenRef = (r) => {
    setTarget({ doc_id: r.doc_id, paragraph_ref: r.paragraph_ref ?? null, row_id: r.row_id ?? null });
    if (view !== "evidence") {
      go({ view: "evidence" });
      window.scrollTo({ top: 0 });
    }
  };
  const onCase = (id: string) => go({ caseId: id, view: "trial" });
  const finished = !!status && status.status !== "running";
  const briefing = status?.results?.briefing ?? null;
  const failed = status?.status === "failed";

  let body: React.ReactNode;
  if (!caseId) {
    body = (
      <>
        <ViewHead title="New investigation">
          Ask a question and pick an as-of date. Heimdall investigates, Thor and Loki argue, Odin rules. Or open a saved case.
        </ViewHead>
        <CaseForm onCase={onCase} />
      </>
    );
  } else if (error && !status) {
    body = <Alert tone="bad" title="Case unavailable">{error}. Check the case ID, or that the API is running.</Alert>;
  } else if (!loaded) {
    body = <><ViewHead title={VIEW_LABEL[view]} /><Skeleton rows={6} label="Loading case" /></>;
  } else {
    body = (
      <>
        <ViewHead title={VIEW_LABEL[view]}>{view === "trial" ? undefined : INTRO[view]}</ViewHead>
        {failed && (
          <Alert tone="bad" title={status?.stage === "FAILED" ? "This case failed. No briefing was produced." : "This case was interrupted before it finished."}>
            {(status?.notes ?? []).slice(-3).map((n, i) => <span key={i} className="block">{n}</span>)}
            <span className="block">Partial results recorded before the failure are shown below.</span>
            {status?.limitations && (
              <details className="mt-1"><summary className="cursor-pointer">Limitation report</summary>
                <pre className="m-0 mt-1 whitespace-pre-wrap font-mono text-xs">{status.limitations}</pre></details>
            )}
          </Alert>
        )}
        {status?.stop_reason && <Alert title="The trial stopped">{status.stop_reason}</Alert>}
        {error && <Alert tone="bad" title="Live status unavailable">{error}. Showing what was recorded so far.</Alert>}
        {view === "trial" && <TrialView t={trial} open={open} question={status?.question} finished={finished} />}
        {view === "exposure" && <ExposureView table={briefing?.exposure_table} t={trial} open={open} finished={finished} />}
        {view === "evidence" && <EvidenceView asOf={status?.as_of} caseId={caseId} t={trial} target={target} open={open} />}
        {view === "trace" && <TraceView t={trial} events={events} briefing={briefing} md={status?.results?.briefing_markdown}
          open={open} status={status?.status} />}
      </>
    );
  }

  return (
    <div className="px-0 pb-10 pt-0 sm:px-4 sm:pt-5">
      <div className="mx-auto max-w-[1180px] overflow-hidden border-rule-2 bg-sheet sm:rounded-md sm:border">
        <TopBar status={status} caseId={caseId} trial={trial} onCase={onCase} />
        <div className="grid min-h-[640px] grid-cols-1 md:grid-cols-[200px_minmax(0,1fr)]">
          <Rail view={view} onView={(v) => go({ view: v })} stages={caseId && loaded ? pipeline(status, trial) : null} />
          <main key={view} className="view-in min-w-0 px-4 pb-8 pt-5 md:px-7 md:pb-10 md:pt-6">{body}</main>
        </div>
      </div>
    </div>
  );
}
