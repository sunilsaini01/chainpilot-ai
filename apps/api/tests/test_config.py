"""Unit tests for settings and database URL construction."""

import pytest
from pydantic import ValidationError

from app.config import Settings


@pytest.fixture(autouse=True)
def clear_settings_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove settings variables from the environment so tests see only defaults.

    CI sets POSTGRES_* for the integration test; without this, a "default" test
    could pass just because CI happens to use the same value.
    """
    for field_name in Settings.model_fields:
        monkeypatch.delenv(field_name.upper(), raising=False)


def make_settings(**overrides: object) -> Settings:
    # _env_file=None so a developer's local .env cannot change test results.
    return Settings(_env_file=None, **overrides)


def test_password_with_reserved_characters_survives_url_building() -> None:
    password = "p@ss:w/rd#1?%"
    settings = make_settings(postgres_password=password, postgres_host="db", postgres_port=5433)

    url = settings.database_url

    # The URL object keeps the raw password and the host/port are not confused by "@" or ":".
    assert url.password == password
    assert url.host == "db"
    assert url.port == 5433
    assert url.drivername == "postgresql+psycopg"
    # When rendered as a string, the reserved characters are percent-encoded.
    rendered = url.render_as_string(hide_password=False)
    assert "p%40ss%3Aw%2Frd%231%3F%25@db:5433" in rendered


def test_password_is_hidden_in_repr_and_default_url_string() -> None:
    settings = make_settings(postgres_password="super-secret")

    assert "super-secret" not in repr(settings)
    assert "super-secret" not in str(settings.database_url)


def test_empty_password_is_omitted_from_url() -> None:
    settings = make_settings(postgres_password="")

    assert settings.database_url.password is None


def test_settings_read_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POSTGRES_HOST", "postgres")
    monkeypatch.setenv("POSTGRES_PORT", "6543")
    monkeypatch.setenv("POSTGRES_DB", "chainpilot_test")

    settings = make_settings()

    assert settings.database_url.host == "postgres"
    assert settings.database_url.port == 6543
    assert settings.database_url.database == "chainpilot_test"


def test_default_host_is_ipv4_loopback() -> None:
    # "localhost" can resolve to IPv6 first and stall against IPv4-only Docker ports.
    assert make_settings().database_url.host == "127.0.0.1"


def test_invalid_port_is_rejected() -> None:
    with pytest.raises(ValidationError):
        make_settings(postgres_port=70000)


def test_unknown_log_level_is_rejected() -> None:
    with pytest.raises(ValidationError):
        make_settings(log_level="verbose")
