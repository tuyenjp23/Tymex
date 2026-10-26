"""Dự đoán TRỰC TIẾP trong trận (kiểu FotMob) và MÔ PHỎNG trận đấu — hàm thuần, không I/O.

Ý tưởng: lấy λ trước trận (bàn thắng kỳ vọng cả trận của mô hình Poisson/Dixon-Coles) rồi chỉ mô hình
hóa phần thời gian CÒN LẠI: λ_còn_lại = λ × (phút còn lại / tổng phút hiệu dụng), điều chỉnh theo
trạng thái trận đấu, cộng phân phối bàn thắng còn lại vào tỷ số hiện tại để ra phân phối tỷ số chung cuộc.

Các hằng số (cố ý giữ khiêm tốn, ghi rõ để ai đọc cũng kiểm chứng được):
 - FULL_MINUTES = 95: một trận coi như 95 phút hiệu dụng (90 phút chính thức + bù giờ hai hiệp trung bình ~5 phút).
 - Đội đang THUA được nhân λ còn lại ×1,12 cho mỗi bàn thua (tối đa 2 bàn): đội thua dồn lên tấn công.
 - Đội đang THẮNG bị nhân ×0,90 cho mỗi bàn thắng (tối đa 2 bàn): đội dẫn thường lùi sâu bảo toàn tỷ số.
 - Thẻ đỏ: đội bị thẻ nhân λ của mình ×0,72 cho mỗi thẻ, đối thủ được ×1,10 cho mỗi thẻ của đội kia
   (mất người vừa khó ghi bàn vừa dễ thủng lưới hơn). Hệ số nhân theo lũy thừa số thẻ.
 - Ma trận bàn thắng còn lại dùng cùng hiệu chỉnh Dixon-Coles (rho = ModelParams().dixon_coles_rho).

`simulate_match` là MÔ PHỎNG Monte Carlo một trận duy nhất (không phải diễn biến thật): chia trận thành
từng phút, mỗi phút mỗi đội ghi bàn với xác suất suy từ λ của phút đó qua phân phối Poisson; sau mỗi phút
gọi lại `predict_live` trên trạng thái mô phỏng để có xác suất thắng/hòa/thua trực tiếp. Truyền `seed`
thì kết quả lặp lại y hệt (phục vụ kiểm thử và minh họa).
"""
from __future__ import annotations

import math
import random

from .poisson import MODEL_VERSION, ModelParams, outcome_probabilities, round_to_100, score_matrix

LIVE_MODEL_VERSION = f"{MODEL_VERSION}+live-v1"
SIM_MODEL_VERSION = f"{MODEL_VERSION}+sim-v1"

FULL_MINUTES = 95.0          # 90 phút + ~5 phút bù giờ trung bình
TRAILING_BOOST_PER_GOAL = 1.12
LEADING_DAMP_PER_GOAL = 0.90
MAX_STATE_GOALS = 2          # hiệu ứng trạng thái chỉ tính tối đa chênh lệch 2 bàn
RED_CARD_OWN_FACTOR = 0.72
RED_CARD_OPP_FACTOR = 1.10
DEFAULT_RHO = ModelParams().dixon_coles_rho
MAX_GOALS = 10


def _state_factor(goal_diff_for_team: int) -> float:
    """Hệ số trạng thái cho MỘT đội: goal_diff_for_team = bàn thắng của đội đó − bàn thua."""
    d = max(-MAX_STATE_GOALS, min(MAX_STATE_GOALS, goal_diff_for_team))
    if d < 0:
        return TRAILING_BOOST_PER_GOAL ** (-d)
    if d > 0:
        return LEADING_DAMP_PER_GOAL ** d
    return 1.0


def remaining_lambdas(lambda_home: float, lambda_away: float, minute: float, home_score: int, away_score: int,
                      home_red_cards: int = 0, away_red_cards: int = 0) -> tuple[float, float]:
    """λ cho phần thời gian còn lại sau khi áp hệ số trạng thái tỷ số và thẻ đỏ."""
    remaining = max(FULL_MINUTES - max(minute, 0.0), 0.0) / FULL_MINUTES
    diff = home_score - away_score
    lam_h = lambda_home * remaining * _state_factor(diff) \
        * (RED_CARD_OWN_FACTOR ** home_red_cards) * (RED_CARD_OPP_FACTOR ** away_red_cards)
    lam_a = lambda_away * remaining * _state_factor(-diff) \
        * (RED_CARD_OWN_FACTOR ** away_red_cards) * (RED_CARD_OPP_FACTOR ** home_red_cards)
    return lam_h, lam_a


def predict_live(lambda_home: float, lambda_away: float, minute: float, home_score: int, away_score: int,
                 home_red_cards: int = 0, away_red_cards: int = 0) -> dict:
    """Dự đoán trực tiếp tại một thời điểm của trận.

    Đầu vào là λ TRƯỚC TRẬN của hai đội (từ dự đoán đã lưu), phút hiện tại, tỷ số hiện tại và số thẻ đỏ.
    Trả về xác suất thắng/hòa/thua trực tiếp, các tỷ số CHUNG CUỘC khả dĩ nhất, tỷ số kỳ vọng chung cuộc
    và xác suất bàn thắng tiếp theo. Phút < 0 được kẹp về 0; phút >= FULL_MINUTES thì trận coi như đã hết:
    xác suất dồn hết vào kết quả hiện tại."""
    minute = max(0.0, float(minute))
    home_score, away_score = max(0, int(home_score)), max(0, int(away_score))
    rem_h, rem_a = remaining_lambdas(lambda_home, lambda_away, minute, home_score, away_score,
                                     home_red_cards, away_red_cards)

    matrix = score_matrix(rem_h, rem_a, MAX_GOALS, rho=DEFAULT_RHO)
    # Dịch ma trận "bàn thắng còn lại" theo tỷ số hiện tại thành phân phối tỷ số chung cuộc.
    final: dict[tuple[int, int], float] = {}
    for i, row in enumerate(matrix):
        for j, v in enumerate(row):
            if v:
                final[(home_score + i, away_score + j)] = final.get((home_score + i, away_score + j), 0.0) + v
    p_home = sum(v for (i, j), v in final.items() if i > j)
    p_draw = sum(v for (i, j), v in final.items() if i == j)
    p_away = sum(v for (i, j), v in final.items() if i < j)
    s = p_home + p_draw + p_away
    p_home, p_draw, p_away = p_home / s, p_draw / s, p_away / s
    pct = round_to_100([p_home, p_draw, p_away])
    cells = sorted(final.items(), key=lambda kv: kv[1], reverse=True)
    top = [{"home": i, "away": j, "prob": round(v, 4)} for (i, j), v in cells[:5]]

    # Bàn thắng tiếp theo: với hai quá trình Poisson độc lập, xác suất "không còn bàn nào" là
    # exp(-(λh+λa)); nếu còn bàn, bàn đó thuộc đội nào tỷ lệ với λ của đội đó. Đây là công thức chính xác
    # cho quá trình Poisson cạnh tranh, không phải ước lượng cảm tính.
    total_rem = rem_h + rem_a
    if total_rem <= 0:
        next_goal = {"home": 0.0, "away": 0.0, "none": 1.0}
    else:
        p_none = math.exp(-total_rem)
        p_any = 1.0 - p_none
        next_goal = {"home": round(p_any * rem_h / total_rem, 4), "away": round(p_any * rem_a / total_rem, 4),
                     "none": round(p_none, 4)}

    return {
        "available": True,
        "model_version": LIVE_MODEL_VERSION,
        "minute": round(minute, 1),
        "home_score": home_score, "away_score": away_score,
        "home_red_cards": int(home_red_cards), "away_red_cards": int(away_red_cards),
        "lambda_home_remaining": round(rem_h, 3), "lambda_away_remaining": round(rem_a, 3),
        "p_home": p_home, "p_draw": p_draw, "p_away": p_away,
        "percent": {"home": pct[0], "draw": pct[1], "away": pct[2]},
        "top_final_scores": top,
        "predicted_final_score": {"home": top[0]["home"], "away": top[0]["away"], "prob": top[0]["prob"]},
        "expected_final": {"home": round(home_score + rem_h, 2), "away": round(away_score + rem_a, 2)},
        "next_goal": next_goal,
        "notes": [
            "Dự đoán trực tiếp chỉ suy từ λ trước trận, tỷ số và phút hiện tại (và thẻ đỏ nếu được cung cấp); "
            "mô hình không có dữ liệu cú sút/xG trực tiếp nên không phản ánh được thế trận ngoài các yếu tố trên.",
            f"Trận được coi là {int(FULL_MINUTES)} phút hiệu dụng (90 phút + bù giờ trung bình).",
        ],
    }


def _poisson_draw(rng: random.Random, lam: float) -> int:
    """Rút số bàn thắng trong một phút từ phân phối Poisson(lam) bằng thuật toán Knuth (lam ở đây rất nhỏ)."""
    if lam <= 0:
        return 0
    limit = math.exp(-lam)
    k, p = 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def simulate_match(lambda_home: float, lambda_away: float, seed: int | None = None,
                   home_red_cards: int = 0, away_red_cards: int = 0) -> dict:
    """MÔ PHỎNG một trận duy nhất theo từng phút — đây là diễn biến GIẢ LẬP bằng mô hình, không phải trận thật.

    Mỗi phút, λ của phút đó = λ còn lại của `predict_live` tại trạng thái hiện tại chia cho số phút còn lại,
    rút số bàn thắng bằng Poisson. Sau mỗi phút, xác suất trực tiếp được tính lại bằng chính `predict_live`
    trên tỷ số mô phỏng. `seed` cố định thì toàn bộ diễn biến lặp lại y hệt."""
    rng = random.Random(seed)
    home_score = away_score = 0
    events: list[dict] = []
    timeline: list[dict] = []
    total_minutes = int(FULL_MINUTES)
    for minute in range(0, total_minutes + 1):
        live = predict_live(lambda_home, lambda_away, minute, home_score, away_score,
                            home_red_cards, away_red_cards)
        timeline.append({
            "minute": minute, "home_score": home_score, "away_score": away_score,
            "p_home": round(live["p_home"], 4), "p_draw": round(live["p_draw"], 4), "p_away": round(live["p_away"], 4),
            "percent": live["percent"],
        })
        if minute >= total_minutes:
            break
        rem_h, rem_a = remaining_lambdas(lambda_home, lambda_away, minute, home_score, away_score,
                                         home_red_cards, away_red_cards)
        minutes_left = FULL_MINUTES - minute
        gh = _poisson_draw(rng, rem_h / minutes_left)
        ga = _poisson_draw(rng, rem_a / minutes_left)
        for _ in range(gh):
            home_score += 1
            events.append({"minute": minute + 1, "type": "goal", "side": "home",
                           "home_score": home_score, "away_score": away_score})
        for _ in range(ga):
            away_score += 1
            events.append({"minute": minute + 1, "type": "goal", "side": "away",
                           "home_score": home_score, "away_score": away_score})
    final_live = timeline[-1]
    return {
        "simulated": True,
        "model_version": SIM_MODEL_VERSION,
        "seed": seed,
        "lambda_home": lambda_home, "lambda_away": lambda_away,
        "final_score": {"home": home_score, "away": away_score},
        "events": events,
        "timeline": timeline,
        "final_percent": final_live["percent"],
        "note": "MÔ PHỎNG bằng mô hình thống kê — không phải diễn biến thật của trận đấu.",
    }
