from pathlib import Path

from werkzeug.security import generate_password_hash

from bangumi2mal.config import Settings
from bangumi2mal.web import create_app


def settings(tmp_path: Path) -> Settings:
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


def test_dashboard_requires_login(tmp_path):
    app = create_app(settings(tmp_path))
    app.config["TESTING"] = True
    response = app.test_client().get("/")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_password_only_login(tmp_path):
    app = create_app(settings(tmp_path))
    app.config["TESTING"] = True
    client = app.test_client()
    client.get("/login")
    with client.session_transaction() as state:
        csrf = state["csrf_token"]
    response = client.post("/login", data={"password": "secret", "csrf_token": csrf})
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/")
    assert client.get("/").status_code == 200
