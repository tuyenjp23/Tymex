import json

import httpx
import pytest

from app.data_providers.base import (ProviderAccessError, ProviderAuthError, ProviderConnectionError,
                                     ProviderNotConfigured, ProviderRateLimitError, ProviderResponseError)
from app.data_providers.football_data_org import FootballDataOrgProvider, RateLimiter

# --- Phản hồi MẪU dựng theo cấu trúc tài liệu API v4 (dữ liệu kiểm thử, không phải dữ liệu thật) ---
MATCHES_JSON = {
    "competition": {"id": 1, "name": "Giải Mẫu", "code": "TST", "type": "LEAGUE", "emblem": "http://x/e.png"},
    "matches": [
        {"id": 11, "utcDate": "2025-08-15T19:00:00Z", "status": "FINISHED", "matchday": 1, "stage": "REGULAR_SEASON",
         "area": {"name": "Testland"}, "season": {"startDate": "2025-08-01"},
         "homeTeam": {"id": 1, "name": "Mẫu A", "shortName": "A", "tla": "AAA", "crest": "http://x/a.png"},
         "awayTeam": {"id": 2, "name": "Mẫu B", "shortName": "B", "tla": "BBB", "crest": None},
         "score": {"winner": "HOME_TEAM", "fullTime": {"home": 2, "away": 1}, "halfTime": {"home": 1, "away": 0}}},
        {"id": 12, "utcDate": "2025-08-22T19:00:00+02:00", "status": "SCHEDULED", "matchday": 2, "season": {"startDate": "2025-08-01"},
         "homeTeam": {"id": 2, "name": "Mẫu B"}, "awayTeam": {"id": 1, "name": "Mẫu A"},
         "score": {"winner": None, "fullTime": {"home": None, "away": None}, "halfTime": {}}},
        {"id": 13, "utcDate": "2025-09-01T19:00:00Z", "status": "SCHEDULED",       # đội chưa xác định => bỏ qua
         "homeTeam": {"id": None, "name": None}, "awayTeam": {"id": 1, "name": "Mẫu A"}, "score": {}},
    ],
}
STANDINGS_JSON = {"season": {"startDate": "2025-08-01"}, "standings": [
    {"type": "TOTAL", "group": None, "table": [{"position": 1, "team": {"id": 1, "name": "Mẫu A"}, "playedGames": 1, "won": 1,
                                                 "draw": 0, "lost": 0, "points": 3, "goalsFor": 2, "goalsAgainst": 1, "goalDifference": 1}]},
    {"type": "HOME", "table": [{"position": 1, "team": {"id": 1, "name": "Mẫu A"}}]}]}


def provider(handler, key="k" * 20, sleeps=None, limiter=None):
    sleeps = sleeps if sleeps is not None else []
    return FootballDataOrgProvider(key, transport=httpx.MockTransport(handler), sleep=sleeps.append,
                                   rate_limiter=limiter or RateLimiter(100, 60, sleep=lambda s: None))


def ok(data):
    return lambda req: httpx.Response(200, json=data)


def test_no_key_raises_not_configured_without_any_http_call():
    calls = []
    p = provider(lambda r: calls.append(r) or httpx.Response(200, json={}), key="")
    assert not p.is_configured()
    with pytest.raises(ProviderNotConfigured):
        p.get_matches("TST")
    assert calls == []


def test_parses_matches_and_sends_token_header():
    seen = {}

    def handler(req):
        seen["token"] = req.headers["X-Auth-Token"]
        seen["url"] = str(req.url)
        return httpx.Response(200, json=MATCHES_JSON)

    league, matches = provider(handler).get_matches("TST", 2025)
    assert seen["token"] == "k" * 20 and "season=2025" in seen["url"]
    assert league.code == "TST" and league.country == "Testland" and league.current_season == 2025
    assert [m.external_id for m in matches] == ["11", "12"]          # đội TBD bị loại
    m = matches[0]
    assert (m.home_score, m.away_score, m.home_ht, m.winner, m.season) == (2, 1, 1, "HOME_TEAM", 2025)
    assert matches[1].utc_date == "2025-08-22T17:00:00Z"              # chuẩn hóa về UTC
    assert matches[1].home_score is None                             # chưa đá => không có tỷ số


def test_current_season_inferred_from_matches():
    league, _ = provider(ok(MATCHES_JSON)).get_matches("TST")
    assert league.current_season == 2025


def test_standings_only_total_table():
    year, rows = provider(ok(STANDINGS_JSON)).get_standings("TST")
    assert year == 2025 and len(rows) == 1 and rows[0].points == 3


@pytest.mark.parametrize("status,exc", [(401, ProviderAuthError), (403, ProviderAccessError), (404, ProviderAccessError),
                                         (500, ProviderConnectionError), (503, ProviderConnectionError)])
def test_http_errors_are_classified(status, exc):
    with pytest.raises(exc):
        provider(lambda r: httpx.Response(status, json={"message": "x"})).get_matches("TST")


def test_timeout_and_network_errors():
    def boom(req):
        raise httpx.ConnectTimeout("t")
    with pytest.raises(ProviderConnectionError, match="Hết thời gian"):
        provider(boom).get_matches("TST")

    def down(req):
        raise httpx.ConnectError("x")
    with pytest.raises(ProviderConnectionError):
        provider(down).get_matches("TST")


def test_bad_json_and_bad_shape():
    with pytest.raises(ProviderResponseError):
        provider(lambda r: httpx.Response(200, content=b"<html>")).get_matches("TST")
    with pytest.raises(ProviderResponseError):
        provider(lambda r: httpx.Response(200, json=[1, 2])).get_matches("TST")
    with pytest.raises(ProviderResponseError):
        provider(ok({"matches": []})).get_matches("TST")   # thiếu competition


def test_429_waits_retry_after_then_succeeds():
    calls, sleeps = [], []

    def handler(req):
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": "7"})
        return httpx.Response(200, json=MATCHES_JSON)

    _, matches = provider(handler, sleeps=sleeps).get_matches("TST")
    assert len(calls) == 2 and sleeps == [8.0] and len(matches) == 2


def test_429_twice_raises_rate_limit_error():
    with pytest.raises(ProviderRateLimitError):
        provider(lambda r: httpx.Response(429, headers={"Retry-After": "3"})).get_matches("TST")


def test_429_with_huge_wait_does_not_block_forever():
    sleeps = []
    with pytest.raises(ProviderRateLimitError):
        provider(lambda r: httpx.Response(429, headers={"Retry-After": "3600"}), sleeps=sleeps).get_matches("TST")
    assert sleeps == []


def test_rate_limiter_blocks_the_11th_call_within_a_minute():
    t = {"now": 0.0}
    slept = []

    def sleep(s):
        slept.append(s)
        t["now"] += s

    rl = RateLimiter(10, 60.0, clock=lambda: t["now"], sleep=sleep)
    for _ in range(10):
        rl.acquire()
        t["now"] += 1.0
    assert slept == []
    rl.acquire()                       # lần thứ 11: phải chờ tới khi lần gọi đầu tiên rời khỏi cửa sổ 60 giây
    assert sum(slept) == pytest.approx(50.0, abs=0.1) and t["now"] >= 60.0
