from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import replace
from difflib import SequenceMatcher
from typing import Protocol

from .models import BangumiEntry, MalCandidate, MatchResult


LOGGER = logging.getLogger(__name__)


class SearchClient(Protocol):
    def search_anime(self, query: str, limit: int = 10) -> list[MalCandidate]: ...


def normalize_title(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
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

    def match(self, entry: BangumiEntry) -> MatchResult:
        by_id: dict[int, MalCandidate] = {}
        for title in entry.search_titles[:6]:
            try:
                candidates = self.client.search_anime(title, limit=10)
            except Exception as exc:
                LOGGER.warning("Skipping failed MAL search title %r: %s", title, exc)
                continue
            for candidate in candidates:
                by_id[candidate.anime_id] = candidate

        ranked = sorted(
            (replace(candidate, score=candidate_score(entry, candidate)) for candidate in by_id.values()),
            key=lambda candidate: candidate.score,
            reverse=True,
        )
        if not ranked:
            return MatchResult(None, "no_candidates", 0.0, ())

        best = ranked[0]
        runner_up = ranked[1].score if len(ranked) > 1 else 0.0
        if best.score >= self.threshold and best.score - runner_up >= self.margin:
            return MatchResult(best, "automatic", best.score, tuple(ranked[:5]))
        return MatchResult(None, "ambiguous", best.score, tuple(ranked[:5]))
