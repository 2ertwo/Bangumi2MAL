from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any

from .database import Database
from .matching import AnimeMatcher
from .models import BangumiEntry, SyncItemResult, SyncRunResult, utc_now_iso


LOGGER = logging.getLogger(__name__)
SYNC_LOCK = threading.Lock()

BANGUMI_TO_MAL_STATUS = {
    1: "plan_to_watch",
    2: "completed",
    3: "watching",
    4: "on_hold",
    5: "dropped",
}

AUTOMATIC_MAPPING_SOURCE = "automatic_date_v2"



class SyncAlreadyRunning(RuntimeError):
    pass


class SyncService:
    def __init__(
        self,
        database: Database,
        bangumi_client: Any,
        mal_client: Any,
        matcher: AnimeMatcher,
        username: str,
        write_delay_seconds: float = 1.0,
        allow_decrease_watched: bool = False,
    ):
        self.database = database
        self.bangumi_client = bangumi_client
        self.mal_client = mal_client
        self.matcher = matcher
        self.username = username
        self.write_delay_seconds = write_delay_seconds
        self.allow_decrease_watched = allow_decrease_watched

    def run(self, dry_run: bool = False, source: str = "cli") -> SyncRunResult:
        if not SYNC_LOCK.acquire(blocking=False):
            raise SyncAlreadyRunning("another sync is already running")
        run_id = f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
        run = SyncRunResult(run_id=run_id, dry_run=dry_run, started_at=utc_now_iso())
        self.database.create_run(run_id, source, dry_run, run.started_at)
        try:
            entries = self.bangumi_client.get_anime_collections(self.username)
            for entry in entries:
                run.items.append(self._sync_entry(entry, dry_run))
            run.status = "partial" if any(item.result == "failed" for item in run.items) else "completed"
            run.finished_at = utc_now_iso()
            self.database.finish_run(run)
            return run
        except Exception as exc:
            LOGGER.exception("Sync run %s failed", run_id)
            run.status = "failed"
            run.finished_at = utc_now_iso()
            run.message = str(exc)
            self.database.finish_run(run)
            raise
        finally:
            SYNC_LOCK.release()

    def _sync_entry(self, entry: BangumiEntry, dry_run: bool) -> SyncItemResult:
        try:
            mapping = self.database.get_mapping(entry.subject_id)
            if mapping and str(mapping["source"]) not in {"manual", AUTOMATIC_MAPPING_SOURCE}:
                self.database.delete_mapping(entry.subject_id)
                mapping = None
            match_method = "saved_mapping"
            confidence = 1.0
            candidates: list[dict[str, Any]] = []
            if mapping:
                mal_id = int(mapping["mal_id"])
                anime = self.mal_client.get_anime(mal_id)
            else:
                enrich_entry = getattr(self.bangumi_client, "enrich_entry", None)
                if callable(enrich_entry):
                    try:
                        entry = enrich_entry(entry)
                    except Exception as exc:
                        LOGGER.warning(
                            "Could not load aliases for Bangumi subject %s: %s",
                            entry.subject_id, exc,
                        )
                matched = self.matcher.match(entry)
                candidates = [candidate.to_dict() for candidate in matched.candidates]
                if matched.candidate is None:
                    return SyncItemResult(
                        bangumi_id=entry.subject_id,
                        bangumi_title=entry.title_cn or entry.title,
                        mal_id=None,
                        mal_title="",
                        match_method=matched.method,
                        match_confidence=matched.confidence,
                        result="unresolved",
                        bangumi_cover_url=entry.cover_url,
                        candidates=candidates,
                        error="No unambiguous MAL match was found",
                    )
                candidate = matched.candidate
                mal_id = candidate.anime_id
                match_method = matched.method
                confidence = matched.confidence
                anime = self.mal_client.get_anime(mal_id)
                self.database.save_mapping(
                    entry.subject_id,
                    mal_id,
                    entry.title_cn or entry.title,
                    str(anime.get("title") or candidate.title),
                    source=AUTOMATIC_MAPPING_SOURCE,
                )

            changes = self._calculate_changes(entry, anime)
            result = SyncItemResult(
                bangumi_id=entry.subject_id,
                bangumi_title=entry.title_cn or entry.title,
                mal_id=mal_id,
                mal_title=str(anime.get("title") or ""),
                match_method=match_method,
                match_confidence=confidence,
                result="skipped",
                bangumi_cover_url=entry.cover_url,
                mal_cover_url=str(
                    (anime.get("main_picture") or {}).get("medium") or (anime.get("main_picture") or {}).get("large") or ""
                ),
                changes=changes,
                candidates=candidates,
            )
            if not changes:
                return result
            if dry_run:
                result.result = "planned"
                return result
            self.mal_client.update_list_status(mal_id, changes)
            result.result = "synced"
            if self.write_delay_seconds:
                time.sleep(self.write_delay_seconds)
            return result
        except Exception as exc:
            LOGGER.warning("Failed to sync Bangumi subject %s: %s", entry.subject_id, exc)
            return SyncItemResult(
                bangumi_id=entry.subject_id,
                bangumi_title=entry.title_cn or entry.title,
                mal_id=None,
                mal_title="",
                match_method="error",
                match_confidence=0.0,
                result="failed",
                bangumi_cover_url=entry.cover_url,
                error=str(exc),
            )

    def _calculate_changes(self, entry: BangumiEntry, anime: dict[str, Any]) -> dict[str, Any]:
        desired_status = BANGUMI_TO_MAL_STATUS.get(entry.collection_type)
        if not desired_status:
            raise ValueError(f"Unsupported Bangumi collection type: {entry.collection_type}")
        current = anime.get("my_list_status") or {}
        changes: dict[str, Any] = {}
        if current.get("status") != desired_status:
            changes["status"] = desired_status
        if entry.score > 0 and int(current.get("score") or 0) != entry.score:
            changes["score"] = entry.score
        current_episodes = int(current.get("num_episodes_watched") or 0)
        desired_episodes = entry.watched_episodes
        total_episodes = int(anime.get("num_episodes") or 0)
        if total_episodes:
            desired_episodes = min(desired_episodes, total_episodes)
        if not self.allow_decrease_watched:
            desired_episodes = max(desired_episodes, current_episodes)
        if desired_episodes != current_episodes:
            changes["num_watched_episodes"] = desired_episodes
        return changes
