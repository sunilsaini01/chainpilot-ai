# Project Status

Current phase: P1 (Core data)
Current task: P1-T1, Alembic migrations + core inventory tables + stock-movement service
Developer: Claude Code
Review method: Claude self-review + user milestone check
Status: READY_FOR_USER_CHECK
Branch: main (remote: origin → github.com/sunilsaini01/chainpilot-ai)
Last commit: 4a568db "Add CI workflow, JSON logging and review fixes" (CI #1 green). P1-T1 is uncommitted.

## P1-T1 acceptance criteria
- [x] Alembic set up; migration `0001` creates products, warehouses, inventory, inventory_movements with PKs, FKs, unique and CHECK constraints, indexes
- [x] Migrations upgrade, downgrade to base, and upgrade again cleanly (test)
- [x] Models and migrations proven in sync (test; fails when a column is added without a migration)
- [x] Stock changes only through `record_movement()`: row lock, no negative stock, ledger entry with balance_after
- [x] Concurrency: two simultaneous sales of the last unit, exactly one succeeds (test; fails when the lock is removed)
- [x] Docker Compose runs migrations in a one-shot `migrate` job before the API starts; re-running is a no-op
- [x] CI checks that migrations ran in the Docker stack; runner pinned to Ubuntu 24.04
- [ ] CI green on GitHub with these changes. NOT VERIFIED: requires a push

Tests executed (2026-10-15, details in docs/CLAUDE_WORK_LOG.md):
- No DB: 15 passed, 19 skipped. With `RUN_DB_TESTS=1`: 34 passed in ~5 s (no warnings allowed).
- Mutation checks on the lock, the model/migration sync test, the `updated_at` trigger and the history tie-breaker (all caught).
- `ruff check .` and `ruff format --check .` pass. Compose: `up --build --wait` exit 0, migrate Exited (0), dev database upgraded 0001 → 0002, `/ready` 200.

Open findings: P1-T1-R4 (MEDIUM, actor on stock movements; needs the users table, scheduled for P1-T3). Fixed before commit: P0-T1-R3 (`httpx2`), P0-T2-R3 (SHA-pinned actions), P1-T1-R2 (history ordering), P1-T1-R3 (`updated_at` trigger, migration 0002). See docs/REVIEW_QUEUE.md.
Next action: Owner reviews P1-T1, commits and pushes, then confirms CI is green.
Blockers: none.

## Roadmap progress
| Phase / task | Status |
|---|---|
| P0-T1 FastAPI + PostgreSQL foundation | APPROVED (owner, 2026-10-15) |
| P0-T2 GitHub Actions CI | APPROVED (owner, 2026-10-15; CI #1 green on 4a568db) |
| P1-T1 Migrations + inventory model + stock ledger | READY_FOR_USER_CHECK |
| P1-T2 Users, password hashing, tokens, roles | NOT_STARTED |
| P1-T3 Product/warehouse/inventory APIs with RBAC + audit | NOT_STARTED |
| P1-T4 Deterministic synthetic seed data | NOT_STARTED |
| P2–P9 | NOT_STARTED |

## History
- 2026-10-08 to 2026-10-15: first attempt under the two-agent Claude↔Codex workflow. On 2026-10-15 the owner deleted it entirely, including Git history. See DECISIONS D-001.
- 2026-10-15: restarted under the Claude-only workflow. P0-T1 rebuilt, self-reviewed and committed by the owner (87fc3c5).
- 2026-10-15: P0-T1 review items R3/R4 addressed; P0-T2 CI built and verified locally.
- 2026-10-15: P0-T2 handoff re-checked; fixed R5 and R6. Owner pushed 4a568db; CI #1 green. P0 approved by the owner.
- 2026-10-15: P1-T1 built and self-reviewed; review queue cleared except P1-T1-R4 before the first P1 commit.
