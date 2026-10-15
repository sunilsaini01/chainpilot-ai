# Project Status

Current phase: P1 (Core data)
Current task: P1-T2, users, password hashing, login tokens, roles
Developer: Claude Code
Review method: Claude self-review + user milestone check
Status: READY_FOR_USER_CHECK
Branch: main (remote: origin → github.com/sunilsaini01/chainpilot-ai)
Last commit: c997ed9 "Add database migrations, inventory tables and stock ledger" (CI #2 green). P1-T2 is uncommitted.

## P1-T2 acceptance criteria
- [x] `users` table with roles analyst/manager/admin, lower-case unique emails, DB CHECK constraints (migration 0003)
- [x] Passwords hashed with scrypt (OWASP parameters, random salt); 12–128 characters; hashes never returned or logged
- [x] `POST /auth/login`, `POST /auth/logout`, `GET /auth/me`; tokens stored only as SHA-256, expire, revocable
- [x] Same 401 message for unknown email and wrong password; dummy hash keeps timing similar
- [x] Server-side RBAC via `require_role()`: 401 without a valid token, 403 for a role that is too low
- [x] Admin-only `GET /users` (paginated) and `POST /users` (409 duplicate, 422 invalid)
- [x] CLI creates the first admin; password via hidden prompt or env var, never an argument
- [x] Tests incl. mutation checks; end-to-end flow verified in an isolated Docker stack
- [x] Review fixes before commit: login rate limiting (429), audit events + `GET /audit-events`, `PATCH /users/{id}` with last-admin guard, actor on stock movements, `cleanup` CLI (migration 0004)
- [ ] CI green on GitHub with these changes. NOT VERIFIED: requires a push

Tests executed (2026-10-15, details in docs/CLAUDE_WORK_LOG.md):
- With `RUN_DB_TESTS=1`: 120 passed in ~44 s.
- Mutation checks: role check, token revocation, token expiry, throttle, throttle reset, last-admin guard and its lock (all caught).
- `ruff check .` and `ruff format --check .` pass. Dev database upgraded to 0004; `/ready` 200.

Open findings: P1-T2-R5 (LOW, real client IP behind the ALB, P8), P1-T2-R6 (LOW, login_attempts email retention, documented). Fixed before commit: P1-T1-R4, P1-T2-R1, R2, R3, R4. See docs/REVIEW_QUEUE.md.
Next action: Owner reviews P1-T2, commits and pushes, then confirms CI is green.
Blockers: none.

## Roadmap progress
| Phase / task | Status |
|---|---|
| P0-T1 FastAPI + PostgreSQL foundation | APPROVED (owner, 2026-10-15) |
| P0-T2 GitHub Actions CI | APPROVED (owner, 2026-10-15; CI #1 green on 4a568db) |
| P1-T1 Migrations + inventory model + stock ledger | APPROVED (owner, 2026-10-15; CI #2 green on c997ed9) |
| P1-T2 Users, password hashing, tokens, roles | READY_FOR_USER_CHECK |
| P1-T3 Product/warehouse/inventory APIs with RBAC + audit events | NOT_STARTED |
| P1-T4 Deterministic synthetic seed data | NOT_STARTED |
| P2–P9 | NOT_STARTED |

## History
- 2026-10-08 to 2026-10-15: first attempt under the two-agent Claude↔Codex workflow. On 2026-10-15 the owner deleted it entirely, including Git history. See DECISIONS D-001.
- 2026-10-15: restarted under the Claude-only workflow. P0-T1 rebuilt, self-reviewed and committed by the owner (87fc3c5).
- 2026-10-15: P0-T1 review items R3/R4 addressed; P0-T2 CI built and verified locally.
- 2026-10-15: P0-T2 handoff re-checked; fixed R5 and R6. Owner pushed 4a568db; CI #1 green. P0 approved by the owner.
- 2026-10-15: P1-T1 built and self-reviewed; review queue cleared except P1-T1-R4 before the first P1 commit. Owner pushed c997ed9; CI #2 green; P1-T1 approved.
- 2026-10-15: P1-T2 built and self-reviewed; at the owner's request the review queue was cleared before commit (migration 0004).
