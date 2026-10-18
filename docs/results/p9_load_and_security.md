# P9-T1 results: load test and security scans (2026-10-18)

Pre-registered in docs/CLAUDE_WORK_LOG.md before running. Raw numbers: `p9_load_*.json` in this folder. Tool: `infrastructure/scripts/load-test.py` (one login, N simulated users looping over `/health`, `/dashboard/kpis` and `/inventory/risks?limit=50`).

## Load test

| Run | Requests | Server errors | Overall p95 | Overview p95 | Stock risks p95 | Target (p95 < 2 s, 0 server errors) |
|---|---|---|---|---|---|---|
| Local Docker, 1 user, 20 s (reference) | 255 | 0 | 0.16 s | 0.18 s | 0.17 s | — |
| Local Docker, 10 users, 60 s | 990 | 0 | 1.07 s | 1.18 s | 0.95 s | **pass** |
| Local Docker, 25 users, 60 s (information) | 1,005 | 0 | 2.80 s | 3.07 s | 2.60 s | — |
| Staging, 1 user, 20 s (reference) | 57 | 0 | 0.68 s | 1.00 s | 0.89 s | — |
| Staging, 10 users, 60 s | 201 | 0 | **6.60 s** | 7.29 s | 5.58 s | **fail** (p95) |

### After the fix (P9-T1-R1: the assessment is cached while its inputs are unchanged)

| Run | Requests | Server errors | Overall p95 | Overview p95 | Stock risks p95 | Target |
|---|---|---|---|---|---|---|
| Local Docker, 10 users, 60 s | 5,118 | 0 | 0.23 s | 0.27 s | 0.19 s | **pass** |
| Local Docker, 25 users, 60 s | 4,968 | 0 | 0.55 s | 0.61 s | 0.49 s | — |
| Staging, 10 users, 60 s | *after the next deploy* | | | | | |

What the first runs showed (before the fix):
- **No errors at any load.** Everything slows down evenly, and nothing fails.
- **Throughput is the limit.** Locally it stays at about 17 requests per second from 10 to 25 users. On staging it is about 3.4 requests per second, and the API task's CPU reached about 100% during the test (CloudWatch). The two data endpoints recalculate the risk assessment for all 800 product-warehouse pairs on every request, with one Uvicorn worker. Staging's task has a quarter of a CPU.
- The fix options are in the review queue (P9-T1-R1).

## Security scans

| Scan | Result | Decision |
|---|---|---|
| `pip-audit` 2.10.1, API locked requirements | No known vulnerabilities | Now runs in CI (API job) |
| `pip-audit`, ML requirements | No known vulnerabilities | — |
| `npm audit --audit-level=high`, dashboard | 0 vulnerabilities | Now runs in CI (web job) |
| ECR scan of the running image `b245fa0` | 3 HIGH (glibc CVE-2026-19499, CVE-2026-5435; zlib CVE-2026-85091), 9 MEDIUM (glibc), 3 LOW, all in Debian packages of the `python:3.11-slim` base image | **No fix published yet**: inside the image, `apt list --upgradable` shows no newer `libc6` or `zlib1g`. Accepted for now. The Dockerfile now runs `apt-get upgrade`, so the next build picks up Debian's fix, and ECR scans every pushed image. |
| `Server` header (P8-T3-R1) | Uvicorn sent `server: uvicorn` | Fixed with `--no-server-header`; checked by the CI Docker smoke test |

Pre-registered pass rule for the scans: no known HIGH or CRITICAL vulnerability **with a fix available**. **Pass.**
