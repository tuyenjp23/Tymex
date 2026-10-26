import pytest

from app.prediction.lineups import adjust_lambdas, missing_regulars, normalize_position_group

PREV_XI = [
    {"name": "Thủ Môn A", "position_group": "GK"},
    {"name": "Hậu Vệ B", "position_group": "DEF"},
    {"name": "Tiền Vệ C", "position_group": "MID"},
    {"name": "Tiền Đạo D", "position_group": "FWD"},
]


def test_normalize_position_group_from_codes_and_names():
    assert normalize_position_group("GK") == "GK"
    assert normalize_position_group("CB") == "DEF"
    assert normalize_position_group("AM") == "MID"
    assert normalize_position_group("ST") == "FWD"
    assert normalize_position_group("Center Back") == "DEF"
    assert normalize_position_group("Attacking Midfielder") == "MID"
    assert normalize_position_group("Goalkeeper") == "GK"
    assert normalize_position_group("Substitute") is None


def test_missing_regulars_counts_bench_as_present():
    current = {
        "starters": [{"name": "Thủ Môn A"}, {"name": "Hậu Vệ B"}, {"name": "Tiền Vệ C"}],
        "substitutes": [{"name": "Tiền Đạo D"}],
    }
    out = missing_regulars(current, PREV_XI)
    assert out["status"] == "available" and out["bench_known"] is True
    assert out["missing"] == []


def test_missing_regulars_without_bench_is_noted():
    current = [{"name": "Thủ Môn A"}, {"name": "Hậu Vệ B"}]
    out = missing_regulars(current, PREV_XI)
    assert out["bench_known"] is False
    assert {m["name"] for m in out["missing"]} == {"Tiền Vệ C", "Tiền Đạo D"}
    assert any("chỉ đối chiếu với đội hình xuất phát" in n for n in out["notes"])


def test_missing_regulars_unpublished_lineup():
    out = missing_regulars([], PREV_XI)
    assert out["status"] == "chưa công bố" and out["missing"] == []
    out2 = missing_regulars([{"name": "Thủ Môn A"}], [])
    assert out2["status"] == "thiếu dữ kiện" and out2["missing"] == []


def test_missing_regulars_matches_by_player_id_when_names_differ():
    prev = [{"id": 7, "name": "J. Smith", "position_group": "FWD"}]
    current = {"starters": [{"id": "7", "name": "John Smith"}], "substitutes": []}
    assert missing_regulars(current, prev)["missing"] == []


def test_adjust_lambdas_synthetic_example():
    """Ví dụ chuẩn để đối chiếu bản web: chủ nhà thiếu 1 FWD + 1 DEF, λ 1,70 / 1,20.
    FWD thiếu -> λ nhà ×0,96 = 1,632. DEF thiếu -> λ khách ×1,04 = 1,248."""
    out = adjust_lambdas(1.70, 1.20,
                         [{"name": "Tiền Đạo D", "position_group": "FWD"},
                          {"name": "Hậu Vệ B", "position_group": "DEF"}],
                         [])
    assert out["lambda_home"] == pytest.approx(1.632)
    assert out["lambda_away"] == pytest.approx(1.248)
    assert out["factor_home"] == pytest.approx(0.96)
    assert out["factor_away"] == pytest.approx(1.04)
    assert len(out["explanations"]) == 2


def test_adjust_lambdas_away_missing_mirror():
    out = adjust_lambdas(1.50, 1.10, [], [{"name": "X", "position_group": "MID"},
                                          {"name": "Y", "position_group": "GK"}])
    assert out["lambda_away"] == pytest.approx(1.10 * 0.96)
    assert out["lambda_home"] == pytest.approx(1.50 * 1.04)


def test_adjust_lambdas_cap_at_15_percent():
    many_forwards = [{"name": f"F{i}", "position_group": "FWD"} for i in range(8)]
    out = adjust_lambdas(2.0, 1.0, many_forwards, [])
    assert out["factor_home"] == pytest.approx(0.85)
    assert out["lambda_home"] == pytest.approx(1.70)
    many_defenders = [{"name": f"D{i}", "position_group": "DEF"} for i in range(8)]
    out2 = adjust_lambdas(1.0, 1.0, many_defenders, [])
    assert out2["factor_away"] == pytest.approx(1.15)
    assert out2["lambda_away"] == pytest.approx(1.15)


def test_adjust_lambdas_accepts_missing_regulars_result_and_no_missing():
    res = missing_regulars([{"name": "Thủ Môn Mới"}], PREV_XI)
    out = adjust_lambdas(1.40, 1.10, res, {"status": "available", "missing": []})
    # Thiếu GK + DEF + MID + FWD của chủ nhà: nhà ×0,96 hai lần (MID, FWD), khách ×1,04 hai lần (GK, DEF)
    assert out["lambda_home"] == pytest.approx(1.40 * 0.96 * 0.96, abs=0.001)
    assert out["lambda_away"] == pytest.approx(1.10 * 1.04 * 1.04, abs=0.001)
    same = adjust_lambdas(1.40, 1.10, [], [])
    assert same["lambda_home"] == 1.40 and same["lambda_away"] == 1.10
    assert same["factor_home"] == 1.0 and same["factor_away"] == 1.0


def test_adjust_lambdas_unknown_position_does_not_change_lambda():
    out = adjust_lambdas(1.40, 1.10, [{"name": "Ai Đó"}], [])
    assert out["lambda_home"] == 1.40 and out["lambda_away"] == 1.10
    assert any("chưa rõ nhóm vị trí" in e for e in out["explanations"])
