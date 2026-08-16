from __future__ import annotations

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
        )
