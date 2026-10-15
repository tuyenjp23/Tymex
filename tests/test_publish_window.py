from datetime import timedelta

import pytest

from app.cloud.export import publish
MATCH_DAYS = 400
from app.main import build_container
from tests import fixtures
from tests.test_cloud import FakeClient


@pytest.fixture
def container(settings, now):
    c = build_container(settings, provider=None)
    fixtures.seed(c.repo, now)
    c.predictions.now = lambda: now
    return c


def test_publish_keeps_recent_matches_when_history_is_large(container, now):
    """Sau khi nhập lịch sử nhiều mùa, giải có > 1000 trận cũ vẫn phải đẩy được trận gần đây và sắp đá."""
    repo = container.repo
    lg = repo.list_leagues()[0]
    teams = [t["id"] for t in repo.list_teams()][:2]
    old = now - timedelta(days=MATCH_DAYS + 30)
    for i in range(1100):
        repo.add_history_match("history-test", lg["id"], {
            "external_id": f"old-{i}", "season": 2022, "matchday": 1,
            "utc_date": (old - timedelta(hours=i + 1)).strftime("%Y-%m-%dT%H:%M:%SZ"), "status": "FINISHED",
            "home_score": 1, "away_score": 0, "winner": "HOME_TEAM"}, teams[0], teams[1])
    client = FakeClient()
    stats = publish(container, client, now=now)
    dates = [r["utc_date"] for r in client.tables["matches"]]
    assert stats["analysis"] > 0                              # trận sắp đá vẫn được phân tích
    assert min(dates) >= (now - timedelta(days=MATCH_DAYS + 1)).strftime("%Y-%m-%d")   # lịch sử cũ không bị đẩy lên
