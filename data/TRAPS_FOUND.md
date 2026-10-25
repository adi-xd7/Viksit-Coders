# RAGNAROK Adversarial Traps and Data Integrity Log

This document records the adversarial traps, integrity anomalies, and deception vectors detected across the Runemark document corpus and synthetic evaluation packs.

---

## 1. Summary of Identified Threat Vectors

| Threat Vector | Source File / ID | Category | Detection Mechanism | Mitigation Strategy |
| :--- | :--- | :--- | :--- | :--- |
| **Tabloid Rumours / Gossip** | `ATL-0012`, `ORV-0035` | Tier 4 Credibility | Metadata Reliability Score (`RELIABILITY=4`) | Deterministically rejected by Odin if sole basis for claim; marked as unverified gossip. |
| **Retracted Government Notices** | `ORV-0014`, `RET-E6-0006` | Retraction / Correction | Header `RETRACTION:`, metadata `is_retracted` | Disqualified in Python citation validator; subsequent correction superseded. |
| **Prompt Injection Attacks** | `ADV-INJ-001`, `INJ-E6-0007` | Prompt Injection | Regex pattern scanner (`scan_text_for_injections()`) | Logged to `LogBook` under `TRAP_INJECTION`; wrapped in XML `<document>` tags; strictly barred from altering system prompt, dates, or verdicts. |
| **Clock Violations (Future Dates)**| `ADV-CLK-001`, `CLK-E6-0012` | Temporal Leakage | Timestamp comparison (`PUB_DATE > as_of`) | Strictly blocked at search and citation validation layers (`CLOCK_VIOLATION_BLOCKED`). |
| **Empty / Zero-Byte Payloads** | `ORV-0023.txt`, `DMG-E6-0008`| Damaged Data | File size check (`len(raw_text) == 0`) | Isolated gracefully without crashing; flagged `is_damaged=True`. |
| **Truncated / Cut-off Documents**| `CUT-E6-0009.txt` | Damaged Data | Premature EOF pattern check | Excluded from calculation baselines; flagged `is_damaged=True`. |
| **Mixed Character Encodings** | `ORV-0007.txt`, `ENC-E6-0010` | Malformed Encoding | Multi-stage decoder (`utf-8` -> `utf-16le` -> `latin-1` + BOM stripping) | Cleaned byte stream parsed safely; original content hash preserved. |
| **Corrupted Trade Rows** | `TAB-E6-0011`, `TAB-ORV-0009#row` | Arithmetic Corruption | Numeric parser (`float(val)`) & duplicate row check | Non-numeric rows discarded; calculation engine records exclusion rationale; missing values never treated as zero. |
| **Fabricated Decoy Events** | `HOAX-2027-01` | Non-Existent Disruption| Top-tier bulletin cross-referencing | Heimdall evaluates authenticity as `NOT_REAL`; trial terminates truthfully with zero exposure. |

---

## 2. Security Invariants Enforced in Code

1. **Untrusted Evidence Isolation**: All documents are treated as data, never instructions. Document text is enclosed in `<document id="..." tier="..." date="...">` tags.
2. **Deterministic Code Enforcement**: Date cutoffs, citation validation, trade mathematics, and budget caps are executed in compiled Python code, never trusted to LLM judgment.
3. **Audit Provenance**: Every trap detection is permanently recorded in the append-only SQLite and JSONL audit logs.
