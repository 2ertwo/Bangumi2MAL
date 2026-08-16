from __future__ import annotations

from dataclasses import replace
from typing import Any

from ..models import BangumiEntry
from .base import BaseApiClient


class BangumiClient(BaseApiClient):
    def __init__(self, access_token: str, user_agent: str):
        headers = {
            "Accept": "application/json",
            "User-Agent": user_agent,
        }
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"
        super().__init__("https://api.bgm.tv", headers)

    def get_me(self) -> dict[str, Any]:
        return self.request("GET", "/v0/me").json()

    def get_user(self, username: str) -> dict[str, Any]:
        return self.request("GET", f"/v0/users/{username}").json()

    def get_subject(self, subject_id: int) -> dict[str, Any]:
        return self.request("GET", f"/v0/subjects/{subject_id}").json()

    def enrich_entry(self, entry: BangumiEntry) -> BangumiEntry:
        subject = self.get_subject(entry.subject_id)
        images = subject.get("images") or {}
        aliases = tuple(
            dict.fromkeys((*entry.aliases, *self._parse_aliases(subject.get("infobox") or [])))
        )
        return replace(
            entry,
            title=str(subject.get("name") or entry.title),
            title_cn=str(subject.get("name_cn") or entry.title_cn),
            total_episodes=int(
                subject.get("total_episodes") or subject.get("eps") or entry.total_episodes
            ),
            air_date=str(subject.get("date") or entry.air_date),
            cover_url=str(
                images.get("large")
                or images.get("common")
                or images.get("medium")
                or entry.cover_url
            ),
            aliases=aliases,
        )

    @staticmethod
    def _parse_aliases(infobox: list[dict[str, Any]]) -> tuple[str, ...]:
        alias_keys = {
            "别名",
            "別名",
            "别称",
            "別稱",
            "alias",
            "aliases",
            "英文名",
            "日文名",
            "原名",
        }
        aliases: list[str] = []
        for field in infobox:
            if str(field.get("key") or "").strip().casefold() not in alias_keys:
                continue
            value = field.get("value")
            items = value if isinstance(value, list) else [value]
            for item in items:
                text = (item.get("v") or item.get("value")) if isinstance(item, dict) else item
                if text and str(text).strip():
                    aliases.append(str(text).strip())
        return tuple(dict.fromkeys(aliases))

    def get_anime_collections(self, username: str) -> list[BangumiEntry]:
        entries: list[BangumiEntry] = []
        offset = 0
        limit = 50
        while True:
            response = self.request(
                "GET",
                f"/v0/users/{username}/collections",
                params={"subject_type": 2, "limit": limit, "offset": offset},
            ).json()
            data = response.get("data", [])
            entries.extend(self._parse_entry(item) for item in data)
            offset += len(data)
            total = int(response.get("total", offset))
            if not data or offset >= total:
                break
        return entries

    @staticmethod
    def _parse_entry(item: dict[str, Any]) -> BangumiEntry:
        subject = item.get("subject") or {}
        images = subject.get("images") or {}
        aliases = BangumiClient._parse_aliases(subject.get("infobox") or [])
        return BangumiEntry(
            subject_id=int(item.get("subject_id") or subject.get("id")),
            title=str(subject.get("name") or ""),
            title_cn=str(subject.get("name_cn") or ""),
            collection_type=int(item.get("type") or 0),
            score=int(item.get("rate") or 0),
            watched_episodes=int(item.get("ep_status") or 0),
            total_episodes=int(subject.get("eps") or 0),
            air_date=str(subject.get("date") or ""),
            updated_at=str(item.get("updated_at") or ""),
            cover_url=str(
                images.get("large") or images.get("common") or images.get("medium") or ""
            ),
            aliases=aliases,
        )
