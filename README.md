# ChainPilot AI

A supply-chain control tower for retail operations, built as a portfolio project: demand forecasts, stockout and supplier risk, deterministic reorder recommendations, AI-agent investigations, and human-approved **simulated** actions.

> **Synthetic / public data only.** This project does not have access to any real company's supply chain. All operational data will be clearly labelled as simulated.

The full specification and roadmap are in [CHAINPILOT_CLAUDE_ONLY_WORKFLOW.md](CHAINPILOT_CLAUDE_ONLY_WORKFLOW.md). Current progress is in [docs/PROJECT_STATUS.md](docs/PROJECT_STATUS.md).

## What exists today (P0 foundation and P1 core data: inventory model, users and login, data APIs, synthetic seed)

| Component | What it does |
|---|---|
| `apps/api` | FastAPI backend. `GET /health` (process is alive) and `GET /ready` (PostgreSQL answers `SELECT 1`; returns 503 if not). OpenAPI docs at `/docs`. Logs are one JSON object per line. |
| `apps/api/app/models.py` | Tables: `products`, `warehouses`, `inventory` (stock per product × warehouse) and `inventory_movements` (stock ledger). |
| `apps/api/app/inventory_service.py` | `record_movement()`, the only way stock changes. See "How stock changes" below. |
| `apps/api/app/security.py`, `users_service.py`, `dependencies.py` | Password hashing, login tokens, and the `require_role()` check used by protected endpoints. See "Users, login and roles" below. |
| `apps/api/app/cli.py` | Command-line tool to create users (needed for the first admin). |
| `apps/api/migrations` | Alembic database migrations. |
| `docker-compose.yml` | Runs PostgreSQL 16, a one-shot `migrate` job, then the API. Ports are published on `127.0.0.1` only. |
| `apps/api/tests` | Unit tests (no database needed) and PostgreSQL integration tests (migrations, stock rules, a concurrency race). |
| `.github/workflows/ci.yml` | On every push and pull request: Ruff lint/format, pytest against a real Postgres 16, then builds the Docker stack, checks `/health`, `/ready` and that migrations ran. |

Not built yet: ML (demand forecasting, delivery risk), inventory decisions, agents, frontend, AWS.

## How stock changes

Stock is never overwritten. Every change goes through `record_movement(session, product_id, warehouse_id, quantity_change, reason, reference)`:

1. It locks the product's inventory row (`SELECT ... FOR UPDATE`), so two simultaneous sales cannot both take the last unit.
2. It computes the new balance and raises `InsufficientStockError` if it would be negative.
3. It updates `inventory.on_hand` **and** appends an `inventory_movements` row (quantity, reason, resulting balance, optional reference such as a PO number) in the same transaction.

So the sum of a product's movements always equals its `on_hand`, and every stock level can be explained. The database also enforces non-negative stock with a CHECK constraint, as a second safety net. Reasons are `receipt`, `sale`, `transfer_in`, `transfer_out` and `adjustment`. `movement_history()` returns a product's recent movements at a warehouse, newest first. `updated_at` columns are kept current by a database trigger, so they are right even for raw SQL updates.

## Synthetic demo data

> **SYNTHETIC DATA.** The seed invents a small retail operation. It is not any real company's data. Every SKU starts with `SYN-` and every warehouse code with `SYN-WH`.

```bash
docker compose up -d
docker compose run --rm api python -m app.cli seed                     # 4 warehouses, 200 products, seed 42
docker compose run --rm api python -m app.cli seed --products 500 --warehouses 5 --seed 7
```

- **Deterministic:** the same `--seed` always produces exactly the same warehouses, products, prices and stock.
- Sizes follow the spec: 100–500 products, 3–5 warehouses.
- Opening stock is recorded as `receipt` movements (reference `SEED-OPENING`, no user), so the ledger adds up and capacity rules apply. Each warehouse is filled to at most 70% of capacity. About 80% of product/warehouse pairs are stocked, and about 10% of those start low (1–20 units), so there is something for stock-out detection to find.
- It refuses to run when `SYN-` products already exist; it never deletes or overwrites data. It creates no user accounts (use `create-user`).
- Suppliers, purchase orders, lead times and shipments are added with the phases that use them (P3/P4).

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

GitHub Actions runs [.github/workflows/ci.yml](.github/workflows/ci.yml) on every push to `main` and every pull request. It has two jobs:
1. **API lint and tests:** Python 3.11, Ruff, and pytest including the PostgreSQL integration test (Postgres runs as a service container).
2. **Docker build and smoke test:** builds the stack with Compose, waits for the healthchecks, then curls `/health` and `/ready`.

The workflow has read-only permissions and uses no secrets; its database passwords are throwaway CI values.

## Design choices a student can defend

- **`/health` vs `/ready`:** liveness never touches the database, so a database outage doesn't make the orchestrator restart a healthy API process. Readiness does check the database, so traffic is only sent when the API can actually serve it.
- **Lazy database engine:** the engine is created on first use, so the API starts even if Postgres is still booting.
- **Localhost-only ports and a non-root container:** secure defaults for a laptop on shared Wi-Fi.
- **No Kafka, no Kubernetes:** the workload doesn't need them. AWS deployment will use ECS Fargate (later phase).

See [docs/DECISIONS.md](docs/DECISIONS.md) for the full list.
