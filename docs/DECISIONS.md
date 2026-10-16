# Decisions

Short records of meaningful choices. Append new decisions; mark superseded ones instead of deleting them.

## D-001 — 2026-10-15 — Restart from zero under the Claude-only workflow
- Context: On 2026-10-15 (≈02:19 UTC) the owner asked for all previous code, docs and the local `.git` folder to be deleted so the project could restart. Only the spec files were kept. The owner then installed `CHAINPILOT_CLAUDE_ONLY_WORKFLOW.md`. The legacy files it mentions (`CHAINPILOT_MASTER_WORKFLOW.md`, `AGENTS.md`, `docs/CODEX_WORK_LOG.md`, old status/logs) no longer exist on disk, so there is no prior history in this repository to preserve.
- Decision: Begin again at P0-T1 and keep the old task IDs (P0-T1 = API + PostgreSQL foundation, P0-T2 = GitHub Actions CI). Claude Code is the only developer. Review is Claude self-review plus user milestone checks, not independent review.
- Lessons carried over from the deleted attempt's review findings: build the DB URL with `URL.create()` from separate fields, and publish ports on `127.0.0.1` by default. Both are now built in and tested.

## D-002 — 2026-10-15 — Python 3.11 with exact pinned versions and pip
- Python 3.11 satisfies the spec's "3.11+" requirement, is installed locally and matches the `python:3.11-slim` image. Direct dependencies are pinned exactly in `apps/api/requirements*.txt`. `uv` is not installed, so plain pip keeps the setup simple. A full transitive lock file can be added later if needed.

## D-003 — 2026-10-15 — API tests live inside `apps/api/tests`
- The spec's example layout shows a top-level `tests/`. Keeping the API tests next to the API package means `pytest` runs from `apps/api` without path tricks and CI can test the API on its own. Cross-component tests can go in a top-level `tests/` later.

## D-004 — 2026-10-15 — Separate liveness and readiness endpoints
- `/health` never touches the database. `/ready` runs `SELECT 1` and returns 503 when it fails. The response hides driver error details, and the log records only the exception type, so hostnames and usernames don't leak.

## D-005 — 2026-10-15 — No migrations tool in P0
- Alembic is planned for P1, when the first tables appear (roadmap: "P1 Core data: migrations…"). P0 has no schema, so adding it now would only be scaffolding.

## D-006 — 2026-10-15 — JSON logs with the standard library
- A ~20-line `logging.Formatter` subclass produces one JSON object per line. No new dependency (for example `structlog` or `python-json-logger`) is needed for four fields. Uvicorn's loggers are routed through the same handler so access logs match. `LOG_FORMAT=text` remains for local readability.

## D-007 — 2026-10-15 — CI design
- One workflow, two jobs: (1) lint + tests with a Postgres 16 service container, so the integration test always runs in CI; (2) Docker build + Compose smoke test with `--wait`, which tests the real image and healthchecks rather than only the Python code.
- `permissions: contents: read`, no secrets, throwaway CI passwords. `concurrency` cancels outdated runs. Actions are pinned by major tag for readability; pin to SHAs before AWS credentials are added (P0-T2-R3).
- pytest treats unexpected warnings as errors (`filterwarnings = error`) so deprecations surface early instead of piling up.

## D-008 — 2026-10-15 — Default database host is 127.0.0.1, not localhost
- On Windows `localhost` resolves to IPv6 first, and Docker publishes Postgres on IPv4 only. That cost ~130 s per connection without a timeout (P0-T2-R1). `127.0.0.1` also matches the Compose bind address.

## D-009 — 2026-10-15 — LF line endings via .gitattributes
- Files end up in Linux containers. `* text=auto eol=lf` stops Windows `core.autocrlf=true` checkouts from turning them into CRLF, which would break future shell scripts.

## D-010 — 2026-10-15 — Use the current major versions of GitHub actions
- `actions/checkout@v7` and `actions/setup-python@v7` run on Node 24. The older v4/v5 run on Node 20, which GitHub is retiring (P0-T2-R6). Still pinned by major tag; SHA pinning is tracked in P0-T2-R3.

## D-011 — 2026-10-15 — P1 split into four tasks
- P1-T1: Alembic + core inventory tables + stock-movement service. P1-T2: users, password hashing, tokens, roles. P1-T3: product/warehouse/inventory APIs with RBAC and audit events. P1-T4: deterministic synthetic seed data. Each task is small enough to review and test on its own.

## D-012 — 2026-10-15 — Stock is a ledger, not an editable number
- `inventory.on_hand` changes only via `record_movement()`, which locks the row (`SELECT … FOR UPDATE`), rejects negative balances, updates `on_hand` and appends an `inventory_movements` row in one transaction. This satisfies spec §6 ("never silently overwrite stock; reconcile through movement records") and keeps an audit trail. A database CHECK (`on_hand >= 0`) is a second safety net.
- Row locking was chosen over optimistic version columns because it is easier to explain and test, and stock contention per product/warehouse is low.
- Movement reasons are text plus a CHECK constraint, not a PostgreSQL ENUM type, because adding a value to a PG enum needs special migration handling.
- Suppliers, purchase orders and shipments are not in P1-T1. They arrive with the phases that use them (P3/P4), so no unused tables are created early.

## D-013 — 2026-10-15 — Migrations live in `apps/api/migrations`
- The spec's example layout shows `database/migrations/`. Keeping them next to the API code means the same Docker image contains the models and the migrations that must match them, and a test (`test_models_and_migrations_are_in_sync`) can compare the two. Migrations are hand-written and readable, with explicit constraint names from a naming convention.
- Compose runs them with a one-shot `migrate` service (`alembic upgrade head`); the API starts only after it exits successfully. That is simpler and safer than migrating inside API startup, which would race when several API containers start at once.

## D-014 — 2026-10-15 — Throwaway database per test run
- Integration tests create `<POSTGRES_DB>_pytest_<random>`, migrate it, empty tables after each test (`TRUNCATE … RESTART IDENTITY`) and drop it at the end with `DROP DATABASE … WITH (FORCE)`. Developers can run tests against their Compose Postgres without losing data. Real commits (not rolled-back transactions) are used so the concurrency test can exercise real row locks across two connections.

## D-015 — 2026-10-15 — `updated_at` maintained by a database trigger
- A small PL/pgSQL trigger function (`set_updated_at`, migration 0002) stamps `updated_at = now()` on every row update of products, warehouses and inventory, so raw SQL and future bulk loads cannot leave it stale. The models declare `server_onupdate=FetchedValue()` so SQLAlchemy reloads the value. The ledger table (`inventory_movements`) has no `updated_at`, because its rows are never updated.

## D-016 — 2026-10-15 — GitHub Actions pinned to commit SHAs
- Done before P8 instead of during it: it costs one comment per line, and a SHA cannot be moved by the action's owner the way a tag can. The version stays readable as a trailing comment (`# v7.0.1`). Upgrades mean looking up the new tag's SHA with `git ls-remote`.

## D-017 — 2026-10-15 — `httpx2` for the test client
- Starlette 1.8 deprecates `httpx` for `TestClient` in favour of `httpx2` (same author, official pydantic/httpx2 repository). Approved by the owner on 2026-10-15. It is a test-only dependency (`requirements-dev.txt`) and is not in the Docker image.

## D-018 — 2026-10-15 — Passwords hashed with the standard library's scrypt
- `hashlib.scrypt` is memory-hard and on OWASP's recommended list. Parameters N=2^14, r=8, p=5 match one of OWASP's equivalent settings (about 16 MiB per hash) and are stored in each hash string (`scrypt$N$r$p$salt$hash`), so they can be raised later. No extra dependency (argon2/bcrypt packages) is needed. Verification uses `hmac.compare_digest`. A dummy hash is checked when the email is unknown, so timing does not reveal which emails exist.
- Password policy: 12–128 characters (length over complexity rules, as in NIST SP 800-63B; the upper bound limits hashing cost).

## D-019 — 2026-10-15 — Opaque database tokens instead of JWTs
- Login returns a random 256-bit token. The database stores its SHA-256 hash with an expiry and a `revoked_at`. Compared with JWTs: logout and deactivation take effect immediately, there is no signing key to manage or leak, and no token library is needed. The cost is one indexed lookup per request, which is fine at this scale.
- Token lifetime defaults to 8 hours (`ACCESS_TOKEN_TTL_MINUTES`, 5 min to 7 days). There are no refresh tokens yet; the user logs in again.

## D-020 — 2026-10-15 — Roles are a simple hierarchy, checked server-side
- `analyst < manager < admin`; `require_role(minimum)` is a FastAPI dependency. A hierarchy is easy to explain and matches the spec (analyst read, manager approve, admin manage). If separation of duties is needed later (for example, an admin who may not approve), it can switch to explicit permission sets.
- 401 is returned for missing, invalid, expired or revoked tokens, always with the same message; 403 for a role that is too low.
- The first admin is created with `python -m app.cli create-user`. The password comes from a hidden prompt or `CHAINPILOT_NEW_USER_PASSWORD`, never a command-line argument (shell history). No default admin account exists.

## D-021 — 2026-10-15 — Simple email validation, no extra package
- A small regex (one `@`, a dot in the domain) plus lower-casing, instead of adding `email-validator`. Emails are used as login names in an internal tool, not to send mail, so strict validation adds little.

## D-022 — 2026-10-15 — Login rate limiting stored in PostgreSQL
- Failed attempts are rows in `login_attempts`; limits are counted with indexed queries over a 15-minute window. No Redis is needed (spec: Redis optional and must be justified), the data survives restarts and is shared by all API containers. Limits: 5 per email (reset by a successful login), 20 per IP. Blocks expire by themselves, so a deliberate lockout of someone else's account lasts at most 15 minutes. The check happens before scrypt, so blocked floods cost little CPU.

## D-023 — 2026-10-15 — Audit events in the same transaction as the change
- `record_event()` only adds a row to the session; the route commits it together with the change, so there is never a change without its audit record (or the reverse). Details are JSONB with old/new values and never secrets. Actor FKs use ON DELETE RESTRICT: users with history are deactivated, not deleted. Readable by managers and admins (the dashboard's audit timeline).

## D-024 — 2026-10-15 — Review-queue items moved forward from P1-T3/P7 at the owner's request
- The owner asked for the review queue to be cleared before committing P1-T2. Audit events, the actor on stock movements, user deactivation/role changes, login rate limiting and token cleanup were built now. P1-T3 keeps the product/warehouse/inventory APIs (which will use `record_event` and `actor_user_id`).

## D-025 — 2026-10-15 — Who may change what (P1-T3)
- Read (products, warehouses, stock, history): analyst and up. Master data (products, warehouses): admin. Stock movements: manager and up, because they change operational state; approvals and simulated purchase orders come in P7.
- Products and warehouses are never deleted (stock history and audit events refer to them). Products are deactivated with `is_active=false`. SKU and warehouse code are immutable identifiers.
- Manual transfers between warehouses are not a separate endpoint yet: a transfer is two movements (`transfer_out`, `transfer_in`). An atomic transfer action belongs with the approval workflow (P4/P7).

## D-026 — 2026-10-15 — Idempotency keys for stock movements
- Optional `Idempotency-Key` header, stored in a unique column on `inventory_movements`. A replay by the same user with the same body returns the original movement (200); a different body or another user gives 409. A race between two identical requests is settled by the unique constraint inside a savepoint. Keys are kept forever with the movement (cheap, and useful for tracing); a TTL is not needed at this scale.

## D-027 — 2026-10-15 — Cheaper password hashing for test fixture users only
- The `make_user` fixture uses scrypt N=2^10, p=1 (stored in each hash, so verification works unchanged). This cut the suite from about 92 s to about 23–50 s. Production parameters stay as they are and are still covered by `tests/test_security.py`, users created through `POST /users`, and the end-to-end checks.

## D-028 — 2026-10-15 — Warehouse capacity enforced on goods-in movements
- Receipts and incoming transfers may not take a warehouse above `capacity_units` (sum over all products). Positive adjustments are exempt, because they record a physical count. The warehouse row is locked (`SELECT … FOR UPDATE`) during the check. Lock order is always warehouse then inventory row; sales lock only the inventory row, so no cycle is possible. Capacity cannot be lowered below current stock. Smarter capacity use (recommendations that leave room, transfers to emptier sites) stays in P4.

## D-029 — 2026-10-15 — Total counts in an `X-Total-Count` header
- A header keeps the response bodies plain JSON arrays (no breaking change for existing clients and tests). One extra `COUNT(*)` per list request is cheap at this scale. The frontend will need CORS `expose_headers=["X-Total-Count"]` (P6).

## D-030 — 2026-10-15 — Real client IP only from trusted proxies
- Uvicorn's `ProxyHeadersMiddleware` (on by default) is configured through `FORWARDED_ALLOW_IPS`, passed by Compose with the safe default `127.0.0.1,::1`. Trusting `X-Forwarded-For` from everyone would let attackers dodge the per-IP login limit by inventing IPs.

## D-031 — 2026-10-15 — Seed as a pure plan plus a loader
- `build_plan(seed, n_products, n_warehouses)` uses its own `random.Random(seed)` and returns frozen dataclasses, so determinism is checked without a database. `load_plan` writes through the normal services: opening stock is `record_movement(..., reason=receipt, reference="SEED-OPENING", actor=None)`, so capacity rules and the ledger apply exactly as for real users. Loading is refused if `SYN-` products exist (no destructive reset command; to start over locally, use `docker compose down -v`).
- Synthetic labelling is part of the identifiers (`SYN-`, `SYN-WH`), and the load writes a `seed.loaded` audit event with the seed and sizes. The dashboard's "simulated data" badge comes in P6.
- No demo user accounts are seeded: default credentials in a repository are a common security mistake. Users are created with `create-user`.

## D-032 — 2026-10-15 — P2 split into four tasks
- P2-T1: M5 download guide, loader, validation, long format, fixtures, CI job (no real data needed). P2-T2: features, seasonal-naive baseline, rolling-origin backtests and metrics. P2-T3: LightGBM model, uncertainty, saved artifacts. P2-T4: forecast tables and API. P2-T2 onwards needs the real data, so it is blocked until the owner downloads M5.

## D-033 — 2026-10-15 — ML code in its own `ml/` package
- `ml/demand_forecasting` has its own `requirements.txt` (pandas 3.0.6, numpy 2.4.6: numpy 2.5 has no Python 3.11 wheels), tests and CI job. The API image stays free of pandas until the inference API (P2-T4) needs model outputs. Same Python 3.11 and the same strict "warnings are errors" test policy as the API.

## D-034 — 2026-10-15 — Synthetic M5-format fixtures, generated by a script
- The real M5 data may not be redistributed and is ~300 MB, so tests use `ml/tests/fixtures/m5_tiny/` (6 series x 21 days, invented values in the real column format, including an item not yet on sale and a SuperBowl event). A seeded generator script makes the fixtures reproducible (verified byte-identical on regeneration). The loader's validator is tested by breaking copies of these tables in 11 different ways.
- The command-line summary is skipped above 5,000 series (the full data becomes ~58M rows); users pass `--store`.

## D-035 — 2026-10-15 — Compact types for the M5 long table
- Categories for the 9 repeated text columns and small number types (sales int16, week int32, weekday/SNAP int8, price float32) cut one store from 3.5 GB to 179 MB and make all 10 stores (58.3M rows) fit in 1.8 GB. float32 prices keep about 7 significant digits, which is far more than cents need. Modelling will still work per store or per store group by default, to keep peaks low on a 16 GB laptop.

## D-036 — 2026-10-15 — Baselines, backtest design and metrics
- Baselines: seasonal naive (spec requirement) plus a 28-day moving average, because seasonal naive is a weak bar for noisy item-level data; the stronger baseline is the one models must beat.
- Rolling origin: 3 origins, 28 days apart, ending on the last day (2016-04-24), non-overlapping test windows; 7/14/28-day horizons are the first 7/14/28 days of each window. The forecaster receives only history up to the origin (tested with a spy and a "cheating" forecaster), and RMSSE scales use only history up to each origin.
- Metrics: MAE, WAPE, bias (sum-based, signed), RMSSE (M5-style scale from first sale; unweighted mean). No MAPE: undefined on the many zero-sales days.
- Features for the tree model use only sales at least 28 days old (`min_lag=28`), so one model can forecast all 28 days directly without feeding back its own predictions. Verified by a perturbation test (changing all newer sales leaves the features unchanged).
- Each run writes a JSON report with origins, windows, runtime, package versions, `git describe --dirty`, and SHA-256 of the data files.

## D-037 — 2026-10-15 — LightGBM model design (first version)
- One model per store (memory and time: ~45 s per store-origin for three boosters), Tweedie objective for zero-heavy counts, product/department/category as categorical features, 730 training days, fixed settings (no tuning on test data), deterministic seeds. Intervals from separate 10%/90% quantile models, ordered after prediction. Days without a price are excluded from training and forecast as 0.
- Models are saved in LightGBM's text format (not pickle, so loading cannot run code) with a metadata JSON (features, window, settings, data checksums, code version) in `ml/artifacts/` (ignored by Git).
- The first backtest did not beat the 28-day moving average (P2-T3-R1). Decision: report it as is and let the owner choose whether to invest in a validated second version.

## D-038 — 2026-10-16 — Production forecast model: weekly LightGBM with conformal intervals
- Chosen by the pre-registered rule on a validation period, then confirmed once on the untouched test windows (`docs/MODEL_RESULTS.md`). Four models per store (days 1–7, 8–14, 15–21, 22–28) with minimum feature lags 7/14/21/28, so each forecast uses the freshest sales it is allowed to without leakage.
- Intervals from split-conformal calibration (validation errors, 10 bins by forecast size) instead of quantile boosters: calibrated by construction, cheaper (no extra models), and model-agnostic (the moving average gets intervals the same way). Bounds are stored in each model's metadata.
- The 28-day moving average remains the documented fallback and benchmark.

## D-039 — 2026-10-16 — Forecasts reach the API as validated files, not by running models in the API
- The ML package writes `forecasts.csv` + `manifest.json`; the API imports them with a CLI command. The API image needs no pandas or LightGBM, the import is all-or-nothing (one transaction, PostgreSQL `COPY`), and each file can be imported once (`run_key` from its checksum). `POST /forecasts/jobs` (spec section 5) needs the background worker, so it is deferred to the phase that adds workers.
- Forecast rows are keyed by M5 series ids and labelled with their dataset, and never joined to `SYN-` products (spec section 3). Connecting model outputs to the simulated demo scenario is a P4 decision.
- `sales_train_evaluation.csv` is used exactly once, as a final untouched check of the published forecasts.
