# PROGRESS — Trial of the Nine Realms (Odin Implementation)

## Project Overview
- **Project**: Trial of the Nine Realms — Supply Chain Disruption Impact Analyzer (RAGNAROK Hackathon)
- **Role**: Senior Python Backend Engineer — Odin (Judge), Trial Orchestration, and Evidence-Grounded Briefing
- **Branch**: `feat/trial-briefing` (branched from `Odin`)

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

- [ ] **Phase 1 — Odin System Prompt and Structured Judgment Engine**
  - [ ] Create Odin prompt (`backend/agents/prompts/odin.md`) with role, rules, untrusted-evidence security, and ruling schema
  - [ ] Implement deterministic eligibility checker in Python (`backend/agents/odin.py`):
    - [ ] As-of date enforcement (clock check)
    - [ ] Document and paragraph existence check
    - [ ] Quote match verification
    - [ ] Source reliability tier evaluation (Tier 1-3 allowed; Tier-4-only rejected)
    - [ ] Retraction / correction checks
    - [ ] Duplicate and damaged document checks
    - [ ] Damaged trade row checks
    - [ ] Prompt-injection detection and isolation
  - [ ] Implement LLM semantic judgment engine with structured Pydantic output
  - [ ] Implement complete claim coverage enforcement (every claim ruled exactly once; deterministic rejections cannot be overridden)
  - [ ] Unit tests (`tests/test_odin.py`, `tests/test_odin_evidence.py`)

- [ ] **Phase 2 — Odin's Exposure Ranges and Sufficiency Checker**
  - [ ] Country-sector unit of analysis mapping
  - [ ] Deterministic trade calculations (no mental arithmetic by LLM)
  - [ ] Evidence-grounded exposure range determination (`odin_range` based on admissible evidence, not blind averaging)
  - [ ] Structured sufficiency checker (`assess_sufficiency`):
    - [ ] Distinguish sufficient vs insufficient vs limits exhausted
    - [ ] Allow uncertainty disclosure for contested claims without failing trial
  - [ ] Actionable, specific `SendBack` requests
  - [ ] Tests (`tests/test_odin_sufficiency.py`)

- [ ] **Phase 3 — Odin Memory, Audit Logging, and Resource Budgets**
  - [ ] Private memory isolation (Odin private memory read/write only)
  - [ ] SQLite and JSONL append-only audit logbook integration
  - [ ] Resource budgets: token tracking, max tool calls, max retries, limit exhaustion handling
  - [ ] Tests (`tests/test_odin_memory.py`, `tests/test_odin_logging.py`)

- [ ] **Phase 4 — LangGraph Trial State Machine and Send-Back Loop**
  - [ ] LangGraph state definition (`TrialState`)
  - [ ] Build trial state machine graph:
    - [ ] HEIMDALL verification -> THOR & LOKI parallel -> CROSS-EXAMINATION -> ODIN -> SUFFICIENCY CHECK -> (SEND-BACK to HEIMDALL or BRIEFING)
  - [ ] New evidence detection for Run 2 (hash/ID comparison)
  - [ ] Termination conditions and bounds (`MAX_RUNS`, `MAX_ROUNDS`, `MAX_TOOL_CALLS`)
  - [ ] CLI runner (`python -m backend.trial "question" --as-of YYYY-MM-DD`)
  - [ ] Tests (`tests/test_trial_graph.py`, `tests/test_trial_limits.py`)

- [ ] **Phase 5 — Final Briefing Generation and Citation Validation**
  - [ ] Briefing generator (`backend/briefing.py`) strictly grounded in Odin's rulings
  - [ ] Sections A through J implementation
  - [ ] Strict inline citation validator (`[DOC_ID Pn, YYYY-MM-DD]`, `<table/doc>#<row>`)
  - [ ] Markdown and JSON exporters
  - [ ] Tests (`tests/test_briefing.py`)

- [ ] **Phase 6 — FastAPI Integration and Persistence**
  - [ ] `POST /cases`, `GET /cases/{id}`, `GET /cases/{id}/stream` (SSE)
  - [ ] SQLite case snapshot persistence
  - [ ] API tests (`tests/test_api.py`)

- [ ] **Phase 7 — Integration, Adversarial Testing, and Final Demonstration**
  - [ ] Synthetic pack generator and adversarial tests (injections, retractions, clock traps, missing data)
  - [ ] End-to-end trial rehearsal
  - [ ] Save demo case and logs to `logs/demo/`
  - [ ] Final verification and review
