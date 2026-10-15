"""Chấm điểm dự đoán sau khi có kết quả thật."""
from __future__ import annotations

import math
from collections import defaultdict

EPS = 1e-12
OUTCOMES = ("H", "D", "A")


def outcome_of(home_goals: int, away_goals: int) -> str:
    return "H" if home_goals > away_goals else ("D" if home_goals == away_goals else "A")


def brier_score(p_home: float, p_draw: float, p_away: float, actual: str) -> float:
    """Brier đa lớp (0 = hoàn hảo, 2 = tệ nhất). Đoán đều 1/3 cho kết quả ≈ 0.667."""
    probs = {"H": p_home, "D": p_draw, "A": p_away}
    return sum((probs[o] - (1.0 if o == actual else 0.0)) ** 2 for o in OUTCOMES)


def log_loss(p_home: float, p_draw: float, p_away: float, actual: str) -> float:
    probs = {"H": p_home, "D": p_draw, "A": p_away}
    return -math.log(max(probs[actual], EPS))


def evaluate_prediction(pred: dict, home_score: int, away_score: int) -> dict:
    """pred cần: p_home, p_draw, p_away, lambda_home, lambda_away, predicted_home, predicted_away."""
    actual = outcome_of(home_score, away_score)
    probs = {"H": pred["p_home"], "D": pred["p_draw"], "A": pred["p_away"]}
    predicted = max(OUTCOMES, key=lambda o: probs[o])   # kết quả 1X2 có xác suất cao nhất
    return {
        "home_score": home_score, "away_score": away_score,
        "actual_outcome": actual, "predicted_outcome": predicted, "correct": predicted == actual,
        "exact_score": pred["predicted_home"] == home_score and pred["predicted_away"] == away_score,
        "brier": brier_score(pred["p_home"], pred["p_draw"], pred["p_away"], actual),
        "log_loss": log_loss(pred["p_home"], pred["p_draw"], pred["p_away"], actual),
        "home_goal_error": pred["lambda_home"] - home_score,
        "away_goal_error": pred["lambda_away"] - away_score,
    }


def _agg(rows: list[dict]) -> dict:
    n = len(rows)
    if n == 0:
        return {"n": 0}
    return {
        "n": n,
        "accuracy": round(100 * sum(r["correct"] for r in rows) / n, 1),
        "exact_score_rate": round(100 * sum(r["exact_score"] for r in rows) / n, 1),
        "brier": round(sum(r["brier"] for r in rows) / n, 4),
        "log_loss": round(sum(r["log_loss"] for r in rows) / n, 4),
        "mae_home_goals": round(sum(abs(r["home_goal_error"]) for r in rows) / n, 3),
        "mae_away_goals": round(sum(abs(r["away_goal_error"]) for r in rows) / n, 3),
    }


def summarize_results(rows: list[dict]) -> dict:
    """rows: các dòng prediction_results (kèm utc_date, league_name). Gộp tổng thể, theo giải và theo tháng.
    Giá trị tham chiếu: đoán đều 1/3 → Brier 0.6667, log loss 1.0986."""
    by_league, by_month = defaultdict(list), defaultdict(list)
    for r in rows:
        by_league[r["league_name"]].append(r)
        by_month[r["utc_date"][:7]].append(r)
    return {
        "overall": _agg(rows),
        "by_league": [{"league": k, **_agg(v)} for k, v in sorted(by_league.items())],
        "by_month": [{"month": k, **_agg(v)} for k, v in sorted(by_month.items())],
        "baseline": {"brier_uniform": round(2 / 3, 4), "log_loss_uniform": round(math.log(3), 4)},
    }
