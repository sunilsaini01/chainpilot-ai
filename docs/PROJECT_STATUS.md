# Project Status

Current phase: P2 (Demand ML)
Current task: P2-T4, forecast publishing, import and API (completes P2)
Developer: Claude Code
Review method: Claude self-review + user milestone check
Status: READY_FOR_USER_CHECK
Branch: main (remote: origin → github.com/sunilsaini01/chainpilot-ai)
Last commit: 0c32413 "Record validated model selection and test results" (CI #10 green). P2-T4 and the review fixes are uncommitted.

## P2-T4 acceptance criteria
- [x] Forecasts for the 28 days after the data (2016-04-25..05-22) for all 30,490 M5 series, with calibrated 80% intervals, written as CSV + manifest (provenance, checksum)
- [x] Migration 0006 (`forecast_runs`, `forecasts`) with database checks on interval order and steps
- [x] Validated, all-or-nothing, audited import (`import-forecasts`); duplicates refused; 853,720 rows in ~45 s
- [x] `GET /forecasts/runs`, `GET /forecasts` (filters, paging, `X-Total-Count`, `X-Dataset` label), analyst+
- [x] M5 forecasts kept separate from the simulated SYN- products (spec section 3)
- [x] Final check on untouched actuals: beats the moving average (WAPE 0.717 vs 0.739 at 28 days), intervals calibrated (~80%)
- [ ] `POST /forecasts/jobs` (spec section 5): deferred to the background-worker phase
- [ ] CI green on GitHub. NOT VERIFIED: requires a push

## P2 phase gate (spec: "reproducible time-split metrics; inference API")
- [x] Time-split metrics with recorded origins, versions and data checksums; baselines reproduced from clean code (identical)
- [x] Inference served through the API (published forecasts)
- [x] Clean re-run from `0c32413`: baselines and model selection identical (reports replaced)
- [ ] CI green, then owner milestone check

Tests executed (2026-10-16, details in docs/CLAUDE_WORK_LOG.md):
- `ml`: 75 passed. API with PostgreSQL: 195 passed. Ruff passes.
- Real data: publish 5 min; import 45 s; holdout check 17 s; isolated Docker end-to-end OK.

Open findings: P2-T4-R1 (MEDIUM, under-forecast 5–8% on the holdout; handle in P4), P1-T4-R2 (LOW, P3/P4). See docs/REVIEW_QUEUE.md.
Next action: owner commits and pushes; confirm CI; P2 milestone check.
Blockers: none.

## Roadmap progress
| Phase / task | Status |
|---|---|
| P0-T1 FastAPI + PostgreSQL foundation | APPROVED (owner, 2026-10-15) |
| P0-T2 GitHub Actions CI | APPROVED (owner, 2026-10-15; CI #1 green on 4a568db) |
| P1-T1 Migrations + inventory model + stock ledger | APPROVED (owner, 2026-10-15; CI #2 green on c997ed9) |
| P1-T2 Users, password hashing, tokens, roles (+ audit, rate limiting) | APPROVED (owner, 2026-10-15; CI #3 green on 51b9039) |
| P1-T3 Product/warehouse/inventory APIs with RBAC + audit events | APPROVED (owner, 2026-10-15; CI #4 green on 92b4793) |
| P1-T4 Deterministic synthetic seed data | APPROVED (owner, 2026-10-15; CI #5 green on 9d9798c) |
| P2-T1 M5 loader, validation, fixtures, download guide | APPROVED (owner, 2026-10-15; CI #7 green on a5ad708) |
| P2-T2 Features, baselines, rolling-origin backtests, metrics | APPROVED (owner, 2026-10-15; CI #8 green on f5601f9) |
| P2-T3 LightGBM model, uncertainty, artifacts | APPROVED as first version (owner, 2026-10-15; CI #9 green on 7ead45b) |
| P2-T3b Improved model: validation period, weekly models, calibrated intervals | APPROVED (owner, 2026-10-16; CI #10 green on 0c32413) |
| P2-T4 Forecast tables, import and API | READY_FOR_USER_CHECK |
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
- 2026-10-15: owner downloaded M5; real data validated; long-table memory fixed (one store 3.5 GB to 179 MB).
- 2026-10-15: P2-T2 built; first real baseline results on all 10 M5 stores (docs/MODEL_RESULTS.md).
- 2026-10-15: P2-T3 built; LightGBM evaluated honestly (ties/loses to the 28-day moving average); artifacts pipeline works.
- 2026-10-16: P2-T3b: weekly LightGBM chosen on validation; beats the moving average on the test windows; intervals calibrated.
- 2026-10-16: P2-T4 built (publish, import, API, holdout check); review fixes for P2-T2-R2/R3.
