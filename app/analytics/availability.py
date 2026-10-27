"""Khối "vắng mặt/chấn thương" của một trận: danh sách cầu thủ + xác suất điều chỉnh tham khảo.

Điều chỉnh CHỈ để tham khảo: không ghi đè dự đoán đã lưu trước trận (dùng cho thống kê độ chính xác) và chưa được kiểm chứng.
Hệ thống không biết cầu thủ vắng mặt đá chính hay dự bị, nên mỗi người chỉ trừ một mức nhỏ, có trần.
"""
from __future__ import annotations

import os

from ..prediction.poisson import outcome_probabilities, score_matrix

PER_OUT, PER_DOUBT, CAP = 0.025, 0.010, 0.12   # mức giảm lực tấn công của đội mỗi cầu thủ vắng / nghi ngờ; trần tổng
DEF_SHARE = 0.5                                 # đối thủ được cộng thêm bằng ngần này của mức giảm


def team_penalty(n_out: int, n_doubt: int) -> float:
    return min(CAP, PER_OUT * n_out + PER_DOUBT * n_doubt)


def build_availability_block(absences: list[dict], prediction: dict | None, match: dict, *, upcoming: bool) -> dict:
    if not upcoming:
        return {"available": False, "reason": "Trận đã/đang diễn ra: không hiển thị danh sách vắng mặt (không có dữ liệu tại thời điểm trước trận)."}
    if not absences:
        return {"available": False,
                "reason": "Chưa có tin vắng mặt cho trận này (cần API_FOOTBALL_KEY và trận nằm trong khung 72 giờ tới; "
                          "nguồn có thể chưa cập nhật). Không có tin không có nghĩa là mọi cầu thủ đều sẵn sàng."}
    teams = {}
    for side, tid, name in (("home", match["home_team_id"], match["home_name"]), ("away", match["away_team_id"], match["away_name"])):
        rows = [a for a in absences if a["team_id"] == tid]
        teams[side] = {"team": name,
                       "out": [{"player": a["player"], "reason": a["reason"]} for a in rows if a["kind"] == "out"],
                       "doubtful": [{"player": a["player"], "reason": a["reason"]} for a in rows if a["kind"] == "doubtful"]}
    block = {"available": True, "teams": teams, "updated_at": max(a["updated_at"] for a in absences),
             "source": absences[0]["source"], "adjusted": None, "note": None}
    if not (prediction and prediction.get("available") and "lambda_home" in prediction):
        return block
    if (os.environ.get("AVAILABILITY_ADJUST") or "1").strip() == "0":
        return block
    ph = team_penalty(len(teams["home"]["out"]), len(teams["home"]["doubtful"]))
    pa = team_penalty(len(teams["away"]["out"]), len(teams["away"]["doubtful"]))
    if ph == 0 and pa == 0:
        return block
    lam_h = prediction["lambda_home"] * (1 - ph) * (1 + DEF_SHARE * pa)
    lam_a = prediction["lambda_away"] * (1 - pa) * (1 + DEF_SHARE * ph)
    h, d, a = outcome_probabilities(score_matrix(lam_h, lam_a))
    base = {"home": prediction["p_home"], "draw": prediction["p_draw"], "away": prediction["p_away"]}
    adj = {"home": h, "draw": d, "away": a}
    block["adjusted"] = {"before": {k: round(v, 4) for k, v in base.items()}, "after": {k: round(v, 4) for k, v in adj.items()},
                         "penalty": {"home": round(ph, 3), "away": round(pa, 3)}}
    block["note"] = ("Xác suất điều chỉnh chỉ là ước lượng thô: mỗi cầu thủ vắng trừ một mức nhỏ vào khả năng ghi bàn của đội, "
                     "không phân biệt đá chính hay dự bị và CHƯA được kiểm chứng. Dự đoán đã lưu trước trận không bị thay đổi.")
    return block
