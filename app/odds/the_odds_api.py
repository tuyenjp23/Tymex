"""Lấy tỷ lệ cược trận SẮP ĐÁ từ The Odds API (cần khóa miễn phí; mỗi lần gọi tốn "credit" theo gói của bạn).

Chỉ lấy thị trường thắng/hòa/thua (h2h) khu vực EU, gộp nhiều nhà cái thành một xác suất đồng thuận
(mỗi nhà cái được bỏ phần lợi nhuận rồi lấy trung bình). Khóa API không bao giờ được ghi vào log hay thông báo lỗi.
"""
from __future__ import annotations

BASE_URL = "https://api.the-odds-api.com/v4"

# mã giải trong CSDL (football-data.org) → khóa môn thể thao của The Odds API
SPORT_KEYS = {
    "PL": "soccer_epl", "ELC": "soccer_efl_champ", "PD": "soccer_spain_la_liga", "SD": "soccer_spain_segunda_division",
    "BL1": "soccer_germany_bundesliga", "BL2": "soccer_germany_bundesliga2", "SA": "soccer_italy_serie_a",
    "SB": "soccer_italy_serie_b", "FL1": "soccer_france_ligue_one", "CL": "soccer_uefa_champs_league",
    "DED": "soccer_netherlands_eredivisie", "PPL": "soccer_portugal_primeira_liga", "BSA": "soccer_brazil_campeonato",
}


class OddsApiError(Exception):
    def __init__(self, message: str, code: str = "error"):
        super().__init__(message)
        self.code = code


class TheOddsApi:
    name = "the-odds-api"

    def __init__(self, api_key: str, client=None, max_calls_per_run: int = 3, min_remaining: int = 40):
        self.api_key = (api_key or "").strip()
        self._client = client
        self.max_calls_per_run, self.min_remaining = max_calls_per_run, min_remaining

    def fetch(self, code: str, start, end) -> tuple[list[dict], dict]:
        """Giao diện chung của mọi nguồn tỷ lệ cược: trả về (sự kiện chuẩn hóa, {'remaining', 'calls'})."""
        sport = SPORT_KEYS.get(code)
        if not sport:
            raise OddsApiError(f"Giải {code} chưa được ánh xạ sang The Odds API.", "unknown_sport")
        events, info = self.fetch_h2h(sport)
        out = []
        for ev in events:
            cons = consensus_h2h(ev)
            if cons and ev.get("commence_time"):
                out.append({"home": ev.get("home_team"), "away": ev.get("away_team"), "commence_time": ev["commence_time"],
                            "p_home": cons["p_home"], "p_draw": cons["p_draw"], "p_away": cons["p_away"],
                            "bookmakers": cons["bookmakers"]})
        return out, {"remaining": info.get("remaining"), "calls": 1}

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def fetch_h2h(self, sport_key: str) -> tuple[list[dict], dict]:
        """Trả về (danh sách sự kiện, {'remaining': int|None, 'used': int|None})."""
        import httpx
        client = self._client or httpx.Client(timeout=30)
        try:
            r = client.get(f"{BASE_URL}/sports/{sport_key}/odds",
                           params={"apiKey": self.api_key, "regions": "eu", "markets": "h2h", "oddsFormat": "decimal"})
        except httpx.HTTPError as exc:   # không đưa exc vào thông báo: URL của nó chứa khóa API
            raise OddsApiError(f"Không kết nối được The Odds API ({type(exc).__name__}).", "network") from None
        info = {"remaining": _int(r.headers.get("x-requests-remaining")), "used": _int(r.headers.get("x-requests-used"))}
        if r.status_code == 401:
            raise OddsApiError("The Odds API từ chối khóa (401). Kiểm tra THE_ODDS_API_KEY.", "auth")
        if r.status_code == 429:
            raise OddsApiError("The Odds API báo hết hạn mức (429).", "quota")
        if r.status_code in (404, 422):
            raise OddsApiError(f"Giải '{sport_key}' không có trên The Odds API ({r.status_code}).", "unknown_sport")
        if r.status_code != 200:
            raise OddsApiError(f"The Odds API trả về lỗi {r.status_code}.", "http")
        try:
            data = r.json()
        except ValueError:
            raise OddsApiError("The Odds API trả về dữ liệu không đọc được.", "bad_json") from None
        return (data if isinstance(data, list) else []), info


def _int(v) -> int | None:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def consensus_h2h(event: dict) -> dict | None:
    """Xác suất đồng thuận (đã bỏ lợi nhuận nhà cái) từ mọi nhà cái có đủ 3 kết quả. None nếu không có."""
    home, away = event.get("home_team"), event.get("away_team")
    rows = []
    for bk in event.get("bookmakers") or []:
        for mk in bk.get("markets") or []:
            if mk.get("key") != "h2h":
                continue
            price = {o.get("name"): o.get("price") for o in mk.get("outcomes") or []}
            try:
                trio = [float(price[home]), float(price["Draw"]), float(price[away])]
            except (KeyError, TypeError, ValueError):
                continue
            if min(trio) <= 1.0:
                continue
            inv = [1.0 / x for x in trio]
            total = sum(inv)
            rows.append([x / total for x in inv])
    if not rows:
        return None
    n = len(rows)
    ph, pd, pa = (sum(r[i] for r in rows) / n for i in range(3))
    return {"p_home": ph, "p_draw": pd, "p_away": pa, "bookmakers": n}
