# Frontend — Trial of the Nine Realms dashboard

React 18 + Vite 6 + TypeScript + Tailwind CSS 4. Every item the dashboard shows comes from the backend API
(case status, the recorded audit events, documents, trade rows, the evidence feed); nothing is simulated.

## Run

```bash
# 1. backend (from the project root)
.venv/Scripts/python -m uvicorn ragnarok.api:app --app-dir backend --port 8000

# 2. frontend (from frontend/)
npm install
npm run dev          # http://localhost:5173  (proxies the API on 127.0.0.1:8000; override with RAGNAROK_API)
```

`npm run build` type-checks and writes `dist/` (not committed). `npm run typecheck` only type-checks.

## Panels

- **Question**: question + as-of date → `POST /cases`; status (running / complete / partial / failed), stage, path.
  "Open" loads a saved case by ID (also kept in the URL as `#case=<id>`).
- **Evidence feed** (left): `GET /feed?as_of=` — documents published on or before the as-of date, newest first, with
  tier, correction / retraction, damaged, suspicious-content and duplicate badges; documents the agents retrieved in
  this case (from `RETRIEVED` events) are marked with run and agents.
- **Trial**: Thor and Loki claims side by side, fact / inference tags, Odin's verdict chips (per run), cross-examination
  threads (attack → defense with new evidence / concession / invalid defense) — built from the recorded
  `CLAIM`, `ATTACK`, `DEFENSE`, `CONCESSION`, `RULING` events, so it fills in live.
- **Exposure**: low–high bars for Thor, Loki and Odin per country × sector with metric, definition, unit, period,
  denominator; "unavailable" with the reason. Live (advocates only) until the briefing exists.
- **Briefing**: the final briefing from `GET /cases/{id}` (Markdown and JSON export). Every citation opens the side
  panel with the document (`GET /docs/{id}?case_id=`) and the cited paragraph highlighted, or the trade table
  (`GET /trade/{table}?case_id=`) with the cited row highlighted. Evidence reads are gated by the case's as-of date.
- **Trace**: the audit timeline filterable by agent, run and event group (trial, retrieval, memory, security & clock,
  limits & errors); run 1 vs run 2 comparison with new evidence highlighted; click a row for its payload.

Live updates use Server-Sent Events (`GET /cases/{id}/events`); if the stream fails the dashboard polls the same
endpoint with `follow=false&after=<last seq>`.
