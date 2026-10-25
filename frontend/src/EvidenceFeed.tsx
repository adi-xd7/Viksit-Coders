import { useEffect, useState } from "react";
import { api, FeedItem } from "./api";
import type { TrialState } from "./useCase";
import { Badge, Empty, ErrorBox, Loading, OpenRef, TierBadge } from "./ui";

/** Documents published on or before the case's as-of date, newest first, with their badges.
 * Documents the agents actually retrieved in this case are marked with run and agents. */
export function EvidenceFeed({ asOf, trial, open }: { asOf?: string; trial: TrialState; open: OpenRef }) {
  const [items, setItems] = useState<FeedItem[] | null>(null);
  const [withheld, setWithheld] = useState(0);
  const [err, setErr] = useState<string | null>(null);
  const [onlyRetrieved, setOnlyRetrieved] = useState(true);

  useEffect(() => {
    if (!asOf) return;
    setItems(null);
    setErr(null);
    api.feed(asOf).then((f) => {
      setItems(f.items);
      setWithheld(f.withheld_after_as_of);
    }).catch((e) => setErr(e.message));
  }, [asOf]);

  if (!asOf) return <Empty>Start or open a case to see its evidence feed.</Empty>;
  if (err) return <ErrorBox>Feed unavailable: {err}</ErrorBox>;
  if (!items) return <Loading what="evidence feed" />;
  const shown = onlyRetrieved ? items.filter((i) => trial.retrievedDocs.has(i.doc_id)) : items;

  return (
    <div>
      <div className="mb-2 flex items-center justify-between text-xs text-slate-600">
        <span>
          {trial.retrievedDocs.size} retrieved · {items.length} in window · {withheld} withheld (after as-of)
        </span>
        <label className="flex items-center gap-1">
          <input type="checkbox" checked={onlyRetrieved} onChange={(e) => setOnlyRetrieved(e.target.checked)} />
          retrieved only
        </label>
      </div>
      {shown.length === 0 && <Empty>{onlyRetrieved ? "No documents retrieved yet." : "No documents in the window."}</Empty>}
      <ul className="space-y-1">
        {shown.map((i) => {
          const r = trial.retrievedDocs.get(i.doc_id);
          const b = i.badges;
          return (
            <li key={i.doc_id}>
              <button onClick={() => open({ doc_id: i.doc_id })}
                className={`w-full rounded border p-2 text-left text-xs hover:bg-slate-50 ${r ? "border-indigo-200 bg-white" : "border-slate-200 bg-slate-50"}`}>
                <div className="flex items-center gap-1">
                  <TierBadge tier={i.reliability_tier} />
                  <span className="font-mono text-slate-500">{i.doc_id}</span>
                  <span className="ml-auto text-slate-500">{i.pub_date}{i.pub_time ? ` ${i.pub_time.slice(0, 5)}` : ""}</span>
                </div>
                <div className="mt-0.5 font-medium text-slate-800">{i.title}</div>
                <div className="mt-1 flex flex-wrap gap-1">
                  <Badge>{i.source_type}</Badge>
                  {b.injection.length > 0 && <Badge tone="red" title="suspicious embedded instructions flagged">⚠ suspicious ({b.injection.join(",")})</Badge>}
                  {b.damaged.map((d) => <Badge key={d} tone="red">damaged: {d}</Badge>)}
                  {b.corrected_by.length > 0 && <Badge tone="amber">corrected by {b.corrected_by.join(", ")}</Badge>}
                  {b.corrects.length > 0 && <Badge tone="amber">correction of {b.corrects.join(", ")}</Badge>}
                  {b.duplicate_of.length > 0 && <Badge tone="slate">duplicate of {b.duplicate_of.join(", ")}</Badge>}
                  {b.near_duplicate_of.length > 0 && <Badge tone="slate">near-duplicate of {b.near_duplicate_of.join(", ")}</Badge>}
                  {r && <Badge tone="blue">retrieved run {[...r.runs].join(",")} by {[...r.agents].join(", ")}</Badge>}
                </div>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
