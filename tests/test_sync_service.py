from bangumi2mal.database import Database
from bangumi2mal.models import BangumiEntry
from bangumi2mal.sync_service import SyncService


class UnusedMatcher:
    def match(self, entry):
        raise AssertionError("saved mapping should be used")


class Bangumi:
    def get_anime_collections(self, username):
        return [BangumiEntry(10, "Title", "标题", 3, 8, 5, 12)]


class Mal:
    def __init__(self):
        self.updates = []

    def get_anime(self, anime_id):
        return {
            "id": anime_id,
            "title": "Title",
            "num_episodes": 12,
            "my_list_status": {"status": "watching", "score": 7, "num_episodes_watched": 7},
        }

    def update_list_status(self, anime_id, changes):
        self.updates.append((anime_id, changes))


def test_dry_run_does_not_write_and_does_not_decrease_episodes(tmp_path):
    database = Database(tmp_path / "app.db")
    database.initialize()
    database.save_mapping(10, 20)
    mal = Mal()
    service = SyncService(database, Bangumi(), mal, UnusedMatcher(), "user", write_delay_seconds=0)
    result = service.run(dry_run=True, source="test")
    assert mal.updates == []
    assert result.items[0].result == "planned"
    assert result.items[0].changes == {"score": 8}


def test_live_sync_writes_changes(tmp_path):
    database = Database(tmp_path / "app.db")
    database.initialize()
    database.save_mapping(10, 20)
    mal = Mal()
    service = SyncService(database, Bangumi(), mal, UnusedMatcher(), "user", write_delay_seconds=0)
    result = service.run(dry_run=False, source="test")
    assert result.items[0].result == "synced"
    assert mal.updates == [(20, {"score": 8})]
