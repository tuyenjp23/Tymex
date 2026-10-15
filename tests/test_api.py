from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.ai_analysis.writer import AIError, AnthropicWriter
from app.main import create_app
from tests import fixtures
from tests.test_services import FakeProvider


class FakeWriter:
    model = "fake-model"

    def __init__(self):
        self.calls = 0
        self.payloads = []

    def generate(self, payload):
        self.calls += 1
        self.payloads.append(payload)
        return "# Bài kiểm thử\nNội dung."


@pytest.fixture
def real_now():
    return datetime.now(timezone.utc)


@pytest.fixture
def client(settings, real_now):
    app = create_app(settings, provider=FakeProvider(real_now), writer=FakeWriter(), start_scheduler=False)
    fixtures.seed(app.state.container.repo, real_now)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def empty_client(settings):
    from app.data_providers.football_data_org import FootballDataOrgProvider
    app = create_app(settings, provider=FootballDataOrgProvider(""), start_scheduler=False)
    with TestClient(app) as c:
        yield c


def test_app_starts_without_api_key_and_explains(empty_client):
    s = empty_client.get("/api/status").json()
    assert s["has_api_key"] is False and s["has_data"] is False and s["ai_configured"] is False
    r = empty_client.post("/api/sync", json={})
    assert r.status_code == 400 and r.json()["error"]["code"] == "not_configured"
    assert empty_client.get("/api/matches").json()["matches"] == []
    assert empty_client.get("/").status_code == 200       # giao diện vẫn tải được


def test_status_flags_test_data(client):
    s = client.get("/api/status").json()
    assert s["is_test_data"] is True and s["has_data"] is True
    assert s["counts"]["matches"] == 90


def test_matches_today_and_tomorrow_and_scopes(client):
    today = client.get("/api/matches?day=today&tz=Asia/Tokyo").json()
    assert today["tz"] == "Asia/Tokyo"
    tomorrow = client.get("/api/matches?day=tomorrow&tz=Asia/Tokyo").json()
    assert today["matches"] and tomorrow["matches"]
    assert {m["id"] for m in today["matches"]}.isdisjoint({m["id"] for m in tomorrow["matches"]})
    assert all(m["is_test_data"] for m in today["matches"])
    fin = client.get("/api/matches?scope=finished&limit=5").json()["matches"]
    assert len(fin) == 5 and all(m["status"] == "FINISHED" for m in fin)
    assert [m["utc_date"] for m in fin] == sorted([m["utc_date"] for m in fin], reverse=True)
    up = client.get("/api/matches?scope=upcoming&limit=500").json()["matches"]
    assert up and all(m["status"] in ("SCHEDULED", "TIMED") for m in up)


def test_matches_filters_and_validation(client):
    ms = client.get("/api/matches?q=alpha&limit=500").json()["matches"]
    assert ms and all("Alpha" in m["home_name"] + m["away_name"] for m in ms)
    assert client.get("/api/matches?tz=Mars/Base").status_code == 400
    assert client.get("/api/matches?day=banana").status_code == 400
    assert client.get("/api/matches?day=2025-02-30").status_code == 400
    assert client.get("/api/matches?scope=zzz").status_code == 422
    assert client.get("/api/matches?limit=0").status_code == 422
    assert client.get("/api/matches/999999").status_code == 404


def test_timezone_shifts_day_boundaries(client):
    tokyo = client.get("/api/matches?day=today&tz=Asia/Tokyo").json()["range"]
    la = client.get("/api/matches?day=today&tz=America/Los_Angeles").json()["range"]
    assert tokyo["from"] != la["from"]


def upcoming_match(client):
    return client.get("/api/matches?scope=upcoming&limit=1").json()["matches"][0]


def test_analysis_for_upcoming_match_has_all_sections_and_stores_prediction(client):
    m = upcoming_match(client)
    a = client.get(f"/api/matches/{m['id']}/analysis").json()
    for key in ("form", "venue", "head_to_head", "advanced", "prediction", "conclusions", "match"):
        assert key in a
    assert len(a["form"]["home"]["games"]) == 5 and a["form"]["home"]["summary"]["played"] == 5
    kickoff = a["match"]["utc_date"]
    assert all(g["utc_date"] < kickoff for g in a["form"]["home"]["games"] + a["form"]["away"]["games"])
    p = a["prediction"]
    assert p["available"] and p["mode"] == "stored_pre_match"
    assert round(sum(p["percent"].values()), 6) == 100.0
    assert a["advanced"]["available"] is False and "xG" in a["advanced"]["reason"]
    assert a["is_test_data"] is True
    assert any("chấn thương" in g.lower() for g in a["conclusions"]["data_gaps"])
    assert all("fact" in i and "inference" in i for i in a["conclusions"]["items"])
    preds = client.get("/api/predictions?kind=live").json()["predictions"]
    assert any(x["match_id"] == m["id"] for x in preds)


def test_form_n_10(client):
    m = upcoming_match(client)
    a = client.get(f"/api/matches/{m['id']}/analysis?form_n=10").json()
    assert a["form_n"] == 10 and len(a["form"]["home"]["games"]) == 10


def test_finished_match_analysis_is_marked_as_recomputed_not_stored(client):
    fin = client.get("/api/matches?scope=finished&limit=1").json()["matches"][0]
    a = client.get(f"/api/matches/{fin['id']}/analysis").json()
    assert a["prediction"]["mode"] in ("recomputed_pre_match", "unavailable")
    if a["prediction"]["mode"] == "recomputed_pre_match":
        assert "KHÔNG phải dự đoán đã được lưu" in a["prediction"]["label"]
    assert client.get("/api/predictions?kind=live").json()["predictions"] == []   # không lưu hồi tố


def test_h2h_in_api_never_exceeds_available_data(client):
    m = upcoming_match(client)
    h = client.get(f"/api/matches/{m['id']}/analysis").json()["head_to_head"]
    assert h["available"] == len(h["games"]) <= 10


def test_standings_teams_leagues(client):
    leagues = client.get("/api/leagues").json()["leagues"]
    st = client.get(f"/api/standings?league_id={leagues[0]['id']}").json()
    assert st["groups"][0]["rows"][0]["position"] == 1
    assert len(client.get("/api/teams").json()["teams"]) == 10
    assert client.get("/api/standings?league_id=999").status_code == 404
    assert client.get("/api/standings").status_code == 422


def test_backtest_and_summary_endpoints(client):
    r = client.post("/api/predictions/backtest", json={"limit": 50}).json()
    assert r["evaluated"] > 0
    s = client.get("/api/predictions/summary?kind=backtest").json()
    assert s["overall"]["n"] == r["evaluated"] and s["kind"] == "backtest"
    live = client.get("/api/predictions/summary?kind=live").json()
    assert live["overall"]["n"] == 0
    assert client.post("/api/predictions/backtest", json={"limit": 9999}).status_code == 422


def test_sync_endpoints(client):
    r = client.post("/api/sync", json={"force": True})
    assert r.status_code == 202
    import time
    for _ in range(100):
        st = client.get("/api/sync/status").json()
        if not st["running"] and st["summary"]:
            break
        time.sleep(0.05)
    assert st["summary"]["ok"] is True
    assert client.get("/api/sync/logs").json()["logs"][0]["status"] in ("ok", "skipped")


def test_settings_never_leak_the_key_and_save_it(client, settings, monkeypatch):
    monkeypatch.setenv("FOOTBALL_DATA_API_KEY", "")
    r = client.post("/api/settings/football-key", json={"api_key": "abcd1234efgh5678ijkl"})
    assert r.status_code == 200 and r.json()["api_key_hint"].endswith("ijkl")
    s = client.get("/api/settings").json()
    assert "abcd1234efgh5678ijkl" not in str(s) and s["api_key_hint"].endswith("ijkl")
    assert "abcd1234efgh5678ijkl" in settings.env_path.read_text()
    assert "abcd1234efgh5678ijkl" not in client.get("/api/status").text
    assert client.post("/api/settings/football-key", json={"api_key": "short"}).status_code == 422
    assert client.post("/api/settings/football-key", json={"api_key": "bad key with spaces!!"}).status_code in (400, 422)
    bad = client.post("/api/settings/leagues", json={"codes": ["pl", "xx; DROP"]})
    assert bad.status_code == 400
    ok = client.post("/api/settings/leagues", json={"codes": ["pl", "sa", "PL"]}).json()
    assert ok["league_codes"] == ["PL", "SA"]


def test_ai_article_flow(client):
    m = upcoming_match(client)
    assert client.get(f"/api/matches/{m['id']}/article").json()["article"] is None
    a1 = client.post(f"/api/matches/{m['id']}/article").json()["article"]
    assert a1["cached"] is False and a1["content"].startswith("# Bài kiểm thử")
    a2 = client.post(f"/api/matches/{m['id']}/article").json()["article"]
    assert a2["cached"] is True and a2["id"] == a1["id"]                 # dữ liệu không đổi => không gọi AI lại
    a3 = client.post(f"/api/matches/{m['id']}/article?force=true").json()["article"]
    assert a3["id"] != a1["id"]
    got = client.get(f"/api/matches/{m['id']}/article").json()["article"]
    assert got["id"] == a3["id"] and got["is_stale"] is False
    assert client.post("/api/matches/999999/article").status_code == 404


def test_ai_payload_has_only_computed_data(client):
    ct = client.app.state.container
    m = upcoming_match(client)
    client.post(f"/api/matches/{m['id']}/article")
    payload = ct.articles.writer.payloads[0]
    assert set(payload) >= {"match", "form", "venue", "head_to_head", "prediction", "conclusions"}
    assert "chấn thương" in str(payload["not_available"]).lower() or payload["not_available"]


def test_ai_not_configured_gives_clear_error(empty_client):
    assert empty_client.get("/api/status").json()["ai_configured"] is False


def test_anthropic_writer_error_handling():
    import httpx
    def make(status, body=None):
        return AnthropicWriter("k", "m", transport=httpx.MockTransport(lambda r: httpx.Response(status, json=body or {})))
    assert make(200, {"content": [{"type": "text", "text": "Xin chào"}]}).generate({}) == "Xin chào"
    for status in (401, 429, 500):
        with pytest.raises(AIError):
            make(status).generate({})
    with pytest.raises(AIError):
        make(200, {"content": []}).generate({})


# ---------------------------------------------------------------------- chỉ-máy-chủ cho thao tác tốn tài nguyên
def test_costly_actions_are_local_only(client):
    """Điện thoại cùng Wi-Fi chỉ được xem: không được kích hoạt đồng bộ, backtest hay viết bài AI."""
    lan = {"host": "192.168.1.20:8000"}
    assert client.post("/api/sync", json={}, headers=lan).status_code == 403
    assert client.post("/api/predictions/backtest", json={}, headers=lan).status_code == 403
    assert client.post("/api/matches/1/article", headers=lan).status_code == 403
    assert client.get("/api/status", headers=lan).status_code == 200   # xem vẫn được


def test_dns_rebinding_host_is_rejected(client):
    r = client.post("/api/settings/test-key", headers={"host": "evil.example.com"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "local_only"
