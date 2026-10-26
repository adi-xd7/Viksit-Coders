import { useCallback, useEffect, useState } from "react";

export const VIEWS = ["trial", "map", "exposure", "evidence", "briefing", "trace"] as const;
export type View = (typeof VIEWS)[number];
export const VIEW_LABEL: Record<View, string> = {
  trial: "Trial", map: "Argument map", exposure: "Exposure", evidence: "Evidence", briefing: "Briefing", trace: "Run trace",
};

export interface Route {
  caseId: string | null;
  view: View;
}

/** The hash holds the case and the view: "#case=<id>&view=exposure". A bare "#exposure" also works. */
export function parseHash(hash: string): Route {
  const h = hash.replace(/^#/, "");
  const params = new URLSearchParams(h.includes("=") ? h : "");
  const bare = h.includes("=") ? null : h;
  const caseId = params.get("case");
  const v = (params.get("view") ?? bare ?? "trial") as View;
  return { caseId: caseId && /^case-[A-Za-z0-9-]{1,80}$/.test(caseId) ? caseId : null, view: VIEWS.includes(v) ? v : "trial" };
}

export function toHash(r: Route): string {
  return r.caseId ? `#case=${r.caseId}&view=${r.view}` : `#${r.view}`;
}

export function useRoute(): [Route, (next: Partial<Route>) => void] {
  const [route, setRoute] = useState<Route>(() => parseHash(window.location.hash));
  useEffect(() => {
    const on = () => setRoute(parseHash(window.location.hash));
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  const go = useCallback((next: Partial<Route>) => {
    const cur = parseHash(window.location.hash);
    const r = { ...cur, ...next };
    if (toHash(r) !== window.location.hash) window.location.hash = toHash(r);
    setRoute(r);
  }, []);
  return [route, go];
}
