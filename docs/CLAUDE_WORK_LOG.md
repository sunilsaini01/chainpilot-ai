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

## 2026-10-15 09:40 UTC — P0-T1 follow-up (review items R3, R4) and P0-T2
- Starting commit / branch: `87fc3c5` on `main` (pushed to origin by the owner). Working tree was clean.
- Objective and plan: the owner asked to fix the open review-queue items first, then continue. (1) P0-T1-R3: Starlette deprecation warning. (2) P0-T1-R4: structured logs. (3) P0-T2: GitHub Actions CI (lint, tests with Postgres, Docker smoke test).
- Files changed and why:
  - `apps/api/pyproject.toml`: `filterwarnings = error`, plus one targeted ignore for the known Starlette/httpx warning (R3 mitigation).
  - `apps/api/app/logging_config.py` (new), `app/main.py`, `app/config.py` (`log_format`), `docker-compose.yml`, `.env.example`: JSON logging (R4).
  - `apps/api/app/config.py`, `.env.example`, local `.env` (gitignored): default host `127.0.0.1` (P0-T2-R1).
  - `apps/api/app/database.py`: `build_engine()` shared by the app and the integration test. `tests/test_database_integration.py` uses it.
  - `apps/api/tests/test_logging.py` (new, 4 tests); `tests/test_config.py` (+1 regression test).
  - `.github/workflows/ci.yml` (new): CI workflow. `.gitattributes` (new): LF endings.
  - `README.md`, `docs/{REVIEW_QUEUE,DECISIONS,PROJECT_STATUS}.md`.
- Tests run / actual results (Windows 11, Python 3.11.9, Docker 29.7.2):
  - R3: tried replacing `httpx` with `httpx2==2.13.1` (verified genuine on PyPI); the install was blocked by the local permission policy for new packages, so nothing changed. Applied the warning filter instead. `pytest -q` gave 10 passed, 1 skipped, 0 warnings.
  - R4: `docker compose up -d --build`, curl `/health` and `/ready`, stopped Postgres to make `/ready` return 503. `docker compose logs api` printed 9 lines and all 9 parsed as JSON (uvicorn startup, access logs, the readiness warning).
  - CI job 1 simulated locally: temporary `postgres:16-alpine` container on 127.0.0.1:5435 with the CI password `ci:p@ss/w#rd?`, then `ruff check .` (pass), `ruff format --check .` (pass), `pytest -v`: 15 passed but took 132 s. `--durations` showed the integration test at 130 s with `localhost` and 0.13 s with `127.0.0.1` (finding P0-T2-R1). After the fix: 16 passed in 2.62 s; a deliberate `localhost` run is now capped at 3.14 s by the connect timeout.
  - CI job 2 simulated locally with `POSTGRES_PASSWORD=ci-smoke-only`: `docker compose config --quiet` OK; `docker compose up --build --detach --wait` gave both containers healthy; first run `/health` 200 but `/ready` 503 because the existing volume had the old password (P0-T2-R2); `down --volumes` deleted the local test volume (it held only the empty P0 database). Rerun on a fresh volume: `/health` 200 and `/ready` 200.
  - Final: `docker compose up --build --wait` with the normal `.env`: both healthy, ports `127.0.0.1:8000` and `127.0.0.1:5434`, `/health` 200, `/ready` 200; stack stopped afterwards. `pytest -q` (no DB): 15 passed, 1 skipped. `git diff --check`: clean. `.gitattributes` removed the CRLF warnings.
  - NOT VERIFIED: the workflow running on GitHub's runners (not pushed yet).
- Self-review findings and fixes: P0-T1-R4 verified. P0-T1-R3 mitigated (open, awaiting dependency approval). P0-T2-R1 found and verified. P0-T2-R2 documented. P0-T2-R3 (action SHA pinning) and P0-T2-R4 (GitHub run pending) open.
- Known limitations / blockers: the CI result on GitHub is unknown until pushed. `httpx2` needs owner approval.
- Ending commit (if any): none. Changes are uncommitted on top of `87fc3c5`.
- Next recommended task: owner commits and pushes; confirm both CI jobs are green on GitHub; then P0 phase review and start P1 (Alembic migrations, users/roles, products, warehouses, inventory, synthetic seed).

## 2026-10-15 10:05 UTC — P0-T2 handoff self-review
- Starting commit / branch: `87fc3c5` on `main`, with the P0-T2 changes uncommitted.
- Objective and plan: the owner asked to re-check the P0-T2 handoff, fix any issues, then provide commit/push commands.
- Files changed and why:
  - `apps/api/tests/test_config.py`: autouse fixture clears settings environment variables (P0-T2-R5).
  - `.github/workflows/ci.yml`: `actions/checkout` v4→v7, `actions/setup-python` v5→v7 (P0-T2-R6).
  - `docs/REVIEW_QUEUE.md`, `docs/DECISIONS.md` (D-010), `docs/PROJECT_STATUS.md`, this log.
- Tests run / actual results:
  - Before the fix: `pytest tests/test_config.py` with `POSTGRES_HOST=db.example` etc. gave 1 failed (`test_default_host_is_ipv4_loopback`), 6 passed.
  - After the fix: misleading env gives 7 passed; CI-like env (full suite, no DB) gives 15 passed, 1 skipped; clean env gives 15 passed, 1 skipped. `ruff check .` and `ruff format --check .` pass.
  - Checked the GitHub API and the actions' `action.yml`: v4/v5 use `node20`, v7 uses `node24`; v7 inputs are compatible. `ci.yml` parsed with PyYAML: 2 jobs, all steps present.
  - NOT VERIFIED: the workflow on GitHub's runners (not pushed yet).
- Self-review findings and fixes: P0-T2-R5 verified; P0-T2-R6 fixed.
- Known limitations / blockers: P0-T1-R3 (`httpx2` approval), P0-T2-R3 (SHA pinning), P0-T2-R4 (first GitHub run).
- Ending commit (if any): none. The owner will commit and push.
- Next recommended task: after the push, confirm both CI jobs are green, then begin P1.
