"""Smoke tests against the live staging URL (P8-T3). Prints PASS or FAIL for each check.

Usage: python infrastructure/scripts/smoke-test.py https://<id>.cloudfront.net <email> <password>
Logs in once (and out again) with the given account. Read-only apart from that session.
"""

import http.cookiejar
import json
import sys
import urllib.error
import urllib.request

SITE = sys.argv[1].rstrip("/")
EMAIL, PASSWORD = sys.argv[2], sys.argv[3]

jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
results = []


def call(path, method="GET", body=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        SITE + path, data=data, method=method, headers=headers or {}
    )
    if data:
        request.add_header("Content-Type", "application/json")
    try:
        response = opener.open(request, timeout=60)
        return (
            response.status,
            response.headers,
            response.read().decode(),
        )  # case-insensitive
    except urllib.error.HTTPError as error:
        return error.code, error.headers, error.read().decode()


def check(name, ok, detail=""):
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + name + (f"  ({detail})" if detail else ""))


status, headers, body = call("/")
check("dashboard page loads", status == 200 and '<div id="root">' in body, status)
csp = headers.get("Content-Security-Policy", "")
check(
    "dashboard has the content policy",
    "script-src 'self'" in csp and "connect-src 'self'" in csp,
)
check(
    "dashboard has HSTS",
    "max-age=31536000" in headers.get("Strict-Transport-Security", ""),
)
check("dashboard: no framing", headers.get("X-Frame-Options") == "DENY")

status, _, body = call("/suppliers")
check("deep link returns the app", status == 200 and '<div id="root">' in body, status)

status, headers, body = call("/api/health")
check(
    "API /health through CloudFront and the VPC origin",
    status == 200 and '"ok"' in body,
    f"{status} {body[:40]}",
)
check(
    "API security headers",
    headers.get("Content-Security-Policy")
    == "default-src 'none'; frame-ancestors 'none'",
)
check("API Cache-Control no-store", headers.get("Cache-Control") == "no-store")

status, _, body = call("/api/ready")
check(
    "API /ready: database reachable",
    status == 200 and "ok" in body,
    f"{status} {body[:60]}",
)

status, headers, body = call("/api/no-such-endpoint")
check(
    "API 404 stays JSON (not the dashboard)", status == 404 and "detail" in body, status
)

status, _, _ = call("/api/dashboard/kpis")
check("data needs a login", status == 401, status)

# A made-up email: a wrong password for the real account would use up its 5 attempts
# per 15 minutes and lock its owner out (it did, 2026-10-18).
status, headers, body = call(
    "/api/auth/login",
    "POST",
    {"email": "nobody@example.com", "password": "wrong-password-123"},
)
check("wrong password refused", status == 401, status)

status, headers, body = call(
    "/api/auth/login", "POST", {"email": EMAIL, "password": PASSWORD}
)
cookie = headers.get("Set-Cookie", "")
check("login works", status == 200, status)
check(
    "session cookie is HttpOnly, Secure, SameSite=Strict",
    "HttpOnly" in cookie and "Secure" in cookie and "SameSite=strict" in cookie,
)
csrf = json.loads(body)["csrf_token"] if status == 200 else ""

status, _, body = call("/api/dashboard/kpis")
check("cookie session reads data", status == 200 and "SIMULATED" in body, status)
kpis = json.loads(body) if status == 200 else {}
check(
    "seeded demo data is there",
    kpis.get("inventory", {}).get("products") == 200,
    kpis.get("inventory"),
)

status, _, body = call("/api/auth/logout", "POST", {})
check("change without CSRF token refused", status == 403, status)
status, _, _ = call("/api/auth/logout", "POST", {}, {"X-CSRF-Token": csrf})
check("logout with CSRF token", status == 204, status)
status, _, _ = call("/api/auth/me")
check("after logout the session is gone", status == 401, status)

print(f"\n{sum(results)} of {len(results)} checks passed")
sys.exit(0 if all(results) else 1)
