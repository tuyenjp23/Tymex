from app.data_providers.base import LeagueDTO, TeamDTO
from app.history.runner import RESOLVER_VERSION, SRC_CO_UK, run_history
from app.history.teams import TeamResolver, is_reserve, norm

P = "football-data.org"


def _teams(repo, names):
    repo.upsert_league(P, LeagueDTO(code="PL", name="Premier League"))
    for i, n in enumerate(names):
        repo.upsert_team(P, TeamDTO(external_id=str(i + 1), name=n))


def test_is_reserve():
    assert is_reserve(norm("Real Sociedad B")) and is_reserve(norm("Villarreal II"))
    assert not is_reserve(norm("Real Sociedad de Fútbol")) and not is_reserve(norm("Villarreal CF"))
    assert not is_reserve("b")        # một từ đơn lẻ không phải đội dự bị


def test_reserve_team_never_merged_with_first_team(repo):
    _teams(repo, ["Real Sociedad de Fútbol", "Villarreal CF"])
    r = TeamResolver(repo)
    main = r.resolve("Sociedad")
    assert r.names[main] == "Real Sociedad de Fútbol"
    b1 = r.resolve("Real Sociedad B")            # openfootball
    b2 = r.resolve("Sociedad B")                 # football-data.co.uk
    assert b1 != main and b1 == b2               # đội B là một đội riêng, hai cách viết cùng một đội
    assert r.resolve("Sociedad") == main         # có đội B rồi vẫn không bị ghép nhầm vào B
    assert r.resolve("Villarreal B") not in (r.resolve("Villarreal"),)
    assert r.names[r.resolve("Villarreal")] == "Villarreal CF"


def test_similar_but_different_clubs_are_not_merged(repo):
    _teams(repo, ["Reggina 1914"])
    r = TeamResolver(repo)
    tid = r.resolve("Reggiana")
    assert r.names[tid] == "Reggiana" and "Reggiana" in r.created


def test_reset_runs_once_and_removes_only_history_matches(repo):
    lid = repo.upsert_league(P, LeagueDTO(code="PL", name="Premier League"))
    a = repo.upsert_team(P, TeamDTO(external_id="1", name="Alpha FC"))
    b = repo.upsert_team(P, TeamDTO(external_id="2", name="Beta FC"))
    m = {"external_id": "h1", "season": 2023, "matchday": 1, "utc_date": "2023-08-12T14:00:00Z", "status": "FINISHED",
         "home_score": 1, "away_score": 0, "winner": "HOME_TEAM"}
    mid, _ = repo.add_history_match(SRC_CO_UK, lid, m, a, b)
    repo.save_odds(mid, "x", 2.0, 3.0, 4.0)
    run_history(repo, seasons=1, league_codes=[], fetch=lambda url: None, log=lambda s: None)   # lần đầu: xóa
    assert repo.get_odds(mid) is None and repo.history_import_done("resolver", "version", RESOLVER_VERSION)
    mid2, _ = repo.add_history_match(SRC_CO_UK, lid, m, a, b)
    run_history(repo, seasons=1, league_codes=[], fetch=lambda url: None, log=lambda s: None)   # lần hai: không xóa nữa
    assert repo.find_match_near(lid, a, b, "2023-08-01T00:00:00Z", "2023-09-01T00:00:00Z")["id"] == mid2


def test_odds_runner_explains_why_it_made_no_calls(repo):
    from app.odds.runner import refresh_upcoming_odds

    class Dummy:
        name = "dummy"; max_calls_per_run = 1; min_remaining = 0
        def is_configured(self): return True
        def fetch(self, *a, **k): raise AssertionError("không được gọi khi không có trận sắp đá")

    res = refresh_upcoming_odds(repo, [Dummy()], log=lambda s: None)
    assert res["calls"] == 0 and any("không có trận nào sắp đá" in x for x in res["skipped"])
