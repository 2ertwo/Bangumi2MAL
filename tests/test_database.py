import os
import stat

from bangumi2mal.database import Database
from bangumi2mal.models import SyncItemResult, SyncRunResult


def test_database_round_trip(tmp_path):
    database = Database(tmp_path / "app.db")
    database.initialize()
    database.save_mapping(42, 84, "BGM", "MAL")
    mapping = database.get_mapping(42)
    assert mapping["mal_id"] == 84

    database.save_token("mal", "access", "refresh", 123)
    assert database.get_token("mal")["refresh_token"] == "refresh"

    run = SyncRunResult("run-1", True, "start", "finish", "completed")
    run.items.append(SyncItemResult(42, "BGM", 84, "MAL", "manual", 1.0, "planned", {"score": 8}))
    database.create_run(run.run_id, "test", run.dry_run, run.started_at)
    database.finish_run(run)
    assert database.get_run("run-1")["planned"] == 1
    assert database.get_run_items("run-1")[0]["changes"] == {"score": 8}


def test_database_is_private_on_posix(tmp_path):
    database_path = tmp_path / "app.db"
    database = Database(database_path)
    database.initialize()

    if os.name != "nt":
        assert stat.S_IMODE(database_path.stat().st_mode) == 0o600
