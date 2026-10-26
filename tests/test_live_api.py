"""Kiểm thử endpoint dự đoán trực tiếp /api/matches/{id}/live-prediction. Dữ liệu giả (fixtures),
không gọi API thật. Trận đang đá được thêm trực tiếp vào CSDL kiểm thử kèm một dự đoán trước trận đã lưu."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.data_providers.base import MatchDTO
from app.main import create_app
from app.utils import to_iso
from tests import fixtures
from tests.test_services import FakeProvider

PRED_OUTPUT = {"lambda_home": 1.7, "lambda_away": 1.1, "p_home": 0.52, "p_draw": 0.26, "p_away": 0.22,
               "predicted_score": {"home": 2, "away": 1}}


@pytest.fixture
def live_setup(settings):
    now = datetime.now(timezone.utc)
    app = create_app(settings, provider=FakeProvider(now), start_scheduler=False)
    repo = app.state.container.repo
    fixtures.seed(repo, now)
    league_id = repo.get_league_by_code("fixture", "TST")["id"]
    teams = fixtures.make_teams()
    kickoff = now - timedelta(minutes=40)

    def add_live(ext_id, with_prediction):
        repo.upsert_matches("fixture", league_id, [MatchDTO(
            external_id=ext_id, season=2025, matchday=99, stage="REGULAR_SEASON", utc_date=to_iso(kickoff),
            status="IN_PLAY", home=teams[0], away=teams[1], home_score=1, away_score=0, winner=None)])
        mid = repo.query_matches(statuses=["IN_PLAY"], q=teams[0].name)[-1]["id"]
        if with_prediction:
            repo.save_prediction(mid, "live", "poisson-v2-dc", to_iso(kickoff - timedelta(hours=2)), "fp-test", PRED_OUTPUT)
        return mid

    ids = {"with_pred": add_live("live-1", True), "no_pred": add_live("live-2", False)}
    with TestClient(app) as client:
        yield client, ids


def test_live_prediction_uses_stored_prematch_lambdas(live_setup):
    client, ids = live_setup
    r = client.get(f"/api/matches/{ids['with_pred']}/live-prediction").json()
    assert r["available"] is True
    assert r["minute_estimated"] is True
    assert 35 <= r["minute"] <= 45                       # bóng lăn 40 phút trước, chưa qua nghỉ giữa hiệp
    assert any("ƯỚC TÍNH" in n for n in r["notes"])
    assert r["pre_match_prediction"]["lambda_home"] == 1.7
    pc = r["percent"]
    assert round(pc["home"] + pc["draw"] + pc["away"], 6) == 100.0
    assert pc["home"] > 52                                # đang dẫn 1-0 nên cao hơn xác suất trước trận
    assert r["top_final_scores"][0]["home"] >= 1
    assert r["match"]["home_score"] == 1 and r["match"]["away_score"] == 0


def test_live_prediction_with_explicit_minute(live_setup):
    client, ids = live_setup
    r = client.get(f"/api/matches/{ids['with_pred']}/live-prediction?minute=88").json()
    assert r["available"] is True and r["minute"] == 88.0 and r["minute_estimated"] is False
    assert r["percent"]["home"] > 90                     # dẫn 1-0 ở phút 88 thì gần như chắc thắng


def test_live_prediction_without_stored_prediction_never_invents_lambdas(live_setup):
    client, ids = live_setup
    r = client.get(f"/api/matches/{ids['no_pred']}/live-prediction").json()
    assert r["available"] is False and "không tự bịa" in r["reason"]
    assert "percent" not in r and "lambda_home_remaining" not in r


def test_live_prediction_rejects_not_in_play_and_missing_match(live_setup):
    client, _ = live_setup
    upcoming = client.get("/api/matches?scope=upcoming&limit=1").json()["matches"][0]
    r = client.get(f"/api/matches/{upcoming['id']}/live-prediction").json()
    assert r["available"] is False and "không đang diễn ra" in r["reason"]
    assert client.get("/api/matches/999999/live-prediction").status_code == 404
    assert client.get(f"/api/matches/{upcoming['id']}/live-prediction?minute=999").status_code == 422
