"""So sánh mô hình với thị trường cược trên các trận đã có tỷ lệ cược (nhập từ football-data.co.uk).

Mỗi trận chỉ dùng dữ liệu TRƯỚC giờ bóng lăn (đúng như dự đoán thật). Tỷ lệ cược được bỏ phần lợi nhuận nhà cái
(chuẩn hóa 1/odds để tổng = 1). Số càng NHỎ càng tốt; "đoán đều" (1/3 mỗi kết quả) là mốc tệ nhất hợp lý.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import timedelta

from ..utils import parse_iso, to_iso
from .evaluation import brier_score, log_loss, outcome_of
from .poisson import ModelParams, predict


def implied_probabilities(odds_home: float, odds_draw: float, odds_away: float) -> tuple[float, float, float]:
    inv = [1.0 / odds_home, 1.0 / odds_draw, 1.0 / odds_away]
    total = sum(inv)
    return inv[0] / total, inv[1] / total, inv[2] / total


def _mean(xs):
    return sum(xs) / len(xs) if xs else float("nan")


def compare_with_odds(repo, params: ModelParams = ModelParams(), league_id: int | None = None) -> dict:
    rows = repo.odds_rows_with_matches(league_id)
    by_league: dict[int, list[dict]] = defaultdict(list)
    for r in rows:
        by_league[r["league_id"]].append(r)
    acc: dict[str, dict[str, list[float]]] = {}
    skipped = 0
    for lid, odds_rows in by_league.items():
        pool_all = repo.finished_matches(league_id=lid)          # mới nhất trước
        name = odds_rows[0]["league_name"]
        bucket = acc.setdefault(name, defaultdict(list))
        for m in odds_rows:
            since = to_iso(parse_iso(m["utc_date"]) - timedelta(days=params.lookback_days))
            pool = [x for x in pool_all if since <= x["utc_date"] < m["utc_date"]]
            out = predict(pool, m["home_team_id"], m["away_team_id"], m["utc_date"], m["home_name"], m["away_name"], params)
            if not out.get("available"):
                skipped += 1
                continue
            actual = outcome_of(m["home_score"], m["away_score"])
            mine = (out["p_home"], out["p_draw"], out["p_away"])
            book = implied_probabilities(m["odds_home"], m["odds_draw"], m["odds_away"])
            for tag, p in (("model", mine), ("bookmaker", book), ("uniform", (1 / 3, 1 / 3, 1 / 3))):
                bucket[f"{tag}_ll"].append(log_loss(*p, actual))
                bucket[f"{tag}_brier"].append(brier_score(*p, actual))
            bucket["model_hit"].append(1.0 if max(zip(mine, "HDA"))[1] == actual else 0.0)
            bucket["book_hit"].append(1.0 if max(zip(book, "HDA"))[1] == actual else 0.0)
    leagues, tot = [], defaultdict(list)
    for name, b in acc.items():
        n = len(b["model_ll"])
        if not n:
            continue
        leagues.append({"league": name, "matches": n,
                        **{k: round(_mean(v), 4) for k, v in b.items()}})
        for k, v in b.items():
            tot[k] += v
    n_all = len(tot["model_ll"])
    overall = {"matches": n_all, **{k: round(_mean(v), 4) for k, v in tot.items()}} if n_all else {"matches": 0}
    if n_all:
        overall["model_vs_bookmaker_logloss_gap"] = round(overall["model_ll"] - overall["bookmaker_ll"], 4)
    return {"overall": overall, "leagues": sorted(leagues, key=lambda x: x["league"]), "skipped_insufficient_data": skipped}
