"""Danh sách giải có dữ liệu lịch sử và cách ánh xạ sang mã của từng nguồn.

`code` trùng mã football-data.org để dữ liệu lịch sử nhập vào CHÍNH giải đó (mô hình dùng chung một giải).
Các giải hạng 2 (BL2, SB, SD) không có trong gói miễn phí của football-data.org nên được tạo mới chỉ để chứa lịch sử.
"""
from __future__ import annotations

MAIN_PROVIDER = "football-data.org"   # trùng FootballDataOrgProvider.name

HIST_LEAGUES: list[dict] = [
    {"code": "PL",  "name": "Premier League",  "country": "England", "co_uk": "E0",  "openfootball": "en.1", "tz": "Europe/London"},
    {"code": "ELC", "name": "Championship",    "country": "England", "co_uk": "E1",  "openfootball": "en.2", "tz": "Europe/London"},
    {"code": "PD",  "name": "Primera Division", "country": "Spain",  "co_uk": "SP1", "openfootball": "es.1", "tz": "Europe/Madrid"},
    {"code": "SD",  "name": "Segunda Division", "country": "Spain",  "co_uk": "SP2", "openfootball": "es.2", "tz": "Europe/Madrid"},
    {"code": "BL1", "name": "Bundesliga",       "country": "Germany", "co_uk": "D1", "openfootball": "de.1", "tz": "Europe/Berlin"},
    {"code": "BL2", "name": "2. Bundesliga",    "country": "Germany", "co_uk": "D2", "openfootball": "de.2", "tz": "Europe/Berlin"},
    {"code": "SA",  "name": "Serie A",          "country": "Italy",   "co_uk": "I1", "openfootball": "it.1", "tz": "Europe/Rome"},
    {"code": "SB",  "name": "Serie B",          "country": "Italy",   "co_uk": "I2", "openfootball": "it.2", "tz": "Europe/Rome"},
    {"code": "FL1", "name": "Ligue 1",          "country": "France",  "co_uk": "F1", "openfootball": "fr.1", "tz": "Europe/Paris"},
]
BY_CODE = {x["code"]: x for x in HIST_LEAGUES}


def season_start_year(today) -> int:
    """Mùa giải châu Âu bắt đầu khoảng tháng 8: từ tháng 7 trở đi tính là mùa mới."""
    return today.year if today.month >= 7 else today.year - 1
