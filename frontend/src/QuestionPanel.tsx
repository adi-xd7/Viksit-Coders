import { useState } from "react";
import { api, CaseStatus } from "./api";
import { Badge, ErrorBox } from "./ui";

const STATUS_TONE: Record<string, string> = { running: "blue", complete: "green", partial: "amber", failed: "red" };

export function QuestionPanel({ status, onCase, transport, eventCount, error }: {
  status: CaseStatus | null;
  onCase: (id: string) => void;
  transport: string;
  eventCount: number;
  error: string | null;
}) {
  const [question, setQuestion] = useState("");
  const [asOf, setAsOf] = useState("");
  const [openId, setOpenId] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const start = async () => {
    setBusy(true);
    setErr(null);
    try {
      const r = await api.createCase(question.trim(), asOf);
      onCase(r.case_id);
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };
  const running = status?.status === "running";

  return (
    <div className="border-b border-slate-200 bg-white px-4 py-3">
      <div className="flex flex-wrap items-end gap-2">
        <label className="flex min-w-[320px] flex-1 flex-col text-xs font-medium text-slate-600">
          Question
          <textarea
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            rows={2}
            placeholder="e.g. As of <date>, how exposed are <countries> to <event>? Give a low and high range for <sectors>."
            className="mt-1 rounded border border-slate-300 p-2 text-sm text-slate-900"
          />
        </label>
        <label className="flex flex-col text-xs font-medium text-slate-600">
          As-of date
          <input type="date" value={asOf} onChange={(e) => setAsOf(e.target.value)}
            className="mt-1 rounded border border-slate-300 p-2 text-sm text-slate-900" />
        </label>
        <button
          onClick={start}
          disabled={busy || running || question.trim().length < 5 || !asOf}
          className="rounded bg-indigo-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-40"
        >
          {busy ? "Starting…" : "Start investigation"}
        </button>
        <div className="flex items-end gap-1">
          <label className="flex flex-col text-xs font-medium text-slate-600">
            or open a saved case
            <input value={openId} onChange={(e) => setOpenId(e.target.value)} placeholder="case-…"
              className="mt-1 w-64 rounded border border-slate-300 p-2 font-mono text-xs" />
          </label>
          <button onClick={() => openId.trim() && onCase(openId.trim())}
            className="rounded border border-slate-300 px-3 py-2 text-sm">Open</button>
        </div>
      </div>
      {err && <div className="mt-2"><ErrorBox>Could not start the case: {err}</ErrorBox></div>}
      {status && (
        <div className="mt-2 flex flex-wrap items-center gap-2 text-sm">
          <span className="font-mono text-xs text-slate-500">{status.case_id}</span>
          <Badge tone={STATUS_TONE[status.status]}>{status.status.toUpperCase()}</Badge>
          <span className="text-slate-600">stage <b>{status.stage}</b></span>
          {status.briefing_status && <span className="text-slate-600">briefing <b>{status.briefing_status}</b></span>}
          {status.as_of && <span className="text-slate-600">as of <b>{status.as_of}</b></span>}
          <span className="text-slate-500">· {eventCount} recorded events · live via {transport}</span>
          {status.question && <div className="w-full truncate text-slate-700" title={status.question}>“{status.question}”</div>}
          {status.history && status.history.length > 0 && (
            <div className="w-full text-xs text-slate-500">path: {status.history.join(" → ")}</div>
          )}
          {status.stop_reason && <div className="w-full"><ErrorBox>Stopped: {status.stop_reason}</ErrorBox></div>}
        </div>
      )}
      {error && <div className="mt-2"><ErrorBox>Case status unavailable: {error}</ErrorBox></div>}
    </div>
  );
}
