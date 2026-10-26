"""Kiểm thử mục Dự đoán vô địch: kèo outright (The Odds API) + mô phỏng Monte Carlo (mô hình Tymex).
Chỉ dùng dữ liệu giả và client giả — không gọi mạng."""
from datetime import datetime, timedelta, timezone

import pytest

from app.data_providers.base import LeagueDTO, MatchDTO, TeamDTO
from app.odds.the_odds_api import OddsApiError, TheOddsApi
from app.prediction import outrights as o


# ---------------------------------------------------------------------- ánh xạ môn -> giải
def test_map_sport_to_league_by_title():
    cases = {
        "English Premier League": "PL", "Spanish La Liga": "PD", "German Bundesliga": "BL1",
        "Italian Serie A": "SA", "French Ligue 1": "FL1", "UEFA Champions League": "UCL",
    }
    for title, code in cases.items():
        assert o.map_sport_to_league({"key": "x", "title": title}) == code
        assert o.map_sport_to_league(title) == code
    # giải hạng 2 / không liên quan => không ánh xạ
    assert o.map_sport_to_league({"title": "German Bundesliga 2"}) is None
    assert o.map_sport_to_league({"title": "Italian Serie B"}) is None
    assert o.map_sport_to_league({"title": "Scottish Premiership"}) is None
    assert o.map_sport_to_league({"title": ""}) is None
    assert o.map_sport_to_league(None) is None


# ---------------------------------------------------------------------- đồng thuận thị trường
def _event(bookmakers):
    return {"bookmakers": [{"key": k, "markets": [{"key": "outrights", "outcomes": outs}]}
                            for k, outs in bookmakers]}


def test_consensus_outrights_median_and_normalization():
    events = [_event([
        ("bk-a", [{"name": "Arsenal", "price": 2.0}, {"name": "Man City", "price": 4.0}]),
        ("bk-b", [{"name": "Arsenal", "price": 3.0}, {"name": "Man City", "price": 3.0}]),
        ("bk-c", [{"name": "Arsenal", "price": 2.5}, {"name": "Man City", "price": 3.5}, {"name": "Hỏng", "price": 1.0}]),
    ])]
    cons = o.consensus_outrights(events)
    assert cons["available"] is True and cons["bookmakers"] == 3
    by_team = {x["team"]: x for x in cons["outcomes"]}
    assert by_team["Arsenal"]["odds"] == 2.5          # trung vị của 2.0, 3.0, 2.5
    assert by_team["Man City"]["odds"] == 3.5          # trung vị của 4.0, 3.0, 3.5
    assert "Hỏng" not in by_team                        # giá <= 1.0 bị bỏ
    assert abs(sum(x["prob"] for x in cons["outcomes"]) - 1.0) < 1e-9
    assert cons["outcomes"][0]["team"] == "Arsenal"     # sắp xếp giảm dần theo xác suất


def test_consensus_outrights_empty_is_unavailable():
    assert o.consensus_outrights([])["available"] is False
    assert o.consensus_outrights([{"bookmakers": []}])["available"] is False
    junk = [_event([("bk", [{"name": "X", "price": "không-phải-số"}, {"name": "Y", "price": None}])])]
    assert o.consensus_outrights(junk)["available"] is False


# ---------------------------------------------------------------------- TheOddsApi outrights (client giả)
class _Resp:
    def __init__(self, status=200, data=None, headers=None):
        self.status_code, self._data, self.headers = status, data, headers or {}

    def json(self):
        return self._data


class _FakeClient:
    def __init__(self, handler):
        self.handler, self.urls = handler, []

    def get(self, url, params=None):
        self.urls.append((url, params))
        return self.handler(url, params)


def test_the_odds_api_outrights_discovery_and_fetch():
    def handler(url, params):
        if url.endswith("/sports/"):
            assert params.get("outrights") == "true"
            return _Resp(200, [
                {"key": "soccer_epl_outrights", "group": "Soccer", "title": "English Premier League"},
                {"key": "golf_x", "group": "Golf", "title": "Golf Outrights"},
                {"key": "soccer_ucl", "group": "Soccer", "title": "UEFA Champions League"},
            ], {"x-requests-remaining": "499"})
        assert params.get("markets") == "outrights" and params.get("oddsFormat") == "decimal"
        return _Resp(200, [_event([("bk", [{"name": "Arsenal", "price": 2.5}])])],
                     {"x-requests-remaining": "498", "x-requests-used": "2"})

    api = TheOddsApi("KEY", client=_FakeClient(handler), max_calls_per_run=10)
    sports = api.list_outright_sports()
    assert [s["title"] for s in sports] == ["English Premier League", "UEFA Champions League"]   # chỉ bóng đá
    events, info = api.fetch_outrights("soccer_epl_outrights")
    assert events and info["remaining"] == 498 and info["used"] == 2


def test_the_odds_api_outrights_budget_and_error_mapping():
    api = TheOddsApi("SECRETKEY", client=_FakeClient(lambda u, p: _Resp(200, [])), max_calls_per_run=1)
    api.fetch_outrights("soccer_epl_outrights")
    with pytest.raises(OddsApiError) as exc:
        api.fetch_outrights("soccer_epl_outrights")
    assert exc.value.code == "budget"
    denied = TheOddsApi("SECRETKEY", client=_FakeClient(lambda u, p: _Resp(401, {})))
    with pytest.raises(OddsApiError) as exc2:
        denied.list_outright_sports()
    assert exc2.value.code == "auth" and "SECRETKEY" not in str(exc2.value)


def test_fetch_market_outrights_stops_when_quota_low():
    class FakeApi:
        def list_outright_sports(self):
            return [{"key": "k-pl", "title": "English Premier League"},
                    {"key": "k-pd", "title": "Spanish La Liga"},
                    {"key": "k-sa", "title": "Italian Serie A"}]

        def fetch_outrights(self, key):
            return ([_event([("bk", [{"name": "Đội A", "price": 2.0}, {"name": "Đội B", "price": 3.0}])])],
                    {"remaining": 55, "used": 445})   # dưới ngưỡng 60 -> dừng sau lần gọi đầu

    markets, meta = o.fetch_market_outrights(FakeApi(), log=lambda _m: None)
    assert meta["calls"] == 1 and markets["PL"]["available"] is True
    assert "PD" not in markets and "SA" not in markets   # đã dừng để giữ hạn mức


# ---------------------------------------------------------------------- mô phỏng Monte Carlo
def _cdf(lh=1.6, la=1.2):
    return o.fixture_cdf(lh, la)


def test_simulate_title_race_deterministic_and_sums_to_one():
    table = {f"Đội {i}": {"points": 40 - 3 * i, "gf": 35, "ga": 20} for i in range(6)}
    fixtures = [{"home": h, "away": a, "cdf": _cdf()} for h in table for a in table if h < a]
    r1 = o.simulate_title_race(table, fixtures, n_sims=400, seed=42)
    r2 = o.simulate_title_race(table, fixtures, n_sims=400, seed=42)
    assert r1 == r2                                     # cùng seed -> cùng kết quả
    assert r1["available"] is True
    assert abs(sum(x["prob"] for x in r1["outcomes"]) - 1.0) < 0.01
    assert r1["outcomes"][0]["team"] == "Đội 0"         # đội dẫn đầu 15 điểm phải được đánh giá cao nhất


def test_simulate_title_race_runaway_leader_gets_everything():
    table = {"Vô địch Sớm": {"points": 90, "gf": 80, "ga": 20}, "Kẻ Theo Sau": {"points": 60, "gf": 50, "ga": 30}}
    fixtures = [{"home": "Kẻ Theo Sau", "away": "Vô địch Sớm", "cdf": _cdf(2.5, 0.5)}]
    r = o.simulate_title_race(table, fixtures, n_sims=200, seed=3)
    probs = {x["team"]: x["prob"] for x in r["outcomes"]}
    assert probs["Vô địch Sớm"] == 1.0                  # hơn 30 điểm khi chỉ còn 1 trận: không thể bị bắt kịp


def test_simulate_title_race_finished_season_and_empty_inputs():
    table = {"A": {"points": 50, "gf": 40, "ga": 10}, "B": {"points": 47, "gf": 30, "ga": 12}}
    r = o.simulate_title_race(table, [], n_sims=100, seed=1)
    assert r["available"] is True
    assert {x["team"]: x["prob"] for x in r["outcomes"]} == {"A": 1.0, "B": 0.0}
    assert o.simulate_title_race({}, [], n_sims=10)["available"] is False
    assert o.simulate_title_race(None, None)["available"] is False


# ---------------------------------------------------------------------- gating + dùng lại payload cũ
def test_market_fetch_due_and_reuse():
    now = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)
    fresh = {"fetched_at": "2026-10-26T10:00:00Z", "leagues": []}
    stale = {"fetched_at": "2026-10-24T10:00:00Z", "leagues": []}
    assert o.market_fetch_due(None, now) is True
    assert o.market_fetch_due({}, now) is True
    assert o.market_fetch_due(fresh, now) is False      # mới 2 giờ, ngưỡng 36 giờ
    assert o.market_fetch_due(stale, now) is True       # đã 50 giờ
    old = {"leagues": [{"code": "PL", "market": {"available": True, "outcomes": [{"team": "Arsenal", "odds": 2.5, "prob": 0.4}]}},
                       {"code": "PD", "market": {"available": False, "reason": "x"}}]}
    reused = o.market_from_payload(old)
    assert set(reused) == {"PL"} and reused["PL"]["outcomes"][0]["team"] == "Arsenal"


# ---------------------------------------------------------------------- builder trên CSDL giả
def _seed_title_league(repo, n_teams=8, finished_rounds=45):
    """Giải PL giả: 8 đội đá vòng tròn 2 lượt (56 trận); `finished_rounds` trận đầu đã kết thúc, còn lại chưa đá."""
    teams = [TeamDTO(external_id=str(200 + i), name=f"Đội {chr(65 + i)} FC", short_name=f"Đội {chr(65 + i)}",
                     tla=f"D{chr(65 + i)}", crest_url=None) for i in range(n_teams)]
    league_id = repo.upsert_league("football-data.org",
                                   LeagueDTO(code="PL", name="Premier League (Anh)", country="England",
                                             type="LEAGUE", current_season=2025))
    fixtures = []
    base = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
    idx = 0
    for leg in range(2):
        for i in range(n_teams):
            for j in range(n_teams):
                if i == j:
                    continue
                h, a = (i, j) if leg == 0 else (j, i)
                if leg == 1 and i > j:
                    continue
                if leg == 0 and i > j:
                    continue
                idx += 1
                done = idx <= finished_rounds
                fixtures.append(MatchDTO(
                    external_id=str(9000 + idx), season=2025, matchday=idx, stage="REGULAR_SEASON",
                    utc_date=(base + timedelta(days=idx)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    status="FINISHED" if done else "SCHEDULED", home=teams[h], away=teams[a],
                    home_score=(idx + h) % 3 if done else None, away_score=(idx + a) % 2 if done else None,
                    winner=None))
    repo.upsert_matches("football-data.org", league_id, fixtures)
    return league_id


def test_build_league_title_model_with_repo_data(repo):
    _seed_title_league(repo)
    model = o.build_league_title_model(repo, "PL", n_sims=200, seed=5)
    assert model["available"] is True
    assert model["fixtures_remaining"] == 11
    assert abs(sum(x["prob"] for x in model["outcomes"]) - 1.0) < 0.01
    assert o.build_league_title_model(repo, "UCL")["available"] is False   # giải cúp: không mô phỏng
    assert o.build_league_title_model(repo, "BL1")["available"] is False   # chưa có giải trong CSDL


def test_build_outrights_payload_market_model_and_alignment(repo):
    _seed_title_league(repo)
    market = {"PL": {"available": True, "source": "The Odds API", "bookmakers": 7,
                     "outcomes": [{"team": "Đội A", "odds": 2.5, "prob": 0.4},
                                  {"team": "Đội B", "odds": 3.5, "prob": 0.28}]},
              "UCL": {"available": True, "source": "The Odds API", "bookmakers": 5,
                      "outcomes": [{"team": "Real Madrid", "odds": 4.0, "prob": 0.25}]}}
    payload = o.build_outrights_payload(repo, market_by_code=market, market_fetched_at="2026-10-26T00:00:00Z",
                                        now=datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc),
                                        n_sims=100, log=lambda _m: None)
    by_code = {lg["code"]: lg for lg in payload["leagues"]}
    assert set(by_code) == {"PL", "PD", "BL1", "SA", "FL1", "UCL"}
    pl_market = by_code["PL"]["market"]
    assert pl_market["available"] is True and pl_market["bookmakers"] == 7
    assert pl_market["outcomes"][0]["team"] == "Đội A FC"      # tên thị trường đã ghép về tên trong CSDL
    assert by_code["PL"]["model"]["available"] is True
    assert by_code["UCL"]["model"]["available"] is False       # cúp: chỉ có thị trường
    assert by_code["PD"]["market"]["available"] is False       # không có kèo thì nói rõ, không bịa
    assert payload["fetched_at"] == "2026-10-26T00:00:00Z" and payload["simulated_at"]


# ---------------------------------------------------------------------- API local
def test_api_outrights_shape_without_key(settings, monkeypatch):
    monkeypatch.delenv("THE_ODDS_API_KEY", raising=False)
    from fastapi.testclient import TestClient
    from app.data_providers.football_data_org import FootballDataOrgProvider
    from app.main import create_app
    app = create_app(settings, provider=FootballDataOrgProvider(""), start_scheduler=False)
    with TestClient(app) as client:
        r = client.get("/api/outrights?n_sims=100")
    assert r.status_code == 200
    body = r.json()
    assert {lg["code"] for lg in body["leagues"]} == {"PL", "PD", "BL1", "SA", "FL1", "UCL"}
    pl = next(lg for lg in body["leagues"] if lg["code"] == "PL")
    assert pl["market"]["available"] is False and "THE_ODDS_API_KEY" in pl["market"]["reason"]
    assert pl["model"]["available"] is False                # CSDL trống: không bịa kết quả mô phỏng
    ucl = next(lg for lg in body["leagues"] if lg["code"] == "UCL")
    assert ucl["model"]["available"] is False and "cúp" in (ucl["model"].get("note") or ucl["model"].get("reason") or "")
