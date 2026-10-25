import { useId, useState } from "react";
import { api } from "../api";

/** Start an investigation (POST /cases) or open a saved case by ID. */
export function CaseForm({ onCase, running }: { onCase: (id: string) => void; running?: boolean }) {
  const [question, setQuestion] = useState("");
  const [asOf, setAsOf] = useState("");
  const [openId, setOpenId] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const id = useId();

  const start = async () => {
    setBusy(true);
    setErr(null);
    try {
      onCase((await api.createCase(question.trim(), asOf)).case_id);
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };
  const field = "mt-1 w-full rounded-sm border border-rule-2 bg-sheet px-2 py-1.5 text-ink";

  return (
    <div className="max-w-[720px]">
      <label htmlFor={`${id}-q`} className="label">Question</label>
      <textarea id={`${id}-q`} value={question} onChange={(e) => setQuestion(e.target.value)} rows={3} className={field}
        placeholder="As of <date>, how exposed are <countries> to <event>? Give a low and high range for <sectors>." />
      <div className="mt-3 flex flex-wrap items-end gap-3">
        <div>
          <label htmlFor={`${id}-d`} className="label">As-of date</label>
          <input id={`${id}-d`} type="date" value={asOf} onChange={(e) => setAsOf(e.target.value)} className={`${field} num`} />
        </div>
        <button type="button" onClick={start} disabled={busy || running || question.trim().length < 5 || !asOf}
          className="rounded-sm bg-ink px-4 py-1.5 font-medium text-sheet disabled:cursor-not-allowed disabled:opacity-40">
          {busy ? "Starting…" : "Start investigation"}
        </button>
        {running && <span className="text-[13px] text-ink-2">A case is running; one case at a time.</span>}
      </div>
      {err && <p role="alert" className="mt-2 text-[13px] text-bad">Could not start the case. {err}</p>}
      <div className="mt-6 border-t border-rule pt-4">
        <label htmlFor={`${id}-o`} className="label">Open a saved case</label>
        <div className="mt-1 flex flex-wrap gap-2">
          <input id={`${id}-o`} value={openId} onChange={(e) => setOpenId(e.target.value)} placeholder="case-…"
            className="mono w-72 max-w-full rounded-sm border border-rule-2 px-2 py-1.5"
            onKeyDown={(e) => e.key === "Enter" && openId.trim() && onCase(openId.trim())} />
          <button type="button" onClick={() => openId.trim() && onCase(openId.trim())}
            className="rounded-sm border border-rule-2 px-3 py-1.5 hover:bg-paper">Open</button>
        </div>
      </div>
    </div>
  );
}
