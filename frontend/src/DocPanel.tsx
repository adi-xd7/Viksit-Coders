import { useEffect, useRef, useState } from "react";
import { api, splitRow } from "./api";
import { Badge, ErrorBox, Loading, TierBadge } from "./ui";

export interface DocTarget {
  doc_id: string;
  paragraph_ref?: string | null;
  row_id?: string | null;
}

/** Side panel: the cited document (as_of-gated through the case) with the cited paragraph or trade row highlighted. */
export function DocPanel({ target, caseId, onClose }: { target: DocTarget; caseId: string; onClose: () => void }) {
  const [doc, setDoc] = useState<any>(null);
  const [table, setTable] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  const [showOriginal, setShowOriginal] = useState(false);
  const hl = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    setDoc(null);
    setTable(null);
    setErr(null);
    api.doc(target.doc_id, caseId).then(setDoc).catch((e) => setErr(e.message));
    if (target.row_id) api.table(splitRow(target.row_id)[0], caseId).then(setTable).catch((e) => setErr(e.message));
  }, [target.doc_id, target.row_id, caseId]);

  useEffect(() => {
    hl.current?.scrollIntoView({ block: "center" });
  }, [doc, table]);

  return (
    <aside className="fixed right-0 top-0 z-20 flex h-full w-[520px] max-w-full flex-col border-l border-slate-300 bg-white shadow-xl">
      <div className="flex items-center justify-between border-b p-3">
        <div className="font-mono text-sm">
          {target.doc_id}{target.paragraph_ref ? ` / ${target.paragraph_ref}` : ""}{target.row_id ? ` / ${target.row_id}` : ""}
        </div>
        <button onClick={onClose} className="rounded border px-2 text-sm">Close</button>
      </div>
      <div className="flex-1 overflow-y-auto p-3 text-sm">
        {err && <ErrorBox>{err}</ErrorBox>}
        {!doc && !err && <Loading what="document" />}
        {doc && (
          <>
            <h3 className="font-semibold">{doc.title}</h3>
            <div className="mt-1 flex flex-wrap gap-1 text-xs">
              <TierBadge tier={doc.reliability_tier} />
              <Badge>{doc.source_type}</Badge>
              <Badge>{doc.source_name}</Badge>
              <Badge>published {doc.pub_date}{doc.pub_time ? ` ${String(doc.pub_time).slice(0, 5)}` : ""}</Badge>
              <Badge>{doc.format}</Badge>
              {doc.damage.map((d: string) => <Badge key={d} tone="red">{d}</Badge>)}
              {doc.relations.map((r: string) => <Badge key={r} tone="amber">{r}</Badge>)}
            </div>
            <div className="mt-1 break-all font-mono text-[10px] text-slate-400">sha256 {doc.content_sha256}</div>
            {doc.injection_flags.length > 0 && (
              <div className="mt-2 rounded border border-rose-300 bg-rose-50 p-2 text-xs text-rose-900">
                ⚠ {doc.injection_flags.length} suspicious span(s) flagged as possible embedded instructions; withheld from the agents.
                <label className="ml-2"><input type="checkbox" checked={showOriginal} onChange={(e) => setShowOriginal(e.target.checked)} /> show original text</label>
              </div>
            )}
            <div className="mt-3 space-y-2">
              {doc.paragraphs.map((p: any) => {
                const on = target.paragraph_ref === p.ref;
                return (
                  <div key={p.ref} id={p.anchor} ref={on ? hl : undefined}
                    className={`rounded p-2 ${on ? "bg-yellow-100 ring-2 ring-yellow-400" : ""} ${p.injection_flagged ? "border border-rose-300" : ""}`}>
                    <span className="mr-1 font-mono text-xs text-slate-400">[{p.ref}]</span>
                    {showOriginal && p.original_text ? <span className="text-rose-800">{p.original_text}</span> : p.text}
                  </div>
                );
              })}
            </div>
            {target.row_id && (
              <div className="mt-4">
                <h4 className="mb-1 text-xs font-semibold uppercase text-slate-600">Trade table {table?.table?.table_id}</h4>
                {!table && !err && <Loading what="trade rows" />}
                {table && (
                  <table className="w-full text-xs">
                    <thead><tr className="text-left text-slate-500"><th>row</th><th>period</th><th>value</th><th>volume</th><th>status</th></tr></thead>
                    <tbody>
                      {table.rows.map((r: any) => {
                        const on = r.row_id === target.row_id;
                        return (
                          <tr key={r.row_id} ref={on ? (el) => { hl.current = el as any; } : undefined}
                            className={on ? "bg-yellow-100 font-semibold" : r.status !== "valid" ? "text-rose-700" : ""}>
                            <td className="font-mono">{r.row_id.split("#").pop()}</td><td>{r.period}</td>
                            <td>{r.value ?? "missing"} {r.value != null ? `${r.currency} M` : ""}</td>
                            <td>{r.volume ?? "missing"} {r.volume != null ? r.volume_unit : ""}</td>
                            <td>{r.status}{r.damage_reason ? `: ${r.damage_reason}` : ""}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                )}
              </div>
            )}
          </>
        )}
      </div>
    </aside>
  );
}
