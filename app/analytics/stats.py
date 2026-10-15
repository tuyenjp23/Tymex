"""Thống kê từ danh sách trận đấu. Toàn bộ là hàm thuần: không đụng DB, không đụng API.

Quy tắc chống "rò rỉ tương lai": mọi hàm đều nhận mốc `before` (thời điểm bóng lăn của trận đang phân tích)
và chỉ dùng các trận ĐÃ KẾT THÚC (status FINISHED, có tỷ số) diễn ra TRƯỚC mốc đó.
"""
from __future__ import annotations

from typing import Iterable


def is_finished(m: dict) -> bool:
    return m.get("status") == "FINISHED" and m.get("home_score") is not None and m.get("away_score") is not None


def result_of(gf: int, ga: int) -> str:
    return "W" if gf > ga else ("D" if gf == ga else "L")


def team_games(matches: Iterable[dict], team_id: int, before: str, *, venue: str | None = None,
               exclude_id: int | None = None) -> list[dict]:
    """Các trận đã hoàn tất của một đội trước mốc `before`, mới nhất trước. venue: 'home' | 'away' | None."""
    out = []
    for m in matches:
        if not is_finished(m) or m["utc_date"] >= before or m.get("id") == exclude_id:
            continue
        is_home, is_away = m["home_team_id"] == team_id, m["away_team_id"] == team_id
        if not (is_home or is_away):
            continue
        if venue == "home" and not is_home:
            continue
        if venue == "away" and not is_away:
            continue
        out.append(m)
    out.sort(key=lambda m: (m["utc_date"], m.get("id") or 0), reverse=True)
    return out


def game_view(m: dict, team_id: int) -> dict:
    home = m["home_team_id"] == team_id
    gf, ga = (m["home_score"], m["away_score"]) if home else (m["away_score"], m["home_score"])
    res = result_of(gf, ga)
    return {
        "match_id": m.get("id"), "utc_date": m["utc_date"], "league": m.get("league_name"),
        "venue": "H" if home else "A",
        "opponent": m["away_name"] if home else m["home_name"],
        "opponent_id": m["away_team_id"] if home else m["home_team_id"],
        "home_name": m.get("home_name"), "away_name": m.get("away_name"),
        "home_score": m["home_score"], "away_score": m["away_score"],
        "gf": gf, "ga": ga, "result": res, "points": {"W": 3, "D": 1, "L": 0}[res],
    }


def summarize(views: list[dict]) -> dict:
    n = len(views)
    wins = sum(v["result"] == "W" for v in views)
    draws = sum(v["result"] == "D" for v in views)
    losses = n - wins - draws
    gf, ga = sum(v["gf"] for v in views), sum(v["ga"] for v in views)
    points = sum(v["points"] for v in views)
    clean = sum(v["ga"] == 0 for v in views)
    return {
        "played": n, "wins": wins, "draws": draws, "losses": losses, "points": points,
        "goals_for": gf, "goals_against": ga,
        "avg_goals_for": round(gf / n, 2) if n else None,
        "avg_goals_against": round(ga / n, 2) if n else None,
        "points_per_game": round(points / n, 2) if n else None,
        "clean_sheets": clean, "failed_to_score": sum(v["gf"] == 0 for v in views),
        "win_rate": round(100 * wins / n, 1) if n else None,
        "clean_sheet_rate": round(100 * clean / n, 1) if n else None,
    }


def team_form(matches: Iterable[dict], team_id: int, before: str, n: int = 5, exclude_id: int | None = None) -> dict:
    games = team_games(matches, team_id, before, exclude_id=exclude_id)[:n]
    views = [game_view(m, team_id) for m in games]
    return {
        "requested": n, "available": len(views), "games": views, "summary": summarize(views),
        "home_games": sum(v["venue"] == "H" for v in views), "away_games": sum(v["venue"] == "A" for v in views),
        "form_string": "".join(v["result"] for v in views),
    }


def venue_stats(matches: Iterable[dict], team_id: int, venue: str, before: str, n: int = 10,
                exclude_id: int | None = None) -> dict:
    """Thành tích riêng sân nhà (venue='home') hoặc sân khách (venue='away') trong n trận gần nhất tại sân đó."""
    games = team_games(matches, team_id, before, venue=venue, exclude_id=exclude_id)[:n]
    views = [game_view(m, team_id) for m in games]
    return {"venue": venue, "requested": n, "available": len(views), "summary": summarize(views), "games": views}


def head_to_head(matches: Iterable[dict], team_a: int, team_b: int, before: str, limit: int = 10,
                 exclude_id: int | None = None) -> dict:
    """Lịch sử đối đầu (mọi sân) từ góc nhìn đội A, tối đa `limit` trận gần nhất đã kết thúc trước `before`."""
    pair = {team_a, team_b}
    found = [m for m in matches
             if is_finished(m) and m["utc_date"] < before and m.get("id") != exclude_id
             and {m["home_team_id"], m["away_team_id"]} == pair]
    found.sort(key=lambda m: (m["utc_date"], m.get("id") or 0), reverse=True)
    found = found[:limit]
    games, a_wins, b_wins, draws, a_goals, b_goals = [], 0, 0, 0, 0, 0
    for m in found:
        a_home = m["home_team_id"] == team_a
        ga, gb = (m["home_score"], m["away_score"]) if a_home else (m["away_score"], m["home_score"])
        a_goals += ga
        b_goals += gb
        if ga > gb:
            a_wins += 1; winner = "A"
        elif gb > ga:
            b_wins += 1; winner = "B"
        else:
            draws += 1; winner = "D"
        games.append({"match_id": m.get("id"), "utc_date": m["utc_date"], "league": m.get("league_name"),
                      "home_name": m["home_name"], "away_name": m["away_name"],
                      "home_score": m["home_score"], "away_score": m["away_score"], "winner": winner})
    return {"requested": limit, "available": len(games), "games": games,
            "summary": {"played": len(games), "a_wins": a_wins, "draws": draws, "b_wins": b_wins,
                        "a_goals": a_goals, "b_goals": b_goals}}
