from datetime import date

from app.data_providers.base import LeagueDTO, MatchDTO, TeamDTO
from app.history.importer import import_matches
from app.history.leagues import BY_CODE
from app.history.runner import run_history
from app.history.sources import co_uk_url, openfootball_url, parse_co_uk_csv, parse_openfootball
from app.history.teams import TeamResolver, norm

P = "football-data.org"

# tên đội theo kiểu football-data.org  →  tên viết trong football-data.co.uk
PAIRS = {
    "Manchester United FC": "Man United", "Manchester City FC": "Man City", "Tottenham Hotspur FC": "Tottenham",
    "Wolverhampton Wanderers FC": "Wolves", "Nottingham Forest FC": "Nott'm Forest", "Newcastle United FC": "Newcastle",
    "Brighton & Hove Albion FC": "Brighton", "AFC Bournemouth": "Bournemouth", "West Ham United FC": "West Ham",
    "Club Atlético de Madrid": "Ath Madrid", "Athletic Club": "Ath Bilbao", "Real Betis Balompié": "Betis",
    "Real Sociedad de Fútbol": "Sociedad", "Rayo Vallecano de Madrid": "Vallecano", "RC Celta de Vigo": "Celta",
    "RCD Espanyol de Barcelona": "Espanol", "Borussia Mönchengladbach": "M'gladbach", "FC Bayern München": "Bayern Munich",
    "Bayer 04 Leverkusen": "Leverkusen", "1. FC Union Berlin": "Union Berlin", "Eintracht Frankfurt": "Ein Frankfurt",
    "1. FC Köln": "FC Koln", "FC St. Pauli 1910": "St Pauli", "FC Internazionale Milano": "Inter", "AC Milan": "Milan",
    "Hellas Verona FC": "Verona", "AS Roma": "Roma", "SS Lazio": "Lazio", "Paris Saint-Germain FC": "Paris SG",
    "Olympique Lyonnais": "Lyon", "Olympique de Marseille": "Marseille", "Stade Rennais FC 1901": "Rennes",
    "Stade Brestois 29": "Brest", "AS Saint-Étienne": "St Etienne", "Hamburger SV": "Hamburg", "Sevilla FC": "Sevilla",
}


def _repo_with_teams(repo, names):
    lid = repo.upsert_league(P, LeagueDTO(code="PL", name="Premier League"))
    for i, n in enumerate(names):
        repo.upsert_team(P, TeamDTO(external_id=str(i + 1), name=n))
    return lid


def test_norm_removes_noise():
    assert norm("1. FC Union Berlin") == "union berlin"
    assert norm("FC St. Pauli 1910") == "st pauli"
    assert norm("Brighton & Hove Albion FC") == "brighton and hove albion"
    assert norm("Nott'm Forest") == "nottm forest"


def test_resolver_matches_known_pairs_without_creating_teams(repo):
    _repo_with_teams(repo, list(PAIRS))
    r = TeamResolver(repo)
    ids = {}
    for fd_name, uk_name in PAIRS.items():
        tid = r.resolve(uk_name)
        ids[fd_name] = tid
        assert r.names[tid] == fd_name, f"{uk_name} -> {r.names[tid]} (mong đợi {fd_name})"
    assert r.created == []
    assert len(set(ids.values())) == len(PAIRS)


def test_resolver_does_not_guess_ambiguous_names(repo):
    _repo_with_teams(repo, ["Sheffield United FC", "Sheffield Wednesday FC"])
    r = TeamResolver(repo)
    tid = r.resolve("Sheffield")           # mơ hồ → tạo đội mới thay vì đoán
    assert r.created == ["Sheffield"]
    assert r.names[tid] == "Sheffield"
    assert r.names[r.resolve("Sheffield Weds")] == "Sheffield Wednesday FC"
    assert r.names[r.resolve("Sheffield Utd")] == "Sheffield United FC"


CSV = ("Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,FTR,HTHG,HTAG,B365H,B365D,B365A,AvgCH,AvgCD,AvgCA\n"
       "E0,16/08/2024,20:00,Man United,Fulham,1,0,H,0,0,1.5,4.2,6.5,1.52,4.1,6.3\n"
       "E0,17/08/24,12:30,Ipswich,Liverpool,0,2,A,0,1,7.0,4.8,1.4,,,\n"
       "E0,,,,,,,,,,,,,,,\n"
       "E0,24/08/2024,15:00,Brighton,Man United,2,1,H,1,0,,,,,,\n")


def test_parse_co_uk_csv_dates_odds_and_skips():
    rows = parse_co_uk_csv(CSV, div="E0", season=2024)
    assert len(rows) == 3
    a, b, c = rows
    assert a["utc_date"] == "2024-08-16T19:00:00Z"            # giờ mùa hè Anh = UTC+1
    assert a["odds"] == (1.52, 4.1, 6.3) and a["odds_source"] == "AvgC"   # ưu tiên trung bình lúc đóng cửa
    assert b["odds"] == (7.0, 4.8, 1.4) and b["odds_source"] == "B365"
    assert b["utc_date"].startswith("2024-08-17") and b["winner"] == "AWAY_TEAM"
    assert c["odds"] is None
    assert a["home_ht"] == 0 and a["winner"] == "HOME_TEAM"


def test_urls():
    assert co_uk_url("E0", 2024) == "https://www.football-data.co.uk/mmz4281/2425/E0.csv"
    assert co_uk_url("E0", 1999).endswith("/9900/E0.csv")
    assert openfootball_url("en.1", 2024).endswith("/2024-25/en.1.json")


def test_import_dedupes_against_existing_provider_matches_and_is_idempotent(repo):
    lid = _repo_with_teams(repo, ["Manchester United FC", "Fulham FC", "Brighton & Hove Albion FC", "Ipswich Town FC", "Liverpool FC"])
    # trận 16/8 đã có từ football-data.org (giờ khác một chút)
    repo.upsert_matches(P, lid, [MatchDTO(
        external_id="999", season=2024, matchday=1, stage="REGULAR_SEASON", utc_date="2024-08-16T19:00:00Z", status="FINISHED",
        home=TeamDTO("1", "Manchester United FC"), away=TeamDTO("2", "Fulham FC"), home_score=1, away_score=0, winner="HOME_TEAM")])
    rows = parse_co_uk_csv(CSV, div="E0", season=2024)
    res1 = import_matches(repo, source="football-data.co.uk", spec=BY_CODE["PL"], matches=rows, resolver=TeamResolver(repo))
    assert res1["seen"] == 3 and res1["added"] == 2 and res1["duplicates"] == 1 and res1["odds"] == 2
    with repo.db.connect() as c:
        assert c.execute("SELECT COUNT(*) n FROM matches").fetchone()["n"] == 3
        assert c.execute("SELECT COUNT(*) n FROM teams").fetchone()["n"] == 5       # không tạo đội trùng
    old = repo.query_matches(date_from="2024-08-16T00:00:00Z", date_to="2024-08-17T00:00:00Z")[0]
    assert repo.get_odds(old["id"])["source"] == "AvgC"                               # tỷ lệ cược gắn vào trận đã có
    res2 = import_matches(repo, source="football-data.co.uk", spec=BY_CODE["PL"], matches=rows, resolver=TeamResolver(repo))
    assert res2["added"] == 0
    with repo.db.connect() as c:
        assert c.execute("SELECT COUNT(*) n FROM matches").fetchone()["n"] == 3


OF = ('{"name":"x","matches":[{"round":"Matchday 1","date":"2024-08-16","time":"20:00","team1":"Manchester United FC",'
      '"team2":"Fulham FC","score":{"ht":[0,0],"ft":[1,0]}},'
      '{"round":"Matchday 38","date":"2099-05-25","team1":"Fulham FC","team2":"Liverpool FC"},'
      '{"round":"Matchday 2","date":"2020-01-01","team1":"A","team2":"B"}]}')


def test_parse_openfootball_status_and_skips_stale():
    rows = parse_openfootball(OF, code="en.1", season=2024, tz="Europe/London", today_iso="2026-10-15T00:00:00Z")
    assert len(rows) == 2                                   # trận quá khứ không có tỷ số bị bỏ
    assert rows[0]["status"] == "FINISHED" and rows[0]["home_score"] == 1 and rows[0]["matchday"] == 1
    assert rows[1]["status"] == "SCHEDULED" and rows[1]["home_score"] is None and rows[1]["winner"] is None


def test_run_history_survives_errors_and_skips_finished_seasons(repo):
    _repo_with_teams(repo, ["Manchester United FC", "Fulham FC"])
    calls = []

    def fetch(url):
        calls.append(url)
        if "SP1" in url:
            raise RuntimeError("mạng lỗi")
        if "mmz4281" in url and url.endswith("/E0.csv") and "/2425/" in url:
            return CSV.encode("utf-8-sig")
        return None

    out = run_history(repo, seasons=2, league_codes=["PL", "PD"], sources=("football-data.co.uk",),
                      today=date(2025, 3, 1), fetch=fetch, log=lambda s: None)
    assert out["added"] >= 1 and len(out["errors"]) >= 1          # lỗi SP1 được ghi nhận nhưng không dừng
    n_first = len(calls)
    out2 = run_history(repo, seasons=2, league_codes=["PL"], sources=("football-data.co.uk",),
                       today=date(2025, 3, 1), fetch=fetch, log=lambda s: None)
    assert out2["added"] == 0
    # mùa 2023 (đã kết thúc) có dữ liệu rỗng nên vẫn thử lại; mùa 2024 (hiện tại) luôn tải lại
    assert len(calls) > n_first


def test_compare_with_odds_runs_and_bookmaker_beats_uniform(repo):
    import random
    from app.prediction.benchmark import compare_with_odds, implied_probabilities
    p = implied_probabilities(2.0, 3.5, 4.0)
    assert abs(sum(p) - 1) < 1e-9 and p[0] > p[2]
    random.seed(7)
    teams = [f"Team {c}" for c in "ABCDEFGH"]
    lid = _repo_with_teams(repo, teams)
    strength = {t: s for t, s in zip(teams, [2.0, 1.6, 1.3, 1.1, 0.9, 0.8, 0.7, 0.6])}
    rows, day = [], 0
    for rnd in range(14):
        for i, h in enumerate(teams):
            a = teams[(i + 1 + rnd) % len(teams)]
            if a == h:
                continue
            day += 1
            lam_h, lam_a = 0.5 + strength[h] * 0.55, 0.4 + strength[a] * 0.4
            hg = sum(random.random() < lam_h / 6 for _ in range(6)); ag = sum(random.random() < lam_a / 6 for _ in range(6))
            pr = (lam_h / (lam_h + lam_a))
            rows.append({"external_id": f"s{day}", "season": 2024, "matchday": None,
                         "utc_date": f"2024-{8 + day // 28:02d}-{1 + day % 28:02d}T15:00:00Z", "status": "FINISHED",
                         "home": h, "away": a, "home_score": hg, "away_score": ag, "home_ht": None, "away_ht": None,
                         "winner": "HOME_TEAM" if hg > ag else ("AWAY_TEAM" if ag > hg else "DRAW"),
                         "odds": (round(1 / max(pr * 0.8, 0.05), 2), 3.6, round(1 / max((1 - pr) * 0.7, 0.05), 2)), "odds_source": "Avg"})
    import_matches(repo, source="football-data.co.uk", spec=BY_CODE["PL"], matches=rows, resolver=TeamResolver(repo))
    res = compare_with_odds(repo)
    o = res["overall"]
    assert o["matches"] > 20
    assert o["bookmaker_ll"] < o["uniform_ll"] and "model_ll" in o and res["leagues"]


# ------------------------------------------------------------------ tỷ lệ cược trận sắp đá
def _event(home, away, kick, prices_by_bk):
    return {"id": "e", "home_team": home, "away_team": away, "commence_time": kick,
            "bookmakers": [{"key": f"bk{i}", "markets": [{"key": "h2h", "outcomes": [
                {"name": home, "price": p[0]}, {"name": "Draw", "price": p[1]}, {"name": away, "price": p[2]}]}]}
                for i, p in enumerate(prices_by_bk)]}


def test_consensus_h2h_removes_margin_and_averages():
    from app.odds.the_odds_api import consensus_h2h
    ev = _event("A", "B", "2026-10-17T14:00:00Z", [(2.0, 3.4, 3.8), (2.1, 3.3, 3.6)])
    c = consensus_h2h(ev)
    assert c["bookmakers"] == 2 and abs(c["p_home"] + c["p_draw"] + c["p_away"] - 1) < 1e-9
    assert c["p_home"] > c["p_away"]
    assert consensus_h2h({"home_team": "A", "away_team": "B", "bookmakers": []}) is None
    bad = _event("A", "B", "x", [(0.9, 3.0, 3.0)])
    assert consensus_h2h(bad) is None


class FakeApi:
    """Nguồn tỷ lệ cược giả theo giao diện chung (name, is_configured, fetch, max_calls_per_run, min_remaining)."""
    def __init__(self, events, remaining=480, name="fake", error=None, max_calls_per_run=3, min_remaining=40):
        self.events, self.remaining, self.calls, self.name, self.error = events, remaining, [], name, error
        self.max_calls_per_run, self.min_remaining = max_calls_per_run, min_remaining

    def is_configured(self):
        return True

    def fetch(self, code, start, end):
        self.calls.append(code)
        if self.error:
            raise self.error
        self.remaining -= 1
        return self.events, {"remaining": self.remaining, "calls": 1}


def _ev(home, away, kick, ph=0.5, pd=0.25, pa=0.25, n=2):
    return {"home": home, "away": away, "commence_time": kick, "p_home": ph, "p_draw": pd, "p_away": pa, "bookmakers": n}


def _upcoming_setup(repo, kick="2026-10-17T14:00:00Z"):
    lid = _repo_with_teams(repo, ["Manchester United FC", "Fulham FC", "Liverpool FC", "Arsenal FC"])
    repo.upsert_matches(P, lid, [MatchDTO(
        external_id="u1", season=2026, matchday=9, stage="REGULAR_SEASON", utc_date=kick, status="TIMED",
        home=TeamDTO("1", "Manchester United FC"), away=TeamDTO("2", "Fulham FC"))])
    return lid


def test_refresh_upcoming_odds_saves_matches_and_respects_budget(repo):
    from datetime import timedelta
    from app.odds.runner import refresh_upcoming_odds
    from app.utils import to_iso, utcnow
    now = utcnow()
    kick = to_iso(now + timedelta(hours=2))
    _upcoming_setup(repo, kick)
    api = FakeApi([_ev("Manchester United", "Fulham", kick, 0.55, 0.25, 0.20, 6), _ev("Nobody FC", "Fulham", kick)])
    out = refresh_upcoming_odds(repo, [api], now=now, log=lambda s: None)
    assert api.calls == ["PL"] and out["calls"] == 1 and out["matched"] == 1 and out["remaining"] == {"fake": 479}
    assert out["unmatched"] == ["Nobody FC - Fulham"]
    m = repo.query_matches(statuses=("TIMED",))[0]
    o = repo.get_odds(m["id"])
    assert o["source"] == "fake:6" and o["odds_home"] < o["odds_away"]
    out2 = refresh_upcoming_odds(repo, [api], now=now, log=lambda s: None)    # vừa cập nhật → không gọi lại, tiết kiệm hạn mức
    assert out2["calls"] == 0 and len(api.calls) == 1


def test_provider_chain_falls_back_when_primary_is_out_of_quota(repo):
    from datetime import timedelta
    from app.odds.runner import refresh_upcoming_odds
    from app.odds.the_odds_api import OddsApiError
    from app.utils import to_iso, utcnow
    now = utcnow()
    kick = to_iso(now + timedelta(hours=2))
    _upcoming_setup(repo, kick)
    lid2 = repo.upsert_league(P, LeagueDTO(code="PD", name="Primera Division"))
    repo.upsert_team(P, TeamDTO("90", "Sevilla FC")); repo.upsert_team(P, TeamDTO("91", "Girona FC"))
    repo.upsert_matches(P, lid2, [MatchDTO(external_id="p1", season=2026, matchday=9, stage="REGULAR_SEASON",
                                           utc_date=to_iso(now + timedelta(hours=5)), status="TIMED",
                                           home=TeamDTO("90", "Sevilla FC"), away=TeamDTO("91", "Girona FC"))])
    primary = FakeApi([], name="primary", error=OddsApiError("hết hạn mức", "quota"))
    backup = FakeApi([_ev("Manchester United", "Fulham", kick, n=3), _ev("Sevilla", "Girona", to_iso(now + timedelta(hours=5)), n=3)], name="backup")
    out = refresh_upcoming_odds(repo, [primary, backup], now=now, log=lambda s: None)
    assert primary.calls == ["PL"]                      # nguồn đầu chỉ bị thử 1 lần rồi bị loại cho cả lần chạy
    assert backup.calls == ["PL", "PD"] and out["matched"] == 2
    assert any("hết hạn mức" in e for e in out["errors"])
    assert repo.get_odds(repo.query_matches(statuses=("TIMED",))[0]["id"])["source"].startswith("backup")


def test_provider_with_bad_key_is_skipped_and_run_survives(repo):
    from datetime import timedelta
    from app.odds.runner import refresh_upcoming_odds
    from app.odds.the_odds_api import OddsApiError
    from app.utils import to_iso, utcnow
    now = utcnow()
    _upcoming_setup(repo, to_iso(now + timedelta(hours=2)))
    bad = FakeApi([], name="bad", error=OddsApiError("khóa sai", "auth"))
    out = refresh_upcoming_odds(repo, [bad], now=now, log=lambda s: None)
    assert out["matched"] == 0 and out["calls"] == 0 and out["errors"]


def test_refresh_upcoming_odds_skips_far_matches_and_stops_on_low_credit(repo):
    from datetime import timedelta
    from app.odds.runner import refresh_upcoming_odds
    from app.utils import to_iso, utcnow
    now = utcnow()
    _upcoming_setup(repo, to_iso(now + timedelta(hours=100)))                 # trận còn quá xa
    api = FakeApi([])
    assert refresh_upcoming_odds(repo, [api], now=now, log=lambda s: None)["calls"] == 0 and api.calls == []
    lid2 = repo.upsert_league(P, LeagueDTO(code="PD", name="Primera Division"))
    repo.upsert_team(P, TeamDTO("90", "Sevilla FC")); repo.upsert_team(P, TeamDTO("91", "Girona FC"))
    repo.upsert_matches(P, lid2, [MatchDTO(external_id="p1", season=2026, matchday=9, stage="REGULAR_SEASON",
                                           utc_date=to_iso(now + timedelta(hours=5)), status="TIMED",
                                           home=TeamDTO("90", "Sevilla FC"), away=TeamDTO("91", "Girona FC"))])
    repo.upsert_matches(P, 1, [MatchDTO(external_id="u2", season=2026, matchday=10, stage="REGULAR_SEASON",
                                        utc_date=to_iso(now + timedelta(hours=6)), status="TIMED",
                                        home=TeamDTO("3", "Liverpool FC"), away=TeamDTO("4", "Arsenal FC"))])
    low = FakeApi([], remaining=10)
    out = refresh_upcoming_odds(repo, [low], now=now, log=lambda s: None)   # gọi 1 lần còn 9 < 40 → dừng
    assert len(low.calls) == 1 and any("credit còn lại thấp" in x for x in out["skipped"])


def test_api_football_parses_fixtures_and_paged_odds():
    import httpx
    from datetime import datetime, timezone
    from app.odds.api_football import ApiFootball

    def wb(h, d, a):
        return {"id": 8, "name": "x", "bets": [{"id": 1, "name": "Match Winner",
                "values": [{"value": "Home", "odd": str(h)}, {"value": "Draw", "odd": str(d)}, {"value": "Away", "odd": str(a)}]}]}

    class Client:
        def __init__(self):
            self.log = []

        def get(self, url, params=None, headers=None):
            self.log.append((url.rsplit("/", 1)[1], dict(params), dict(headers)))
            h = {"x-ratelimit-requests-remaining": "91"}
            if url.endswith("/fixtures"):
                return httpx.Response(200, headers=h, json={"errors": [], "response": [
                    {"fixture": {"id": 11, "date": "2026-10-17T14:00:00+00:00"}, "teams": {"home": {"name": "Manchester United"}, "away": {"name": "Fulham"}}},
                    {"fixture": {"id": 12, "date": "2026-10-17T16:30:00+00:00"}, "teams": {"home": {"name": "Arsenal"}, "away": {"name": "Liverpool"}}}]})
            page = params["page"]
            row = {11: {"fixture": {"id": 11}, "bookmakers": [wb(1.9, 3.8, 4.4), wb(2.0, 3.6, 4.2)]},
                   12: {"fixture": {"id": 12}, "bookmakers": [wb(2.6, 3.5, 2.7)]}}[11 if page == 1 else 12]
            return httpx.Response(200, headers=h, json={"errors": [], "paging": {"current": page, "total": 2}, "response": [row]})

    c = Client()
    api = ApiFootball("KEY123", client=c)
    events, info = api.fetch("PL", datetime(2026, 10, 17, 9, tzinfo=timezone.utc), datetime(2026, 10, 18, 15, tzinfo=timezone.utc))
    assert info == {"remaining": 91, "calls": 3}                         # 1 fixtures + 2 trang odds của 1 ngày
    ev = {e["home"]: e for e in events}
    assert ev["Manchester United"]["bookmakers"] == 2 and ev["Arsenal"]["bookmakers"] == 1
    assert abs(ev["Arsenal"]["p_home"] + ev["Arsenal"]["p_draw"] + ev["Arsenal"]["p_away"] - 1) < 1e-9
    assert c.log[0][1]["league"] == 39 and c.log[0][1]["season"] == 2026 and c.log[0][2] == {"x-apisports-key": "KEY123"}


def test_api_football_classifies_errors_in_200_body():
    import httpx
    from datetime import datetime, timezone
    from app.odds.api_football import ApiFootball
    from app.odds.the_odds_api import OddsApiError

    class C:
        def __init__(self, body):
            self.body = body

        def get(self, *a, **k):
            return httpx.Response(200, json=self.body)

    for body, code in (({"errors": {"token": "Error/Missing application key."}, "response": []}, "auth"),
                       ({"errors": {"requests": "You have reached the request limit for the day"}, "response": []}, "quota")):
        try:
            ApiFootball("K", client=C(body)).fetch("PL", datetime(2026, 10, 17, tzinfo=timezone.utc), datetime(2026, 10, 18, tzinfo=timezone.utc))
            assert False
        except OddsApiError as e:
            assert e.code == code


def test_odds_api_hides_key_in_errors():
    import httpx
    from app.odds.the_odds_api import OddsApiError, TheOddsApi

    class Boom:
        def get(self, *a, **k):
            raise httpx.ConnectError("failed https://x?apiKey=SECRETKEY123")

    try:
        TheOddsApi("SECRETKEY123", client=Boom()).fetch_h2h("soccer_epl")
        assert False
    except OddsApiError as e:
        assert "SECRETKEY123" not in str(e) and e.__cause__ is None


def test_market_block_levels_and_analysis_integration(repo, settings, now):
    from app.main import build_container
    from app.odds.compare import build_market_block
    odds = {"odds_home": 2.0, "odds_draw": 3.4, "odds_away": 3.8, "source": "OddsAPI:5", "updated_at": "2026-10-17T10:00:00Z"}
    near = {"available": True, "p_home": 0.48, "p_draw": 0.27, "p_away": 0.25}
    far = {"available": True, "p_home": 0.70, "p_draw": 0.20, "p_away": 0.10}
    assert build_market_block(odds, near, "A", "B")["level"] == "agree"
    b = build_market_block(odds, far, "A", "B")
    assert b["level"] == "large" and "lời khuyên cá cược" in b["verdict"] and b["margin"] > 0
    assert build_market_block(None, near, "A", "B")["available"] is False
    assert build_market_block(odds, {"available": False}, "A", "B")["level"] == "none"
    from tests import fixtures
    c = build_container(settings, provider=None)
    fixtures.seed(c.repo, now)
    c.predictions.now = lambda: now
    mid = c.repo.query_matches(limit=1)[0]["id"]
    assert c.analysis.build(mid, 5)["market"]["available"] is False
    c.repo.save_odds(mid, "AvgC", 2.0, 3.4, 3.8)
    assert c.analysis.build(mid, 5)["market"]["available"] is True
