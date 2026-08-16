from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import replace
from datetime import date, timedelta
from difflib import SequenceMatcher
from typing import Optional, Protocol

from .models import BangumiEntry, MalCandidate, MatchResult


LOGGER = logging.getLogger(__name__)

_TITLE_CONFUSABLES = str.maketrans({"\u0396": "Z", "\u03b6": "z"})


def _normalize_search_title(value: str) -> str:
    return unicodedata.normalize("NFKC", value).translate(_TITLE_CONFUSABLES)


class SearchClient(Protocol):
    def list_anime_by_season(self, year: int, season: str) -> list[MalCandidate]: ...

    def search_anime(self, query: str, limit: int = 10) -> list[MalCandidate]: ...


def normalize_title(value: str) -> str:
    value = _normalize_search_title(value).casefold()
    value = re.sub(r"[^\w\u3040-\u30ff\u3400-\u9fff]+", "", value, flags=re.UNICODE)
    return value


def _title_similarity(entry: BangumiEntry, candidate: MalCandidate) -> float:
    sources = [normalize_title(title) for title in entry.search_titles]
    targets = [normalize_title(candidate.title)] + [
        normalize_title(title) for title in candidate.alternative_titles
    ]
    scores = [
        SequenceMatcher(None, source, target).ratio()
        for source in sources
        for target in targets
        if source and target
    ]
    return max(scores, default=0.0)


def _date_similarity(entry_date: str, candidate_date: str) -> float:
    if not entry_date or not candidate_date:
        return 0.5
    if entry_date == candidate_date:
        return 1.0
    if len(entry_date) == 10 and len(candidate_date) == 10:
        try:
            entry_day = date.fromisoformat(entry_date)
            candidate_day = date.fromisoformat(candidate_date)
        except ValueError:
            pass
        else:
            if abs((entry_day - candidate_day).days) <= 1:
                return 1.0
    if len(entry_date) >= 7 and len(candidate_date) >= 7 and entry_date[:7] == candidate_date[:7]:
        return 0.9
    if entry_date[:4] == candidate_date[:4]:
        return 0.75
    return 0.0


def _episode_similarity(entry_episodes: int, candidate_episodes: int) -> float:
    if not entry_episodes or not candidate_episodes:
        return 0.5
    if entry_episodes == candidate_episodes:
        return 1.0
    if abs(entry_episodes - candidate_episodes) <= 1:
        return 0.6
    return 0.0


def candidate_score(entry: BangumiEntry, candidate: MalCandidate) -> float:
    title_score = _title_similarity(entry, candidate)
    date_score = _date_similarity(entry.air_date, candidate.start_date)
    episode_score = _episode_similarity(entry.total_episodes, candidate.num_episodes)
    score = date_score * 0.55 + title_score * 0.40 + episode_score * 0.05

    return max(0.0, min(1.0, score))


class AnimeMatcher:
    def __init__(self, client: SearchClient, threshold: float = 0.94, margin: float = 0.08):
        self.client = client
        self.threshold = threshold
        self.margin = margin
        self._season_cache: dict[tuple[int, str], tuple[MalCandidate, ...]] = {}

    def clear_cache(self) -> None:
        self._season_cache.clear()

    def match(self, entry: BangumiEntry) -> MatchResult:
        searched = self._rank(entry, self._search_candidates(entry))
        primary = self._match_ranked(searched, "automatic_search")
        if primary.candidate is not None:
            return primary

        periods = self._air_seasons(entry.air_date)
        if not periods:
            return primary

        seasonal = self._rank(entry, self._season_candidates(periods))
        fallback = self._match_ranked(seasonal, "automatic_season")
        return fallback if fallback.method != "no_candidates" else primary

    def _search_candidates(self, entry: BangumiEntry) -> tuple[MalCandidate, ...]:
        by_id: dict[int, MalCandidate] = {}
        for title in entry.search_titles[:6]:
            try:
                candidates = self.client.search_anime(_normalize_search_title(title), limit=10)
            except Exception as exc:
                LOGGER.warning("Skipping failed MAL search title %r: %s", title, exc)
                continue
            for candidate in candidates:
                by_id[candidate.anime_id] = candidate
        return tuple(by_id.values())

    def _season_candidates(
        self, periods: tuple[tuple[int, str], ...]
    ) -> tuple[MalCandidate, ...]:
        by_id: dict[int, MalCandidate] = {}
        for period in periods:
            if period not in self._season_cache:
                year, season = period
                self._season_cache[period] = tuple(
                    self.client.list_anime_by_season(year, season)
                )
            for candidate in self._season_cache[period]:
                by_id[candidate.anime_id] = candidate
        return tuple(by_id.values())

    @staticmethod
    def _rank(
        entry: BangumiEntry, candidates: tuple[MalCandidate, ...]
    ) -> tuple[MalCandidate, ...]:
        scored = (
            replace(candidate, score=candidate_score(entry, candidate))
            for candidate in candidates
        )
        return tuple(sorted(scored, key=lambda candidate: candidate.score, reverse=True))

    def _match_ranked(
        self, ranked: tuple[MalCandidate, ...], automatic_method: str
    ) -> MatchResult:
        if not ranked:
            return MatchResult(None, "no_candidates", 0.0, ())
        best = ranked[0]
        runner_up = ranked[1].score if len(ranked) > 1 else 0.0
        if best.score >= self.threshold and best.score - runner_up >= self.margin:
            return MatchResult(best, automatic_method, best.score, ranked[:5])
        return MatchResult(None, "ambiguous", best.score, ranked[:5])

    @staticmethod
    def _air_season(air_date: str) -> Optional[tuple[int, str]]:
        match = re.match(r"^(\d{4})-(\d{2})(?:-|$)", air_date)
        if not match:
            return None
        month = int(match.group(2))
        if not 1 <= month <= 12:
            return None
        seasons = ("winter", "spring", "summer", "fall")
        return int(match.group(1)), seasons[(month - 1) // 3]

    @classmethod
    def _air_seasons(cls, air_date: str) -> tuple[tuple[int, str], ...]:
        primary = cls._air_season(air_date)
        if primary is None:
            return ()
        if len(air_date) != 10:
            return (primary,)
        try:
            air_day = date.fromisoformat(air_date)
        except ValueError:
            return (primary,)

        periods: list[tuple[int, str]] = []
        for offset in (0, -1, 1):
            nearby_day = air_day + timedelta(days=offset)
            period = cls._air_season(nearby_day.isoformat())
            if period is not None and period not in periods:
                periods.append(period)
        return tuple(periods)
