# Project Status

Current phase: P1 (Core data)
Current task: P1-T3, product/warehouse/inventory APIs with roles, audit and idempotency
Developer: Claude Code
Review method: Claude self-review + user milestone check
Status: READY_FOR_USER_CHECK
Branch: main (remote: origin → github.com/sunilsaini01/chainpilot-ai)
Last commit: 51b9039 "Add users, login tokens, roles, audit events and login rate limiting" (CI #3 green). P1-T3 is uncommitted.

## P1-T3 acceptance criteria
- [x] Products: list (search, category, active, pagination), get, create, patch; admin-only writes; SKU normalized and immutable; exact decimal prices
- [x] Warehouses: list, get, create, patch; admin-only writes; code normalized and immutable
- [x] Inventory: stock levels with filters and low-stock (`max_on_hand`), movement history; readable by analysts
- [x] `POST /inventory/movements` for managers+: actor stored, audit event, 404/409/422 errors, optional `Idempotency-Key` (replay 200, conflict 409, race-safe, scoped to the user)
- [x] Every write audited with the acting user (P1-T1-R4 / P1-T2-R4 foundation used)
- [x] Migration 0005; dev database upgraded; end-to-end flow verified in an isolated Docker stack
- [x] Review fixes before commit: warehouse capacity (409, locked), `X-Total-Count` on all lists, trusted-proxy client IP (`FORWARDED_ALLOW_IPS`), `docs/DATA_RETENTION.md`
- [ ] CI green on GitHub with these changes. NOT VERIFIED: requires a push

Tests executed (2026-10-15, details in docs/CLAUDE_WORK_LOG.md):
- With `RUN_DB_TESTS=1`: 161 passed in ~25 s. No DB: 36 passed, 125 skipped.
- Mutation checks: movement role, product role, idempotency key use, race handling (after strengthening the test), search escaping, actor-scoped keys, capacity check/lock/exemption, PATCH capacity guard, total count (all caught).
- `ruff check .` and `ruff format --check .` pass.

Open findings: none that can be done before later phases. P1-T2-R5 needs only its P8 value (`FORWARDED_ALLOW_IPS` = ALB subnet). See docs/REVIEW_QUEUE.md.
Next action: Owner reviews P1-T3, commits and pushes, then confirms CI is green.
Blockers: none.

## Roadmap progress
| Phase / task | Status |
|---|---|
| P0-T1 FastAPI + PostgreSQL foundation | APPROVED (owner, 2026-10-15) |
| P0-T2 GitHub Actions CI | APPROVED (owner, 2026-10-15; CI #1 green on 4a568db) |
| P1-T1 Migrations + inventory model + stock ledger | APPROVED (owner, 2026-10-15; CI #2 green on c997ed9) |
| P1-T2 Users, password hashing, tokens, roles (+ audit, rate limiting) | APPROVED (owner, 2026-10-15; CI #3 green on 51b9039) |
| P1-T3 Product/warehouse/inventory APIs with RBAC + audit events | READY_FOR_USER_CHECK |
| P1-T4 Deterministic synthetic seed data | NOT_STARTED |
| P2–P9 | NOT_STARTED |

## History
- 2026-10-08 to 2026-10-15: first attempt under the two-agent Claude↔Codex workflow. On 2026-10-15 the owner deleted it entirely, including Git history. See DECISIONS D-001.
- 2026-10-15: restarted under the Claude-only workflow. P0-T1 rebuilt, self-reviewed and committed by the owner (87fc3c5).
- 2026-10-15: P0-T1 review items R3/R4 addressed; P0-T2 CI built and verified locally.
- 2026-10-15: P0-T2 handoff re-checked; fixed R5 and R6. Owner pushed 4a568db; CI #1 green. P0 approved by the owner.
- 2026-10-15: P1-T1 built and self-reviewed; review queue cleared except P1-T1-R4 before the first P1 commit. Owner pushed c997ed9; CI #2 green; P1-T1 approved.
- 2026-10-15: P1-T2 built and self-reviewed; at the owner's request the review queue was cleared before commit (migration 0004). Owner pushed 51b9039; CI #3 green; P1-T2 approved.
- 2026-10-15: P1-T3 built and self-reviewed (migration 0005).
