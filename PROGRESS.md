# PROGRESS — Trial of the Nine Realms

Last updated: 2026-10-25 (end of Phase 0). Branch: Amogh.

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

### Phase 1 — Ingestion and evidence storage
- [ ] Pack discovery: any folder with manifest.json (dev pack + live packs); manifest normaliser (mixed key case/types)
- [ ] Header parser (`KEY: value` until `---`); merge with manifest, record conflicts, keep raw
- [ ] TXT decoding: BOM detection, segment-wise decode (header and body may differ), charset fallback, flag bad_encoding/truncated
- [ ] PDF (pypdf) and DOCX (python-docx) text extraction; header from first text
- [ ] Paragraph splitter on `[Pn]` markers (unwrap PDF lines); fallback to blank-line split when no markers
- [ ] Damage flags: empty, truncated (mid-sentence end / odd-byte), unparseable, missing header, metadata conflict
- [ ] Injection scanner (role labels, "ignore/skip/approve" imperatives, hidden text, odd encodings); flags only, text preserved
- [ ] Duplicate detection: exact (normalised body hash) → duplicate_of; near-duplicate/truncated copies → near_duplicate_of (not merged)
- [ ] Correction/retraction relations (source_type, title cues) — generic, no IDs
- [ ] Trade parser: prose layout + PS fixed layout → TradeTable/TradeRow, row validation (missing value, bad number, repeated row, truncated table); commodity from Route line, conflict with SECTOR flagged
- [ ] SQLite store (documents, paragraphs, trade tables/rows, flags) + content hashes; idempotent re-ingest
- [ ] Tests incl. synthetic damaged files and a synthetic unseen pack

### Phase 2 — Hybrid retrieval and calculations
- [ ] BM25 (rank-bm25) + fastembed vectors over paragraphs; RRF fusion
- [ ] Filters: country, sector/commodity, event_id, source_type, tier, date range; as_of mandatory, enforced on every path, CLOCK_VIOLATION_BLOCKED logged
- [ ] Exact duplicates hidden by default; query cache with logged reuse
- [ ] Trade-row access by table/row with as_of gate
- [ ] calc/: sums, YoY change, share, period windows, offsets — CalculationRecord with row refs; invalid rows excluded with reason

### Phase 3 — Basic end-to-end trial
- [ ] llm/ client: structured output (messages.parse), one repair attempt, retries, timeouts, token accounting
- [ ] Heimdall: question → CaseFile, event verification (established/disproved/uncertain)
- [ ] Thor ∥ Loki: own searches, claims with citations + estimates
- [ ] Cross-exam: ≥1 attack each way; defense with new evidence or concession
- [ ] Odin: per-claim rulings, citation validator, sufficiency → briefing or SendBack
- [ ] Audit log events for every step

### Phase 4 — Second run, memory, failure handling
- [ ] SendBack → Heimdall new targeted searches → new evidence → advocates reconsider → Odin reassesses
- [ ] Private per-agent memory (SQLite), MEMORY_READ/WRITE, logged behaviour change
- [ ] Budgets (tool calls, tokens, runs, rounds, retries) with LIMIT_HIT; agent failure paths; injection tests

### Phase 5 — Final briefing and API
- [ ] Briefing from rulings only; exposure table Thor/Loki/Odin; outlook; inline citations; Markdown + JSON export
- [ ] Endpoints: create case, status/results, SSE events, doc/paragraph, trade table/row, ingest pack, evidence feed

### Phase 6 — Functional dashboard
- [ ] Question box, live feed (replayed docs), trial view, exposure table, briefing + trace, click-through

### Phase 7 — Final validation and submission
- [ ] Full two-run demo case with saved logs (logs/demo/), README, architecture diagram, unseen-pack dry run

## Setup facts (verified Phase 0)
- OS: Windows 11 Home 10.0.26200. Shells: Git Bash + PowerShell 5.1.
- Python: 3.12.4 venv at `.venv` (3.13 and 3.14 also installed; 3.12 chosen for wheel compatibility).
- Node v25.9.0, npm 11.12.1, pnpm 12.10.1, uv 0.12.17; yarn not installed.
- `git config core.longpaths true` (repo-local). Hooks pre-commit/pre-push installed and tested. CLAUDECODE=1 in Claude Code's shell.
- Unauthenticated GitHub API was rate-limited for this IP; the dev pack is fetched as a zip from codeload.github.com instead.

## Models (verified with this key, 2026-10-25)
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

## Known problems / risks
- Trade data layout in the dev pack differs from the PS description (prose vs fixed tables): support both.
- Sector metadata can be wrong; commodity must be read from content.
- Final-round packs: unseen events, damaged tables (cut-off, missing value, repeated row, bad number).
- GitHub API rate limit on this IP (worked around with zip download).

## Next steps
Start Phase 1 (ingestion and evidence storage) from the checklist above.

## Notes for next session
- Read CLAUDE.md (§17–19), this file and `git log` first. Confirm branch is Amogh.
- Run tests: `.venv/Scripts/python -m pytest` (59 passing at end of Phase 0).
- Re-fetch/verify data: `.venv/Scripts/python scripts/fetch_dev_pack.py [--verify-only]`.
- Start API: `.venv/Scripts/python -m uvicorn ragnarok.api:app --app-dir backend` → GET /api/health.
- Never hard-code dev-pack IDs/values; scratch analysis scripts lived outside the repo.
