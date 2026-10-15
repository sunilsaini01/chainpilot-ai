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
