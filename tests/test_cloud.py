import httpx
import pytest

from app.cloud.export import publish
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
