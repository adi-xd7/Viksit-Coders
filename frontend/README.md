# Frontend — Ragnarok dashboard

React 18 + Vite 6 + TypeScript + Tailwind CSS 4. Every value the dashboard shows comes from the backend API
(case status, the recorded audit events, documents, trade rows, the evidence feed); nothing is simulated or
hard-coded. Light theme only.

## Run

```bash
# 1. backend (from the project root)
.venv/Scripts/python -m uvicorn ragnarok.api:app --app-dir backend --port 8000

# 2. frontend (from frontend/)
npm install
npm run dev          # http://localhost:5173  (proxies the API on 127.0.0.1:8000; override with RAGNAROK_API)
```

`npm run build` type-checks and writes `dist/` (not committed). `npm run typecheck` only type-checks.
Fonts are self-hosted from `@fontsource` packages, so the dashboard works offline.

## Layout and routing

Top bar (brand, case ID, as-of date, run status such as "Partial briefing · run 2 of 2", **New case**), a left rail
(view navigation + the **Pipeline** list built from the case status and events), and the main column. Below 768 px the
rail becomes a horizontal nav and the pipeline list is hidden.

Views are addressed by the URL hash: `#case=<id>&view=trial|exposure|evidence|trace`; a bare `#exposure` also works
(`src/lib/route.ts`). Without a case, the main column shows the start form (question + as-of date, or open a saved case).

| View | Built from |
|---|---|
| **Trial** | `CLAIM`, `ATTACK`, `DEFENSE`, `CONCESSION`, `RULING` events of the latest attempt: rulings ledger, Thor / Loki claim columns, cross-examination as Attack · Response · Odin (defense with new evidence, concession, invalid defense, undefended) |
| **Exposure** | the briefing's exposure table (or, while running, the advocates' submitted estimates): one shared scale per unit with nice ticks computed from the data; Thor / Loki / Odin lines; dashed "no estimate" with the recorded reason (missing is never drawn as zero); row details with metric definitions, unit / period / denominator, assumptions, missing data, trade-row refs and calculation records (from `RETRIEVED` trade_calc events) |
| **Evidence** | `GET /feed?as_of=` + `RETRIEVED` / `NEW_EVIDENCE` / `CLOCK_VIOLATION_BLOCKED` events: publication timeline with the as-of line, filters, document list, inline viewer (`GET /docs/{id}?case_id=`, `GET /trade/{table}?case_id=`) with the cited paragraph or row highlighted and flagged spans marked "withheld as instruction"; blocked documents show no content |
| **Run trace** | `SENDBACK`, `RESEARCH_PLAN`, `MEMORY_APPLIED`, `SUFFICIENCY`, `NEW_EVIDENCE` events and the run summaries: send-back, Heimdall's new queries, memory before / after, run comparison, the event list with type filters, then the full **Briefing** (findings with citations, Markdown view, .md / .json export) |

Every citation, anywhere, opens the Evidence view with that document and the cited paragraph (or trade row)
highlighted. Model-request bookkeeping (`LLM_USAGE`, `LLM_CACHE_HIT`) is never shown: no call or token meters.

## Design tokens (`src/index.css`)

| Token | Value | Use |
|---|---|---|
| `--paper` | `#F6F7F8` | page background, hover rows |
| `--sheet` | `#FFFFFF` | the working surface |
| `--ink` / `--ink-2` / `--ink-3` | `#15181C` / `#575F69` / `#8A929B` | text, secondary text, labels |
| `--rule` / `--rule-2` | `#E5E8EB` / `#D3D8DD` | 1px hairlines, borders |
| `--accent` (+ `--accent-wash`, `--accent-line`) | `#2B4C9B` | only citations, Odin's marks, the selected row, the as-of line, focus rings |
| `--bad` (+ `--bad-wash`) | `#B42318` | only rejected, flagged, failed and bad states |
| `--hl` | `#FFF3C4` | highlighted (cited) passage |

They are mapped into Tailwind's theme (`bg-paper`, `text-ink-2`, `border-rule`, `text-accent`, …). Fonts:
Hanken Grotesk (UI) and IBM Plex Mono (IDs, refs, numbers; `.num` adds tabular numerals). Rules: no cards,
shadows, gradients or pills; content is ruled rows; section headers are small uppercase labels over a 1px ink rule;
radius at most 6px.

## Shared components (`src/components/`)

- `marks.tsx`: `<Verdict>` (established = filled dot, contested = half dot, conceded = hollow grey dot, rejected = red
  square, plus "not ruled"), `<ClaimType>` (fact / inference), `<AgentMark>` (Thor solid ink bar, Loki outlined bar,
  Odin accent bar), `<Cite>` (citation link → Evidence view).
- `layout.tsx`: `<Section>`, `<ViewHead>`, `<Empty>`, `<Alert>`, `<Skeleton>`, `<Filters>` (aria-pressed toggles).
- `Shell.tsx`: `<TopBar>`, `<Rail>`, `pipeline()` (stage states from status + events), `runStatusText()`.
- `CaseForm.tsx`: start a case (`POST /cases`) or open a saved one.
- `ui/dialog.tsx`: the shadcn/ui Dialog pattern on `@radix-ui/react-dialog` (focus trap, Escape), restyled to the
  tokens (used for **New case**).

`src/useCase.ts` holds the live state of a case (status polling, SSE with a polling fallback) and `deriveTrial()`,
which turns the recorded events of the latest attempt into the trial state (a resumed case is not shown twice).

## Adding a view

1. Add its key and label in `src/lib/route.ts` (`VIEWS`, `VIEW_LABEL`).
2. Create `src/views/<Name>View.tsx`; read only from `useCase` data (status, events, `TrialState`) or the API client
   in `src/api.ts`; give it loading (`<Skeleton>`), empty (`<Empty>`) and error (`<Alert tone="bad">`) states.
3. Render it in `App.tsx` next to the others (and add an intro line in `INTRO` if it needs one).
4. Use the shared components for verdicts, agents and citations; keep wide tables inside their own
   `overflow-x-auto` container so the page never scrolls sideways at 400 px.
