"""Nguồn tỷ lệ cược thứ hai: API-Football (api-sports.io), gói miễn phí 100 request/ngày.

Chưa được thử với khóa thật khi viết (chỉ thử bằng dữ liệu giả theo tài liệu công khai): lần chạy đầu hãy xem log.
Mỗi giải tốn: 1 request lấy danh sách trận (có tên đội) + 1 request cho mỗi ngày có trận (trang kết quả tỷ lệ cược, tối đa MAX_PAGES trang).
"""
from __future__ import annotations

from datetime import datetime

from ..history.leagues import season_start_year
from .the_odds_api import OddsApiError, _int

BASE_URL = "https://v3.football.api-sports.io"
MAX_PAGES = 3
MATCH_WINNER_ID = 1

# mã giải trong CSDL (football-data.org) → id giải của API-Football
LEAGUE_IDS = {
    "PL": 39, "ELC": 40, "PD": 140, "SD": 141, "BL1": 78, "BL2": 79, "SA": 135, "SB": 136, "FL1": 61,
    "CL": 2, "DED": 88, "PPL": 94, "BSA": 71,
}


def _classify_errors(errors) -> OddsApiError | None:
    """API-Football trả HTTP 200 kèm trường `errors` khi sai khóa hoặc hết hạn mức."""
    if not errors:
        return None
    text = (" ".join(f"{k} {v}" for k, v in errors.items()) if isinstance(errors, dict) else str(errors)).lower()
    if "token" in text or "key" in text or "subscription" in text:
        return OddsApiError("API-Football từ chối khóa (kiểm tra API_FOOTBALL_KEY).", "auth")
    if "request" in text or "limit" in text or "quota" in text or "rate" in text:
        return OddsApiError("API-Football báo hết hạn mức.", "quota")
    return OddsApiError("API-Football trả về lỗi: " + text[:120], "http")


def _book_probs(bookmakers: list) -> list[list[float]]:
    rows = []
    for bk in bookmakers or []:
        for bet in bk.get("bets") or []:
            if bet.get("id") != MATCH_WINNER_ID and bet.get("name") != "Match Winner":
                continue
            odd = {v.get("value"): v.get("odd") for v in bet.get("values") or []}
            try:
                trio = [float(odd["Home"]), float(odd["Draw"]), float(odd["Away"])]
            except (KeyError, TypeError, ValueError):
                continue
            if min(trio) <= 1.0:
                continue
            inv = [1 / x for x in trio]
            total = sum(inv)
            rows.append([x / total for x in inv])
    return rows


class ApiFootball:
    name = "api-football"

    def __init__(self, api_key: str, client=None, max_calls_per_run: int = 12, min_remaining: int = 15):
        self.api_key = (api_key or "").strip()
        self._client = client
        self.max_calls_per_run, self.min_remaining = max_calls_per_run, min_remaining
        self._remaining: int | None = None

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def _get(self, path: str, params: dict) -> dict:
        import httpx
        client = self._client or httpx.Client(timeout=30)
        try:
            r = client.get(BASE_URL + path, params=params, headers={"x-apisports-key": self.api_key})
        except httpx.HTTPError as exc:
            raise OddsApiError(f"Không kết nối được API-Football ({type(exc).__name__}).", "network") from None
        rem = _int(r.headers.get("x-ratelimit-requests-remaining"))
        if rem is not None:
            self._remaining = rem
        if r.status_code in (401, 403):
            raise OddsApiError("API-Football từ chối khóa (401/403).", "auth")
        if r.status_code == 429:
            raise OddsApiError("API-Football báo hết hạn mức (429).", "quota")
        if r.status_code != 200:
            raise OddsApiError(f"API-Football trả về lỗi {r.status_code}.", "http")
        try:
            data = r.json()
        except ValueError:
            raise OddsApiError("API-Football trả về dữ liệu không đọc được.", "bad_json") from None
        err = _classify_errors(data.get("errors"))
        if err:
            raise err
        return data

    def fetch(self, code: str, start: datetime, end: datetime) -> tuple[list[dict], dict]:
        lid = LEAGUE_IDS.get(code)
        if not lid:
            raise OddsApiError(f"Giải {code} chưa được ánh xạ sang API-Football.", "unknown_sport")
        season = season_start_year(start.date())
        calls = 0
        fx = self._get("/fixtures", {"league": lid, "season": season, "from": start.date().isoformat(), "to": end.date().isoformat()})
        calls += 1
        fixtures = {}
        for row in fx.get("response") or []:
            f, t = row.get("fixture") or {}, row.get("teams") or {}
            if f.get("id") and f.get("date") and (t.get("home") or {}).get("name") and (t.get("away") or {}).get("name"):
                fixtures[f["id"]] = {"home": t["home"]["name"], "away": t["away"]["name"], "commence_time": f["date"]}
        books: dict[int, list[list[float]]] = {}
        for day in sorted({v["commence_time"][:10] for v in fixtures.values()}):
            page = 1
            while page <= MAX_PAGES:
                od = self._get("/odds", {"league": lid, "season": season, "date": day, "bet": MATCH_WINNER_ID, "page": page})
                calls += 1
                for row in od.get("response") or []:
                    fid = (row.get("fixture") or {}).get("id")
                    if fid in fixtures:
                        books.setdefault(fid, []).extend(_book_probs(row.get("bookmakers")))
                paging = od.get("paging") or {}
                if page >= int(paging.get("total") or 1):
                    break
                page += 1
        events = []
        for fid, rows in books.items():
            if not rows:
                continue
            n = len(rows)
            events.append({**fixtures[fid], "p_home": sum(r[0] for r in rows) / n, "p_draw": sum(r[1] for r in rows) / n,
                           "p_away": sum(r[2] for r in rows) / n, "bookmakers": n})
        return events, {"remaining": self._remaining, "calls": calls}
