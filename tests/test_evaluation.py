import math

import pytest

from app.prediction.evaluation import brier_score, evaluate_prediction, log_loss, outcome_of, summarize_results

PRED = {"p_home": 0.5, "p_draw": 0.3, "p_away": 0.2, "lambda_home": 1.6, "lambda_away": 0.9,
        "predicted_home": 1, "predicted_away": 0}


def test_outcome():
    assert outcome_of(2, 1) == "H" and outcome_of(1, 1) == "D" and outcome_of(0, 3) == "A"


def test_brier_and_logloss_values():
    assert brier_score(0.5, 0.3, 0.2, "H") == pytest.approx(0.25 + 0.09 + 0.04)
    assert brier_score(1, 0, 0, "H") == 0
    assert brier_score(1 / 3, 1 / 3, 1 / 3, "D") == pytest.approx(2 / 3)
    assert log_loss(0.5, 0.3, 0.2, "A") == pytest.approx(-math.log(0.2))
    assert math.isfinite(log_loss(1, 0, 0, "A"))   # không ra vô cực


def test_evaluate_correct_and_wrong():
    ok = evaluate_prediction(PRED, 2, 0)
    assert ok["correct"] and ok["actual_outcome"] == "H" and not ok["exact_score"]
    assert ok["home_goal_error"] == pytest.approx(-0.4) and ok["away_goal_error"] == pytest.approx(0.9)
    exact = evaluate_prediction(PRED, 1, 0)
    assert exact["exact_score"]
    wrong = evaluate_prediction(PRED, 0, 2)
    assert not wrong["correct"] and wrong["brier"] > ok["brier"]


def test_summary_counts_wrong_predictions_too():
    rows = []
    for hs, as_, month, league in [(2, 0, "2025-09", "A"), (0, 2, "2025-09", "A"), (1, 1, "2025-10", "B"), (0, 1, "2025-10", "B")]:
        r = evaluate_prediction(PRED, hs, as_)
        rows.append({**r, "utc_date": f"{month}-10T12:00:00Z", "league_name": league})
    s = summarize_results(rows)
    assert s["overall"]["n"] == 4 and s["overall"]["accuracy"] == 25.0
    assert [x["league"] for x in s["by_league"]] == ["A", "B"]
    assert [x["month"] for x in s["by_month"]] == ["2025-09", "2025-10"]
    assert s["baseline"]["brier_uniform"] == pytest.approx(0.6667, abs=1e-4)


def test_empty_summary():
    assert summarize_results([])["overall"] == {"n": 0}
