"""A small load test (P9-T1): N users read the API at the same time for a fixed time.

Usage: python infrastructure/scripts/load-test.py <api base> <email> <password> <users> <seconds> [out.json]
  <api base> is http://127.0.0.1:8000 locally, or https://<id>.cloudfront.net/api on staging.
Logs in once and shares that session cookie between the simulated users (more logins
would only test the login, which is deliberately slow and rate-limited). Each user
loops over three reads: the health check, the overview numbers and the first page of
stock risks. Prints requests, errors, requests per second and latency percentiles.
Standard library only, so it runs anywhere Python does.
"""

import json
import statistics
import sys
import threading
import time
import urllib.error
import urllib.request

BASE, EMAIL, PASSWORD = sys.argv[1].rstrip("/"), sys.argv[2], sys.argv[3]
USERS, SECONDS = int(sys.argv[4]), int(sys.argv[5])
OUT = sys.argv[6] if len(sys.argv) > 6 else None
ENDPOINTS = ["/health", "/dashboard/kpis", "/inventory/risks?limit=50"]


def login() -> str:
    """The session cookie ("chainpilot_session=...") for the given account."""
    request = urllib.request.Request(
        BASE + "/auth/login",
        data=json.dumps({"email": EMAIL, "password": PASSWORD}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.headers["Set-Cookie"].split(";", 1)[0]


def percentile(values: list[float], share: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(share * len(ordered)))]


cookie = login()
results: dict[str, list[tuple[int, float]]] = {path: [] for path in ENDPOINTS}
lock = threading.Lock()
stop_at = time.monotonic() + SECONDS


def user() -> None:
    while time.monotonic() < stop_at:
        for path in ENDPOINTS:
            request = urllib.request.Request(BASE + path, headers={"Cookie": cookie})
            started = time.monotonic()
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    response.read()
                    status = response.status
            except urllib.error.HTTPError as error:
                status = error.code
            except OSError:  # connection refused, timeout, reset
                status = 0
            with lock:
                results[path].append((status, time.monotonic() - started))


threads = [threading.Thread(target=user) for _ in range(USERS)]
for thread in threads:
    thread.start()
for thread in threads:
    thread.join()

report = {"base": BASE, "users": USERS, "seconds": SECONDS, "endpoints": {}}
print(f"{USERS} users for {SECONDS} s against {BASE}")
for path, rows in results.items():
    times = [seconds for _, seconds in rows]
    errors = sum(1 for status, _ in rows if status != 200)
    server_errors = sum(1 for status, _ in rows if status >= 500 or status == 0)
    summary = {
        "requests": len(rows),
        "errors": errors,
        "server_errors": server_errors,
        "requests_per_second": round(len(rows) / SECONDS, 1),
        "p50_ms": round(statistics.median(times) * 1000),
        "p95_ms": round(percentile(times, 0.95) * 1000),
        "p99_ms": round(percentile(times, 0.99) * 1000),
    }
    report["endpoints"][path] = summary
    print(f"  {path:28} {summary}")
all_rows = [row for rows in results.values() for row in rows]
report["total_requests"] = len(all_rows)
report["server_errors"] = sum(
    1 for status, _ in all_rows if status >= 500 or status == 0
)
report["p95_ms"] = round(percentile([seconds for _, seconds in all_rows], 0.95) * 1000)
print(
    f"  total {report['total_requests']} requests, {report['server_errors']} server errors, "
    f"p95 {report['p95_ms']} ms"
)
if OUT:
    with open(OUT, "w", encoding="utf-8") as file:
        json.dump(report, file, indent=2)
