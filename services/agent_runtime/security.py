"""Production hardening: security headers, request caps and rate limiting.

Single-origin deployment notes:
- The limiter is in-process. That is the right scope for the shipped image
  (one uvicorn process); a multi-instance deployment should move the same
  policy behind Redis or an ingress limiter.
- Client identity is the socket peer unless FLARE_RATE_LIMIT_TRUST_PROXY is
  on, in which case the first X-Forwarded-For hop is used (only safe behind
  a proxy that overwrites the header).
"""

from __future__ import annotations

import base64
import binascii
import hmac
import math
import threading
import time
from collections import deque

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; "
    "font-src 'self'; "
    "connect-src 'self'; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'none'"
)

# Cheap probes must never consume a client's budget or fail a deploy.
RATE_LIMIT_EXEMPT = frozenset({"/api/health"})
RATE_LIMITED_PREFIXES = ("/api/", "/v1/")


class SlidingWindowLimiter:
    """Per-key sliding window, bounded in memory and thread-safe."""

    def __init__(self, window_seconds: float = 60.0) -> None:
        self._window = window_seconds
        self._hits: dict[tuple[str, str], deque[float]] = {}
        self._lock = threading.Lock()
        self._checks = 0

    def hit(self, bucket: str, key: str, limit: int) -> tuple[bool, float, int]:
        """Return ``(allowed, retry_after_seconds, remaining)``."""
        now = time.monotonic()
        with self._lock:
            self._checks += 1
            if self._checks % 2048 == 0:
                self._purge(now)
            slot = (bucket, key)
            hits = self._hits.get(slot)
            if hits is None:
                hits = deque()
                self._hits[slot] = hits
            cutoff = now - self._window
            while hits and hits[0] <= cutoff:
                hits.popleft()
            if len(hits) >= limit:
                return False, max(hits[0] + self._window - now, 0.0), 0
            hits.append(now)
            return True, 0.0, max(limit - len(hits), 0)

    def _purge(self, now: float) -> None:
        cutoff = now - self._window
        stale = [slot for slot, hits in self._hits.items() if not hits or hits[-1] <= cutoff]
        for slot in stale:
            self._hits.pop(slot, None)


def client_ip(request: Request, trust_proxy: bool) -> str:
    if trust_proxy:
        forwarded = request.headers.get("x-forwarded-for", "")
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    return request.client.host if request.client is not None else "unknown"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Sliding-window limiter for API traffic, stricter for model calls."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        per_minute: int,
        chat_per_minute: int,
        trust_proxy: bool = False,
    ) -> None:
        super().__init__(app)
        self._limiter = SlidingWindowLimiter()
        self._per_minute = max(per_minute, 1)
        self._chat_per_minute = max(chat_per_minute, 1)
        self._trust_proxy = trust_proxy

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if (
            request.method == "OPTIONS"
            or path in RATE_LIMIT_EXEMPT
            or not path.startswith(RATE_LIMITED_PREFIXES)
        ):
            return await call_next(request)

        chat = path == "/v1/chat/completions"
        bucket = "chat" if chat else "api"
        limit = self._chat_per_minute if chat else self._per_minute
        allowed, retry_after, remaining = self._limiter.hit(
            bucket, client_ip(request, self._trust_proxy), limit
        )
        if not allowed:
            seconds = max(1, math.ceil(retry_after))
            return JSONResponse(
                status_code=429,
                content={
                    "code": "RATE_LIMITED",
                    "message": f"Too many requests. Retry in {seconds}s.",
                },
                headers={
                    "Retry-After": str(seconds),
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Remaining": "0",
                },
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response


class BasicAuthMiddleware(BaseHTTPMiddleware):
    """Optional gate for the whole UI/API (HTTP Basic, use behind TLS)."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        username: str,
        password: str,
        realm: str = "MicroBalance",
    ) -> None:
        super().__init__(app)
        self._username = username.encode()
        self._password = password.encode()
        self._realm = realm

    async def dispatch(self, request: Request, call_next):
        if request.method == "OPTIONS" or request.url.path in RATE_LIMIT_EXEMPT:
            return await call_next(request)
        header = request.headers.get("authorization", "")
        if header.lower().startswith("basic "):
            try:
                decoded = base64.b64decode(header[6:], validate=True)
                user, _, password = decoded.partition(b":")
            except (ValueError, binascii.Error):
                user = password = b""
            if hmac.compare_digest(user, self._username) and hmac.compare_digest(
                password, self._password
            ):
                return await call_next(request)
        return JSONResponse(
            status_code=401,
            content={"code": "UNAUTHORIZED", "message": "Authentication required."},
            headers={"WWW-Authenticate": f'Basic realm="{self._realm}"'},
        )


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """Reject oversized bodies before they reach a handler."""

    def __init__(self, app: ASGIApp, *, max_bytes: int) -> None:
        super().__init__(app)
        self._max_bytes = max_bytes

    async def dispatch(self, request: Request, call_next):
        raw = request.headers.get("content-length")
        if raw is not None:
            try:
                length = int(raw)
            except ValueError:
                length = 0
            if length > self._max_bytes:
                return JSONResponse(
                    status_code=413,
                    content={
                        "code": "PAYLOAD_TOO_LARGE",
                        "message": f"Request body exceeds {self._max_bytes} bytes.",
                    },
                )
        return await call_next(request)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Baseline browser hardening for every response."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        headers = response.headers
        headers["X-Content-Type-Options"] = "nosniff"
        headers["X-Frame-Options"] = "DENY"
        headers["Referrer-Policy"] = "no-referrer"
        headers["Cross-Origin-Opener-Policy"] = "same-origin"
        headers["Cross-Origin-Resource-Policy"] = "same-origin"
        headers["Permissions-Policy"] = "camera=(), geolocation=(), microphone=(self)"
        headers["Content-Security-Policy"] = CSP
        secure = request.url.scheme == "https" or (
            request.headers.get("x-forwarded-proto", "").lower() == "https"
        )
        if secure:
            headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        if "server" in headers:
            del headers["server"]
        return response
