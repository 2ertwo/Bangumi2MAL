from pathlib import Path

import pytest
from dotenv import dotenv_values
from werkzeug.security import check_password_hash

from bangumi2mal.setup_wizard import (
    SetupError,
    SetupWizard,
    base_url_from_redirect,
    normalize_base_url,
)


CONFIG_KEYS = [
    "BANGUMI_USERNAME",
    "BANGUMI_ACCESS_TOKEN",
    "BANGUMI_USER_AGENT",
    "MAL_CLIENT_ID",
    "MAL_CLIENT_SECRET",
    "MAL_REDIRECT_URI",
    "WEB_PASSWORD_HASH",
    "FLASK_SECRET_KEY",
    "SESSION_COOKIE_SECURE",
]


class FakeBangumi:
    def __init__(self, token, user_agent):
        assert token == "bangumi-token"
        assert user_agent

    def get_me(self):
        return {"username": "test-user", "nickname": "Test User"}

    def close(self):
        pass


def clear_config_environment(monkeypatch):
    for key in CONFIG_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_normalize_base_url():
    assert normalize_base_url("https://sync.example.com/") == "https://sync.example.com"
    assert base_url_from_redirect("https://sync.example.com/oauth/mal/callback") == "https://sync.example.com"
    with pytest.raises(SetupError):
        normalize_base_url("sync.example.com")
    with pytest.raises(SetupError):
        normalize_base_url("https://sync.example.com/path")


def test_setup_writes_complete_configuration_and_detects_username(tmp_path, monkeypatch):
    clear_config_environment(monkeypatch)
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "data" / "app.db"))
    inputs = iter(["mal-client-id"])
    secrets = iter(["bangumi-token", "mal-client-secret", "web-password", "web-password"])
    opened = []
    env_path = tmp_path / ".env"
    wizard = SetupWizard(
        env_path,
        input_func=lambda prompt: next(inputs),
        secret_func=lambda prompt: next(secrets),
        opener=opened.append,
        bangumi_client_factory=FakeBangumi,
    )

    result = wizard.run(
        base_url="https://sync.example.com",
        open_browser=False,
        authorize_mal=False,
    )

    values = dotenv_values(env_path)
    assert values["BANGUMI_USERNAME"] == "test-user"
    assert values["BANGUMI_ACCESS_TOKEN"] == "bangumi-token"
    assert values["MAL_CLIENT_ID"] == "mal-client-id"
    assert values["MAL_CLIENT_SECRET"] == "mal-client-secret"
    assert values["MAL_REDIRECT_URI"] == "https://sync.example.com/oauth/mal/callback"
    assert values["SESSION_COOKIE_SECURE"] == "true"
    assert check_password_hash(values["WEB_PASSWORD_HASH"], "web-password")
    assert values["FLASK_SECRET_KEY"]
    assert result.settings.database_path.exists()
    assert result.bangumi_display_name == "Test User"
    assert not result.mal_authorized
    assert opened == []


def test_setup_reuses_existing_values_without_reasking(tmp_path, monkeypatch):
    clear_config_environment(monkeypatch)
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "data" / "app.db"))
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "BANGUMI_ACCESS_TOKEN='bangumi-token'",
                "MAL_CLIENT_ID='existing-client'",
                "MAL_CLIENT_SECRET=''",
                "MAL_REDIRECT_URI='http://127.0.0.1:5000/oauth/mal/callback'",
                "WEB_PASSWORD_HASH='existing-hash'",
                "FLASK_SECRET_KEY='existing-secret'",
            ]
        ),
        encoding="utf-8",
    )
    wizard = SetupWizard(
        env_path,
        input_func=lambda prompt: pytest.fail(f"unexpected input prompt: {prompt}"),
        secret_func=lambda prompt: pytest.fail(f"unexpected secret prompt: {prompt}"),
        bangumi_client_factory=FakeBangumi,
    )
    result = wizard.run(open_browser=False, authorize_mal=False)
    assert result.settings.mal_client_id == "existing-client"
    assert result.settings.flask_secret_key == "existing-secret"
