# ChainPilot AI

A supply-chain control tower for retail operations, built as a portfolio project: demand forecasts, stockout and supplier risk, deterministic reorder recommendations, AI-agent investigations, and human-approved **simulated** actions.

> **Synthetic / public data only.** This project does not have access to any real company's supply chain. All operational data will be clearly labelled as simulated.

The full specification and roadmap are in [CHAINPILOT_CLAUDE_ONLY_WORKFLOW.md](CHAINPILOT_CLAUDE_ONLY_WORKFLOW.md). Current progress is in [docs/PROJECT_STATUS.md](docs/PROJECT_STATUS.md).

## What exists today (Phase 0: foundation and CI)

| Component | What it does |
|---|---|
| `apps/api` | FastAPI backend. `GET /health` (process is alive) and `GET /ready` (PostgreSQL answers `SELECT 1`; returns 503 if not). OpenAPI docs at `/docs`. Logs are one JSON object per line. |
| `docker-compose.yml` | Runs PostgreSQL 16 and the API locally. Ports are published on `127.0.0.1` only. |
| `apps/api/tests` | Unit tests (no database needed) and one PostgreSQL integration test. |
| `.github/workflows/ci.yml` | On every push and pull request: Ruff lint/format, pytest against a real Postgres 16, then builds the Docker stack and checks `/health` and `/ready`. |

Nothing else (ML, agents, frontend, AWS) is built yet.

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

**Changing the password later:** Postgres sets the password only when it first creates its data volume. If you change `POSTGRES_PASSWORD` afterwards, `/ready` will return 503 until you recreate the volume with `docker compose down -v` (this deletes the local database).

## Run the API and tests without Docker

Requirements: Python 3.11.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate   macOS/Linux: source .venv/bin/activate
pip install -r apps/api/requirements-dev.txt

cd apps/api
pytest                      # unit tests; the database test is skipped
ruff check . && ruff format --check .

# Run the API against the Compose Postgres (start it with: docker compose up -d postgres)
uvicorn app.main:app --reload --env-file ../../.env

# Database integration test (needs Postgres running and the POSTGRES_* variables set)
RUN_DB_TESTS=1 pytest tests/test_database_integration.py
```

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
