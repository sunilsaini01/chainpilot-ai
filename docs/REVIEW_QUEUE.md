# Review Queue

Findings from Claude self-review, tests and user feedback. Self-review is **not** an independent review.
History note: the review queue from the deleted first attempt (including Codex findings P0-T1-R1/R2) was removed with that attempt on 2026-10-15. See `docs/DECISIONS.md` D-001.

## P0-T1-R1 — [LOW] Invalid LOG_LEVEL crashed startup with an unclear error
- Source: Claude self-review
- File and reproduction: `apps/api/app/config.py` — with `LOG_LEVEL=verbose`, `logging.basicConfig` raised `ValueError` inside app creation.
- Expected behavior: a clear settings validation error.
- Fix and regression test: `log_level` is now `Literal["DEBUG","INFO","WARNING","ERROR"]`; `test_unknown_log_level_is_rejected`.
- Status: VERIFIED

## P0-T1-R2 — [LOW] Running the API outside Docker didn't read the root `.env`
- Source: Claude self-review
- File and reproduction: `Settings` reads `.env` from the current directory, but the API is run from `apps/api` while `.env` lives at the repo root.
- Expected behavior: a documented, working way to run locally.
- Fix and regression test: README documents `uvicorn app.main:app --env-file ../../.env`. Manually verified: `/health` 200 and `/ready` 200 against Compose Postgres on port 5434. No automated test.
- Status: FIXED

## P0-T1-R3 — [LOW] Starlette deprecation warning for httpx-based TestClient
- Source: test output
- File and reproduction: `pytest` prints `StarletteDeprecationWarning: Using httpx with starlette.testclient is deprecated; install httpx2 instead.`
- Expected behavior: no deprecation warnings.
- Fix and regression test: not fixed. It is only a warning and the tests pass. Revisit when pinning versions in CI (P0-T2) once the replacement package's stability is checked.
- Update 2026-10-15: the cause is in Starlette 1.8, which wants `httpx2` in place of `httpx`. `httpx2` is genuine (published from the official pydantic/httpx2 repository and listed in Starlette's own optional dependencies), but installing it was blocked by the local permission policy for new packages. Interim mitigation: `pyproject.toml` now turns every warning into a test failure (`filterwarnings = error`) and ignores only this one message, so any *new* deprecation still fails the run. Remaining step: owner approves adding `httpx2==2.13.1` to `requirements-dev.txt`, then the ignore line can be removed.
- Update 2026-10-15 (2): owner approved `httpx2`. `requirements-dev.txt` now pins `httpx2==2.13.1` instead of `httpx==0.28.1`; `httpx` and `httpcore` were uninstalled from the venv (`import httpx` gives ModuleNotFoundError) and `pip check` reports no broken requirements. The ignore line was removed, so `filterwarnings = ["error"]` now applies to every warning. Results: no DB 15 passed, 19 skipped; with DB 34 passed.
- Status: VERIFIED

## P0-T1-R4 — [LOW] Logs are plain text, not structured
- Source: Claude self-review against spec §4.H ("structured logs")
- File and reproduction: `apps/api/app/main.py` uses `logging.basicConfig` with a text format.
- Expected behavior: JSON or key=value logs suitable for CloudWatch.
- Fix and regression test: deferred. Add before AWS work (P8) or with request logging in P1.
- Update 2026-10-15: fixed. `app/logging_config.py` adds a standard-library `JsonFormatter` (timestamp in UTC, level, logger, message, exception) and routes uvicorn's own loggers through it. `LOG_FORMAT=text` is still available for local reading. Tests in `tests/test_logging.py` (4). Verified in the running container: 9 of 9 log lines were valid JSON, including uvicorn access logs and the readiness warning.
- Status: VERIFIED

## P0-T2-R1 — [MEDIUM] `localhost` stalls for ~2 minutes on Windows
- Source: Claude self-review (timing of the local CI simulation)
- File and reproduction: `apps/api/app/config.py`, `.env.example`. With `POSTGRES_HOST=localhost` on Windows, the integration test took 130 s. `localhost` resolves to IPv6 `::1` first, but Docker publishes Postgres on IPv4 `127.0.0.1` only, so the IPv6 attempt hangs. The integration test's engine also had no connect timeout. The API's `/ready` would have lost ~3 s per call (its connect timeout).
- Expected behavior: connections are immediate.
- Fix and regression test: default host is now `127.0.0.1` (settings, `.env.example`, CI). New `build_engine()` is shared by the app and the integration test, so the test gets the same connect timeout. Regression test `test_default_host_is_ipv4_loopback`. Re-measured: full suite 2.6 s. A deliberate `localhost` run is now capped at 3.1 s.
- Status: VERIFIED

## P0-T2-R2 — [LOW] Changing POSTGRES_PASSWORD after first start breaks `/ready`
- Source: Claude self-review (local CI simulation returned 503)
- File and reproduction: `docker-compose.yml`. Postgres applies `POSTGRES_PASSWORD` only when it first initialises its volume. Changing the password later makes the API use the new one while the database still has the old one, so `/ready` returns 503.
- Expected behavior: a developer knows how to recover.
- Fix and regression test: documented in README ("Changing the password later": `docker compose down -v`). This is standard Postgres image behaviour, so no code change. CI always uses a fresh volume.
- Status: FIXED

## P0-T2-R3 — [LOW] GitHub Actions pinned by version tag, not commit SHA
- Source: Claude self-review
- File and reproduction: `.github/workflows/ci.yml` uses `actions/checkout@v7` and `actions/setup-python@v7` (updated from v4/v5, see P0-T2-R6). A tag can be moved by the action's owner, while a full commit SHA cannot.
- Expected behavior: supply-chain-hardened CI before deployment credentials exist.
- Fix and regression test: acceptable for now, because the workflow has read-only permissions and no secrets. Pin to SHAs before adding AWS OIDC credentials in P8.
- Update 2026-10-15: pinned now instead of waiting. SHAs taken from `git ls-remote` of the official repositories: `actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1` (tag v7.0.1 = v7) and `actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97` (tag v7.0.0 = v7), with the version as a trailing comment. Both tags are lightweight (they point directly at commits).
- Update 2026-10-15: verified. GitHub Actions run 38724402173 (CI #2) on `c997ed9` concluded `success`: both jobs ran on the `ubuntu-24.04` label, every step succeeded (including "Check database migrations ran"), the actions ran from their pinned SHAs, and both jobs had 0 annotations.
- Status: VERIFIED

## P0-T2-R4 — [MEDIUM] CI workflow not yet run on GitHub
- Source: Claude self-review
- File and reproduction: `.github/workflows/ci.yml` can only run on GitHub after it is pushed. Locally I reproduced both jobs' steps (same commands, same Postgres image and passwords), but GitHub's runner itself is NOT VERIFIED.
- Expected behavior: both jobs green on GitHub.
- Fix and regression test: owner pushes (or authorizes Claude to commit and push), then confirm in the Actions tab with `gh run list` / `gh run view`.
- Update 2026-10-15: the owner pushed `4a568db`. GitHub Actions run 38721880236 (CI #1) concluded `success` in 38 s. Checked via the public GitHub API: both jobs and all steps succeeded, and the only annotation is a notice that `ubuntu-latest` moves to Ubuntu 26 on 2026-10-19 (P0-T2-R7). Job logs need authentication (HTTP 403), so the pytest output itself was not read. The integration test cannot skip in CI because the workflow sets `RUN_DB_TESTS=1`.
- Status: VERIFIED

## P0-T2-R5 — [MEDIUM] Config "default" tests read real environment variables
- Source: Claude self-review of the P0-T2 handoff
- File and reproduction: `apps/api/tests/test_config.py`. `make_settings()` ignored `.env` but still read environment variables. With `POSTGRES_HOST=db.example` set, `test_default_host_is_ipv4_loopback` failed. In CI (`POSTGRES_HOST=127.0.0.1`) it would have passed by coincidence without testing the default.
- Expected behavior: config tests see only defaults plus the values each test passes in.
- Fix and regression test: autouse fixture `clear_settings_env` removes every settings variable before each config test. Verified: with misleading `POSTGRES_HOST/PORT/PASSWORD`, `LOG_LEVEL`, `LOG_FORMAT` set, 7 passed; with CI-like variables, 15 passed and 1 skipped; with a clean environment, 15 passed and 1 skipped.
- Status: VERIFIED

## P0-T2-R6 — [MEDIUM] CI used actions that run on the retiring Node 20 runtime
- Source: Claude self-review of the P0-T2 handoff
- File and reproduction: `.github/workflows/ci.yml` used `actions/checkout@v4` and `actions/setup-python@v5`. Their `action.yml` files declare `using: node20`, a runtime GitHub is retiring (deprecation warnings, later failures).
- Expected behavior: current, supported action versions.
- Fix and regression test: upgraded both to `@v7` (released 2026-07-20; `action.yml` declares `node24`). Checked that v7 still supports the inputs used (`python-version`, `cache`, `cache-dependency-path`); the only removed input, `pip-install`, is not used. Workflow re-parsed with PyYAML: both jobs and all steps present. A real GitHub run is still required (P0-T2-R4).
- Status: VERIFIED (CI #1 green; no Node 20 deprecation annotations)

## P0-T2-R7 — [LOW] `ubuntu-latest` moves to Ubuntu 26 on 2026-10-19
- Source: GitHub Actions notice on CI #1
- File and reproduction: `.github/workflows/ci.yml` uses `runs-on: ubuntu-latest`, so the runner OS would change without any commit.
- Expected behavior: CI environment changes only when we choose.
- Fix and regression test: pin both jobs to `ubuntu-24.04` (the image CI #1 passed on). Upgrade deliberately later.
- Update 2026-10-15: verified. GitHub Actions run 38724402173 (CI #2) on `c997ed9` concluded `success`: both jobs ran on the `ubuntu-24.04` label, every step succeeded (including "Check database migrations ran"), the actions ran from their pinned SHAs, and both jobs had 0 annotations. The Ubuntu 26 migration notice no longer appears.
- Status: VERIFIED

## P1-T1-R1 — [LOW] Alembic deprecation warning about `path_separator`
- Source: test run (pytest `filterwarnings = error` turned it into a failure)
- File and reproduction: `apps/api/alembic.ini` without `path_separator`: Alembic 1.20 warns about legacy path splitting.
- Expected behavior: no warnings.
- Fix and regression test: added `path_separator = os`. The strict warning filter now guards against regressions.
- Status: VERIFIED

## P1-T1-R2 — [LOW] Movements in one transaction share the same `created_at`
- Source: Claude self-review
- File and reproduction: `inventory_movements.created_at` uses `now()`, which is the transaction start time in PostgreSQL. Two movements recorded in one transaction (for example, both sides of a transfer) get identical timestamps.
- Expected behavior: a stable order for movement history.
- Fix and regression test: not a bug in the data. When the history API is built (P1-T3), order by `created_at, id` (the id always increases). Add a test there.
- Update 2026-10-15: fixed now. `movement_history()` in `app/inventory_service.py` orders by `created_at DESC, id DESC`. Tests: `test_history_is_newest_first_even_within_one_transaction`, `test_history_respects_limit_and_rejects_bad_limit`, and `test_history_tie_break_uses_id_not_storage_order` (20 movements with one timestamp, stored in shuffled id order, fixed seed). The first version of the ordering test still passed with the tie-breaker removed (PostgreSQL happened to return the ties in order), so the shuffled test was added. With the tie-breaker removed it fails (`[4, 1, 9, 8, 17, 3, ...]`); restored, it passes.
- Status: VERIFIED

## P1-T1-R3 — [LOW] `updated_at` changes only for ORM updates
- Source: Claude self-review
- File and reproduction: `onupdate=func.now()` is applied by SQLAlchemy, not by the database. A raw SQL `UPDATE` would leave `updated_at` unchanged.
- Expected behavior: `updated_at` reflects every change.
- Fix and regression test: acceptable while all writes go through the ORM/service. Revisit if raw-SQL bulk updates are added (for example, in the seed task), possibly with a database trigger.
- Update 2026-10-15: fixed. Migration `0002` adds the function `set_updated_at()` and `BEFORE UPDATE` triggers on products, warehouses and inventory. The models use `server_onupdate=FetchedValue()` (via `updated_at_column()`), so the ORM reloads the value the database set. Tests: `test_updated_at_changes_on_raw_sql_update` (even an explicit `updated_at = '2000-01-01'` is replaced) and `test_orm_sees_database_updated_at_after_update`. Both fail when migration 0002 is removed. Docker: the existing dev database upgraded `0001 -> 0002`, and all three triggers are present.
- Status: VERIFIED

## P1-T1-R4 — [MEDIUM] Stock movements do not record who made them
- Source: Claude self-review against spec §4.A ("audit actor/timestamp")
- File and reproduction: `inventory_movements` has no actor column, because users do not exist until P1-T2.
- Expected behavior: every stock change records the acting user.
- Fix and regression test: add `created_by_user_id` (FK to users) in a new migration in P1-T3, when the write APIs and audit events are built, with a test that the actor is stored.
- Update 2026-10-15: still deferred on purpose. A foreign key needs the `users` table (P1-T2); a column without a real user to reference would be scaffolding.
- Update 2026-10-15 (2): fixed now that users exist. Migration 0004 adds nullable `inventory_movements.created_by_user_id` (FK to users, ON DELETE RESTRICT; NULL only for system processes such as the seed). `record_movement(..., actor_user_id=...)` stores it. Tests: `test_movement_records_the_acting_user`, `test_movement_with_unknown_actor_is_rejected`.
- Status: VERIFIED

## P1-T1-R5 — [LOW] Running `alembic` on the host does not read the root `.env`
- Source: Claude self-review
- File and reproduction: `Settings` reads `.env` from the current directory, but Alembic runs from `apps/api` (the same situation as P0-T1-R2).
- Expected behavior: a documented way to run migrations.
- Fix and regression test: README documents `docker compose run --rm migrate alembic …` as the main path. For host use, set the `POSTGRES_*` variables.
- Status: FIXED (documentation)

## P1-T2-R1 — [MEDIUM] No rate limiting or lockout on login
- Source: Claude self-review
- File and reproduction: `POST /auth/login` accepts unlimited attempts. Each attempt costs about 0.3 s of CPU (scrypt, by design), so it is open to password guessing and to CPU exhaustion.
- Expected behavior: limit failed attempts per account and per client IP.
- Fix and regression test: planned for P7 (approval/security phase), together with an audit trail of login failures; tests for the limit and the reset. Mitigations already in place: 12-character minimum, slow hash, generic error message.
- Update 2026-10-15: fixed now at the owner's request. `login_attempts` table (migration 0004) and `app/login_throttle.py`: 5 failures per normalized email (counted since that email's last success) or 20 per client IP within 15 minutes gives 429 with `Retry-After: 900`. The check runs before scrypt. Tests in `tests/test_login_throttle.py` (8): block, case-insensitive email, password check skipped while blocked, reset on success, expiry after the window, other accounts unaffected, IP limit, attempts recorded. Mutations (throttle off, no reset) were caught. End-to-end: 6th bad login gave 429 and `Retry-After: 900`. Known limits: concurrent requests can exceed the limit by a few (count-then-insert is not locked); an attacker can lock a known email out for 15 minutes at a time; the client IP is the proxy's until P8 (P1-T2-R5).
- Status: VERIFIED

## P1-T2-R2 — [LOW] Expired and revoked tokens are never deleted
- Source: Claude self-review
- File and reproduction: `auth_tokens` grows with every login.
- Expected behavior: periodic cleanup.
- Fix and regression test: add a cleanup CLI command (or worker job) that deletes rows expired more than N days ago, with a test. Small now; needed before a long-running deployment (P8).
- Update 2026-10-15: fixed. `python -m app.cli cleanup --days 30` deletes tokens expired or revoked more than N days ago and login attempts older than N days (`--days` must be at least 1). Tests: `test_cleanup_deletes_only_old_tokens_and_attempts` (valid token and recent attempt survive), `test_cleanup_rejects_zero_days`. Ran in Docker. Scheduling it (cron or worker) belongs to deployment (P8).
- Status: VERIFIED

## P1-T2-R3 — [LOW] Admins cannot yet deactivate users or change roles
- Source: Claude self-review
- File and reproduction: only `GET /users` and `POST /users` exist. `is_active` is enforced everywhere (login and tokens) but can only be changed in the database.
- Expected behavior: `PATCH /users/{id}` for admins (role, is_active), with audit events, plus a guard so the last admin cannot demote or deactivate themselves.
- Fix and regression test: P1-T3, together with the audit_events table.
- Update 2026-10-15: fixed now. `PATCH /users/{id}` (admin) changes role, full name or `is_active`; returns 404/409/422. `update_user()` refuses to remove the last active admin and locks active admin rows (`SELECT … FOR UPDATE`) so two admins demoting each other at once cannot both succeed. Tests in `tests/test_user_management.py`, including a two-thread race. Mutations (lock removed, guard removed) were caught. End-to-end: self-demotion of the only admin gave 409; deactivation gave 200.
- Status: VERIFIED

## P1-T2-R4 — [LOW] Logins and user creation are logged, not audited
- Source: Claude self-review against spec §4.A ("audit actor/timestamp")
- File and reproduction: login, logout, failed login and user creation write JSON log lines with user ids, but there is no `audit_events` table yet.
- Expected behavior: durable audit events for security-relevant actions.
- Fix and regression test: P1-T3 adds `audit_events` (with P1-T1-R4). Record login/user-management events there, with tests.
- Update 2026-10-15: fixed now. `audit_events` (migration 0004; actor FK RESTRICT, JSONB details) written by `app/audit.py` in the same transaction as the change: `user.login`, `user.logout`, `user.created`, `user.updated` (with old/new values; a no-op PATCH writes nothing). `GET /audit-events` for managers and admins, filterable, newest first (`id` tie-break). Tests check the actor, details, ordering, access by role, and that no password or token text appears in any event. Failed logins are recorded in `login_attempts` rather than as audit events.
- Status: VERIFIED

## P1-T2-R5 — [LOW] Client IP is the proxy's address behind a load balancer
- Source: Claude self-review
- File and reproduction: `app/routes/auth.py` uses `request.client.host`. Behind the AWS ALB (P8) every request would show the balancer's IP, so the per-IP login limit would apply to all users together.
- Expected behavior: use the real client IP from `X-Forwarded-For`, but only when it is set by the trusted proxy.
- Fix and regression test: in P8, run uvicorn with `--proxy-headers --forwarded-allow-ips=<ALB subnet>`, and test it.
- Update 2026-10-15: fixed for everything that can be done before AWS exists. Uvicorn 0.54 already enables proxy headers but trusts them only from `FORWARDED_ALLOW_IPS` (default `127.0.0.1,::1`). Compose now passes `FORWARDED_ALLOW_IPS` (same default) and `.env.example` documents it. Verified in Docker: with the default, a request with a fake `X-Forwarded-For: 203.0.113.9` was recorded with the real address `172.23.0.1`; with `FORWARDED_ALLOW_IPS=*` (simulating a trusted proxy) it was recorded as `203.0.113.9`. Remaining for P8: set the variable to the ALB subnet in the ECS task definition.
- Status: FIXED (P8 configuration value pending)

## P1-T2-R6 — [LOW] `login_attempts` stores emails typed at login
- Source: Claude self-review (privacy)
- File and reproduction: needed for per-account limits, but the table holds personal data, including mistyped emails.
- Expected behavior: kept only as long as necessary.
- Fix and regression test: `cleanup --days 30` deletes old rows (tested). Document the retention in the deployment/privacy notes (P9).
- Update 2026-10-15: documented now in `docs/DATA_RETENTION.md` (what is stored about users, why, how long, how it is removed; audit events kept; CloudWatch retention for P8), linked from the README.
- Status: FIXED

## P1-T3-R1 — [MEDIUM] Concurrency test for idempotency keys did not really race
- Source: Claude self-review (mutation check)
- File and reproduction: `tests/test_inventory_api.py::test_concurrent_requests_with_same_key_apply_once`. With the race handling in `record_movement_once` removed, the test still passed: the first thread usually finished before the second looked up the key, so the unique-constraint path never ran.
- Expected behavior: the test fails when the race handling is missing.
- Fix and regression test: the test now wraps `_find_by_key` so both threads finish their first lookup (both see "not used") before either inserts, which forces the unique-constraint collision every time. Thread exceptions are collected and asserted empty. Real code: passed 3 of 3 runs. With the handling removed: fails with `UniqueViolation … uq_inventory_movements_idempotency_key`.
- Status: VERIFIED

## P1-T3-R2 — [LOW] Product search treated `%` and `_` as wildcards
- Source: Claude self-review
- File and reproduction: `GET /products?search=%` matched every product. Not SQL injection (bound parameter), but wrong results.
- Expected behavior: search text matches literally.
- Fix and regression test: `%`, `_` and `\` are escaped and `ilike(..., escape="\\")` is used. `test_search_treats_percent_and_underscore_literally` (the first version of its `_` check was itself wrong, because "Mug_Large" contains the literal text "g_L"; replaced with `p_a`). With escaping removed, the test fails.
- Status: VERIFIED

## P1-T3-R3 — [MEDIUM] Idempotency keys were shared between users
- Source: Claude self-review
- File and reproduction: if manager B reused manager A's key with the same body, B silently received A's movement and B's intended change was never applied.
- Expected behavior: a key only replays the same user's request.
- Fix and regression test: `_same_request` also compares `created_by_user_id`; another user gets 409. `test_same_key_from_another_user_is_409`; fails when the actor comparison is removed.
- Status: VERIFIED

## P1-T3-R4 — [LOW] DB tests with Postgres down produced 118 slow errors
- Source: Claude (own mistake: stopped the dev database, then ran `RUN_DB_TESTS=1`)
- File and reproduction: every database test errored separately after a connection timeout (~2 min 45 s in total) instead of one clear message.
- Expected behavior: fail fast with instructions.
- Fix and regression test: `tests/conftest.py` uses the connect timeout and calls `pytest.exit(..., returncode=1)` with "PostgreSQL at host:port is not reachable … Start it, e.g. `docker compose up -d postgres`". Verified: with Postgres stopped, the run ends in ~6 s with that message and exit code 1.
- Status: VERIFIED

## P1-T3-R5 — [LOW] Warehouse capacity is not enforced on receipts
- Source: Claude self-review
- File and reproduction: `capacity_units` is stored, but a receipt can push a warehouse's total stock above it.
- Expected behavior: capacity is respected by replenishment decisions.
- Fix and regression test: the spec places capacity constraints in inventory decisions (P4, section 4.E). Enforce there (recommendations and simulated execution), with tests. Manual receipts keep working, because physical reality wins over a recorded number.
- Update 2026-10-15: fixed now at the owner's request. `record_movement` checks capacity for positive `receipt` and `transfer_in` movements (all products in the warehouse together) and raises `WarehouseCapacityError` (API 409). Positive adjustments are exempt (a stock count records physical reality). `check_capacity` locks the warehouse row, so concurrent receipts are checked one after the other; lock order is always warehouse then inventory row, and sales take only the inventory lock, so no deadlock cycle. `PATCH /warehouses/{id}` refuses a capacity below the units stored (409) under the same lock. Tests: `tests/test_capacity_and_paging.py` (5 capacity tests, including a two-thread race that pauses each thread after reading the total). Mutations caught: lock removed, check removed, adjustments included, PATCH guard removed. End-to-end: 50/50 receipt 201, +1 receipt 409, +2 adjustment 201, lowering capacity to 10 with 52 stored 409. Capacity-aware *recommendations* remain part of P4.
- Status: VERIFIED

## P1-T3-R6 — [LOW] List endpoints return no total count
- Source: Claude self-review
- File and reproduction: `/products`, `/warehouses`, `/inventory`, `/users` and `/audit-events` page with limit/offset but do not say how many rows exist, so a UI cannot show "page 3 of 12".
- Expected behavior: a total count when the frontend needs it.
- Fix and regression test: add an `X-Total-Count` header (or a wrapper object) in P6 when the dashboard tables are built, with tests.
- Update 2026-10-15: fixed now. `app/pagination.py` `fetch_page()` counts the filtered query (ordering dropped, before limit/offset) and sets `X-Total-Count` on `/users`, `/products`, `/warehouses`, `/inventory` and `/audit-events`. `test_list_endpoints_report_total_count` checks totals with `limit=1` and that filters apply; it fails if the count is taken from the page only. A browser frontend on another origin must expose this header via CORS (P6).
- Status: VERIFIED

## P1-T4-R1 — [MEDIUM] Seed produced no low-stock items
- Source: Claude self-review (end-to-end check)
- File and reproduction: `app/seed.py`. After seeding 500 products into 5 warehouses, `GET /inventory?max_on_hand=20` returned `X-Total-Count: 0`. Every stocked pair received roughly 100+ units, so the demo had nothing for stock-out detection (P4) or the dashboard (P6) to show.
- Expected behavior: a realistic mix of well-stocked and nearly empty items.
- Fix and regression test: about 10% of stocked pairs (`LOW_STOCK_SHARE`) get 1–20 units, taken from the warehouse budget first; the rest share the remaining budget as before. `test_plan_includes_low_stock_and_well_stocked_items` (fails with `LOW_STOCK_SHARE = 0`). The default plan (seed 42) has 49 of 654 pairs at 20 units or fewer (7.5%); end-to-end, `/inventory?max_on_hand=20` gives `X-Total-Count: 49`.
- Status: VERIFIED

## P1-T4-R2 — [LOW] Seed covers products, warehouses and stock only
- Source: Claude self-review against spec section 3 (synthetic operations also list suppliers, purchase orders, lead times, shipping events and costs)
- File and reproduction: no supplier, PO or shipment tables exist yet.
- Expected behavior: the seed grows with the data model.
- Fix and regression test: extend `build_plan`/`load_plan` when those tables are added (P3 delivery data, P4 replenishment), with determinism and bounds tests like the existing ones.
- Update 2026-10-16 (P4-T3): the seed now creates suppliers (lead time and variation), purchasing rules per product and about 120 days of purchase orders (open, overdue and delivered). Tests: labels, numbering, date and quantity consistency, unreliable vs reliable supplier, `as_of` only shifting dates, the products and stock of seed 42 unchanged, and loading without extra stock movements. Shipping events are represented by the orders' promised and actual delivery dates (D-046).
- Status: VERIFIED

## P2-T1-R1 — [MEDIUM] Loader not yet run on the real M5 files
- Source: Claude self-review
- File and reproduction: `ml/demand_forecasting/m5_data.py` is tested only on the tiny synthetic M5-format fixtures. The real files are not on this machine and must be downloaded by the owner (Kaggle account and competition rules).
- Expected behavior: `python -m demand_forecasting.m5_data validate ../data/raw/m5` prints `OK: 30490 series x 1913 days`, and a one-store summary works.
- Fix and regression test: owner downloads per `docs/DATASETS.md`; then run both validate commands and record the actual output.
- Update 2026-10-15: the owner downloaded M5 into `data/raw/m5` (5 files, all ignored by Git: `git check-ignore` matched `data/raw/`). `validate ../data/raw/m5` gave `OK: 30490 series x 1913 days` (exit 0, ~13 s); `--store CA_1` gave `OK: 3049 series x 1913 days`, 5,832,737 rows, 2011-01-29 to 2016-04-24, zero_sales_share 0.639, days_without_price_share 0.194.
- Status: VERIFIED

## P2-T1-R2 — [LOW] `load_sales` reads the whole file before filtering stores
- Source: Claude self-review
- File and reproduction: `pd.read_csv` loads all 30,490 rows (default 64-bit integers, roughly 0.5 GB for the day columns) and only then filters by store and converts to int16.
- Expected behavior: memory use that a laptop handles comfortably.
- Fix and regression test: measure on the real file first (P2-T1-R1). If it is a problem, read with `dtype` int16 for day columns and/or in chunks filtered by store; add a test that the filtered result is unchanged.
- Update 2026-10-15: measured with the Windows process peak working set (my first measurement script returned 0 MB because of a 32/64-bit handle mistake in ctypes; fixed and sanity-checked at 62 MB idle). Reading the full file: 642 MB peak (fine). The real problem was in `to_long`: one store's long table used **3,476 MB** (pandas deep size) / 1,493 MB peak, because every row held Python strings for 9 repeated text columns, so all stores would need roughly 35 GB. Fix: id columns read as `category` in `load_sales` (unused categories dropped after store filtering); `compact_long` makes `d` and event columns categories and uses int16/int32/int8/float32 numbers. After: one store **179 MB**, 1,205 MB peak, ~10 s; all 10 stores 58,327,370 rows, **1,784 MB**, 6,435 MB peak, 66 s. Regression tests: `test_long_table_uses_compact_types` (fails without `compact_long`) and `test_store_filter_drops_unused_categories`. Price comparisons in tests now use a 1e-6 relative tolerance (float32).
- Status: VERIFIED

## P2-T2-R1 — [LOW] Docstring command silently merged two lines
- Source: Claude self-review
- File and reproduction: `ml/demand_forecasting/backtest.py`. A line ending in a single `\` inside a normal docstring is a line continuation, so `__doc__` showed one garbled line.
- Expected behavior: the usage text reads as written.
- Fix and regression test: rewrote the example without a continuation; checked `__doc__` prints both command lines.
- Status: FIXED

## P2-T2-R2 — [LOW] Results were produced from uncommitted code
- Source: Claude self-review (provenance)
- File and reproduction: `docs/results/p2_baselines.json` records `git_commit: a5ad708-dirty`. The provenance uses `git describe --always --dirty`, so this is reported honestly instead of a misleading clean SHA.
- Expected behavior: results traceable to exact code.
- Fix and regression test: the code is committed together with the results. To regenerate from a clean checkout, rerun the command in `docs/MODEL_RESULTS.md`; with unchanged code and data (checksums recorded) the numbers are deterministic.
- Update 2026-10-16: re-ran both the baseline backtest and the full model selection from a clean `git worktree` of `0c32413` (outputs outside the repository, so the tree stayed clean; `git describe --dirty` gave `0c32413`). Every metric (overall and per store, validation and test), the calibrated interval bounds and the chosen model are identical to the earlier reports; only the runtime differs. `docs/results/p2_baselines.json` and `p2_model_selection.json` were replaced with the clean re-runs. `p2_lightgbm.json` (the superseded first LightGBM version) keeps its original `f5601f9-dirty` stamp as a historical record; that code was committed as `35de6cc`.
- Status: VERIFIED

## P2-T2-R3 — [LOW] RMSSE is unweighted, not the M5 competition WRMSSE
- Source: Claude self-review
- File and reproduction: `metrics.mean_rmsse` averages RMSSE over series equally; the competition weighted by dollar sales across 12 aggregation levels.
- Expected behavior: users must not compare these numbers with the Kaggle leaderboard.
- Fix and regression test: documented clearly in `metrics.py` and `docs/MODEL_RESULTS.md` ("not comparable"). A weighted variant could be added if aggregate-level evaluation is needed (P2-T3).
- Update 2026-10-16: added a sales-value-weighted RMSSE (M5's bottom-level weighting: dollar sales in the 28 days before the origin, computed only from data up to the origin). `metrics.sales_value_weights`, `metrics.weighted_rmsse`, `backtest.weights_for`; `score()` reports `rmsse_weighted`. Tests: weights ignore older days and the test window (mutation "weights from the full series" caught), weighted mean by hand. Real numbers on the untouched holdout: weighted RMSSE 0.758/0.805/0.834 (weekly LightGBM) vs 0.816/0.839/0.868 (moving average). The full 12-level WRMSSE is still not computed and the docs say so; the backtest tables gain the weighted column at their next regeneration.
- Status: FIXED

## P2-T3-R1 — [MEDIUM] LightGBM does not beat the 28-day moving average
- Source: real backtest (docs/results/p2_lightgbm.json)
- File and reproduction: `ml/demand_forecasting/lgbm_model.py` with `features.DEFAULT_MIN_LAG = 28`. All stores, 3 origins: WAPE at 7/14/28 days 0.753/0.751/0.755 vs moving average 0.736/0.737/0.753; RMSSE at 28 days 0.736 for both. Better in 5 of 10 stores.
- Expected behavior: a tree model that clearly beats the strongest baseline, or a documented decision to use the baseline.
- Fix and regression test: not fixed, on purpose. Changing the model while scoring on these same windows would tune it to the test set. Proposed next step (owner decision): carve out a validation period before 2016-01-31; compare (a) one model per forecast week with minimum lags 7/14/21/28 and (b) origin-anchored "recent level" features; choose on validation only, then report once on the existing test windows.
- Update 2026-10-16: owner chose "Improve the model properly". Pre-registered plan (work log, 2026-10-15 23:20 UTC) executed: on validation (Nov 2015 – Jan 2016) the weekly-model layout won (mean WAPE 0.7651 vs single 0.7910). On the unchanged test windows it beats the 28-day moving average at all horizons (WAPE 0.718/0.725/0.740 vs 0.736/0.737/0.753; RMSSE 0.665/0.705/0.728 vs 0.675/0.714/0.736), in 8 of 10 stores (CA_4 effectively a tie). Leakage tests cover both layouts (future-perturbation test; mutation "lag-7 model also forecasts days 8–14" caught).
- Status: VERIFIED

## P2-T3-R2 — [LOW] 80% interval covers 87% (too wide)
- Source: real backtest
- File and reproduction: the 10th-percentile model predicts 0 for most zero-heavy series, so `[lower, upper]` contains most zero days. Coverage 0.870–0.873 at all horizons; per store 0.856–0.881.
- Expected behavior: coverage close to 0.80 with the narrowest honest width.
- Fix and regression test: calibrate on a validation window (e.g. conformal adjustment of the bounds, or a different lower-quantile approach for intermittent demand), then check coverage on the test windows.
- Update 2026-10-16: replaced the quantile boosters with split-conformal calibration (`conformal.py`, 10 bins by forecast size, fitted on 2,561,160 validation rows). Test coverage 0.809/0.804/0.799 at 7/14/28 days (per store 0.789–0.809), width 2.68–2.72. Tests: coverage on fresh data within 0.78–0.82, zero-heavy data, tiny-bin fallback; mutation "90% bounds" caught.
- Status: VERIFIED

## P2-T3-R3 — [LOW] Unclear error when there is nothing to train on
- Source: Claude self-review (a passing test that passed for the wrong reason)
- File and reproduction: with fewer than 29 days of history, LightGBM raised "Input data must be 2 dimensional and non empty", which is confusing for a user.
- Expected behavior: a clear message.
- Fix and regression test: `train_models` raises "no training rows: each series needs more than 28 days of history (with prices) before the origin"; `test_train_final_command_on_fixtures` checks that message.
- Status: VERIFIED

## P2-T3b-R1 — [MEDIUM] Conformal fit crashed on many exact-zero forecasts
- Source: the first official run (crashed after ~1 h of validation, before any numbers were shown)
- File and reproduction: `ml/demand_forecasting/conformal.py`. With right-open bins (`np.digitize` default), forecasts equal to the lowest edge (0) went into bin 1, leaving bin 0 empty; `np.percentile` of an empty array raised IndexError.
- Expected behavior: robust calibration on zero-heavy data.
- Fix and regression test: `right=True` in fit and apply; bins with fewer than 100 rows use the overall percentiles. `test_many_exact_zero_forecasts_are_handled`, `test_tiny_bins_fall_back_to_overall_bounds` (the old code reproduces the exact IndexError). `model_selection` now checkpoints after validation. Second run completed.
- Status: VERIFIED

## P2-T3b-R2 — [LOW] My test premise about the single model was wrong
- Source: Claude self-review (test failure)
- File and reproduction: a new test claimed the single model's forecast cannot react to last week's sales. It does, legitimately: last week's sales are training targets (dated before the origin). Not leakage.
- Expected behavior: the test checks the real difference between layouts.
- Fix and regression test: replaced by `test_next_weeks_inputs_include_last_week_only_with_a_7_day_lag`, which checks the *input features* for days 1–7 (they change with a 7-day lag and not with a 28-day lag).
- Status: FIXED

## P2-T4-R1 — [MEDIUM] Published forecasts under-forecast by 5–8%
- Source: final check on untouched data (docs/results/p2_holdout.json)
- File and reproduction: bias of the weekly LightGBM on 2016-04-25..05-22 is −6.1% / −5.0% / −7.7% at 7/14/28 days (moving average +2.1% / −1.6% / −3.9%); on the test windows it was −1.0% / −2.3% / −3.8%.
- Expected behavior: replenishment based on these forecasts must not systematically order too little.
- Fix and regression test: not a forecasting-code bug. In P4, use the 80% upper bound or an explicit safety stock in reorder points, and/or a bias correction estimated on validation data only; test that the simulator's service level meets its target.
- Update 2026-10-16 (P4-T2): replay on real demand (3 stores, 77 days). The safety-stock formula fed by the LightGBM forecast and its calibrated interval reached a 94.0% cycle service level and 96.3% fill rate at the 95% setting (pre-registered criterion ≥ 93%), with 17–34% less stock than a simple reorder rule at the same fill rate. No separate bias correction needed; the 1-point shortfall at high targets is documented.
- Status: VERIFIED

## P2-T4-R2 — [LOW] My holdout test needed files I forgot to provide
- Source: Claude (test failure while adding weighted RMSSE to the holdout)
- File and reproduction: the holdout now reads `calendar.csv` and `sell_prices.csv` for the weights; the test's temporary raw folder only had the evaluation file (FileNotFoundError).
- Fix and regression test: the test copies the fixture calendar and prices; a new test checks that the vectorised `history_scales` equals `metrics.rmsse_scales` exactly (including series that never sold).
- Status: FIXED

## P2-T4-R3 — [LOW] Short histories broke the holdout moving average
- Source: Claude self-review (test failure)
- File and reproduction: with fewer than 28 known days the moving-average window reached `d_-6..d_0`. Real M5 data has 1,913 days, so it never happened there.
- Fix and regression test: the window is clamped at day 1 (same rule as `baselines.moving_average_28`); covered by the fixture-based holdout test.
- Status: FIXED

## P2-T4-R4 — [LOW] pandas PerformanceWarning in the holdout on real data
- Source: real run (the narrow fixture did not trigger it)
- File and reproduction: adding a column to the 1,947-column evaluation table fragmented it.
- Fix and regression test: the series id is used as the index instead of a new column; the real run passes with `python -W error`.
- Status: FIXED

## P3-T1-R1 — [LOW] Missing product weights summed to 0 kg
- Source: Claude self-review (feature profiling on real data)
- File and reproduction: `ml/delivery_risk/olist_data.py`. pandas' `sum` treats an all-missing group as 0, so 16 orders whose products all lack a weight showed `total_weight_kg = 0` instead of unknown (5 orders genuinely weigh 0 g).
- Expected behavior: unknown stays unknown.
- Fix and regression test: `sum(min_count=1)`; `test_missing_weights_stay_unknown_not_zero` (fails with the old sum). Real data now: 16 missing, 5 zero.
- Status: VERIFIED

## P3-T1-R2 — [MEDIUM] Late rate jumps from 5.6% (2017) to 12.9% (Jan–Mar 2018)
- Source: real-data validation
- File and reproduction: train late rate 0.056, validation 0.129. A model fitted on 2017 alone would under-estimate risk in 2018.
- Expected behavior: risk scores whose probabilities match recent reality.
- Fix and regression test: P3-T2: report calibration on validation and test, compare models trained on 2017 with an expanding window, and consider recalibration on validation data only. Never tune on the test period.
- Update 2026-10-16: P3-T2 ran the pre-registered recalibration on validation. It made things worse: the test period's late rate (4.5%) is close to 2017's (5.6%), and Jan–Mar 2018 (12.9%) was the unusual quarter. Calibrated test ECE 0.137 vs 0.003 uncalibrated. Superseded by P3-T2-R1.
- Status: VERIFIED (handled by P3-T2b; residual issue in P3-T2b-R1)

## P3-T1-R3 — [LOW] I left a nonsense expression in the code while writing it
- Source: Claude self-review (reading back the new module before running it)
- File and reproduction: `dispatched_after_limit` was written as `(... if False else ...)`. It computed the right value but was confusing.
- Fix and regression test: rewritten plainly; `test_timing_features` checks the flag for a late and an on-time handover.
- Status: FIXED

## P3-T2-R1 — [MEDIUM] One unusual validation quarter made the model choice, calibration and threshold unreliable
- Source: pre-registered P3-T2 experiment (docs/results/p3_delivery_risk.json)
- File and reproduction: `ml/delivery_risk/experiment.py`. Validation (Jan–Mar 2018) had a 12.9% late rate, unlike 2017 (5.6%) and the test period (4.5%). Results: logistic regression chosen on validation (PR-AUC 0.361 vs 0.292) but LightGBM ranks better on test (0.366 vs 0.281); Platt calibration fitted on validation over-predicts on test (mean 18.2% vs 4.5% actual, ECE 0.137); the F1 threshold flags 34% of test orders at 10% precision.
- Expected behavior: choices that hold up when conditions change.
- Fix and regression test (proposed, needs the owner's go-ahead, and a new plan written before running): rolling-origin evaluation with several monthly windows inside Jan 2017 – Mar 2018 (no test data) to choose the model; calibrate on a **recent rolling window** (e.g. the 8 weeks of delivered orders before each scoring date) and check that rule across the windows; choose the threshold from a business rule (e.g. a fixed share of orders to review) rather than F1 on one quarter. Then evaluate once more on the unchanged test period.
- Update 2026-10-16: owner chose "Improve it properly". Pre-registered rolling monthly evaluation (P3-T2b) executed: logistic regression with recent-Platt calibration chosen on 9 development months; on the unchanged test months ECE fell from 0.137 to 0.059, alert precision rose from 10.0% to 17.3% (recall 53.2%), ROC-AUC 0.817. Probabilities are still about 2x too high on average because the monthly late rate swings 1.2%–19%; the ranking is stable (ROC-AUC 0.79–0.83 every month). Remaining work moves to P3-T3 as a serving design (rank-based tiers, same-day alert share): P3-T2b-R1.
- Status: VERIFIED (improved and measured; residual issue tracked in P3-T2b-R1)

## P3-T2-R2 — [LOW] Over-engineered first version of the logistic pipeline
- Source: Claude self-review (reading back before running)
- File and reproduction: the first draft used a hand-made transformer and a nested `ColumnTransformer` just to turn categories into strings.
- Fix and regression test: replaced by a plain `logistic_inputs()` helper; covered by the model tests (unseen categories, missing values).
- Status: FIXED

## P3-T2-R3 — [LOW] My test used an invalid pandas call
- Source: test failure
- File and reproduction: `column.where(False, "D")` raised ValueError inside a test that sets unseen categories.
- Fix and regression test: sets the categories explicitly; both models now pass the unseen-category test.
- Status: FIXED

## P3-T2b-R1 — [MEDIUM] Late probabilities drift with the monthly late rate
- Source: rolling evaluation (docs/results/p3_delivery_risk_rolling.json)
- File and reproduction: monthly late rate 1.2%–19%; calibrated mean prediction 5.7%–16.1% in the test months vs 1.2%–6.6% actual; the fixed alert cut-off flags 3.8%–23.8% of orders per month.
- Expected behavior: users get a stable, understandable risk signal and a predictable review workload.
- Fix and regression test: in P3-T3, serve a risk **tier/percentile** (relative to recent dispatches) as the main signal, label probabilities as approximate, and make the alert "top N% of the same day's dispatches". Test that the daily flagged share equals N% and that tiers are computed only from same-day or earlier orders.
- Update 2026-10-16 (P3-T3): served as designed. Tiers are ranked within each dispatch day (`ml/delivery_risk/scoring.py::assign_tiers`); the API and README present the tier as the main signal and the probability as approximate. Tests: `test_tiers_follow_the_daily_ranking` (daily share), `test_scores_ignore_outcomes_that_were_not_known_yet` (no future outcomes). On the real file the daily flagged share is 10.0%–11.1% on every day with at least 50 dispatches (monthly 3.8%–23.8% before). Small days: P3-T3-R3.
- Status: VERIFIED

## P3-T2b-R2 — [LOW] Rolling simulation only sees orders that were eventually delivered
- Source: Claude self-review
- File and reproduction: the order table (P3-T1) keeps delivered orders only, so the "recent purchases" used for the alert cut-off exclude orders that were later cancelled or never delivered. In a live system those would be scored too.
- Expected behavior: documented; small effect (about 3% of orders are not delivered).
- Fix and regression test: none needed for the experiment; a live scorer (P3-T3) scores every dispatched order.
- Update 2026-10-16 (P3-T3): the published scores are historical, so they also cover delivered orders only (the order table has no others). A live scorer would score every dispatched order; there is none in this project yet.
- Status: OPEN (documented limitation)

## P3-T3-R1 — [LOW] Reasons named the seller's state for almost every order
- Source: Claude self-review (reading real explanations before publishing)
- File and reproduction: `ml/delivery_risk/scoring.py`. The first version ranked features by coefficient × scaled value. One-hot categories are never centred, so a common category with a positive coefficient (for example a frequent seller state) became a "reason" for most orders, although it describes the typical order.
- Expected behavior: reasons say what makes this order riskier than a typical order.
- Fix and regression test: contributions are measured from the training average (coefficient × (value − training mean)), summed per source feature; `test_contributions_add_up_to_the_log_odds_difference` checks the exact identity and `test_reasons_are_the_strongest_positive_contributions` checks the reasons.
- Status: VERIFIED

## P3-T3-R2 — [LOW] One import-validation test did not test what it said
- Source: mutation check
- File and reproduction: `apps/api/tests/test_delivery_risk.py`. The "dispatch day outside the period" case changed only `dispatch_date`, so the "day differs from dispatched_at" check rejected it first. Removing the period check left all tests passing.
- Expected behavior: each validation has a test that fails without it.
- Fix and regression test: split into two cases (day mismatch; a self-consistent order after the period). All 7 import-check mutations are now caught.
- Status: VERIFIED

## P3-T3-R3 — [LOW] Very small dispatch days flag more than 10%
- Source: Claude self-review (real published file)
- File and reproduction: `ml/delivery_risk/scoring.py::assign_tiers`. The riskiest order of a day is always high tier, so 13 days with 2–9 dispatches (82 orders, mostly Saturdays and the last days of the data) flag one order each: 11%–50% of those days.
- Expected behavior: a predictable review workload. At least one review per day is a reasonable rule, and it adds only a handful of alerts.
- Fix and regression test: none; documented in MODEL_RESULTS and here. Revisit if real daily volumes are small (for example ranking against the last 7 days of dispatches).
- Status: OPEN (documented limitation)

## P3-T3-R4 — [MEDIUM] Some bad import files gave a raw database error or a broken API
- Source: Claude self-review after P3-T3 was pushed (re-reading both import modules)
- File and reproduction: `apps/api/app/delivery_risk_import.py`, `apps/api/app/forecast_import.py`.
  - `reasons = [1, 2]` passed the delivery-risk import, then `GET /delivery-risk/scores` would fail with 500 (the response expects a list of objects).
  - An id longer than its column (e.g. a 33-character `order_id`, a 17-character `store_id`) or a manifest `dataset` over 200 characters failed inside `COPY`/flush with a raw database error.
  - A duplicate order (or series and day) was only stopped by the unique constraint during `COPY`.
  - An unreadable manifest (invalid JSON, a list, a bad date) raised a raw `ValueError`; a forecast `horizon_days` above 28 would hit the table's step check.
- Expected behavior: every bad file stops before writing, with a clear message naming the problem (and the line).
- Fix and regression test: shared helpers in `app/files.py` (`read_manifest`, `check_text` with lengths read from the table definitions, a common `ImportFileError` base); reasons must be `{feature, value, effect}` objects; duplicates are found while reading; manifest values are parsed with a clear error; horizon 1–28. 17 new test cases (11 delivery risk, 6 forecasts). The rollback tests now force a database error by skipping the row checks, because duplicates no longer reach the database. Mutations: 12 of 12 caught. Both real files still pass; checking the 853,720 forecast rows takes 4.5 s instead of 3.4 s.
- Status: VERIFIED

## P4-T1-R1 — [LOW] Worked example could not tell "round up" from "round to nearest"
- Source: mutation check
- File and reproduction: `apps/api/tests/test_inventory_policy.py`. The worked example's level is 177.72, which is 178 either way, so replacing `math.ceil` with `round` left every test passing. I had also added a float-noise tolerance to the rounding that no realistic input needs; removed to keep the code plain.
- Expected behavior: the target is always rounded up (rounding down would order less than the safety stock asks for).
- Fix and regression test: `test_level_is_rounded_up_never_down` (140.48 -> 141). 11 of 11 policy mutations caught.
- Status: VERIFIED

## P4-T2-R1 — [HIGH] Integer overflow gave wrong baseline targets in the first replay run
- Source: Claude self-review (a per-store result looked impossible: in TX_1 more buffer gave a lower fill rate; a cached re-run then gave different numbers)
- File and reproduction: `ml/inventory_sim/policies.py::baseline_targets`. M5 sales are int16; `sales_28 * 28` (buffer 14 days) or `* 21` (7 days) wraps around above 32,767 without any warning, so fast sellers (e.g. 1,657 units in 28 days) got wrong targets. The 0-day setting (x 14) and the 3.5-day setting (float) were not affected; nor were the formula policies.
- Expected behavior: exact targets for every item.
- Fix and regression test: convert to float first; `test_baseline_targets_do_not_overflow_small_integer_sales` fails without the fix. The first run's numbers were discarded; the experiment was re-run from scratch, and a cached re-run reproduced it exactly. Before the fix the baseline looked worse than it is (buffer 14 d: 95.6% fill instead of 97.2%). Reported numbers use the fixed code.
- Status: VERIFIED

## P4-T2-R2 — [LOW] Two of my test expectations were wrong or too weak
- Source: test failure; mutation check
- File and reproduction: `ml/tests/test_inventory_replay.py`. (1) I expected a target of 14 with no demand uncertainty, forgetting that lead-time variation (std 1.41 days) still adds safety stock (14 + 1.645 x 1.41 = 16.3 -> 17); the code was right. (2) The weekly service-level count survived a mutation ("no lost sales" changed to "at most 2 lost"), because the example's weeks lost 4, 4 and 0 units.
- Fix and regression test: corrected expectation with the arithmetic in a comment; new test where a week loses exactly 1 unit. 13 of 13 simulator mutations caught.
- Status: VERIFIED

## P4-T2-R3 — [LOW] Forecast-driven policy places 5–10% more orders
- Source: replay results (docs/results/p4_inventory_replay.json)
- File and reproduction: LightGBM rarely forecasts exactly 0, so slow items get frequent small orders (67.5k orders vs 61–64k for the baseline). The replay has no ordering cost, minimum order or pack size.
- Expected behavior: recommendations should not create many tiny orders.
- Fix and regression test: in P4-T4, apply the supplier's minimum order and pack size (already in `order_quantity`) and test that tiny shortfalls are raised or skipped as the rules say.
- Update 2026-10-16 (P4-T4): recommendations use the supplier's minimum order and pack size; `test_tiny_shortfall_is_raised_to_the_minimum_order` (a shortfall of 3 becomes the minimum of 24). On the real data no reorder is below its minimum or outside whole packs. Whether fewer, larger orders would be cheaper overall is not modelled (no ordering cost).
- Status: VERIFIED

## P4-T3-R1 — [LOW] A comment claimed a separate random generator protected the old seed data
- Source: mutation check
- File and reproduction: `apps/api/app/seed.py`. The purchasing data had its own generator "so adding it did not change the products and stock". Using the main generator instead left every test passing, because the purchasing data is drawn after the products and stock anyway; the extra generator protected nothing.
- Fix and regression test: removed the extra generator; the comment now gives the real reason. `test_products_and_stock_are_unchanged_by_the_purchasing_data` pins seed 42's first product and stock totals. 14 purchasing and seed mutations were run; the only survivor was this one.
- Status: VERIFIED

## P4-T3-R2 — [LOW] The first migration downgrade used the wrong constraint names
- Source: test failure (`test_downgrade_then_upgrade_round_trip`)
- File and reproduction: `migrations/versions/20261016_0008_suppliers_purchase_orders.py`. Alembic applies the naming convention when dropping check constraints too, so `drop_constraint("ck_products_pack_size_positive")` looked for `ck_products_ck_products_...`.
- Fix and regression test: use the short names, as in the upgrade; the round-trip test passes.
- Status: VERIFIED

## P4-T3-R3 — [LOW] Purchasing is read-and-receive only
- Source: Claude self-review
- File and reproduction: there is no endpoint to create, cancel or partly receive an order, and a product's supplier, minimum order and pack size cannot be changed through the API.
- Expected behavior: new orders come from approved recommendations (P4-T4, approval in the spec's section 4.F/P7); admins can edit purchasing rules.
- Fix and regression test: P4-T4 (orders from approved recommendations) and a later catalogue update for the purchasing fields.
- Update 2026-10-16 (P4-T4): recommendations exist as pending proposals; turning an approved one into a purchase order or transfer is the approval workflow (spec section 4.G), so this moves to P7.
- Status: OPEN (P7)

## P4-T4-R1 — [MEDIUM] Six planning rules were not covered by any test at first
- Source: mutation check (17 mutations; 6 survived the first test version)
- File and reproduction: `apps/api/app/replenishment_service.py`. Survivors: (1) transfers ignored the free space at the receiving site; (2) status was not used for priority; (3) existing warehouse links could be overwritten; (4) non-SYN products could be linked; (5) superseding hit all rows, not only pending ones; (6) free space ignored open orders. One more survivor was an equivalent mutation: "a short site gives nothing" can never trigger, because a short site's stock on hand is always below its own target.
- Expected behavior: every rule has a test that fails without it; no dead code.
- Fix and regression test: new or stronger tests for each (space-limited transfer, status before days of cover with scarce space, both kinds of link kept, a non-SYN product in a mapped category, a third run, `free_space` with an open order); the redundant branch was removed with a comment explaining why. 16 of 16 caught.
- Status: VERIFIED

## P4-T4-R2 — [LOW] Lead time over 21 days would have shortened the review period
- Source: Claude self-review before testing
- File and reproduction: the first version capped the protection period at the 28 forecast days, which for a lead time of 22–28 days silently shortened the review period, and for more than 28 days made it negative (a crash in the policy math).
- Fix and regression test: such items are unassessed instead (counted in `X-Unassessed-Count`); `test_protection_days_must_fit_in_the_forecast`.
- Status: VERIFIED

## P4-T4-R3 — [LOW] Known simplifications in the recommendations
- Source: Claude self-review
- File and reproduction: transfers are treated as arriving at once (no travel time); there is no ordering or transfer cost, so the plan does not trade a transfer against an order; risks are not stored as alerts (D-047); the seed overstocks most items (542 of 800 pairs are excess with the real forecasts; first written as 242, see P6-T1-R5), which makes transfers dominate.
- Expected behavior: documented, so the demo is read correctly.
- Fix and regression test: none now; revisit with the dashboard (P6) and approvals (P7).
- Status: OPEN (documented limitation)

## P5-T1-R1 — [MEDIUM] Policy search misses questions that use other words
- Source: pre-registered retrieval check (docs/results/p5_policy_retrieval.json)
- File and reproduction: `apps/api/app/policies_service.py::search_policies`. Paraphrased questions found the right section 0 times out of 3, e.g. "Which vendors are unreliable?" returns nothing because the policy says "supplier".
- Expected behavior: the copilot finds the relevant policy however the user phrases the question.
- Fix and regression test: decide in P5-T3 together with the model provider: (a) the copilot turns the question into policy terms before searching, and/or (b) embeddings. Then re-run the same 12 questions plus new unseen ones. Not tuned on the 3 failing questions.
- Update 2026-10-17: option (a) is in the copilot's rules (search in the policy's own words). In the P5-T4 run the paraphrase "Who signs off on buying more stock?" got the right policy citation through the copilot. The search endpoint by itself is unchanged and still misses paraphrases; embeddings are not needed for the copilot now.
- Status: VERIFIED (for the copilot path)

## P5-T1-R2 — [LOW] First policy drafts said slightly more than the system does
- Source: Claude self-review (comparing every policy statement with the code)
- File and reproduction: `apps/api/policies/`. The first drafts said the service level could be set "between 50% and 99.9%" (the API accepts anything from 50% to just under 100%), that stock adjustments "need approval" (managers record them directly) and that a discrepancy needs "a note" (the movement has a reference field).
- Expected behavior: policies the copilot cites must match what the system does.
- Fix and regression test: wording corrected; `test_shipped_policies_are_labelled_and_parse`. A test cannot check meaning; P5-T4 will check the copilot's answers against the records.
- Status: VERIFIED

## P5-T2-R1 — [MEDIUM] Seeded delivery history made every supplier look bad
- Source: Claude self-review (real-data check of `GET /suppliers/risks`)
- File and reproduction: `apps/api/app/seed.py::_order_history`. Delivery times were drawn symmetrically around the promised lead time, so even the "reliable" suppliers were late 16–31% of the time; with the policy's thresholds all six suppliers came out at risk or on watch (SUP05, meant to be reliable, at 72%). The copilot would have had no real signal.
- Expected behavior: reliable simulated suppliers rate good, unreliable ones at risk.
- Fix and regression test: each supplier now has an on-time share (on time = 0–2 days early, late = 1 to N days); `test_history_gives_the_supplier_ratings_a_clear_signal` for seeds 42 and 7 (SUP01 and SUP05 good, SUP04 at risk). Products and stock of old seeds are unchanged; order counts changed (seed 42: 210 orders, 20 open instead of 208/21), and the README numbers were re-measured.
- Status: VERIFIED

## P5-T2-R2 — [LOW] My own test expectations were wrong three times, and two rules were untested
- Source: test failures; mutation check
- File and reproduction: `apps/api/tests/test_copilot_tools.py`. (1) I again forgot that lead-time spread adds safety stock (expected a target of 28; the code's 32 is right, as in P4-T2-R2); (2) I forgot the two open orders already on order (expected 32 to order; 12 is right); (3) my "old" order was received exactly 90 days back, which the window includes. Mutations then showed no test for early deliveries (counted as negative lateness) and that bad policy-section citations failed only because no policies were loaded.
- Fix and regression test: corrected expectations with the arithmetic in comments; an early delivery and loaded policies in the tests. Final: 17 of 17 mutations caught in two repeated runs (one earlier run reported 16 of 17; I did not record which mutation and could not reproduce it).
- Status: VERIFIED

## P5-T3-R1 — [BLOCKER for real use] The real model has not answered yet: the OpenAI account has no credits
- Source: first real run (isolated Docker stack, full demo data, 5 questions + 1 API call)
- File and reproduction: every call returned `429 insufficient_quota` ("You have no credits remaining", code `credit_balance_exhausted`). The key was accepted; 0 tokens were used, so nothing was charged. The copilot stored each run as `failed` with the error, and no key text appeared in logs or stored errors.
- Expected behavior: real answers from `gpt-5.4-mini`, checked for grounding.
- Fix and regression test: the owner adds credits (OpenAI billing settings). Then re-run the same five questions (`copilot_smoke` questions in the work log) and record the results. Until then the real-model behavior is NOT VERIFIED; everything else is tested with a scripted model.
- Update 2026-10-17: the owner switched to Groq and Gemini (free tiers, D-052) instead of buying OpenAI credits. The same five questions will be run with the chosen provider once its key and model are in `.env`.
- Update 2026-10-17: real answers obtained from Groq `qwen/qwen3.8-27b` in the evaluation run (P5-T4).
- Status: VERIFIED

## P5-T3-R2 — [LOW] The first `investigate` command read the run after its session had closed
- Source: test failure (`DetachedInstanceError`)
- File and reproduction: `apps/api/app/cli.py::investigate_command` printed the run after the `with Session(...)` block; after commit the fields must be reloaded from an open session.
- Fix and regression test: print inside the session; `test_investigate_command`.
- Status: VERIFIED

## P5-T3-R3 — [LOW] Three limits were untested, and one could never trigger
- Source: mutation check (11 mutations; 3 survived at first)
- File and reproduction: `apps/api/app/copilot/graph.py`. The tool-call limit was never reached in tests (the model-call limit always came first), the 3-rounds-per-specialist limit was not checked, and the "citation must name a real record" half of verification had no test (tools only return real citations). A separate 4-step limit was redundant: each of the four specialists may run once.
- Fix and regression test: a model asking for 5 tools per reply (tool limit reached exactly), a check of exactly 3 rounds, a tool returning a citation to a missing record, and the redundant limit replaced by "finish once every specialist has reported" (saves a model call; tested). Final: 12 of 12 caught.
- Status: VERIFIED

## P5-T4-R1 — [LOW] The first numbers check would have flagged every correct figure
- Source: Claude self-review before any run
- File and reproduction: `apps/api/app/copilot/evaluation.py`. The first version looked for an answer's numbers in the run's trace, which holds only citations and row counts, not the tools' data. Every correct number (for example 25.77 units) would have been reported as unsupported.
- Fix and regression test: the investigation now returns the tool results it used (`InvestigationResult.evidence`), and the check reads those; `test_numbers_ignore_ids_and_accept_rounded_or_percent_forms`.
- Status: VERIFIED

## P5-T4-R2 — [BLOCKER for P5] The evaluation has not been run against a real model
- Source: owner's instruction: no use of the API keys without permission
- File and reproduction: the evaluation is built and tested offline (scripted models; 13 of 13 mutations caught) and dry-run on the real demo data with a fake model (6 of 14, as expected for a model that declines everything; expected citations computed correctly). No Groq or Gemini call was made.
- Expected behavior: a real run with the owner's permission, reported as it comes out, including failures.
- Fix and regression test: owner gives permission; then `evaluate-copilot --confirm-model-calls` with Groq (`llama-3.1-8b-instant`) and, if wanted, Gemini. This also answers P5-T3-R1 and P5-T1-R1.
- Update 2026-10-17: with the owner's permission, run against Groq `qwen/qwen3.8-27b`: 12/14 cases, gate passed (docs/MODEL_RESULTS.md). The configured Groq model no longer exists (404) and the Gemini project is denied access (403), so neither of those was evaluated.
- Status: VERIFIED

## P5-T4-R3 — [MEDIUM] Groq's free tier refuses the copilot's larger requests
- Source: real evaluation run (docs/results/p5_copilot_eval_groq.json)
- File and reproduction: `apps/api/app/copilot/graph.py`. Two of 14 cases failed with HTTP 413 "Request too large ... input tokens per minute: Limit 7000" because tool results (up to 6,000 characters each) and the answer prompt (up to 18,000 characters) add up. Questions also took 6–139 s, mostly waiting for rate limits.
- Expected behavior: questions fit the free tier, or the run says clearly that the limit was hit.
- Fix and regression test (next task, then a second evaluation run reported next to the first): send the model compact tool results (fewer fields, smaller limits), and on a 413 retry once with half the evidence. A paid Groq tier is the alternative (owner's choice).
- Update 2026-10-17: done (`MAX_RESULT_CHARS` 3,000, `MAX_EVIDENCE_CHARS` 8,000, compact JSON, `RequestTooLargeError` with one half-size retry, a specialist stops with a note). 5 new tests; 5 of 5 mutations caught. Second run: 0 refusals for size (2 before).
- Status: VERIFIED

## P5-T4-R4 — [LOW] The checks do not catch every factual slip
- Source: reading the saved answers
- File and reproduction: in the injection-data case the answer says "Four suppliers are rated good" and lists three. Numbers are checked against the tools, but counts written as words are not.
- Expected behavior: documented; answers are saved for reading.
- Fix and regression test: none now; a stricter check (counts against tool data) could come later.
- Status: OPEN (documented limitation)

## P5-T4-R5 — [LOW] The configured models do not work as set
- Source: real evaluation run
- File and reproduction: the owner's `.env` has `GROQ_MODEL=llama-3.1-8b-instant`, which Groq no longer offers (404), and the Gemini project behind `GEMINI_API_KEY` is denied access by Google (403, also for a single test request).
- Expected behavior: `.env` names a model that exists, with a key that is allowed.
- Fix and regression test: owner's choice: set `GROQ_MODEL=qwen/qwen3.8-27b` (the model that passed), and for Gemini create a key in a new Google AI Studio project. Not changed by Claude (owner's file and choice).
- Status: OPEN (owner action)

## P5-T4-R6 — [MEDIUM] Groq's free tier also limits output tokens per minute
- Source: second real evaluation run
- File and reproduction: the injection-data case failed with HTTP 429 "output tokens per minute (OTPM): Limit 1000", after the OpenAI client's 2 retries.
- Expected behavior: a question waits out short rate limits instead of failing.
- Fix and regression test: more retries for rate limits only (the reply says how long to wait), or a paid tier (owner's choice). Not changed yet.
- Status: OPEN

## P5-T4-R7 — [MEDIUM] The model may put tool error messages in its citation list
- Source: second real evaluation run ("missing" case)
- File and reproduction: `apps/api/app/copilot/graph.py` answer prompt. The model listed "Unknown warehouse 'SYN-WH9'" and "No product matches 'SYN-4242'" as citations. Verification removed them and marked the answer not grounded, so the user never saw them as evidence, but the pre-registered gate counts them.
- Expected behavior: citations are only record ids from the tools.
- Fix and regression test: say in the answer prompt that a citation looks like `supplier:SYN-SUP04` and that messages are not citations, and give the citation list shown to the model separately from the messages; then a third run reported next to the others. The evaluation rule itself stays as it is.
- Status: OPEN

## P6-T1-R1 — [LOW] Logging out with the API down gave an unhandled error
- Source: test run (unhandled promise rejection reported by Vitest)
- File and reproduction: `apps/web/src/auth/AuthContext.tsx`. If the logout request failed (API down), the error went up to the button handler and was never caught.
- Expected behavior: the user is logged out in this browser either way (the token is cleared first), without an error.
- Fix and regression test: the context catches the failure; test "still logs out in this browser, without an unhandled error".
- Status: VERIFIED

## P6-T1-R2 — [LOW] My own test setup ran six tests twice and faked an impossible reply
- Source: test count (20 instead of 14) and the same Vitest report
- File and reproduction: `apps/web/src/pages/OverviewPage.test.tsx` imported example data from another test file, which runs that file's tests again; the fake API built a "204 No Content" reply with a body, which browsers refuse.
- Fix and regression test: shared example data moved to `src/testUtils.tsx`; the fake API sends no body with 204. 14 tests, each run once.
- Status: VERIFIED

## P6-T1-R3 — [MEDIUM] The login token is readable by scripts in the page
- Source: Claude self-review (design)
- File and reproduction: `apps/web/src/api/client.ts` keeps the token in `sessionStorage`. A script injected into the page (XSS) could read it.
- Expected behavior: tokens out of reach of page scripts.
- Fix and regression test: move to an httpOnly, Secure, SameSite cookie set by the API (with CSRF protection) in the security phase (P7/P8). React's escaping and no third-party scripts reduce the risk meanwhile.
- Status: OPEN (P7/P8)

## P6-T1-R4 — [LOW] The first overview showed stock value in pounds
- Source: Claude self-review
- File and reproduction: `apps/web/src/pages/OverviewPage.tsx` formatted the value with a £ sign, but the simulated data has no currency.
- Fix and regression test: plain amount with two decimals; the overview test checks "1,234.50".
- Status: VERIFIED

## P6-T1-R5 — [LOW] The docs gave 242 "excess" items instead of 542
- Source: the owner's screenshot of the new overview (146 + 24 + 88 + 542 = 800 pairs)
- File and reproduction: my P4-T4 and P5-T2 checks counted statuses from `GET /inventory/risks?limit=500`, which returns at most 500 of the 800 rows (most urgent first), so 300 "excess" rows were missed. The README and P4-T4-R3 said 242; the dashboard counts all rows and shows 542. The other three counts were right (they all fall in the first 500).
- Expected behavior: published numbers count every row.
- Fix and regression test: README and P4-T4-R3 corrected; the work log gets a correction entry (it is append-only). `test_kpis_match_the_detailed_services` checks the dashboard's counts against the services.
- Status: VERIFIED

## P6-T1b-R1 — [LOW] No self-service "forgot password" by email
- Source: Claude self-review
- File and reproduction: a user who forgets their password must ask an admin for a temporary one.
- Expected behavior: acceptable for an internal tool; emailed reset links need an email service, short-lived signed tokens and rate limits.
- Fix and regression test: later, if wanted (P9 or after).
- Status: OPEN (documented limitation)
