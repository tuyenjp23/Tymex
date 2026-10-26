import math
import random

import pytest

from app.prediction.poisson import (MODEL_VERSION, ModelParams, dixon_coles_tau, outcome_probabilities,
                                    poisson_pmf, predict, round_to_100, score_matrix)
from tests.conftest import mk


def test_poisson_pmf_known_values():
    assert poisson_pmf(0, 1.0) == pytest.approx(math.exp(-1))
    assert poisson_pmf(2, 1.5) == pytest.approx(math.exp(-1.5) * 1.5 ** 2 / 2)
    assert sum(poisson_pmf(k, 2.3) for k in range(60)) == pytest.approx(1.0)


def test_score_matrix_sums_to_one_and_outcomes_too():
    m = score_matrix(1.6, 0.9, 10)
    assert sum(sum(r) for r in m) == pytest.approx(1.0)
    h, d, a = outcome_probabilities(m)
    assert h + d + a == pytest.approx(1.0)
    assert h > a   # chủ nhà mạnh hơn => xác suất thắng cao hơn


def test_symmetric_teams_give_symmetric_probabilities():
    h, d, a = outcome_probabilities(score_matrix(1.3, 1.3, 10))
    assert h == pytest.approx(a)


@pytest.mark.parametrize("probs", [[1 / 3, 1 / 3, 1 / 3], [0.4551, 0.2749, 0.2700], [0.9999, 0.00005, 0.00005], [0.5, 0.5, 0.0]])
def test_rounded_percentages_always_sum_to_exactly_100(probs):
    r = round_to_100(probs)
    assert round(sum(r), 6) == 100.0
    assert all(abs(x - 100 * p) <= 0.1 for x, p in zip(r, probs))


def test_rounded_percentages_random_sums():
    rng = random.Random(1)
    for _ in range(500):
        x = [rng.random() for _ in range(3)]
        t = sum(x)
        assert round(sum(round_to_100([v / t for v in x])), 6) == 100.0


def league(n_rounds=12, teams=6, seed=3):
    """Giải kiểm thử: đội 1 rất mạnh, đội 6 rất yếu."""
    rng = random.Random(seed)
    out, mid = [], 1
    strength = {1: 2.2, 2: 1.4, 3: 1.2, 4: 1.0, 5: 0.8, 6: 0.5}
    for r in range(n_rounds):
        for h in range(1, teams + 1):
            for a in range(1, teams + 1):
                if h == a or rng.random() > 0.35:
                    continue
                day = 1 + (mid % 28)
                month = 1 + (mid // 28) % 9
                lam_h = 1.4 * strength[h] / strength[a] ** 0.5
                lam_a = 1.1 * strength[a] / strength[h] ** 0.5
                out.append(mk(mid, f"2025-{month:02d}-{day:02d}T12:00:00Z", h, a, _p(rng, lam_h), _p(rng, lam_a)))
                mid += 1
    return out


def _p(rng, lam):
    lim, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= lim:
            return k
        k += 1


KICK = "2025-11-20T12:00:00Z"


def test_strong_home_vs_weak_away_favours_home_and_percent_sums_to_100():
    out = predict(league(), 1, 6, KICK, "Mạnh", "Yếu", ModelParams(lookback_days=500))
    assert out["available"]
    pc = out["percent"]
    assert round(pc["home"] + pc["draw"] + pc["away"], 6) == 100.0
    assert pc["home"] > 60 and pc["home"] > pc["away"]
    assert out["lambda_home"] > out["lambda_away"]
    assert out["p_home"] + out["p_draw"] + out["p_away"] == pytest.approx(1.0)
    assert out["top_scores"][0]["prob"] >= out["top_scores"][1]["prob"]
    assert out["predicted_score"]["home"] == out["top_scores"][0]["home"]
    assert out["factors"], "phải có các yếu tố giải thích"


def test_swapping_venue_changes_prediction():
    a = predict(league(), 1, 6, KICK, "A", "B", ModelParams(lookback_days=500))
    b = predict(league(), 6, 1, KICK, "B", "A", ModelParams(lookback_days=500))
    assert a["percent"]["home"] > b["percent"]["home"]


def test_future_results_do_not_change_prediction():
    base = league()
    p1 = predict(base, 1, 6, KICK, "A", "B", ModelParams(lookback_days=500))
    leak = base + [mk(9999, "2025-12-25T12:00:00Z", 1, 6, 0, 9), mk(9998, "2025-11-30T12:00:00Z", 6, 1, 7, 0)]
    p2 = predict(leak, 1, 6, KICK, "A", "B", ModelParams(lookback_days=500))
    assert p1["lambda_home"] == p2["lambda_home"] and p1["percent"] == p2["percent"]


def test_unfinished_matches_are_ignored():
    base = league()
    extra = [mk(9000 + i, "2025-11-10T12:00:00Z", 1, 6, 8, 0, status="SCHEDULED") for i in range(30)]
    assert predict(base + extra, 1, 6, KICK, "A", "B", ModelParams(lookback_days=500))["lambda_home"] == \
        predict(base, 1, 6, KICK, "A", "B", ModelParams(lookback_days=500))["lambda_home"]


def test_insufficient_league_data_returns_no_fake_prediction():
    out = predict(league()[:10], 1, 6, KICK, "A", "B")
    assert out["available"] is False and "Chưa đủ dữ liệu" in out["reason"]
    assert "percent" not in out and "lambda_home" not in out


def test_insufficient_team_data_returns_no_prediction():
    ms = league()
    out = predict(ms, 1, 99, KICK, "A", "Đội lạ", ModelParams(lookback_days=500))   # đội 99 chưa có trận nào
    assert out["available"] is False and "Đội lạ" in out["reason"]


def test_no_data_at_all():
    assert predict([], 1, 2, KICK, "A", "B")["available"] is False


# ---------------------------------------------------------------------- Dixon-Coles
def test_dixon_coles_tau_formula_and_untouched_cells():
    rho = -0.08
    assert dixon_coles_tau(0, 0, 1.5, 1.1, rho) == pytest.approx(1 - 1.5 * 1.1 * rho)
    assert dixon_coles_tau(1, 0, 1.5, 1.1, rho) == pytest.approx(1 + 1.1 * rho)
    assert dixon_coles_tau(0, 1, 1.5, 1.1, rho) == pytest.approx(1 + 1.5 * rho)
    assert dixon_coles_tau(1, 1, 1.5, 1.1, rho) == pytest.approx(1 - rho)
    assert dixon_coles_tau(2, 1, 1.5, 1.1, rho) == 1.0
    assert dixon_coles_tau(0, 2, 1.5, 1.1, rho) == 1.0


def test_dixon_coles_negative_rho_shifts_low_score_probabilities():
    """rho âm: P(0-0) và P(1-1) tăng, P(1-0) và P(0-1) giảm so với Poisson thuần ở cùng λ."""
    plain = score_matrix(1.5, 1.1, 10)                    # rho mặc định 0 = Poisson thuần (tương thích ngược)
    dc = score_matrix(1.5, 1.1, 10, rho=-0.08)
    assert dc[0][0] > plain[0][0]
    assert dc[1][1] > plain[1][1]
    assert dc[1][0] < plain[1][0]
    assert dc[0][1] < plain[0][1]
    # các ô ngoài nhóm 4 ô thấp chỉ đổi do chuẩn hóa lại, theo cùng một tỷ lệ
    ratio = dc[4][3] / plain[4][3]
    assert dc[2][0] == pytest.approx(plain[2][0] * ratio)


def test_dixon_coles_matrix_still_sums_to_one_and_outcomes_too():
    for lam_h, lam_a, rho in [(1.5, 1.1, -0.08), (0.6, 0.5, -0.13), (3.2, 2.8, -0.03), (1.3, 1.3, 0.05)]:
        m = score_matrix(lam_h, lam_a, 10, rho=rho)
        assert sum(sum(r) for r in m) == pytest.approx(1.0)
        h, d, a = outcome_probabilities(m)
        assert h + d + a == pytest.approx(1.0)
        assert all(v >= 0 for row in m for v in row)


def test_dixon_coles_zero_rho_matches_plain_poisson_exactly():
    a = score_matrix(1.7, 0.8, 10)
    b = score_matrix(1.7, 0.8, 10, rho=0.0)
    assert a == b


def test_predict_uses_dixon_coles_and_reports_it():
    out = predict(league(), 1, 6, KICK, "Mạnh", "Yếu", ModelParams(lookback_days=500))
    assert out["available"]
    assert out["dixon_coles_rho"] == pytest.approx(-0.08)
    assert out["model_version"] == MODEL_VERSION and "dc" in MODEL_VERSION
    pc = out["percent"]
    assert round(pc["home"] + pc["draw"] + pc["away"], 6) == 100.0
    assert out["p_home"] + out["p_draw"] + out["p_away"] == pytest.approx(1.0)
    # ma trận trả ra bị cắt còn 6x6 và làm tròn nên tổng nhỏ hơn 1 (đội mạnh có λ cao, đuôi >5 bàn đáng kể)
    assert 0.8 < sum(sum(r) for r in out["matrix"]) <= 1.0
    assert out["top_scores"][0]["prob"] >= out["top_scores"][1]["prob"]
