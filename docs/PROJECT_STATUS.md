# Project Status

Current phase: P2 (Demand ML)
Current task: P2-T2, baselines, rolling-origin backtests, metrics and features
Developer: Claude Code
Review method: Claude self-review + user milestone check
Status: READY_FOR_USER_CHECK
Branch: main (remote: origin → github.com/sunilsaini01/chainpilot-ai)
Last commit: a5ad708 "Record M5 validation results and memory measurements" (CI #7 green). P2-T2 is uncommitted.

## P2-T2 acceptance criteria
- [x] Seasonal naive baseline (spec) and a 28-day moving average
- [x] Rolling-origin backtest: 3 non-overlapping 28-day windows ending 2016-04-24; forecaster sees only data up to its origin (tested)
- [x] Metrics: MAE, WAPE, bias, RMSSE for 7/14/28-day horizons; split dates recorded; no invented numbers
- [x] Real results on all 10 stores (30,490 series) in `docs/MODEL_RESULTS.md` and `docs/results/p2_baselines.json` with provenance and data checksums
- [x] One metric cross-checked independently (0.8876 vs 0.888)
- [x] Leakage-safe features (min lag 28), proven by a perturbation test; fast on real data (one store 2.5 s)
- [ ] CI green on GitHub. NOT VERIFIED: requires a push

Tests executed (2026-10-15, details in docs/CLAUDE_WORK_LOG.md):
- `ml`: 44 passed; Ruff passes. Four leakage/logic mutations caught.
- Real data: all-stores backtest 133 s.

Open findings: P2-T2-R2 (LOW, results from `a5ad708-dirty`, committed together), P2-T2-R3 (LOW, unweighted RMSSE documented), P1-T4-R2 (LOW, P3/P4). See docs/REVIEW_QUEUE.md.
Next action: Owner commits and pushes P2-T2, then confirms CI.
Blockers: none. P2-T3 needs approval to install LightGBM (new dependency).

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
| P2-T2 Features, baselines, rolling-origin backtests, metrics | READY_FOR_USER_CHECK |
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
- 2026-10-15: owner downloaded M5; real data validated; long-table memory fixed (one store 3.5 GB to 179 MB).
- 2026-10-15: P2-T2 built; first real baseline results on all 10 M5 stores (docs/MODEL_RESULTS.md).
