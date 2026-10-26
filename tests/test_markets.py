import pytest

from app.prediction.markets import (PICK_FLOOR, build_verdict, goal_lines, strength_label)
from app.prediction.poisson import ModelParams, outcome_probabilities, predict, score_matrix
from tests.test_poisson import KICK, league

LH, LA = 1.7, 1.2   # cặp λ dùng cho kiểm chứng chéo Python <-> JS (bản web)


def test_goal_lines_over_under_sum_to_one_per_line():
    mk = goal_lines(lambda_home=LH, lambda_away=LA)
    assert [ln["line"] for ln in mk["lines"]] == [0.5, 1.5, 2.5, 3.5, 4.5]
    for ln in mk["lines"]:
        assert ln["over"] + ln["under"] == pytest.approx(1.0, abs=1e-3)   # đã làm tròn 4 chữ số


def test_goal_lines_monotonic_and_expected_total():
    mk = goal_lines(lambda_home=LH, lambda_away=LA)
    overs = [ln["over"] for ln in mk["lines"]]
    assert overs == sorted(overs, reverse=True)          # mốc càng cao, Tài càng khó
    assert all(0 < p < 1 for p in overs)
    assert mk["expected_total_goals"] == pytest.approx(LH + LA, abs=0.05)


def test_goal_lines_from_matrix_matches_from_lambdas():
    m = score_matrix(LH, LA, rho=-0.08)
    a = goal_lines(matrix=m)
    b = goal_lines(lambda_home=LH, lambda_away=LA)
    for x, y in zip(a["lines"], b["lines"]):
        assert x["over"] == pytest.approx(y["over"], abs=1e-9)
    assert a["btts"] == b["btts"]


def test_goal_lines_btts_and_double_chance_consistency():
    mk = goal_lines(lambda_home=LH, lambda_away=LA)
    assert mk["btts"]["yes"] + mk["btts"]["no"] == pytest.approx(1.0, abs=1e-3)
    h, d, a = outcome_probabilities(score_matrix(LH, LA, rho=-0.08))
    dc = mk["double_chance"]
    assert dc["1X"] == pytest.approx(h + d, abs=1e-3)
    assert dc["12"] == pytest.approx(h + a, abs=1e-3)
    assert dc["X2"] == pytest.approx(d + a, abs=1e-3)
    assert dc["1X"] + a == pytest.approx(1.0, abs=1e-3)


def test_goal_lines_needs_matrix_or_lambdas():
    with pytest.raises(ValueError):
        goal_lines()


def test_strength_label_thresholds():
    assert strength_label(0.65) == "Mạnh"
    assert strength_label(0.80) == "Mạnh"
    assert strength_label(0.57) == "Khá"
    assert strength_label(0.569) is None
    assert strength_label(0.30) is None


def _fake_prediction(lh, la):
    m = score_matrix(lh, la, rho=-0.08)
    h, d, a = outcome_probabilities(m)
    return {
        "available": True, "lambda_home": lh, "lambda_away": la, "dixon_coles_rho": -0.08,
        "p_home": h, "p_draw": d, "p_away": a,
        "predicted_score": {"home": 1, "away": 1, "prob": round(m[1][1], 4)},
        "markets": goal_lines(matrix=m),
        "factors": [{"text": "Yếu tố A.", "direction": "up", "side": "home"},
                    {"text": "Yếu tố B.", "direction": "down", "side": "away"},
                    {"text": "Yếu tố C.", "direction": "up", "side": "home"}],
        "quality": {"league_games": 200, "home_games": 25, "away_games": 24, "reliability": "khá"},
    }


def test_verdict_never_recommends_below_floor():
    for lh, la in [(1.7, 1.2), (1.35, 1.30), (0.8, 0.7), (2.6, 0.7), (1.1, 2.4)]:
        v = build_verdict(_fake_prediction(lh, la), "Nhà", "Khách")
        assert v["picks"], "luôn có ít nhất một lựa chọn >= 0,50 trong các cặp λ này"
        for p in v["picks"]:
            assert p["probability"] >= PICK_FLOOR
            assert p["strength"] in ("Mạnh", "Khá", "Cân nhắc")
        assert 2 <= len(v["reasoning"]) <= 4
        assert v["disclaimer"] and "không phải lời khuyên cá cược" in v["disclaimer"]
        # tỷ số dự đoán nằm riêng, xác suất thấp của nó không trà trộn vào picks
        assert all(p["market"] != "score" for p in v["picks"])
        assert v["score"]["prob"] < PICK_FLOOR


def test_verdict_strong_home_lambda_gives_home_pick():
    v = build_verdict(_fake_prediction(2.6, 0.7), "Rất Mạnh", "Rất Yếu")
    home_picks = [p for p in v["picks"] if p["market"] == "1x2"]
    assert home_picks and home_picks[0]["selection"] == "Rất Mạnh thắng"
    assert home_picks[0]["probability"] >= 0.65 and home_picks[0]["strength"] == "Mạnh"


def test_verdict_picks_sorted_and_capped():
    v = build_verdict(_fake_prediction(2.2, 1.9), "Nhà", "Khách")
    probs = [p["probability"] for p in v["picks"]]
    assert probs == sorted(probs, reverse=True)
    assert len(v["picks"]) <= 4


def test_predict_includes_markets_and_verdict_backward_compatible():
    out = predict(league(), 1, 6, KICK, "Mạnh", "Yếu", ModelParams(lookback_days=500))
    assert out["available"]
    # các khóa cũ vẫn nguyên vẹn
    for key in ("percent", "predicted_score", "top_scores", "over_2_5", "both_teams_score", "matrix", "factors"):
        assert key in out
    mk = out["markets"]
    assert [ln["line"] for ln in mk["lines"]] == [0.5, 1.5, 2.5, 3.5, 4.5]
    line25 = next(ln for ln in mk["lines"] if ln["line"] == 2.5)
    assert line25["over"] == pytest.approx(out["over_2_5"], abs=1e-3)   # khớp số cũ đã công bố
    assert mk["btts"]["yes"] == pytest.approx(out["both_teams_score"], abs=1e-3)
    v = out["verdict"]
    assert v["picks"] and all(p["probability"] >= PICK_FLOOR for p in v["picks"])
    assert v["score"]["home"] == out["predicted_score"]["home"]
