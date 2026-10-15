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
- Status: OPEN

## P0-T1-R4 — [LOW] Logs are plain text, not structured
- Source: Claude self-review against spec §4.H ("structured logs")
- File and reproduction: `apps/api/app/main.py` uses `logging.basicConfig` with a text format.
- Expected behavior: JSON or key=value logs suitable for CloudWatch.
- Fix and regression test: deferred. Add before AWS work (P8) or with request logging in P1.
- Status: OPEN
