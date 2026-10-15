# Project Status

Current phase: P1 (Core data)
Current task: P1-T4, deterministic synthetic seed data (completes P1)
Developer: Claude Code
Review method: Claude self-review + user milestone check
Status: READY_FOR_USER_CHECK
Branch: main (remote: origin → github.com/sunilsaini01/chainpilot-ai)
Last commit: 92b4793 "Document inventory APIs, capacity rules and data retention" (CI #4 green). P1-T4 is uncommitted.

## P1-T4 acceptance criteria
- [x] Deterministic plan: same seed gives identical data (tested); different seeds differ
- [x] Spec bounds enforced: 100–500 products, 3–5 warehouses
- [x] Clearly synthetic: `SYN-` SKUs, `SYN-WH` codes, CLI output says SYNTHETIC, `seed.loaded` audit event
- [x] Opening stock through the ledger (`receipt`, `SEED-OPENING`, no user); capacity respected (≤70% fill); ledger = on_hand
- [x] Realistic mix: ~80% of pairs stocked, ~10% of those low (1–20 units)
- [x] Safe: refuses a second load, never deletes, no demo user accounts
- [x] `python -m app.cli seed` verified at max size in Docker (~9 s)
- [ ] CI green on GitHub with these changes. NOT VERIFIED: requires a push

## P1 phase gate (spec: "CRUD and role tests pass; audit foundation")
- [x] Migrations 0001–0005, auth/RBAC, products, warehouses, inventory, stock ledger, audit events, seeds
- [x] CRUD and role tests pass locally (176 tests with PostgreSQL)
- [ ] Confirmed by CI on the pushed P1-T4 commit and the owner's milestone check

Tests executed (2026-10-15, details in docs/CLAUDE_WORK_LOG.md):
- With `RUN_DB_TESTS=1`: 176 passed in ~35 s. No DB: 48 passed, 128 skipped.
- Mutation checks for the seed: determinism, already-seeded guard, fill limit, low-stock share (all caught).
- `ruff check .` and `ruff format --check .` pass.

Open findings: P1-T4-R2 (LOW, extend the seed with suppliers/POs/shipments in P3/P4); P1-T2-R5 needs only its P8 value. See docs/REVIEW_QUEUE.md.
Next action: Owner reviews P1-T4, commits and pushes, then confirms CI is green (P1 milestone).
Blockers: none for P1. P2 will need the M5 dataset downloaded from Kaggle by the owner (account and competition rules acceptance required).

## Roadmap progress
| Phase / task | Status |
|---|---|
| P0-T1 FastAPI + PostgreSQL foundation | APPROVED (owner, 2026-10-15) |
| P0-T2 GitHub Actions CI | APPROVED (owner, 2026-10-15; CI #1 green on 4a568db) |
| P1-T1 Migrations + inventory model + stock ledger | APPROVED (owner, 2026-10-15; CI #2 green on c997ed9) |
| P1-T2 Users, password hashing, tokens, roles (+ audit, rate limiting) | APPROVED (owner, 2026-10-15; CI #3 green on 51b9039) |
| P1-T3 Product/warehouse/inventory APIs with RBAC + audit events | APPROVED (owner, 2026-10-15; CI #4 green on 92b4793) |
| P1-T4 Deterministic synthetic seed data | READY_FOR_USER_CHECK |
| P2–P9 | NOT_STARTED |

## History
- 2026-10-08 to 2026-10-15: first attempt under the two-agent Claude↔Codex workflow. On 2026-10-15 the owner deleted it entirely, including Git history. See DECISIONS D-001.
- 2026-10-15: restarted under the Claude-only workflow. P0-T1 rebuilt, self-reviewed and committed by the owner (87fc3c5).
- 2026-10-15: P0-T1 review items R3/R4 addressed; P0-T2 CI built and verified locally.
- 2026-10-15: P0-T2 handoff re-checked; fixed R5 and R6. Owner pushed 4a568db; CI #1 green. P0 approved by the owner.
- 2026-10-15: P1-T1 built and self-reviewed; review queue cleared except P1-T1-R4 before the first P1 commit. Owner pushed c997ed9; CI #2 green; P1-T1 approved.
- 2026-10-15: P1-T2 built and self-reviewed; at the owner's request the review queue was cleared before commit (migration 0004). Owner pushed 51b9039; CI #3 green; P1-T2 approved.
- 2026-10-15: P1-T3 built and self-reviewed (migration 0005); review queue cleared before commit. Owner pushed d614e58, 7d4e841, 92b4793; CI #4 green; P1-T3 approved.
- 2026-10-15: P1-T4 built and self-reviewed; P1 gate met locally.
