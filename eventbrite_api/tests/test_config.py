from __future__ import annotations

from pathlib import Path

import pytest

from app import config
from app.schemas import build_minor_authorization_form_url


def test_get_settings_prefers_api_local_env_file(monkeypatch):
    local_env = config.API_ROOT / ".env.local"
    original = local_env.read_text(encoding="utf-8") if local_env.exists() else None
    local_env.write_text(
        "\n".join(
            [
                "EVENTBRITE_RUNTIME_MODE=local",
                "EVENTBRITE_PRIVATE_TOKEN=test-local-token",
                "EVENTBRITE_DEFAULT_CURRENCY=usd",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("EVENTBRITE_PRIVATE_TOKEN", raising=False)
    monkeypatch.delenv("EVENTBRITE_SECRET_ID", raising=False)
    monkeypatch.delenv("EVENTBRITE_RUNTIME_MODE", raising=False)
    try:
        settings = config.get_settings()
    finally:
        if original is None:
            local_env.unlink(missing_ok=True)
        else:
            local_env.write_text(original, encoding="utf-8")

    assert settings.private_token == "test-local-token"
    assert settings.default_currency == "USD"
    assert settings.runtime_mode == "local"


def test_get_settings_skips_secrets_manager_in_local_mode(monkeypatch):
    monkeypatch.setenv("EVENTBRITE_RUNTIME_MODE", "local")
    monkeypatch.setenv("EVENTBRITE_PRIVATE_TOKEN", "from-env")
    monkeypatch.setenv("EVENTBRITE_SECRET_ID", "secret-id")

    def fail_load_secret(_: str) -> dict[str, str]:
        raise AssertionError("load_secret should not be called in local mode")

    monkeypatch.setattr(config, "load_secret", fail_load_secret)
    settings = config.get_settings()

    assert settings.private_token == "from-env"
    assert settings.runtime_mode == "local"


def test_get_settings_uses_secrets_manager_when_available(monkeypatch):
    monkeypatch.setenv("EVENTBRITE_RUNTIME_MODE", "cloud")
    monkeypatch.setenv("EVENTBRITE_SECRET_ID", "secret-id")
    monkeypatch.delenv("EVENTBRITE_PRIVATE_TOKEN", raising=False)

    def fake_load_secret(secret_id: str) -> dict[str, str]:
        assert secret_id == "secret-id"
        return {
            "EVENTBRITE_PRIVATE_TOKEN": "secret-token",
            "EVENTBRITE_API_AUTH_TOKEN": "api-token",
        }

    monkeypatch.setattr(config, "load_secret", fake_load_secret)
    settings = config.get_settings()

    assert settings.private_token == "secret-token"
    assert settings.api_auth_token == "api-token"
    assert settings.runtime_mode == "cloud"


def test_get_settings_rejects_invalid_runtime_mode(monkeypatch):
    monkeypatch.setenv("EVENTBRITE_RUNTIME_MODE", "staging-ish")
    monkeypatch.setenv("EVENTBRITE_PRIVATE_TOKEN", "from-env")

    with pytest.raises(RuntimeError, match="EVENTBRITE_RUNTIME_MODE"):
        config.get_settings()


def test_build_minor_authorization_form_url_includes_event_url_and_date():
    url = build_minor_authorization_form_url(
        "https://www.eventbrite.co/e/summer-triangle-corner-tickets-1996424879557",
        "08/07/2026",
    )

    assert "event_url=https%3A%2F%2Fwww.eventbrite.co%2Fe%2Fsummer-triangle-corner-tickets-1996424879557" in url
    assert "event_date=08%2F07%2F2026" in url
