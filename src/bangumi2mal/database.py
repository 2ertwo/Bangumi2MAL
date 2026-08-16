from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Optional

from .models import SyncItemResult, SyncRunResult, utc_now_iso


SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS mappings (
    bangumi_id INTEGER PRIMARY KEY,
    mal_id INTEGER NOT NULL,
    bangumi_title TEXT NOT NULL DEFAULT '',
    mal_title TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'manual',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS oauth_tokens (
    provider TEXT PRIMARY KEY,
    access_token TEXT NOT NULL,
    refresh_token TEXT NOT NULL DEFAULT '',
    expires_at INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sync_runs (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    dry_run INTEGER NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL DEFAULT '',
    total INTEGER NOT NULL DEFAULT 0,
    synced INTEGER NOT NULL DEFAULT 0,
    planned INTEGER NOT NULL DEFAULT 0,
    skipped INTEGER NOT NULL DEFAULT 0,
    unresolved INTEGER NOT NULL DEFAULT 0,
    failed INTEGER NOT NULL DEFAULT 0,
    message TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS sync_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES sync_runs(id) ON DELETE CASCADE,
    bangumi_id INTEGER NOT NULL,
    bangumi_title TEXT NOT NULL,
    mal_id INTEGER,
    mal_title TEXT NOT NULL DEFAULT '',
    bangumi_cover_url TEXT NOT NULL DEFAULT '',
    mal_cover_url TEXT NOT NULL DEFAULT '',
    match_method TEXT NOT NULL DEFAULT '',
    match_confidence REAL NOT NULL DEFAULT 0,
    result TEXT NOT NULL,
    changes_json TEXT NOT NULL DEFAULT '{}',
    candidates_json TEXT NOT NULL DEFAULT '[]',
    error TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_sync_items_run_id ON sync_items(run_id);
CREATE INDEX IF NOT EXISTS idx_sync_items_result ON sync_items(result);
"""


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(self.path), timeout=30)
        if os.name != "nt":
            self.path.chmod(0o600)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(SCHEMA)
            columns = {
                str(row["name"])
                for row in connection.execute("PRAGMA table_info(sync_items)").fetchall()
            }
            for column in ("bangumi_cover_url", "mal_cover_url"):
                if column not in columns:
                    connection.execute(
                        f"ALTER TABLE sync_items ADD COLUMN {column} TEXT NOT NULL DEFAULT ''"
                    )

    def get_mapping(self, bangumi_id: int) -> Optional[sqlite3.Row]:
        with self.connect() as connection:
            return connection.execute(
                "SELECT * FROM mappings WHERE bangumi_id = ?", (bangumi_id,)
            ).fetchone()

    def save_mapping(
        self,
        bangumi_id: int,
        mal_id: int,
        bangumi_title: str = "",
        mal_title: str = "",
        source: str = "manual",
    ) -> None:
        now = utc_now_iso()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO mappings
                    (bangumi_id, mal_id, bangumi_title, mal_title, source, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(bangumi_id) DO UPDATE SET
                    mal_id = excluded.mal_id,
                    bangumi_title = excluded.bangumi_title,
                    mal_title = excluded.mal_title,
                    source = excluded.source,
                    updated_at = excluded.updated_at
                """,
                (bangumi_id, mal_id, bangumi_title, mal_title, source, now, now),
            )

    def delete_mapping(self, bangumi_id: int) -> None:
        with self.connect() as connection:
            connection.execute("DELETE FROM mappings WHERE bangumi_id = ?", (bangumi_id,))

    def list_mappings(self) -> list[sqlite3.Row]:
        with self.connect() as connection:
            return connection.execute(
                "SELECT * FROM mappings ORDER BY updated_at DESC"
            ).fetchall()

    def save_token(
        self, provider: str, access_token: str, refresh_token: str, expires_at: int
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO oauth_tokens
                    (provider, access_token, refresh_token, expires_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(provider) DO UPDATE SET
                    access_token = excluded.access_token,
                    refresh_token = CASE
                        WHEN excluded.refresh_token = '' THEN oauth_tokens.refresh_token
                        ELSE excluded.refresh_token
                    END,
                    expires_at = excluded.expires_at,
                    updated_at = excluded.updated_at
                """,
                (provider, access_token, refresh_token, expires_at, utc_now_iso()),
            )

    def get_token(self, provider: str) -> Optional[sqlite3.Row]:
        with self.connect() as connection:
            return connection.execute(
                "SELECT * FROM oauth_tokens WHERE provider = ?", (provider,)
            ).fetchone()

    def create_run(self, run_id: str, source: str, dry_run: bool, started_at: str) -> None:
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO sync_runs (id, source, dry_run, status, started_at) VALUES (?, ?, ?, 'running', ?)",
                (run_id, source, int(dry_run), started_at),
            )

    def finish_run(self, run: SyncRunResult) -> None:
        counts = run.counts
        with self.connect() as connection:
            connection.execute("DELETE FROM sync_items WHERE run_id = ?", (run.run_id,))
            connection.executemany(
                """
                INSERT INTO sync_items
                    (run_id, bangumi_id, bangumi_title, mal_id, mal_title,
                     bangumi_cover_url, mal_cover_url, match_method, match_confidence, result, changes_json,
                     candidates_json, error)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        run.run_id,
                        item.bangumi_id,
                        item.bangumi_title,
                        item.mal_id,
                        item.mal_title,
                        item.bangumi_cover_url,
                        item.mal_cover_url,
                        item.match_method,
                        item.match_confidence,
                        item.result,
                        json.dumps(item.changes, ensure_ascii=False),
                        json.dumps(item.candidates, ensure_ascii=False),
                        item.error,
                    )
                    for item in run.items
                ],
            )
            connection.execute(
                """
                UPDATE sync_runs SET status = ?, finished_at = ?, total = ?, synced = ?,
                    planned = ?, skipped = ?, unresolved = ?, failed = ?, message = ?
                WHERE id = ?
                """,
                (
                    run.status,
                    run.finished_at,
                    counts["total"],
                    counts["synced"],
                    counts["planned"],
                    counts["skipped"],
                    counts["unresolved"],
                    counts["failed"],
                    run.message,
                    run.run_id,
                ),
            )

    def mark_run_failed(self, run_id: str, message: str) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE sync_runs SET status = 'failed', finished_at = ?, message = ? WHERE id = ?",
                (utc_now_iso(), message, run_id),
            )

    def list_runs(self, limit: int = 50) -> list[sqlite3.Row]:
        with self.connect() as connection:
            return connection.execute(
                "SELECT * FROM sync_runs ORDER BY started_at DESC LIMIT ?", (limit,)
            ).fetchall()

    def get_run(self, run_id: str) -> Optional[sqlite3.Row]:
        with self.connect() as connection:
            return connection.execute("SELECT * FROM sync_runs WHERE id = ?", (run_id,)).fetchone()

    def get_run_items(self, run_id: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """SELECT * FROM sync_items
                WHERE run_id = ?
                ORDER BY CASE result
                    WHEN 'unresolved' THEN 0
                    WHEN 'failed' THEN 1
                    ELSE 2
                END, id""",
                (run_id,),
            ).fetchall()
        items: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["changes"] = json.loads(item.pop("changes_json"))
            item["candidates"] = json.loads(item.pop("candidates_json"))
            items.append(item)
        return items

    def get_item(self, item_id: int) -> Optional[dict[str, Any]]:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM sync_items WHERE id = ?", (item_id,)).fetchone()
        if row is None:
            return None
        item = dict(row)
        item["changes"] = json.loads(item.pop("changes_json"))
        item["candidates"] = json.loads(item.pop("candidates_json"))
        return item

    def has_running_run(self) -> bool:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM sync_runs WHERE status = 'running' LIMIT 1"
            ).fetchone()
            return row is not None
