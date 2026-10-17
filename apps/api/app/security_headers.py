"""HTTP security headers on every API response (P7-T4).

The API answers with JSON, never with pages, so browsers are told not to guess
content types, not to show answers in frames, not to send the address on to other
sites, and not to keep copies (answers contain business and personal data).
The interactive docs (/docs, /redoc) are real pages that load Swagger UI from a
CDN, so they keep FastAPI's defaults instead of the strict content policy.
"""

from collections.abc import Awaitable, Callable

from fastapi import Request, Response

DOCS_PATHS = ("/docs", "/redoc")
API_CONTENT_POLICY = "default-src 'none'; frame-ancestors 'none'"
ONE_YEAR_SECONDS = 365 * 24 * 60 * 60


def security_headers_middleware(https_only: bool):
    """A middleware that adds the headers. `https_only`: also tell browsers to use HTTPS
    for this host from now on (Strict-Transport-Security); only sent when the API is
    served over HTTPS (the same setting as the Secure login cookie)."""

    async def add_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        headers = response.headers
        headers["X-Content-Type-Options"] = "nosniff"
        headers["X-Frame-Options"] = "DENY"
        headers["Referrer-Policy"] = "no-referrer"
        headers.setdefault("Cache-Control", "no-store")
        if not request.url.path.startswith(DOCS_PATHS):
            headers["Content-Security-Policy"] = API_CONTENT_POLICY
        if https_only:
            headers["Strict-Transport-Security"] = f"max-age={ONE_YEAR_SECONDS}"
        return response

    return add_headers
