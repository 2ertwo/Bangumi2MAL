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


def test_candidate_score_prioritizes_air_date_over_exact_title():
    same_date = MalCandidate(
        anime_id=1,
        title="Frieren Beyond Journey",
        start_date="2023-09-29",
        num_episodes=28,
    )
    exact_title_wrong_date = MalCandidate(
        anime_id=2,
        title="Sousou no Frieren",
        start_date="2020-01-01",
        num_episodes=28,
    )
    assert candidate_score(entry(), same_date) > candidate_score(entry(), exact_title_wrong_date)


def test_matcher_accepts_clear_winner():
    class Client:
        def search_anime(self, query, limit=10):
            return [
                MalCandidate(52991, "Sousou no Frieren", start_date="2023-09-29", num_episodes=28),
                MalCandidate(60000, "Frieren Shorts", start_date="2024-01-01", num_episodes=6),
            ]

    result = AnimeMatcher(Client(), threshold=0.94, margin=0.08).match(entry())
    assert result.candidate is not None
    assert result.candidate.anime_id == 52991


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

    result = AnimeMatcher(Client()).match(
        entry(
            title="葬送のフリーレン",
            title_cn="葬送的芙莉莲",
            aliases=("Frieren: Beyond Journey's End",),
        )
    )
    assert result.candidate is not None
    assert "Frieren: Beyond Journey's End" in queries


def test_matcher_rejects_ambiguous_candidates():
    class Client:
        def search_anime(self, query, limit=10):
            return [
                MalCandidate(1, "Same Title", start_date="2020-01-01", num_episodes=12),
                MalCandidate(2, "Same Title", start_date="2020-01-01", num_episodes=12),
            ]

    ambiguous = entry(title="Same Title", title_cn="", air_date="2020-01-01", total_episodes=12)
    result = AnimeMatcher(Client()).match(ambiguous)
    assert result.candidate is None
    assert result.method == "ambiguous"


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

    result = AnimeMatcher(Client()).match(
        entry(title="invalid alias", title_cn="", aliases=("Frieren: Beyond Journey's End",))
    )
    assert result.candidate is not None
    assert result.candidate.anime_id == 52991
