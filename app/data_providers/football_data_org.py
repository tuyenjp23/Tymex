"""Nhà cung cấp dữ liệu football-data.org (API v4).

Gói miễn phí (theo tài liệu công khai của football-data.org): 12 giải đấu, 10 lần gọi/phút,
có lịch thi đấu, kết quả và bảng xếp hạng; KHÔNG có xG, cú sút, kiểm soát bóng, chấn thương, đội hình.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any, Callable

import httpx

from ..utils import normalize_utc
from .base import (
    FootballDataProvider, LeagueDTO, MatchDTO, ProviderAccessError, ProviderAuthError, ProviderConnectionError,
    ProviderError, ProviderNotConfigured, ProviderRateLimitError, ProviderResponseError, StandingDTO, TeamDTO,
)


class RateLimiter:
    """Cửa sổ trượt: tối đa `max_calls` lần gọi trong `period` giây; vượt thì chờ."""

    def __init__(self, max_calls: int = 10, period: float = 60.0,
                 clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep):
        self.max_calls, self.period, self.clock, self.sleep = max_calls, period, clock, sleep
        self._calls: deque[float] = deque()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        with self._lock:
            while True:
                now = self.clock()
                while self._calls and now - self._calls[0] >= self.period:
                    self._calls.popleft()
                if len(self._calls) < self.max_calls:
                    self._calls.append(now)
                    return
                self.sleep(max(self.period - (now - self._calls[0]), 0.01))


def _int_or_none(v: Any) -> int | None:
    return v if isinstance(v, int) else None


class FootballDataOrgProvider(FootballDataProvider):
    name = "football-data.org"
    BASE_URL = "https://api.football-data.org/v4"

    def __init__(self, api_key: str, *, timeout: float = 20.0, rate_limiter: RateLimiter | None = None,
                 transport: httpx.BaseTransport | None = None, sleep: Callable[[float], None] = time.sleep):
        self.api_key = (api_key or "").strip()
        self.limiter = rate_limiter or RateLimiter()
        self.sleep = sleep
        self._client = httpx.Client(base_url=self.BASE_URL, timeout=timeout, transport=transport,
                                    headers={"X-Auth-Token": self.api_key, "Accept": "application/json"})

    def set_api_key(self, api_key: str) -> None:
        self.api_key = (api_key or "").strip()
        self._client.headers["X-Auth-Token"] = self.api_key

    def is_configured(self) -> bool:
        return bool(self.api_key)

    # ------------------------------------------------------------------ HTTP
    @staticmethod
    def _retry_after(resp: httpx.Response) -> float:
        for header in ("Retry-After", "X-RequestCounter-Reset"):
            try:
                return float(resp.headers[header]) + 1.0
            except (KeyError, ValueError):
                continue
        return 61.0

    def _get(self, path: str, params: dict | None = None) -> dict:
        if not self.is_configured():
            raise ProviderNotConfigured("Chưa cấu hình FOOTBALL_DATA_API_KEY.")
        for attempt in range(2):
            self.limiter.acquire()
            try:
                resp = self._client.get(path, params=params)
            except httpx.TimeoutException as exc:
                raise ProviderConnectionError("Hết thời gian chờ khi gọi API bóng đá.") from exc
            except httpx.HTTPError as exc:
                raise ProviderConnectionError(f"Không kết nối được tới API bóng đá: {exc.__class__.__name__}.") from exc

            code = resp.status_code
            if code == 429:
                wait = self._retry_after(resp)
                if attempt == 0 and wait <= 75:
                    self.sleep(wait)   # chờ hết hạn mức rồi thử lại đúng một lần
                    continue
                raise ProviderRateLimitError("API báo vượt giới hạn số lần gọi (HTTP 429). Hãy thử lại sau ít phút.")
            if code == 401:
                raise ProviderAuthError("API từ chối khóa (HTTP 401). Kiểm tra lại FOOTBALL_DATA_API_KEY.")
            if code in (403, 404):
                raise ProviderAccessError("Gói API hiện tại không có quyền truy cập dữ liệu này, hoặc giải đấu không tồn tại "
                                          f"(HTTP {code}).")
            if code >= 500:
                raise ProviderConnectionError(f"Máy chủ API đang lỗi (HTTP {code}).")
            if code != 200:
                raise ProviderError(f"API trả về mã không mong đợi: HTTP {code}.")
            try:
                data = resp.json()
            except ValueError as exc:
                raise ProviderResponseError("API trả về dữ liệu không phải JSON.") from exc
            if not isinstance(data, dict):
                raise ProviderResponseError("API trả về cấu trúc dữ liệu không đúng định dạng.")
            return data
        raise ProviderRateLimitError("Không thể hoàn tất yêu cầu do giới hạn tốc độ.")  # pragma: no cover

    # ------------------------------------------------------------------ chuyển đổi dữ liệu
    @staticmethod
    def _team(d: dict | None) -> TeamDTO | None:
        if not d or d.get("id") is None or not d.get("name"):
            return None   # đội chưa xác định (vòng knock-out chưa biết đối thủ)
        return TeamDTO(external_id=str(d["id"]), name=d["name"], short_name=d.get("shortName"),
                       tla=d.get("tla"), crest_url=d.get("crest"))

    @staticmethod
    def _season_year(season: dict | None) -> int | None:
        try:
            return int(str((season or {}).get("startDate", ""))[:4])
        except ValueError:
            return None

    def get_matches(self, code: str, season: int | None = None) -> tuple[LeagueDTO, list[MatchDTO]]:
        params = {"season": season} if season else None
        data = self._get(f"/competitions/{code}/matches", params)
        comp = data.get("competition") or {}
        if not comp.get("code"):
            raise ProviderResponseError("Phản hồi thiếu thông tin giải đấu.")
        matches: list[MatchDTO] = []
        years: list[int] = []
        for m in data.get("matches") or []:
            home, away = self._team(m.get("homeTeam")), self._team(m.get("awayTeam"))
            if home is None or away is None or not m.get("utcDate") or m.get("id") is None:
                continue
            score = m.get("score") or {}
            ft, ht = score.get("fullTime") or {}, score.get("halfTime") or {}
            year = self._season_year(m.get("season"))
            if year:
                years.append(year)
            matches.append(MatchDTO(
                external_id=str(m["id"]), season=year, matchday=_int_or_none(m.get("matchday")), stage=m.get("stage"),
                utc_date=normalize_utc(m["utcDate"]), status=m.get("status") or "SCHEDULED", home=home, away=away,
                home_score=_int_or_none(ft.get("home")), away_score=_int_or_none(ft.get("away")),
                home_ht=_int_or_none(ht.get("home")), away_ht=_int_or_none(ht.get("away")), winner=score.get("winner")))
        first = (data.get("matches") or [{}])[0] or {}
        country = (first.get("area") or {}).get("name")
        league = LeagueDTO(code=comp["code"], name=comp.get("name") or comp["code"], country=country,
                           type=comp.get("type"), emblem_url=comp.get("emblem"),
                           current_season=(season or (max(years) if years else None)))
        return league, matches

    def get_standings(self, code: str) -> tuple[int | None, list[StandingDTO]]:
        data = self._get(f"/competitions/{code}/standings")
        year = self._season_year(data.get("season"))
        rows: list[StandingDTO] = []
        for block in data.get("standings") or []:
            if block.get("type") != "TOTAL":
                continue
            for r in block.get("table") or []:
                team = self._team(r.get("team"))
                if team is None:
                    continue
                rows.append(StandingDTO(
                    group_name=block.get("group"), position=int(r.get("position") or 0), team=team,
                    played=int(r.get("playedGames") or 0), won=int(r.get("won") or 0), draw=int(r.get("draw") or 0),
                    lost=int(r.get("lost") or 0), points=int(r.get("points") or 0), goals_for=int(r.get("goalsFor") or 0),
                    goals_against=int(r.get("goalsAgainst") or 0), goal_diff=int(r.get("goalDifference") or 0),
                    form=r.get("form")))
        return year, rows
