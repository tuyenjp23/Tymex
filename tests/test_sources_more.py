import json
from datetime import date

from app.history.importer import import_matches
from app.history.leagues import BY_CODE, HIST_LEAGUES
from app.history.runner import SRC_ESPN, run_history
from app.history.sources import parse_co_uk_new_csv, parse_espn
from app.history.teams import TeamResolver

ESPN = {"events": [
    {"id": "1", "date": "2025-03-01T10:00Z", "competitions": [{"status": {"type": {"state": "post", "completed": True}},
        "competitors": [{"homeAway": "home", "score": "2", "team": {"displayName": "Ulsan HD"}},
                        {"homeAway": "away", "score": "1", "team": {"displayName": "Jeonbuk Hyundai Motors"}}]}]},
    {"id": "2", "date": "2999-03-08T10:00Z", "competitions": [{"status": {"type": {"state": "pre", "completed": False}},
        "competitors": [{"homeAway": "home", "score": "0", "team": {"displayName": "FC Seoul"}},
                        {"homeAway": "away", "score": "0", "team": {"displayName": "Pohang Steelers"}}]}]},
    {"id": "3", "date": "2025-03-02T10:00Z", "competitions": [{"status": {"type": {"state": "in", "completed": False}},
        "competitors": [{"homeAway": "home", "score": "1", "team": {"displayName": "A"}},
                        {"homeAway": "away", "score": "0", "team": {"displayName": "B"}}]}]},
]}


def test_parse_espn():
    rows = parse_espn(json.dumps(ESPN), slug="kor.1", season=2025, today_iso="2026-01-01T00:00:00Z")
    assert [r["status"] for r in rows] == ["FINISHED", "SCHEDULED"]       # trận đang đá bị bỏ qua
    assert rows[0]["home_score"] == 2 and rows[0]["winner"] == "HOME_TEAM"
    assert rows[1]["home_score"] is None and rows[1]["winner"] is None


def test_parse_co_uk_new():
    csv_text = ("Country,League,Season,Date,Time,Home,Away,HG,AG,Res,PH,PD,PA,AvgH,AvgD,AvgA\n"
                "Japan,J1 League,2025,15/02/2025,10:00,Gamba Osaka,Cerezo Osaka,2,5,A,2.5,3.3,2.8,2.4,3.2,2.9\n"
                "Japan,J1 League,2024,10/02/2024,10:00,X,Y,1,0,H,,,,,,\n")
    rows = parse_co_uk_new_csv(csv_text, code="JPN", season=2025, tz="Asia/Tokyo")
    assert len(rows) == 1 and rows[0]["odds"] == (2.4, 3.2, 2.9) and rows[0]["odds_source"] == "Avg"


def test_scheduled_history_match_gets_result_later(repo):
    spec = BY_CODE["KR1"]
    r = TeamResolver(repo)
    sched = [{"external_id": "espn:kor.1:2", "season": 2025, "matchday": None, "utc_date": "2025-03-08T10:00:00Z", "status": "SCHEDULED",
              "home": "FC Seoul", "away": "Pohang Steelers", "home_score": None, "away_score": None, "home_ht": None, "away_ht": None,
              "winner": None, "odds": None, "odds_source": None}]
    import_matches(repo, source=SRC_ESPN, spec=spec, matches=sched, resolver=r)
    done = [dict(sched[0], status="FINISHED", home_score=3, away_score=1, winner="HOME_TEAM")]
    import_matches(repo, source="openfootball", spec=spec, matches=done, resolver=TeamResolver(repo))
    ms = repo.query_matches(limit=10)
    assert len(ms) == 1 and ms[0]["status"] == "FINISHED" and ms[0]["home_score"] == 3


def test_run_history_espn_with_fake_fetch(repo):
    calls = []

    def fetch(url):
        calls.append(url)
        return json.dumps(ESPN).encode() if "kor.1" in url else None

    out = run_history(repo, seasons=1, league_codes=["KR1"], today=date(2025, 3, 10), fetch=fetch, log=lambda s: None)
    assert out["added"] >= 1 and not out["errors"]
    assert all("espn.com" in u for u in calls) and len(calls) >= 3          # nhiều khoảng tháng
    calls.clear()
    run_history(repo, seasons=1, league_codes=["KR1"], today=date(2025, 3, 10), fetch=fetch, log=lambda s: None)
    assert 1 <= len(calls) <= 5                                            # lần sau chỉ lấy cửa sổ gần hiện tại


def test_all_specs_have_a_source():
    for x in HIST_LEAGUES:
        assert x.get("co_uk") or x.get("openfootball") or x.get("co_uk_new") or x.get("espn") or x.get("world"), x["code"]
    assert len({x["code"] for x in HIST_LEAGUES}) == len(HIST_LEAGUES)


def test_known_wrong_merges_blocked_and_duplicates_joined(repo):
    from app.history.teams import TeamResolver
    r = TeamResolver(repo)
    gremio = r.resolve("Gremio", "Brazil")
    assert r.resolve("Grêmio Novorizontino SP", "Brazil") != gremio
    mg, go = r.resolve("Atletico-MG", "Brazil"), r.resolve("Atletico GO", "Brazil")
    assert mg != go
    assert r.resolve("Athletico Paranaense", "Brazil") == r.resolve("CA Paranaense", "Brazil")
    assert r.resolve("PSV", "Netherlands") == r.resolve("PSV Eindhoven", "Netherlands")
    assert r.resolve("Sp Lisbon", "Portugal") == r.resolve("Sporting CP", "Portugal")
    assert r.resolve("Remo PA", "Brazil") == r.resolve("Clube do Remo", "Brazil")


def test_espn_one_bad_month_does_not_drop_season(repo):
    calls = {"n": 0}

    def fetch(url):
        calls["n"] += 1
        if "20250101" in url:
            raise RuntimeError("400 Bad Request")
        return json.dumps(ESPN).encode() if "kor.1" in url else None

    out = run_history(repo, seasons=1, league_codes=["KR1"], today=date(2025, 3, 10), fetch=fetch, log=lambda s: None)
    assert out["added"] >= 1


def test_more_wrong_merges_blocked_and_aliases(repo):
    from app.history.teams import TeamResolver, norm
    assert norm("Kasımpaşa SK") == "kasimpasa sk" and norm("Wisła Kraków") == "wisla krakow"
    r = TeamResolver(repo)
    assert r.resolve("Cercle Brugge", "Belgium") != r.resolve("Club Brugge KV", "Belgium")
    assert r.resolve("Los Angeles Galaxy", "USA") != r.resolve("Los Angeles FC", "USA")
    assert r.resolve("Wuhan FC", "China") != r.resolve("Wuhan Three Towns", "China")
    assert r.resolve("Guangzhou City", "China") != r.resolve("Guangzhou FC", "China")
    assert r.resolve("Lausanne", "Switzerland") != r.resolve("Lausanne Ouchy", "Switzerland")
    assert r.resolve("Athletic MG", "Brazil") != r.resolve("Atletico-MG", "Brazil")
    assert r.resolve("Wisla", "Poland") != r.resolve("Wisla Plock", "Poland")
    assert r.resolve("Heart of Midlothian", "Scotland") == r.resolve("Hearts", "Scotland")
    assert r.resolve("Buyuksehyr", "Turkey") == r.resolve("İstanbul Başakşehir", "Turkey")
    assert r.resolve("CR Flamengo", "Brazil") == r.resolve("Flamengo RJ", "Brazil")
    assert r.resolve("AE Lárissa", "Greece") == r.resolve("Larisa", "Greece")
    assert r.resolve("Kasımpaşa SK", "Turkey") == r.resolve("Kasimpasa", "Turkey")


def test_club_directory_is_authoritative(repo):
    from app.history.teams import ClubDirectory, TeamResolver, get_directory
    d = get_directory()
    assert len(d.alias["England"]) > 300                         # bảng chuẩn đã được nạp
    assert d.club_id("Sp Lisbon", "Portugal") == d.club_id("Sporting CP", "Portugal") is not None
    assert d.club_id("Cercle Brugge", "Belgium") != d.club_id("Club Brugge KV", "Belgium")
    assert d.club_id("Cardiff City", "Wales") == d.club_id("Cardiff City", "England")   # Wales dùng chung nhóm với England
    r = TeamResolver(repo)
    a = r.resolve("Sp Lisbon", "Portugal")
    assert r.resolve("Sporting Clube de Portugal", "Portugal") == a == r.resolve("Sporting CP", "Portugal")
    assert r.resolve("Cercle Brugge", "Belgium") != r.resolve("Club Brugge", "Belgium")
    # tên trùng cho nhiều CLB trong một nước thì bị bỏ khỏi bảng (không đoán)
    small = ClubDirectory([("X", "Alpha FC", "Al"), ("X", "Beta FC", "Al"), ("X", "Beta FC", "Beta FC"), ("X", "Alpha FC", "Alpha FC")])
    assert small.club_id("Al", "X") is None and small.club_id("Alpha", "X") is not None


def test_directory_team_found_when_db_has_other_spelling(repo):
    from app.data_providers.base import TeamDTO
    from app.history.teams import TeamResolver
    tid = repo.upsert_team("football-data.org", TeamDTO(external_id="9001", name="Sporting Clube de Portugal"))
    r = TeamResolver(repo)
    r.countries[tid] = {"Portugal"}
    r._rebuild()
    assert r.resolve("Sp Lisbon", "Portugal") == tid
