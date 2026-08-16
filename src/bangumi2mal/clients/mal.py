from __future__ import annotations

import secrets
import time
from typing import Any, Callable, Optional
from urllib.parse import urlencode

import httpx

from ..models import MalCandidate
from .base import ApiError, BaseApiClient


class MalOAuth:
    AUTHORIZE_URL = "https://myanimelist.net/v1/oauth2/authorize"
    TOKEN_URL = "https://myanimelist.net/v1/oauth2/token"

    def __init__(self, client_id: str, client_secret: str, redirect_uri: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri

    @staticmethod
    def create_code_verifier() -> str:
        # MAL currently documents the plain PKCE challenge method.
        return secrets.token_urlsafe(64)[:96]

    def authorization_url(self, code_verifier: str, state: str) -> str:
        return f"{self.AUTHORIZE_URL}?{urlencode({'response_type': 'code', 'client_id': self.client_id, 'code_challenge': code_verifier, 'code_challenge_method': 'plain', 'state': state, 'redirect_uri': self.redirect_uri})}"

    def exchange_code(self, code: str, code_verifier: str) -> dict[str, Any]:
        data = {
            "client_id": self.client_id,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.redirect_uri,
            "code_verifier": code_verifier,
        }
        if self.client_secret:
            data["client_secret"] = self.client_secret
        return self._token_request(data)

    def refresh(self, refresh_token: str) -> dict[str, Any]:
        data = {
            "client_id": self.client_id,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }
        if self.client_secret:
            data["client_secret"] = self.client_secret
        return self._token_request(data)

    @classmethod
    def _token_request(cls, data: dict[str, str]) -> dict[str, Any]:
        try:
            response = httpx.post(cls.TOKEN_URL, data=data, timeout=30.0)
        except httpx.RequestError as exc:
            raise ApiError(f"MAL OAuth request failed: {exc}") from exc
        if response.status_code >= 400:
            try:
                detail = response.json()
            except ValueError:
                detail = response.text[:300]
            raise ApiError(f"MAL OAuth failed ({response.status_code}): {detail}")
        return response.json()


class MalClient(BaseApiClient):
    SEARCH_FIELDS = "id,title,alternative_titles,main_picture,media_type,start_date,num_episodes,my_list_status"

    def __init__(
        self,
        client_id: str,
        token_loader: Callable[[], Optional[dict[str, Any]]],
        token_saver: Callable[[str, str, int], None],
        oauth: MalOAuth,
    ):
        self.client_id = client_id
        self.token_loader = token_loader
        self.token_saver = token_saver
        self.oauth = oauth
        super().__init__("https://api.myanimelist.net/v2")

    def _access_token(self) -> str:
        token = self.token_loader()
        if not token:
            raise ApiError("MAL is not authorized; run 'bangumi2mal auth-mal' first")
        if int(token.get("expires_at", 0)) <= int(time.time()) + 60:
            refresh_token = str(token.get("refresh_token") or "")
            if not refresh_token:
                raise ApiError("MAL access token expired and no refresh token is available")
            refreshed = self.oauth.refresh(refresh_token)
            expires_at = int(time.time()) + int(refreshed.get("expires_in", 3600))
            self.token_saver(
                str(refreshed["access_token"]),
                str(refreshed.get("refresh_token") or refresh_token),
                expires_at,
            )
            token = self.token_loader()
        return str(token["access_token"])

    def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        headers = dict(kwargs.pop("headers", {}))
        headers["Authorization"] = f"Bearer {self._access_token()}"
        headers["X-MAL-CLIENT-ID"] = self.client_id
        return super().request(method, url, headers=headers, **kwargs)

    def get_me(self) -> dict[str, Any]:
        return self.request("GET", "/users/@me").json()

    def search_anime(self, query: str, limit: int = 10) -> list[MalCandidate]:
        payload = self.request(
            "GET",
            "/anime",
            params={"q": query, "limit": min(limit, 20), "fields": self.SEARCH_FIELDS},
        ).json()
        return [self._candidate_from_node(row.get("node") or {}) for row in payload.get("data", [])]

    def get_anime(self, anime_id: int) -> dict[str, Any]:
        return self.request(
            "GET", f"/anime/{anime_id}", params={"fields": self.SEARCH_FIELDS}
        ).json()

    def update_list_status(self, anime_id: int, changes: dict[str, Any]) -> dict[str, Any]:
        return self.request(
            "PATCH", f"/anime/{anime_id}/my_list_status", data=changes
        ).json()

    @staticmethod
    def _candidate_from_node(node: dict[str, Any]) -> MalCandidate:
        alternatives = node.get("alternative_titles") or {}
        picture = node.get("main_picture") or {}
        titles: list[str] = []
        for key in ("ja", "en"):
            if alternatives.get(key):
                titles.append(str(alternatives[key]))
        titles.extend(str(value) for value in alternatives.get("synonyms", []) if value)
        return MalCandidate(
            anime_id=int(node.get("id") or 0),
            title=str(node.get("title") or ""),
            alternative_titles=tuple(dict.fromkeys(titles)),
            media_type=str(node.get("media_type") or ""),
            start_date=str(node.get("start_date") or ""),
            num_episodes=int(node.get("num_episodes") or 0),
            cover_url=str(picture.get("medium") or picture.get("large") or ""),
        )
