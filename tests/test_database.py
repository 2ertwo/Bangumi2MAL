import os
import sqlite3
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
    run.items.append(
        SyncItemResult(
            42, "BGM", 84, "MAL", "manual", 1.0, "planned",
            bangumi_cover_url="https://example.com/bgm.jpg",
            mal_cover_url="https://example.com/mal.jpg",
            changes={"score": 8},
        )
    )
    database.create_run(run.run_id, "test", run.dry_run, run.started_at)
    database.finish_run(run)
    assert database.get_run("run-1")["planned"] == 1
    item = database.get_run_items("run-1")[0]
    assert item["changes"] == {"score": 8}
    assert item["bangumi_cover_url"] == "https://example.com/bgm.jpg"
    assert item["mal_cover_url"] == "https://example.com/mal.jpg"


def test_database_is_private_on_posix(tmp_path):
    database_path = tmp_path / "app.db"
    database = Database(database_path)
    database.initialize()

    if os.name != "nt":
        assert stat.S_IMODE(database_path.stat().st_mode) == 0o600


def test_database_adds_cover_columns_to_existing_database(tmp_path):
    database_path = tmp_path / "legacy.db"
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """CREATE TABLE sync_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                result TEXT NOT NULL
            )"""
        )

    database = Database(database_path)
    database.initialize()

    with database.connect() as connection:
        columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(sync_items)").fetchall()
        }
    assert {"bangumi_cover_url", "mal_cover_url"} <= columns
