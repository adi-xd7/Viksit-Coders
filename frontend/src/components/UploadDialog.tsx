import { useId, useRef, useState } from "react";
import { api, type IngestSummary } from "../api";

const ACCEPT = ".zip,.pdf,.txt,.docx";

/** Add documents to the live index: a pack .zip (with manifest.json) or loose PDF / TXT / DOCX files.
 * Documents are untrusted data: they are parsed, flagged and indexed, never executed. */
export function UploadForm({ onDone }: { onDone: (r: IngestSummary) => void }) {
  const [files, setFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [res, setRes] = useState<IngestSummary | null>(null);
  const [over, setOver] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const id = useId();

  const pick = (list: FileList | null) => {
    const fs = Array.from(list ?? []);
    setRes(null);
    setErr(null);
    const zips = fs.filter((f) => f.name.toLowerCase().endsWith(".zip"));
    const bad = fs.filter((f) => !/\.(zip|pdf|txt|docx)$/i.test(f.name));
    if (bad.length) return setErr(`Not a supported file: ${bad.map((f) => f.name).join(", ")}. Use a pack .zip or PDF, TXT, DOCX documents.`);
    if (zips.length && fs.length > 1) return setErr("Upload a pack .zip on its own, or loose documents without a zip.");
    setFiles(fs);
  };
  const send = async () => {
    setBusy(true);
    setErr(null);
    try {
      const r = await api.ingest(files);
      setRes(r);
      setFiles([]);
      onDone(r);
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <p className="m-0 text-[13px] text-ink-2">
        A pack <span className="mono">.zip</span> with its <span className="mono">manifest.json</span>, or loose PDF, TXT and DOCX documents
        (each document's header supplies its metadata). They are added to the index at once; questions asked after this can use them.
      </p>
      <label htmlFor={`${id}-f`}
        onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
        onDrop={(e) => { e.preventDefault(); setOver(false); pick(e.dataTransfer.files); }}
        className={`mt-3 block cursor-pointer border border-dashed px-3 py-5 text-center text-[13px] ${over ? "border-accent bg-accent-wash" : "border-rule-2 hover:bg-paper"}`}>
        Drop files here, or <span className="text-accent underline underline-offset-4">choose files</span>
        <input id={`${id}-f`} ref={input} type="file" multiple accept={ACCEPT} className="sr-only"
          onChange={(e) => pick(e.target.files)} />
      </label>
      {files.length > 0 && (
        <ul className="m-0 mt-2 list-none p-0 text-[13px]">
          {files.map((f) => (
            <li key={f.name} className="flex justify-between gap-3 border-b border-rule py-1.5">
              <span className="mono break-all">{f.name}</span><span className="num text-ink-3">{(f.size / 1024).toFixed(0)} KB</span>
            </li>
          ))}
        </ul>
      )}
      <div className="mt-3 flex items-center gap-3">
        <button type="button" onClick={send} disabled={busy || !files.length}
          className="rounded-sm bg-ink px-4 py-1.5 font-medium text-sheet disabled:cursor-not-allowed disabled:opacity-40">
          {busy ? "Ingesting…" : `Add ${files.length || ""} ${files.length === 1 && files[0].name.toLowerCase().endsWith(".zip") ? "pack" : "document"}${files.length > 1 ? "s" : ""}`}
        </button>
        {files.length > 0 && !busy && (
          <button type="button" className="text-[13px] text-ink-2 hover:text-ink" onClick={() => { setFiles([]); if (input.current) input.current.value = ""; }}>Clear</button>
        )}
      </div>
      {err && <p role="alert" className="m-0 mt-3 text-[13px] text-bad">{err}</p>}
      {res && (
        <div role="status" className="mt-3 border-l-2 border-accent pl-3 text-[13px]">
          <div className="font-medium">Added to the index: {res.documents} document{res.documents === 1 ? "" : "s"}, {res.tables} trade
            table{res.tables === 1 ? "" : "s"} <span className="mono text-ink-3">({res.pack_id})</span></div>
          {(res.damaged > 0 || res.injection_flags > 0) && (
            <div className="text-bad">{res.damaged} damaged document{res.damaged === 1 ? "" : "s"} · {res.injection_flags} suspicious
              span{res.injection_flags === 1 ? "" : "s"} flagged (kept as data, never followed)</div>
          )}
          {[...res.errors, ...res.problems].slice(0, 8).map((p, i) => <div key={i} className="text-ink-2">{p}</div>)}
        </div>
      )}
    </div>
  );
}
