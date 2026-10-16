# Project Status

Current phase: P3 (Delivery ML)
Current task: P3-T3, delivery-risk scores in the API
Developer: Claude Code
Review method: Claude self-review + user milestone check
Status: READY_FOR_USER_CHECK
Branch: main (remote: origin → github.com/sunilsaini01/chainpilot-ai)
Last commit: 3f32f42 (CI #14 green). P3-T3 is uncommitted.

## P3-T3 acceptance criteria
- [x] Serving design written before scoring; each month scored only with outcomes known before it
- [x] Daily tiers (high = top 10% = alert, medium, low), approximate probability, top-3 reasons; no outcomes in the published file
- [x] Validated all-or-nothing import (migration 0007), audit event, duplicate refused
- [x] Analyst API `/delivery-risk/runs`, `/scores`, `/alerts`, labelled as Olist data with `X-Dataset`
- [x] Tier check on real outcomes: high 19.9% late, medium 6.8%, low 2.0% (second look at test, rule fixed beforehand)
- [x] Tests: API 216, ML 119; import-check mutations 7/7 caught; isolated Docker import of the real 32,422 scores
- [ ] CI green on GitHub. NOT VERIFIED: requires a push

P3 gate ("no leakage; evaluated and calibrated scores"): met locally (leakage tests, rolling evaluation, calibration measured, tiers checked); waits for CI.

Open findings: P3-T3-R3 (LOW, documented), P3-T2b-R2 (LOW, documented), P2-T4-R1 (MEDIUM, P4), P1-T4-R2 (LOW, P4). See docs/REVIEW_QUEUE.md.
Next action: Owner checks and pushes P3-T3; then P4.
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
| P2-T4 Forecast tables, import and API | APPROVED (CI #11 green on 8c07d78; P2 complete) |
| P3-T1 Olist loader, label, dispatch features, split | APPROVED (pushed 0b891fb; CI #12) |
| P3-T2 Delivery-risk models (logistic baseline, tree), calibration | APPROVED as first experiment (CI #13 green on 66a6915) |
| P3-T2b Rolling monthly evaluation, recent calibration | APPROVED (CI #14 green on 3f32f42) |
| P3-T3 Delivery-risk scores in the API | READY_FOR_USER_CHECK |
| P4–P9 | NOT_STARTED |

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
- 2026-10-16: P2 complete (CI #11). P3 started: Olist downloaded; P3-T1 built.
- 2026-10-16: P3-T2 first experiment: ranking good, calibration and model choice unstable across periods.
- 2026-10-16: P3-T2b: rolling monthly evaluation; logistic regression + recent Platt chosen; calibration much improved; rank-first serving recommended.
- 2026-10-16: P3-T3: delivery-risk scores published (daily tiers with reasons), imported and served under /delivery-risk; tiers checked on real outcomes.
