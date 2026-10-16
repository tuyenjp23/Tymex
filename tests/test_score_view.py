from app.analytics.conclusions import build_conclusions
from app.analytics.score_view import score_view
from app.history.leagues import HIST_LEAGUES, current_season
from app.history.sources import openfootball_url, parse_openfootball
from datetime import date


def test_score_view_top3_and_none():
    v = score_view(2.4, 0.6, "x")
    assert len(v["top"]) == 3 and v["top"][0]["home"] > v["top"][0]["away"]
    assert score_view(None, 1.0, "x") is None
    assert score_view(1.0, 1.0, "x")["top"][0]["prob"] > 0


def _summ(gf, ga):
    return {"played": 10, "points": 15, "wins": 4, "draws": 3, "losses": 3, "points_per_game": 1.5, "avg_goals_for": gf,
            "avg_goals_against": ga, "clean_sheets": 2, "failed_to_score": 1, "clean_sheet_rate": .2}


def test_each_conclusion_has_distinct_score():
    hf = {"summary": _summ(2.4, 0.8), "requested": 5}
    af = {"summary": _summ(0.9, 1.9), "requested": 5}
    hv = {"summary": _summ(2.6, 0.7)}; av = {"summary": _summ(0.7, 2.1)}
    h2h = {"summary": {"played": 5, "a_wins": 3, "b_wins": 1, "draws": 1, "a_goals": 9, "b_goals": 4}, "available": 5}
    pred = {"available": True, "percent": {"home": 70, "draw": 18, "away": 12}, "lambda_home": 2.2, "lambda_away": 0.8,
            "quality": {"reliability": "khá"}}
    out = build_conclusions("A", "B", hf, af, hv, av, h2h, pred, False)
    scored = [i for i in out["items"] if i.get("score")]
    assert len(scored) == 6
    assert all(len(i["score"]["top"]) == 3 for i in scored)
    assert len({(i["score"]["lambda_home"], i["score"]["lambda_away"]) for i in scored}) >= 4


def test_new_leagues_config_and_calendar_urls():
    codes = [x["code"] for x in HIST_LEAGUES]
    assert len(codes) == len(set(codes)) >= 24
    jp = next(x for x in HIST_LEAGUES if x["code"] == "JP1")
    assert current_season(jp, date(2026, 10, 15)) == 2026
    assert current_season(HIST_LEAGUES[0], date(2026, 10, 15)) == 2026 and current_season(HIST_LEAGUES[0], date(2026, 3, 1)) == 2025
    assert openfootball_url("jp.1", 2025, True).endswith("/2025/jp.1.json")
    assert openfootball_url("en.1", 2025).endswith("/2025-26/en.1.json")


def test_openfootball_list_score_format():
    txt = '{"matches":[{"round":"Matchday 1","date":"2025-03-29","time":"18:30","team1":"A","team2":"B","score":[0,0]}]}'
    r = parse_openfootball(txt, code="br.1", season=2025, tz="America/Sao_Paulo", today_iso="2026-01-01T00:00:00Z")
    assert len(r) == 1 and r[0]["home_score"] == 0 and r[0]["status"] == "FINISHED"


def test_same_name_different_country_not_merged(repo):
    from app.history.teams import TeamResolver
    r = TeamResolver(repo)
    ar = r.resolve("Santa Fe", "Argentina")
    co = r.resolve("Santa Fe", "Colombia")
    assert ar != co and r.resolve("Santa Fe", "Argentina") == ar and r.resolve("Santa Fe", "Colombia") == co
    assert r.resolve("Rangers FC", "Scotland") != r.resolve("Queens Park Rangers", "England")


def test_same_root_clubs_in_one_country_stay_separate(repo):
    from app.history.teams import TeamResolver
    r = TeamResolver(repo)
    assert r.resolve("Dundee United", "Scotland") != r.resolve("Dundee FC", "Scotland")
    assert r.resolve("Independiente Rivadavia", "Argentina") != r.resolve("Independiente", "Argentina")
    assert r.resolve("Yokohama F. Marinos", "Japan") != r.resolve("Yokohama FC", "Japan")
