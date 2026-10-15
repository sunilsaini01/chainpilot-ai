# Project Status

Current phase: P2 (Demand ML)
Current task: P2-T1, M5 loader, validation, fixtures and download guide
Developer: Claude Code
Review method: Claude self-review + user milestone check
Status: READY_FOR_USER_CHECK
Branch: main (remote: origin → github.com/sunilsaini01/chainpilot-ai)
Last commit: 9d9798c "Document synthetic seed data and Phase 1 completion" (CI #5 green, P1 complete). P2-T1 is uncommitted.

## P2-T1 acceptance criteria
- [x] Download guide (`docs/DATASETS.md`): browser and Kaggle CLI, terms, where files go, how to check them
- [x] Loader for the three M5 files with store filter and compact dtypes
- [x] Validator: required columns, consecutive day columns, non-negative whole sales, unique ids, consecutive calendar covering all days, positive unique prices, known weeks, every series priced
- [x] Long format: one row per series/day with date, week, events, own-state SNAP flag, weekly price (empty when not on sale)
- [x] Synthetic M5-format fixtures from a seeded script; 24 tests; new `ml-tests` CI job
- [x] Raw data, `kaggle.json` and zip archives ignored by Git
- [ ] Loader run on the real M5 files. BLOCKED: dataset must be downloaded by the owner
- [ ] CI green on GitHub with the new job. NOT VERIFIED: requires a push

Tests executed (2026-10-15, details in docs/CLAUDE_WORK_LOG.md):
- `ml`: 24 passed; Ruff passes. Mutations (SNAP mapping, price join) caught.
- API unchanged: 176 passed with PostgreSQL.

Open findings: P2-T1-R1 (MEDIUM, BLOCKED: real data), P2-T1-R2 (LOW, memory, measure after download), P1-T4-R2 (LOW, P3/P4). See docs/REVIEW_QUEUE.md.
Next action: Owner commits and pushes P2-T1, then downloads M5 into data/raw/m5 (docs/DATASETS.md).
Blockers: **M5 dataset download** (owner's Kaggle account; rules acceptance). P2-T2 to P2-T4 cannot produce real metrics until then.

## Roadmap progress
| Phase / task | Status |
|---|---|
| P0-T1 FastAPI + PostgreSQL foundation | APPROVED (owner, 2026-10-15) |
| P0-T2 GitHub Actions CI | APPROVED (owner, 2026-10-15; CI #1 green on 4a568db) |
| P1-T1 Migrations + inventory model + stock ledger | APPROVED (owner, 2026-10-15; CI #2 green on c997ed9) |
| P1-T2 Users, password hashing, tokens, roles (+ audit, rate limiting) | APPROVED (owner, 2026-10-15; CI #3 green on 51b9039) |
| P1-T3 Product/warehouse/inventory APIs with RBAC + audit events | APPROVED (owner, 2026-10-15; CI #4 green on 92b4793) |
| P1-T4 Deterministic synthetic seed data | APPROVED (owner, 2026-10-15; CI #5 green on 9d9798c) |
| P2-T1 M5 loader, validation, fixtures, download guide | READY_FOR_USER_CHECK |
| P2-T2 Features, baselines, rolling-origin backtests, metrics | BLOCKED (M5 download) |
| P2-T3 LightGBM model, uncertainty, artifacts | NOT_STARTED |
| P2-T4 Forecast tables and API | NOT_STARTED |
| P3–P9 | NOT_STARTED |

## History
- 2026-10-08 to 2026-10-15: first attempt under the two-agent Claude↔Codex workflow. On 2026-10-15 the owner deleted it entirely, including Git history. See DECISIONS D-001.
- 2026-10-15: restarted under the Claude-only workflow. P0-T1 rebuilt, self-reviewed and committed by the owner (87fc3c5).
- 2026-10-15: P0-T1 review items R3/R4 addressed; P0-T2 CI built and verified locally.
- 2026-10-15: P0-T2 handoff re-checked; fixed R5 and R6. Owner pushed 4a568db; CI #1 green. P0 approved by the owner.
- 2026-10-15: P1-T1 built and self-reviewed; review queue cleared except P1-T1-R4 before the first P1 commit. Owner pushed c997ed9; CI #2 green; P1-T1 approved.
- 2026-10-15: P1-T2 built and self-reviewed; at the owner's request the review queue was cleared before commit (migration 0004). Owner pushed 51b9039; CI #3 green; P1-T2 approved.
- 2026-10-15: P1-T3 built and self-reviewed (migration 0005); review queue cleared before commit. Owner pushed d614e58, 7d4e841, 92b4793; CI #4 green; P1-T3 approved.
- 2026-10-15: P1-T4 built and self-reviewed; P1 gate met locally. Owner pushed 528ae5e, ca0d17c, 9d9798c; CI #5 green; P1 complete.
- 2026-10-15: P2 started. P2-T1 built (no real data needed); P2-T2 blocked until M5 is downloaded.
