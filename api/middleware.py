"""HTTP hardening: security headers and origin checks for cookie-authenticated mutations.

Evidence for SOC 2 CC6.6 / CC6.7, HIPAA 164.312(e)(1) and CIS Controls 12/13. The security
workstream extends this module (rate limiting, HSTS tuning, CSP policy modes).
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable
from urllib.parse import urlsplit

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response

SESSION_COOKIE = "vma_session"
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

STRICT_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
    "font-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'; "
    "object-src 'none'; upgrade-insecure-requests"
)
# Swagger UI and ReDoc load their assets from a CDN; they get a relaxed policy on their own paths only.
DOCS_CSP = (
    "default-src 'self'; script-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; "
    "style-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; img-src 'self' data: https://fastapi.tiangolo.com; "
    "font-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; object-src 'none'"
)
DOCS_PATHS = ("/docs", "/redoc", "/openapi.json")


def is_https(request: Request) -> bool:
    return request.url.scheme == "https" or request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower() == "https"


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: Any, hsts: bool = True, csp_mode: str = "default") -> None:
        super().__init__(app)
        self.hsts = hsts
        self.csp_mode = csp_mode

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        response = await call_next(request)
        headers = response.headers
        headers.setdefault("X-Content-Type-Options", "nosniff")
        headers.setdefault("X-Frame-Options", "DENY")
        headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=(), usb=()")
        headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
        headers.setdefault("Cache-Control", "no-store") if request.url.path.startswith("/api") else None
        if self.csp_mode != "off":
            path = request.url.path
            headers.setdefault("Content-Security-Policy", DOCS_CSP if path.startswith(DOCS_PATHS) else STRICT_CSP)
        if self.hsts and is_https(request):
            headers.setdefault("Strict-Transport-Security", "max-age=63072000; includeSubDomains")
        return response


class OriginCheckMiddleware(BaseHTTPMiddleware):
    """Reject state-changing requests that carry the session cookie but come from another origin.

    Bearer-token requests are exempt (no ambient credential, no CSRF). SameSite=Lax on the cookie
    already blocks cross-site POSTs in modern browsers; this check is the defence in depth.
    """

    def __init__(self, app: Any, allowed_origins: list[str] | None = None) -> None:
        super().__init__(app)
        self.allowed_origins = {origin.rstrip("/") for origin in (allowed_origins or [])}

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        if (
            request.method in UNSAFE_METHODS
            and request.url.path.startswith("/api")
            and SESSION_COOKIE in request.cookies
            and not request.headers.get("authorization")
        ):
            origin = request.headers.get("origin") or _origin_of(request.headers.get("referer"))
            if origin is None:
                return PlainTextResponse("missing Origin header on a cookie-authenticated request", status_code=403)
            if origin.rstrip("/") not in self.allowed_origins and _host_of(origin) != request.headers.get("host"):
                return PlainTextResponse("cross-origin request rejected", status_code=403)
        return await call_next(request)


def _origin_of(referer: str | None) -> str | None:
    if not referer:
        return None
    parts = urlsplit(referer)
    if not parts.scheme or not parts.netloc:
        return None
    return f"{parts.scheme}://{parts.netloc}"


def _host_of(origin: str) -> str:
    return urlsplit(origin).netloc
