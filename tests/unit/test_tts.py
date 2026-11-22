"""Voice reply proxy: configuration guards and upstream failures."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_runtime.routes.tts import build_tts_router
from flare_common.config import Settings


def _client(**overrides: Any) -> TestClient:
    settings = Settings(_env_file=None, env="test", **overrides)
    app = FastAPI()
    app.include_router(build_tts_router(settings))
    return TestClient(app)


def test_disabled_returns_503() -> None:
    response = _client(tts_enabled=False).post("/api/tts", json={"text": "hello"})
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "TTS_DISABLED"


def test_blank_text_is_rejected() -> None:
    response = _client().post("/api/tts", json={"text": "   "})
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "TTS_EMPTY"


def test_text_length_is_capped() -> None:
    response = _client().post("/api/tts", json={"text": "x" * 4001})
    assert response.status_code == 422


def test_unreachable_service_returns_503() -> None:
    client = _client(tts_url="http://127.0.0.1:1/v1/audio/speech", tts_timeout=1.0)
    response = client.post("/api/tts", json={"text": "hello"})
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "TTS_UNAVAILABLE"
