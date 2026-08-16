import pytest

from bangumi2mal.clients.bangumi import BangumiClient
from bangumi2mal.clients.mal import MalClient, MalOAuth


def test_bangumi_collection_parser():
    entry = BangumiClient._parse_entry(
        {
            "subject_id": 123,
            "type": 3,
            "rate": 8,
            "ep_status": 6,
            "updated_at": "2026-01-01T00:00:00Z",
            "subject": {
                "name": "Original",
                "name_cn": "中文",
                "eps": 12,
                "date": "2025-10-01",
                "images": {"large": "https://lain.bgm.tv/pic/cover/l/example.jpg"},
                "infobox": [{"key": "别名", "value": [{"v": "English Alias"}, {"v": "日本別名"}]}],
            },
        }
    )
    assert entry.subject_id == 123
    assert entry.watched_episodes == 6
    assert entry.cover_url == "https://lain.bgm.tv/pic/cover/l/example.jpg"
    assert entry.aliases == ("English Alias", "日本別名")
    assert entry.search_titles == ["Original", "中文", "English Alias", "日本別名"]


def test_mal_candidate_parser_collects_alternative_titles():
    candidate = MalClient._candidate_from_node(
        {
            "id": 456,
            "title": "Main",
            "alternative_titles": {"ja": "日本語", "en": "English", "synonyms": ["Alias"]},
            "media_type": "tv",
            "start_date": "2025-01-01",
            "num_episodes": 24,
            "main_picture": {"medium": "https://cdn.myanimelist.net/images/anime/example.jpg"},
        }
    )
    assert candidate.anime_id == 456
    assert candidate.cover_url == "https://cdn.myanimelist.net/images/anime/example.jpg"
    assert candidate.alternative_titles == ("日本語", "English", "Alias")


def test_oauth_url_contains_pkce_and_state():
    oauth = MalOAuth("client", "", "http://localhost/callback")
    url = oauth.authorization_url("verifier", "state-value")
    assert "code_challenge=verifier" in url
    assert "code_challenge_method=plain" in url
    assert "state=state-value" in url


def test_mal_season_catalog_pages_deduplicates_and_filters_quarter():
    calls = []

    class Response:
        def __init__(self, payload):
            self.payload = payload

        def json(self):
            return self.payload

    client = object.__new__(MalClient)

    def request(method, url, params):
        calls.append((method, url, params["offset"]))
        season = url.rsplit("/", 1)[-1]
        offset = params["offset"]
        if season == "winter" and offset == 0:
            return Response(
                {
                    "data": [
                        {"node": {"id": 1, "title": "In year", "start_date": "2023-01-01"}},
                        {"node": {"id": 2, "title": "Old", "start_date": "2022-10-01"}},
                    ],
                    "paging": {"next": "next-page"},
                }
            )
        if season == "winter" and offset == 2:
            return Response(
                {
                    "data": [
                        {"node": {"id": 1, "title": "Duplicate", "start_date": "2023-01-01"}},
                        {"node": {"id": 3, "title": "Also in year", "start_date": "2023-02-01"}},
                        {"node": {"id": 5, "title": "Next quarter", "start_date": "2023-04-01"}},
                        {"node": {"id": 4, "title": "Year only", "start_date": "2023"}},
                    ],
                    "paging": {},
                }
            )
        return Response({"data": [], "paging": {}})

    client.request = request
    candidates = client.list_anime_by_season(2023, "winter")

    assert {candidate.anime_id for candidate in candidates} == {1, 3}
    assert [offset for _, url, offset in calls if url.endswith("/winter")] == [0, 2]


def test_mal_season_catalog_rejects_unknown_season():
    client = object.__new__(MalClient)
    with pytest.raises(ValueError, match="Unsupported MAL season"):
        client.list_anime_by_season(2023, "monsoon")
