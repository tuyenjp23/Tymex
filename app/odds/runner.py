"""Cập nhật tỷ lệ cược cho các trận sắp đá từ một CHUỖI nguồn (nguồn đầu hết hạn mức thì dùng nguồn kế tiếp).

Quy tắc tiết kiệm (chỉnh bằng biến môi trường, xem scripts/cloud_sync.py):
- chỉ gọi cho giải có trận sắp đá trong `hours_ahead` giờ tới;
- giải có trận trong `near_hours` giờ tới: làm mới tối đa mỗi `near_interval_min` phút; giải còn xa: mỗi `far_interval_min` phút;
- mỗi nguồn có trần số request mỗi lần chạy và ngưỡng credit tối thiểu; nguồn bị từ chối khóa/hết hạn mức sẽ bị bỏ qua cho phần còn lại của lần chạy.
Chỉ dùng một khóa mỗi nguồn; không xoay vòng nhiều tài khoản để lách hạn mức.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Callable, Sequence

from ..history.leagues import MAIN_PROVIDER
from ..history.teams import TeamResolver
from ..utils import parse_iso, to_iso, utcnow
from .the_odds_api import OddsApiError

PROVIDER = "odds-feed"          # dùng chung cho mọi nguồn để việc "vừa cập nhật" không lặp lại khi đổi nguồn
UPCOMING = ("SCHEDULED", "TIMED")
DEFAULT_CODES = ["PL", "PD", "BL1", "SA", "FL1"]


def refresh_upcoming_odds(repo, providers: Sequence, *, now=None, hours_ahead: float = 30, near_hours: float = 3,
                          far_interval_min: int = 1440, near_interval_min: int = 120, codes: list[str] | None = None,
                          log: Callable[[str], None] = print) -> dict:
    now = now or utcnow()
    providers = [p for p in providers if p.is_configured()]
    out = {"calls": 0, "matched": 0, "unmatched": [], "skipped": [], "errors": [], "remaining": {}, "used": {}}
    if not providers:
        out["skipped"].append("chưa có khóa nguồn tỷ lệ cược nào")
        return out
    state = {p.name: {"calls": 0, "dead": None} for p in providers}
    plan = []
    for code in (codes or DEFAULT_CODES):
        league = repo.get_league_by_code(MAIN_PROVIDER, code)
        if not league:
            continue
        end = now + timedelta(hours=hours_ahead)
        upcoming = repo.query_matches(league_id=league["id"], date_from=to_iso(now), date_to=to_iso(end), statuses=UPCOMING, limit=100)
        if not upcoming:
            continue
        next_kick = min(m["utc_date"] for m in upcoming)
        near = parse_iso(next_kick) <= now + timedelta(hours=near_hours)
        last = repo.last_successful_sync(PROVIDER, code)
        gap = timedelta(minutes=near_interval_min if near else far_interval_min)
        if last and now - parse_iso(last) < gap:
            out["skipped"].append(f"{code}: vừa cập nhật")
            continue
        plan.append((next_kick, code, league, end))
    plan.sort(key=lambda x: x[0])
    resolver = TeamResolver(repo)
    for _, code, league, end in plan:
        for p in providers:
            st = state[p.name]
            if st["dead"]:
                continue
            if st["calls"] >= p.max_calls_per_run:
                out["skipped"].append(f"{code}: {p.name} hết lượt gọi của lần chạy này ({p.max_calls_per_run})")
                continue
            rem = out["remaining"].get(p.name)
            if rem is not None and rem < p.min_remaining:
                out["skipped"].append(f"{code}: {p.name} credit còn lại thấp ({rem})")
                continue
            log_id = repo.start_sync_log(PROVIDER, code)
            try:
                events, info = p.fetch(code, now, end)
            except OddsApiError as exc:
                repo.finish_sync_log(log_id, "error", 0, exc.code, f"{p.name}: {exc}")
                out["errors"].append(f"{code} [{p.name}]: {exc}")
                if exc.code in ("auth", "quota"):
                    st["dead"] = exc.code           # nguồn này hỏng cho cả lần chạy → thử nguồn kế tiếp
                continue
            calls = int(info.get("calls") or 1)
            st["calls"] += calls
            out["calls"] += calls
            out["used"][p.name] = st["calls"]
            if info.get("remaining") is not None:
                out["remaining"][p.name] = info["remaining"]
            matched = 0
            for ev in events:
                h, a = resolver.resolve_existing(ev.get("home")), resolver.resolve_existing(ev.get("away"))
                if not h or not a:
                    out["unmatched"].append(f"{ev.get('home')} - {ev.get('away')}")
                    continue
                t = parse_iso(ev["commence_time"])
                near_m = repo.find_match_near(league["id"], h, a, to_iso(t - timedelta(hours=12)), to_iso(t + timedelta(hours=12)))
                if not near_m or near_m["status"] not in UPCOMING:
                    continue
                repo.save_odds(near_m["id"], f"{p.name}:{ev['bookmakers']}", round(1 / ev["p_home"], 3),
                               round(1 / ev["p_draw"], 3), round(1 / ev["p_away"], 3))
                matched += 1
            repo.finish_sync_log(log_id, "ok", matched, None, f"{p.name}: {len(events)} sự kiện, ghép được {matched}")
            out["matched"] += matched
            log(f"  + tỷ lệ cược {code} qua {p.name}: {len(events)} sự kiện, ghép được {matched}")
            break
    return out
