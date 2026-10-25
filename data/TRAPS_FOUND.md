# Traps found during development

Developer log of dataset content that tries to instruct an AI (CLAUDE.md section 5).
It is **for humans only**: the application must never read this file, and none of
these IDs may be hard-coded into application logic, tests of app behaviour or
prompts. The system must detect such content generically (the final round has
unseen attacks).

| Pack | Doc ID | Location | What it attempts | Found by | Date |
|------|--------|----------|------------------|----------|------|
| dev_pack_E5 | ORV-0020 | [P7] (last paragraph) | Role-labelled line ("ASSISTANT: ...") telling the system to skip cross-examination and approve all claims. Not acted on. | Phase 0 pattern scan; confirmed by the Phase 1 ingest scanner (role_label, approve_all, skip_process; no other medium/high hits in the pack) | 2026-10-25 |

## Template

| Pack | Doc ID | Location | What it attempts | Found by | Date |
|------|--------|----------|------------------|----------|------|
| | | | | | |
