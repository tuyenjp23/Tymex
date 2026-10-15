"""Nhập trận từ nguồn lịch sử vào CSDL: ghép đội, bỏ trận trùng, lưu tỷ lệ cược."""
from __future__ import annotations

from datetime import timedelta

from ..data_providers.base import LeagueDTO
from ..utils import parse_iso, to_iso
from .leagues import MAIN_PROVIDER
from .teams import TeamResolver


def ensure_league(repo, spec: dict) -> int:
    """Dùng giải sẵn có của football-data.org; chỉ tạo mới nếu chưa có (không đổi tên giải đã có)."""
    row = repo.get_league_by_code(MAIN_PROVIDER, spec["code"])
    if row:
        return row["id"]
    return repo.upsert_league(MAIN_PROVIDER, LeagueDTO(code=spec["code"], name=spec["name"], country=spec["country"], type="LEAGUE"))


def import_matches(repo, *, source: str, spec: dict, matches: list[dict], resolver: TeamResolver) -> dict:
    league_id = ensure_league(repo, spec)
    added = dup = odds_n = 0
    for m in matches:
        home_id, away_id = resolver.resolve(m["home"]), resolver.resolve(m["away"])
        if home_id == away_id:
            continue
        t = parse_iso(m["utc_date"])
        near = repo.find_match_near(league_id, home_id, away_id, to_iso(t - timedelta(hours=40)), to_iso(t + timedelta(hours=40)))
        if near:
            match_id, created = near["id"], False
            dup += 1
        else:
            match_id, created = repo.add_history_match(source, league_id, m, home_id, away_id)
            added += int(created)
        if m.get("odds") and m["status"] == "FINISHED":
            repo.save_odds(match_id, m["odds_source"], *m["odds"])
            odds_n += 1
    return {"seen": len(matches), "added": added, "duplicates": dup, "odds": odds_n}
