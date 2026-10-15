"""DỮ LIỆU KIỂM THỬ — không phải dữ liệu bóng đá thật.

Mọi bản ghi tạo ở đây dùng provider="fixture" để giao diện luôn hiển thị cảnh báo "DỮ LIỆU KIỂM THỬ".
Tên đội/giải đều là tên giả ("Test FC ...").
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

from app.data_providers.base import LeagueDTO, MatchDTO, StandingDTO, TeamDTO
from app.database.repository import Repository
from app.utils import to_iso

PROVIDER = "fixture"
TEAM_NAMES = ["Alpha", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot", "Golf", "Hotel", "India", "Juliet"]


def make_teams() -> list[TeamDTO]:
    return [TeamDTO(external_id=str(100 + i), name=f"Test FC {n}", short_name=n, tla=n[:3].upper(), crest_url=None)
            for i, n in enumerate(TEAM_NAMES)]


def make_league() -> LeagueDTO:
    return LeagueDTO(code="TST", name="Giải Kiểm Thử (dữ liệu giả)", country="Testland", type="LEAGUE", current_season=2025)


def make_matches(now: datetime, seed: int = 7, today_round: int = 12) -> list[MatchDTO]:
    """Vòng tròn 2 lượt cho 10 đội = 18 vòng, mỗi vòng cách nhau 1 ngày; vòng `today_round` rơi vào hôm nay.
    Các vòng trước đó đã kết thúc (tỷ số sinh ngẫu nhiên có chủ đích theo sức mạnh từng đội), các vòng sau chưa đá."""
    rng = random.Random(seed)
    teams = make_teams()
    n = len(teams)
    attack = {t.external_id: rng.uniform(0.7, 1.5) for t in teams}
    defence = {t.external_id: rng.uniform(0.7, 1.4) for t in teams}
    ids = list(range(n))
    rounds = []
    for r in range(n - 1):   # thuật toán xoay vòng tròn
        pairs = [(ids[i], ids[n - 1 - i]) for i in range(n // 2)]
        rounds.append(pairs)
        ids = [ids[0]] + [ids[-1]] + ids[1:-1]
    schedule = rounds + [[(b, a) for a, b in pairs] for pairs in rounds]
    base = now.replace(hour=12, minute=0, second=0, microsecond=0)
    out = []
    for r, pairs in enumerate(schedule, start=1):
        for k, (h, a) in enumerate(pairs):
            kickoff = base + timedelta(days=r - today_round, hours=k)
            ht, at = teams[h], teams[a]
            status, hs, as_ = "SCHEDULED", None, None
            if kickoff < now - timedelta(hours=3):
                lam_h = 1.45 * attack[ht.external_id] * defence[at.external_id]
                lam_a = 1.15 * attack[at.external_id] * defence[ht.external_id]
                hs, as_ = _poisson(rng, lam_h), _poisson(rng, lam_a)
                status = "FINISHED"
            out.append(MatchDTO(external_id=str(5000 + len(out)), season=2025, matchday=r, stage="REGULAR_SEASON",
                                utc_date=to_iso(kickoff), status=status, home=ht, away=at, home_score=hs, away_score=as_,
                                winner=None if hs is None else ("HOME_TEAM" if hs > as_ else "AWAY_TEAM" if as_ > hs else "DRAW")))
    return out


def _poisson(rng: random.Random, lam: float) -> int:
    import math
    limit, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def seed(repo: Repository, now: datetime | None = None, seed_value: int = 7) -> int:
    now = now or datetime.now(timezone.utc)
    league_id = repo.upsert_league(PROVIDER, make_league())
    matches = make_matches(now, seed_value)
    repo.upsert_matches(PROVIDER, league_id, matches)
    # bảng xếp hạng tính từ các trận đã kết thúc
    table = {}
    for m in matches:
        if m.status != "FINISHED":
            continue
        for team, gf, ga in ((m.home, m.home_score, m.away_score), (m.away, m.away_score, m.home_score)):
            row = table.setdefault(team.external_id, {"team": team, "p": 0, "w": 0, "d": 0, "l": 0, "gf": 0, "ga": 0})
            row["p"] += 1; row["gf"] += gf; row["ga"] += ga
            row["w"] += gf > ga; row["d"] += gf == ga; row["l"] += gf < ga
    ranked = sorted(table.values(), key=lambda r: (-(3 * r["w"] + r["d"]), -(r["gf"] - r["ga"]), -r["gf"]))
    repo.replace_standings(league_id, PROVIDER, 2025, [
        StandingDTO(group_name=None, position=i, team=r["team"], played=r["p"], won=r["w"], draw=r["d"], lost=r["l"],
                    points=3 * r["w"] + r["d"], goals_for=r["gf"], goals_against=r["ga"], goal_diff=r["gf"] - r["ga"])
        for i, r in enumerate(ranked, start=1)])
    return league_id
