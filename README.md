# ChainPilot AI

A supply-chain control tower for retail operations, built as a portfolio project: demand forecasts, stockout and supplier risk, deterministic reorder recommendations, AI-agent investigations, and human-approved **simulated** actions.

> **Synthetic / public data only.** This project does not have access to any real company's supply chain. All operational data will be clearly labelled as simulated.

The full specification and roadmap are in [CHAINPILOT_CLAUDE_ONLY_WORKFLOW.md](CHAINPILOT_CLAUDE_ONLY_WORKFLOW.md). Current progress is in [docs/PROJECT_STATUS.md](docs/PROJECT_STATUS.md).

## What exists today (Phase 0, task P0-T1)

| Component | What it does |
|---|---|
| `apps/api` | FastAPI backend. `GET /health` (process is alive) and `GET /ready` (PostgreSQL answers `SELECT 1`; returns 503 if not). OpenAPI docs at `/docs`. |
| `docker-compose.yml` | Runs PostgreSQL 16 and the API locally. Ports are published on `127.0.0.1` only. |
| `apps/api/tests` | Unit tests (no database needed) and one PostgreSQL integration test. |

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

## Design choices a student can defend

- **`/health` vs `/ready`:** liveness never touches the database, so a database outage doesn't make the orchestrator restart a healthy API process. Readiness does check the database, so traffic is only sent when the API can actually serve it.
- **Lazy database engine:** the engine is created on first use, so the API starts even if Postgres is still booting.
- **Localhost-only ports and a non-root container:** secure defaults for a laptop on shared Wi-Fi.
- **No Kafka, no Kubernetes:** the workload doesn't need them. AWS deployment will use ECS Fargate (later phase).

See [docs/DECISIONS.md](docs/DECISIONS.md) for the full list.
