# PROGRESS — Trial of the Nine Realms (Odin Implementation)

## Project Overview
- **Project**: Trial of the Nine Realms — Supply Chain Disruption Impact Analyzer (RAGNAROK Hackathon)
- **Role**: Senior Python Backend Engineer — Odin (Judge), Trial Orchestration, and Evidence-Grounded Briefing
- **Branch**: `Odin`

---

## Repository Discovery & Baseline (Phase 0)

### Current Repository State
- **Git Branch**: `feat/trial-briefing`
- **Initial Commits**: 
  - `7a7c385` (Revise README for 'Trial of the Nine Realms' project)
  - `c10ed2f` (Initial commit)
- **Teammate Branches**: `origin/aditya`, `origin/pranav`, `origin/main` (all currently at `7a7c385`).
- **Existing Files in Repo at start**: `README.md`
- **Reference Problem Statement**: Ingested from `Nodal-leaf/Problem-Statements-RAGNAROK` (`03_Ragnarok Trial of the Nine Realms`).
- **Test Dataset**: `dev_pack_E5` (76 documents: PDF, TXT, DOCX; `manifest.json`, `hashes.sha256`, `sample_question.txt`).

### Python Environment
- Python 3.14.7
- Key Packages Installed:
  - `pydantic` 2.13.5
  - `fastapi` 0.141.1, `uvicorn` 0.52.4
  - `langgraph` 1.2.17, `langchain-core` 1.7.0
  - `anthropic` 2.3.0
  - `pytest` 9.1.1
  - `python-docx` 1.2.0, `pymupdf` 1.28.2, `pypdf` 6.19.0
  - `rank-bm25` 0.2.2

---

## Contract Definitions & Integration Interfaces

Because teammates have not yet pushed `backend/` code to remote branches, we establish the clean, standardized Pydantic v2 contract specified in the project guidelines so that teammate modules can dock seamlessly without impedance mismatches.

### 1. Data Models (`backend/models.py`)
- **`DocMeta`**: Document metadata matching `manifest.json` (`DOC_ID`, `PUB_DATE`, `RELIABILITY` (Tiers 1-4), `COUNTRY`, `SECTOR`, `SOURCE_NAME`, `SOURCE_TYPE`, `FORMAT`).
- **`Document`**: Parsed document representation with structured paragraphs (`Pn`), raw text, metadata, and data-integrity flags (`is_damaged`, `is_retracted`, `is_duplicate`, `injection_detected`).
- **`TradeRow`**: Structured monthly trade flow (`table_id`, `row_num`, `country_pair`, `sector`, `month`, `value`, `volume`, `unit`, `is_damaged`).
- **`CaseFile`**: Case identifier, user query, normalized as-of date (`YYYY-MM-DD`), targeted country-sector pairs, and event verification status (`real`, `uncertain`, `not_real`).
- **`Claim`**: Advocacy claim submitted by Thor/Loki:
  - `claim_id`: Unique identifier (e.g. `THOR-C1`, `LOKI-C1`)
  - `agent`: `thor` or `loki`
  - `country`: Target country
  - `sector`: Target sector
  - `posture`: `high` or `limited`
  - `statement`: Text of the claim
  - `estimate_low`: Optional numeric value
  - `estimate_high`: Optional numeric value
  - `unit`: Currency/volume unit
  - `citations`: List of citation references (`doc_id`, `paragraph_num`, `quoted_text`, `trade_row_ref`)
  - `nature`: `sourced_fact` or `inference`
- **`Attack`**: Cross-examination challenge attacking an opponent's claim with counter-evidence.
- **`Defense`**: Response to an attack with either new evidence or an explicit concession.
- **`Concession`**: Explicit record of a conceded claim.
- **`Ruling`**: Odin's binding judicial ruling on a claim:
  - `claim_id`: Matching claim
  - `verdict`: `established`, `contested`, `conceded`, or `rejected`
  - `basis`: `sourced_fact` or `inference`
  - `rationale`: Explanation grounded in evidence
  - `disqualified_reason`: Specific reason if rejected deterministically
  - `admissible_citations`: List of citations that passed deterministic eligibility checks
- **`ExposureRange`**:
  - `country`: Country
  - `sector`: Sector
  - `thor_range`: `(low, high)`
  - `loki_range`: `(low, high)`
  - `odin_range`: `(low, high)` or `None` if unresolved
  - `status`: `resolved` or `unresolved`
  - `rationale`: Grounded explanation
- **`SendBack`**: Structured missing evidence request:
  - `missing`: List of actionable, specific gap descriptions
  - `gap_type`: e.g. `missing_baseline`, `unresolved_contradiction`, `tier4_only`, `unverified_event`
- **`Briefing`**: Complete final intelligence briefing with sections A through J, JSON & Markdown exports.
- **`LogEvent`**: Structured audit event for SQLite and SSE streaming.

### 2. Integration Adapters & Mocks
To maintain modularity and isolation:
- Mocks/Adapters for `Heimdall`, `Thor`, `Loki` will be provided for deterministic testing of the graph, without overwriting teammate implementations when they arrive.
- Shared LLM wrapper in `backend/llm.py` with mock support for cost-free, deterministic unit testing.
- Shared SQLite and JSONL logbook in `backend/logbook.py`.

---

## Phased Implementation Checklist

- [x] **Phase 0 — Repository Discovery and Contract Definition**
  - [x] Inspect Git status, branches, commit logs, file tree
  - [x] Read official problem statement and dev_pack_E5 specifications
  - [x] Check Python environment and install core requirements (`langgraph`, `anthropic`, etc.)
  - [x] Define contracts for Models, Rulings, SendBack, Briefing, and Logging
  - [x] Create `PROGRESS.md` and report baseline findings to team

- [x] **Phase 1 — Odin System Prompt and Structured Judgment Engine**
  - [x] Create Odin prompt (`backend/agents/prompts/odin.md`) with role, rules, untrusted-evidence security, and ruling schema
  - [x] Implement deterministic eligibility checker in Python (`backend/agents/odin.py`):
    - [x] As-of date enforcement (clock check)
    - [x] Document and paragraph existence check
    - [x] Quote match verification
    - [x] Source reliability tier evaluation (Tier 1-3 allowed; Tier-4-only rejected)
    - [x] Retraction / correction checks
    - [x] Duplicate and damaged document checks
    - [x] Damaged trade row checks
    - [x] Prompt-injection detection and isolation
  - [x] Implement LLM semantic judgment engine with structured Pydantic output
  - [x] Implement complete claim coverage enforcement (every claim ruled exactly once; deterministic rejections cannot be overridden)
  - [x] Unit tests (`tests/test_odin.py`, `tests/test_odin_evidence.py` - 20/20 passing)

- [x] **Phase 2 — Odin's Exposure Ranges and Sufficiency Checker**
  - [x] Country-sector unit of analysis mapping
  - [x] Deterministic trade calculations (no mental arithmetic by LLM)
  - [x] Evidence-grounded exposure range determination (`odin_range` based on admissible evidence, not blind averaging)
  - [x] Structured sufficiency checker (`assess_sufficiency`):
    - [x] Distinguish sufficient vs insufficient vs limits exhausted
    - [x] Allow uncertainty disclosure for contested claims without failing trial
  - [x] Actionable, specific `SendBack` requests
  - [x] Tests (`tests/test_odin_sufficiency.py`, `tests/test_trade_calc.py` - 21/21 passing, 41/41 total)

- [x] **Phase 3 — Odin Memory, Audit Logging, and Resource Budgets**
  - [x] Private memory isolation (Odin private memory read/write only, strict permission enforcement)
  - [x] SQLite and JSONL append-only audit logbook integration (`LogBook`, recursive secret redaction)
  - [x] Resource budgets: token tracking, max tool calls (`MAX_TOOL_CALLS_PER_AGENT=12`), max retries (`MAX_RETRIES=2`), timeout handling, limit exhaustion graceful fallback
  - [x] Tests (`tests/test_odin_memory.py`, `tests/test_odin_logging.py`, `tests/test_odin_budgets.py` - 20/20 passing, 61/61 total)

- [x] **Phase 4 — LangGraph Trial State Machine and Send-Back Loop**
  - [x] LangGraph state definition (`TrialState`) with disjoint parallel updates and typed fields
  - [x] Build trial state machine graph:
    - [x] HEIMDALL verification -> THOR & LOKI parallel -> CROSS-EXAMINATION -> ODIN -> SUFFICIENCY CHECK -> (SEND-BACK to HEIMDALL or READY_FOR_BRIEFING)
  - [x] New evidence detection for Run 2 (hash/ID comparison, admissibility filtering)
  - [x] Termination conditions and bounds (`MAX_RUNS`, `MAX_ROUNDS`, `MAX_TOOL_CALLS_PER_AGENT`, `MAX_TOKENS_PER_CASE`)
  - [x] Run snapshot persistence to `logs/cases/<case_id>/run_<n>.json` with secret redaction
  - [x] CLI runner (`python -m backend.trial "<question>" --as-of YYYY-MM-DD`)
  - [x] Tests (`tests/test_trial_graph.py`, `tests/test_trial_limits.py` - 15/15 passing, 76/76 total)

- [x] **Phase 5 — Final Briefing Generation and Citation Validation**
  - [x] Briefing generator (`backend/briefing.py`) strictly grounded in Odin's rulings
  - [x] Sections A through J implementation
  - [x] Strict inline citation validator (`[DOC_ID Pn, YYYY-MM-DD]`, `<table/doc>#<row>`)
  - [x] Markdown and JSON exporters
  - [x] Integration with Phase 4 LangGraph trial state machine (`node_briefing`)
  - [x] Comprehensive test suite (`tests/test_briefing.py` - 18/18 passing, 94/94 total)

- [x] **Phase 6 — FastAPI Integration and Case Persistence**
  - [x] FastAPI application entry point and factory (`backend/app.py`)
  - [x] Request and response Pydantic schemas (`backend/api/schemas.py`)
  - [x] Case and trial registry with concurrency locks (`backend/case_store.py`)
  - [x] Service layer executing LangGraph trial and LogBook events (`backend/api/service.py`)
  - [x] REST routes (`backend/api/routes.py`):
    - [x] `GET /health`: Health check (process + database)
    - [x] `POST /api/cases`: Create case with Pydantic validation
    - [x] `GET /api/cases`: List cases with pagination
    - [x] `GET /api/cases/{case_id}`: Retrieve case metadata
    - [x] `POST /api/cases/{case_id}/trials`: Start/execute trial (synchronous or background, 409 on duplicate concurrent execution)
    - [x] `GET /api/cases/{case_id}/trials/{trial_id}`: Sanitized trial status
    - [x] `GET /api/cases/{case_id}/trials/{trial_id}/rulings`: Odin's final rulings
    - [x] `GET /api/cases/{case_id}/trials/{trial_id}/briefing`: Phase 5 validated briefing (409 if pending research)
  - [x] Error handling & security: sanitized errors (400, 404, 409, 422, 500), zero leakage of raw traces, API keys, or private memory
  - [x] Comprehensive test suite (`tests/test_api.py` - 22/22 passing, 116/116 total)

- [x] **Phase 7 — Final Validation, Adversarial Evaluation & Demo Pack**
  - [x] Synthetic fixture catalog and loader (`demo/fixtures/manifest.json`, `demo/fixtures/loader.py`)
  - [x] Dedicated adversarial evaluation suite covering 12 threat categories A–L (`tests/test_adversarial.py`, `demo/adversarial_manifest.json`, `demo/adversarial_runner.py`)
  - [x] Deterministic financial and exposure calculations verification (`tests/test_financial_audit.py`)
  - [x] Citation, provenance, and briefing consistency audit tool (`demo/briefing_audit.py`)
  - [x] Runtime API smoke tests exercising 8 endpoints and error contracts (`demo/api_smoke_test.py`)
  - [x] Deterministic 7-stage end-to-end trial demonstration (`demo/run_demo.py`)
  - [x] Demo pack deliverables: master README, scenario guide, 10-slide presentation deck, live demo script, and judge Q&A guide (`demo/README.md`, `demo/scenario.md`, `demo/presentation.md`, `demo/live_demo_script.md`, `demo/qna_guide.md`)
  - [x] Full test suite execution: 139 / 139 passed (100%), zero regressions

---

## Phase 1 Execution Notes

- **Status**: Completed
- **Files Created / Changed**:
  - `backend/models.py`: Shared Pydantic v2 data models contract (`Claim`, `Ruling`, `CaseFile`, `Document`, `DocMeta`, `TradeRow`, `Attack`, `Defense`, `Concession`, `Briefing`, `LogEvent`, `Verdict`, `Basis`, etc.).
  - `backend/llm.py`: Shared LLM wrapper using Anthropic SDK, token accounting (`MAX_TOKENS_PER_CASE`), retry repair, mock handler injection, and document tag sanitization.
  - `backend/agents/prompts/odin.md`: Impartial Odin judicial prompt with strict evidence security, tier hierarchies, and verdict rules.
  - `backend/agents/odin.py`: Deterministic citation validation (`validate_citation`), claim eligibility checks (`evaluate_claim_eligibility`), Tier 4 rejection enforcement, LLM semantic adjudication with retry repair, and complete claim coverage guarantee.
  - `tests/test_odin_evidence.py`: 11 deterministic validation unit tests.
  - `tests/test_odin.py`: 9 judicial engine unit tests including cross-examination, concessions, duplicate ruling deduplication, prompt injection isolation, and LLM repair.
- **Tests Executed**:
  - `python -m pytest tests -v`
  - Result: 20 passed in 0.08s (100% pass rate).
- **Decisions Made**:
  - Code-level enforcement: Python deterministically rejects claims citing post-cutoff dates, missing documents/paragraphs, retracted sources, damaged sources, duplicate-only sources, or Tier-4-only evidence. LLM responses can never override deterministic rejections.
  - Untrusted document wrapping: Document text is encapsulated within `<document id="..." tier="..." date="...">` tags with internal closing tag sanitization.
  - Exact claim coverage guarantee: Every submitted claim receives a final ruling; if an LLM response omits a claim, Odin falls back to a `CONTESTED` ruling with rationale noting omission rather than failing silently.
  - Duplicate LLM rulings for the same claim ID are ignored to preserve the primary ruling.
- **Dependencies for Phase 2**:
  - Implementation of country-sector unit of analysis, exposure range derivation from admissible trade data/rulings, and sufficiency evaluation (`assess_sufficiency`) with structured `SendBack`.

---

## Phase 2 Execution Notes

- **Status**: Completed
- **Files Created / Changed**:
  - `backend/trade_calc.py`: Deterministic trade calculation engine supporting sums, YoY growth, period-over-period change, substitute-route offset netting, and exposure bounds derivation. Pre-calculation input validation ensures damaged, post-cutoff, duplicate, and unit-incompatible rows are excluded. Zero denominators and non-finite values are handled explicitly, with complete calculation provenance preserved. Zero mental arithmetic by LLM.
  - `backend/models.py`: Added `SufficiencyStatus`, `SufficiencyResult`, and enriched `ExposureRange` with tracked claim IDs, trade row references, and transparent assumptions.
  - `backend/agents/odin.py`:
    - Implemented `derive_exposure_ranges`: Maps country-sector analysis pairs, evaluates Thor and Loki estimates strictly as advocacy bounds rather than ground truth, prevents blind averaging or uncritical union, calculates net exposure deterministically from established trade rows and disruption severity, credits established/conceded substitute offsets, and sets explicit `unresolved` status with rationale when evidence is absent or claims are rejected.
    - Implemented `assess_sufficiency`: Determines whether evidence supports a defensible final briefing. Evaluates event verification, country-sector baseline presence, damaged trade data, Tier-4-only rejected claims, and unresolved material contradictions. Generates actionable, specific `SendBack` requests when insufficient; allows contested claims to proceed with disclosed uncertainties when sufficient; terminates gracefully under `LIMITS_EXHAUSTED` when `run_count >= max_runs`.
  - `tests/test_trade_calc.py`: 9 unit tests for all arithmetic operations, provenance, damaged row exclusions, zero denominators, and incompatible units.
  - `tests/test_odin_sufficiency.py`: 12 unit tests covering all exposure derivation, offset netting, sufficiency checks, send-back generation, limits exhaustion, and event verification cases.
- **Tests Executed**:
  - `python -m pytest tests -v`
  - Result: 41 passed in 0.11s (100% pass rate).
- **Decisions Made**:
  - Advocacy vs Truth: Thor and Loki ranges are recorded as party positions; Odin's range is derived strictly from validated rulings and admissible trade rows.
  - Graceful limit termination: When `run_count >= max_runs`, `assess_sufficiency` returns `LIMITS_EXHAUSTED` without generating an infinite loop of send-back requests.
  - Actionable SendBack: Requests pinpoint exact countries, sectors, missing baselines, or specific contradictory claim IDs rather than generic "find more evidence" prompts.
- **Dependencies for Phase 3**:
  - Odin private memory isolation (`recall`/`remember`), append-only SQLite/JSONL audit logbook integration, and case-wide token/tool-call budget enforcement.

---

## Phase 3 Execution Notes

- **Status**: Completed
- **Files Created / Changed**:
  - `backend/memory.py`:
    - Implemented `MemoryStore` supporting isolated agent memories (`recall(agent, topic)`, `remember(agent, lesson, evidence)`).
    - Enforced strict agent memory isolation: Odin can only read and write Odin's private memory. Attempts to read Thor's or Loki's private memory raise `MemoryAccessError`.
    - Added recursive credential and secret sanitization (`sanitize_lesson_text`), scrubbing Anthropic API keys, bearer tokens, passwords, and authorization headers from stored lessons and evidence.
    - Preserved provenance (`case_id`, `evidence`, `timestamp`) and added support for optional SQLite persistence.
  - `backend/logbook.py`:
    - Implemented thread-safe `LogBook` persisting append-only audit events to SQLite and JSONL with query support (`case_id`, `event_type`, `agent`).
    - Configured automatic recursive secret redaction (`redact_secrets`) across strings, dicts, lists, and Pydantic models.
    - Verified strict audit reliability: SQLite and JSONL persistence failures raise `RuntimeError` rather than silently reporting success.
  - `backend/llm.py`:
    - Enforced shared resource configuration: `MAX_RUNS=3`, `MAX_ROUNDS=2`, `MAX_RETRIES=2`, `MAX_TOOL_CALLS_PER_AGENT=12`, `MAX_TOKENS_PER_CASE=200000`, `LLM_TIMEOUT=60.0`.
    - Added preflight and in-flight token budget accounting (`BudgetExceededError`). Tokens accumulate case-wide across runs and cycles (never reset within the same case).
    - Added per-agent tool-call quota tracking (`record_tool_call`), enforcing `MAX_TOOL_CALLS_PER_AGENT=12` (`ToolCallLimitExceededError`).
    - Bounded structured output repair retries to `MAX_RETRIES=2` with controlled failure upon exhaustion.
  - `backend/agents/odin.py`:
    - Integrated memory recall: Odin queries prior judicial lessons (e.g. tier admissibility, baseline requirements) and passes them as untrusted advisory notes in the prompt (never modifying system rules, dates, or schemas).
    - Added memory failure resilience: Memory recall or write failures are safely logged (`MEMORY_READ` failed or `ERROR`), preventing fabricated rulings and preserving trial integrity.
    - Integrated audit logging: Logs `QUERY` on cycle start, `TRAP_INJECTION` for tainted evidence, `MEMORY_READ`, `RULING` for all final rulings, `MEMORY_WRITE` for learned lessons, `SENDBACK` for missing evidence, `LIMIT_HIT` for budget/run exhaustion, and `ERROR` for provider failures.
    - Integrated budget failure fallback: On token or tool-call budget exhaustion, valid deterministic rulings are preserved, unadjudicated claims are marked `CONTESTED` with clear `disqualified_reason`, and `LIMIT_HIT` is logged.
  - `tests/test_odin_memory.py`: 8 unit tests verifying memory recall, isolation (`MemoryAccessError` on cross-agent reads), secret redaction, provenance, untrusted memory handling, recall failure tolerance, write failure logging, and SQLite persistence.
  - `tests/test_odin_logging.py`: 6 unit tests verifying recursive secret redaction, event creation, SQLite/JSONL persistence, query filtering, SQLite/JSONL failure detection, and trial cycle audit taxonomy.
  - `tests/test_odin_budgets.py`: 6 unit tests verifying within-budget execution, preflight token budget exhaustion, tool-call quota exhaustion, provider timeout handling, repair retry exhaustion, and non-resetting case budgets across runs.
- **Tests Executed**:
  - `python -m pytest tests -v`
  - Result: 61 passed in 0.29s (100% pass rate: 20 Phase 1 + 21 Phase 2 + 20 Phase 3).
- **Decisions Made**:
  - Thread-Safe SQLite: `LogBook` and `MemoryStore` maintain persistent connections with thread locks, ensuring in-memory SQLite instances (`:memory:`) do not discard tables across calls and SQLite file writes are thread-safe.
  - Fail-Safe Persistence: Logging persistence failures raise `RuntimeError`, guaranteeing that no unsupported ruling can be presented as established if audit logging fails.
  - Preserved Claims on Budget Limit: When an LLM budget limit or provider error interrupts judgment, already validated deterministic rulings are preserved, and unadjudicated claims are returned as `CONTESTED` with an explicit reason (`token_budget_exceeded`, `tool_call_limit_exceeded`, `provider_error`), maintaining 100% claim coverage.
- **Dependencies for Phase 4**:
  - LangGraph trial state machine orchestration (`TrialState`), connecting Heimdall verification, Thor/Loki parallel advocacy, cross-examination, Odin judgment, sufficiency check, and send-back routing loop.

---

## Phase 4 Execution Notes

- **Status**: Completed
- **Files Created / Changed**:
  - `backend/trial_state.py`:
    - Defined `TrialState` (TypedDict) compatible with LangGraph 1.2+ and Pydantic v2 domain models.
    - Preserves case parameters, run and round counters, evidence stores (`doc_store`, `trade_store`), stable IDs and hashes, disjoint parallel advocate claims (`thor_claims`, `loki_claims`), cross-examination records (`attacks`, `defenses`, `concessions`), judicial rulings, derived exposure ranges, sufficiency result, send-back request, run history, and resource budget state.
  - `backend/agents/adapters.py`:
    - Implemented `HeimdallAdapter` parsing questions into `CaseFile` (with target country-sector pairs), verifying event authenticity (`REAL`, `NOT_REAL`, `UNCERTAIN`), retrieving initial evidence from `dev_pack_E5`, and executing send-back re-search.
    - Added evidence novelty tracking: Computes SHA256 hashes of retrieved documents/rows, compares against `previous_evidence_ids` and `previous_evidence_hashes`, filters damaged/duplicate/irrelevant material, and flags `new_evidence_count = 0` if re-search finds no novel admissible evidence.
    - Implemented `ThorAdapter` (HIGH exposure advocate) and `LokiAdapter` (LIMITED exposure advocate) with tool-call quota tracking and failure simulation.
    - Implemented `CrossExamAdapter` managing reciprocal attacks, defenses, concessions, and degraded modes when an advocate fails (surviving claims stand unchallenged without fabricating arguments).
  - `backend/trial.py`:
    - Implemented `TrialGraphBuilder` compiling the full LangGraph state machine:
      - `START -> heimdall`
      - `heimdall -> [thor, loki]` (parallel fan-out) or `END` (if `not_real` or unrecoverable error)
      - `[thor, loki] -> cross_exam` (parallel fan-in merging disjoint claims)
      - `cross_exam -> odin`
      - `odin -> sufficiency`
      - `sufficiency -> heimdall` (loop back on SendBack if `run_count < max_runs`) or `END` (if `ready_for_briefing` or limits reached)
    - Implemented `persist_run_snapshot` writing complete, secret-redacted JSON snapshots to `logs/cases/<case_id>/run_<n>.json` before starting new runs.
    - Implemented `run_trial` convenience runner and `main()` CLI terminal entry point supporting `python -m backend.trial "<question>" --as-of YYYY-MM-DD`.
  - `tests/test_trial_graph.py`: 8 integration tests covering single-run sufficient trials, parallel Thor and Loki execution with disjoint merge preservation, `not_real` event early termination without advocates, `uncertain` event policy, send-back loop routing, degraded modes on advocate failures, and cross-examination.
  - `tests/test_trial_limits.py`: 7 tests covering run limit exhaustion (`terminated_limits_exhausted`), evidence novelty enforcement (0 new evidence terminates truthfully), token budget exhaustion, tool-call quota exhaustion, non-resetting case budgets across runs, snapshot persistence secret redaction, and CLI entry point execution.
- **Tests Executed**:
  - `python -m pytest tests -v`
  - Result: 76 passed in 2.72s (100% pass rate: 20 Phase 1 + 21 Phase 2 + 20 Phase 3 + 15 Phase 4).
- **Decisions Made**:
  - Disjoint Parallel State: Parallel execution of Thor and Loki updates separate fields (`thor_claims` and `loki_claims`) in `TrialState`, guaranteeing neither advocate's output can overwrite the other regardless of execution order.
  - Truthful Incomplete Termination: When Heimdall's re-search yields 0 qualifying new evidence or when the maximum run limit is reached, the graph terminates with status `incomplete` or `terminated_limits_exhausted`, never labeling a case complete prematurely.
  - Early Event Termination: If an event is verified as `not_real`, the graph branches directly to `END`, preventing unnecessary advocate hearings or judicial LLM calls.
- **Dependencies for Phase 5**:
  - Final intelligence briefing generator (`backend/briefing.py`) implementing Sections A through J grounded strictly in Odin's rulings, with inline citation validation, and Markdown / JSON export.

---

## Phase 5 Execution Notes

- **Status**: Completed
- **Files Created / Changed**:
  - `backend/models.py`:
    - Enriched `Citation` model with optional `pub_date: Optional[str] = None` and updated `display_str()` to render canonical string `[DOC_ID Pn, YYYY-MM-DD]` or `[TAB#row, YYYY-MM]`.
    - Added `executive_summary: str = ""` and `verification_summary: Dict[str, Any] = Field(default_factory=dict)` to `Briefing` model with backward-compatible defaults.
  - `backend/briefing.py`:
    - Implemented `validate_citation_provenance()` providing deterministic provenance verification:
      - Document and paragraph existence in physical evidence store.
      - As-of cutoff clock constraint compliance (`pub_date <= as_of`).
      - Cited publication date match against source metadata.
      - Disqualification of formally retracted, superseded, damaged, or duplicate documents.
      - Normalized/exact quote substring matching (`quoted_text in paragraph_text`).
      - Structural claim support verification: checks substantive statement content words and sector overlap against paragraph text, rejecting unsupported claims while documenting structural vs semantic NLP limitations.
      - Trade row existence, damage check, and month cutoff constraint.
    - Implemented canonical string parser `parse_citation()` and `validate_citation_str()`.
    - Implemented `BriefingGenerator` assembling Sections A through J strictly from Odin's final rulings:
      - **Section A (Executive Summary)**: Disruption event, as-of date, judicial breakdown, and status. Handles `not_real` counterfeit notice (zero net exposure across all sectors) and `uncertain` provisional findings warning.
      - **Section B (Established Findings)**: Sourced facts and inferences with verdict `established`, canonical citations, excerpts, and rationale. Marks findings lacking valid citations as `[INSUFFICIENTLY SUPPORTED - Citations Failed Validation]`.
      - **Section C (Contested Findings)**: Disputed claims with cross-examination opposing arguments and missing evidence to resolve.
      - **Section D (Conceded Findings)**: Explicit concessions on record; advocate timeouts or failures are never treated as concessions.
      - **Section E (Rejected Findings)**: Disqualified claims with reason, clarifying rejection is lack of proof, not affirmation of converse.
      - **Section F (Exposure Analysis Table)**: Grounded in Phase 2 models and deterministic calculations; zero LLM mental math; represents failed advocates as `None` with explicit assumption note (never assumed zero).
      - **Section G (Outlook & Implications)**: Distinctly separates established facts, inferences, contested disputes, and unknown gaps.
      - **Section H (Verification Summary)**: Verdict counts, citation verification stats, source counts, tier distribution, clock compliance, execution metrics, advocate statuses, and validation methodology disclosure.
      - **Section I (Sources & Traps Caught)**: Cited sources list and actual recorded traps (prompt injections, retractions, corrections, duplicates, damaged records, clock violations, Tier 4 rejections).
      - **Section J (Markdown Report)**: Complete, publication-grade formatted briefing.
    - Implemented `generate_briefing()` convenience helper.
  - `backend/trial_state.py`:
    - Added `briefing: Optional[Any]` and `persisted_briefing_path: Optional[str]` to `TrialState`.
  - `backend/trial.py`:
    - Wired `node_briefing` into the LangGraph state machine: routes terminal states (`ready_for_briefing`, `terminated_limits_exhausted`, `incomplete`, `event_not_real`) to `node_briefing -> END`.
    - Persists `briefing.json` (with secret redaction) and `briefing.md` in `logs/cases/<case_id>/`.
    - Added replay preservation check: re-running on state with existing briefing reuses persisted files without overwriting or corrupting.
    - Enhanced CLI `main()` to display persisted briefing path and executive summary snippet.
  - `tests/test_briefing.py`:
    - Comprehensive unit and integration test suite covering all 18 required scenarios:
      1. Ordinary case with established, contested, conceded, and rejected rulings.
      2. Multiple countries and sectors.
      3. No exposure data.
      4. One advocate failed and the other succeeded.
      5. Both advocates failed.
      6. Missing and malformed citations.
      7. Nonexistent document citation.
      8. Nonexistent paragraph citation.
      9. Ineligible source published after as-of date (clock violation).
      10. Evidence paragraph does not support claim (quote mismatch & zero topic overlap).
      11. Event classified as not_real.
      12. Event classified as uncertain.
      13. Trial stopped by run or resource limit.
      14. Trial awaiting research / send-back.
      15. Briefing contains only final Odin rulings (unadjudicated advocacy claims excluded).
      16. Empty or minimal case.
      17. Replay idempotency / persistence preservation.
      18. End-to-end regression confirming Phase 1-4 trial workflow produces briefing.
- **Tests Executed**:
  - `python -m pytest tests -v`
  - Result: 94 passed in 2.83s (100% pass rate: 20 Phase 1 + 21 Phase 2 + 20 Phase 3 + 15 Phase 4 + 18 Phase 5).
- **Decisions Made**:
  - Grounding Exclusivity: Briefings are strictly derived from Odin's binding rulings. Advocate claims provide statement context for ruled claims only; unadjudicated claims from Thor or Loki are never exposed in findings.
  - Substantive Claim Support Check: Citation support validation verifies substantive statement keywords and sector against paragraph text, preventing spurious matches based solely on country jurisdiction.
  - Zero Mental Math: All exposure totals and bounds in Section F reuse deterministic calculations from Phase 2; missing advocate estimates are recorded as `None` with assumptions rather than zero.
- **Dependencies for Phase 6**:
  - Successfully integrated in Phase 6.

---

## Phase 6 Execution Notes — API Integration & Trial Exposure

- **Objective**: Expose the existing Phase 1–5 judicial engine, LangGraph trial workflow, and validated briefings through a robust, production-grade FastAPI application.
- **Components Created & Modified**:
  - `backend/case_store.py`:
    - SQLite and file-backed case and trial registry (`CaseStore`, `CaseRecord`, `TrialRecord`).
    - Thread-safe concurrency control via `acquire_case_lock(case_id)` and `release_case_lock(case_id)` to prevent duplicate concurrent runs on the same case.
    - Full persistence of final artifacts (`rulings.json`, `briefing.json`, `final_state.json`) in `logs/cases/<case_id>/`.
    - Pagination support with upper bounds (`limit <= 100`, `offset`).
  - `backend/api/schemas.py`:
    - Strict Pydantic v2 request/response schemas: `CreateCaseRequest`, `CaseResponse`, `CaseListResponse`, `StartTrialRequest`, `TrialStatusResponse`, `RulingsResponse`, `HealthResponse`, `ErrorResponse`.
    - Validation: Date format (`YYYY-MM-DD`), non-empty queries, target pairs, and status enums.
  - `backend/api/service.py`:
    - `TrialService` business logic layer:
      - Validates case existence and as-of date before execution.
      - Acquires per-case concurrency lock; raises `TrialConflictError` (409) if already running.
      - Invokes canonical `run_trial()` from `backend/trial.py`.
      - Extracts and persists Odin rulings and validated Phase 5 `Briefing`.
      - Enforces case/run tenant isolation.
      - Emits structured lifecycle events (`case_created`, `trial_started`, `trial_completed`, `trial_failed`, `briefing_retrieved`, `citation_validation_failed`) to `LogBook`.
  - `backend/api/routes.py`:
    - `GET /health`: Health check evaluating both server process and database availability.
    - `POST /api/cases`: Create a new case file.
    - `GET /api/cases`: List registered cases with pagination.
    - `GET /api/cases/{case_id}`: Retrieve safe case metadata.
    - `POST /api/cases/{case_id}/trials`: Start or execute a LangGraph trial (supports synchronous or background execution).
    - `GET /api/cases/{case_id}/trials/{trial_id}`: Honest trial execution status, active node, timestamps, and error state.
    - `GET /api/cases/{case_id}/trials/{trial_id}/rulings`: Odin's final rulings (`established`, `contested`, `conceded`, `rejected`).
    - `GET /api/cases/{case_id}/trials/{trial_id}/briefing`: Validated Phase 5 briefing (returns 409 if pending research or still executing).
  - `backend/app.py`:
    - Application factory `create_app()` with CORS middleware.
    - Sanitized exception handlers for 422 Unprocessable Entity, HTTPException, and unhandled 500 exceptions, guaranteeing zero exposure of stack traces, secrets, or internal paths.
  - `backend/models.py`:
    - Added `@property def target_country_sector_pairs` to `CaseFile` for seamless schema interoperability.
  - `backend/logbook.py`:
    - Added `record_event()` convenience method.
  - `backend/trial.py`:
    - Updated `node_heimdall` and `run_trial` to preserve caller-provided `case_id` across graph transitions, snapshots, and briefings.
  - `README.md`:
    - Added complete API documentation, environment variables, local execution guide, endpoint request/response examples, and status semantics.
- **Tests Executed**:
  - `tests/test_api.py` covering all 22 required scenarios:
    1. Health endpoint (`GET /health`).
    2. Successful case creation (`POST /api/cases`).
    3. Invalid case input (invalid date, empty query) returning 422.
    4. Case retrieval and missing-case behavior (`404 Not Found`).
    5. Case listing, pagination, and page-size limits (`limit <= 100`).
    6. Trial start for an existing case (`200 OK` sync, `202 Accepted` background).
    7. Trial start for a nonexistent case (`404 Not Found`).
    8. Duplicate concurrent trial start (`409 Conflict`).
    9. Trial status before execution (`pending`).
    10. Trial status after successful execution (`completed`).
    11. Trial status after failure or resource-limit termination (`limits_exhausted`).
    12. Rulings endpoint returns only final Odin rulings (`established`, `contested`, `conceded`, `rejected`).
    13. Briefing endpoint returns validated Phase 5 briefing.
    14. Briefing unavailable while research is pending (`409 Conflict`).
    15. Citation-validation failure is not presented as a validated success.
    16. `not_real` and `uncertain` event handling.
    17. Malformed IDs and invalid state transitions (`400 Bad Request`).
    18. Provider failure without secret leakage.
    19. Persistence failure behavior (`500 Internal Server Error`).
    20. Case/run isolation (data from one case cannot appear in another case's responses).
    21. Regression verification across all Phases 1–5 test suites.
    22. JSON serialization of dates, enums, and nested briefing data.
  - `python -m pytest tests -v`
  - Result: **116 passed in 4.28s (100% pass rate)**.
- **Key Architectural Decisions & Safety Guarantees**:
  - **Zero Fabrication**: Statuses, rulings, and briefings reflect actual graph and storage state; no synthetic progress percentages or dummy verdicts.
  - **Strict Grounding & Citation Integrity**: The briefing endpoint serves only briefings verified by Phase 5 `validate_citation_provenance`.
  - **Thread-Safe Concurrency**: Trial execution utilizes per-case mutex locks; concurrent requests for an active case return `409 Conflict`.
  - **Information Security**: Private agent memories, chain-of-thought, system prompts, filesystem paths, and exception tracebacks are strictly excluded from API responses.
- **Dependencies for Phase 7**:
  - Successfully validated and hardened in Phase 7.

---

## Phase 7 Execution Notes — Final Validation, Adversarial Evaluation & Demo Pack

- **Status**: Completed
- **Objective**: Execute end-to-end trial validation, synthetic adversarial stress evaluation across 12 threat vectors, deterministic financial calculations verification, briefing consistency audit, API smoke tests, and final presentation pack preparation.
- **Components Created & Modified**:
  - `demo/fixtures/manifest.json`: Synthetic document manifest cataloging 16 adversarial documents with reliability tiers (Tier 1-4), publication dates, sectors, and threat categories.
  - `demo/fixtures/loader.py`: Fixture loader parsing `manifest.json`, providing synthetic `Document` objects with structured paragraphs and synthetic `TradeRow` tables (`TAB-SYNTH-WHEAT`, `TAB-SYNTH-MAIZE`, `TAB-SYNTH-DAMAGED`, `TAB-SYNTH-FUTURE`).
  - `demo/adversarial_manifest.json`: Machine-readable specification of 19 adversarial scenarios covering categories A through L.
  - `demo/adversarial_runner.py`: Dedicated evaluation runner executing all 19 scenarios and outputting structured artifacts (`demo/adversarial_report.json`, `demo/adversarial_report.md`).
  - `demo/briefing_audit.py`: Independent audit tool performing 6-point provenance and semantic checks on final briefings.
  - `demo/api_smoke_test.py`: Runtime FastAPI smoke test validating 8 REST endpoints, concurrency locks, and error contracts (400, 404, 409, 422).
  - `demo/run_demo.py`: Deterministic, 7-stage end-to-end demonstration script.
  - `demo/scenario.md`: Comprehensive synthetic scenario specification for the Winter Sluice Disruption.
  - `demo/presentation.md`: 10-slide final presentation deck outline with complete speaker notes.
  - `demo/live_demo_script.md`: 3–5 minute live demonstration script with spoken cues and fallback pivots.
  - `demo/qna_guide.md`: Detailed technical answers to the 11 judge questions.
  - `demo/README.md`: Master demo guide and command reference.
  - `tests/test_adversarial.py`: 15 automated Pytest unit and integration tests for categories A–L.
  - `tests/test_financial_audit.py`: 8 automated Pytest tests validating deterministic financial calculations and unit safety.
  - `backend/agents/odin.py`: Integrated injection scanning (`scan_text_for_injections()`) during judicial review and automatic `TRAP_INJECTION` logging.
  - `backend/briefing.py`: Enhanced Section I trap recording, made doc store optional for pre-rendered briefings, and fixed bracket matching in citation parsing.
  - `backend/models.py`: Added section property getters for briefing interoperability.
- **Verification Results**:
  - `python -m pytest`: **139 passed in 4.27s (100% pass rate across 12 test modules)**.
  - `python demo/adversarial_runner.py`: **19 / 19 scenarios passed (100.0%)**.
  - `python demo/briefing_audit.py`: **Audit passed with 0 violations**.
  - `python demo/api_smoke_test.py`: **21 / 21 assertions passed (100.0%)**.
  - `python demo/run_demo.py`: **All 7 demonstration stages completed successfully**.
- **Adversarial Evaluation Metrics**:
  - *Scenarios Executed*: 19 / 19 (100%)
  - *Scenarios Passed*: 19 / 19 (100%)
  - *Scenarios Failed*: 0 / 19 (0.0%)
  - *Scenarios Skipped*: 0 / 19 (0.0%)
  - *Prompt Injections Contained*: 3 / 3 (100%)
  - *Future-Dated Sources Excluded*: 2 / 2 (100%)
  - *Duplicate Sources Deduplicated*: 1 / 1 (100%)
  - *Uncertainty Retained*: 4 / 4 (100%)
  - *Resource Limits Handled Gracefully*: 2 / 2 (100%)
  - *Citation Failures Caught*: 1 / 1 (100%)
  - *Deterministic Arithmetic Checks*: 8 / 8 (100%)
- **Key Architectural Decisions & Hardening**:
  - *Multi-Layer Injection Containment*: Untrusted evidence is encapsulated in XML tags, regex-scanned for override directives, logged to `LogBook` under `TRAP_INJECTION`, and strictly barred from modifying system prompts or as-of dates.
  - *Zero Mental Arithmetic*: All exposure numbers and bounds are computed via deterministic Python math in `backend/trade_calc.py`, preventing LLM hallucination of numerical statistics.
  - *Truthful Termination*: Non-existent events (`not_real`), thin evidence, or exhausted budgets terminate with honest status disclosures rather than fabricated conclusions.

---

## Full Four-Agent System Implementation — Complete RAGNAROK Intelligence Suite

- **Status**: Completed
- **Objective**: Deliver a fully integrated, tested, demonstrable four-agent intelligence system—unifying multi-format document ingestion, hybrid evidence retrieval, Heimdall gatekeeper, Thor high-exposure advocate, Loki limited-exposure advocate, cross-examination orchestrator, Odin judicial arbiter, deterministic financial calculations, LangGraph workflow, FastAPI backend, and an interactive real-time dashboard UI.
- **Components Created & Integrated**:
  - `backend/ingestion.py`:
    - Full multi-format document extraction for PDF (`pymupdf`/`pypdf`), DOCX (`python-docx`), and TXT with multi-encoding fallback (`utf-8`, `utf-16le`, `latin-1`).
    - Structured paragraph segmentation `[P1]`, `[P2]`...
    - Trade row synthesis: extracts structured monthly records into `TradeRow` objects with volumes and values.
    - Content hashing with SHA-256 for deduplication.
    - Automated prompt injection security scanning via `scan_text_for_injections()`.
    - Safe handling of damaged documents (e.g. empty payloads like `ORV-0023.txt`).
  - `backend/retrieval.py`:
    - Hybrid retrieval engine combining BM25 lexical ranking (`BM25Okapi`) and dense vector similarity (`FastEmbed` + in-memory `QdrantClient`).
    - Deterministic As-Of Date enforcement: sources published after `case_file.as_of` are strictly excluded from search candidate sets.
    - Reciprocal Rank Fusion (RRF) with topical metadata weighting and reliability tier awareness.
  - `backend/agents/heimdall.py` & `backend/agents/prompts/heimdall.md`:
    - Full `HeimdallAgent` gatekeeper and chief investigator.
    - Query parser extracting target country-sector pairs and normalized as-of dates.
    - Event verification: evaluates disruption authenticity (`REAL`, `UNCERTAIN`, `NOT_REAL`) grounded in admissible records; isolates Tier 4 rumors; detects fabricated decoys.
    - Send-back research loop: re-queries retrieval engine for specific missing commodities/routes and tracks novelty via SHA-256 hashes.
  - `backend/agents/thor.py` & `backend/agents/prompts/thor.md`:
    - Full `ThorAgent` high-exposure advocate.
    - Claims generation with `posture="high"`, paragraph citations, and deterministic exposure bounds via `calculate_exposure_bounds()`.
    - Cross-examination challenges attacking Loki's unproven substitution claims; evidence-backed defenses.
  - `backend/agents/loki.py` & `backend/agents/prompts/loki.md`:
    - Full `LokiAgent` limited-exposure advocate.
    - Claims generation with `posture="limited"`, substitute rail route throughput credits, and deterministic offsets via `calculate_substitute_offset()`.
    - Cross-examination challenges attacking Thor's gross-loss extrapolations; explicit concessions (`Concession`) when data is unequivocal.
  - `backend/agents/cross_exam.py`:
    - Dynamic `CrossExaminationOrchestrator` managing reciprocal clashes between Thor and Loki.
    - Preserves degraded modes when an advocate fails (surviving claims stand unchallenged; zero automatic concessions on failure/timeout).
  - `backend/trial.py`:
    - Integrated real agents into `TrialGraphBuilder` by default while preserving adapter base classes for full backwards-compatibility.
  - `backend/static/index.html` & `backend/app.py`:
    - Interactive single-page dashboard UI served at `http://localhost:8000/` and `/dashboard`.
    - Live trial execution with scenario presets (E5 Orvan Corridor, Synthetic Winter Sluice, Hoax Decoy).
    - Stepper progress tracker, Heimdall evidence vault, Thor vs Loki advocate chamber, cross-examination viewer, Odin rulings table, deterministic exposure table, executive briefing markdown viewer, and audit log stream.
- **Verification Results**:
  - `python -m pytest`: **150 passed in 9.63s (100% pass rate across all 16 test suites)**.
    - `test_adversarial.py`: 15 passed
    - `test_advocates.py`: 4 passed (new)
    - `test_api.py`: 22 passed
    - `test_briefing.py`: 18 passed
    - `test_financial_audit.py`: 8 passed
    - `test_four_agents.py`: 2 passed (new)
    - `test_heimdall.py`: 5 passed (new)
    - `test_odin.py`: 9 passed
    - `test_odin_budgets.py`: 6 passed
    - `test_odin_evidence.py`: 11 passed
    - `test_odin_logging.py`: 6 passed
    - `test_odin_memory.py`: 8 passed
    - `test_odin_sufficiency.py`: 12 passed
    - `test_trade_calc.py`: 9 passed
    - `test_trial_graph.py`: 8 passed
    - `test_trial_limits.py`: 7 passed
  - `python demo/adversarial_runner.py`: **19 / 19 passed (100.0%)**.
  - `python demo/briefing_audit.py`: **0 violations detected (100% consistent)**.
  - `python demo/api_smoke_test.py`: **21 / 21 checks passed (100.0%)**.
  - `python demo/run_demo.py`: **All 7 stages succeeded with real integrated agents**.
  - Dashboard routes (`GET /` and `GET /dashboard`): **200 OK (35KB UI payload)**.

