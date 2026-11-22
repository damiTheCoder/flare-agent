"""Provider-native API keys configure a real model without FLARE_* renames."""

from __future__ import annotations

from flare_common.config import Settings

_CLEAR = (
    "FLARE_MODEL_PROVIDER",
    "FLARE_MODEL_API_KEY",
    "FLARE_MODEL_BASE_URL",
    "FLARE_MODEL_NAME",
    "DEEPSEEK_API_KEY",
    "DEEPSEEK_BASE_URL",
    "DEEPSEEK_MODEL",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
)


def _clean(monkeypatch) -> None:
    for name in _CLEAR:
        monkeypatch.delenv(name, raising=False)


def test_defaults_to_real_provider_without_keys(monkeypatch) -> None:
    """Production default is a real provider; it only lacks a credential."""
    _clean(monkeypatch)
    settings = Settings()
    assert settings.model_provider == "openai"
    assert settings.model_api_key == ""
    assert settings.model_base_url == "https://api.openai.com/v1"


def test_deepseek_key_switches_to_openai_protocol(monkeypatch) -> None:
    _clean(monkeypatch)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-deepseek")
    settings = Settings()
    assert settings.model_provider == "openai"
    assert settings.model_api_key == "sk-deepseek"
    assert settings.model_base_url == "https://api.deepseek.com/v1"
    assert settings.model_name == "deepseek-chat"


def test_openai_key_uses_openai_endpoint(monkeypatch) -> None:
    _clean(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
    settings = Settings()
    assert settings.model_provider == "openai"
    assert settings.model_api_key == "sk-openai"
    assert settings.model_base_url == "https://api.openai.com/v1"


def test_explicit_flare_key_wins(monkeypatch) -> None:
    _clean(monkeypatch)
    monkeypatch.setenv("FLARE_MODEL_API_KEY", "sk-explicit")
    monkeypatch.setenv("FLARE_MODEL_PROVIDER", "anthropic")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-deepseek")
    settings = Settings()
    assert settings.model_api_key == "sk-explicit"
    assert settings.model_provider == "anthropic"
