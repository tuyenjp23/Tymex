from datetime import datetime, timezone

import pytest

from app.config import Settings
from app.database.db import Database
from app.database.repository import Repository

NOW = datetime(2025, 11, 20, 10, 0, tzinfo=timezone.utc)


@pytest.fixture
def now():
    return NOW


@pytest.fixture
def repo(tmp_path):
    db = Database(tmp_path / "test.db")
    db.init()
    return Repository(db)


@pytest.fixture
def settings(tmp_path):
    return Settings(database_path=tmp_path / "app.db", env_path=tmp_path / ".env", football_data_api_key="",
                    league_codes=["TST"], auto_sync_minutes=0)


def mk(id, date, home, away, hs=None, as_=None, status="FINISHED", league="Liga Test"):
    """Dựng nhanh một dòng trận đấu (dữ liệu kiểm thử) cho các hàm thống kê thuần."""
    return {"id": id, "utc_date": date, "status": status, "home_team_id": home, "away_team_id": away,
            "home_name": f"T{home}", "away_name": f"T{away}", "home_score": hs, "away_score": as_, "league_name": league}
