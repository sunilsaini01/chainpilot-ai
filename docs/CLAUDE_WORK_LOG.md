# Claude Work Log

Append-only. Each entry records what was actually done and actually run.

## 2026-10-15 03:10 UTC — P0-T1
- Starting commit / branch: none. There was no Git repository, because the owner deleted the previous attempt including `.git` at ≈02:19 UTC (see `docs/DECISIONS.md` D-001). Ran `git init -b main`. Nothing committed: commits not yet authorized.
- Objective and plan: build a local runnable FastAPI + PostgreSQL foundation: env-based config, a safe DB URL, `/health` and `/ready`, a non-root Docker image, Compose with localhost-only ports, unit and integration tests, Ruff, and docs. CI (P0-T2) is out of scope.
- Files changed and why:
  - `apps/api/app/config.py`: settings from env; `URL.create()` so reserved characters in passwords are safe; `SecretStr`; validated port and log level.
  - `apps/api/app/database.py`: lazy engine with `pool_pre_ping` and connect timeout; `check_database()`.
  - `apps/api/app/routes/health.py`: `/health` (no DB) and `/ready` (`SELECT 1`; 503 without leaking details).
  - `apps/api/app/main.py`: app creation and logging.
  - `apps/api/tests/*`: 6 config tests, 4 endpoint tests (SQLite stand-in plus an unreachable Postgres), 1 opt-in Postgres integration test.
  - `apps/api/{pyproject.toml,requirements.txt,requirements-dev.txt,Dockerfile,.dockerignore}`: pinned deps, Ruff/pytest config, non-root image with healthcheck.
  - `docker-compose.yml`, `.env.example`, `.gitignore`, `README.md`, `docs/{PROJECT_STATUS,CLAUDE_WORK_LOG,REVIEW_QUEUE,DECISIONS}.md`.
- Tests run / actual results (Windows 11, Python 3.11.9, Docker 29.7.2, Compose v5.4.0):
  - `pytest -q` (in `apps/api`): 10 passed, 1 skipped (DB test opt-in), 1 deprecation warning.
  - `RUN_DB_TESTS=1 ... pytest -q`: 11 passed against Compose Postgres 16 on 127.0.0.1:5434 with the password `Loc@l:p/w#2026?`.
  - `ruff check .`: all checks passed. `ruff format --check .`: 10 files already formatted.
  - `docker compose config`: both ports have `host_ip: 127.0.0.1`.
  - `docker compose up -d --build`: both containers healthy. `docker compose ps` shows `127.0.0.1:8000->8000` and `127.0.0.1:5434->5432`. `id` in the API container shows uid 10001 (appuser).
  - curl: `/health` 200 `{"status":"ok"}`; `/ready` 200 `{"status":"ready","database":"ok"}`; `/docs` 200.
  - Outage check: `docker compose stop postgres` gave `/ready` 503 `{"status":"not_ready","database":"unavailable"}` while `/health` stayed 200; after `docker compose start postgres`, `/ready` returned 200 again.
  - Host run: `uvicorn app.main:app --env-file ../../.env --port 8010` gave `/health` 200 and `/ready` 200.
  - `git add -A --dry-run`: `.env` and `.venv/` are not included.
- Self-review findings and fixes: P0-T1-R1 (log level validation) verified. P0-T1-R2 (local `.env` path) fixed via docs. R3 (httpx deprecation warning) and R4 (structured logs) are open and LOW. See `docs/REVIEW_QUEUE.md`.
- Process incident: while stopping the temporary uvicorn server I ran a broad `taskkill /F /IM python.exe` filter, which may have ended unrelated Python processes on the machine. Its output was suppressed, so the effect is unknown. Reported to the owner. In future, stop processes only by their exact PID.
- Known limitations / blockers: no CI yet (P0-T2). `git diff --check` is not meaningful without a commit; ran a dry-run add instead. Host port 5432 is used by another local Postgres, so verification used 5434 via `.env`. No migrations (P1).
- Ending commit (if any): none, uncommitted.
- Next recommended task: P0-T2, the GitHub Actions CI workflow (Ruff + pytest + Postgres service integration test + Docker build).
