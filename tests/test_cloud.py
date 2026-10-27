from types import SimpleNamespace

import httpx
import pytest

from app.cloud.export import dedupe_export_matches, publish
from app.cloud.supabase import SupabaseClient, SupabaseError
from app.main import build_container
from tests import fixtures


class FakeClient:
    """Thay SupabaseClient: ghi lại những gì được đẩy lên."""
    def __init__(self):
        self.tables = {}

    def upsert(self, table, rows, on_conflict, batch=300):
        self.tables.setdefault(table, []).extend(rows)
        return len(rows)


@pytest.fixture
def container(settings, now):
    c = build_container(settings, provider=None)
    fixtures.seed(c.repo, now)
    c.predictions.now = lambda: now
    return c


def test_publish_exports_everything_the_web_needs(container, now):
    client = FakeClient()
    stats = publish(container, client, now=now)
    t = client.tables
    assert stats["matches"] == 90 and len(t["matches"]) == 90
    row = t["matches"][0]
    assert {"id", "home_name", "away_name", "utc_date", "home_search", "away_search", "is_test_data"} <= set(row)
    assert all(set(r) == set(row) for r in t["matches"])           # PostgREST cần cùng bộ cột trong một lô
    assert t["analysis"] and set(t["analysis"][0]["payload"]) == {"5", "10"}
    a = t["analysis"][0]["payload"]["5"]
    assert a["match"]["home_name"] and "prediction" in a and "conclusions" in a
    keys = {r["key"] for r in t["kv"]}
    assert {"teams", "leagues", "status", "summary:live", "summary:backtest", "predictions:live", "predictions:backtest"} <= keys
    assert any(k.startswith("standings:") for k in keys)
    teams = next(r for r in t["kv"] if r["key"] == "teams")["payload"]["teams"]
    assert teams and "search" in teams[0] and "leagues" in teams[0]


def _fake_export_match(mid, league_id, provider, home, away, utc_date, *,
                       status="SCHEDULED", home_score=None, away_score=None):
    return {
        "id": mid, "league_id": league_id, "league_name": f"Giải {league_id}", "league_code": f"L{league_id}",
        "season": 2026, "matchday": 1, "stage": "REGULAR_SEASON", "utc_date": utc_date, "status": status,
        "home_team_id": mid * 10 + 1, "away_team_id": mid * 10 + 2,
        "home_name": home, "away_name": away, "home_short": None, "away_short": None,
        "home_crest": None, "away_crest": None, "home_score": home_score, "away_score": away_score,
        "home_ht": None, "away_ht": None, "winner": None, "provider": provider,
    }


def test_dedupe_export_matches_priority_and_non_duplicates():
    scored = _fake_export_match(20, 2, "openfootball", "Central Cordoba", "River Plate",
                                 "2026-10-20T20:00:00Z", status="FINISHED", home_score=2, away_score=1)
    unscored = _fake_export_match(10, 1, "football-data.org", "Central Córdoba FC", "River Plate CF",
                                  "2026-10-20T23:00:00Z")
    reverse = _fake_export_match(30, 1, "espn", "River Plate", "Central Córdoba",
                                 "2026-10-20T20:00:00Z", status="FINISHED", home_score=0, away_score=0)
    other_date = _fake_export_match(40, 1, "espn", "Central Córdoba", "River Plate",
                                    "2026-11-20T20:00:00Z")
    out, removed = dedupe_export_matches([unscored, scored, reverse, other_date])
    assert removed == 1
    assert [m["id"] for m in out] == [20, 30, 40]       # bản có tỷ số thắng; đảo chiều/khác ngày giữ nguyên
    assert out[0]["league_id"] == 2                      # giữ league_id của chính bản ghi được chọn

    canonical = _fake_export_match(99, 1, "football-data.org", "Alpha FC", "Beta Club", "2026-10-21T20:00:00Z")
    other_source = _fake_export_match(1, 2, "openfootball", "Alpha", "Beta", "2026-10-21T20:00:00Z")
    out2, removed2 = dedupe_export_matches([other_source, canonical])
    assert removed2 == 1 and out2[0]["id"] == 99         # ngang nhau về tỷ số/trạng thái -> ưu tiên nguồn chuẩn


def test_publish_merges_duplicate_matches_before_upsert(now, capsys):
    leagues = [{"id": 1, "provider": "football-data.org"}, {"id": 2, "provider": "openfootball"}]
    rows_by_league = {
        1: [
            _fake_export_match(10, 1, "espn", "Central Córdoba FC", "River Plate CF", "2026-10-20T20:00:00Z"),
            _fake_export_match(30, 1, "espn", "River Plate", "Central Córdoba", "2026-10-20T20:00:00Z",
                               status="FINISHED", home_score=0, away_score=0),
            _fake_export_match(40, 1, "espn", "Central Córdoba", "River Plate", "2026-11-20T20:00:00Z"),
        ],
        2: [
            _fake_export_match(20, 2, "openfootball", "Central Cordoba", "River Plate", "2026-10-20T23:00:00Z",
                               status="FINISHED", home_score=2, away_score=1),
        ],
    }

    class FakeRepo:
        def list_leagues(self):
            return leagues

        def query_matches(self, *, league_id, date_from, limit):
            return rows_by_league[league_id]

        def list_teams(self):
            return []

        def get_league(self, league_id):
            return next(lg for lg in leagues if lg["id"] == league_id)

        def get_standings(self, league_id):
            return []

        def list_predictions(self, *, kind, limit):
            return []

        def last_sync_overall(self):
            return None

        def counts(self):
            return {"leagues": 2, "teams": 4, "matches": 4, "predictions": 0}

    fake_container = SimpleNamespace(
        repo=FakeRepo(),
        analysis=SimpleNamespace(build=lambda match_id, n: None),
        predictions=SimpleNamespace(summary=lambda kind: {"overall": {"n": 0}}),
    )
    client = FakeClient()
    stats = publish(fake_container, client, now=now, run_backtest=False)
    exported = client.tables["matches"]
    assert stats["matches"] == 3 and len(exported) == 3
    kept = next(m for m in exported if m["utc_date"] == "2026-10-20T23:00:00Z")
    assert kept["id"] == 20 and kept["league_id"] == 2 and kept["home_score"] == 2
    assert {m["id"] for m in exported} == {20, 30, 40}
    assert "đã gộp 1 trận trùng" in capsys.readouterr().out


def test_publish_enriches_live_predictions_with_market(now):
    """Hàng dự đoán 'live' có kèo trong CSDL thì được gắn khối market gọn (xác suất tổng ≈ 1);
    hàng không có kèo giữ nguyên, và hàng gốc của repo không bị sửa tại chỗ."""
    leagues = [{"id": 1, "provider": "football-data.org"}]
    pred_with = {"id": 11, "match_id": 101, "kind": "live", "p_home": 0.5, "p_draw": 0.3, "p_away": 0.2}
    pred_without = {"id": 12, "match_id": 102, "kind": "live", "p_home": 0.4, "p_draw": 0.3, "p_away": 0.3}
    odds_by_match = {101: {"match_id": 101, "source": "the-odds-api:6", "odds_home": 2.0, "odds_draw": 3.4,
                           "odds_away": 3.8, "updated_at": "2026-10-26T00:00:00Z"}}

    class FakeRepo:
        def list_leagues(self):
            return leagues

        def query_matches(self, *, league_id, date_from, limit):
            return []

        def list_teams(self):
            return []

        def get_league(self, league_id):
            return leagues[0]

        def get_standings(self, league_id):
            return []

        def list_predictions(self, *, kind, limit):
            return [pred_with, pred_without] if kind == "live" else []

        def get_odds(self, match_id):
            return odds_by_match.get(match_id)

        def last_sync_overall(self):
            return None

        def counts(self):
            return {"leagues": 1, "teams": 0, "matches": 0, "predictions": 2}

    fake_container = SimpleNamespace(
        repo=FakeRepo(),
        analysis=SimpleNamespace(build=lambda match_id, n: None),
        predictions=SimpleNamespace(summary=lambda kind: {"overall": {"n": 0}}),
    )
    client = FakeClient()
    publish(fake_container, client, now=now, run_backtest=False)
    kv = {r["key"]: r["payload"] for r in client.tables["kv"]}
    rows = {r["match_id"]: r for r in kv["predictions:live"]["predictions"]}
    m = rows[101]["market"]
    assert m["odds"] == {"home": 2.0, "draw": 3.4, "away": 3.8}
    assert m["source"] == "the-odds-api:6" and m["updated_at"] == "2026-10-26T00:00:00Z"
    assert abs(m["probs"]["home"] + m["probs"]["draw"] + m["probs"]["away"] - 1) < 1e-3
    assert m["probs"]["home"] > m["probs"]["away"]
    assert "market" not in rows[102]                     # không có kèo → không thêm trường (tương thích ngược)
    assert "market" not in pred_with                     # không sửa tại chỗ hàng của repo
    bt_rows = kv["predictions:backtest"]["predictions"]
    assert all("market" not in r for r in bt_rows)       # chỉ enrich cho kind 'live'


def test_publish_runs_backtest_separately_from_live(container, now):
    client = FakeClient()
    publish(container, client, now=now)
    bt = next(r for r in client.tables["kv"] if r["key"] == "summary:backtest")["payload"]
    live = next(r for r in client.tables["kv"] if r["key"] == "summary:live")["payload"]
    assert bt["overall"]["n"] > 0 and live["overall"]["n"] == 0


def test_supabase_client_upsert_batches_and_hides_key():
    seen = []

    def handler(req: httpx.Request):
        seen.append(req)
        return httpx.Response(201)

    c = SupabaseClient("https://x.supabase.co/", "SECRETKEY", transport=httpx.MockTransport(handler))
    assert c.upsert("kv", [{"key": str(i), "payload": {}} for i in range(5)], "key", batch=2) == 5
    assert len(seen) == 3 and seen[0].url.params["on_conflict"] == "key"
    assert "merge-duplicates" in seen[0].headers["prefer"]

    bad = SupabaseClient("https://x.supabase.co", "SECRETKEY", transport=httpx.MockTransport(lambda r: httpx.Response(401, text="no")))
    with pytest.raises(SupabaseError) as exc:
        bad.upsert("kv", [{"key": "a"}], "key")
    assert "SECRETKEY" not in str(exc.value)


def test_storage_roundtrip_handles_missing_object():
    c = SupabaseClient("https://x.supabase.co", "k", transport=httpx.MockTransport(
        lambda r: httpx.Response(400, json={"statusCode": "404"}) if r.method == "GET" else httpx.Response(200)))
    assert c.download_object("b", "f.db") is None
    c.upload_object("b", "f.db", b"abc")
    with pytest.raises(SupabaseError):
        SupabaseClient("", "")


def test_new_style_secret_key_is_sent_only_as_apikey():
    seen = []
    c = SupabaseClient("https://x.supabase.co", "sb_secret_abc", transport=httpx.MockTransport(lambda r: (seen.append(r), httpx.Response(201))[1]))
    c.upsert("kv", [{"key": "a"}], "key")
    assert seen[0].headers["apikey"] == "sb_secret_abc" and "authorization" not in seen[0].headers
    legacy = []
    c2 = SupabaseClient("https://x.supabase.co", "eyJlegacy", transport=httpx.MockTransport(lambda r: (legacy.append(r), httpx.Response(201))[1]))
    c2.upsert("kv", [{"key": "a"}], "key")
    assert legacy[0].headers["authorization"] == "Bearer eyJlegacy"
