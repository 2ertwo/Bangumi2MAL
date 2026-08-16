from __future__ import annotations

import getpass
import os
import secrets
import stat
import time
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Optional
from urllib.parse import parse_qs, urlparse

from dotenv import dotenv_values, set_key

from .clients import BangumiClient, MalOAuth
from .config import Settings
from .database import Database
from .runtime import build_database


BANGUMI_TOKEN_URL = "https://next.bgm.tv/demo/access-token"
MAL_CLIENT_URL = "https://myanimelist.net/apiconfig/create"
DEFAULT_BASE_URL = "http://127.0.0.1:5000"


class SetupError(RuntimeError):
    pass


@dataclass(frozen=True)
class SetupResult:
    settings: Settings
    bangumi_display_name: str
    mal_authorized: bool


def normalize_base_url(value: str) -> str:
    value = value.strip().rstrip("/")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise SetupError("Base URL must start with http:// or https://")
    if parsed.path not in {"", "/"} or parsed.params or parsed.query or parsed.fragment:
        raise SetupError("Base URL must not contain a path, query, or fragment")
    return value


def base_url_from_redirect(redirect_uri: str) -> str:
    suffix = "/oauth/mal/callback"
    if redirect_uri.endswith(suffix):
        return redirect_uri[: -len(suffix)].rstrip("/")
    return ""


def write_env_values(path: Path, values: Mapping[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(mode=0o600, exist_ok=True)
    for key, value in values.items():
        set_key(str(path), key, value, quote_mode="always")
    if os.name != "nt":
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)


def authorize_mal_interactively(
    settings: Settings,
    database: Database,
    *,
    input_func: Callable[[str], str] = input,
    opener: Callable[[str], Any] = webbrowser.open,
    open_browser: bool = True,
) -> None:
    oauth = MalOAuth(settings.mal_client_id, settings.mal_client_secret, settings.mal_redirect_uri)
    verifier = oauth.create_code_verifier()
    state = secrets.token_urlsafe(24)
    url = oauth.authorization_url(verifier, state)
    print("\nAuthorize MyAnimeList at this address:\n")
    print(url)
    if open_browser:
        try:
            opener(url)
        except Exception:
            pass
    pasted = input_func("\nPaste the full callback URL (or just the authorization code): ").strip()
    if "://" in pasted:
        query = parse_qs(urlparse(pasted).query)
        if query.get("state", [state])[0] != state:
            raise SetupError("MAL OAuth state mismatch")
        code = query.get("code", [""])[0]
    else:
        code = pasted
    if not code:
        raise SetupError("No MAL authorization code was provided")
    token = oauth.exchange_code(code, verifier)
    database.save_token(
        "mal",
        str(token["access_token"]),
        str(token.get("refresh_token") or ""),
        int(time.time()) + int(token.get("expires_in", 3600)),
    )


class SetupWizard:
    def __init__(
        self,
        env_path: Path = Path(".env"),
        *,
        input_func: Callable[[str], str] = input,
        secret_func: Callable[[str], str] = getpass.getpass,
        opener: Callable[[str], Any] = webbrowser.open,
        bangumi_client_factory: Callable[[str, str], BangumiClient] = BangumiClient,
    ):
        self.env_path = env_path
        self.input = input_func
        self.secret = secret_func
        self.opener = opener
        self.bangumi_client_factory = bangumi_client_factory

    def run(
        self,
        *,
        base_url: str = "",
        open_browser: bool = True,
        authorize_mal: bool = True,
    ) -> SetupResult:
        existing = dotenv_values(self.env_path) if self.env_path.exists() else {}

        token = self._existing(existing, "BANGUMI_ACCESS_TOKEN")
        if not token:
            self._show_page(BANGUMI_TOKEN_URL, open_browser)
            token = self.secret("Paste Bangumi access token: ").strip()
        if not token:
            raise SetupError("Bangumi access token is required")

        user_agent = self._existing(existing, "BANGUMI_USER_AGENT") or "Bangumi2MAL/0.1 (personal self-hosted sync tool)"
        bangumi = self.bangumi_client_factory(token, user_agent)
        try:
            me = bangumi.get_me()
        finally:
            bangumi.close()
        username = str(me.get("username") or "").strip()
        if not username:
            raise SetupError("Bangumi token was accepted, but /v0/me did not return a username")
        display_name = str(me.get("nickname") or username)
        print(f"Bangumi account detected: {display_name} ({username})")

        existing_redirect = self._existing(existing, "MAL_REDIRECT_URI")
        if base_url:
            selected_base_url = normalize_base_url(base_url)
        elif existing_redirect and base_url_from_redirect(existing_redirect):
            selected_base_url = base_url_from_redirect(existing_redirect)
        else:
            entered = self.input(f"Public/base URL [{DEFAULT_BASE_URL}]: ").strip()
            selected_base_url = normalize_base_url(entered or DEFAULT_BASE_URL)
        redirect_uri = f"{selected_base_url}/oauth/mal/callback"

        mal_client_id = self._existing(existing, "MAL_CLIENT_ID")
        mal_client_secret = self._existing(existing, "MAL_CLIENT_SECRET")
        if not mal_client_id:
            print(f"\nCreate a MAL API client and set its Redirect URL to:\n{redirect_uri}\n")
            self._show_page(MAL_CLIENT_URL, open_browser)
            mal_client_id = self.input("Paste MAL client ID: ").strip()
            if not mal_client_id:
                raise SetupError("MAL client ID is required")
            mal_client_secret = self.secret("Paste MAL client secret (Enter if none): ").strip()

        web_password_hash = self._existing(existing, "WEB_PASSWORD_HASH")
        if not web_password_hash:
            web_password_hash = self._new_password_hash()

        flask_secret = self._existing(existing, "FLASK_SECRET_KEY") or secrets.token_urlsafe(48)
        values = {
            "BANGUMI_USERNAME": username,
            "BANGUMI_ACCESS_TOKEN": token,
            "BANGUMI_USER_AGENT": user_agent,
            "MAL_CLIENT_ID": mal_client_id,
            "MAL_CLIENT_SECRET": mal_client_secret,
            "MAL_REDIRECT_URI": redirect_uri,
            "WEB_PASSWORD_HASH": web_password_hash,
            "FLASK_SECRET_KEY": flask_secret,
            "SESSION_COOKIE_SECURE": "true" if selected_base_url.startswith("https://") else "false",
        }
        write_env_values(self.env_path, values)
        for key, value in values.items():
            os.environ[key] = value

        settings = Settings.from_env(self.env_path)
        database = build_database(settings)
        mal_authorized = False
        if authorize_mal:
            authorize_mal_interactively(
                settings,
                database,
                input_func=self.input,
                opener=self.opener,
                open_browser=open_browser,
            )
            mal_authorized = True

        return SetupResult(settings, display_name, mal_authorized)

    def _new_password_hash(self) -> str:
        from werkzeug.security import generate_password_hash

        password = self.secret("Choose Web access password: ")
        confirmation = self.secret("Confirm Web access password: ")
        if not password or password != confirmation:
            raise SetupError("Web passwords are empty or do not match")
        return generate_password_hash(password)

    def _show_page(self, url: str, open_browser: bool) -> None:
        print(f"\n{url}\n")
        if open_browser:
            try:
                self.opener(url)
            except Exception:
                pass

    @staticmethod
    def _existing(existing: Mapping[str, Optional[str]], key: str) -> str:
        return str(os.getenv(key) or existing.get(key) or "").strip()
