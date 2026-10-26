import pytest

from app.prediction.corners import CORNER_LINES, estimate_from_matches, predict_corners

LAH, LAA = 5.4, 4.3   # trung bình góc sân nhà / sân khách của giải (giá trị điển hình kiểu Premier League)


def test_average_teams_give_league_average_total():
    out = predict_corners(LAH, LAA, LAA, LAH, LAH, LAA, home_games=20, away_games=20)
    assert out["available"]
    assert out["expected"]["home"] == pytest.approx(LAH, abs=0.05)
    assert out["expected"]["away"] == pytest.approx(LAA, abs=0.05)
    assert out["expected"]["total"] == pytest.approx(LAH + LAA, abs=0.1)


def test_corner_lines_sum_to_one_and_monotonic():
    out = predict_corners(LAH, LAA, LAA, LAH, LAH, LAA, home_games=10, away_games=10)
    assert [ln["line"] for ln in out["lines"]] == list(CORNER_LINES)
    overs = []
    for ln in out["lines"]:
        assert ln["over"] + ln["under"] == pytest.approx(1.0, abs=1e-3)
        overs.append(ln["over"])
    assert overs == sorted(overs, reverse=True)
    band = out["likely_band"]
    assert band[0] <= out["most_likely_total"] <= band[1]


def test_high_corner_teams_raise_total_and_over_probability():
    base = predict_corners(LAH, LAA, LAA, LAH, LAH, LAA, home_games=15, away_games=15)
    high = predict_corners(7.5, 6.0, 6.5, 6.2, LAH, LAA, home_games=15, away_games=15)
    assert high["expected"]["total"] > base["expected"]["total"] + 1.5
    over95 = {ln["line"]: ln["over"] for ln in high["lines"]}
    base95 = {ln["line"]: ln["over"] for ln in base["lines"]}
    assert over95[9.5] > base95[9.5]
    # đội đá góc nhiều + đối thủ để lọt góc nhiều -> Tài 9,5 đủ mạnh để được nêu
    assert high["pick"] is not None and high["pick"]["probability"] >= 0.57
    assert high["pick"]["market"] == "corners_ou"


def test_no_sample_shrinks_fully_to_league_average():
    """games=0: tỷ lệ của đội bị bỏ qua hoàn toàn, kết quả là trận của hai đội trung bình."""
    out = predict_corners(9.9, 9.9, 9.9, 9.9, LAH, LAA, home_games=0, away_games=0)
    assert out["expected"]["total"] == pytest.approx(LAH + LAA, abs=0.1)


def test_small_sample_shrinks_towards_league_average():
    few = predict_corners(9.0, LAA, LAA, LAH, LAH, LAA, home_games=1, away_games=10)
    many = predict_corners(9.0, LAA, LAA, LAH, LAH, LAA, home_games=30, away_games=10)
    assert LAH < few["expected"]["home"] < many["expected"]["home"]


def test_invalid_league_average_unavailable():
    out = predict_corners(1, 1, 1, 1, 0, LAA)
    assert out["available"] is False


def _rows(n_matches=12, home_id=1, away_id=2):
    rows = []
    for i in range(n_matches):
        # đội 1 đá sân nhà 6 trận góc cao; đội 2 đá sân khách 6 trận; còn lại là các đội khác
        if i < 6:
            rows.append({"home_team_id": home_id, "away_team_id": 90 + i, "home_corners": 8, "away_corners": 5})
        elif i < 9:
            rows.append({"home_team_id": 80 + i, "away_team_id": away_id, "home_corners": 6, "away_corners": 5})
        else:
            rows.append({"home_team_id": 70 + i, "away_team_id": 60 + i, "home_corners": 5, "away_corners": 4})
    return rows


def test_estimate_from_matches_teams_scope():
    est = estimate_from_matches(_rows(), home_id=1, away_id=2)
    assert est["available"] and est["scope"] == "teams"
    assert est["matches"] == 12 and est["home_games"] == 6 and est["away_games"] == 3
    assert est["league_avg_home_corners"] == pytest.approx((6 * 8 + 3 * 6 + 3 * 5) / 12)
    pred = est["prediction"]
    assert pred["available"] and pred["expected"]["total"] > est["league_avg_home_corners"] + est["league_avg_away_corners"]


def test_estimate_from_matches_insufficient_total():
    est = estimate_from_matches(_rows()[:5], home_id=1, away_id=2)
    assert est["available"] is False and est["matches"] == 5
    assert "prediction" not in est


def test_estimate_from_matches_insufficient_team_sample():
    rows = _rows()
    rows[6] = {**rows[6], "away_team_id": 999}   # đội 2 chỉ còn 2 trận sân khách (< 3), tổng vẫn đủ 12 trận
    est = estimate_from_matches(rows, home_id=1, away_id=2)
    assert est["available"] is False
    assert est["away_games"] == 2 and est["home_games"] == 6
    assert "prediction" not in est


def test_estimate_from_matches_ignores_rows_without_corners():
    rows = _rows() + [{"home_team_id": 1, "away_team_id": 2, "home_corners": None, "away_corners": None},
                      {"home_team_id": 3, "away_team_id": 4}]
    est = estimate_from_matches(rows)
    assert est["matches"] == 12 and est["available"] and est["scope"] == "league"
    # không truyền đội -> dự đoán mức giải: tổng kỳ vọng = trung bình giải
    assert est["prediction"]["expected"]["total"] == pytest.approx(
        est["league_avg_home_corners"] + est["league_avg_away_corners"], abs=0.1)
