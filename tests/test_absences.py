from datetime import timedelta

import httpx

from tests.test_history import _upcoming_setup
from app.analytics.availability import build_availability_block, team_penalty
from app.odds.absences import refresh_absences
from app.odds.api_football import ApiFootball
from app.utils import to_iso, utcnow


def _row(team, player, typ, reason, kick):
    return {"player": {"id": 1, "name": player, "type": typ, "reason": reason}, "team": {"name": team}, "fixture": {"id": 5, "date": kick}}


class Client:
    def __init__(self, rows):
        self.rows, self.log = rows, []

    def get(self, url, params=None, headers=None):
        self.log.append((url.rsplit("/", 1)[1], dict(params)))
        return httpx.Response(200, headers={"x-ratelimit-requests-remaining": "88"}, json={"errors": [], "response": self.rows})


def test_injuries_parses_and_skips_unknown_types():
    c = Client([_row("Fulham", "A Player", "Missing Fixture", "Knee Injury", "2026-10-17T14:00:00+00:00"),
                _row("Fulham", "B Player", "Questionable", "Illness", "2026-10-17T14:00:00+00:00"),
                _row("Fulham", "C Player", "Something else", None, "2026-10-17T14:00:00+00:00")])
    items, info = ApiFootball("K", client=c).injuries("PL", "2026-10-17", 2026)
    assert [(i["player"], i["kind"]) for i in items] == [("A Player", "out"), ("B Player", "doubtful")]
    assert info == {"remaining": 88, "calls": 1} and c.log[0][1]["league"] == 39 and c.log[0][1]["date"] == "2026-10-17"


def test_refresh_absences_saves_and_respects_interval(repo):
    now = utcnow()
    kick = to_iso(now + timedelta(hours=2))
    _upcoming_setup(repo, kick)
    c = Client([_row("Fulham", "A Player", "Missing Fixture", "Knee", kick), _row("Manchester United", "B Player", "Questionable", "Knock", kick),
                _row("Nobody FC", "Z", "Missing Fixture", None, kick)])
    api = ApiFootball("K", client=c)
    out = refresh_absences(repo, api, now=now, log=lambda s: None)
    assert out["calls"] == 1 and out["matched"] == 2 and out["unmatched"] == ["Nobody FC"]
    m = repo.query_matches(statuses=("TIMED",))[0]
    rows = repo.get_absences(m["id"])
    assert {(r["player"], r["kind"]) for r in rows} == {("A Player", "out"), ("B Player", "doubtful")}
    out2 = refresh_absences(repo, api, now=now, log=lambda s: None)
    assert out2["calls"] == 0 and len(c.log) == 1


def test_refresh_absences_stops_on_quota_and_no_key(repo):
    now = utcnow()
    _upcoming_setup(repo, to_iso(now + timedelta(hours=2)))
    assert refresh_absences(repo, ApiFootball(""), now=now)["skipped"]

    class Q:
        def get(self, *a, **k):
            return httpx.Response(429, json={})
    out = refresh_absences(repo, ApiFootball("K", client=Q()), now=now, log=lambda s: None)
    assert out["calls"] == 0 and out["errors"] and repo.get_absences(1) == []


MATCH = {"home_team_id": 1, "away_team_id": 2, "home_name": "H", "away_name": "A"}
PRED = {"available": True, "lambda_home": 1.6, "lambda_away": 1.1, "p_home": 0.5, "p_draw": 0.25, "p_away": 0.25}


def _abs(tid, n, kind="out"):
    return [{"team_id": tid, "player": f"P{tid}{kind}{i}", "kind": kind, "reason": None, "source": "api-football", "updated_at": "2026-10-17T10:00:00Z"} for i in range(n)]


def test_availability_block_adjusts_in_the_expected_direction():
    b = build_availability_block(_abs(1, 3), PRED, MATCH, upcoming=True)
    assert b["available"] and b["adjusted"]["after"]["home"] < b["adjusted"]["before"]["home"]
    assert abs(sum(b["adjusted"]["after"].values()) - 1) < 1e-6 and "CHƯA" in b["note"]
    assert team_penalty(50, 50) == 0.12                      # có trần


def test_availability_block_no_news_or_finished_match_and_toggle(monkeypatch):
    assert not build_availability_block([], PRED, MATCH, upcoming=True)["available"]
    assert not build_availability_block(_abs(1, 1), PRED, MATCH, upcoming=False)["available"]
    monkeypatch.setenv("AVAILABILITY_ADJUST", "0")
    assert build_availability_block(_abs(1, 3), PRED, MATCH, upcoming=True)["adjusted"] is None
