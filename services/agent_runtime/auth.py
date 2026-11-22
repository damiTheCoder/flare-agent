"""Landing-page auth gate: signed cookie sessions + Google OAuth.

The SPA shell and assets stay public so the landing page can render; every
``/api`` and ``/v1`` route requires a session when auth is enabled. Google
sign-in is configurable with FLARE_GOOGLE_CLIENT_ID/SECRET; for local demos
FLARE_AUTH_ALLOW_LOCAL enables an explicit local sign-in button.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import time
import uuid
from typing import Any
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from flare_common.config import Settings
from flare_common.identity import reset_identity, set_identity
from flare_common.tenant import DEFAULT_TENANT

logger = logging.getLogger(__name__)

COOKIE_NAME = "mb_session"
GOOGLE_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO = "https://www.googleapis.com/oauth2/v3/userinfo"

PUBLIC_PREFIXES = ("/api/auth/", "/auth/", "/assets/", "/fonts/")
PUBLIC_PATHS = {"/", "/index.html", "/api/health", "/metrics", "/logo.png", "/grokbot.jpeg"}
PROTECTED_PREFIXES = ("/api/", "/v1/", "/mcp")


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _b64d(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def sign_session(payload: dict[str, Any], secret: str, ttl_seconds: int) -> str:
    body = {**payload, "exp": int(time.time()) + ttl_seconds}
    data = _b64e(json.dumps(body, separators=(",", ":")).encode())
    signature = hmac.new(secret.encode(), data.encode(), hashlib.sha256).digest()
    return f"{data}.{_b64e(signature)}"


def verify_session(token: str, secret: str) -> dict[str, Any] | None:
    try:
        data, signature = token.split(".", 1)
        expected = hmac.new(secret.encode(), data.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(_b64d(signature), expected):
            return None
        payload = json.loads(_b64d(data))
    except (ValueError, json.JSONDecodeError):
        return None
    if int(payload.get("exp", 0)) < int(time.time()):
        return None
    return payload if isinstance(payload, dict) else None


def read_session(request: Request, secret: str) -> dict[str, Any] | None:
    token = request.cookies.get(COOKIE_NAME)
    return verify_session(token, secret) if token else None


def _is_secure(request: Request) -> bool:
    return request.url.scheme == "https" or (
        request.headers.get("x-forwarded-proto", "").lower() == "https"
    )


def _set_session_cookie(response: Any, token: str, settings: Settings, secure: bool) -> None:
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=settings.session_ttl_hours * 3600,
        httponly=True,
        samesite="lax",
        secure=secure,
        path="/",
    )


def _user_payload(user: dict[str, Any], settings: Settings) -> dict[str, Any]:
    return {
        "sub": str(user.get("sub") or ""),
        "email": str(user.get("email") or ""),
        "name": str(user.get("name") or user.get("email") or "User"),
        "picture": str(user.get("picture") or ""),
        "companyId": str(user.get("companyId") or DEFAULT_TENANT),
    }


def build_auth_router(settings: Settings, *, enabled: bool) -> APIRouter:
    router = APIRouter(tags=["auth"])
    google_configured = bool(settings.google_client_id and settings.google_client_secret)

    @router.get("/api/auth/session")
    async def session(request: Request) -> dict[str, Any]:
        payload = read_session(request, settings.session_secret)
        return {
            "authenticated": payload is not None,
            "user": _user_payload(payload, settings) if payload else None,
            "googleConfigured": google_configured,
            "localAllowed": settings.auth_allow_local,
            "authRequired": enabled,
        }

    @router.get("/auth/google/start")
    async def google_start() -> Any:
        if not google_configured:
            return JSONResponse(
                status_code=503,
                content={
                    "code": "GOOGLE_NOT_CONFIGURED",
                    "message": "Google sign-in is not configured on this deployment.",
                },
            )
        state = sign_session(
            {"purpose": "oauth", "nonce": uuid.uuid4().hex}, settings.session_secret, 600
        )
        query = urlencode(
            {
                "client_id": settings.google_client_id,
                "redirect_uri": f"{settings.app_base_url.rstrip('/')}/auth/google/callback",
                "response_type": "code",
                "scope": "openid email profile",
                "state": state,
                "access_type": "online",
                "prompt": "select_account",
            }
        )
        return RedirectResponse(f"{GOOGLE_AUTH}?{query}", status_code=302)

    @router.get("/auth/google/callback")
    async def google_callback(request: Request, code: str = "", state: str = "") -> Any:
        payload = verify_session(state, settings.session_secret)
        if payload is None or payload.get("purpose") != "oauth":
            return RedirectResponse("/?auth=state", status_code=302)
        if code == "":
            return RedirectResponse("/?auth=denied", status_code=302)
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                token_response = await client.post(
                    GOOGLE_TOKEN,
                    data={
                        "code": code,
                        "client_id": settings.google_client_id,
                        "client_secret": settings.google_client_secret,
                        "redirect_uri": f"{settings.app_base_url.rstrip('/')}/auth/google/callback",
                        "grant_type": "authorization_code",
                    },
                )
                token_response.raise_for_status()
                access_token = token_response.json().get("access_token", "")
                info = await client.get(
                    GOOGLE_USERINFO, headers={"Authorization": f"Bearer {access_token}"}
                )
                info.raise_for_status()
                profile = info.json()
        except httpx.HTTPError as exc:
            logger.warning("google sign-in failed: %s", exc)
            return RedirectResponse("/?auth=failed", status_code=302)

        token = sign_session(
            _user_payload(profile, settings),
            settings.session_secret,
            settings.session_ttl_hours * 3600,
        )
        response = RedirectResponse("/", status_code=302)
        _set_session_cookie(response, token, settings, _is_secure(request))
        return response

    @router.post("/auth/local")
    async def local_login(request: Request) -> Any:
        if not settings.auth_allow_local:
            return JSONResponse(
                status_code=403,
                content={"code": "LOCAL_AUTH_DISABLED", "message": "Local sign-in is disabled."},
            )
        token = sign_session(
            {
                "sub": "local:damian",
                "email": "damian@microbalance.local",
                "name": "Damian",
                "picture": "",
                "companyId": DEFAULT_TENANT,
            },
            settings.session_secret,
            settings.session_ttl_hours * 3600,
        )
        response = JSONResponse({"ok": True})
        _set_session_cookie(response, token, settings, _is_secure(request))
        return response

    @router.post("/api/auth/logout")
    async def logout() -> Any:
        response = JSONResponse({"ok": True})
        response.delete_cookie(COOKIE_NAME, path="/")
        return response

    return router


class AuthGateMiddleware(BaseHTTPMiddleware):
    """Bind the session to the request; require it for API traffic."""

    def __init__(self, app: ASGIApp, *, settings: Settings) -> None:
        super().__init__(app)
        self._settings = settings

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if request.method == "OPTIONS" or path in PUBLIC_PATHS or path.startswith(PUBLIC_PREFIXES):
            return await call_next(request)

        payload = read_session(request, self._settings.session_secret)
        token = set_identity(payload)
        try:
            if payload is None and path.startswith(PROTECTED_PREFIXES):
                return JSONResponse(
                    status_code=401,
                    content={"code": "UNAUTHORIZED", "message": "Sign in to continue."},
                )
            response = await call_next(request)
            if payload is not None:
                response.headers["X-MicroBalance-User"] = payload.get("email", "")
            return response
        finally:
            reset_identity(token)
