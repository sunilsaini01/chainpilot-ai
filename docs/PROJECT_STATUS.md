# Project Status

Current phase: P2 (Demand ML)
Current task: P2-T3, LightGBM model, uncertainty intervals, saved artifacts
Developer: Claude Code
Review method: Claude self-review + user milestone check
Status: READY_FOR_USER_CHECK
Branch: main (remote: origin → github.com/sunilsaini01/chainpilot-ai)
Last commit: f5601f9 "Record baseline forecast results on M5" (CI #8 green). P2-T3 is uncommitted.

## P2-T3 acceptance criteria
- [x] Tree-based model (spec section 4.C): LightGBM per store, Tweedie objective, leakage-safe features, fixed settings
- [x] Uncertainty: 80% interval from quantile models; evaluated with coverage, width and pinball loss
- [x] Evaluated in the same rolling-origin backtest as the baselines (all 10 stores, 3 origins), real numbers only
- [x] Leakage proven absent: rewriting all sales after the origin leaves predictions identical (mutations caught)
- [x] Final model artifacts saved (text format + metadata) and reloaded; not in Git
- [ ] **Beats the 28-day moving average: NO** (tie at 28 days, slightly worse at 7/14). Owner decision needed (P2-T3-R1)
- [ ] Interval calibrated to about 80%: NO (87%) (P2-T3-R2)
- [ ] CI green with LightGBM installed. NOT VERIFIED: requires a push

Tests executed (2026-10-15, details in docs/CLAUDE_WORK_LOG.md):
- `ml`: 52 passed; Ruff passes.
- Real data: full LightGBM backtest 23 min; final CA_1 model trained and reloaded.

Open findings: P2-T3-R1 (MEDIUM, owner decision), P2-T3-R2 (LOW), P2-T2-R2/R3 (LOW, documented), P1-T4-R2 (LOW). See docs/REVIEW_QUEUE.md.
Next action: Owner reviews the results, commits and pushes, and decides on P2-T3-R1.
Blockers: decision on whether to improve the model (validation-based) or use the moving average for now.

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
| P2-T3 LightGBM model, uncertainty, artifacts | READY_FOR_USER_CHECK (does not beat the baseline; decision needed) |
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
- 2026-10-15: P2-T3 built; LightGBM evaluated honestly (ties/loses to the 28-day moving average); artifacts pipeline works.
