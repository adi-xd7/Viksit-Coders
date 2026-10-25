# RAGNAROK Live Demonstration Script (3–5 Minutes)

This script guides the presenter through a live, high-impact demonstration of the **Odin Courtroom Subsystem**.

---

## Preflight Setup (T - 2 Minutes)

Open two terminal windows in `x:\Odin`:
- **Terminal 1**: Backend API Server
- **Terminal 2**: Interactive Demo / Evaluation Commands

Ensure dependencies are installed and test environment is ready:
```bash
python -m pytest tests/test_adversarial.py -v
```

---

## Segment 1: The Pitch & Architecture (0:00 – 1:00)

### Spoken Narrative:
> *"Judges, when a supply chain crisis hits, decision-makers are flooded with conflicting claims. Current LLMs hallucinate consensus and blend rumors with facts.
> 
> Our system—**Trial of the Nine Realms**—treats disruption analysis as a legal courtroom case. We have four specialized agents: **Heimdall** verifies the disruption event and gathers evidence; **Thor** argues for maximum commercial exposure; **Loki** argues for mitigation and alternative routing; and **Odin** is the impartial judge who rules on evidence admissibility, enforces deterministic trade math, and authors the final briefing.
> 
> Let's watch the full courtroom trial execute live."*

---

## Segment 2: Running the End-to-End Trial (1:00 – 2:30)

### Action:
In **Terminal 2**, run:
```bash
python demo/run_demo.py
```

### Spoken Narrative:
> *"We launch our end-to-end demo runner. Notice what is happening under the hood:
> 
> First, **Heimdall** ingests the evidence corpus and verifies the disruption event is active as of our strict cutoff date—**25 January 2027**.
> 
> Next, **Thor and Loki** generate opposing claims in parallel. Thor argues that canal sluice icing has halted 50% of Midgard wheat shipments. Loki fires back, proving that southern rail bypasses absorb 65% of the volume.
> 
> Then comes **Cross-Examination**: advocates attack each other's weakest claims.
> 
> Finally, **Odin enters the bench**. Odin doesn't just guess or average their numbers. Odin deterministically validates citations against our manifest:
> - Did this document exist before January 25?
> - Is it from a credible tier, or just a tabloid rumor?
> - Has it been retracted?
> - Does it contain prompt injections?"*

### Highlight on Screen:
Point to **Step 5 (Judicial Rulings)**:
- Show that Odin ruled claims as `ESTABLISHED`, `CONTESTED`, `CONCEDED`, or `REJECTED`.
- Show that `ADV-RUM-001` (Tier 4 tabloid) was disqualified under `tier_4_only`.
- Show that `ADV-INJ-001` (Prompt Injection) was caught and isolated.

Point to **Step 6 (Commercial Exposure Table)**:
- Show Thor's high bound vs. Loki's low bound vs. Odin's adjudicated range.
- Explain that all calculations were computed deterministically by Python code, not LLM mental math.

---

## Segment 3: Adversarial Robustness & Traps Evaluation (2:30 – 3:45)

### Spoken Narrative:
> *"Now let's put Odin under intense adversarial pressure. Hackathon evaluators planted prompt injections, fake decoy notices, retracted reports, and post-cutoff traps in the documents.
> 
> Let's run our dedicated adversarial evaluation suite live across all 12 challenge categories."*

### Action:
In **Terminal 2**, run:
```bash
python demo/adversarial_runner.py
```

### Highlight on Screen:
Point to the final summary output:
- **19 / 19 Scenarios Passed (100%)**.
- Highlight specific defense categories:
  1. **Prompt Injections Contained**: Injections attempting to force a zero-exposure verdict or exfiltrate system prompts were neutralized and logged as `TRAP_INJECTION`.
  2. **Clock Violations Rejected**: Documents published in February 2027 were strictly blocked.
  3. **Duplicate Reprints**: Verbatim duplicate articles were disqualified from inflating corroboration counts.
  4. **Damaged Trade Rows**: Corrupted data rows were excluded without assuming zero.

---

## Segment 4: Briefing Audit & Consistency Verification (3:45 – 4:30)

### Spoken Narrative:
> *"Finally, how do we guarantee that the briefing deliverable never fabricates evidence? We built an independent audit tool that verifies every claim, ruling, and citation in the briefing file against our raw evidence store."*

### Action:
In **Terminal 2**, run:
```bash
python demo/briefing_audit.py
```

### Highlight on Screen:
Point to:
- `Overall Status: PASSED`
- `Zero violations detected. Briefing is 100% consistent with judicial rulings and citation provenance.`

---

## Segment 5: Conclusion & Q&A Transition (4:30 – 5:00)

### Spoken Narrative:
> *"In summary, the Odin Courtroom subsystem delivers:
> 1. Dialectical truth-seeking through genuine adversarial debate.
> 2. Zero mental math hallucinations via deterministic calculations.
> 3. Ironclad evidence provenance with automated trap detection.
> 
> The system is fully tested with 139 passing automated tests and exposed via a production-grade FastAPI backend. Thank you, and we are ready for your questions."*

---

## Fallback Procedures (If Live Model Fails or Network Drops)

| Failure Scenario | Immediate Action | Spoken Pivot |
| :--- | :--- | :--- |
| **Anthropic API rate-limit or timeout** | Run `python demo/run_demo.py` (offline mode automatically executes with deterministic mock adapter). | *"Notice that our architecture is fully resilient to provider outages: when an upstream LLM times out, our deterministic fallback activates, preserving existing rulings and logging resource limits without crashing."* |
| **Database lock error** | Pass `--case-id DEMO-FALLBACK-$RANDOM` to create a fresh case instance. | *"Our SQLite case store supports concurrent case isolation; let's launch a fresh isolated case."* |
| **Evaluation script interruption** | Run `python -m pytest tests/test_adversarial.py -v`. | *"Let's inspect the automated pytest execution of the 15 adversarial test fixtures."* |
