"""Auth gate, signed sessions, and identity-aware tooling."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from agent_runtime.app import create_app
from agent_runtime.auth import COOKIE_NAME, sign_session, verify_session
from agent_runtime.graph import _build_tool_schema
from flare_common.config import Settings
from flare_common.identity import reset_identity, set_identity
from tools_gateway.builtin import create_default_registry


def _settings(tmp_path: Path, **overrides) -> Settings:
    values = {
        "_env_file": None,
        "env": "test",
        "task_store": "memory",
        "model_config_path": str(tmp_path / "model_config.json"),
        "workspace_dir": str(tmp_path),
        "auth_required": True,
        "session_secret": "test-secret",
        "auth_allow_local": True,
        "tts_enabled": False,
    }
    values.update(overrides)
    return Settings(**values)


def test_session_token_roundtrip_and_tamper() -> None:
    token = sign_session({"email": "a@b.c"}, "secret", 60)
    assert verify_session(token, "secret")["email"] == "a@b.c"
    assert verify_session(token, "other-secret") is None
    assert verify_session(token[:-2] + "AA", "secret") is None


def test_expired_session_is_rejected() -> None:
    assert verify_session(sign_session({"email": "a"}, "secret", -1), "secret") is None


def test_gate_requires_a_session_then_accepts_local_login(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path))
    with TestClient(app) as client:
        session = client.get("/api/auth/session").json()
        assert session["authenticated"] is False
        assert session["authRequired"] is True

        assert client.post("/api/tts", json={"text": "hi"}).status_code == 401
        assert client.get("/version").status_code == 200  # SPA bootstrap stays public

        logged_in = client.post("/auth/local")
        assert logged_in.status_code == 200
        session = client.get("/api/auth/session").json()
        assert session["authenticated"] is True
        assert session["user"]["name"] == "Damian"
        assert session["user"]["companyId"] == "acme"

        assert client.post("/api/tts", json={"text": "hi"}).status_code == 503  # allowed, disabled
        assert client.post("/api/auth/logout").status_code == 200
        assert client.post("/api/tts", json={"text": "hi"}).status_code == 401


def test_local_login_can_be_disabled(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path, auth_allow_local=False))
    with TestClient(app) as client:
        assert client.post("/auth/local").status_code == 403


def test_google_start_without_credentials(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path))
    with TestClient(app) as client:
        response = client.get("/auth/google/start", follow_redirects=False)
        assert response.status_code == 503
        assert response.json()["code"] == "GOOGLE_NOT_CONFIGURED"


def test_google_start_redirects_when_configured(tmp_path: Path) -> None:
    app = create_app(
        _settings(
            tmp_path,
            google_client_id="client-123.apps.googleusercontent.com",
            google_client_secret="GOCSPX-test",
            app_base_url="http://localhost:8000",
        )
    )
    with TestClient(app) as client:
        response = client.get("/auth/google/start", follow_redirects=False)
        assert response.status_code == 302
        location = response.headers["location"]
        assert location.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
        assert "client_id=client-123.apps.googleusercontent.com" in location
        assert "redirect_uri=http%3A%2F%2Flocalhost%3A8000%2Fauth%2Fgoogle%2Fcallback" in location


def test_prompt_states_the_signed_in_identity(tmp_path: Path) -> None:
    registry = create_default_registry(workspace=str(tmp_path))
    token = set_identity({"name": "Damian", "email": "damian@example.com", "companyId": "acme"})
    try:
        prompt = _build_tool_schema(registry)
    finally:
        reset_identity(token)
    assert "You are logged in as Damian for company acme. You have full access." in prompt
    assert "bash" in prompt and "read" in prompt


async def test_default_registry_runs_bash(tmp_path: Path) -> None:
    registry = create_default_registry(workspace=str(tmp_path))
    result = await registry.execute("bash", {"command": "printf 'harness-ok'"})
    assert result.ok is True
    assert "harness-ok" in result.content
