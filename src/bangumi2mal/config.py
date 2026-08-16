from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv


def _as_bool(value: Optional[str], default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    bangumi_username: str
    bangumi_access_token: str
    bangumi_user_agent: str
    mal_client_id: str
    mal_client_secret: str
    mal_redirect_uri: str
    web_password_hash: str
    flask_secret_key: str
    database_path: Path
    reports_dir: Path
    log_level: str
    auto_sync_enabled: bool
    auto_sync_hours: int
    mal_write_delay_seconds: float
    auto_match_threshold: float
    auto_match_margin: float
    allow_decrease_watched: bool
    session_cookie_secure: bool
    incremental_sync_minutes: int = 10
    rss_poll_minutes: int = 5

    @classmethod
    def from_env(cls, env_file: Optional[Path] = None) -> "Settings":
        load_dotenv(dotenv_path=env_file, override=False)
        return cls(
            bangumi_username=os.getenv("BANGUMI_USERNAME", "").strip(),
            bangumi_access_token=os.getenv("BANGUMI_ACCESS_TOKEN", "").strip(),
            bangumi_user_agent=os.getenv(
                "BANGUMI_USER_AGENT",
                "Bangumi2MAL/0.1 (personal self-hosted sync tool)",
            ).strip(),
            mal_client_id=os.getenv("MAL_CLIENT_ID", "").strip(),
            mal_client_secret=os.getenv("MAL_CLIENT_SECRET", "").strip(),
            mal_redirect_uri=os.getenv(
                "MAL_REDIRECT_URI", "http://127.0.0.1:5000/oauth/mal/callback"
            ).strip(),
            web_password_hash=os.getenv("WEB_PASSWORD_HASH", "").strip(),
            flask_secret_key=os.getenv("FLASK_SECRET_KEY", "").strip(),
            database_path=Path(os.getenv("DATABASE_PATH", "data/app.db")),
            reports_dir=Path(os.getenv("REPORTS_DIR", "reports")),
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
            auto_sync_enabled=_as_bool(os.getenv("AUTO_SYNC_ENABLED")),
            auto_sync_hours=max(
                1,
                int(os.getenv("FULL_SYNC_HOURS", os.getenv("AUTO_SYNC_HOURS", "24"))),
            ),
            incremental_sync_minutes=max(
                1, int(os.getenv("INCREMENTAL_SYNC_MINUTES", "10"))
            ),
            rss_poll_minutes=max(1, int(os.getenv("RSS_POLL_MINUTES", "5"))),
            mal_write_delay_seconds=max(
                0.0, float(os.getenv("MAL_WRITE_DELAY_SECONDS", "1.0"))
            ),
            auto_match_threshold=float(os.getenv("AUTO_MATCH_THRESHOLD", "0.94")),
            auto_match_margin=float(os.getenv("AUTO_MATCH_MARGIN", "0.08")),
            allow_decrease_watched=_as_bool(os.getenv("ALLOW_DECREASE_WATCHED")),
            session_cookie_secure=_as_bool(os.getenv("SESSION_COOKIE_SECURE")),
        )

    def ensure_directories(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.reports_dir.mkdir(parents=True, exist_ok=True)

    def configuration_errors(self, require_web: bool = False) -> list[str]:
        errors: list[str] = []
        required = {
            "BANGUMI_USERNAME": self.bangumi_username,
            "BANGUMI_ACCESS_TOKEN": self.bangumi_access_token,
            "MAL_CLIENT_ID": self.mal_client_id,
        }
        if require_web:
            required.update(
                {
                    "WEB_PASSWORD_HASH": self.web_password_hash,
                    "FLASK_SECRET_KEY": self.flask_secret_key,
                }
            )
        errors.extend(f"{name} is not configured" for name, value in required.items() if not value)
        if not 0.0 <= self.auto_match_threshold <= 1.0:
            errors.append("AUTO_MATCH_THRESHOLD must be between 0 and 1")
        if not 0.0 <= self.auto_match_margin <= 1.0:
            errors.append("AUTO_MATCH_MARGIN must be between 0 and 1")
        return errors
