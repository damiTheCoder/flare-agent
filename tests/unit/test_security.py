"""Security middleware: rate limits, headers, and request caps."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_runtime.app import create_app
from agent_runtime.security import (
    BasicAuthMiddleware,
    RateLimitMiddleware,
    RequestSizeLimitMiddleware,
    SecurityHeadersMiddleware,
    SlidingWindowLimiter,
)
from flare_common.config import Settings


def _limited_app(
    *, per_minute: int = 2, chat_per_minute: int = 1, trust_proxy: bool = False
) -> FastAPI:
    app = FastAPI()
    app.add_middleware(
        RateLimitMiddleware,
        per_minute=per_minute,
        chat_per_minute=chat_per_minute,
        trust_proxy=trust_proxy,
    )

    @app.get("/api/items")
    def items() -> dict:
        return {"ok": True}

    @app.post("/v1/chat/completions")
    def chat() -> dict:
        return {"ok": True}

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok"}

    return app


def test_general_budget_returns_429_with_retry_after() -> None:
    client = TestClient(_limited_app())
    assert client.get("/api/items").status_code == 200
    assert client.get("/api/items").status_code == 200
    blocked = client.get("/api/items")
    assert blocked.status_code == 429
    assert blocked.json()["code"] == "RATE_LIMITED"
    assert int(blocked.headers["retry-after"]) >= 1
    assert blocked.headers["x-ratelimit-remaining"] == "0"


def test_chat_has_its_own_stricter_bucket() -> None:
    client = TestClient(_limited_app())
    assert client.post("/v1/chat/completions").status_code == 200
    assert client.post("/v1/chat/completions").status_code == 429
    # a blocked model call must not spend the general budget
    assert client.get("/api/items").status_code == 200


def test_health_is_never_limited() -> None:
    client = TestClient(_limited_app(per_minute=1))
    for _ in range(5):
        assert client.get("/api/health").status_code == 200


def test_forwarded_ip_is_only_used_when_trusted() -> None:
    trusted = TestClient(_limited_app(per_minute=1, trust_proxy=True))
    assert trusted.get("/api/items", headers={"x-forwarded-for": "1.1.1.1"}).status_code == 200
    assert trusted.get("/api/items", headers={"x-forwarded-for": "1.1.1.1"}).status_code == 429
    assert trusted.get("/api/items", headers={"x-forwarded-for": "2.2.2.2"}).status_code == 200

    untrusted = TestClient(_limited_app(per_minute=1, trust_proxy=False))
    assert untrusted.get("/api/items", headers={"x-forwarded-for": "1.1.1.1"}).status_code == 200
    # a spoofed header cannot mint a fresh bucket
    assert untrusted.get("/api/items", headers={"x-forwarded-for": "2.2.2.2"}).status_code == 429


def test_security_headers_are_applied_and_server_is_removed() -> None:
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/api/ping")
    def ping() -> dict:
        return {"ok": True}

    response = TestClient(app).get("/api/ping")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["cross-origin-opener-policy"] == "same-origin"
    assert "default-src 'self'" in response.headers["content-security-policy"]
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert "server" not in {header.lower() for header in response.headers}


def test_hsts_only_when_the_request_is_https() -> None:
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/api/ping")
    def ping() -> dict:
        return {"ok": True}

    client = TestClient(app)
    assert "strict-transport-security" not in client.get("/api/ping").headers
    secure = client.get("/api/ping", headers={"x-forwarded-proto": "https"})
    assert secure.headers["strict-transport-security"].startswith("max-age=")


def test_oversized_body_is_rejected_before_the_handler() -> None:
    app = FastAPI()
    app.add_middleware(RequestSizeLimitMiddleware, max_bytes=16)

    @app.post("/api/echo")
    def echo() -> dict:
        return {"ok": True}

    response = TestClient(app).post("/api/echo", content=b"x" * 64)
    assert response.status_code == 413
    assert response.json()["code"] == "PAYLOAD_TOO_LARGE"


def test_sliding_window_reports_remaining() -> None:
    limiter = SlidingWindowLimiter()
    assert limiter.hit("api", "key", 2) == (True, 0.0, 1)
    assert limiter.hit("api", "key", 2) == (True, 0.0, 0)
    allowed, retry_after, remaining = limiter.hit("api", "key", 2)
    assert allowed is False
    assert retry_after > 0
    assert remaining == 0


def test_optional_basic_auth_gate() -> None:
    app = FastAPI()
    app.add_middleware(BasicAuthMiddleware, username="admin", password="secret")

    @app.get("/api/private")
    def private() -> dict:
        return {"ok": True}

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok"}

    client = TestClient(app)
    blocked = client.get("/api/private")
    assert blocked.status_code == 401
    assert blocked.headers["www-authenticate"].startswith("Basic ")
    assert blocked.json()["code"] == "UNAUTHORIZED"
    assert client.get("/api/private", auth=("admin", "secret")).status_code == 200
    assert client.get("/api/private", auth=("admin", "wrong")).status_code == 401
    # probes stay open for orchestrators
    assert client.get("/api/health").status_code == 200


def test_production_enables_limits_and_hides_docs() -> None:
    app = create_app(
        Settings(
            _env_file=None,
            env="production",
            task_store="memory",
            rate_limit_enabled=True,  # the suite disables it globally
        )
    )
    with TestClient(app) as client:
        assert client.get("/docs").status_code == 404
        assert client.get("/openapi.json").status_code == 404
        models = client.get("/v1/models")
        assert models.status_code == 200
        assert models.headers["x-ratelimit-limit"] == "120"
        assert models.headers["x-content-type-options"] == "nosniff"
