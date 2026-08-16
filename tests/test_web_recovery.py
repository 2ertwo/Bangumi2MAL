from pathlib import Path

import pytest
from werkzeug.security import generate_password_hash

from bangumi2mal.config import Settings
from bangumi2mal.database import Database
from bangumi2mal.web import create_app


def web_settings(tmp_path: Path) -> Settings:
    return Settings(
        bangumi_username="user",
        bangumi_access_token="token",
        bangumi_user_agent="tests",
        mal_client_id="client",
        mal_client_secret="",
        mal_redirect_uri="http://localhost/oauth/mal/callback",
        web_password_hash=generate_password_hash("secret"),
        flask_secret_key="test-secret",
        database_path=tmp_path / "app.db",
        reports_dir=tmp_path / "reports",
        log_level="INFO",
        auto_sync_enabled=False,
        auto_sync_hours=6,
        mal_write_delay_seconds=0,
        auto_match_threshold=0.94,
        auto_match_margin=0.08,
        allow_decrease_watched=False,
        session_cookie_secure=False,
    )


def test_create_app_rejects_missing_secrets(tmp_path, monkeypatch):
    settings = web_settings(tmp_path)
    object.__setattr__(settings, "flask_secret_key", "")
    with pytest.raises(RuntimeError, match="FLASK_SECRET_KEY"):
        create_app(settings)


def test_create_app_marks_interrupted_run_failed(tmp_path):
    settings = web_settings(tmp_path)
    database = Database(settings.database_path)
    database.initialize()
    database.create_run("interrupted", "web", True, "2026-01-01T00:00:00+00:00")
    create_app(settings)
    assert database.get_run("interrupted")["status"] == "failed"
