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
    # ---- mở rộng: các hạng khác của châu Âu (mã DED/PPL/BSA trùng football-data.org để dùng chung giải)
    {"code": "EL1", "name": "League One",       "country": "England", "co_uk": "E2", "openfootball": "en.3", "tz": "Europe/London"},
    {"code": "EL2", "name": "League Two",       "country": "England", "co_uk": "E3", "openfootball": "en.4", "tz": "Europe/London"},
    {"code": "FL2", "name": "Ligue 2",          "country": "France",  "co_uk": "F2", "openfootball": "fr.2", "tz": "Europe/Paris"},
    {"code": "DED", "name": "Eredivisie",       "country": "Netherlands", "co_uk": "N1", "openfootball": "nl.1", "tz": "Europe/Amsterdam"},
    {"code": "PPL", "name": "Primeira Liga",    "country": "Portugal", "co_uk": "P1", "openfootball": "pt.1", "tz": "Europe/Lisbon"},
    {"code": "BE1", "name": "Jupiler Pro League", "country": "Belgium", "co_uk": "B1", "openfootball": "be.1", "tz": "Europe/Brussels"},
    {"code": "TR1", "name": "Süper Lig",        "country": "Turkey",  "co_uk": "T1", "openfootball": "tr.1", "tz": "Europe/Istanbul"},
    {"code": "SC0", "name": "Scottish Premiership", "country": "Scotland", "co_uk": "SC0", "openfootball": "sco.1", "tz": "Europe/London"},
    {"code": "GR1", "name": "Super League Greece", "country": "Greece", "co_uk": "G1", "openfootball": "gr.1", "tz": "Europe/Athens"},
    {"code": "AT1", "name": "Austrian Bundesliga", "country": "Austria", "co_uk": None, "openfootball": "at.1", "tz": "Europe/Vienna"},
    {"code": "AT2", "name": "2. Liga Austria",  "country": "Austria", "co_uk": None, "openfootball": "at.2", "tz": "Europe/Vienna"},
    # ---- châu Á và châu Mỹ: mùa theo năm dương lịch, thư mục openfootball là "2025" (không phải "2025-26")
    {"code": "JP1", "name": "J1 League",        "country": "Japan",   "co_uk": None, "openfootball": "jp.1", "tz": "Asia/Tokyo", "calendar": True, "co_uk_new": "JPN", "espn": "jpn.1"},
    {"code": "CN1", "name": "Chinese Super League", "country": "China", "co_uk": None, "openfootball": "cn.1", "tz": "Asia/Shanghai", "calendar": True, "co_uk_new": "CHN", "espn": "chn.1"},
    {"code": "BSA", "name": "Brasileirão Série A", "country": "Brazil", "co_uk": None, "openfootball": "br.1", "tz": "America/Sao_Paulo", "calendar": True, "co_uk_new": "BRA", "espn": "bra.1"},
    {"code": "BR2", "name": "Brasileirão Série B", "country": "Brazil", "co_uk": None, "openfootball": "br.2", "tz": "America/Sao_Paulo", "calendar": True},
    {"code": "AR1", "name": "Argentina Primera División", "country": "Argentina", "co_uk": None, "openfootball": "ar.1", "tz": "America/Argentina/Buenos_Aires", "calendar": True, "co_uk_new": "ARG", "espn": "arg.1"},
    {"code": "CO1", "name": "Colombia Primera A", "country": "Colombia", "co_uk": None, "openfootball": "co.1", "tz": "America/Bogota", "calendar": True, "espn": "col.1"},
    # ---- mở rộng nguồn 2: ESPN (kết quả + lịch sắp đá) và football-data.co.uk/new (kèm tỷ lệ cược)
    {"code": "KR1", "name": "K League 1",       "country": "South Korea", "co_uk": None, "openfootball": None, "tz": "Asia/Seoul", "calendar": True, "espn": "kor.1"},
    {"code": "AU1", "name": "A-League Men",     "country": "Australia", "co_uk": None, "openfootball": None, "tz": "Australia/Sydney", "espn": "aus.1"},
    {"code": "SA1", "name": "Saudi Pro League", "country": "Saudi Arabia", "co_uk": None, "openfootball": None, "tz": "Asia/Riyadh", "espn": "ksa.1"},
    {"code": "IN1", "name": "Indian Super League", "country": "India", "co_uk": None, "openfootball": None, "tz": "Asia/Kolkata", "espn": "ind.1"},
    {"code": "TH1", "name": "Thai League 1",    "country": "Thailand", "co_uk": None, "openfootball": None, "tz": "Asia/Bangkok", "espn": "tha.1"},
    {"code": "MLS", "name": "Major League Soccer", "country": "USA", "co_uk": None, "openfootball": None, "tz": "America/New_York", "calendar": True, "co_uk_new": "USA", "espn": "usa.1"},
    {"code": "MX1", "name": "Liga MX",          "country": "Mexico", "co_uk": None, "openfootball": None, "tz": "America/Mexico_City", "calendar": True, "co_uk_new": "MEX", "espn": "mex.1"},
    {"code": "CL1", "name": "Primera División Chile", "country": "Chile", "co_uk": None, "openfootball": None, "tz": "America/Santiago", "calendar": True, "espn": "chi.1"},
    {"code": "UY1", "name": "Primera División Uruguay", "country": "Uruguay", "co_uk": None, "openfootball": None, "tz": "America/Montevideo", "calendar": True, "espn": "uru.1"},
    {"code": "EC1", "name": "LigaPro Ecuador",  "country": "Ecuador", "co_uk": None, "openfootball": None, "tz": "America/Guayaquil", "calendar": True, "espn": "ecu.1"},
    {"code": "PE1", "name": "Liga 1 Peru",      "country": "Peru", "co_uk": None, "openfootball": None, "tz": "America/Lima", "calendar": True, "espn": "per.1"},
    {"code": "DK1", "name": "Superliga",        "country": "Denmark", "co_uk": None, "openfootball": None, "tz": "Europe/Copenhagen", "co_uk_new": "DNK", "espn": "den.1"},
    {"code": "SE1", "name": "Allsvenskan",      "country": "Sweden", "co_uk": None, "openfootball": None, "tz": "Europe/Stockholm", "calendar": True, "co_uk_new": "SWE", "espn": "swe.1"},
    {"code": "NO1", "name": "Eliteserien",      "country": "Norway", "co_uk": None, "openfootball": None, "tz": "Europe/Oslo", "calendar": True, "co_uk_new": "NOR", "espn": "nor.1"},
    {"code": "PL1", "name": "Ekstraklasa",      "country": "Poland", "co_uk": None, "openfootball": None, "tz": "Europe/Warsaw", "co_uk_new": "POL", "espn": "pol.1"},
    {"code": "RO1", "name": "Liga I Romania",   "country": "Romania", "co_uk": None, "openfootball": None, "tz": "Europe/Bucharest", "co_uk_new": "ROU", "espn": "rou.1"},
    {"code": "CH1", "name": "Swiss Super League", "country": "Switzerland", "co_uk": None, "openfootball": None, "tz": "Europe/Zurich", "co_uk_new": "SWZ", "espn": "sui.1"},
    {"code": "IE1", "name": "League of Ireland", "country": "Ireland", "co_uk": None, "openfootball": None, "tz": "Europe/Dublin", "calendar": True, "co_uk_new": "IRL", "espn": "irl.1"},
    {"code": "FI1", "name": "Veikkausliiga",    "country": "Finland", "co_uk": None, "openfootball": None, "tz": "Europe/Helsinki", "calendar": True, "co_uk_new": "FIN", "espn": "fin.1"},
]
BY_CODE = {x["code"]: x for x in HIST_LEAGUES}


def current_season(spec: dict, today) -> int:
    """Năm của mùa hiện tại: giải mùa theo năm dương lịch (Nhật, Brazil…) dùng năm hiện tại."""
    return today.year if spec.get("calendar") else season_start_year(today)


def season_start_year(today) -> int:
    """Mùa giải châu Âu bắt đầu khoảng tháng 8: từ tháng 7 trở đi tính là mùa mới."""
    return today.year if today.month >= 7 else today.year - 1
