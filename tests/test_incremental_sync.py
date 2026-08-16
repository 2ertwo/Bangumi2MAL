from pathlib import Path

from werkzeug.security import generate_password_hash

from bangumi2mal.config import Settings
from bangumi2mal.database import Database
from bangumi2mal.models import BangumiEntry, MatchResult
from bangumi2mal.sync_service import SyncService
from bangumi2mal.web import create_app


class MutableBangumi:
    def __init__(self, entries):
        self.entries = entries

    def get_anime_collections(self, username):
        return list(self.entries)


class CountingMal:
    def __init__(self, statuses):
        self.statuses = statuses
        self.get_calls = []
        self.updates = []

    def get_anime(self, anime_id):
        self.get_calls.append(anime_id)
        return {
            "id": anime_id,
            "title": f"MAL {anime_id}",
            "num_episodes": 12,
            "my_list_status": dict(self.statuses[anime_id]),
        }

    def update_list_status(self, anime_id, changes):
        self.updates.append((anime_id, changes))
        self.statuses[anime_id].update(changes)


class UnusedMatcher:
    def match(self, entry):
        raise AssertionError("saved mapping should be used")


def entry(subject_id, collection_type=3, score=7, watched=1):
    return BangumiEntry(
        subject_id,
        f"Title {subject_id}",
        "",
        collection_type,
        score,
        watched,
        12,
    )


def test_incremental_sync_only_processes_changed_collections(tmp_path):
    database = Database(tmp_path / "app.db")
    database.initialize()
    database.save_mapping(10, 20)
    database.save_mapping(11, 21)
    bangumi = MutableBangumi(
        [
            entry(10),
            entry(11, collection_type=2, score=8, watched=12),
        ]
    )
    mal = CountingMal(
        {
            20: {"status": "watching", "score": 7, "num_episodes_watched": 1},
            21: {"status": "completed", "score": 8, "num_episodes_watched": 12},
        }
    )
    service = SyncService(
        database, bangumi, mal, UnusedMatcher(), "user", write_delay_seconds=0
    )

    initial = service.run_incremental(source="test-incremental")
    assert [item.result for item in initial.items] == ["skipped", "skipped"]
    assert database.get_collection_sync_state() == {
        10: (3, 7, 1),
        11: (2, 8, 12),
    }

    mal.get_calls.clear()
    unchanged = service.run_incremental(source="test-incremental")
    assert unchanged.items == []
    assert unchanged.message == "No Bangumi collection changes detected."
    assert mal.get_calls == []

    bangumi.entries[0] = entry(10, score=8, watched=2)
    changed = service.run_incremental(source="test-incremental")
    assert len(changed.items) == 1
    assert changed.items[0].bangumi_id == 10
    assert changed.items[0].result == "synced"
    assert mal.get_calls == [20]
    assert mal.updates == [
        (20, {"score": 8, "num_watched_episodes": 2})
    ]
    assert database.get_collection_sync_state()[10] == (3, 8, 2)


def test_incremental_sync_retries_unresolved_entries(tmp_path):
    class UnresolvedMatcher:
        def __init__(self):
            self.calls = 0

        def match(self, item):
            self.calls += 1
            return MatchResult(None, "ambiguous", 0.7, ())

    database = Database(tmp_path / "app.db")
    database.initialize()
    matcher = UnresolvedMatcher()
    service = SyncService(
        database,
        MutableBangumi([entry(10)]),
        CountingMal({}),
        matcher,
        "user",
        write_delay_seconds=0,
    )

    first = service.run_incremental(source="test-incremental")
    second = service.run_incremental(source="test-incremental")

    assert first.items[0].result == "unresolved"
    assert second.items[0].result == "unresolved"
    assert matcher.calls == 2
    assert database.get_collection_sync_state() == {}


def test_dry_run_does_not_advance_incremental_state(tmp_path):
    database = Database(tmp_path / "app.db")
    database.initialize()
    database.save_mapping(10, 20)
    mal = CountingMal(
        {20: {"status": "watching", "score": 6, "num_episodes_watched": 1}}
    )
    service = SyncService(
        database,
        MutableBangumi([entry(10, score=8)]),
        mal,
        UnusedMatcher(),
        "user",
        write_delay_seconds=0,
    )

    result = service.run_incremental(dry_run=True, source="test-incremental")

    assert result.items[0].result == "planned"
    assert database.get_collection_sync_state() == {}
    assert mal.updates == []


def test_incremental_sync_forgets_removed_collections(tmp_path):
    database = Database(tmp_path / "app.db")
    database.initialize()
    database.save_collection_sync_states([entry(10), entry(11)])
    service = SyncService(
        database,
        MutableBangumi([entry(10)]),
        CountingMal({}),
        UnusedMatcher(),
        "user",
        write_delay_seconds=0,
    )

    result = service.run_incremental(source="test-incremental")

    assert result.items == []
    assert database.get_collection_sync_state() == {10: (3, 7, 1)}


def scheduler_settings(tmp_path: Path) -> Settings:
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
    )


def test_web_scheduler_registers_incremental_and_full_jobs(tmp_path, monkeypatch):
    class FakeScheduler:
        def __init__(self, **kwargs):
            self.jobs = {}
            self.started = False

        def add_job(self, function, trigger, **kwargs):
            self.jobs[kwargs["id"]] = {"function": function, "trigger": trigger, **kwargs}

        def get_job(self, job_id):
            return self.jobs.get(job_id)

        def start(self):
            self.started = True

    monkeypatch.setattr("bangumi2mal.web.BackgroundScheduler", FakeScheduler)

    app = create_app(scheduler_settings(tmp_path))
    scheduler = app.extensions["bangumi2mal_scheduler"]

    assert scheduler.started is True
    assert scheduler.jobs["rss-trigger"]["minutes"] == 5
    assert scheduler.jobs["incremental-sync"]["minutes"] == 10
    assert scheduler.jobs["full-sync"]["hours"] == 24
