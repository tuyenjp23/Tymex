"""Cập nhật danh sách cầu thủ vắng mặt (chấn thương/treo giò/nghi ngờ) cho các trận sắp đá, từ API-Football.

Tiết kiệm request: chỉ giải có trận trong `hours_ahead` giờ tới, mỗi giải mỗi ngày có trận tốn 1 request,
làm mới tối đa mỗi `interval_min` phút, trần `max_calls` request mỗi lần chạy và dừng khi credit còn lại thấp.
Đội hình xuất phát chỉ được công bố khoảng 1 giờ trước giờ đá nên chưa lấy (lịch chạy hiện tại không bắt kịp).
"""
from __future__ import annotations

from datetime import timedelta
from typing import Callable

from ..history.leagues import MAIN_PROVIDER, season_start_year
from ..history.teams import TeamResolver
from ..utils import parse_iso, to_iso, utcnow
from .the_odds_api import OddsApiError

PROVIDER = "absences-feed"
UPCOMING = ("SCHEDULED", "TIMED")


def refresh_absences(repo, api, *, now=None, hours_ahead: float = 30, interval_min: int = 360, max_calls: int = 6,
                     min_remaining: int = 15, codes: list[str] | None = None, log: Callable[[str], None] = print) -> dict:
    now = now or utcnow()
    out = {"calls": 0, "matched": 0, "unmatched": [], "skipped": [], "errors": []}
    if not api or not api.is_configured():
        out["skipped"].append("chưa có API_FOOTBALL_KEY")
        return out
    resolver = TeamResolver(repo)
    end = now + timedelta(hours=hours_ahead)
    for code in codes or ["PL", "PD", "BL1", "SA", "FL1"]:
        league = repo.get_league_by_code(MAIN_PROVIDER, code)
        if not league:
            continue
        upcoming = repo.query_matches(league_id=league["id"], date_from=to_iso(now), date_to=to_iso(end), statuses=UPCOMING, limit=100)
        if not upcoming:
            continue
        last = repo.last_successful_sync(PROVIDER, code)
        if last and now - parse_iso(last) < timedelta(minutes=interval_min):
            out["skipped"].append(f"{code}: vừa cập nhật vắng mặt")
            continue
        days = sorted({m["utc_date"][:10] for m in upcoming})
        if out["calls"] + len(days) > max_calls:
            out["skipped"].append(f"{code}: hết lượt gọi của lần chạy này ({max_calls})")
            continue
        rem = getattr(api, "_remaining", None)
        if rem is not None and rem < min_remaining:
            out["skipped"].append(f"{code}: credit còn lại thấp ({rem})")
            break
        log_id = repo.start_sync_log(PROVIDER, code)
        by_match: dict[int, list[dict]] = {}
        try:
            for day in days:
                items, _ = api.injuries(code, day, season_start_year(parse_iso(day + "T12:00:00Z").date()))
                out["calls"] += 1
                for it in items:
                    tid = resolver.resolve_existing(it["team"])
                    if not tid:
                        out["unmatched"].append(it["team"])
                        continue
                    t = parse_iso(it["commence_time"])
                    for m in upcoming:
                        if tid in (m["home_team_id"], m["away_team_id"]) and abs((parse_iso(m["utc_date"]) - t).total_seconds()) <= 12 * 3600:
                            by_match.setdefault(m["id"], []).append({"team_id": tid, "player": it["player"], "kind": it["kind"], "reason": it["reason"]})
                            break
        except OddsApiError as exc:
            repo.finish_sync_log(log_id, "error", 0, exc.code, f"api-football: {exc}")
            out["errors"].append(f"{code}: {exc}")
            if exc.code in ("auth", "quota"):
                break
            continue
        # trận không có ai trong danh sách = không có tin vắng mặt (xóa danh sách cũ nếu có)
        for m in upcoming:
            repo.replace_absences(m["id"], "api-football", by_match.get(m["id"], []))
        n = sum(len(v) for v in by_match.values())
        out["matched"] += n
        repo.finish_sync_log(log_id, "ok", n, None, f"api-football: {len(days)} ngày, {n} cầu thủ vắng mặt/nghi ngờ")
        log(f"  + vắng mặt {code}: {n} cầu thủ ({len(days)} request)")
    return out
