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

## D-040 — 2026-10-16 — Olist delivery-risk data design (fixed before any modelling)
- Label: delivered on a later calendar day than promised. Prediction at dispatch (spec: "no actual-delivery fields in dispatch-time prediction"), so handover timing is allowed and the customer delivery date, reviews and final status are not.
- Chronological split by purchase date: 2017 train, Jan–Mar 2018 validation, Apr–Aug 2018 test. 2016 (launch, very few orders) and Sep–Oct 2018 (almost nothing delivered) are dropped. Split dates were chosen from data availability (orders and delivery completeness per month), not from late rates.
- Censoring rule: drop orders promised within 30 days of the data end, so late outcomes in the last weeks are not under-counted.
- One row per order: multi-item orders are summarized (counts, totals, heaviest/biggest), with seller, category and payment type taken from the most expensive item / largest payment.
- Distance from zip-prefix centroids, after removing coordinates outside Brazil's bounding box. Unknown zip prefixes give a missing distance (475 orders), not a guess.
- Not used yet: seller history (past late rate per seller). It could help, but it must be computed only from orders delivered before each dispatch, to avoid leakage; a candidate for P3-T2 validation.

## D-041 — 2026-10-16 — Delivery-risk metrics and the first experiment's result
- PR-AUC is the main ranking metric (late orders are rare); Brier, log loss and ECE judge the probabilities; precision/recall/F1 at a threshold describe an alerting policy. Accuracy is not reported (always saying "on time" is ~90% accurate).
- The first pre-registered experiment is reported as run, including its failure: calibrating on one unusual quarter (Jan–Mar 2018) over-predicts later risk. No model is deployed from it. The owner decides whether to run a rolling-window evaluation (P3-T2-R1) before P3-T3.

## D-042 — 2026-10-16 — Delivery risk: rolling monthly evaluation; serve rank first
- Model chosen by a pre-registered rolling monthly simulation (outcomes visible only after delivery): logistic regression with Platt calibration on the last 56 days of known outcomes. It beat LightGBM on 9 development months (mean PR-AUC 0.295 vs 0.260) and improved test calibration a lot (ECE 0.137 -> 0.059).
- Because the monthly late rate swings strongly (1.2%–19%), P3-T3 will present risk mainly as a relative tier/percentile and alert on a fixed share of each day's dispatches; probabilities are shown as approximate.
- Logistic regression is also easier to explain (coefficients per feature) and to store safely as plain numbers instead of a pickle.

## D-043 — 2026-10-16 — Delivery risk is served as daily tiers with reasons, from validated files
- Each order's main signal is its tier among the same day's dispatches (high = top 10% = alert, medium = next 20%, low = rest). The probability is shown but labelled approximate because the monthly late rate swings (D-042).
- Reasons come straight from the logistic regression: coefficient × (value − training average), top 3 positive. This needs no extra explanation library and is exact for this model.
- Scores reach the API like forecasts (D-039): a CSV + manifest written by `ml/`, checked and loaded in one transaction by `import-delivery-risk`. The file holds no outcomes; outcomes are joined only in the separate `tier_check` report.
- `app/files.py::sha256_of` is shared by both imports instead of a copy in each.

## D-044 — 2026-10-16 — P4 split into four tasks; policy math shared from the API package
- P4-T1 policy math (pure functions); P4-T2 replay simulator on real M5 demand, compared with a simple reorder baseline (resolves P2-T4-R1 by measuring the service level); P4-T3 suppliers, purchase orders and lead times in the database and seed (P1-T4-R2); P4-T4 stock-out risks and reorder/transfer recommendations in the API, waiting for approval.
- The math lives in `apps/api/app/inventory_policy.py`, standard library only. The API image contains only `apps/api`, so the API must own it; the ML simulator will import the same file (P4-T2) instead of keeping a second copy that could drift.
- Periodic review with an order-up-to level (weekly review fits the weekly forecasts), cycle service level, lost sales (no backorders), demand and lead time treated as independent and roughly normal. The textbook variance formula is checked by a seeded simulation test; whether it holds for lumpy real demand is the simulator's job, not assumed.
- Open for P4-T3 (owner's choice): how simulated `SYN-` products get demand. Proposal: each `SYN-` product is given the forecast of one M5 series of the same category as a clearly labelled "demand profile", never presented as the same product or company.

## D-045 — 2026-10-16 — Recommendations will use the formula with LightGBM forecasts at a 95% target
- In the replay (P4-T2) this combination reached a 94% cycle service level and 96% fill rate with 17–34% less stock than a simple reorder rule at the same fill rate. The safety-stock formula fed by calibrated forecast intervals handles the forecast's under-forecast bias (P2-T4-R1), so no separate bias correction is added.
- 95% is the default service level; it stays a setting, because the right level depends on the product's margin and the cost of a lost sale.
- The simulator imports the same `app/inventory_policy.py` as the API (`ml/inventory_sim/__init__.py` adds `apps/api` to the path; `ml/pyproject.toml` does the same for tests), so the evaluated math is the deployed math.

## D-046 — 2026-10-16 — Purchasing data model (P4-T3)
- One supplier per product, with the purchasing rules (minimum order, pack size) on the product. Enough for reorder recommendations; a many-suppliers-per-product table can come later if needed.
- A purchase order goes to one supplier for one warehouse and is received in full, once. Partial deliveries and cancellation through the API are not built yet. There is no separate shipments table: an order's promised (`expected_date`) and actual (`received_date`) dates are the delivery record that supplier risk will use.
- Receiving goes through `record_movement`, so the stock ledger and the capacity check apply, and the order row is locked to stop double booking.
- Seeded order history is a set of documents, not stock changes: delivered orders are already part of the opening stock. Only receiving an open order changes stock.
- The seed takes an "as of" date (the command passes today); tests use a fixed date so the plan stays the same.
- Not done in P4-T3, deliberately: linking `SYN-` products to M5 demand profiles. That needs the imported forecasts, so it belongs with the recommendations (P4-T4), still following the D-044 proposal unless the owner decides otherwise.

## D-047 — 2026-10-16 — Stock-out risks and recommendations (P4-T4)
- Demand for the simulated products comes from the D-044 demo link. The owner did not choose otherwise, so it is the default. It is stored on the product (M5 item) and warehouse (M5 store), set by `link-demand-profiles`, never overwritten, and labelled in every response.
- Risks are computed live from current stock, open orders and the newest forecast run; there is no stored `risk_alerts` table yet. A stored history of alerts can come with the dashboard (P6) or the agents (P5) if they need it.
- Recommendations follow the replay-tested order-up-to rule (D-045): any item below its target gets an order, not only items below the reorder point. Transfers come first, because moving spare stock is cheaper and faster than buying. Transfer travel time is not modelled.
- Recommendations are stored as `pending` proposals with their inputs; a new run marks the old pending ones `superseded`. Approval, rejection and execution (creating the purchase order or the transfer movements) belong to the approval workflow (P7), as the spec's section 4.G describes.
- A lead time longer than 21 days (lead + 7-day review > 28 forecast days) makes an item unassessable rather than guessed.

## D-048 — 2026-10-17 — Policy retrieval with PostgreSQL full-text search (P5-T1)
- The copilot's policy grounding uses PostgreSQL full-text search: no embedding model, no external service, no extra database, and results that are easy to explain (which words matched). The corpus is small (26 sections), so no index is needed.
- Any word may match (the stemmed terms are joined with OR), ranked by `ts_rank`. The first plan (`websearch_to_tsquery`, all words required) was changed before any search ran, because most natural questions would have found nothing.
- Known gap, measured: no synonyms (paraphrased questions 0/3). Closing it is a P5-T3 decision, together with the model provider.
- The policies live in `apps/api/policies/` and are copied into the API image, so `load-policies` works the same locally, in Docker and later on AWS. They are labelled as simulated policies written for the demo, and say plainly where a rule is not enforced by the system yet, so the copilot cannot claim more than the system does.
- Loading syncs the folder (add, replace, delete) so the copilot never cites a removed policy.

## D-049 — 2026-10-17 — The AI copilot will use OpenAI (owner's choice) — SUPERSEDED by D-052
- Owner's answer to the P5-T3 question: "open AI". The LangGraph supervisor (P5-T3) will call an OpenAI chat model through the official `openai` Python package, behind one small adapter, so tests can swap in a scripted fake model and CI never calls the paid API.
- The API key goes only in the owner's local `.env` (never in Git, never read or printed by Claude) as `OPENAI_API_KEY`; the model name is a setting (`OPENAI_MODEL`), so the owner picks the model and its price.
- Still to confirm by the owner before any real call: the key exists, and the usage cost is accepted. Until then, everything is built and tested with the fake model only.
- Update 2026-10-17: the owner chose the model `gpt-5.4-mini` and put the key in `.env` themselves (format checked without reading the value: one line, starts with `sk-`, no quotes or spaces).

## D-050 — 2026-10-17 — Copilot tools: in the API package, read-only by the database (P5-T2)
- The tools live in `apps/api/app/copilot/` and call the existing services (risks, recommendations, purchasing, forecasts, policies), so the numbers the copilot reports are the system's tested numbers, not the model's.
- Read-only is enforced by PostgreSQL (`SET TRANSACTION READ ONLY` as the first statement, plus `statement_timeout`), not just by careful code: a tool that tries to write fails, which a test proves.
- Inputs are Pydantic models with `extra="forbid"` and capped limits; problems come back as messages, so the model can correct itself instead of crashing the run.
- `stock_risks` uses the default 95% service level (D-045); changing it is a planner decision through the recommendations API, not something the copilot chooses.
- `demand_forecast` adds up only point forecasts. Summing daily 80% bounds would not give an 80% range for the total, so ranges are given per day.
- `supplier_performance` implements the supplier policy (90%/75% thresholds, 90 days, at least 5 orders) and also serves `GET /suppliers/risks`.

## D-051 — 2026-10-17 — Copilot graph, limits and storage (P5-T3)
- LangGraph `StateGraph` with a supervisor and four specialists, matching the spec (demand, inventory, supplier, decision). Each specialist sees only its own tools; each runs at most once, so a run has at most four specialist steps. This rule replaced a separate step limit that could never trigger.
- OpenAI Chat Completions with function calling for the tools and strict JSON schemas for the supervisor's choice and the final answer, behind `ChatModel` (`app/copilot/model.py`), so tests use a scripted model and never call the paid API. The SDK's own retries (2) and a 60-second timeout apply.
- Grounding is checked by code, not trusted from the model: citations must appear in this run's tool results and name a real record (`resolve_citation`). One retry tells the model exactly which citations were wrong; what remains invented is removed and reported, and the run is marked not grounded.
- The model is told to quote tool numbers and not calculate quantities. Code does not yet check the numbers in the answer text; that is part of the P5-T4 evaluation.
- Every run (including failures) is stored in `agent_runs` with its trace and token counts, and audited. A model error does not crash the request: it is stored as a `failed` run and returned with HTTP 201, because the run itself was created; the client reads `status`.
- Runs execute inside the request (typically several seconds). A background worker can come later (spec `POST /forecasts/jobs`, `GET /jobs/{id}`); the per-user hourly limit caps cost meanwhile.
- `LANGSMITH_TRACING=false` in Compose: LangGraph includes LangSmith, which would otherwise be able to send traces to a third party.

## D-052 — 2026-10-17 — Copilot providers: Groq and Google Gemini instead of OpenAI (owner's choice)
- The OpenAI account had no API credits (P5-T3-R1). The owner's ChatGPT and Claude subscriptions do not include API access. The owner asked to "remove the openai api and keep the groq and gemini", which both have free tiers.
- `LLM_PROVIDER=groq|gemini` with `GROQ_API_KEY`/`GROQ_MODEL` and `GEMINI_API_KEY`/`GEMINI_MODEL`. Only the chosen provider's settings are needed; OpenAI is no longer a provider (an `openai` provider name is refused).
- Both offer an OpenAI-compatible Chat Completions API (Groq: `https://api.groq.com/openai/v1`, Gemini: `https://generativelanguage.googleapis.com/v1beta/openai/`), so one adapter (`CompatibleChatModel`) serves both. The `openai` package stays only as the HTTP client for that protocol; no request goes to OpenAI. This is simpler than two vendor SDKs.
- Some models on these providers support only plain JSON mode. The adapter tries a strict JSON schema first; if the provider rejects it (HTTP 400), it switches that model to JSON mode with the schema in the prompt. The graph still checks every reply.
- Free tiers limit requests per minute and tokens per day. The client's 2 retries cover short rate limits; the per-user hourly limit stays.
- The owner's `.env`: the OpenAI lines were removed at the owner's request without being read. The old key still exists in the OpenAI account; the owner can revoke it there.

## D-053 — 2026-10-17 — How the copilot is evaluated (P5-T4)
- Fourteen cases fixed before any run, with pass thresholds (work log, P5-T4 plan). Expected citations come from the tools when the case runs, so the evaluation follows the data rather than numbers typed by hand.
- Database safety is checked exactly (row counts of every table before and after each safety case). Text checks are keyword rules: they can be wrong both ways, so every answer is saved for a person to read, and the report says so.
- Numbers in an answer are compared with every number the tools returned in that run (also as rounded values and percentages); unmatched ones are reported, not failed, except for the key figure a case requires.
- Real runs call the provider for every case, so `evaluate-copilot` refuses without `--confirm-model-calls`. The owner asked that no key be used without permission. A `--dry-run` with a fake model checks the whole evaluation on real data for free.

## D-054 — 2026-10-17 — Evaluation model for the first real run
- The configured Groq model (`llama-3.1-8b-instant`) no longer exists on Groq, and the Gemini project is denied access. To make the permitted run meaningful, the evaluation used `qwen/qwen3.8-27b` from Groq's current list, passed for that run only; the owner's `.env` was not changed.
- `openai/gpt-oss-*` models on Groq were not used: they are open models run by Groq (no data goes to OpenAI), but the owner asked to drop OpenAI, so a non-OpenAI model was the clearer choice.

## D-055 — 2026-10-17 — Frontend: React + TypeScript + Vite, kept simple (P6)
- React 19 with TypeScript and Vite, React Router for pages, plain CSS, no UI framework or state library: the dashboard is mostly tables and numbers from the API, and fewer dependencies are easier to keep safe (109 packages installed, 0 known vulnerabilities).
- Exact versions in `package.json` plus `package-lock.json`; each version was the newest one at least two weeks old when chosen. CI installs with `npm ci` and runs a type-check (`tsc --noEmit`, strict), the unit tests (Vitest + Testing Library) and a production build. GitHub actions stay pinned to commit SHAs (`actions/setup-node` v6.5.0).
- The browser talks to the API directly; CORS allows only the configured origins and exposes the paging and data-label headers. `GET /dashboard/kpis` reuses the existing services, so the overview always agrees with the detailed screens.
- The login token is kept in `sessionStorage` (tab only). An httpOnly cookie would protect it better against injected scripts; that belongs to the security phase (P6-T1-R3).

## D-056 — 2026-10-17 — Accounts are created by admins; users change their own password
- No public sign-up: accounts are created by an admin (CLI for the first one, then the Users page), each with a role and a temporary password. This is the owner's choice after asking how real users get accounts.
- `POST /auth/password` lets anyone change their own password. It needs the current password, and a wrong one counts as a failed login in the existing throttle (5 per email per 15 minutes), so a stolen session cannot be used to guess faster. Other sessions are signed out; the current one stays.
- `POST /users/{id}/password` lets an admin set a temporary password, for example when someone forgot theirs. All of that user's sessions are signed out. Emailed reset links would need an email service and are left for later.
- Audit events record that a password was changed or reset and how many sessions were signed out, never the password.

## D-057 — 2026-10-17 — The approval queue is built with the approval workflow (P7)
- The spec's dashboard lists an approval queue. Until P7 there is nothing to approve or reject, so a read-only queue would only repeat the Recommendations screen or show buttons that do nothing. It is built in P7 together with approve/reject, so the screen and the rules arrive together.
- The audit log shows the actor's email: the API now returns `actor_email` with each audit event (loaded in one extra query), because the user list that maps ids to people is for admins only, while the audit log is for managers too.

## D-058 — 2026-10-17 — The dashboard in Docker, and how it is tested in a browser (P6-T4)
- The web container serves the built files with nginx (pinned `nginx:1.30.5-alpine`, built with `node:24.21.0-alpine`), running as the unprivileged `nginx` user like the API. Unknown paths return `index.html`, so reloading a page works; `index.html` is never cached, hashed bundle files are cached for a year.
- The browser calls the API directly (CORS), not through an nginx proxy. A proxy would make every login look like it comes from the proxy's address, which would weaken the per-IP login limit unless forwarded addresses were trusted, which is more setup than this step needs. The cost: the API address is built into the files (`WEB_API_URL`), so each environment builds its own image. P8 can revisit this behind the AWS load balancer.
- Browser tests run against the real stack, not a fake API: a throwaway Compose project with its own settings file, demo data, one user per role with random passwords, removed afterwards. They run in CI on every push. Pinned: `@playwright/test` 1.63.0 with `playwright-core` 1.63.0 (pinned directly so the accessibility package does not pull a newer, unvetted copy), `@axe-core/playwright` 4.13.0, `@types/node` 24.19.1.
- Accessibility is checked automatically with axe (WCAG 2.1 A and AA) on every page with real data. Automatic checks catch only part of the problems; a manual screen-reader review is still open (P6-T4-R3).
