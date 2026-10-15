# Project Status

Current phase: P0 (Foundation)
Current task: P0-T1, local runnable FastAPI + PostgreSQL foundation
Developer: Claude Code
Review method: Claude self-review + user milestone check
Status: READY_FOR_USER_CHECK
Branch: main (local repository created 2026-10-15; no remote configured)
Last commit: none (changes are uncommitted; commits not yet authorized)

Acceptance criteria:
- [x] `GET /health` returns 200 without needing the database (unit test + curl against Docker)
- [x] `GET /ready` returns 200 when Postgres answers and 503 when it is down (unit tests + real stop/start check)
- [x] DB URL built with `URL.create()`; password with `@ : / # ?` verified end-to-end
- [x] Docker Compose starts Postgres 16 + API; both healthy; ports bound to 127.0.0.1 only
- [x] API container runs as a non-root user
- [x] Configuration via environment variables, `.env.example` provided, `.env` ignored by Git
- [x] Ruff lint + format pass; pytest passes (unit and Postgres integration)
- [x] README explains how to run and test
- [ ] CI runs these checks automatically (P0-T2)

Tests executed (2026-10-15, details in docs/CLAUDE_WORK_LOG.md):
- `pytest -q` gave 10 passed, 1 skipped. With `RUN_DB_TESTS=1` against Compose Postgres: 11 passed.
- `ruff check .` and `ruff format --check .` pass.
- `docker compose config`, `up --build`, `ps`, curl `/health`, `/ready`, `/docs`, and the database stop/start check: all as expected.

Open findings: P0-T1-R3 (LOW, test deprecation warning), P0-T1-R4 (LOW, structured logs). See docs/REVIEW_QUEUE.md.
Next action: Owner checks P0-T1. After approval, start P0-T2 (GitHub Actions CI).
Blockers: none. Commits await owner authorization, and a GitHub remote is needed before CI can actually run.

## Roadmap progress
| Phase | Status |
|---|---|
| P0 Foundation | P0-T1 READY_FOR_USER_CHECK; P0-T2 CI NOT_STARTED |
| P1–P9 | NOT_STARTED |

## History
- 2026-10-08 to 2026-10-15: first attempt under the two-agent Claude↔Codex workflow (P0-T1 approved by Codex; P0-T2/T3 in progress). On 2026-10-15 the owner deleted it entirely, including Git history. See DECISIONS D-001.
- 2026-10-15: restarted under the Claude-only workflow. P0-T1 rebuilt and self-reviewed.
