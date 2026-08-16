from bangumi2mal.clients.bangumi import BangumiClient
from bangumi2mal.database import Database


def test_bangumi_timeline_feed_parses_guids_and_quotes_username():
    calls = []

    class Response:
        text = """<?xml version="1.0" encoding="UTF-8"?>
        <rss><channel>
          <item><guid>timeline/second</guid></item>
          <item><guid>timeline/first</guid></item>
        </channel></rss>"""

    client = object.__new__(BangumiClient)

    def request(method, url, headers):
        calls.append((method, url, headers))
        return Response()

    client.request = request

    assert client.get_timeline_feed_guids("user/name") == (
        "timeline/second",
        "timeline/first",
    )
    assert calls == [
        (
            "GET",
            "https://bgm.tv/feed/user/user%2Fname/timeline",
            {"Accept": "application/rss+xml"},
        )
    ]


def test_feed_checkpoint_round_trip(tmp_path):
    database = Database(tmp_path / "app.db")
    database.initialize()

    assert database.get_feed_checkpoint("timeline:user") == ""
    database.save_feed_checkpoint("timeline:user", "guid-1")
    assert database.get_feed_checkpoint("timeline:user") == "guid-1"
    database.save_feed_checkpoint("timeline:user", "guid-2")
    assert database.get_feed_checkpoint("timeline:user") == "guid-2"
