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
- Status: OPEN (mitigated; full fix awaits owner approval of the new dependency)

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
- Status: OPEN

## P0-T2-R4 — [MEDIUM] CI workflow not yet run on GitHub
- Source: Claude self-review
- File and reproduction: `.github/workflows/ci.yml` can only run on GitHub after it is pushed. Locally I reproduced both jobs' steps (same commands, same Postgres image and passwords), but GitHub's runner itself is NOT VERIFIED.
- Expected behavior: both jobs green on GitHub.
- Fix and regression test: owner pushes (or authorizes Claude to commit and push), then confirm in the Actions tab with `gh run list` / `gh run view`.
- Status: OPEN

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
- Status: FIXED (VERIFIED after the first green GitHub run)
