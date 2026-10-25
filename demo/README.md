# RAGNAROK Phase 7: Demonstration & Adversarial Evaluation Pack

Welcome to the **Trial of the Nine Realms: Supply Chain Disruption Impact Analyzer** demonstration and evaluation suite.

This directory contains reproducible demo scripts, adversarial test runners, briefing audit tools, presentation slides, and evaluation manifests for the **Odin Courtroom Subsystem**.

---

## 1. Quick Start Commands

```bash
# 1. Run the Full Automated Test Suite (139 passing tests)
python -m pytest tests -v

# 2. Run the End-to-End Live Demonstration
python demo/run_demo.py

# 3. Run the Dedicated Synthetic Adversarial Evaluation Suite (19 scenarios)
python demo/adversarial_runner.py

# 4. Run the Briefing Citation & Provenance Audit
python demo/briefing_audit.py

# 5. Run the FastAPI Runtime Smoke Tests (21 checks)
python demo/api_smoke_test.py
```

---

## 2. Directory Structure

```text
demo/
├── README.md                  ← You are here: Demo quick start & usage guide
├── scenario.md                ← Synthetic disruption scenario specification
├── presentation.md            ← 10-slide final round presentation with speaker notes
├── live_demo_script.md        ← 3–5 minute spoken live demonstration script
├── qna_guide.md               ← Technical answers to 11 key judge questions
├── run_demo.py                ← End-to-end demo runner (case creation -> briefing)
├── adversarial_runner.py      ← Adversarial test suite runner & report generator
├── briefing_audit.py          ← Citation provenance & briefing consistency auditor
├── api_smoke_test.py          ← FastAPI runtime endpoint smoke test
├── adversarial_manifest.json  ← Machine-readable catalog of 19 adversarial scenarios
├── adversarial_report.json    ← Machine-readable evaluation results & metrics
├── adversarial_report.md      ← Human-readable Markdown evaluation report
└── fixtures/                  ← Synthetic documents & trade tables
    ├── manifest.json          ← Document catalog (dates, credibility tiers, categories)
    └── loader.py              ← Python fixture loader for tests and demos
```

---

## 3. Environment Configuration

Copy or export environment variables without real secrets:

```bash
# Optional: Set for live Anthropic Claude model calls.
# If omitted or invalid, system automatically runs in deterministic offline mode.
export ANTHROPIC_API_KEY="sk-ant-your-key-here"

# Model Selection (Defaults to Sonnet for Judge & Advocates, Haiku for fast routing)
export MODEL_JUDGE="claude-3-5-sonnet-20241022"
export MODEL_ADVOCATE="claude-3-5-sonnet-20241022"
export MODEL_FAST="claude-3-haiku-20240307"

# Audit Log & Storage Paths (Defaults to logs/)
export LOGBOOK_DB_PATH="logs/audit.db"
```

---

## 4. How to Run the End-to-End Demo

The demo runner (`demo/run_demo.py`) exercises the entire courtroom pipeline from case registration through briefing delivery:

```bash
# Standard reproducible demonstration (offline deterministic mode):
python demo/run_demo.py

# With live Anthropic API access (requires ANTHROPIC_API_KEY):
python demo/run_demo.py --live

# Custom as-of date or case ID:
python demo/run_demo.py --as-of 2027-01-25 --case-id DEMO-CASE-CUSTOM
```

### What You Will See in the Output:
1. **Scenario Ingestion**: Ingests 16 synthetic documents and 4 trade tables.
2. **Case Registration**: Creates a registered case record in the SQLite case store.
3. **LangGraph Execution**: Executes Heimdall -> Thor/Loki parallel hearings -> Cross-Examination -> Odin Adjudication -> Sufficiency -> Briefing.
4. **Audit Log Stream**: Displays real-time SQLite audit events (`QUERY`, `CLAIM`, `ATTACK`, `DEFENSE`, `RULING`).
5. **Judicial Rulings**: Displays Odin's binding verdicts (`ESTABLISHED`, `CONTESTED`, `CONCEDED`, `REJECTED`).
6. **Commercial Exposure Table**: Compares Thor high bounds, Loki low bounds, and Odin's reconciled judicial range.
7. **Traps Caught Summary**: Displays prompt injections, clock violations, retractions, and damaged records isolated.
8. **Exported Artifacts**: Confirms persistent JSON briefing and Markdown report generation.

---

## 5. How to Run Adversarial Evaluation

To run the complete synthetic adversarial evaluation suite:

```bash
# Via dedicated evaluation runner (outputs JSON and Markdown reports):
python demo/adversarial_runner.py

# Via Pytest runner:
python -m pytest tests/test_adversarial.py -v
```

The runner evaluates all 12 challenge categories:
- **Category A**: Prompt Injection Containment (`ADV-INJ-001`, `ADV-INJ-002`)
- **Category B**: Rumors & Weak Sources (Tier 4 rejection policy)
- **Category C**: Retractions & Superseded Corrections (`ADV-RET-001`, `ADV-COR-001/002`)
- **Category D**: Contradictory Evidence Classification (`ADV-CONTR-001/002`)
- **Category E**: Duplicate Source Suppression (`ADV-DUP-001/002`)
- **Category F**: Off-Event Lookalike Isolation (`ADV-OFF-001`)
- **Category G**: Damaged Records & Trade Rows (`ADV-MAL-001`, `TAB-SYNTH-DAMAGED`)
- **Category H**: Clock Cutoff Enforcement (Post-2027-01-25 evidence excluded)
- **Category I**: Insufficient Evidence Gaps & Send-Back
- **Category J**: Fake Event Decoy Early Termination (`not_real`)
- **Category K**: Advocate Crashes & Budget Limit Exhaustion
- **Category L**: Citation Integrity (Nonexistent docs, quote mismatches)

---

## 6. How to Run Briefing Consistency Audit

To audit any generated briefing deliverable for citation provenance and ruling consistency:

```bash
# Audit synthetic test briefing:
python demo/briefing_audit.py

# Audit specific generated briefing JSON artifact:
python demo/briefing_audit.py logs/demo_cases/DEMO-CASE-2027-01/briefing.json
```

The audit tool verifies:
- Every cited document exists in the store.
- Paragraph references exist and are non-empty.
- Publication dates strictly precede the `as_of` cutoff.
- Cited paragraphs share substantive keywords with claim statements.
- Briefing findings strictly map to Odin's rulings (no unadjudicated claims, no rejected claims presented as established).

---

## 7. How to Run Runtime API Smoke Tests

To verify the FastAPI backend server:

```bash
python demo/api_smoke_test.py
```

Tests all 8 core REST endpoints, error envelopes (400, 404, 409, 422), case/trial isolation, and JSON serialization.

---

## 8. Known Limitations & Production Roadmap

1. **Authentication**: The API is unauthenticated by default for hackathon convenience. Production deployment requires deploying behind an API Gateway with OAuth2 bearer token verification.
2. **Task Concurrency**: Background tasks currently run via in-process `asyncio.create_task`. High-throughput enterprise deployments will transition to Celery or Redis queue workers.
3. **Semantic Entailment**: The current validator verifies document presence, exact quote matching, and structural keyword/sector overlap. Deep natural language entailment (NLI) using embedding distance will be integrated in future phases.
