"""Xuất dữ liệu đã tính (trận, phân tích, dự đoán, bảng xếp hạng...) sang Supabase để web tĩnh trên Cloudflare Pages chỉ việc đọc.

Toàn bộ phép tính (thống kê, mô hình Poisson, kết luận) vẫn do Python thực hiện — cùng mã đã được kiểm thử — nên
trình duyệt không phải tính lại và không thể lệch kết quả với bản chạy trên máy.
"""
from __future__ import annotations

import re
from datetime import timedelta

from ..api.routes import KNOWN_LEAGUES, public_match   # noqa: F401  (KNOWN_LEAGUES giữ để tiện tham chiếu)
from ..utils import search_key, to_iso, utcnow

PAST_DAYS = 30        # phân tích sẵn cho trận đã đá trong N ngày qua
FUTURE_DAYS = 14      # và cho trận sắp đá trong N ngày tới
FORM_SIZES = (5, 10)
MATCH_DAYS = 400      # chỉ đẩy trận trong N ngày gần đây (đủ cả mùa hiện tại + mùa trước); lịch sử cũ chỉ để mô hình/đánh giá
CANONICAL_MATCH_PROVIDER = "football-data.org"   # nguồn chính của dự án (history/leagues.MAIN_PROVIDER)

_TEAM_NAME_AFFIXES = {
    "fc", "cf", "sc", "afc", "club", "de", "ca", "cd", "ec", "ifk", "bk",
    "ac", "as", "us", "ss", "sv", "fk", "sk", "if", "ff", "ik",
}
_STATUS_RANK = {"FINISHED": 50, "AWARDED": 40, "PAUSED": 35, "IN_PLAY": 30, "TIMED": 20, "SCHEDULED": 10}


def normalize_export_team_name(name) -> str:
    """Chuẩn hóa tên đội cho khóa chống trùng khi xuất Supabase (khớp web/data.js):
    bỏ dấu/dấu câu, bỏ các tiền/hậu tố tổ chức phổ biến, gộp khoảng trắng."""
    text = re.sub(r"[^a-z0-9]+", " ", search_key(name))
    return " ".join(t for t in text.split() if t not in _TEAM_NAME_AFFIXES)


def _export_match_key(m: dict) -> tuple[str, str, str] | None:
    """Khóa trùng KHÔNG gồm league_id: cùng ngày UTC + đúng cặp đội/chiều nhà-khách.
    Lượt về/đảo chiều sân có khóa khác; khác ngày cũng là khóa khác — cả hai đều hợp lệ, không gộp."""
    if not m.get("utc_date") or not m.get("home_name") or not m.get("away_name"):
        return None
    return (str(m["utc_date"])[:10], normalize_export_team_name(m["home_name"]),
            normalize_export_team_name(m["away_name"]))


def _export_match_priority(m: dict) -> tuple[int, int, int, int]:
    """Thứ tự ưu tiên bản ghi được giữ: có tỷ số > trạng thái tiến triển hơn > nguồn chuẩn > id nhỏ nhất.
    Dùng -id trong tuple để max() chọn id nhỏ hơn khi mọi tiêu chí còn lại bằng nhau."""
    has_score = int(m.get("home_score") is not None or m.get("away_score") is not None)
    status_rank = _STATUS_RANK.get(str(m.get("status") or ""), 0)
    canonical = int(m.get("provider") == CANONICAL_MATCH_PROVIDER)
    try:
        neg_id = -int(m.get("id"))
    except (TypeError, ValueError):
        neg_id = 0
    return (has_score, status_rank, canonical, neg_id)


def dedupe_export_matches(matches: list[dict]) -> tuple[list[dict], int]:
    """Gộp các trận trùng TRƯỚC khi upsert Supabase; trả (danh sách đã gộp, số trận bị gộp mất).
    Việc gộp kiểm tra league-agnostic trước: nếu cùng khóa xuất hiện dưới hai league_id khác nhau,
    bản ghi thắng giữ nguyên league_id của chính nó (không ép về giải của bản thua)."""
    out: list[dict] = []
    index_by_key: dict[tuple[str, str, str], int] = {}
    removed = 0
    for m in matches:
        key = _export_match_key(m)
        if key is None:
            out.append(m)
            continue
        idx = index_by_key.get(key)
        if idx is None:
            index_by_key[key] = len(out)
            out.append(m)
            continue
        removed += 1
        if _export_match_priority(m) > _export_match_priority(out[idx]):
            out[idx] = m
    return out, removed


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
    # Gom từ mọi giải trước, rồi gộp trùng league-agnostic TRƯỚC khi tạo hàng/upsert: các nguồn
    # football-data.org/ESPN/openfootball có thể đã tạo cùng một trận dưới league_id/đội khác nhau.
    raw_matches = []
    for lg in leagues:
        raw_matches.extend(repo.query_matches(
            league_id=lg["id"], date_from=to_iso(now_dt - timedelta(days=MATCH_DAYS)), limit=1000))
    unique_matches, merged_duplicates = dedupe_export_matches(raw_matches)
    if merged_duplicates:
        print(f"đã gộp {merged_duplicates} trận trùng trước khi xuất Supabase")
    match_rows, window = [], []
    lo, hi = to_iso(now_dt - timedelta(days=PAST_DAYS)), to_iso(now_dt + timedelta(days=FUTURE_DAYS))
    for m in unique_matches:
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
