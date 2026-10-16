# ChainPilot AI

A supply-chain control tower for retail operations, built as a portfolio project: demand forecasts, stockout and supplier risk, deterministic reorder recommendations, AI-agent investigations, and human-approved **simulated** actions.

> **Synthetic / public data only.** This project does not have access to any real company's supply chain. All operational data will be clearly labelled as simulated.

The full specification and roadmap are in [CHAINPILOT_CLAUDE_ONLY_WORKFLOW.md](CHAINPILOT_CLAUDE_ONLY_WORKFLOW.md). Current progress is in [docs/PROJECT_STATUS.md](docs/PROJECT_STATUS.md).

## What exists today (P0 foundation and P1 core data: inventory model, users and login, data APIs, synthetic seed)

| Component | What it does |
|---|---|
| `apps/api` | FastAPI backend. `GET /health` (process is alive) and `GET /ready` (PostgreSQL answers `SELECT 1`; returns 503 if not). OpenAPI docs at `/docs`. Logs are one JSON object per line. |
| `apps/api/app/models.py` | Tables: `products` (with supplier, minimum order and pack size), `warehouses`, `inventory` (stock per product × warehouse), `inventory_movements` (stock ledger), `suppliers`, `purchase_orders` and `purchase_order_lines`, plus users, audit, forecasts and delivery-risk tables. |
| `apps/api/app/purchasing_service.py` | Units on order (open purchase orders) and receiving an order into stock through the ledger. |
| `apps/api/app/replenishment_service.py` | Stock-out risks and reorder/transfer recommendations for the simulated stock, using the replay-tested policy math and borrowed M5 demand. |
| `apps/api/policies/`, `apps/api/app/policies_service.py` | Six policy documents for the simulated company (written for the demo, labelled as such) and their search, the grounding for the AI copilot (P5). |
| `apps/api/app/inventory_service.py` | `record_movement()`, the only way stock changes. See "How stock changes" below. |
| `apps/api/app/security.py`, `users_service.py`, `dependencies.py` | Password hashing, login tokens, and the `require_role()` check used by protected endpoints. See "Users, login and roles" below. |
| `apps/api/app/cli.py` | Command-line tool to create users (needed for the first admin). |
| `apps/api/migrations` | Alembic database migrations. |
| `apps/api/app/inventory_policy.py` | Inventory policy math (P4): inventory position, safety stock with demand and lead-time variability, reorder point, order-up-to level, and order size with minimum order, pack size and a space/budget cap. Units and assumptions are written at the top of the file. Tested on real demand by `ml/inventory_sim`; not connected to an endpoint yet. |
| `docker-compose.yml` | Runs PostgreSQL 16, a one-shot `migrate` job, then the API. Ports are published on `127.0.0.1` only. |
| `apps/api/tests` | Unit tests (no database needed) and PostgreSQL integration tests (migrations, stock rules, a concurrency race). |
| `ml/demand_forecasting/m5_data.py` | Loads and validates the Kaggle M5 dataset and turns it into one row per product, store and day. The data itself must be downloaded: see [docs/DATASETS.md](docs/DATASETS.md). |
| `ml/demand_forecasting/{lgbm_model,conformal,model_selection,train_final}.py` | LightGBM demand model (one model per forecast week), chosen on a validation period, with calibrated 80% intervals; it beats the 28-day moving average on the test windows (WAPE 0.740 vs 0.753 at 28 days). `train_final` saves the models per store in `ml/artifacts/` (not in Git). See [docs/MODEL_RESULTS.md](docs/MODEL_RESULTS.md). |
| `ml/demand_forecasting/{baselines,backtest,metrics,features}.py` | Baseline forecasts (seasonal naive, 28-day moving average), rolling-origin backtests with MAE/WAPE/bias/RMSSE for 7/14/28 days, and leakage-safe features. Results: [docs/MODEL_RESULTS.md](docs/MODEL_RESULTS.md). |
| `ml/delivery_risk/olist_data.py` | Prepares the Olist marketplace data for delivery-delay risk: one row per delivered order, a `late` label, and features known at dispatch time (no delivery dates, no reviews), with a time-based split. See [docs/DATASETS.md](docs/DATASETS.md). |
| `ml/delivery_risk/{models,evaluation,rolling,scoring,tier_check}.py` | Delivery-delay risk: logistic regression retrained every month with calibration on recent outcomes (chosen in a rolling monthly evaluation), scoring of dispatched orders into daily high/medium/low tiers with the top 3 reasons, and an after-the-fact check of the tiers. See [docs/MODEL_RESULTS.md](docs/MODEL_RESULTS.md). |
| `ml/inventory_sim/` | Replay simulator (P4): real M5 sales are replayed day by day through the inventory policy (weekly review, random 5–9 day lead times, lost sales) and compared with a simple reorder rule. With LightGBM forecasts the policy needed 17–34% less stock for the same fill rate. See [docs/MODEL_RESULTS.md](docs/MODEL_RESULTS.md). |
| `.github/workflows/ci.yml` | On every push and pull request: API and ML Ruff lint/format and tests (API tests against a real Postgres 16, ML tests on tiny M5-format fixtures), then builds the Docker stack, checks `/health`, `/ready` and that migrations ran. |

Not built yet: forecast and scoring jobs from the API (needs the background worker), approving and executing recommendations (P7), the AI copilot itself (P5-T2 onwards), frontend, AWS.

## How stock changes

Stock is never overwritten. Every change goes through `record_movement(session, product_id, warehouse_id, quantity_change, reason, reference)`:

1. It locks the product's inventory row (`SELECT ... FOR UPDATE`), so two simultaneous sales cannot both take the last unit.
2. It computes the new balance and raises `InsufficientStockError` if it would be negative.
3. It updates `inventory.on_hand` **and** appends an `inventory_movements` row (quantity, reason, resulting balance, optional reference such as a PO number) in the same transaction.

So the sum of a product's movements always equals its `on_hand`, and every stock level can be explained. The database also enforces non-negative stock with a CHECK constraint, as a second safety net. Reasons are `receipt`, `sale`, `transfer_in`, `transfer_out` and `adjustment`. `movement_history()` returns a product's recent movements at a warehouse, newest first. `updated_at` columns are kept current by a database trigger, so they are right even for raw SQL updates.

## Synthetic demo data

> **SYNTHETIC DATA.** The seed invents a small retail operation. It is not any real company's data. Every SKU starts with `SYN-`, every warehouse code with `SYN-WH`, every supplier code with `SYN-SUP` and every purchase order with `SYN-PO-`.

```bash
docker compose up -d
docker compose run --rm api python -m app.cli seed                     # 4 warehouses, 200 products, seed 42
docker compose run --rm api python -m app.cli seed --products 500 --warehouses 5 --seed 7
```

- **Deterministic:** the same `--seed` always produces exactly the same warehouses, products, prices and stock. Order dates are counted back from the day you run it (the same seed on the same day gives the same orders).
- Sizes follow the spec: 100–500 products, 3–5 warehouses.
- Opening stock is recorded as `receipt` movements (reference `SEED-OPENING`, no user), so the ledger adds up and capacity rules apply. Each warehouse is filled to at most 70% of capacity. About 80% of product/warehouse pairs are stocked, and about 10% of those start low (1–20 units), so there is something for stock-out detection to find.
- It refuses to run when `SYN-` products already exist; it never deletes or overwrites data. It creates no user accounts (use `create-user`).
- **Suppliers and purchase orders:** 6 simulated suppliers with promised lead times (4–21 days) and their variation; two are deliberately unreliable. Each product gets a supplier for its category, a pack size and a minimum order (whole packs). About 120 days of order history per supplier and warehouse: delivered orders are history (their goods are part of the opening stock, so they make no stock movements); orders not yet delivered are open, and some are overdue. With seed 42: 208 orders, 21 open.

## Products, warehouses and stock (API)

| Endpoint | Who |
|---|---|
| `GET /products?search=&category=&is_active=&limit=&offset=`, `GET /products/{id}` | analyst+ |
| `POST /products`, `PATCH /products/{id}` (no delete: set `is_active=false`) | admin |
| `GET /warehouses`, `GET /warehouses/{id}` | analyst+ |
| `POST /warehouses`, `PATCH /warehouses/{id}` | admin |
| `GET /inventory?warehouse_id=&product_id=&max_on_hand=` (stock levels; `max_on_hand` finds low stock) | analyst+ |
| `GET /inventory/movements?product_id=&warehouse_id=` (history, newest first) | analyst+ |
| `POST /inventory/movements` `{product_id, warehouse_id, quantity_change, reason, reference}` | manager+ |

- SKUs and warehouse codes are trimmed and stored upper-case (`sku-1` becomes `SKU-1`), and cannot be changed after creation.
- Prices are exact decimals with 2 places, sent as strings in JSON (`"4.99"`).
- Recording a movement returns **201**; overselling returns **409** with the stock on hand; an unknown product or warehouse returns **404**.
- **Safe retries:** send an `Idempotency-Key: <unique string>` header with `POST /inventory/movements`. If the same user repeats the same request with the same key (for example after a timeout), the API returns the original movement with **200** and does not change stock again. The same key with a different body, or from another user, returns **409**. Two simultaneous retries are handled by a unique constraint.
- Every create, update and stock movement writes an audit event with the acting user.
- **Warehouse capacity:** a receipt or incoming transfer that would take a warehouse above `capacity_units` (all products together) returns **409**. Positive adjustments are allowed, because a stock count records what is physically there. Capacity cannot be lowered below the units currently stored (409). The warehouse row is locked during the check, so two simultaneous receipts cannot overfill it together.
- **Paging:** every list endpoint takes `limit` (max 200) and `offset` and returns the total number of matching rows in the `X-Total-Count` response header.

## Demand forecasts (M5 public data)

> **Data label:** these forecasts are for the public **M5 (Walmart)** dataset, keyed by M5 series ids such as `FOODS_3_090_CA_1_validation`. They are kept separate from the simulated `SYN-` products and are never joined to them. Every forecast response carries an `X-Dataset` header saying so.

How forecasts get from the model to the API:

```powershell
cd ml
python -m demand_forecasting.publish ..\data\raw\m5 --all-stores          # -> data/processed/forecasts/<run>/ (not in Git)
cd ..\apps\api
# Import into the database (POSTGRES_* pointing at your database, e.g. the Compose one on 127.0.0.1)
python -m app.cli import-forecasts ..\..\data\processed\forecasts\m5_lightgbm_weekly_2016-04-24
```

The import checks the file against its manifest (checksum, row count, column names, `0 <= lower <= forecast <= upper`, step/date consistency) before writing, loads all 853,720 rows in one transaction with PostgreSQL `COPY` (about 45 s), writes an audit event, and refuses to import the same file twice.

| Endpoint | Who |
|---|---|
| `GET /forecasts/runs` (newest first) | analyst+ |
| `GET /forecasts?run_id=&store_id=&item_id=&series_id=&date_from=&date_to=&limit=&offset=` (default: newest run; point forecast plus 80% interval `lower`/`upper`) | analyst+ |

## Delivery-delay risk (Olist public data)

> **Data label:** these scores are for historical orders in the public **Olist** Brazilian marketplace dataset (April–August 2018). They are not ChainPilot's simulated suppliers or purchase orders and are never joined to them. Every response carries an `X-Dataset` header saying so.

How scores get from the model to the API:

```powershell
cd ml
python -m delivery_risk.scoring ..\data\raw\olist          # -> data/processed/delivery_risk/<run>/ (not in Git)
cd ..\apps\api
python -m app.cli import-delivery-risk ..\..\data\processed\delivery_risk\olist_logistic_2018-04-02_2018-08-31
```

Each dispatched order is scored by the model of its month, which only learned from outcomes known before that month started. It gets:

| Field | Meaning |
|---|---|
| `tier` / `alert` | **The main signal.** Among the orders dispatched the same day: `high` = riskiest 10% (these are the alerts), `medium` = next 20%, `low` = the rest. |
| `day_percentile` | Its rank among the same day's dispatches (1.0 = riskiest). |
| `probability` | Approximate chance of arriving late. It drifts with the monthly late rate (1%–19% in this data), so compare orders by tier, not by this number. |
| `reasons` | The 3 features that raised its risk the most compared with a typical order (logistic-regression contribution in log-odds), e.g. a long handling time or a long distance. |

Measured afterwards on these months: high-tier orders were late 19.9% of the time, medium 6.8%, low 2.0% (all orders 4.8%); the daily alerts caught 42.5% of the late orders. See [docs/MODEL_RESULTS.md](docs/MODEL_RESULTS.md).

The import checks the file against its manifest (checksum, row count, column names, probability and percentile ranges, `alert` exactly for the high tier, consistent dates inside the period) before writing, loads all rows in one transaction with PostgreSQL `COPY`, writes an audit event, and refuses to import the same file twice.

| Endpoint | Who |
|---|---|
| `GET /delivery-risk/runs` (newest first) | analyst+ |
| `GET /delivery-risk/scores?run_id=&dispatch_date=&tier=&alert=&order_id=&limit=&offset=` (default: newest run; newest day first, riskiest first) | analyst+ |
| `GET /delivery-risk/alerts?date=2018-05-15` (that day's alerts, riskiest first) | analyst+ |

## Suppliers and purchase orders (API)

| Endpoint | Who |
|---|---|
| `GET /suppliers` | analyst+ |
| `GET /purchase-orders?status=&warehouse_id=&supplier_id=&product_id=&limit=&offset=` (newest first, with lines) | analyst+ |
| `GET /purchase-orders/{id}` | analyst+ |
| `POST /purchase-orders/{id}/receive`: books every line into stock (`receipt` movements, reference = PO number) | manager+ |

Receiving is all or nothing: if the warehouse has no room for the whole delivery, nothing is booked (409) and the order stays open. An order can be received only once; two managers receiving at the same moment book it once (the order row is locked). Open orders count as "on order" in the inventory position (`purchasing_service.on_order_quantities`). New orders will come from approved recommendations (P4-T4).

## Stock-out risks and recommendations (API)

> **Data label:** stock, suppliers and orders are **simulated** (`SYN-`). Their demand is **borrowed** from the forecast of a linked M5 item and store: a demo link, not the same product or company. Every response carries an `X-Dataset` header saying so.

```powershell
# After seed and import-forecasts:
python -m app.cli link-demand-profiles      # gives SYN- products an M5 item and SYN- warehouses an M5 store
```

The link is deterministic (a product's M5 item is picked by a hash of its SKU from the mapped category: kitchen, home and garden use HOUSEHOLD items; office, toys and sports use HOBBIES; pets and health use FOODS). Existing links are never changed.

For each product at each warehouse, the forecast for the next (lead time + 7) days gives the daily demand and its uncertainty. Stock on hand plus open orders is compared with the reorder point and the order-up-to level from `app/inventory_policy.py`, at a 95% service level by default. That is the setting the replay simulator tested (docs/MODEL_RESULTS.md).

| Status | Meaning |
|---|---|
| `out_of_stock` | nothing on hand, demand expected |
| `at_risk` | on hand + on order is below the reorder point: it may run out before a new order arrives |
| `excess` | more than 60 days of demand above the target level |
| `ok` | everything else |

Recommendations are **proposals** (`pending`). Nothing is ordered or moved until they are approved and executed (P7).
- **Transfers come first:** stock another site holds above its own target.
- **Supplier orders follow** for what is still missing, in whole packs and at least the supplier's minimum order.
- **Space:** each warehouse's free space (capacity minus stock minus open orders) is shared, most urgent first.
- **Replacement:** a new run replaces the pending set.
- **Explainable:** each recommendation stores the numbers it was based on.

| Endpoint | Who |
|---|---|
| `GET /inventory/risks?warehouse_id=&status=&service_level=&limit=&offset=` (most urgent first; `X-Unassessed-Count` = pairs without demand data) | analyst+ |
| `POST /inventory/recommendations` `{"service_level": 0.95}` | manager+ |
| `GET /inventory/recommendations?status=pending&kind=&warehouse_id=` | analyst+ |

With seed 42 and the real forecasts, 800 pairs are assessed: 146 out of stock, 23 at risk, 89 ok and 242 excess (the seed overstocks). The recommendations are 148 transfers (4,607 units) and 23 supplier orders (1,293 units).

## Policy documents (grounding for the AI copilot)

> **SIMULATED COMPANY POLICIES**, written for this demo, not any real company's. They describe the rules the system follows (service level, transfers first, supplier rules, approvals, receiving, data labels and the copilot's limits), and say where a rule is not enforced by the system yet.

```powershell
python -m app.cli load-policies        # syncs apps/api/policies/*.md into document_chunks (also inside the Docker image)
```

Each `## ` section becomes one searchable chunk with a citation such as `policy:replenishment#order-quantities`. Loading only changes what changed: new and edited files are (re)loaded, removed files are deleted, and every load is audited.

Search uses PostgreSQL full-text search with English stemming. Any word of the question may match, and sections matching more of the words rank higher. It does not know synonyms. In the pre-registered check, direct questions found the right section first 9 times out of 9, and paraphrased ones ("vendors" for suppliers) 0 times out of 3. See [docs/MODEL_RESULTS.md](docs/MODEL_RESULTS.md).

| Endpoint | Who |
|---|---|
| `GET /policies` (documents, chunk counts, checksums) | analyst+ |
| `GET /policies/search?q=&limit=` (best sections first, with citation and highlighted snippet) | analyst+ |

## Users, login and roles

| Role | Can |
|---|---|
| `analyst` | read data |
| `manager` | everything an analyst can, plus approve actions (later phases) |
| `admin` | everything a manager can, plus manage users |

| Endpoint | Who |
|---|---|
| `POST /auth/login` `{email, password}` returns `{access_token, expires_at, user}` | anyone |
| `GET /auth/me` | any logged-in user |
| `POST /auth/logout` (revokes the token) | any logged-in user |
| `GET /users?limit=&offset=`, `POST /users`, `PATCH /users/{id}` (role, name, active) | admin |
| `GET /audit-events?entity_type=&entity_id=&limit=&offset=` | manager, admin |

Send the token as `Authorization: Bearer <token>`. A missing, unknown, expired or revoked token gives **401**; a role that is too low gives **403**. Tokens last `ACCESS_TOKEN_TTL_MINUTES` (default 480 = 8 hours).

**Create the first admin** (prompts twice for the password; nothing is echoed or saved in shell history):

```bash
docker compose up -d
docker compose run --rm api python -m app.cli create-user --email you@example.com --full-name "Your Name" --role admin
```

How it is kept safe:
- Passwords are hashed with **scrypt** (Python standard library, OWASP-recommended settings, random salt per user) and must be 12–128 characters.
- Tokens are 256-bit random values. The database stores only their SHA-256 hash, so a leaked database does not leak usable tokens. Logout revokes a token immediately.
- Failed logins return the same message whether the email exists or not, and take about the same time either way.
- Emails are stored lower-case, so `Ana@X.com` and `ana@x.com` are the same account.
- Logs record user ids, never passwords, tokens or the emails used in failed attempts.
- **Rate limiting:** after 5 failed logins for one email (or 20 from one IP) within 15 minutes, login returns **429** with `Retry-After: 900`, even for the right password. The check runs before the slow password hash. A successful login resets that email's count, and blocks expire on their own.
- **Last admin protection:** the last active admin cannot be demoted or deactivated (409). The check locks the admin rows, so two admins demoting each other at the same moment cannot leave zero admins.
- Deactivating a user (`PATCH /users/{id}` with `{"is_active": false}`) blocks their login and stops their existing tokens immediately.

**Audit trail:** logins, logouts, user creation and user changes are written to `audit_events` (actor, action, entity, details such as `{"changes": {"role": ["analyst", "manager"]}}`) in the same transaction as the change itself. Stock movements record the acting user in `inventory_movements.created_by_user_id`.

**Client IP behind a proxy:** rate limiting uses the client's IP. Uvicorn takes the IP from `X-Forwarded-For` only when the request comes from an address in `FORWARDED_ALLOW_IPS` (default `127.0.0.1,::1`), so clients cannot fake their IP. Behind the AWS load balancer (P8), set it to the load balancer's subnet.

**Housekeeping:** `docker compose run --rm api python -m app.cli cleanup --days 30` deletes tokens that expired or were revoked more than 30 days ago, and login attempts older than 30 days. Safe to run daily. What is kept and for how long: [docs/DATA_RETENTION.md](docs/DATA_RETENTION.md).

## Run locally with Docker

Requirements: Docker Desktop with Compose v2.

```bash
cp .env.example .env          # then edit POSTGRES_PASSWORD
docker compose up --build -d
curl http://127.0.0.1:8000/health   # {"status":"ok"}
curl http://127.0.0.1:8000/ready    # {"status":"ready","database":"ok"}
docker compose down                 # add -v to also delete the database volume
```

If port 5432 or 8000 is already used on your machine, change `POSTGRES_HOST_PORT` / `API_HOST_PORT` in `.env` (and `POSTGRES_PORT` to match if you run the API outside Docker).

**Database migrations** run automatically: `docker compose up` starts the `migrate` job (`alembic upgrade head`) and the API waits for it to finish. Useful commands:

```bash
docker compose run --rm migrate alembic current            # which revision the database is at
docker compose run --rm migrate alembic downgrade -1       # undo the latest migration
```

To create a new migration after changing `app/models.py`, run `alembic revision --autogenerate -m "describe change"` inside `apps/api` with the `POSTGRES_*` variables set, then **read and edit** the generated file before committing. The test `test_models_and_migrations_are_in_sync` fails if models and migrations disagree.

**Changing the password later:** Postgres sets the password only when it first creates its data volume. If you change `POSTGRES_PASSWORD` afterwards, `/ready` will return 503 until you recreate the volume with `docker compose down -v` (this deletes the local database).

## Run the API and tests without Docker

Requirements: Python 3.11.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate   macOS/Linux: source .venv/bin/activate
pip install -r apps/api/requirements-dev.txt

cd apps/api
pytest                      # unit tests; database tests are skipped
ruff check . && ruff format --check .

# Run the API against the Compose Postgres (start it with: docker compose up -d migrate)
uvicorn app.main:app --reload --env-file ../../.env

# Database tests (need Postgres running and the POSTGRES_* variables set)
RUN_DB_TESTS=1 pytest
```

Database tests never touch your development data. Each run creates a throwaway database named `<POSTGRES_DB>_pytest_<random>`, applies the migrations, and drops it at the end. The `POSTGRES_USER` therefore needs permission to create databases (the Compose user has it).

## Configuration

All settings come from environment variables (see [.env.example](.env.example)). The database password is a separate variable, and the API builds the connection URL with SQLAlchemy's `URL.create()`, so passwords containing `@ : / # ?` work. Avoid `$` in passwords because Docker Compose treats it as variable interpolation.

- `POSTGRES_HOST` defaults to `127.0.0.1`, not `localhost`. On Windows, `localhost` tries IPv6 first, which stalls because Docker publishes the port on IPv4 only.
- `LOG_FORMAT=json` (default) prints one JSON object per line, which log tools like CloudWatch can search by field. Use `LOG_FORMAT=text` for easier reading while developing.

## Continuous integration

GitHub Actions runs [.github/workflows/ci.yml](.github/workflows/ci.yml) on every push to `main` and every pull request. It has three jobs:
1. **API lint and tests:** Python 3.11, Ruff, and pytest including the PostgreSQL integration tests (Postgres runs as a service container).
2. **ML lint and tests:** Ruff and pytest for `ml/`, using tiny synthetic files in the M5 format (the real dataset is never in CI).
3. **Docker build and smoke test:** builds the stack with Compose, waits for the healthchecks, then curls `/health` and `/ready` and checks that migrations ran.

The workflow has read-only permissions and uses no secrets; its database passwords are throwaway CI values.

## Design choices a student can defend

- **`/health` vs `/ready`:** liveness never touches the database, so a database outage doesn't make the orchestrator restart a healthy API process. Readiness does check the database, so traffic is only sent when the API can actually serve it.
- **Lazy database engine:** the engine is created on first use, so the API starts even if Postgres is still booting.
- **Localhost-only ports and a non-root container:** secure defaults for a laptop on shared Wi-Fi.
- **No Kafka, no Kubernetes:** the workload doesn't need them. AWS deployment will use ECS Fargate (later phase).

See [docs/DECISIONS.md](docs/DECISIONS.md) for the full list.
