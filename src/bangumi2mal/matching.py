from __future__ import annotations

import re
import unicodedata
from dataclasses import replace
from difflib import SequenceMatcher
from typing import Protocol

from .models import BangumiEntry, MalCandidate, MatchResult


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


def candidate_score(entry: BangumiEntry, candidate: MalCandidate) -> float:
    title_score = _title_similarity(entry, candidate)
    score = title_score * 0.82

    entry_year = entry.air_date[:4]
    candidate_year = candidate.start_date[:4]
    if entry_year and candidate_year:
        score += 0.10 if entry_year == candidate_year else -0.08

    if entry.total_episodes and candidate.num_episodes:
        if entry.total_episodes == candidate.num_episodes:
            score += 0.08
        elif abs(entry.total_episodes - candidate.num_episodes) <= 1:
            score += 0.03
        else:
            score -= 0.05
    elif title_score >= 0.99:
        score += 0.08

    return max(0.0, min(1.0, score))


class AnimeMatcher:
    def __init__(self, client: SearchClient, threshold: float = 0.94, margin: float = 0.08):
        self.client = client
        self.threshold = threshold
        self.margin = margin

    def match(self, entry: BangumiEntry) -> MatchResult:
        by_id: dict[int, MalCandidate] = {}
        for title in entry.search_titles[:2]:
            for candidate in self.client.search_anime(title, limit=10):
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
