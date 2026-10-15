"""Cấu hình ứng dụng: đọc từ biến môi trường / file .env. Không chứa logic nghiệp vụ."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BASE_DIR / ".env"
DEFAULT_LEAGUES = ["PL", "PD", "BL1", "SA", "FL1"]


def _bool(value: str | None, default: bool) -> bool:
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int(value: str | None, default: int) -> int:
    try:
        return int(value) if value not in (None, "") else default
    except ValueError:
        return default


@dataclass
class Settings:
    football_data_api_key: str = ""
    anthropic_api_key: str = ""
    ai_model: str = "claude-sonnet-5-5"
    database_path: Path = BASE_DIR / "data" / "football.db"
    default_timezone: str = "Asia/Tokyo"
    league_codes: list[str] = field(default_factory=lambda: list(DEFAULT_LEAGUES))
    sync_previous_season: bool = True
    min_sync_interval_minutes: int = 15
    auto_sync_minutes: int = 180
    rate_limit_per_minute: int = 10
    request_timeout: float = 20.0
    env_path: Path = ENV_PATH

    @property
    def has_football_key(self) -> bool:
        return bool(self.football_data_api_key.strip())

    @property
    def ai_configured(self) -> bool:
        return bool(self.anthropic_api_key.strip())


def load_settings(env_path: Path = ENV_PATH) -> Settings:
    load_dotenv(env_path, override=False)
    env = os.environ
    db_path = Path(env.get("DATABASE_PATH") or "data/football.db")
    if not db_path.is_absolute():
        db_path = BASE_DIR / db_path
    leagues = [c.strip().upper() for c in (env.get("LEAGUES") or "").split(",") if c.strip()]
    return Settings(
        football_data_api_key=env.get("FOOTBALL_DATA_API_KEY", "").strip(),
        anthropic_api_key=env.get("ANTHROPIC_API_KEY", "").strip(),
        ai_model=env.get("AI_MODEL", "claude-sonnet-5-5").strip() or "claude-sonnet-5-5",
        database_path=db_path,
        default_timezone=env.get("DEFAULT_TIMEZONE", "Asia/Tokyo").strip() or "Asia/Tokyo",
        league_codes=leagues or list(DEFAULT_LEAGUES),
        sync_previous_season=_bool(env.get("SYNC_PREVIOUS_SEASON"), True),
        min_sync_interval_minutes=_int(env.get("MIN_SYNC_INTERVAL_MINUTES"), 15),
        auto_sync_minutes=_int(env.get("AUTO_SYNC_MINUTES"), 180),
        rate_limit_per_minute=max(1, _int(env.get("RATE_LIMIT_PER_MINUTE"), 10)),
        env_path=env_path,
    )


def set_env_value(env_path: Path, key: str, value: str) -> None:
    """Ghi/cập nhật một dòng KEY=VALUE trong .env, giữ nguyên các dòng khác."""
    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    prefix = f"{key}="
    for i, line in enumerate(lines):
        if line.strip().startswith(prefix):
            lines[i] = f"{key}={value}"
            break
    else:
        lines.append(f"{key}={value}")
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
