"""Xuất dữ liệu đã tính (trận, phân tích, dự đoán, bảng xếp hạng...) sang Supabase để web tĩnh trên Cloudflare Pages chỉ việc đọc.

Toàn bộ phép tính (thống kê, mô hình Poisson, kết luận) vẫn do Python thực hiện — cùng mã đã được kiểm thử — nên
trình duyệt không phải tính lại và không thể lệch kết quả với bản chạy trên máy.
"""
from __future__ import annotations

from datetime import timedelta

from ..api.routes import KNOWN_LEAGUES, public_match   # noqa: F401  (KNOWN_LEAGUES giữ để tiện tham chiếu)
from ..utils import search_key, to_iso, utcnow

PAST_DAYS = 30        # phân tích sẵn cho trận đã đá trong N ngày qua
FUTURE_DAYS = 14      # và cho trận sắp đá trong N ngày tới
FORM_SIZES = (5, 10)


def _kv(key: str, payload, now: str) -> dict:
    return {"key": key, "payload": payload, "updated_at": now}


def match_row(m: dict, now: str) -> dict:
    row = public_match(m)
    row["home_search"] = search_key(f"{m['home_name']} {m.get('home_short') or ''}")
    row["away_search"] = search_key(f"{m['away_name']} {m.get('away_short') or ''}")
    row["updated_at"] = now
    return row


def build_standings_payload(repo, league_id: int) -> dict | None:
    league = repo.get_league(league_id)
    if not league:
        return None
    rows = repo.get_standings(league_id)
    groups: dict[str, list] = {}
    for r in rows:
        groups.setdefault(r["group_name"], []).append(r)
    return {"league": league, "groups": [{"name": k, "rows": v} for k, v in groups.items()],
            "updated_at": rows[0]["updated_at"] if rows else None}


def publish(container, client, now=None, *, run_backtest: bool = True) -> dict:
    """Đẩy ảnh chụp (snapshot) dữ liệu hiện tại lên Supabase. Trả về số lượng bản ghi theo bảng."""
    repo, analysis, predictions = container.repo, container.analysis, container.predictions
    now_dt = now or utcnow()
    stamp = to_iso(now_dt)
    stats: dict[str, int] = {}

    if run_backtest:
        predictions.backtest(None, 100)   # chỉ đánh giá thêm các trận chưa có; không chạm dự đoán thật

    leagues = repo.list_leagues()

    # --- trận đấu: toàn bộ trận đang có theo từng giải (đủ cho lịch cả mùa của một đội)
    match_rows, window = [], []
    lo, hi = to_iso(now_dt - timedelta(days=PAST_DAYS)), to_iso(now_dt + timedelta(days=FUTURE_DAYS))
    for lg in leagues:
        for m in repo.query_matches(league_id=lg["id"], limit=1000):
            match_rows.append(match_row(m, stamp))
            if lo <= m["utc_date"] <= hi:
                window.append(m["id"])
    stats["matches"] = client.upsert("matches", match_rows, "id")

    # --- phân tích từng trận (5 và 10 trận gần nhất) — dùng đúng AnalysisService của bản chạy trên máy
    analysis_rows = []
    for mid in window:
        payload = {}
        for n in FORM_SIZES:
            a = analysis.build(mid, n)
            if a is None:
                break
            a["match"] = public_match(a["match"])
            payload[str(n)] = a
        if payload:
            analysis_rows.append({"match_id": mid, "payload": payload, "updated_at": stamp})
    stats["analysis"] = client.upsert("analysis", analysis_rows, "match_id", batch=20)

    # --- các khối dữ liệu dùng chung
    kv = []
    teams = repo.list_teams()
    for t in teams:
        t["search"] = t.pop("search_name", "")
    kv.append(_kv("teams", {"teams": teams}, stamp))
    kv.append(_kv("leagues", {"leagues": leagues}, stamp))
    for lg in leagues:
        kv.append(_kv(f"standings:{lg['id']}", build_standings_payload(repo, lg["id"]), stamp))
    for kind in ("live", "backtest"):
        kv.append(_kv(f"summary:{kind}", predictions.summary(kind), stamp))
        rows = repo.list_predictions(kind=kind, limit=150)
        kv.append(_kv(f"predictions:{kind}", {"predictions": rows, "count": len(rows)}, stamp))
    kv.append(_kv("status", {"last_sync": repo.last_sync_overall(), "counts": repo.counts(), "published_at": stamp,
                             "is_test_data": any(l["provider"] == "fixture" for l in leagues)}, stamp))
    stats["kv"] = client.upsert("kv", kv, "key", batch=10)
    return stats
