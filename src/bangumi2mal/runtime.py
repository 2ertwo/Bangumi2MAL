from __future__ import annotations

from typing import Any, Optional

from .clients import BangumiClient, MalClient, MalOAuth
from .config import Settings
from .database import Database
from .matching import AnimeMatcher
from .sync_service import SyncService


def build_database(settings: Settings) -> Database:
    settings.ensure_directories()
    database = Database(settings.database_path)
    database.initialize()
    return database


def build_mal_client(settings: Settings, database: Database) -> MalClient:
    oauth = MalOAuth(settings.mal_client_id, settings.mal_client_secret, settings.mal_redirect_uri)

    def load_token() -> Optional[dict[str, Any]]:
        row = database.get_token("mal")
        return dict(row) if row else None

    def save_token(access_token: str, refresh_token: str, expires_at: int) -> None:
        database.save_token("mal", access_token, refresh_token, expires_at)

    return MalClient(settings.mal_client_id, load_token, save_token, oauth)


def build_sync_service(settings: Settings, database: Database) -> SyncService:
    bangumi = BangumiClient(settings.bangumi_access_token, settings.bangumi_user_agent)
    mal = build_mal_client(settings, database)
    matcher = AnimeMatcher(mal, settings.auto_match_threshold, settings.auto_match_margin)
    return SyncService(
        database=database,
        bangumi_client=bangumi,
        mal_client=mal,
        matcher=matcher,
        username=settings.bangumi_username,
        write_delay_seconds=settings.mal_write_delay_seconds,
        allow_decrease_watched=settings.allow_decrease_watched,
    )
