from dataclasses import replace

from bangumi2mal.database import Database
from bangumi2mal.models import BangumiEntry, MalCandidate, MatchResult
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
            "main_picture": {"medium": "https://example.com/mal.jpg"},
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
    assert result.items[0].mal_cover_url == "https://example.com/mal.jpg"


def test_live_sync_writes_changes(tmp_path):
    database = Database(tmp_path / "app.db")
    database.initialize()
    database.save_mapping(10, 20)
    mal = Mal()
    service = SyncService(database, Bangumi(), mal, UnusedMatcher(), "user", write_delay_seconds=0)
    result = service.run(dry_run=False, source="test")
    assert result.items[0].result == "synced"
    assert mal.updates == [(20, {"score": 8})]


def test_unmapped_entry_is_enriched_with_bangumi_aliases(tmp_path):
    class BangumiWithAliases:
        def get_anime_collections(self, username):
            return [BangumiEntry(10, "Original", "", 3, 8, 5, 12)]

        def enrich_entry(self, entry):
            return replace(
                entry,
                air_date="2020-01-01",
                aliases=("English Alias",),
            )

    class AliasMatcher:
        def match(self, entry):
            assert entry.air_date == "2020-01-01"
            assert entry.aliases == ("English Alias",)
            candidate = MalCandidate(
                20,
                "English Alias",
                start_date="2020-01-01",
                num_episodes=12,
            )
            return MatchResult(candidate, "automatic", 1.0, (candidate,))

    database = Database(tmp_path / "app.db")
    database.initialize()
    service = SyncService(
        database,
        BangumiWithAliases(),
        Mal(),
        AliasMatcher(),
        "user",
        write_delay_seconds=0,
    )
    result = service.run(dry_run=True, source="test")
    assert result.items[0].result == "planned"
    assert database.get_mapping(10)["mal_id"] == 20


def test_old_automatic_mapping_is_rematched(tmp_path):
    class BangumiWithDetails:
        def get_anime_collections(self, username):
            return [BangumiEntry(10, "Title", "", 3, 8, 5, 12)]

        def enrich_entry(self, entry):
            return replace(entry, air_date="2020-01-01")

    class Rematcher:
        def __init__(self):
            self.called = False

        def match(self, entry):
            self.called = True
            candidate = MalCandidate(
                30,
                "Title",
                start_date="2020-01-01",
                num_episodes=12,
            )
            return MatchResult(candidate, "automatic", 1.0, (candidate,))

    database = Database(tmp_path / "app.db")
    database.initialize()
    database.save_mapping(10, 20, source="automatic")
    matcher = Rematcher()
    service = SyncService(
        database,
        BangumiWithDetails(),
        Mal(),
        matcher,
        "user",
        write_delay_seconds=0,
    )
    original_get_anime = service.mal_client.get_anime

    def get_anime(anime_id):
        anime = original_get_anime(anime_id)
        anime["id"] = anime_id
        return anime

    service.mal_client.get_anime = get_anime
    result = service.run(dry_run=True, source="test")
    assert result.items[0].result == "planned"
    assert matcher.called is True
    mapping = database.get_mapping(10)
    assert mapping["mal_id"] == 30
    assert mapping["source"] == "automatic_date_v2"
