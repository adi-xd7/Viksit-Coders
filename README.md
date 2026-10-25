# Trial of the Nine Realms — Supply Chain Disruption Intelligence Challenge

## The Mission

A supply chain disruption has been reported across the Runemark trade network. Most AI tools only summarize the news — sourced facts and speculation get blended together, and decision-makers cannot tell what is certain and what is disputed.

Your task is to build an adversarial multi-agent courtroom system that treats every disruption as a court case. The system must ingest the document corpus, verify the event is real, debate the commercial exposure from two opposing sides, and deliver a structured intelligence briefing with every claim graded by nature and confidence.

There is no spoon-fed answer. You and your team must design the architecture, retrieve the right evidence, challenge each other's claims, and prove your system's reasoning from the raw documents.

---

## Commercial Value vs. Physical Disruption

Alarming news or transit drops do not automatically mean a large trade value collapse. Alternative routing, carrier consolidation, and price/freight adjustments often cushion commercial exposure. Your courtroom agents must evaluate actual net value impact, not assume all crises cause massive drops.

---

## Folder Layout

```text
dev_pack_E5/
├── README.md                  ← You are here
├── manifest.json              ← Document catalog (IDs, dates, formats, sectors)
├── hashes.sha256              ← File integrity checksums
├── sample_question.txt        ← The target query in plain text
└── docs/                      ← The document pool (76 files: TXT, PDF, DOCX)
    ├── ATL-0001 to ATL-0016   # Runemark Atlas — geography, country profiles, trade routes & outlet credibility tiers
    ├── ORV-0001 to ORV-0050   # Regional agricultural notices, customs filings, port bulletins & industry reports
    └── WLD-0021 to WLD-0030   # General newswire: public affairs, cultural dispatches & civic reporting
```

---

## What Your System Must Uncover

A successful system must autonomously solve challenges across the document pool:

* **Event Verification:** Heimdall must confirm the disruption event is real and active as of the as-of date (**25 January 2027**). Fake decoys, retracted notices, and planted injections exist in the corpus and must be caught before the trial begins.
* **Opposing Exposure Cases:** Thor and Loki must each build a document-grounded case on opposite sides — high exposure vs. limited exposure — covering the specified commercial trade flows. Vague positions are not valid claims.
* **Cross-Examination & Concessions:** Each side must attack the other's weakest claims with counter-evidence. Agents must either defend with new documents or concede. A system where no one ever concedes has not genuinely debated.
* **Judicial Classification:** Odin must distinguish between sourced facts (directly stated in a document) and inferences (derived by reasoning). Every claim must receive a ruling and be classified as Established, Contested, or Conceded.
* **Sufficiency Loop:** If the evidence base is thin after the first trial run, Odin returns it for a second round of retrieval. A minimum of two trial runs must be demonstrated.
* **Final Intelligence Briefing & Human-Readable Deliverable:** Odin authors the final briefing from his rulings only — not from Thor or Loki's raw arguments. The briefing must include an exposure table (with separate Thor, Loki, and Odin ranges), inline paragraph-level citations, and a next-quarter outlook. In your user interface (UI), this briefing must be rendered cleanly for human decision-makers.
* **Source Hygiene:** The corpus contains documents from four outlet credibility tiers (see `ATL-0012`). Your system must not treat a tabloid rumour or a retracted notice as established fact. The as-of date is **25 January 2027** — citing anything published after this date is a clock violation.

---

## Submission Deliverables

Submit a final output and an execution trace, in any format. Label each item with the question it answers.

**Final output**
- Event Verification
- Exposure Ranges
- Odin's Executive Briefing

**Execution trace**
- Agent queries and retrieved document IDs
- Cross-examination challenges and counter-arguments
- Memory updates and claim concessions
- Judicial rulings per round

**This is the bare minimum, not the full goal.** Go further: add more results, add more detail to your execution trace, and show your creativity. But every finding must come from the document pool and be retrieved by your agent at run time. Missing any item above is a serious penalty that extras cannot cancel.

---

## Evaluation

Submissions are evaluated on:
* **Citation Validity** — Grounded evidence from verified documents.
* **Range Accuracy** — Precise commercial exposure bounds.
* **Calibration** — Well-calibrated confidence intervals.
* **Trap Handling** — Robustness against adversarial noise.
* **Quality of Debate** — Genuine cross-examination and concessions.
* **Pipeline Reliability** — Stable end-to-end execution.
* **Reproducibility** — Consistent multi-round trial results.
* **Briefing & UI Presentation** — Executive briefing and interface.

---

## Attribution

The Runemark world, nations, trade routes, and document corpus are entirely fictional and created for this challenge. All companies, trade figures, and events are simulated.

The outlet credibility tier model in `ATL-0012` is inspired by standard source reliability frameworks used in intelligence and investigative journalism contexts.

*This dataset is for educational and competition use only.*

---

## Odin Courtroom API Documentation (Phase 6)

The Odin Courtroom provides a FastAPI backend exposing case registration, LangGraph trial execution, binding judicial rulings, and verified intelligence briefings.

### 1. Environment Configuration

Copy or export environment variables without real secrets:

```bash
# LLM Provider Configuration (Optional for mock/deterministic testing)
export ANTHROPIC_API_KEY="sk-ant-your-key-here"

# Audit Logging & Storage (Defaults to logs/audit.db and logs/cases/)
export LOGBOOK_DB_PATH="logs/audit.db"
export LOGBOOK_JSONL_PATH="logs/audit.jsonl"
```

### 2. Running Locally

Start the development server using Uvicorn:

```bash
# Using uvicorn directly:
uvicorn backend.app:app --host 0.0.0.0 --port 8000 --reload

# Or via Python module:
python -m backend.app
```

Interactive Swagger documentation is available at `http://localhost:8000/docs` and ReDoc at `http://localhost:8000/redoc`.

### 3. Running Automated Tests

Run the full suite of 116 unit, integration, and API tests:

```bash
python -m pytest tests -v
```

### 4. API Endpoints Reference

#### System Health
- **`GET /health`**
  - Response:
    ```json
    {
      "status": "ok",
      "version": "1.0.0",
      "process": "healthy",
      "database": "healthy",
      "timestamp": "2027-01-25T12:00:00Z"
    }
    ```

#### Case Management
- **`POST /api/cases`**
  - Creates a new case.
  - Request:
    ```json
    {
      "query": "As of 25 January 2027, how exposed is Midgard wheat to the canal lock disruption?",
      "as_of": "2027-01-25",
      "case_id": "CASE-MIDGARD-01",
      "target_country_sector_pairs": [["Midgard", "wheat"]]
    }
    ```
  - Response (`201 Created`):
    ```json
    {
      "case_id": "CASE-MIDGARD-01",
      "query": "As of 25 January 2027, how exposed is Midgard wheat to the canal lock disruption?",
      "as_of": "2027-01-25",
      "verification_status": "real",
      "verification_reason": null,
      "target_country_sector_pairs": [["Midgard", "wheat"]],
      "status": "created",
      "created_at": "2027-01-25T12:00:00Z",
      "updated_at": "2027-01-25T12:00:00Z"
    }
    ```

- **`GET /api/cases`**
  - Lists cases with pagination (`limit` up to 100, `offset`).
  - Response (`200 OK`):
    ```json
    {
      "items": [...],
      "total": 1,
      "limit": 20,
      "offset": 0
    }
    ```

- **`GET /api/cases/{case_id}`**
  - Retrieves safe metadata and status for a specific case.

#### Trial Execution
- **`POST /api/cases/{case_id}/trials`**
  - Initiates a LangGraph trial run for the case.
  - Request:
    ```json
    {
      "max_runs": 3,
      "max_rounds": 2,
      "background": false
    }
    ```
  - Response (`200 OK` if synchronous, `202 Accepted` if `background=true`):
    ```json
    {
      "case_id": "CASE-MIDGARD-01",
      "trial_id": "TRIAL-B812F9A1",
      "status": "completed",
      "current_node": "briefing",
      "run_count": 1,
      "max_runs": 3,
      "start_time": "2027-01-25T12:00:00Z",
      "end_time": "2027-01-25T12:00:03Z",
      "is_awaiting_research": false,
      "is_completed": true,
      "error_message": null
    }
    ```

- **`GET /api/cases/{case_id}/trials/{trial_id}`**
  - Retrieves sanitized trial execution status, active node, timestamps, and completion flags.

#### Judicial Rulings & Briefing Deliverable
- **`GET /api/cases/{case_id}/trials/{trial_id}/rulings`**
  - Returns Odin's binding rulings (`established`, `contested`, `conceded`, `rejected`) with admissible citations.
  - Response (`200 OK`):
    ```json
    {
      "case_id": "CASE-MIDGARD-01",
      "trial_id": "TRIAL-B812F9A1",
      "rulings_count": 2,
      "rulings": [
        {
          "claim_id": "THOR-C1-MID-WHE",
          "verdict": "established",
          "basis": "sourced_fact",
          "rationale": "Sufficiently proven by corridor damage record.",
          "disqualified_reason": null,
          "admissible_citations": [{"doc_id": "ATL-0001", "paragraph_num": 2, "pub_date": "2027-01-10"}],
          "inadmissible_citations": []
        }
      ]
    }
    ```

- **`GET /api/cases/{case_id}/trials/{trial_id}/briefing`**
  - Returns the full Phase 5 judicial intelligence briefing model including Executive Summary, Established/Contested/Conceded/Rejected Findings, Exposure Analysis Table, Outlook, Verification Summary, Sources & Traps Caught, and complete Markdown document.
  - Returns `409 Conflict` if the trial is awaiting research or still executing.

### 5. Trial Lifecycle & Status Semantics

| Status | Meaning |
| :--- | :--- |
| `pending` | Trial registered and queued. |
| `running` | Trial in progress through courtroom workflow. |
| `completed` | Trial reached evidence sufficiency; validated briefing generated. |
| `awaiting_research` | Insufficient evidence base; send-back loop active awaiting Heimdall. |
| `limits_exhausted` | Maximum trial runs or token/tool-call budget reached. |
| `incomplete` | Investigation halted due to budget or 0 new evidence discovered. |
| `event_not_real` | Event confirmed as fake/decoy notice; early conclusion with zero exposure. |
| `failed` | System or unrecoverable provider exception. |

### 6. Architectural Assumptions & Limitations

- **Authentication**: Unauthenticated by default for hackathon development. For production deployments, deploy behind an API gateway with OAuth2 / mTLS.
- **Data Isolation**: Case and trial operations verify case-ID ownership (`/api/cases/{case_id}/trials/{trial_id}`), preventing cross-tenant data leakage.
- **Execution Mode**: Default `background=false` executes synchronously for deterministic client inspection; `background=true` executes via asynchronous background tasks for polling architectures.
