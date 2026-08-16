from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass(frozen=True)
class BangumiEntry:
    subject_id: int
    title: str
    title_cn: str
    collection_type: int
    score: int
    watched_episodes: int
    total_episodes: int
    air_date: str = ""
    updated_at: str = ""
    cover_url: str = ""

    @property
    def search_titles(self) -> list[str]:
        values = [self.title, self.title_cn]
        return list(dict.fromkeys(value.strip() for value in values if value and value.strip()))


@dataclass(frozen=True)
class MalCandidate:
    anime_id: int
    title: str
    alternative_titles: tuple[str, ...] = ()
    media_type: str = ""
    start_date: str = ""
    num_episodes: int = 0
    score: float = 0.0
    cover_url: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "anime_id": self.anime_id,
            "title": self.title,
            "alternative_titles": list(self.alternative_titles),
            "media_type": self.media_type,
            "start_date": self.start_date,
            "num_episodes": self.num_episodes,
            "score": round(self.score, 4),
            "cover_url": self.cover_url,
        }


@dataclass(frozen=True)
class MatchResult:
    candidate: Optional[MalCandidate]
    method: str
    confidence: float
    candidates: tuple[MalCandidate, ...] = ()


@dataclass
class SyncItemResult:
    bangumi_id: int
    bangumi_title: str
    mal_id: Optional[int]
    mal_title: str
    match_method: str
    match_confidence: float
    result: str
    bangumi_cover_url: str = ""
    mal_cover_url: str = ""
    changes: dict[str, Any] = field(default_factory=dict)
    candidates: list[dict[str, Any]] = field(default_factory=list)
    error: str = ""


@dataclass
class SyncRunResult:
    run_id: str
    dry_run: bool
    started_at: str
    finished_at: str = ""
    status: str = "running"
    items: list[SyncItemResult] = field(default_factory=list)
    message: str = ""

    @property
    def counts(self) -> dict[str, int]:
        values = {"total": len(self.items), "synced": 0, "planned": 0, "skipped": 0, "unresolved": 0, "failed": 0}
        for item in self.items:
            if item.result in values:
                values[item.result] += 1
        return values
