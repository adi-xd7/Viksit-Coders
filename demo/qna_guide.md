# RAGNAROK Final-Round Judge Q&A Guide

Concise, technically grounded answers to the 11 key questions judges are most likely to ask, based directly on the implemented Odin courtroom codebase.

---

### 1. Why use four agents instead of one?
> **Answer**:  
> A single LLM prompted to be "neutral" suffers from compromise bias—it averages conflicting numbers and is vulnerable to whichever assertion uses the strongest rhetoric. By dividing responsibilities into four distinct roles:
> - **Heimdall** specializes in verification and retrieval without taking an advocacy stance.
> - **Thor** builds the strongest possible high-exposure case.
> - **Loki** builds the strongest possible mitigation and limited-exposure case.
> - **Odin** acts as an impartial judge who never generates claims, only evaluates admissibility and adjudicates evidence.
> 
> Cross-examination forces advocates to defend or concede their weakest claims, producing higher evidentiary rigor than any single prompt could achieve.

---

### 2. How does Odin avoid blindly accepting an LLM's answer?
> **Answer**:  
> Odin operates with a **dual-layer judgment engine**:
> 1. **Deterministic Eligibility Layer in Python** (`backend/agents/odin.py`): Before any LLM sees a claim, code validates document existence, paragraph existence, exact or normalized quote matching, source reliability tier (`ATL-0012`), clock cutoff date, retraction flags, and duplicate markers. If all citations fail, the claim is rejected deterministically. An LLM prompt can **never** override a deterministic rejection.
> 2. **Structured LLM Evaluation**: Only claims with valid Tier 1–3 citations are submitted to the LLM judge, which must return structured Pydantic verdicts (`established`, `contested`, `conceded`, `rejected`).
> 3. **Exclusivity Enforcement**: The briefing reflects only claims that passed Odin's rulings. Unadjudicated advocate claims are strictly excluded from findings.

---

### 3. How are source documents and citations verified?
> **Answer**:  
> Every citation is validated at two stages: during Odin's initial eligibility evaluation (`validate_citation`) and during briefing assembly (`validate_citation_provenance` in `backend/briefing.py`). The validator verifies:
> - Document ID exists in `manifest.json` or the evidence store.
> - Paragraph ID `Pn` exists in the parsed document.
> - Quoted excerpts match the paragraph text under whitespace/punctuation normalization.
> - Publication date matches the source metadata and precedes `as_of`.
> - Substantive topicality: The paragraph text must share meaningful keywords and sector entities with the claim statement, preventing spurious citations.

---

### 4. How are prompt injections handled?
> **Answer**:  
> Through a **defense-in-depth architecture**:
> 1. **Untrusted Evidence Boundary**: All source text is encapsulated in `<document id="..." tier="...">` tags. System prompts strictly instruct models that document contents are untrusted evidence and cannot issue instructions.
> 2. **Automated Signature Scanner**: `scan_text_for_injections()` scans evidence for known adversarial patterns (e.g., *"ignore previous instructions"*, *"override as-of date"*, *"reveal system prompt"*, *"developer mode"*).
> 3. **Audit Logging & Disclosures**: Flagged injections generate `LogEventType.TRAP_INJECTION` events in the append-only SQLite logbook and are published in Section I of the final briefing deliverable.
> 4. **Hardcoded Invariance**: Injected text cannot alter date cutoffs (enforced in Python), verdict rules, tool budgets, or deterministic trade math.

---

### 5. How are financial values calculated?
> **Answer**:  
> **Zero LLM mental arithmetic.** All numbers are calculated by deterministic Python functions in `backend/trade_calc.py`:
> - Baseline trade sums (`calculate_sum`).
> - Period-over-period percentage changes (`calculate_period_change`).
> - Substitute route offsets (`calculate_substitute_offset`).
> - Exposure bounds (`calculate_exposure_bounds`).
> 
> If a trade row has missing volume, the calculation engine returns an explicit error rather than assuming zero. Floating-point numbers are rounded to 2 or 4 decimal places per documentation, and unit compatibility (e.g. `tons` vs. `kg`) is verified before arithmetic.

---

### 6. How do you prevent future-dated evidence from influencing past investigations?
> **Answer**:  
> We enforce a strict **temporal clock check**:
> - The investigation requires a normalized `as_of` date (e.g., `2027-01-25`).
> - When validating any document citation or trade row, `pub_date` or `month` is compared directly against `as_of`:
>   ```python
>   if pub_date and as_of_date and pub_date > as_of_date:
>       return CitationValidationResult(is_valid=False, reason="Clock violation...")
>   ```
> - Documents published after the cutoff date are disqualified as clock violations, logged in the audit log, and reported under traps caught in Section I.

---

### 7. What happens when sources contradict each other?
> **Answer**:  
> The system does not pick a winner arbitrarily or hallucinate a false compromise.
> - During Cross-Examination, Thor and Loki challenge each other's conflicting figures.
> - If both sides present admissible evidence from comparable reliability tiers (e.g., Tier 2 grain exporters claiming 80% loss vs. Tier 2 rail freight claiming 65% bypass), Odin rules the claims as **`CONTESTED`**.
> - In the Briefing, contested findings are isolated in **Section C**, clearly detailing both perspectives and explaining why evidence is insufficient to settle the dispute.
> - The Commercial Exposure Table (Section F) reflects an **exposure range** spanning the credible bounds, rather than a misleading single-point estimate.

---

### 8. How do you measure evaluation quality?
> **Answer**:  
> We built a dedicated, machine-readable adversarial evaluation runner (`demo/adversarial_runner.py`) mapped to `demo/adversarial_manifest.json`.
> - It evaluates 19 scenarios covering all 12 challenge categories (A–L).
> - Every scenario asserts specific programmatic invariants (e.g., prompt injection trapped, clock violation rejected, duplicate filtered, invalid citation flagged).
> - We calculate honest, objective metrics from actual execution: scenario pass rate, injection containment rate, clock violation detection rate, and citation integrity score.
> - We do not claim 100% security against unseen attacks; we report our verified deterministic pass rates on our synthetic adversarial pack.

---

### 9. What are the system's limitations?
> **Answer**:  
> 1. **Authentication**: The API endpoints are currently unauthenticated for hackathon testing; production deployment requires an API gateway with OAuth2 / mTLS.
> 2. **Semantic Entailment**: Citation validation verifies structural existence, quote matches, and keyword/entity overlap. Full natural language inference (NLI) entailment between complex sentences will be enhanced in future phases.
> 3. **Single-Node Background Execution**: Background trial runs currently execute via in-process `asyncio.create_task`. High-throughput production scaling would transition to a distributed task broker like Celery or Temporal.

---

### 10. What happens when a model or provider fails?
> **Answer**:  
> - **Retry Budget**: LLM calls are bounded by `MAX_RETRIES = 2` and configurable timeouts (`DEFAULT_TIMEOUT = 60.0s`).
> - **Fallback & Concession Invariance**: An advocate's crash or failure is **never** interpreted as a concession. In Section F, failed advocate estimates are preserved as `None` with explicit assumption notes.
> - **Budget Exhaustion**: If the token budget (`MAX_TOKENS_PER_CASE = 200,000`) or tool call quota (`MAX_TOOL_CALLS = 12/agent`) is reached, Odin logs `LIMIT_HIT` and gracefully completes unruled claims as `CONTESTED` with an honest limit disclosure.
> - **Offline Resilience**: The system includes a deterministic mock adapter, allowing the full graph, rulings, and briefings to execute offline without internet or Anthropic API keys.

---

### 11. How would this architecture scale to more cases or users?
> **Answer**:  
> - **Per-Case Thread Locking**: Our `CaseStore` enforces per-case mutex locks (`acquire_case_lock`), preventing duplicate concurrent trials on the same case while allowing distinct cases to execute concurrently.
> - **State Machine Decoupling**: LangGraph state updates are partitioned and disjoint, allowing parallel agent execution (e.g., Thor and Loki running concurrently).
> - **Stateless REST Layer**: FastAPI handlers remain thin and delegate to `TrialService` and `CaseStore`. Swapping SQLite for PostgreSQL and `asyncio.create_task` for Celery/Redis allows linear horizontal scaling across containerized workers.
