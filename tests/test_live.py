import pytest

from app.prediction.live import FULL_MINUTES, predict_live, remaining_lambdas, simulate_match
from app.prediction.poisson import predict as prematch_predict  # noqa: F401  (đảm bảo import không vòng lặp)
from app.prediction.poisson import score_matrix, outcome_probabilities


def _sums_to_one(out):
    assert out["p_home"] + out["p_draw"] + out["p_away"] == pytest.approx(1.0)
    assert round(out["percent"]["home"] + out["percent"]["draw"] + out["percent"]["away"], 6) == 100.0
    ng = out["next_goal"]
    assert ng["home"] + ng["away"] + ng["none"] == pytest.approx(1.0, abs=0.002)
    assert sum(t["prob"] for t in out["top_final_scores"]) <= 1.0


def test_minute_zero_close_to_prematch_probabilities():
    """Ở phút 0, tỷ số 0-0: xác suất trực tiếp gần bằng xác suất trước trận ở cùng λ (chỉ khác do
    hiệu chỉnh trạng thái = không có và làm tròn), không được lệch hẳn."""
    lam_h, lam_a = 1.6, 1.0
    ph, pd, pa = outcome_probabilities(score_matrix(lam_h, lam_a, 10, rho=-0.08))
    out = predict_live(lam_h, lam_a, 0, 0, 0)
    _sums_to_one(out)
    assert out["p_home"] == pytest.approx(ph, abs=0.01)
    assert out["p_draw"] == pytest.approx(pd, abs=0.01)
    assert out["p_away"] == pytest.approx(pa, abs=0.01)
    assert out["expected_final"] == {"home": pytest.approx(lam_h, abs=0.01), "away": pytest.approx(lam_a, abs=0.01)}


def test_leading_at_85_gives_high_win_probability():
    out = predict_live(1.5, 1.2, 85, 2, 0)
    _sums_to_one(out)
    assert out["percent"]["home"] > 90
    assert out["predicted_final_score"]["home"] >= 2


def test_trailing_at_85_gives_low_win_probability():
    out = predict_live(1.5, 1.2, 85, 0, 2)
    _sums_to_one(out)
    assert out["percent"]["home"] < 5
    assert out["percent"]["away"] > 90


def test_late_equalizer_keeps_draw_most_likely():
    out = predict_live(1.4, 1.4, 88, 1, 1)
    _sums_to_one(out)
    assert out["percent"]["draw"] > out["percent"]["home"]
    assert out["predicted_final_score"] == {"home": 1, "away": 1, "prob": out["top_final_scores"][0]["prob"]}


def test_red_card_hurts_the_carded_team():
    base = predict_live(1.5, 1.2, 30, 0, 0)
    carded = predict_live(1.5, 1.2, 30, 0, 0, home_red_cards=1)
    _sums_to_one(carded)
    assert carded["p_home"] < base["p_home"]
    assert carded["p_away"] > base["p_away"]
    assert carded["lambda_home_remaining"] < base["lambda_home_remaining"]
    assert carded["lambda_away_remaining"] > base["lambda_away_remaining"]


def test_finished_match_is_certain():
    for hs, as_ in [(2, 1), (1, 1), (0, 3)]:
        out = predict_live(1.5, 1.2, FULL_MINUTES, hs, as_)
        _sums_to_one(out)
        expected = {"home": 100.0, "draw": 0.0, "away": 0.0} if hs > as_ else \
            {"home": 0.0, "draw": 100.0, "away": 0.0} if hs < as_ else {"home": 0.0, "draw": 0.0, "away": 100.0}
        if hs > as_:
            assert out["percent"]["home"] == 100.0
        elif hs < as_:
            assert out["percent"]["away"] == 100.0
        else:
            assert out["percent"]["draw"] == 100.0
        assert out["next_goal"]["none"] == 1.0
        assert out["top_final_scores"][0] == {"home": hs, "away": as_, "prob": 1.0}
        assert out["expected_final"] == {"home": float(hs), "away": float(as_)}


def test_minute_beyond_full_time_and_negative_minute_are_clamped():
    over = predict_live(1.5, 1.2, 130, 1, 0)
    assert over["percent"]["home"] == 100.0
    neg = predict_live(1.5, 1.2, -5, 0, 0)
    assert neg["minute"] == 0.0
    _sums_to_one(neg)


def test_remaining_lambdas_shrink_with_time_and_react_to_score_state():
    early_h, early_a = remaining_lambdas(1.8, 1.2, 10, 0, 0)
    late_h, late_a = remaining_lambdas(1.8, 1.2, 80, 0, 0)
    assert late_h < early_h and late_a < early_a
    # đang thua 0-2: đội nhà tấn công mạnh hơn mức trung tính, đội khách giảm nhịp
    trail_h, trail_a = remaining_lambdas(1.8, 1.2, 60, 0, 2)
    neutral_h, neutral_a = remaining_lambdas(1.8, 1.2, 60, 1, 1)
    assert trail_h > neutral_h and trail_a < neutral_a


def test_next_goal_probabilities_favour_stronger_remaining_lambda():
    out = predict_live(2.4, 0.6, 20, 0, 0)
    assert out["next_goal"]["home"] > out["next_goal"]["away"] > 0
    assert out["next_goal"]["none"] > 0


# ---------------------------------------------------------------------- mô phỏng trận (simulate_match)
def test_simulation_is_deterministic_with_seed():
    a = simulate_match(1.6, 1.1, seed=42)
    b = simulate_match(1.6, 1.1, seed=42)
    assert a == b
    c = simulate_match(1.6, 1.1, seed=43)
    assert c["timeline"] != a["timeline"] or c["final_score"] != a["final_score"]


def test_simulation_timeline_and_final_probabilities():
    sim = simulate_match(1.6, 1.1, seed=7)
    minutes = [t["minute"] for t in sim["timeline"]]
    assert minutes == sorted(minutes) and minutes[0] == 0 and minutes[-1] == int(FULL_MINUTES)
    # xác suất ở cuối trận mô phỏng phải dồn vào đúng kết quả của tỷ số mô phỏng
    fs = sim["final_score"]
    last = sim["timeline"][-1]
    key = "home" if fs["home"] > fs["away"] else "away" if fs["home"] < fs["away"] else "draw"
    assert last["percent"][key] == 100.0
    assert sim["final_percent"] == last["percent"]
    # sự kiện bàn thắng khớp với tỷ số chung cuộc và phút tăng dần
    ev = sim["events"]
    assert [e["minute"] for e in ev] == sorted(e["minute"] for e in ev)
    assert sum(1 for e in ev if e["side"] == "home") == fs["home"]
    assert sum(1 for e in ev if e["side"] == "away") == fs["away"]
    for t in sim["timeline"]:
        assert t["p_home"] + t["p_draw"] + t["p_away"] == pytest.approx(1.0, abs=0.002)
    assert sim["simulated"] is True and "không phải diễn biến thật" in sim["note"]


def test_simulation_goal_counts_are_sane_across_seeds():
    finals = [simulate_match(1.5, 1.2, seed=s)["final_score"] for s in range(30)]
    total = sum(f["home"] + f["away"] for f in finals)
    assert 30 * 1.5 < total < 30 * 4.5     # trung bình quanh λ tổng 2,7 bàn/trận, không nổ tung hay câm lặng
