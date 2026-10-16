"""Kiểm tra chất lượng dữ liệu sau khi nhập lịch sử: tìm trận bị lặp và đội bị tách đôi vì viết tên khác nhau."""
from __future__ import annotations

from datetime import timedelta

from ..utils import to_iso, utcnow

# Một đội không thể đá hai trận cùng chiều (nhà/khách) trong vòng 36 giờ ở cùng giải: nếu thấy thì đó là cùng một trận
# bị ghi hai lần với hai cái tên khác nhau của đối thủ.
_SPLIT_SQL = """
SELECT a.league_id, l.code AS league, a.home_team_id AS ah, a.away_team_id AS aa, b.home_team_id AS bh, b.away_team_id AS ba,
       a.utc_date AS d, a.provider AS pa, b.provider AS pb, a.home_score AS s1, a.away_score AS s2
FROM matches a JOIN matches b ON a.league_id=b.league_id AND a.id<b.id
     AND ((a.home_team_id=b.home_team_id AND a.away_team_id!=b.away_team_id) OR (a.away_team_id=b.away_team_id AND a.home_team_id!=b.home_team_id))
     AND ABS(julianday(a.utc_date)-julianday(b.utc_date)) <= 1.5
     AND COALESCE(a.home_score,-1)=COALESCE(b.home_score,-1) AND COALESCE(a.away_score,-1)=COALESCE(b.away_score,-1)
JOIN leagues l ON l.id=a.league_id
"""

_SAME_PAIR_SQL = """
SELECT l.code AS league, a.home_team_id AS h, a.away_team_id AS aw, a.utc_date AS d1, b.utc_date AS d2,
       a.provider AS p1, b.provider AS p2, a.status AS s1, b.status AS s2
FROM matches a JOIN matches b ON a.league_id=b.league_id AND a.id<b.id AND a.home_team_id=b.home_team_id AND a.away_team_id=b.away_team_id
     AND ABS(julianday(a.utc_date)-julianday(b.utc_date)) <= ?
JOIN leagues l ON l.id=a.league_id
"""


def _names(repo) -> dict[int, str]:
    with repo.db.connect() as c:
        return {r["id"]: r["name"] for r in c.execute("SELECT id, name FROM teams")}


def audit(repo, *, now=None) -> dict:
    now = now or utcnow()
    names = _names(repo)
    out: dict = {}
    with repo.db.connect() as c:
        rows = [dict(r) for r in c.execute(_SPLIT_SQL)]
        same = [dict(r) for r in c.execute(_SAME_PAIR_SQL, (10,))]
        stale = [dict(r) for r in c.execute(
            """SELECT l.code AS league, COUNT(*) AS n FROM matches m JOIN leagues l ON l.id=m.league_id
               WHERE m.status='SCHEDULED' AND m.provider != 'football-data.org' AND m.utc_date < ? GROUP BY l.code ORDER BY n DESC""",
            (to_iso(now - timedelta(days=3)),))]
    pairs: dict[tuple, dict] = {}
    for r in rows:
        x, y = (r["aa"], r["ba"]) if r["ah"] == r["bh"] else (r["ah"], r["bh"])
        key = (r["league"],) + tuple(sorted((x, y)))
        e = pairs.setdefault(key, {"league": r["league"], "a": names.get(key[1], "?"), "b": names.get(key[2], "?"), "n": 0, "example": r["d"][:10]})
        e["n"] += 1
    out["split_teams"] = sorted(pairs.values(), key=lambda e: -e["n"])
    out["same_pair_close"] = [
        {"league": r["league"], "home": names.get(r["h"], "?"), "away": names.get(r["aw"], "?"), "d1": r["d1"][:16], "d2": r["d2"][:16],
         "src": f'{r["p1"]}/{r["p2"]}', "status": f'{r["s1"]}/{r["s2"]}'} for r in same]
    out["stale_scheduled"] = stale
    return out


def format_audit(a: dict, limit: int = 60) -> list[str]:
    lines = ["=== KIỂM TRA TRẬN LẶP / ĐỘI BỊ TÁCH ĐÔI ==="]
    sp = a["split_teams"]
    lines.append(f"[1] Đội nghi bị tách đôi (cùng giải, cùng ngày, cùng tỷ số, chung một đội, khác đối thủ): {len(sp)} cặp")
    for e in sp[:limit]:
        lines.append(f"    {e['league']}: '{e['a']}' <-> '{e['b']}'  ({e['n']} trận, ví dụ {e['example']})")
    sc = a["same_pair_close"]
    lines.append(f"[2] Cùng cặp đội, cùng chiều, cách nhau ≤10 ngày (trận bị ghi 2 lần hoặc đá bù): {len(sc)} trường hợp")
    for e in sc[:limit]:
        lines.append(f"    {e['league']}: {e['home']} v {e['away']}  {e['d1']} | {e['d2']}  [{e['src']}] [{e['status']}]")
    st = a["stale_scheduled"]
    lines.append(f"[3] Trận lịch sử 'chưa đá' nhưng giờ đá đã qua >3 ngày: {sum(x['n'] for x in st)} trận")
    for e in st[:15]:
        lines.append(f"    {e['league']}: {e['n']}")
    lines.append("=== HẾT KIỂM TRA ===")
    return lines
