# PROGRESS — Trial of the Nine Realms

Last updated: 2026-10-26 (LLM request economy after Phase 6: a two-run case now needs ~22 model requests; scripted-model tests only, no real API run yet). Branch: Amogh.

## Phase checklist

### Phase 0 — Inspection, contracts, setup ✅
- [x] Clone branch Amogh (single-branch), longpaths, hooks, .claude/settings.json
- [x] .gitignore, .env (gitignored, key set), .env.example (placeholders)
- [x] Python 3.12.4 venv `.venv`, dependencies installed (requirements.txt)
- [x] API key verified (models list OK); models chosen and smoke-tested with structured output
- [x] PS PDF + dev pack fetched (scripts/fetch_dev_pack.py), counted and checksum-verified
- [x] Dataset inspected (manifest schema, headers, paragraphs, trade layout, damage, traps)
- [x] Local embedding model tested (fastembed bge-small, 384-d)
- [x] Config module, Pydantic contracts, minimal FastAPI /api/health
- [x] CLAUDE.md, PROGRESS.md, data/TRAPS_FOUND.md
- [x] Tests: 59 passed (config, models good/bad, dev pack presence/integrity)

### Phase 1 — Ingestion and evidence storage ✅ (2026-10-25)
- [x] Pack discovery: manifest entries (docs/ or root), unlisted files (flag not_in_manifest), path-traversal refused, hashes.sha256 checked (hash_mismatch); manifest normaliser (mixed key case/types, upper wins, conflicts recorded)
- [x] Header parser (`KEY: value` until `---`, key case/spacing/aliases tolerant); merge with manifest (header wins, manifest fills; DOC_ID: manifest wins), conflicts + raw values kept (`header.X` / `manifest.X`); dates→ISO, tier→int, time→HH:MM
- [x] Sniffing by magic bytes (PDF/DOCX/zip/text) — extension mismatch is a parser warning
- [x] TXT decoding: BOM → mid-file BOM (segment-wise) → UTF-8 (rejected if UTF-16 NUL pattern) → BOM-less UTF-16 → strict cp1252 for mostly-ASCII → charset-normalizer → cp1252+replace; encoding recorded; bad_encoding on replacements; truncated on odd UTF-16 byte
- [x] PDF (pypdf) and DOCX (python-docx: body paragraphs + tables in order, hidden runs, core props, headers/footers, comments) extraction; never raises
- [x] Paragraphs on `[Pn]` markers (PDF wraps undone), P0 preamble, blank-line fallback; repeated/missing/out-of-order markers flagged (malformed), never lost
- [x] Damage flags: empty, header_only, truncated (mid-sentence / odd byte / cut-off table), unparseable, missing_header, malformed, bad_metadata, hash_mismatch; notices: metadata_conflict, not_in_manifest, duplicate, possible_duplicate (`DAMAGE_KINDS` in models)
- [x] Injection scanner (17 generic patterns + hidden/bidi/tag chars + DOCX hidden runs + metadata fields); spans stored; `Paragraph.evidence_text` withholds high-severity spans, wraps medium; originals/hashes untouched; TRAP_INJECTION logged
- [x] Duplicates: exact (normalised body hash; earliest = canonical) → duplicate_of; near-duplicates (cut-off prefix, shingle ≥0.6, same title) → near_duplicate_of + possible_duplicate, not merged; recomputed store-wide after each ingest
- [x] Corrections/retractions linked generically (source_type/title cue + same outlet + date mentioned + title overlap)
- [x] Trade parser: prose layout + PS fixed layout (|, tab, csv, whitespace-aligned by column position; table header block read); rows validated (missing_value, bad_number, duplicate_row, truncated, malformed); period gaps and declared-period shortfalls flagged; identical-to-previous-month = warning only; commodity from content vs SECTOR conflict flagged
- [x] SQLite store (packs, documents, paragraphs, doc_flags, doc_relations, trade_tables, trade_rows, audit_log append-only via triggers) + JSONL export; idempotent re-ingest; cross-pack ID collision refused
- [x] CLI `python -m backend.ingest <pack_dir> [--db] [--json]` with summary
- [x] Tests: synthetic pack (tests/fixtures/synth_pack, built by build_fixtures.py) + live-added pack + dev pack integration

### Phase 2 — Hybrid retrieval and calculations ✅ (2026-10-25)
- [x] Paragraph chunks (`retrieval/index.py`) with doc_id, ref and all metadata incl. table sectors, damage kinds, injection flag, duplicate/near-duplicate/correction links; indexed text = title + evidence text
- [x] Hybrid index: BM25 (rank-bm25, built per query over the filtered in-window candidates) + ONE vector index (fastembed `BAAI/bge-small-en-v1.5`, local ONNX, 384-d, normalised) fused with RRF (k = RRF_K = 60); per-hit bm25/vector ranks and cosine kept
- [x] `RetrievalService.search(query, as_of, agent, filters, limit, case_id, run_number)`: as_of required; filters country, sector (doc SECTOR or table commodity), event_id ("none" = background), source_type, max_reliability, date_from/date_to, doc_ids; AND across fields; exact duplicates hidden by default; result cap MAX_EVIDENCE_PER_QUERY
- [x] Query cache in SQLite: key = case, agent, normalised query, filters, as_of, limit, index version, model; reuse logged (QUERY reused=true + first_query_seq); any other change runs a new query
- [x] `read_doc` and `get_trade_rows` date-guarded (pub_date and row period); explicit out-of-window requests return nothing + CLOCK_VIOLATION_BLOCKED; relations to out-of-window docs never shown; rows of exact-duplicate docs hidden by default; invalid rows returned with status/reason (or `valid_only`)
- [x] `calc/trade_calc.py`: sum, mean, yoy_change (abs / %), share (explicit denominator_label), period_change, net_offset; rows resolved through the as_of gate; exclusions with reasons; require_complete (default) → no result if anything excluded; deterministic calc_id; record stores its request → `verify` replays it exactly; records persisted (`calculations` table)
- [x] `retrieval/citations.py`: doc/paragraph/row existence, row belongs to doc, pub_date match, within as_of, quote match (NFKC + quote chars + case + whitespace only), not from a flagged instruction span, invalid-row citation flagged; `validate_claim` requires reproducible calc records for estimates
- [x] Hot ingest: `RetrievalService.hot_ingest(pack_dir)` + `python -m backend.search --ingest <pack_dir>`; store version bump → any running index refreshes on next query (only new paragraphs embedded)
- [x] Audit: QUERY, RETRIEVED, CLOCK_VIOLATION_BLOCKED, ERROR, INGEST in the append-only log; `python -m backend.search --export-log out.jsonl [--case ID]`
- [x] CLI `python -m backend.search "<query>" --as-of YYYY-MM-DD [--country --sector --event-id --source-type --max-reliability --date-from --date-to --include-duplicates --limit --agent --case --json]`

### Phase 3 — Basic end-to-end trial ✅ (2026-10-25)
- [x] llm/client.py: messages.parse with Pydantic output (beta parse + server-side refusal fallback `fallbacks="default"` on Opus 5.5 / Sonnet 5.5; plain parse otherwise), effort per role, timeout + SDK bounded retries, refusal / max_tokens handled, ONE repair attempt then LLMOutputError (or `allow_residual` → code drops invalid parts), token ledger per agent/case with LimitHit; injectable backend
- [x] agents/prompts/: preamble.md (exact untrusted-evidence sentence) + heimdall/thor/loki/odin.md; `wrap_document()` escapes < > so a document cannot close its tag
- [x] Tool permissions in code (agents/common.py TOOL_PERMISSIONS); as_of never selectable by agents; tool-call budget per agent/case → LIMIT_HIT
- [x] Heimdall → CaseFile (countries/sectors asked about, related countries, routes, events, corrections, trade tables, missing data); status without a valid citation → downgraded to uncertain; disproved → STOPPED
- [x] Thor ∥ Loki (threads, own SQLite connection each): ≥1 own search enforced; citations resolved against the store (dates from the store; must be retrieved by that agent); uncited claims rejected before Odin; estimate bounds must equal |result| of complete calc records in the same unit
- [x] Cross-exam: ≥1 attack each way required (else "X's claims went unchallenged"); attack = opponent target + counter-evidence or concrete gap; defense must carry a NEW valid citation not used by the claim, else invalid defense (attack stands); full/partial concessions
- [x] Odin: code pre-checks per claim (citations, post-as_of, duplicates, damage, invalid rows, tier-4-only, corrected-only, calc reproducibility); two calls (rulings; ranges + sufficiency + summary); guards: every claim ruled or reported unruled, conceded ⇔ concession, no established with hard failures, range bounds from calc records (not averages); sufficiency logged (send-back in Phase 4)
- [x] Briefing (briefing/build.py) from rulings only: Markdown + Briefing JSON, inline citations [DOC Pn, date], exposure table Thor/Loki/Odin, outlook + assumptions, missing data, traps/failures, sources
- [x] Explicit state machine (trial/machine.py, ALLOWED transitions; no planner); persistence to logs/cases/<case_id>/ (state, case_file, heimdall_report, claims, cross_exam, rulings, briefing.md/.json, evidence_refs, config, events.jsonl)
- [x] Audit events: CASE_FILE, CLAIM, ATTACK, DEFENSE, CONCESSION, PRECHECK, RULING, SUFFICIENCY, BRIEFING, STAGE, RUN_START/END, TRAP_INJECTION, LIMIT_HIT, ERROR
- [x] CLI `python -m backend.trial "<question>" --as-of YYYY-MM-DD [--stop-after HEIMDALL|THOR_LOKI|CROSS_EXAMINATION]`

### Phase 4 — Second run, memory, failure handling (code + scripted tests done 2026-10-25; REAL DEMO PENDING: API limit)
- [x] SendBack (Odin's structured missing list; decided in code: insufficient + missing named + run < MAX_RUNS) → HEIMDALL_RESEARCH: per-item NEW targeted queries (plan validated; queries equal to any earlier query in the case refused in code and by AgentEnv.forbidden_queries) → follow-up reads → findings → code novelty check (Novelty: not retrieved by anyone in earlier runs, not exact/near duplicate of a seen doc, not the same text) → NEW_EVIDENCE events with run number
- [x] No genuinely new evidence → logged, advocates/Odin not re-run, briefing from last rulings labelled `incomplete`
- [x] Run n ≥ 2: advocates get the new evidence via the as_of-gated paths, must make ≥1 new (non-cached) search, then AdvocateRevision: revise (revises_claim_id) / withdraw (Concession W{n}-…) / new claims; unrevised claims carry over and are re-ruled; cross-exam on new claims; Odin reassesses all active claims with <run_history>; effect of new evidence logged (NEW_EVIDENCE phase=effect) and saved
- [x] MAX_RUNS default 2, max 3; LIMIT_HIT on the run limit; cross-exam rounds per run (round 2+ = rebuttal on defended claims; LIMIT_HIT when the cap stops it)
- [x] Private memory: agent_memory table, AgentMemory bound to one owner (every SQL filtered by owner; no cross-agent API; AgentEnv.remember refuses other agents' lessons); lessons derived by code after each run's rulings (rejected/conceded/withdrawn/established estimates/invalid defenses/useful queries; Heimdall send-back gaps, useful/dead-end targeted queries, corrections; Odin code-guard and send-back-effect lessons); Masker removes place/entity names, IDs, dates, numbers; identical lessons reinforced (times_seen, confidence)
- [x] Memory use: recall by stage before planning (MEMORY_READ always logged); first planning round: baseline plan WITHOUT memory (not executed) + plan WITH memory; MEMORY_APPLIED only when the agent names a recalled lesson AND the plan differs (payload: original_action, changed_action, added, removed, memory_used, agent_stated_effect); otherwise logged as "did not change"; Odin: agent-stated only (no baseline, prompt too large)
- [x] Budgets: tool calls per agent/case, tokens per agent/case, evidence per case (new), runs, cross-exam rounds, request timeout + SDK retries, upload size (Phase 1); LIMIT_HIT logged; graceful finish
- [x] Failures: advocate fails in run 1 → other unchallenged (Phase 3); in run n → its earlier claims stand, other side's new claims unchallenged; both fail run 1 / Odin fails run 1 → FAILED + limitations.md, no briefing; Odin / Heimdall / both advocates / token budget fail in run n → briefing from run n-1 rulings, incomplete
- [x] Persistence: logs/cases/<id>/run-N/{case_file,claims,cross_exam,rulings,sendback,research,new_evidence_effect}.json + top-level state/claims/rulings/briefing/memory.json/events.jsonl; CLI prints runs, memory events, `--save-demo` copies to logs/demo/
- [ ] Real two-run demo on the dev pack saved to logs/demo/ (blocked: API workspace usage limit until 2026-11-01 00:00 UTC)

### Phase 5 — Final briefing and API ✅ (2026-10-25; scripted-model tests + live server smoke on the dev pack)
- [x] Briefing build-time checks: every finding/event citation re-validated (validate_citation: exists, quote, as_of); every Thor/Loki/Odin estimate's provenance replayed (bound_problems + calc.verify from in-window rows). Failures dropped, listed in briefing.dropped_citations + Markdown, logged as ERROR (payload briefing_check); a finding with no surviving citation is not shown; failed/missing estimates shown "unavailable (reason)" (ExposureRow.unavailable)
- [x] Briefing sections: summary, verification, established/contested/conceded/rejected with inline [DOC Pn, date] / [ROW, date], exposure table with Metric (unit, period, denominator) + Thor/Loki/Odin columns, per-estimate details, Assumptions and uncertainty (new), investigation runs, outlook + assumptions, missing data/evidence quality, traps/corrections/failures, sources (labelled Runemark)
- [x] Core shared by CLI and API: trial/runner.py (run_case, CaseRunner threads, case_status, case_results); CLI now calls run_case
- [x] API (backend/ragnarok/api.py, create_app factory, lazy `app`): POST /cases (202; 409 if a case is running; 503 without key), GET /cases/{id} (running|complete|partial|failed + results from saved files), GET /cases/{id}/events (SSE of stored audit events, after / Last-Event-ID, follow, end event), GET /docs/{id}[/{para}] and GET /trade/{table}[/{row}] (as_of or case_id required; 403 + CLOCK_VIOLATION_BLOCKED when out of window; anchors, injection flags, original text for flagged paragraphs), POST /ingest (form pack_dir inside PACKS_DIR, or .zip upload: size 413, type 415, zip-slip/absolute/symlink 400, one manifest, stored in PACKS_DIR/uploads), GET /feed?as_of= (newest first, badges tier/damaged/notices/injection/corrects/corrected_by/duplicates, withheld count). Swagger moved to /api/docs. CORS for localhost:5173.
- [x] Status mapping: DONE+complete briefing -> complete; DONE+partial/incomplete, STOPPED, or --stop-after -> partial; FAILED or interrupted -> failed

### Phase 6 — Functional dashboard ✅ UI built and browser-checked (2026-10-25); full real case blocked by Gemini free-tier daily quota
- [x] frontend/: React 18.3.1 + Vite 6.3.5 + TypeScript 5.8 + Tailwind 4.1 (no Recharts: range bars are plain divs). Vite proxies /cases /docs /trade /feed /ingest /api to 127.0.0.1:8000 (RAGNAROK_API overrides).
- [x] Question panel (POST /cases; status running/complete/partial/failed, stage, path, briefing status; open saved case; #case=<id> in URL)
- [x] Evidence feed (GET /feed?as_of=: tier, source type, damaged, suspicious, corrected-by / correction-of, duplicates; docs retrieved in the case marked with run + agents from RETRIEVED events; "retrieved only" toggle)
- [x] Trial view built only from recorded CLAIM/ATTACK/DEFENSE/CONCESSION/RULING events (fills in live): Thor vs Loki columns, fact/inference tags, verdict chips per run, attack -> defense/concession/invalid-defense threads, revised/withdrawn markers
- [x] Exposure view: Thor/Loki/Odin low-high bars per country x sector, metric definition, unit, period, denominator, confidence, calc IDs; "unavailable: reason"; live advocate-only view before the briefing; unit-mismatch warning
- [x] Briefing view: rendered from briefing JSON, Markdown toggle, .md/.json export; every citation and source opens the side panel (GET /docs?case_id= with the paragraph highlighted; trade citations also load GET /trade?case_id= with the row highlighted); injection-flag banner with "show original text"
- [x] Trace view: audit timeline filterable by agent / run / group (trial, retrieval, memory, security & clock, limits & errors, stages), payload on click, counters for memory / MEMORY_APPLIED / injection / clock blocks / limits; run 1 vs run 2 table with send-backs and NEW evidence highlighted (clickable)
- [x] Live updates: EventSource on /cases/{id}/events (named events), fallback polling (follow=false&after=seq); status polled while running; loading, empty and error states in every panel
- [x] Backend fix found during the real run: an empty filtered search now tells the agent which filter matched nothing and the values that exist (from the evidence) — agents/common.py `_empty_search_hint`; test_empty_filtered_search_explains_which_filter_matches_nothing
- [ ] A complete real case (briefing) through the UI — blocked by the Gemini free-tier daily request quota (see verification)

### LLM request economy (2026-10-26, between Phase 6 and 7) ✅ code + scripted tests; real-model run pending
Goal: a full real case with MAX_RUNS=2 in <= ~25 model requests (free tier ~25-30/day/model). Every change has a Settings flag; the legacy values restore the old path (verified: the legacy profile reproduces the old counts exactly).
- [x] STEP 0 instrumentation: LLMClient records every request in TokenLedger.records (agent, label, schema, stage, run, repair, cached, input/output tokens, stop reason, ms); `llm_calls.json` (summary + calls) in each case folder; LLM_USAGE event at RUN_END (by agent / stage / label, repairs, tokens)
- [x] A research(): MAX_RESEARCH_ROUNDS default 1 (was 3), MAX_REQUESTS_PER_ROUND setting default 8 (was constant 5); one extra turn only while the agent's required own search is missing; tool budgets unchanged in code
- [x] B cross-exam: no "cross-exam research" / "defense research" planning calls (CROSS_EXAM_CODE_SEARCH). Code derives the searches: attacks = one search per targeted opponent claim (claim text + generic side cue words, claim country filter); defense = one search from the attack's objection + evidence gap (claim country filter) + re-read of the attacked claim's first cited document (CROSS_EXAM_READS_PER_ATTACK). All through the advocate's own as_of-gated, logged, query-deduped tools; RESEARCH_PLAN event lists them. Then ONE AttackSet / ResponseSet call. Rules unchanged (target + specific objection + counter-evidence or gap; defense needs NEW valid citation or it is an invalid defense; unanswered attacks logged)
- [x] C memory baseline: MEMORY_BASELINE_MODE=combined: one call (DualResearchTurn / DualSendBackPlan) returns plan_without_memory (recorded, never executed) + the executed plan; MEMORY_APPLIED payload unchanged (original_action, changed_action, added/removed, memory_used) + baseline_kind; `separate` keeps the old extra call; MEMORY_BASELINE=false turns it off
- [x] D Odin: no planning turn (ODIN_RESEARCH_ROUND=false); prompt carries code pre-checks of every citation and code replays of every calc; ONE OdinVerdict call (rulings + ranges + sufficiency + summary + outlook + memory_used); fallback to the two-step path when the merged output still fails validation after its repair (LLMOutputError) or the API rejects the schema (HTTP 400); an API outage is not retried as a fallback. Guards unchanged; Odin alone decides sufficiency
- [x] E delta run (DELTA_RUN): run n>=2 revised/new claims must cite evidence first retrieved in that run (else dropped by code, logged); cross-exam only on revised/new claims (already so); Odin rules only on revised/new claims, unchanged claims keep their earlier Ruling (run_number of that run) inside the run-n OdinResult and are shown to Odin as <standing_rulings>; novelty check and NEW_EVIDENCE effect logging unchanged
- [x] F repairs: REPAIR_MODE=residual_first: semantic problems in optional parts are dropped by code without a second call (logged ERROR llm=residual, repaired=false); one repair only for schema failures, truncation, or "essential" problems (no surviving claim; no valid attack; missing ruling; countries empty; a send-back item with no new query)
- [x] G Heimdall seeds: up to HEIMDALL_SEED_SEARCHES code-run searches from the user's question (question as asked; candidate event = most frequent event ID among its hits, tiers 1-2; each country/sector named in the question, matched against in-window metadata values) - logged RESEARCH_PLAN seed=true, counted as Heimdall tool calls; advocates receive the cached results via the query cache (RETRIEVED seed=true reused=true from_agent=heimdall, re-checked against as_of) plus the Case File's trade-table rows (as_of-gated reads); neither counts as the advocate's own search (>=1 own search still enforced; test)
- [x] Send-back follow-up planning turn replaced by code (SENDBACK_FOLLOWUP_LLM=false): rows of trade tables hit by the targeted searches are fetched
- [x] H MAX_LLM_CALLS_PER_CASE (default 30): checked before every request -> LimitHit -> LIMIT_HIT + the same graceful finish as the token budget; GET /cases/{id} returns calls_used / calls_limit (and attempt) (the dashboard no longer shows them: no LLM-call or token meter, user decision 2026-10-26)
- [x] I response cache: SQLite table llm_cache keyed by (case_id, sha256(model, system, user, schema name)); written always, read only when the same case ID runs again (attempt > 1); LLM_CACHE_HIT event per replay; never across cases (test). Resume = CLI `--resume <case_id>` or POST /cases/{id}/resume (failed/partial cases; 409 when running or complete). For identical prompts on resume: memory recalls replay what the earlier attempt recalled (from its MEMORY_READ events), lessons already written are not reinforced again, cached searches from the earlier attempt count as replays (not "reused"), "earlier queries" and traps are scoped to the current attempt. Dashboard trial view uses events of the latest attempt only
- [x] .env.example documents every new setting

Before / after (scripted model, synthetic pack, `measure_calls.py` scratch script; legacy profile = the old defaults):

| stage | before: 1 run | before: 2 runs | before: 2 runs, worst case* | after: 1 run | after: 2 runs | after: 2 runs, worst case* |
|---|---|---|---|---|---|---|
| run 1 HEIMDALL | 2 | 2 | 5 | 2 | 2 | 2 |
| run 1 THOR_LOKI | 5 | 5 | 11 | 4 | 4 | 4 |
| run 1 CROSS_EXAMINATION | 8 | 8 | 8 | 4 | 4 | 4 |
| run 1 ODIN | 4 | 4 | 4 | 1 | 1 | 1 |
| run 2 HEIMDALL_RESEARCH | - | 4 | 4 | - | 2 | 2 |
| run 2 THOR_LOKI | - | 6 | 10 | - | 4 | 4 |
| run 2 CROSS_EXAMINATION | - | 8 | 8 | - | 4 | 4 |
| run 2 ODIN | - | 3 | 3 | - | 1 | 1 |
| **total** | **19** | **40** | **53** | **11** | **22** | **22** |
| repairs | 2 | 2 | 2 | 0 | 0 | 0 |

\* worst case = memory from a prior case present and research turns that never say done. Real runs before this change: ~24 per run + baselines + repairs (~55-80 per two-run case).
Per label after (2 runs): heimdall research 1, report 1, send-back plan (+ no-memory plan) 1, findings 1; thor/loki each: research 1, brief 1, attacks 2, responses 2, run-2 research (+ no-memory plan) 1, revision 1; odin verdict 2.
Remaining real-model risk: each extra planning turn (own search missing) or essential repair adds 1; the cap (30) turns overflow into LIMIT_HIT + incomplete briefing instead of a quota failure.

### Dashboard restyle to the approved design mock (2026-10-26) ✅ frontend only; API contract unchanged
- [x] Tokens from the mock (paper, sheet, ink, ink-2, ink-3, rule, rule-2, accent, bad, hl + washes) as CSS variables mapped into the Tailwind 4 theme; light only; Hanken Grotesk + IBM Plex Mono self-hosted via @fontsource 5.3.0 (offline); tabular numerals in numeric columns; no cards/shadows/gradients/pills; ruled rows; uppercase section labels over a 1px ink rule; radius <= 6px
- [x] Shared `<Verdict>` (filled / half / hollow grey / red square + "not ruled"), `<ClaimType>`, `<AgentMark>` (Thor solid, Loki outline, Odin accent), `<Cite>`; layout primitives (Section, Alert, Skeleton, Empty, Filters with aria-pressed); shadcn/ui Dialog pattern on @radix-ui/react-dialog 1.1.23 restyled (New case). No other shadcn parts were needed (no Tooltip/Tabs: titles + aria-current nav suffice)
- [x] Shell: top bar (brand, case ID mono, as-of, run status text from status + RUN_START config, New case), left rail with nav (aria-current) + Pipeline (Heimdall / Thor and Loki / Cross-examination / Odin / Briefing; state and counts from status history and events; failed stage = red square); < 768px: horizontal nav, pipeline hidden
- [x] Routing `#case=<id>&view=trial|exposure|evidence|trace` (bare `#exposure` also works); old `#case=<id>` links still open (view defaults to trial)
- [x] Trial: question, rulings ledger, Thor / Loki ruled claim rows (ID, fact/inference, country/sector, verdict per latest run, citations, calc IDs, revises / superseded / withdrawn notes), cross-examination rows Attack | Response | Odin (defense with new evidence, concession incl. partial + revised text, invalid defense = undefended, no response = undefended once finished)
- [x] Exposure: one shared 0..max scale per unit with nice ticks from the data (rows with different units never share an axis); Thor / Loki / Odin lines with mono low-high; per-agent "no estimate" lines; dashed no-estimate box with the recorded reason ("missing data, not zero"); header from the estimates; row detail with per-agent metric definitions, unit / period / denominator / confidence, assumptions, missing data, clickable trade-row refs (open the row) and calculation IDs (expand the recorded trade_calc record)
- [x] Evidence: timeline (month ticks generated from the range, the year before as-of; older reference documents counted at the left edge), as-of line, ticks by state (normal, corrected hollow, flagged red, damaged dotted, retrieved taller), hatched marker for documents withheld after as-of; filters All / Tier 1 and 2 / Corrections / Damaged or flagged / Added in run 2+ and scope Retrieved / All before as-of; ruled list; inline viewer with the cited paragraph or trade row highlighted, flagged paragraphs marked "withheld as instruction" (original text behind an aria-pressed toggle), 403 = "Blocked … no content"
- [x] Run trace: Odin's send-backs (reason + missing items), Heimdall's targeted queries (accepted + refused), memory before/after from MEMORY_APPLIED (original_action vs changed_action, added/removed, memory used, agent's account; honest empty state), run table (evidence retrieved / new evidence / claims / sufficiency / Odin range changes from the NEW_EVIDENCE effect / briefing status), event list with type filters (paged by 60, payload on click), then the full Briefing (findings with citations, outlook, missing data, traps, sources, Markdown view, .md / .json export). LLM_USAGE / LLM_CACHE_HIT events are not shown
- [x] States: skeletons while loading, empty states per view, error alerts (case unavailable, feed / document errors), failed / interrupted cases labelled in the top bar (red) and an alert with notes + limitation report while partial results stay visible; stopped (disproved) cases explained
- [x] Removed the old components (DocPanel, EvidenceFeed, ui, old views, QuestionPanel); the earlier "model requests X / Y" status text is gone
- [x] frontend/README.md: tokens, components, views, how to add a view

## Dashboard restyle verification (2026-10-26)
- `npm run build` (tsc -b + vite build) OK. Backend untouched: `.venv/Scripts/python -m pytest` exit 0 (357).
- The built-in browser is not available in this VS Code session, so checks ran in headless Microsoft Edge via playwright-core (scratch scripts outside the repo, Edge launched outside the command sandbox), against the running API + Vite dev server, read-only (0 POST requests).
- Saved case case-20261025-084715-fa6fe3, 35/35 scripted checks passed: 11 claim rows = 11 CLAIM events; ledger 5 established / 2 contested / 4 conceded / 0 rejected = latest RULING events; 6 cross-exam rows = 6 ATTACK events; citation ORV-0022 P5 opens Evidence with exactly P5 highlighted and the quote inside it; Evidence summary 29 retrieved / 73 in window / 3 withheld = API; 29 list rows; Tier 1-2 filter 25 rows with aria-pressed; Exposure 4 rows = briefing table, 1 dashed no-estimate row, scale 0-300 computed from max high 216.2; trade-row citation ORV-0030 R10 highlights row R10; calc ID expands its recorded record; Tab order New case -> Trial -> Exposure… with a solid accent focus ring, Enter switches view; New case dialog opens and closes with Escape; Run trace shows the honest memory empty state, no LLM_USAGE rows, briefing export present; failed case case-20261025-110349-21e64d labelled "Failed at Heimdall" + alert; no-case start form; 400px width: no sideways scroll on all four views; no console errors (inline favicon fixed the old 404).
- Before / after screenshots (desktop 1280 and phone 400, all views, plus the mock's four views) are in the session scratchpad, not in the repo.

### First real run of the request-economy code (2026-10-26, new AI Studio key from the user, stored in .env; old key kept as a comment there)
- Probe OK (gemini-3.5-flash, 1.5 s). Case **case-20261025-204050-ac35da** (sample question, as of 2027-01-25, MAX_RUNS=2; copy in logs/demo/): run 1 complete in **11 model requests, 0 repairs** (heimdall 2, thor 4, loki 4, odin 1; exactly the scripted prediction), ~137k input / 30k output tokens, ~8 min of request time (503 retries, max 107 s per request).
- Run 1 results: event established (expiry, cited); Case File 6 docs, 3 trade tables; 7 claims (Thor 3, Loki 4; 1 Thor claim rejected in code: no valid citation); 6 attacks (3 each way), 4 defenses with new evidence, 2 concessions, 0 invalid; Odin 4 established / 1 contested / 2 conceded, every claim ruled; Odin ranges Midgard wheat 156.5-216.2, Midgard maize 105.7-126.4, Tolan wheat 69.6-96.0 USD M, Tolan maize insufficient; Odin INSUFFICIENT -> SENDBACK SB-1 (Tolan maize series; Vanir/Ravik substitution data); MEMORY_APPLIED: Heimdall's lesson added a corrections/retractions search vs the no-memory plan (combined baseline); briefing citations dropped at build time: 0.
- Run 2 did not happen: Heimdall's send-back plan request got 429 `GenerateRequestsPerDayPerProjectPerModel-FreeTier` (limit **20/day** for gemini-3.5-flash on this key; the probes and server-side 503 failures count too). Recorded honestly: Heimdall failed in run 2 -> briefing from run-1 rulings, status **incomplete**. Quota reset ~10 h after 2026-10-25 20:58 UTC. Next: `.venv/Scripts/python -m backend.trial --resume case-20261025-204050-ac35da` (run 1 replays from the case cache at 0 requests; run 2 needs ~11).
- Quality issue seen: residual-first dropped both of Loki's estimates ("numbers not reproducible from calc records") without a repair, so Loki has no range in the exposure table. Candidate fix: treat estimate-bound problems as essential (one repair, +1-2 requests).
- Dashboard on this case (separate current-code API on :8001 + Vite :5174, headless Edge): 35/35 checks pass, incl. the real send-back, Heimdall's queries and the memory before/after block; fixed: the no-estimate box now shows the per-agent recorded reasons when the row note is empty. The API process on :8000 started before the LLM_USAGE event type existed returned an empty event stream for new cases (blank dashboard); restarted by Claude on user request (no case was running) -> 35/35 checks pass on localhost:5173. Restart the API after backend changes.

### Model chain + quota pause (2026-10-26) ✅ code + scripted tests + one real resume
- Problem: free tier = 20 generate requests/day PER MODEL (GenerateRequestsPerDayPerProjectPerModel-FreeTier); a two-run case needs ~22. Rotating keys/projects to dodge the cap was ruled out (Google API terms); billing is the only way to remove the cap.
- [x] GEMINI_MODEL_CHAIN / GEMINI_JUDGE_CHAIN: models tried in order. A daily-quota 429 (QuotaFailure "PerDay") is no longer retried (each retry counted against the same quota): QuotaExhausted -> the same request goes to the next model; the used-up model is skipped until the server's retryDelay (table model_quota, shared by CLI/API/later cases). 5xx/timeouts: LLM_SERVER_RETRIES (1 in .env) then ModelUnavailable -> next model, MODEL_COOLDOWN_S skip. MODEL_SWITCH event per switch; llm_calls.json has by_model and failed_requests. Per-minute 429s keep the old waits.
- [x] Whole chain used up -> QuotaPause (not an LLMError, so no agent treats it as its own failure) -> stage PAUSED, state.json paused_until, LIMIT_HIT "daily model quota"; no briefing, no limitations report; GET /cases status "paused" + paused_until; the API re-starts the case by itself after the reset (CaseRunner timer, skipped if resumed by hand); CLI `--wait` keeps waiting/resuming until it finishes; dashboard shows "Paused · daily model quota · resumes after …" + banner; MODEL_SWITCH in the trace filters.
- [x] Resume replays a reply from ANY model of the chain (cache lookup per chain model).
- [x] Bug found by the real resume and fixed: Thor's and Loki's defenses/concessions were recorded in thread-completion order, so a replay (instant replies) rebuilt a different Odin prompt and Odin's run-1 verdict was asked again live. Now sorted by attack ID after each cross-exam round. Test test_resume_does_not_depend_on_parallel_timing (mutation-checked: fails without the sort).
- [x] Probes 2026-10-25 (1 request each, key's own per-model quotas): gemini-3-flash-preview OK 2.5 s; 3.5-flash-lite OK 1.7 s; 3.1-flash-lite OK 7 s; 3.8-flash / flash-latest OK but 60-70 s; 3.6-flash no free quota; 3.7-flash 504; 2.5-flash-lite 404. .env now: chain 3.5-flash, 3-flash-preview, 3.5-flash-lite, 3.1-flash-lite, 3.8-flash; judge chain 3.5-flash, 3-flash-preview, 3.8-flash.
- Tests: tests/test_model_chain.py (10) + the timing test; full suite 368 passed (exit 0); `npm run build` OK.
- Real resume of case-20261025-204050-ac35da (attempt 2): 10 run-1 replies replayed, 4 requests (gemini-3.5-flash refused once -> MODEL_SWITCH -> gemini-3-flash-preview answered Odin + Heimdall's plan + findings); Odin's re-ruling (asked again because of the ordering bug) gave the same verdicts and ranges but a send-back with ONE item (Tolan maize trade series), which does not exist in the pack -> Heimdall's 2 targeted searches found no genuinely new evidence -> correctly no advocate/Odin re-run, briefing incomplete. A real second run with new evidence is therefore still not demonstrated; it depends on Odin naming missing evidence that exists.

### Dashboard gaps vs the problem statement (2026-10-26) ✅
- [x] Briefing tab (FR8 / criterion 6): status, executive summary, event verification, exposure TABLE (Thor / Loki / Odin low-high per country x sector + metric, unit, period, trade rows), Established / Contested / Conceded / Rejected with inline citations `[DOC Pn, date time]` (time from the briefing's source list), outlook + assumptions, assumptions/uncertainty, missing data, traps/failures + trial notes, sources labelled Runemark ("no off-Runemark source", NFR2). Save as PDF (print layout: navigation hidden, case header), Export .md / .json, Markdown view. Run trace now links to it.
- [x] Add documents (criterion 1, final-round live packs): dialog in the top bar + on the start page: a pack .zip (manifest) or loose PDF / TXT / DOCX files. Backend: POST /ingest accepts `files` (multi-upload; only .pdf/.txt/.docx, per-file and total size limits, sanitised unique names, stored under PACKS_DIR/uploads/docs-<time>/, ingested without a manifest so the header supplies metadata and each doc is flagged not_in_manifest); exactly one of pack_dir / file / files. Test test_ingest_loose_documents.
- [x] Live feed (FR7.1): Evidence view section, documents in the order the agents first retrieve them (RETRIEVED events, live via SSE), agent mark, run, tier, date; click opens the document at the first retrieved paragraph/row. Feed re-reads the index after an upload.
- [x] Question box (FR7.1): "Ask a question" button in the top bar (dialog) + the start page form.
- [x] Case file on the Trial view (FR1.1 / FR1.3): event status with reasons and citations, countries, sectors, related countries, routes, trade tables, key documents, corrections/rumours, missing data; trial notes (e.g. "the other side went unchallenged", NFR3).
- Verification (headless Edge, real API on :8000 restarted with the upload change, read-only except intercepted uploads): verify3 25/25 (Briefing tab aria-current; 4 exposure rows = briefing; 7 findings; timestamps; Runemark labels; outlook; PDF written 59 KB with navigation hidden; briefing citation -> Evidence viewer; live feed 8 of 18 + show all = 18; case file status + countries; upload dialog sends loose PDF+TXT as `files` and a .zip as `file`, refuses .exe, shows the summary; 400px no sideways scroll on all 5 views; no console errors); earlier suite 35/35 on both saved cases. Backend 369 passed. `npm run build` OK.
- Not done: an in-browser real upload (it would add test documents to the real index); covered by the API test instead.

### Remaining FRs + Phase 7 work (2026-10-26, new key from the user)
- New key probe OK; it turned out to belong to the SAME Google project (same per-project daily quota and reset time 06:59 UTC), so gemini-3.5-flash stayed used up; the chain switched to gemini-3-flash-preview.
- [x] Model-quota records are scoped to the key (sha256 fingerprint, 12 chars, never the key): a key from another project starts clean. Test test_model_blocks_belong_to_one_key.
- [x] FR3.2 / FR2.2: the real cause of Loki's lost ranges was notation (a fall written as negative bounds, low -156.5 > high -216.2), not wrong numbers. normalise_bounds() takes ascending magnitudes for negative or reversed bounds (logged in the estimate / Odin guards; a range across zero is left alone); remaining estimate problems are now essential (one repair, the message lists the valid calc results). tests/test_estimates_fr.py (5).
- [x] FR5.4 robustness: a real case (case-20261025-223333-e776a1) again had no second run because every top hit of Heimdall's send-back searches had been retrieved in run 1. Send-back searches now leave out paragraphs retrieved in earlier runs (SearchFilters.exclude_chunks: applied in code, part of the cache key, logged as a count, shown to the agent as "leaving out N paragraphs"); the novelty check stays the gate. Tests test_exclude_filter_leaves_out_given_paragraphs, test_sendback_searches_look_past_run1_evidence.
- Real case case-20261025-223333-e776a1 (14 requests; 13 on gemini-3-flash-preview): run 1 complete, but weak: point ranges (low = high), 0 concessions, 7/7 established (criterion 5 not met by THIS case), send-back -> no new evidence -> incomplete. Not a demo case. (Saved to logs/demo/ by --save-demo; the user may delete that copy.)
- [x] README.md (root) rewritten for the submission (the organizers' challenge text stays in data/runemark/dev_pack_E5/README.md); architecture diagram assets/architecture.svg (rendered and checked) + Mermaid flow in the README.
- [x] Unseen-pack dry run: scripts/build_dryrun_pack.py builds data/dryrun/pack_e7 (invented event E7 "Ymir Canal lock failure", 19 docs PDF/TXT/DOCX, PS fixed-layout trade tables, rumour, correction, duplicate, unrelated event E8, embedded AI instruction, empty / cut-off / cp1252 files, missing value, bad number, repeated row, cut-off table, a post-as-of notice). Ingested through POST /ingest (zip) into a COPY of the store (logs/dryrun/dryrun.db, API on :8002) with no code or index edits: 19 docs, 3 tables, 3 damaged, 4 injection spans; feed withholds the post-as-of doc, /docs -> 403; correction and duplicate linked; flags shown.
- [x] Bug found by the dry run and fixed: a fixed table cut off inside its last number ("65,300" -> "65") was accepted as valid. Now (1) a PERIOD with several ranges ("a..b; c..d") is read, so missing declared months are flagged, and (2) a row whose value/volume ratio is >= 20x off the table median is invalid (last row -> truncated, otherwise bad_number). Dev pack unaffected (98 rows, 0 invalid). Tests in test_ingest_trade.py (3).
- .gitignore: logs/**/*.db, logs/dryrun/, data/runemark/uploads/, data/dryrun/*.zip.

### Phase 7 — Final validation and submission
- [ ] Full two-run demo case with saved logs (logs/demo/), README, architecture diagram, unseen-pack dry run

## Setup facts (verified Phase 0)
- OS: Windows 11 Home 10.0.26200. Shells: Git Bash + PowerShell 5.1.
- Python: 3.12.4 venv at `.venv` (3.13 and 3.14 also installed; 3.12 chosen for wheel compatibility).
- Node v25.9.0, npm 11.12.1, pnpm 12.10.1, uv 0.12.17; yarn not installed.
- `git config core.longpaths true` (repo-local). Hooks pre-commit/pre-push installed and tested. CLAUDECODE=1 in Claude Code's shell.
- Unauthenticated GitHub API was rate-limited for this IP; the dev pack is fetched as a zip from codeload.github.com instead.

## LLM provider switch to Gemini (user request, 2026-10-25)
- LLM_PROVIDER=gemini (default) | anthropic. Key in .env as GEMINI_API_KEY (gitignored; never printed). The ANTHROPIC_API_KEY line is still in .env, unused (user may delete it).
- New backend backend/ragnarok/llm/gemini.py (google-genai 2.33.0): response_json_schema = the Pydantic schema, reply validated in code; thinking_level (Gemini 3.x) / thinking_budget (2.x) from effort; finish MAX_TOKENS -> max_tokens, SAFETY/BLOCKLIST/PROHIBITED_CONTENT/prompt block -> refusal; bounded retries on 429/5xx/timeouts honouring retryDelay; global pacer LLM_MIN_INTERVAL_S between request starts. Prompts, schemas, validators, budgets and flow unchanged.
- Verified with the key: model list OK; gemini-pro-latest / gemini-3.1-pro-preview -> 429 (no quota on this key); gemini-2.5-pro/flash -> 404 retired for new users; gemini-3.8-flash works but 97-112 s per call and 503s; gemini-3.5-flash ~2-5 s. All 12 trial schemas accepted and parsed on gemini-3.5-flash. Free tier ~5 requests/min (429 after 5 quick calls) -> LLM_MIN_INTERVAL_S=13 in .env.
- Real smoke run case-20261025-102052-4b94d2 (--stop-after HEIMDALL, effort medium -> thinking low): OK end to end (event established with citations, 8 tool calls, 4 LLM calls, ~13k tokens), but sectors came back ['agriculture'] instead of wheat/maize and only 3 trade tables.
- Second smoke run case-20261025-102216-981f84 (EFFORT_ADVOCATE=high): hung >8 min on its first model call with nothing in the log; stopped by Claude (it was a test run). Fixes: every Gemini retry now logged (ERROR event, payload llm=retry, with reason and wait), and GEMINI_REQUEST_TIMEOUT_S=120 (was the shared 300 s). The high-thinking quality question is still open.
- Expected duration of a full two-run trial on this free-tier key: ~60-80 model calls x >=13 s pacing, so roughly 15-25 min if the model is not overloaded; the daily free quota may not cover a full two-run case (unverified).
- .env non-secret limits updated to current defaults (the stale low values noted earlier).
- Tests: tests/test_gemini.py (10, fake client from SDK types), provider tests in test_config.py.

## Models (Anthropic, verified with that key, 2026-10-25)
Models API returned 14 models. Each chosen model passed a structured-output smoke test (`messages.parse` → Pydantic):
- MODEL_FAST = `claude-haiku-5-5` (cheap extraction, classification, query parsing)
- MODEL_ADVOCATE = `claude-sonnet-5-5` (Thor and Loki)
- MODEL_JUDGE = `claude-opus-5-5` (Odin)
Notes: these models reject `thinking: disabled` and `budget_tokens`; use `output_config.effort`. Forced `tool_choice` (any/tool) returns 400 on Opus 5.5 / Sonnet 5.5 — use structured outputs or `auto`. Always check `stop_reason == "refusal"`. Anthropic SDK 2.3.0.
- EMBEDDING_MODEL = `BAAI/bge-small-en-v1.5` via fastembed (local ONNX, 384-d, ~65 MB cached in data/index/models, gitignored). Tested working; a Windows symlink warning is harmless.

## Dataset facts
See CLAUDE.md §19 (verified). Key points for Phase 1: mixed manifest key case and types; `KEY: value` header + `---`; `[Pn]` paragraph markers with PDF line wrapping; trade data is prose in trade_note docs (not fixed tables); maize notes mis-tagged SECTOR Wheat; a 0-byte file; a mixed-encoding (ASCII header + truncated UTF-16 body) file; a truncated near-duplicate; exact duplicates; 3 docs after as_of; one embedded instruction (data/TRAPS_FOUND.md).

## Decisions
- Build at repo root (branch had only README.md; left untouched).
- Package `backend/ragnarok`, tests via `pytest` with `pythonpath=backend` (pyproject.toml).
- Config: pydantic-settings, `.env` at project root, SecretStr key, hard limits validated (e.g. per-agent ≤ per-case).
- Contracts in `backend/ragnarok/models.py`; extra fields forbidden; verdict enum lower-case; missing numbers stay None; attacks need counter-evidence or a concrete gap; defenses need new evidence; "conceded" rulings must reference a concession; briefings reject post-as_of citations.
- Embeddings: local fastembed instead of sentence-transformers (no torch, smaller install).
- Trial orchestration: decide in Phase 3 between LangGraph (installed, 1.2.17) and a plain explicit state machine; prefer the plain one if LangGraph adds risk.
- Dev pack data (`data/runemark/`) is small (~3.4 MB) and organizer-public; committing it is optional (it can always be re-fetched and verified with the script).

## Implementation plan (dependencies → first end-to-end milestone)
1. Phase 1 ingest + store (depends on contracts) → every doc/row addressable by stable ID.
2. Phase 2 retrieval + calc (depends on store) → filtered, as_of-gated search; deterministic maths.
3. Phase 3 llm client + four agents + state machine (depends on 1–2).
   **First E2E milestone:** sample question → CaseFile → Thor/Loki claims with valid citations → one attack each way → Odin rulings → minimal Markdown briefing, all events in the audit log, run from a CLI script.
4. Phase 4 second run + memory + budgets/failures (depends on 3).
5. Phase 5 briefing/API, then Phase 6 dashboard (start a minimal UI right after the API contract stabilises), Phase 7 validation.

Minimum implementation per PS §3.3 criterion: (1) ingest + CaseFile + trade parser + event verification; (2) hybrid search with country+sector/tier filters; (3) per-advocate search tool calls logged; (4) cross-exam step; (5) Odin rulings + validator, at least one conceded/rejected arising from evidence; (6) briefing builder; (7) dashboard panels; (8) SendBack loop with novelty check on evidence; (9) memory store + logged change; (10) damaged-file handling + limits.

## Phase 1 verification (2026-10-25)
- `.venv/Scripts/python -m pytest` → 214 passed (59 Phase 0 + 155 new: parsers 59, trade 42, injection/relations 29, pipeline 18, dev pack 7).
- `.venv/Scripts/python -m backend.ingest data/runemark/dev_pack_E5` → exit 0, 0 errors. 76 docs (docx 16, pdf 30, txt 29, unreadable 1); valid 74, damaged 2 (0-byte file → empty; cut-off copy → truncated); 2 exact duplicates; 2 possible duplicates (empty same-title copy, cut-off copy at 43%); 1 correction linked to the report it corrects; 3 high injection flags all in one paragraph (the known trap); 1 mixed-encoding file decoded losslessly (utf-8+utf-16-le); 3 docs after pack as_of reported; 9 trade tables, 98 rows all valid; 4 rows warned "identical to previous month"; 2 maize notes flagged SECTOR conflict (content says maize).
- Correction of a Phase 0 fact: the UTF-16 body is NOT truncated (even length, ends with an encoded newline, 0 replacement chars).
- DB: logs/ragnarok.db (gitignored).

## Phase 1 design notes (for later phases)
- Row IDs: `<table_id>#R<n>`; prose tables use the doc ID as table ID, rows numbered in document order with `paragraph_ref` to the [Pn] paragraph. Fixed tables use TABLE_ID. Repeated row numbers get the next free number after the max (reason recorded).
- Values stored in millions of currency (unit "USD M"); a value with no scale and no table unit is invalid, never guessed.
- `Paragraph.evidence_text` is what agents must see (None = same as text). The citation validator (Phase 3) must accept quotes matching `text` or `evidence_text` after whitespace normalisation only.
- `DocMeta.pub_date` may be None only for unreadable files without manifest metadata: the as_of gate must treat None as "not provably in window" → block.
- Retrieval should hide `is_exact_duplicate` docs by default; possible duplicates stay visible with their flag.
- Trade-table sector (from content) can differ from document SECTOR metadata; Phase 2 sector filters should match either.
- Audit events for ingestion use case_id `ingest:<pack_id>`, agent heimdall; types INGEST, DAMAGED_INPUT, TRAP_INJECTION, ERROR (the PS name "DOC_DAMAGED" maps to DAMAGED_INPUT).
- Pack ingestion accepts any folder path; restricting uploads to approved dirs and size limits for POST /packs is Phase 5 (size limit already applied per file via MAX_UPLOAD_BYTES).

## Phase 2 verification (2026-10-25)
- `.venv/Scripts/python -m pytest` → 258 passed (44 new: retrieval 24, calc + citations 20; run time ~30 s with the real local embedding model).
- `python -m backend.search "Tolan wheat imports after the corridor agreement expired" --as-of 2027-01-25 --country Tolan --max-reliability 2 --limit 4` → 4 hits from 49 candidates, all Tolan, tier ≤ 2, published ≤ as_of, each with doc#paragraph, date/time, tier, source, scores.
- `... "maize import values Midgard" --country Midgard --sector maize --max-reliability 2` → the maize trade note mis-tagged SECTOR Wheat is found via its table commodity.
- Repeating a query with different case/trailing punctuation → `[REUSED from query #N]` in 0.8 s.
- Dev-pack calc demo (scratch script, not in repo): yoy_change % for every two-year trade table under as_of 2027-01-25 → 8 records, 0 exclusions, all `verify` = True; explicit request for the post-as_of trade note's rows → blocked.
- First search on a fresh DB embeds all paragraphs (~10 s for the dev pack); later processes reuse stored embeddings (<1 s).

## Phase 2 design notes (for later phases)
- Embedding choice: fastembed + `BAAI/bge-small-en-v1.5` (local, no torch, ~65 MB, tested in Phase 0 and Phase 2). One model, one vector index; vectors cached in the `embeddings` table by sha256(text) + model.
- Agents must call RetrievalService with their own `agent` and the case's `case_id`/`run_number` so QUERY/RETRIEVED land in the case trace; the cache key includes the case, so cross-case reuse never happens.
- SearchHit.text / DocView paragraphs are evidence text (flagged spans withheld). `read_doc(original_text=True)` is for the dashboard/Odin audit only.
- Calculations: agents should pass `require_complete=True` (default); a partial result is only acceptable when the claim states the exclusions. Save records with `save_calculation` so the validator and Odin can replay them.
- `validate_claim` = existence + quote + date + calc reproducibility. It does not judge support; Odin does.
- RowStatus.OUT_OF_WINDOW is not used: out-of-window rows are withheld, not returned with a status.

## Phase 3 verification (2026-10-25)
- `.venv/Scripts/python -m pytest` → 289 passed (31 new in tests/test_trial.py with a scripted model, tests/fake_llm.py). Mutation check: disabling Odin's "no established with hard failures" guard makes the injection test fail.
- Live schema check: all 7 LLM schemas compile on the API (after flattening: every property required; per-tool request lists; Odin split into two calls).
- Real runs on the sample question (as of 2027-01-25):
  1. case-20261025-082407: failed at Heimdall, "Schema is too complex" (controlled FAILED). Fixed.
  2. case-20261025-083612 (--stop-after THOR_LOKI): Heimdall + Thor/Loki OK (SAFE CHECKPOINT).
  3. case-20261025-084027: DONE, but trade-row citations never validated (rendered rows differed from the source text) and the 12-call tool budget ran out, so 0 defenses. Both fixed.
  4. **case-20261025-084715-fa6fe3: DONE, the Phase 3 evidence case** (copied to logs/demo/). Event established (tier-1 notice; renewal report recognised as corrected). 11 claims (Thor 6, Loki 5, 0 rejected in code); 6 attacks (3 each way); 2 defenses with new evidence, 4 concessions; Odin ruled 11/11: 5 established, 2 contested, 4 conceded, 0 rejected; briefing status partial (Odin: insufficient). Ranges (USD M, year-on-year fall in import value): Midgard wheat Thor 104.2-216.2 / Loki 50.9-216.2 / Odin 104.2-216.2; Midgard maize Thor 105.7-126.4 / Loki 52.9-126.4 / Odin 105.7-126.4; Tolan wheat Thor 46.5-96.0 / Loki 22.8-96.0 / Odin insufficient; Tolan maize no trade data (insufficient). Audit (scratch script): 53 citations (24 unique) all valid, in the manifest, published <= as_of; 9/9 exposure calcs replay identically.
  5. case-20261025-085334: stopped by the API workspace usage limit ("regain access on 2026-11-01") during cross-exam responses; FAILED recorded honestly, no briefing fabricated.
- Usage per completed case: about 430k tokens (Sonnet 5.5 for Heimdall/advocates, Opus 5.5 for Odin), about 6 minutes.

## Phase 3 design notes (for later phases)
- Agents use structured outputs, not native tool_use: the model returns typed tool-request lists; code checks permissions and budgets, runs tools with the case as_of and feeds results back wrapped. Calls are stateless (no thinking-block replay).
- Schemas sent to the model (agents/schemas.py `_LLM`) mark every property required; optional properties blew up the grammar ("Schema is too complex" / "compiled grammar is too large"). Keep new schemas flat.
- Odin's prompt now has a <calculations> section (each calc record replayed by code). Added after case 4, where Odin left Tolan/wheat insufficient because he could not see the advocates' calc records. Verified with the scripted model only (API limit).
- SendBack: Odin's sufficiency verdict and missing-evidence list are logged as SUFFICIENCY and stored in rulings.json; Phase 4 turns them into HEIMDALL_RESEARCH.

## Phase 4 verification (2026-10-25)
- `.venv/Scripts/python -m pytest` → exit 0, 311 tests (289 Phase 3 + 1 config case + 21 in tests/test_phase4.py; scripted model, no API calls).
- test_phase4.py covers: two-run send-back with genuinely new evidence (refs absent from run-1 RETRIEVED events; Heimdall's repeated run-1 query refused; advocates' own non-cached run-2 searches; revise/withdraw/carry-over; Odin re-rules all active claims; effect logged; per-run files; briefing run history); run 2 with only old evidence → `incomplete`, advocates not re-run; duplicate / near-duplicate not new; run limit (2/2 LIMIT_HIT; max_runs=1 → no send-back); repeated send-back query refused after one repair; memory isolation (store + AgentEnv + prompts); lessons general (no names/IDs/digits) and written after rulings; memory read changes a query (MEMORY_APPLIED with original vs changed, baseline never executed); recalled-but-unchanged not claimed; memory persists into a later case; advocate failure in run 2 → unchallenged; both advocates / Odin fail in run 1 → FAILED + limitations.md, no briefing; Odin fails in run 2 → run-1 briefing incomplete; token budget hit in run 2 → graceful; evidence cap; cross-exam rounds bounded (round 2 + LIMIT_HIT); injected "always send back" text cannot exceed MAX_RUNS.
- Mutation check: making Novelty.why_not_new always return None fails test_run2_without_new_evidence_is_labelled_incomplete and test_duplicate_of_seen_document_is_not_new (file restored, tests green again).
- NOT verified: any real-model run of Phase 4 code. API probe on 2026-10-25: HTTP 400 "You have reached your specified workspace API usage limits. You will regain access on 2026-11-01 at 00:00 UTC." for Haiku and Sonnet. The new schemas (MemoryResearchTurn, SendBackPlan(M), AdvocateRevision, ResearchFindings) have not been compiled by the API yet (local JSON schema sizes 1.3–4.8 kB; AdvocateBrief, which compiled in Phase 3, is 3.7 kB).

## Phase 5 verification (2026-10-25)
- tests/test_api.py: 13 passed (lifecycle + results; SSE = stored events exactly; partial and failed reported; validation 422/400/404; 503 without key; 409 one case at a time; every briefing citation and estimate row resolves via /docs or /trade with matching quote and date; tampered citation dropped and tampered estimate shown unavailable; docs/trade as_of gating 403 + CLOCK_VIOLATION_BLOCKED; feed order/badges; ingest rejects outside dir, traversal, missing, non-zip, bad zip, ../ and absolute members, .exe, oversized, no manifest; approved dir + zip upload ingest then readable).
- Live server smoke (uvicorn on the real dev DB): /api/health provider gemini; /feed?as_of=2027-01-25 -> newest trade notes with badges, 3 docs withheld after as_of; /docs/<tier-1 notice>?as_of=2027-01-25 -> 7 paragraphs with anchors, same doc with as_of before its pub date -> 403; /trade/<table>/R1 -> valid row. No real-model case was created through the API (each two-run case is ~20+ min on the free Gemini tier).
- Bug found and fixed: case_dir compared resolve() paths, which differ on Windows before/after the folder exists -> intermittent 400; now the strict ID pattern alone guards the path.

## Phase 6 verification (2026-10-25)
- `npm run build` (tsc + vite build) OK; `.venv/Scripts/python -m pytest` -> 336 passed (335 + the empty-search hint test).
- Browser checks with headless Microsoft Edge 156 via playwright-core 1.64 (scratch scripts outside the repo; Edge launches only outside the command sandbox):
  1. Saved full case case-20261025-084715-fa6fe3 (Phase 3 Anthropic run): UI 128 events = API 128; 11 claim cards = 11 API claims; 4 exposure rows = 4 API rows; 29 feed docs marked retrieved; 30 briefing citations; clicking the first opened ORV-0016 with P1 highlighted; trace memory filter 0 rows (that case predates memory); no page errors except one 404 (favicon).
  2. Real Gemini case started from the UI, case-20261025-110349-21e64d: live via SSE (RUNNING, events streaming), then FAILED — gemini-3.5-flash daily free quota exhausted (429 x7, retries logged). UI showed FAILED + limitations correctly.
  3. case-20261025-111411-14a46e (flash-lite advocates, 3.8-flash judge): Heimdall OK + MEMORY_APPLIED, but every advocate search returned 0 candidates (models filtered event_id "orv"; packs use "E5") -> both advocates failed -> FAILED, honestly reported. Led to the empty-search hint fix.
  4. New AI Studio key (user, 2026-10-25), gemini-3.5-flash, case-20261025-111938-c5c54f: Heimdall -> Thor/Loki (9 claims) -> cross-examination (3 attacks), 1 MEMORY_APPLIED, live in the UI; then the new key's free daily quota ran out too (QuotaFailure GenerateRequestsPerDayPerProjectPerModel-FreeTier, retryDelay ~19.5 h). Stopped on user request (API restarted) -> reported as failed/interrupted at CROSS_EXAMINATION.
- Free-tier capacity observed: roughly 25-30 generate requests per day per model per project; one real case needs ~60-80 (one run) or more (two runs). A full real case needs billing enabled on the AI Studio project (or the Anthropic key after 2026-11-01).
- The user then reviewed the dashboard manually.

## LLM request economy verification (2026-10-26)
- `.venv/Scripts/python -m pytest` -> exit 0, 357 tests (336 + 21: tests/test_llm_economy.py 17, test_trial 2, test_phase4 1, test_api 1). No API calls.
- test_llm_economy.py: per-stage counts of a two-run case (22, <= 25; no cross-exam/defense/follow-up/Odin planning or separate baseline labels; llm_calls.json, LLM_USAGE, case_status calls_used/limit); one planning turn holds up to MAX_REQUESTS_PER_ROUND; extra turn only when the own search is missing; call cap -> LIMIT_HIT + graceful incomplete briefing (run 2 cut) or honest FAILED (run 1 cut); seeds via the query cache reach both advocates (RETRIEVED seed, reused) and both still search themselves; advocate without own search still fails; code-derived cross-exam searches logged as the advocate's QUERY events, >= 1 attack each way, defense with new evidence / concession; essential attack problem gets one repair; Odin merged -> two-step fallback; API outage not retried as fallback; Odin prompt has PRE-CHECK + replays and no planning turn; run 2 delta (Odin rules T2-1, L2-1 only; carried rulings keep run 1; L1-1 still conceded; effect logged); run-2 re-summary dropped; run 2 still needs genuinely new evidence; resume of a complete case = 0 backend calls, all LLM_CACHE_HIT, same history/verdicts, memory not reinforced twice; resume after Odin failure = 1 backend call (Odin) -> DONE; cache never shared across cases.
- Existing tests adjusted to the new defaults (assert changes only): Odin schema name OdinVerdict; defense without new evidence now 1 call (no repair; still an invalid defense); repeated send-back query refused by code without repair (residual logged); memory tests use the combined schema (MEMORY_APPLIED still has the no-memory original action, the memory used and the changed action); new test keeps the separate baseline mode and baseline-off covered. test_residual_allowed_returns_repaired_output runs with REPAIR_MODE=always.
- Injection tests unchanged and passing (cannot skip cross-exam, force established, change question/as_of, force endless send-backs).
- Mutation check: disabling the call cap in TokenLedger.check fails test_case_call_cap_finishes_gracefully (restored, green).
- `npm run build` OK (frontend: new event types, "model requests" filter group, calls/attempt in the status line, trial view from the latest attempt).
- NOT verified: any real-model run of the new code (no API calls made). Unknown: whether the real model fits its research into one turn (each miss = +1 call), how often residual-first drops content a repair would have fixed (e.g. paraphrased quotes), whether OdinVerdict (5.4 kB schema) compiles on Gemini / Anthropic (fallback exists for HTTP 400).

## Phase 4 design notes (for later phases)
- Stage names: HEIMDALL_RESEARCH added. BRIEFING requires a completed Odin result (go() guard); HEIMDALL_RESEARCH requires a pending SendBack and run_number ≤ MAX_RUNS.
- Claim IDs per run: T{run}-{n} / L{run}-{n}; attack IDs A{run}-{T|L}{n} continue across rounds; withdrawals W{run}-{claim}. Superseded (revised/withdrawn) claims are not re-ruled; their earlier rulings stay in run-N/rulings.json and the briefing lists them.
- Briefing status: incomplete = Odin still insufficient at the end; partial = sufficient but with notes/unruled; complete otherwise. Briefing JSON gained `runs` (RunSummary) and `superseded`.
- Memory recall stages: research, sendback, brief, cross_exam, ruling. Lesson `context` keeps the unmasked case details (audit only, never in prompts). memory.json in each case folder is a snapshot of the involved agents' memories.
- Advocate `searches` now counts only executed (non-cached) searches.
- Real runs cost: the baseline plan adds one extra research-planning call per agent per run when that agent has lessons (Heimdall, Thor, Loki; not Odin). Estimated two-run case ≈ 800k tokens.
- Demo plan (task 8): case A = sample question with MAX_RUNS=2 (memory starts empty in logs/ragnarok.db, so memory influence can only appear in run 2 from run-1 lessons); if no MEMORY_APPLIED appears, run case B (same question) — Heimdall/advocates then recall case A's lessons in run 1.

## Known problems / risks
- Trade data layout in the dev pack differs from the PS description (prose vs fixed tables): support both.
- Sector metadata can be wrong; commodity must be read from content.
- Final-round packs: unseen events, damaged tables (cut-off, missing value, repeated row, bad number).
- GitHub API rate limit on this IP (worked around with zip download).
- Injection patterns are regex-only: tuned for recall on English; unseen attacks with new wording may pass (classification could be added where useful). Low-severity hits are stored but not logged as TRAP_INJECTION.
- Truncation heuristic = last own paragraph ≥4 words without closing punctuation; a doc legitimately ending in a list/figure could be flagged (only one hit in the dev pack, a real cut-off copy).
- Retrieval relevance is only spot-checked (no labelled eval set); BM25 stemming is a light suffix strip.
- The vector ranker ranks every candidate, so a nonsense query still returns its nearest paragraphs (no score threshold).
- API workspace usage limit reached on 2026-10-25: no real-model runs until 2026-11-01 00:00 UTC (or until the limit is raised in the Anthropic console).
- `.env` still overrides the new defaults with old values (LLM_MAX_OUTPUT_TOKENS=4096, REQUEST_TIMEOUT_S=120, MAX_TOOL_CALLS_PER_AGENT=12, MAX_TOOL_CALLS_PER_CASE=60, MAX_TOKENS_PER_AGENT=150000, MAX_TOKENS_PER_CASE=600000); real runs used env-var overrides. The user should update .env (see .env.example).
- Odin's ranges in case 4 coincide with Thor's bounds for Midgard (same calc records, not averaged): plausible, but watch judge independence.
- Advocate estimates are signed year-on-year changes; bounds match |result|; the sign convention lives in the metric definitions.
- The fixed-table layout is implemented from the PS description only (no real sample yet); whitespace tables are aligned by column-name positions.
- CLAUDE.md, PROGRESS.md, data/TRAPS_FOUND.md and .claude/settings.json are tracked in git (committed in 2a8cf08, on origin/Amogh), so .git/info/exclude does not hide them. The user decides whether to untrack them (`git rm --cached`, run by the user).

- Phase 4 real-model behaviour unknown: whether Odin sends back on the dev pack, whether run 2 finds new evidence, whether the models fill memory_used, and whether the new schemas compile. If a schema is "too complex", flatten it like Phase 3.
- Memory influence detection compares a no-memory baseline plan with the memory plan; model randomness also changes wording, so MEMORY_APPLIED additionally requires the agent to name the lesson. The diff is logged in full so a reader can judge.
- Lesson masking is heuristic (known country names from the store + capitalised multi-word names + IDs/dates/numbers). A single capitalised proper noun at the start of a sentence may survive. Test: test_lessons_are_general.
- The dev DB logs/ragnarok.db will accumulate memories across real cases (by design: persistent). To start a demo with empty memory, the user must decide (no deletion done by Claude).

- Request economy trade-offs (2026-10-26): (1) the combined memory baseline is weaker evidence than a separate no-memory call (the model writes both plans knowing its lessons); MEMORY_BASELINE_MODE=separate restores the independent baseline at +1 call per memory-planned turn. (2) Odin no longer computes his own calcs by default; his range bounds must be results of the advocates' calc records (ODIN_RESEARCH_ROUND=true restores his tool turn). (3) residual-first drops invalid optional parts (e.g. a citation with a paraphrased quote) instead of asking for a fix. (4) Attack searches are derived from the targeted opponent claim plus generic side cue words, because the attack itself does not exist before the single AttackSet call; defense searches are derived from the attack's objection and gap. (5) Heimdall seeds match country/sector names of in-window metadata in the question text, so the exporter named in a question is also seeded (harmless, one extra search).
- Resume replays depend on identical prompts: a code or prompt change between attempts turns the remaining steps into live calls (correct, just not free).

- Dashboard gaps (API cannot supply yet; shown honestly, nothing invented): (1) documents published after as-of are excluded from GET /feed, so the timeline cannot place them by date: shown as a hatched marker + count, and blocked IDs from CLOCK_VIOLATION_BLOCKED events (in "Damaged or flagged") with no content; (2) Odin's ranges per run are not exposed per run, only the NEW_EVIDENCE effect's range changes (run table shows those); (3) briefing status exists only for the final run (earlier runs: "Not issued (sent back)"); (4) calculation records are shown only when their trade_calc RETRIEVED event is in the case log (no calc endpoint); (5) the only saved full case predates Phase 4 (no runs/memory/send-back), so the run-2 and memory blocks were verified only in their empty states; check them on the first real two-run case.
- `npm install` reports existing audit advisories in the dev toolchain; not force-fixed (would change pinned versions).

## Next steps
0. First real check of the request economy: probe Gemini once; then one real two-run case (sample question) and compare llm_calls.json with the table above; if a step overruns (extra planning turns, repairs), tune MAX_REQUESTS_PER_ROUND / prompts, not the caps. If the daily quota runs out mid-case, resume the next day with `--resume <case_id>`.
1. When the API is available again (2026-11-01 00:00 UTC, or after the user raises the workspace limit): run the real two-run demo (command in Notes) and save it to logs/demo/; check MEMORY_APPLIED; if absent, run case B. Then tick the remaining Phase 4 criteria with evidence.
2. Get LLM capacity for one full real case: enable billing on the AI Studio project (or LLM_PROVIDER=anthropic after 2026-11-01). Then run the sample question through the UI, check every panel against GET /cases/{id}, save to logs/demo/ (`--save-demo` or copy the case folder) — this also closes the Phase 4 demo item.
3. Phase 7: README, architecture diagram, reproducible demo logs, unseen-pack dry run, final validation.

## Notes for next session
- LOCAL ONLY, never commit: CLAUDE.md, PROGRESS.md, .claude/, data/TRAPS_FOUND.md (excluded via .git/info/exclude). Committed files must not reference them.
- Read CLAUDE.md (§17–19), this file and `git log` first. Confirm branch is Amogh.
- Run tests: `.venv/Scripts/python -m pytest` (357 on 2026-10-26; needs the local embedding model in data/index/models; makes no API calls).
- Model requests per case: see `logs/cases/<id>/llm_calls.json` (summary by agent/stage/label) and the LLM_USAGE event; GET /cases/{id} has calls_used/calls_limit. Resume a failed case: `.venv/Scripts/python -m backend.trial --resume <case_id>` or POST /cases/{id}/resume (finished steps replay from the case's own cache, LLM_CACHE_HIT events).
- Call-count measurement script (scratch, outside the repo): it ran the scripted trials under the legacy profile (MAX_RESEARCH_ROUNDS=3, MAX_REQUESTS_PER_ROUND=5, HEIMDALL_SEED_SEARCHES=0, SHARE_SEEDS_WITH_ADVOCATES=false, CROSS_EXAM_CODE_SEARCH=false, ODIN_MERGED_CALL=false, ODIN_RESEARCH_ROUND=true, DELTA_RUN=false, SENDBACK_FOLLOWUP_LLM=true, REPAIR_MODE=always, MEMORY_BASELINE_MODE=separate) and the new defaults; test_llm_economy.py::test_two_run_case_fits_the_free_tier_budget is the in-repo equivalent.
- Trial: `.venv/Scripts/python -m backend.trial "<question>" --as-of 2027-01-25` writes logs/cases/<case_id>/ (real API calls; one run about 430k tokens, two runs about 800k).
- Phase 4 demo (Git Bash, from the project root; env overrides because .env still has old limits):
  `MAX_RUNS=2 MAX_TOOL_CALLS_PER_AGENT=45 MAX_TOOL_CALLS_PER_CASE=180 MAX_TOKENS_PER_AGENT=450000 MAX_TOKENS_PER_CASE=1500000 LLM_MAX_OUTPUT_TOKENS=16000 REQUEST_TIMEOUT_S=300 MAX_EVIDENCE_PER_CASE=400 .venv/Scripts/python -m backend.trial "As of 25 January 2027, how exposed are Midgard and Tolan to the end of the Orvan corridor agreement? Give a low and high range for wheat and maize imports." --as-of 2027-01-25 --save-demo`
- Probe the API first with one tiny call (a 400 "workspace API usage limits" means still blocked).
- Search: `.venv/Scripts/python -m backend.search "<query>" --as-of 2027-01-25 [--country X --sector Y --max-reliability 2]`; hot ingest: `... -m backend.search --ingest <pack_dir>`.
- Ingest: `.venv/Scripts/python -m backend.ingest data/runemark/dev_pack_E5` (→ logs/ragnarok.db; re-running is idempotent).
- Rebuild synthetic fixtures (only if the builder changes): `.venv/Scripts/python tests/fixtures/build_fixtures.py`.
- Re-fetch/verify data: `.venv/Scripts/python scripts/fetch_dev_pack.py [--verify-only]`.
- Start API: `.venv/Scripts/python -m uvicorn ragnarok.api:app --app-dir backend --port 8000` → GET /api/health, Swagger at /api/docs. Endpoints listed in the api.py docstring.
- Dashboard: `cd frontend && npm install && npm run dev` → http://localhost:5173 (open a case with #case=<id>). Details in frontend/README.md.
- Before any real run, probe Gemini once: a 429 with QuotaFailure "...PerDay..." means the free daily quota is gone (retryDelay says when it resets).
- Never hard-code dev-pack IDs/values; scratch analysis scripts lived outside the repo.

## Bonus feature: Argument map (2026-10-26)
- New dashboard view "Argument map" (`#view=map`): frontend/src/lib/argmap.ts (pure layout: lanes per claim,
  evidence -> claim -> attacks -> responses -> Odin ruling; doc nodes placed by barycentre) and
  frontend/src/views/ArgumentMapView.tsx (SVG edges + button nodes, hover/select focus, detail panel, side/run filters,
  empty states). Built only from recorded trial events; no backend change, no AI requests.
- Verified (headless Edge, real saved cases): 204050-ac35da 34 nodes (8 docs, 7 claims, 6 attacks, 4 defenses,
  2 concessions, 7 rulings) = Trial view counts; 084715-fa6fe3 45 nodes; filters, Enter/Esc keyboard, citation
  click-through to Evidence, no page side-scroll at 1280 / 390 px; tsc + vite build clean.
- Not yet in assets/Ragnarok_Dashboard_Guide.pdf.

## Final validation (2026-10-26, new Gemini key in a new Google project)
- Key probe OK (gemini-3.5-flash, 2.3 s). Servers restarted with new key + latest code.
- REAL two-run demo: logs/demo/case-20261026-005913-e4e654 (24 requests, 0 repairs). Send-back -> 13 new refs
  (ORV-0005, Orvan->Ravik rail) -> T2-1 added (established), L1-1 revised -> L2-1, L1-2 withdrawn; 6 MEMORY_APPLIED.
  Replayed from cache (0 requests) after the briefing fix -> 5 established / 2 contested / 1 conceded, incomplete
  (Tolan maize data absent from pack). Dashboard checks 35/35 + 25/25 on it.
- Unseen data: scripts/build_random_pack.py (random world per seed, all PS traps, 4 random table layouts) +
  scripts/check_unseen_pack.py (zip upload via POST /ingest, checks via /feed /docs /trade). Seeds 11, 2024, 777:
  26/26 each. Real trial seed 11: case-20261026-011234-6779fc complete briefing, 12 requests, injection withheld.
- Bugs found and fixed:
  1. Withdrawn claims were listed only as "superseded" -> now under conceded findings (machine._briefing, build_briefing).
  2. Ranges mixing calc kinds (sum + yoy_change), negative net_offset read as exposure, fall+rise merged ->
     estimates._metric_problems (one repair, else dropped); prompts state the rule. Test test_range_must_measure_one_metric.
  3. Quota pause waited for the daily reset even when a chain model was only cooling down after 503s ->
     pause until the earliest free model. Test test_pause_ends_when_the_first_model_is_free_again.
  4. frozenset in SearchFilters serialisation warning (retrieval/service.py).
- README rewritten for evaluators (criteria -> evidence table, demo walkthrough, unseen-data results).
- Dashboard guide PDF updated with the Argument map page.
