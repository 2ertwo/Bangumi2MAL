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
            },
        }
    )
    assert entry.subject_id == 123
    assert entry.search_titles == ["Original", "中文"]
    assert entry.watched_episodes == 6
    assert entry.cover_url == "https://lain.bgm.tv/pic/cover/l/example.jpg"


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
