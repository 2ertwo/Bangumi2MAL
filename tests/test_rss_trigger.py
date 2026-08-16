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
        auto_sync_enabled=True,
        auto_sync_hours=24,
        mal_write_delay_seconds=0,
        auto_match_threshold=0.94,
        auto_match_margin=0.08,
        allow_decrease_watched=False,
        session_cookie_secure=False,
        incremental_sync_minutes=10,
        rss_poll_minutes=5,
    )


def test_rss_poll_initializes_checkpoint_then_starts_incremental_sync(
    tmp_path, monkeypatch
):
    feeds = iter([("guid-1",), ("guid-2",)])
    started_threads = []

    class FakeBangumiClient:
        def __init__(self, token, user_agent):
            pass

        def get_timeline_feed_guids(self, username):
            return next(feeds)

        def close(self):
            pass

    class FakeThread:
        def __init__(self, target, args, daemon):
            self.target = target
            self.args = args

        def start(self):
            started_threads.append(self.args)

    class FakeScheduler:
        def __init__(self, **kwargs):
            self.jobs = {}

        def add_job(self, function, trigger, **kwargs):
            self.jobs[kwargs["id"]] = {"function": function, "trigger": trigger, **kwargs}

        def get_job(self, job_id):
            return self.jobs.get(job_id)

        def start(self):
            pass

    monkeypatch.setattr("bangumi2mal.web.BangumiClient", FakeBangumiClient)
    monkeypatch.setattr("bangumi2mal.web.threading.Thread", FakeThread)
    monkeypatch.setattr("bangumi2mal.web.BackgroundScheduler", FakeScheduler)

    app = create_app(settings(tmp_path))
    database = app.extensions["bangumi2mal_database"]
    poll = app.extensions["bangumi2mal_scheduler"].jobs["rss-trigger"]["function"]

    poll()
    assert database.get_feed_checkpoint("timeline:user") == "guid-1"
    assert started_threads == []

    poll()
    assert database.get_feed_checkpoint("timeline:user") == "guid-2"
    assert started_threads == [(False, "rss-trigger", True)]
