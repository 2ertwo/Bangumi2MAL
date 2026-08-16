import pytest

from bangumi2mal.matching import AnimeMatcher, candidate_score, normalize_title
from bangumi2mal.models import BangumiEntry, MalCandidate


def entry(**overrides):
    values = dict(
        subject_id=1,
        title="Sousou no Frieren",
        title_cn="葬送的芙莉莲",
        collection_type=2,
        score=9,
        watched_episodes=28,
        total_episodes=28,
        air_date="2023-09-29",
    )
    values.update(overrides)
    return BangumiEntry(**values)


def test_normalize_title_handles_width_case_and_punctuation():
    assert normalize_title("ＦＲＩＥＲＥＮ: Beyond Journey's End") == "frierenbeyondjourneysend"


def test_candidate_score_rewards_title_date_and_episode_match():
    candidate = MalCandidate(
        anime_id=52991,
        title="Sousou no Frieren",
        start_date="2023-09-29",
        num_episodes=28,
    )
    assert candidate_score(entry(), candidate) == pytest.approx(1.0)


@pytest.mark.parametrize(
    "entry_date, candidate_date",
    [
        ("2023-09-29", "2023-09-28"),
        ("2023-09-29", "2023-09-30"),
        ("2023-03-31", "2023-04-01"),
        ("2023-12-31", "2024-01-01"),
    ],
)
def test_candidate_score_accepts_one_day_air_date_difference(entry_date, candidate_date):
    candidate = MalCandidate(
        anime_id=52991,
        title="Sousou no Frieren",
        start_date=candidate_date,
        num_episodes=28,
    )
    assert candidate_score(entry(air_date=entry_date), candidate) == pytest.approx(1.0)


def test_candidate_score_does_not_fully_accept_two_day_air_date_difference():
    candidate = MalCandidate(
        anime_id=52991,
        title="Sousou no Frieren",
        start_date="2023-09-27",
        num_episodes=28,
    )
    assert candidate_score(entry(), candidate) < 1.0


def test_candidate_score_prefers_exact_air_date_for_same_title():
    same_title_other_date = MalCandidate(
        anime_id=1,
        title="Sousou no Frieren",
        start_date="2023-07-01",
        num_episodes=28,
    )
    same_title_exact_date = MalCandidate(
        anime_id=2,
        title="Sousou no Frieren",
        start_date="2023-09-29",
        num_episodes=28,
    )
    assert candidate_score(entry(), same_title_exact_date) > candidate_score(entry(), same_title_other_date)


def test_matcher_accepts_clear_winner():
    searches = []

    class Client:
        def search_anime(self, query, limit=10):
            searches.append(query)
            return [
                MalCandidate(52991, "Sousou no Frieren", start_date="2023-09-29", num_episodes=28),
                MalCandidate(60000, "Frieren Shorts", start_date="2023-07-01", num_episodes=6),
            ]

        def list_anime_by_season(self, year, season):
            raise AssertionError("quarter fallback should not run for a clear search match")

    result = AnimeMatcher(Client(), threshold=0.94, margin=0.08).match(entry())
    assert result.candidate is not None
    assert result.candidate.anime_id == 52991
    assert result.method == "automatic_search"
    assert searches


def test_matcher_searches_bangumi_aliases():
    queries = []

    class Client:
        def search_anime(self, query, limit=10):
            queries.append(query)
            if query == "Frieren: Beyond Journey's End":
                return [
                    MalCandidate(
                        52991,
                        "Frieren: Beyond Journey's End",
                        start_date="2023-09-29",
                        num_episodes=28,
                    )
                ]
            return []

        def list_anime_by_season(self, year, season):
            raise AssertionError("quarter fallback should not run for an alias search match")

    result = AnimeMatcher(Client()).match(
        entry(
            title="葬送のフリーレン",
            title_cn="葬送的芙莉莲",
            aliases=("Frieren: Beyond Journey's End",),
        )
    )
    assert result.candidate is not None
    assert "Frieren: Beyond Journey's End" in queries
    assert result.method == "automatic_search"


def test_matcher_rejects_ambiguous_candidates_after_quarter_fallback():
    periods = []

    class Client:
        @staticmethod
        def candidates():
            return [
                MalCandidate(1, "Same Title", start_date="2020-01-01", num_episodes=12),
                MalCandidate(2, "Same Title", start_date="2020-01-01", num_episodes=12),
            ]

        def search_anime(self, query, limit=10):
            return self.candidates()

        def list_anime_by_season(self, year, season):
            periods.append((year, season))
            return self.candidates()

    ambiguous = entry(title="Same Title", title_cn="", air_date="2020-01-01", total_episodes=12)
    result = AnimeMatcher(Client()).match(ambiguous)
    assert result.candidate is None
    assert result.method == "ambiguous"
    assert periods == [(2020, "winter"), (2019, "fall")]


def test_matcher_skips_failed_alias_search_and_uses_other_titles():
    queries = []

    class Client:
        def search_anime(self, query, limit=10):
            queries.append(query)
            if query == "invalid alias":
                raise RuntimeError("invalid q")
            if query == "Frieren: Beyond Journey's End":
                return [
                    MalCandidate(
                        52991,
                        "Frieren: Beyond Journey's End",
                        start_date="2023-09-29",
                        num_episodes=28,
                    )
                ]
            return []

    result = AnimeMatcher(Client(), threshold=0.70).match(
        entry(
            title="invalid alias",
            title_cn="",
            aliases=("Frieren: Beyond Journey's End",),
            air_date="",
        )
    )
    assert result.candidate is not None
    assert result.candidate.anime_id == 52991
    assert result.method == "automatic_search"


def test_matcher_caches_each_quarter_until_cleared():
    periods = []

    class Client:
        def search_anime(self, query, limit=10):
            return []

        def list_anime_by_season(self, year, season):
            periods.append((year, season))
            return [
                MalCandidate(
                    52991,
                    "Sousou no Frieren",
                    start_date="2023-09-29",
                    num_episodes=28,
                )
            ]

    matcher = AnimeMatcher(Client())
    first = matcher.match(entry())
    matcher.match(entry(subject_id=2))
    assert first.method == "automatic_season"
    assert periods == [(2023, "summer")]

    matcher.clear_cache()
    matcher.match(entry(subject_id=3))
    assert periods == [(2023, "summer"), (2023, "summer")]


def test_matcher_scans_adjacent_quarter_for_one_day_boundary_tolerance():
    periods = []

    class Client:
        def search_anime(self, query, limit=10):
            return []

        def list_anime_by_season(self, year, season):
            periods.append((year, season))
            if (year, season) == (2023, "spring"):
                return [
                    MalCandidate(
                        52991,
                        "Sousou no Frieren",
                        start_date="2023-04-01",
                        num_episodes=28,
                    )
                ]
            return []

    result = AnimeMatcher(Client()).match(entry(air_date="2023-03-31"))
    assert result.candidate is not None
    assert result.method == "automatic_season"
    assert periods == [(2023, "winter"), (2023, "spring")]


@pytest.mark.parametrize(
    "air_date, expected",
    [
        ("2023-01-01", (2023, "winter")),
        ("2023-03-31", (2023, "winter")),
        ("2023-04-01", (2023, "spring")),
        ("2023-07-01", (2023, "summer")),
        ("2023-10-01", (2023, "fall")),
        ("2023", None),
        ("2023-13-01", None),
    ],
)
def test_air_date_maps_to_quarter(air_date, expected):
    assert AnimeMatcher._air_season(air_date) == expected


def test_normalize_title_treats_greek_zeta_as_latin_z():
    greek = "\u6a5f\u52d5\u6226\u58eb\u30ac\u30f3\u30c0\u30e0\u0396\u0396"
    latin = "\u6a5f\u52d5\u6226\u58eb\u30ac\u30f3\u30c0\u30e0ZZ"
    assert normalize_title(greek) == normalize_title(latin)


def test_matcher_normalizes_greek_zeta_before_mal_search():
    queries = []
    latin_title = "\u6a5f\u52d5\u6226\u58eb\u30ac\u30f3\u30c0\u30e0ZZ"

    class Client:
        def search_anime(self, query, limit=10):
            queries.append(query)
            if query == latin_title:
                return [
                    MalCandidate(
                        86,
                        "Kidou Senshi Gundam ZZ",
                        alternative_titles=(latin_title, "Mobile Suit Gundam ZZ"),
                        start_date="1986-03-01",
                        num_episodes=47,
                    )
                ]
            return []

        def list_anime_by_season(self, year, season):
            raise AssertionError("quarter fallback should not run for normalized title match")

    result = AnimeMatcher(Client()).match(
        entry(
            subject_id=4213,
            title="\u6a5f\u52d5\u6226\u58eb\u30ac\u30f3\u30c0\u30e0\u0396\u0396",
            title_cn="\u673a\u52a8\u6218\u58eb\u9ad8\u8fbeZZ",
            total_episodes=47,
            watched_episodes=47,
            air_date="1986-03-01",
        )
    )

    assert queries[0] == latin_title
    assert result.candidate is not None
    assert result.candidate.anime_id == 86
    assert result.confidence == pytest.approx(1.0)
    assert result.method == "automatic_search"
