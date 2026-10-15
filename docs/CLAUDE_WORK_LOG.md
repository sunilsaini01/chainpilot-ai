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

## 2026-10-15 11:00 UTC — P0 close-out and P1-T1
- Starting commit / branch: `4a568db` on `main` (pushed by the owner), working tree clean.
- Objective and plan: (1) record the first GitHub CI result; (2) the owner approved P0 ("it's done so check and go ahead"), so start P1-T1: Alembic, core inventory tables, a stock-movement service, tests, Compose migrate job, CI check.
- CI verification (public GitHub API): run 38721880236 (CI #1) on `4a568db` concluded `success`; both jobs and all steps succeeded. The only annotation is a notice that `ubuntu-latest` moves to Ubuntu 26 on 2026-10-19, so both jobs are now pinned to `ubuntu-24.04` (P0-T2-R7). Job logs need authentication (HTTP 403), so the pytest output itself was not read.
- Files changed and why:
  - `apps/api/app/models.py` (new): Product, Warehouse, Inventory, InventoryMovement, MovementReason; constraint naming convention; CHECK constraints.
  - `apps/api/app/inventory_service.py` (new): `record_movement()`, `InsufficientStockError`.
  - `apps/api/alembic.ini`, `apps/api/migrations/{env.py,script.py.mako}`, `migrations/versions/20261015_0001_core_inventory_tables.py` (new).
  - `apps/api/tests/conftest.py` (new, throwaway-database fixtures), `tests/test_migrations.py` (3 tests), `tests/test_inventory_service.py` (10 tests).
  - `apps/api/requirements.txt` (+ `alembic==1.20.0`), `apps/api/Dockerfile` (copy migrations), `docker-compose.yml` (`migrate` service, shared env anchor), `.github/workflows/ci.yml` (Ubuntu 24.04 pin, migration check step).
  - `README.md`, `docs/{DECISIONS,REVIEW_QUEUE,PROJECT_STATUS}.md`.
- Tests run / actual results (Windows 11, Python 3.11.9, Docker 29.7.2, Compose v5.4.0):
  - Alembic 1.20.0 checked on PyPI (official sqlalchemy/alembic, released 2026-09-11) and installed.
  - First DB run: 13 errors from Alembic's `path_separator` deprecation warning (P1-T1-R1). After the fix: `RUN_DB_TESTS=1 pytest -q` gives 29 passed in 4.5 s.
  - Mutation checks: removing `.with_for_update()` made the concurrency test fail with `['sold', 'sold']`; adding an unmigrated `region` column made the sync test fail with `add_column`. Both files were restored (diff identical) and all 29 tests passed again.
  - No `%pytest%` databases left behind afterwards (checked with psql).
  - `docker compose up --build --detach --wait`: exit 0; `migrate` Exited (0) after "Running upgrade -> 0001"; `alembic_version` = 0001; tables `inventory, inventory_movements, products, warehouses`; `/ready` 200. A second `up` was also exit 0 with no new upgrade; `alembic current` gives `0001 (head)`.
  - Ruff: fixed one E501 and applied `ruff format` to 2 files; `ruff check .` and `ruff format --check .` pass. After formatting: no DB 15 passed, 14 skipped; with DB 29 passed.
  - NOT VERIFIED: the new CI step and Ubuntu 24.04 pin on GitHub (not pushed yet).
- Self-review findings and fixes: P1-T1-R1 verified; R2/R3 LOW open; R4 MEDIUM open (actor column planned for P1-T3); R5 documented.
- Known limitations / blockers: no users/auth yet (P1-T2); no API endpoints for the new tables yet (P1-T3).
- Ending commit (if any): none. Changes are uncommitted on top of `4a568db`.
- Next recommended task: owner reviews, commits and pushes; confirm CI is green; then P1-T2 (users, password hashing, login tokens, roles).

## 2026-10-15 11:40 UTC — Review queue fixes before the P1-T1 commit
- Starting commit / branch: `4a568db` on `main`, with P1-T1 uncommitted.
- Objective and plan: the owner asked to fix the open review-queue items before committing. Fixed: P1-T1-R3 (`updated_at` trigger), P1-T1-R2 (history ordering), P0-T2-R3 (SHA pinning), P0-T1-R3 (`httpx2`, owner approved via question). Not fixable yet: P1-T1-R4 (actor column needs the users table from P1-T2).
- Files changed and why:
  - `apps/api/migrations/versions/20261015_0002_updated_at_triggers.py` (new): trigger function and three triggers.
  - `apps/api/app/models.py`: `updated_at_column()` helper with `server_onupdate=FetchedValue()`.
  - `apps/api/app/inventory_service.py`: `movement_history()` ordered by `created_at DESC, id DESC`.
  - `apps/api/tests/test_inventory_service.py`: +5 tests (three history, two `updated_at`).
  - `.github/workflows/ci.yml`: actions pinned to commit SHAs.
  - `apps/api/requirements-dev.txt` (`httpx` → `httpx2==2.13.1`), `apps/api/pyproject.toml` (removed the warning exception).
  - `docs/{REVIEW_QUEUE,DECISIONS,PROJECT_STATUS}.md`, this log.
- Tests run / actual results:
  - `git ls-remote --tags` for actions/checkout and actions/setup-python: v7 = v7.0.1 = `3d3c42e…`; v7 = v7.0.0 = `5fda3b9…`.
  - After the trigger and history changes: `RUN_DB_TESTS=1 pytest -q` gave 33 passed.
  - Mutation: migration 0002 moved away gave 2 failed (both `updated_at` tests); restored.
  - Mutation: `id` tie-breaker removed: the original 3-movement test still passed (a weak test, found in self-review), so a shuffled 20-row test was added. With the mutation it failed (`[4, 1, 9, 8, 17, 3, ...]`); restored (diff identical) and it passed. Full suite: 34 passed.
  - Docker: `docker compose up --build --wait` exit 0; migrate log "Running upgrade 0001 -> 0002"; `alembic_version` = 0002; triggers `trg_inventory_set_updated_at, trg_products_set_updated_at, trg_warehouses_set_updated_at`; `/ready` 200; stack stopped.
  - `httpx2==2.13.1` installed after owner approval; `httpx` and `httpcore` uninstalled; `import httpx` gives ModuleNotFoundError; `pip check` clean. No DB: 15 passed, 19 skipped. With DB: 34 passed. `ruff check .` and `ruff format --check .` pass. No leftover `%pytest%` databases.
  - NOT VERIFIED: CI on GitHub with these changes (not pushed yet).
- Self-review findings and fixes: found and fixed a weak ordering test (above). Remaining open: P1-T1-R4 (scheduled for P1-T3).
- Ending commit (if any): none. The owner will commit and push.
- Next recommended task: owner commits and pushes; confirm CI green; then P1-T2.

## 2026-10-15 12:00 UTC — P1-T1 CI verification
- Starting commit / branch: `c997ed9` on `main` (pushed by the owner), working tree clean.
- Tests run / actual results: GitHub Actions run 38724402173 (CI #2) on `c997ed9` concluded `success`: both jobs ran on the `ubuntu-24.04` label, every step succeeded (including "Check database migrations ran"), the actions ran from their pinned SHAs, and both jobs had 0 annotations. Job logs were not read (they need authentication).
- Outcome: P1-T1 approved by the owner ("it's done now check and then go ahead"). P0-T2-R3 and P0-T2-R7 verified.
- Next recommended task: P1-T2 (users, password hashing, login tokens, roles), started next.

## 2026-10-15 12:45 UTC — P1-T2
- Starting commit / branch: `c997ed9` on `main`, working tree clean apart from the doc updates recording CI #2.
- Objective and plan: users with roles, secure password hashing, login/logout tokens, server-side role checks, a CLI for the first admin. No new dependencies.
- Files changed and why:
  - `apps/api/app/security.py` (new): scrypt hash/verify, dummy hash, token generation and SHA-256.
  - `apps/api/app/models.py`: `Role` (hierarchy with `at_least`), `User`, `AuthToken`.
  - `apps/api/migrations/versions/20261015_0003_users_and_auth_tokens.py` (new): tables, constraints, users `updated_at` trigger.
  - `apps/api/app/users_service.py` (new): `create_user`, `authenticate`, `issue_token`, `user_for_token`, `revoke_token`, email/password validation.
  - `apps/api/app/dependencies.py` (new): `get_db_session`, `get_bearer_token`, `get_current_user`, `require_role`.
  - `apps/api/app/schemas.py` (new), `app/routes/auth.py` (new), `app/routes/users.py` (new), `app/main.py` (routers), `app/cli.py` (new), `app/config.py` (`access_token_ttl_minutes`).
  - Tests (counts from `pytest --collect-only`): `tests/test_security.py` (21), `tests/test_users_service.py` (17), `tests/test_auth_api.py` (19), `tests/test_cli.py` (3), i.e. 60 new; `tests/conftest.py` (`api_client`, `make_user`, `login`; TRUNCATE now covers every model table automatically).
  - `docker-compose.yml`, `.env.example` (`ACCESS_TOKEN_TTL_MINUTES`), `README.md`, `docs/{DECISIONS,REVIEW_QUEUE,PROJECT_STATUS}.md`.
- Tests run / actual results (Windows 11, Python 3.11.9, Docker 29.7.2):
  - `ruff format` (5 files), one E501 fixed; `ruff check .` and `ruff format --check .` pass.
  - No DB: 36 passed, 58 skipped. With `RUN_DB_TESTS=1`: 94 passed in 29.3 s (slower because each login and user creation runs scrypt).
  - Mutation checks (each file restored afterwards, diff identical): role check disabled made 3 RBAC tests fail; revocation filter removed made 2 tests fail (API + service); expiry filter removed made 2 tests fail (API + service).
  - End-to-end in an isolated Compose project `chainpilot-e2e` (ports 8002/5436, fresh volume): migrations 0001→0002→0003; CLI created admin (`id=1`, email lower-cased); wrong password gave 401 with the generic message; admin login gave a 43-character token; `/auth/me` 200; admin `POST /users` 201; analyst `GET /users` 403; admin `GET /users` 200; no token 401; logout 204 then the same token 401. DB: 0 rows contain the raw token, 2 tokens, 1 revoked; password hashes start with `scrypt$16384$8$5$`. API logs: 0 occurrences of either password or either token; log lines contain user ids only. The project was then removed with `down --volumes --rmi local` (its own volume and images only; `chainpilot-ai_postgres_data` untouched).
  - Development stack: `docker compose up --build --wait` exit 0, "Running upgrade 0002 -> 0003", `alembic current` = `0003 (head)`, `/ready` 200, `/auth/me` without a token 401; stopped.
  - NOT VERIFIED: CI on GitHub for this task (not pushed yet).
- Self-review findings and fixes: fixed during the task: the TRUNCATE list would have missed new tables (now generated from the models); an unclear log comment. Open: P1-T2-R1 (MEDIUM, login rate limiting, planned P7), R2–R4 (LOW; P1-T3/P8).
- Ending commit (if any): none. The owner will commit and push.
- Next recommended task: owner commits and pushes; confirm CI green; then P1-T3 (product/warehouse/inventory APIs with RBAC, audit_events, actor on stock movements, user deactivation).

## 2026-10-15 13:30 UTC — P1-T2 review-queue fixes (owner request before commit)
- Starting commit / branch: `c997ed9` on `main`, with P1-T2 uncommitted.
- Objective and plan: fix every open review item before committing: P1-T2-R1 (rate limiting), P1-T2-R2 (token cleanup), P1-T2-R3 (PATCH users, last-admin guard), P1-T2-R4 (audit events), P1-T1-R4 (actor on stock movements).
- Files changed and why:
  - `apps/api/migrations/versions/20261015_0004_audit_login_attempts_actor.py` (new): `login_attempts`, `audit_events`, `inventory_movements.created_by_user_id`.
  - `apps/api/app/models.py`: LoginAttempt, AuditEvent, actor column.
  - `apps/api/app/login_throttle.py` (new), `app/audit.py` (new), `app/routes/audit.py` (new).
  - `apps/api/app/routes/auth.py`: throttle check before authentication, attempt recording, login/logout audit events.
  - `apps/api/app/routes/users.py`: audit on create; `PATCH /users/{id}`.
  - `apps/api/app/users_service.py`: `update_user` (last-admin guard with row lock), `LastAdminError`, `delete_stale_tokens`.
  - `apps/api/app/inventory_service.py`: `actor_user_id` parameter. `app/schemas.py`: UpdateUserRequest, AuditEventOut. `app/cli.py`: `cleanup` command. `app/main.py`: audit router.
  - Tests (counts from `pytest --collect-only`): `tests/test_login_throttle.py` (8, new), `tests/test_user_management.py` (14, new), `tests/test_cli.py` (+2), `tests/test_inventory_service.py` (+2), i.e. 26 new; 120 in total.
  - `README.md`, `docs/{REVIEW_QUEUE,DECISIONS,PROJECT_STATUS}.md`.
- Tests run / actual results:
  - Before new tests: existing suite 94 passed with migration 0004 (model/migration sync test included). `ruff format` 4 files; `ruff check .` passes.
  - Full suite with DB: 120 passed in 44.2 s. `ruff check .` and `ruff format --check .` pass.
  - Mutations (files restored, diff identical): throttle disabled gave 4 failed; last-admin lock removed gave 1 failed (the two-thread race test); success no longer resets gave 1 failed; last-admin guard removed gave 3 failed.
  - Isolated Docker project `chainpilot-e2e` (ports 8002/5436): migrations 0001→0004; CLI admin created; admin created "victim"; 6 wrong logins gave `401 401 401 401 401 429`; correct password then gave `429` with `retry-after: 900`; admin login still 200; the only admin's self-demotion gave 409; deactivating the victim gave 200; `/audit-events` listed user.updated (`is_active [True, False]`), user.login, user.created (`email`, `role`), user.login, all with actor 1; `login_attempts` held 5 failures for the victim and 2 successes for the admin; `cleanup --days 30` ran ("Deleted 0 stale tokens and 0 old login attempts"). The project was removed with its own volume and images; `chainpilot-ai_postgres_data` untouched.
  - Development stack: "Running upgrade 0003 -> 0004", `alembic current` = `0004 (head)`, `/ready` 200; stopped.
  - NOT VERIFIED: CI on GitHub for these changes (not pushed yet).
- Self-review findings and fixes: all five targeted items VERIFIED. New LOW items: P1-T2-R5 (real client IP behind the ALB, P8) and P1-T2-R6 (retention of emails in login_attempts, documented).
- Ending commit (if any): none. The owner will commit and push.
- Next recommended task: owner commits and pushes; confirm CI green; then P1-T3 (product/warehouse/inventory APIs with RBAC, using `record_event` and `actor_user_id`).
