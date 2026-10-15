from datetime import timedelta

import pytest

from app.data_providers.base import (FootballDataProvider, ProviderAccessError, ProviderAuthError,
                                     ProviderConnectionError, ProviderRateLimitError)
from app.prediction.poisson import MODEL_VERSION
from app.services.prediction_service import PredictionService
from app.services.sync_service import SyncService
from app.utils import to_iso
from tests import fixtures


class FakeProvider(FootballDataProvider):
    name = "fixture"

    def __init__(self, now, fail=None, configured=True):
        self.now, self.fail, self.configured = now, fail, configured
        self.calls = []

    def is_configured(self):
        return self.configured

    def get_matches(self, code, season=None):
        self.calls.append(("matches", code, season))
        if self.fail and self.fail.get(code):
            raise self.fail[code]
        if season and season != 2025:
            raise ProviderAccessError("không có mùa trước")
        return fixtures.make_league(), fixtures.make_matches(self.now)

    def get_standings(self, code):
        self.calls.append(("standings", code))
        return 2025, []


def seeded(repo, now):
    fixtures.seed(repo, now)
    return PredictionService(repo, now=lambda: now)


# ---------------------------------------------------------------- database
def test_database_roundtrip_and_upsert_is_idempotent(repo, now):
    fixtures.seed(repo, now)
    before = repo.counts()
    fixtures.seed(repo, now)
    assert repo.counts() == before and before["matches"] == 90 and before["teams"] == 10
    m = repo.query_matches(limit=5)[0]
    assert m["home_name"].startswith("Test FC") and m["league_name"].startswith("Giải Kiểm Thử")


def test_query_filters(repo, now):
    fixtures.seed(repo, now)
    team = repo.list_teams(q="alpha")[0]
    ms = repo.query_matches(team_id=team["id"], limit=500)
    assert len(ms) == 18 and all(team["id"] in (m["home_team_id"], m["away_team_id"]) for m in ms)
    fin = repo.finished_matches(before=to_iso(now))
    assert fin and all(m["status"] == "FINISHED" and m["utc_date"] < to_iso(now) for m in fin)
    assert repo.query_matches(statuses=["FINISHED"], q="ALPHA", limit=500)


def test_accent_insensitive_team_search(repo):
    from app.data_providers.base import TeamDTO
    repo.upsert_team("fixture", TeamDTO("1", "Atlético Test", "Atlético", "ATL"))
    assert repo.list_teams(q="atletico")[0]["name"] == "Atlético Test"


# ---------------------------------------------------------------- dự đoán
def test_prediction_saved_before_kickoff_and_not_duplicated(repo, now):
    svc = seeded(repo, now)
    upcoming = [m for m in repo.query_matches(statuses=["SCHEDULED"], limit=500) if m["utc_date"] > to_iso(now)]
    match = upcoming[0]
    p1 = svc.ensure_stored(match)
    assert p1 and p1["kind"] == "live" and p1["created_at"] < match["utc_date"]
    assert p1["model_version"] == MODEL_VERSION
    assert round(p1["p_home"] + p1["p_draw"] + p1["p_away"], 9) == 1.0
    d = p1["details"]["percent"]
    assert round(d["home"] + d["draw"] + d["away"], 6) == 100.0
    p2 = svc.ensure_stored(match)           # dữ liệu không đổi => không tạo bản trùng
    assert p2["id"] == p1["id"] and repo.count_predictions("live") == 1


def test_new_data_creates_new_prediction_but_keeps_old(repo, now):
    svc = seeded(repo, now)
    match = [m for m in repo.query_matches(statuses=["SCHEDULED"], limit=500) if m["utc_date"] > to_iso(now)][0]
    first = svc.ensure_stored(match)
    # có thêm một trận vừa kết thúc => dấu vân tay dữ liệu đổi
    from app.data_providers.base import MatchDTO
    league_id = match["league_id"]
    t = repo.list_teams()
    from app.data_providers.base import TeamDTO
    extra = MatchDTO("9999", 2025, 99, "REGULAR_SEASON", to_iso(now - timedelta(hours=5)), "FINISHED",
                     TeamDTO(t[0]["external_id"], t[0]["name"]), TeamDTO(t[1]["external_id"], t[1]["name"]), 3, 0)
    repo.upsert_matches("fixture", league_id, [extra])
    second = svc.ensure_stored(match)
    assert second["id"] != first["id"] and repo.count_predictions("live") == 2   # bản cũ vẫn còn


def test_no_prediction_stored_when_data_insufficient(repo, now):
    from app.data_providers.base import LeagueDTO, MatchDTO, TeamDTO
    lid = repo.upsert_league("fixture", LeagueDTO("X", "Giải rỗng"))
    ko = to_iso(now + timedelta(days=1))
    repo.upsert_matches("fixture", lid, [MatchDTO("1", 2025, 1, None, ko, "SCHEDULED", TeamDTO("1", "A"), TeamDTO("2", "B"))])
    svc = PredictionService(repo, now=lambda: now)
    assert svc.ensure_stored(repo.query_matches()[0]) is None
    assert repo.count_predictions("live") == 0


def test_started_match_never_gets_a_new_live_prediction(repo, now):
    svc = seeded(repo, now)
    finished = repo.finished_matches(limit=1)[0]
    assert svc.ensure_stored(finished) is None and repo.count_predictions("live") == 0


def test_results_scored_and_history_keeps_wrong_predictions(repo, now):
    svc = seeded(repo, now)
    # lập dự đoán cho một trận sắp đá, sau đó "trận kết thúc" ở lần đồng bộ sau
    match = [m for m in repo.query_matches(statuses=["SCHEDULED"], limit=500) if m["utc_date"] > to_iso(now)][0]
    pred = svc.ensure_stored(match)
    from app.data_providers.base import MatchDTO, TeamDTO
    repo.upsert_matches("fixture", match["league_id"], [MatchDTO(
        _ext(repo, match["id"])["external_id"], 2025, match["matchday"], None, match["utc_date"],
        "FINISHED", TeamDTO(*_team(repo, match["home_team_id"])), TeamDTO(*_team(repo, match["away_team_id"])), 0, 4)])
    later = PredictionService(repo, now=lambda: now + timedelta(days=10))
    assert later.resolve_results() == 1
    assert later.resolve_results() == 0     # idempotent
    rows = repo.list_predictions(kind="live")
    assert len(rows) == 1 and rows[0]["actual_outcome"] == "A" and rows[0]["brier"] is not None
    s = later.summary("live")
    assert s["overall"]["n"] == 1 and s["total_predictions"] == 1
    assert pred["id"] == rows[0]["id"]


def _ext(repo, match_id):
    with repo.db.connect() as c:
        return dict(c.execute("SELECT external_id FROM matches WHERE id=?", (match_id,)).fetchone())


def _team(repo, team_id):
    t = repo.get_team(team_id)
    return t["external_id"], t["name"]


def test_backtest_uses_only_pre_match_data_and_is_separate_from_live(repo, now):
    svc = seeded(repo, now)
    res = svc.backtest(limit=60)
    assert res["evaluated"] > 0
    assert repo.count_predictions("live") == 0 and repo.count_predictions("backtest") == res["evaluated"]
    assert svc.backtest(limit=60)["evaluated"] == 0     # không chạy trùng
    s = svc.summary("backtest")
    assert s["overall"]["n"] == res["evaluated"] and 0 <= s["overall"]["brier"] <= 2


# ---------------------------------------------------------------- đồng bộ
def make_sync(repo, settings, now, **kw):
    provider = FakeProvider(now, **kw)
    return provider, SyncService(repo, provider, settings, PredictionService(repo, now=lambda: now), now=lambda: now)


def test_sync_stores_data_logs_and_generates_predictions(repo, settings, now):
    provider, sync = make_sync(repo, settings, now)
    out = sync.run()
    assert out["ok"] and out["matches"] > 0 and out["predictions_created"] > 0
    assert repo.counts()["matches"] == 90
    logs = repo.list_sync_logs()
    assert logs[0]["status"] == "ok" and repo.last_sync_overall()
    assert ("matches", "TST", 2024) in provider.calls       # mùa trước bị từ chối nhưng không làm hỏng đồng bộ
    assert sync.status()["running"] is False and sync.status()["leagues"][0]["state"] == "ok"


def test_sync_uses_cache_unless_forced(repo, settings, now):
    provider, sync = make_sync(repo, settings, now)
    sync.run()
    n = len(provider.calls)
    out = sync.run()
    assert len(provider.calls) == n and out["matches"] == 0            # không gọi API lại
    assert sync.status()["leagues"][0]["state"] == "skipped"
    sync.run(force=True)
    assert len(provider.calls) > n


def test_sync_without_key_does_not_crash(repo, settings, now):
    _, sync = make_sync(repo, settings, now, configured=False)
    out = sync.run()
    assert out["ok"] is False and out["error_code"] == "not_configured"


@pytest.mark.parametrize("exc,code", [(ProviderAuthError("sai khóa"), "auth_error"),
                                       (ProviderRateLimitError("quá tải"), "rate_limited")])
def test_sync_aborts_on_auth_or_rate_limit(repo, settings, now, exc, code):
    settings.league_codes = ["TST", "TS2"]
    provider, sync = make_sync(repo, settings, now, fail={"TST": exc})
    out = sync.run()
    assert out["ok"] is False and out["error_code"] == code
    assert not any(c[1] == "TS2" for c in provider.calls)          # dừng, không gọi tiếp các giải khác
    log = repo.list_sync_logs()[0]
    assert log["status"] == "error" and log["error_code"] == code


def test_sync_continues_after_connection_error(repo, settings, now):
    settings.league_codes = ["BAD", "TST"]
    _, sync = make_sync(repo, settings, now, fail={"BAD": ProviderConnectionError("mất mạng")})
    out = sync.run()
    assert out["ok"] is False and out["leagues_synced"] == 1 and repo.counts()["matches"] == 90


def test_concurrent_sync_is_rejected(repo, settings, now):
    _, sync = make_sync(repo, settings, now)
    assert sync._lock.acquire(blocking=False)
    try:
        assert sync.start_background() is False
        assert sync.run()["error_code"] == "already_running"
    finally:
        sync._lock.release()
