from pathlib import Path

from werkzeug.security import generate_password_hash

from bangumi2mal.config import Settings
from bangumi2mal.database import Database
from bangumi2mal.models import SyncItemResult, SyncRunResult
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


def test_run_detail_renders_entry_and_candidate_covers(tmp_path):
    app_settings = settings(tmp_path)
    database = Database(app_settings.database_path)
    database.initialize()
    run = SyncRunResult("covers", True, "start", "finish", "completed")
    run.items.append(
        SyncItemResult(
            42,
            "Bangumi title",
            None,
            "",
            "ambiguous",
            0.8,
            "unresolved",
            bangumi_cover_url="https://example.com/bangumi.jpg",
            candidates=[
                {
                    "anime_id": 84,
                    "title": "MAL candidate",
                    "score": 0.8,
                    "cover_url": "https://example.com/candidate.jpg",
                }
            ],
        )
    )
    run.items.append(
        SyncItemResult(
            43,
            "Second Bangumi title",
            None,
            "",
            "ambiguous",
            0.7,
            "unresolved",
            candidates=[
                {
                    "anime_id": 86,
                    "title": "Second MAL candidate",
                    "score": 0.7,
                    "cover_url": "https://example.com/candidate-2.jpg",
                }
            ],
        )
    )
    database.create_run(run.run_id, "test", run.dry_run, run.started_at)
    database.finish_run(run)

    app = create_app(app_settings)
    app.config["TESTING"] = True
    client = app.test_client()
    client.get("/login")
    with client.session_transaction() as state:
        csrf = state["csrf_token"]
    client.post("/login", data={"password": "secret", "csrf_token": csrf})

    response = client.get("/runs/covers")
    assert response.status_code == 200
    assert b"https://example.com/bangumi.jpg" in response.data
    assert b"https://example.com/candidate.jpg" in response.data
    assert b'name="mal_id" value="84"' in response.data
    assert b'name="mal_id" value="86"' in response.data
    assert response.data.count(b"candidate-strip") == 2
    assert b'data-bangumi-id="42"' in response.data
    assert b'data-bangumi-id="43"' in response.data
    assert b'Use &amp; retry' not in response.data
    assert b'name="retry"' not in response.data
    assert b"Retry dry run" in response.data


def test_mapping_save_waits_for_explicit_retry(tmp_path, monkeypatch):
    app_settings = settings(tmp_path)
    database = Database(app_settings.database_path)
    database.initialize()
    run = SyncRunResult("manual-map", True, "start", "finish", "completed")
    run.items.append(
        SyncItemResult(
            42,
            "Bangumi title",
            None,
            "",
            "ambiguous",
            0.8,
            "unresolved",
        )
    )
    database.create_run(run.run_id, "test", run.dry_run, run.started_at)
    database.finish_run(run)
    item_id = database.get_run_items(run.run_id)[0]["id"]

    class FakeMalClient:
        @staticmethod
        def get_anime(mal_id):
            return {"id": mal_id, "title": "Chosen MAL title"}

    started = []

    class UnexpectedThread:
        def __init__(self, *args, **kwargs):
            started.append("created")

        def start(self):
            started.append("started")

    monkeypatch.setattr("bangumi2mal.web.build_mal_client", lambda *_: FakeMalClient())
    monkeypatch.setattr("bangumi2mal.web.threading.Thread", UnexpectedThread)

    app = create_app(app_settings)
    app.config["TESTING"] = True
    client = app.test_client()
    client.get("/login")
    with client.session_transaction() as state:
        csrf = state["csrf_token"]
    client.post("/login", data={"password": "secret", "csrf_token": csrf})
    with client.session_transaction() as state:
        csrf = state["csrf_token"]

    response = client.post(
        f"/items/{item_id}/map",
        data={"mal_id": "84", "retry": "yes", "csrf_token": csrf},
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith(f"/runs/manual-map#item-{item_id}")
    mapping = database.get_mapping(42)
    assert mapping is not None
    assert mapping["mal_id"] == 84
    assert mapping["source"] == "manual"
    assert started == []


def test_run_detail_lists_items_needing_attention_first(tmp_path):
    app_settings = settings(tmp_path)
    database = Database(app_settings.database_path)
    database.initialize()
    run = SyncRunResult("attention-first", True, "start", "finish", "completed")
    run.items.extend(
        [
            SyncItemResult(1, "Planned title", 101, "MAL", "automatic", 1.0, "planned"),
            SyncItemResult(2, "Skipped title", 102, "MAL", "automatic", 1.0, "skipped"),
            SyncItemResult(3, "Failed title", None, "", "error", 0.0, "failed"),
            SyncItemResult(
                4,
                "Needs confirmation",
                None,
                "",
                "ambiguous",
                0.8,
                "unresolved",
            ),
        ]
    )
    database.create_run(run.run_id, "test", run.dry_run, run.started_at)
    database.finish_run(run)

    app = create_app(app_settings)
    app.config["TESTING"] = True
    client = app.test_client()
    client.get("/login")
    with client.session_transaction() as state:
        csrf = state["csrf_token"]
    client.post("/login", data={"password": "secret", "csrf_token": csrf})

    response = client.get("/runs/attention-first")
    page = response.data.decode()

    assert response.status_code == 200
    assert page.index("Needs confirmation") < page.index("Failed title")
    assert page.index("Failed title") < page.index("Planned title")
    assert page.index("Planned title") < page.index("Skipped title")
