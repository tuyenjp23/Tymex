"""Thị trường suy ra từ ma trận tỷ số + bản "Nhận định dự đoán" (verdict) có cấu trúc — hàm thuần.

Từ cùng một ma trận tỷ số Dixon-Coles của `poisson.py`, suy ra nhất quán:
 - Tài/Xỉu bàn thắng ở nhiều mốc (0,5 / 1,5 / 2,5 / 3,5 / 4,5) — trước đây dự đoán chỉ lộ mốc 2,5.
 - Cả hai đội ghi bàn (BTTS) và cơ hội kép (1X, 12, X2).

`build_verdict` gom các lựa chọn THẬT SỰ đáng nêu thành danh sách `picks`, theo ngưỡng cố định dùng
chung toàn hệ thống (cả bản web trong web/live.js phải giữ đúng các ngưỡng này):
 - xác suất >= 0,65 → nhãn "Mạnh"; >= 0,57 → nhãn "Khá"; dưới 0,57 thì KHÔNG khuyến nghị.
 - Nếu không có lựa chọn nào đạt 0,57, chỉ nêu đúng MỘT lựa chọn tốt nhất (miễn là >= 0,50) với nhãn
   "Cân nhắc" và nói rõ trong reasoning là chưa có lựa chọn đủ mạnh.
 - Không bao giờ nêu lựa chọn có xác suất < 0,50 trong `picks`.
 - Tỷ số dự đoán đơn lẻ luôn có xác suất thấp (~10-15%) nên nằm ở trường `score` riêng (mức tham khảo),
   không bao giờ trà trộn vào `picks` như một khuyến nghị.
"""
from __future__ import annotations

from .poisson import outcome_probabilities, score_matrix

GOAL_LINES = (0.5, 1.5, 2.5, 3.5, 4.5)
PICK_STRONG = 0.65      # >= ngưỡng này: nhãn "Mạnh"
PICK_OK = 0.57          # >= ngưỡng này: nhãn "Khá"; dưới ngưỡng này không khuyến nghị
PICK_FLOOR = 0.50       # sàn tuyệt đối: không nêu lựa chọn nào dưới mức này trong picks
DISCLAIMER = "Nhận định tham khảo từ mô hình thống kê — không phải lời khuyên cá cược."


def strength_label(probability: float) -> str | None:
    """Nhãn độ mạnh của một lựa chọn theo xác suất; None = không đủ mạnh để khuyến nghị."""
    if probability >= PICK_STRONG:
        return "Mạnh"
    if probability >= PICK_OK:
        return "Khá"
    return None


def goal_lines(matrix: list[list[float]] | None = None, lambda_home: float | None = None,
               lambda_away: float | None = None, rho: float = -0.08) -> dict:
    """Xác suất Tài/Xỉu bàn thắng theo từng mốc + BTTS + cơ hội kép, từ ma trận tỷ số.

    Truyền `matrix` (ma trận đã chuẩn hóa, hàng = bàn chủ nhà, cột = bàn đội khách) hoặc cặp
    `lambda_home`/`lambda_away` (hàm tự dựng ma trận Dixon-Coles với `rho`, mặc định -0,08 như mô hình chính).
    Với mỗi mốc L: Tài = P(tổng bàn > L), Xỉu = 1 − Tài (mốc lẻ ,5 nên không có trường hợp "đúng mốc")."""
    if matrix is None:
        if lambda_home is None or lambda_away is None:
            raise ValueError("goal_lines cần matrix hoặc cặp lambda_home/lambda_away")
        matrix = score_matrix(lambda_home, lambda_away, rho=rho)
    total_dist: dict[int, float] = {}
    btts = 0.0
    expected_total = 0.0
    for i, row in enumerate(matrix):
        for j, v in enumerate(row):
            total_dist[i + j] = total_dist.get(i + j, 0.0) + v
            expected_total += (i + j) * v
            if i >= 1 and j >= 1:
                btts += v
    lines = []
    for line in GOAL_LINES:
        over = sum(v for t, v in total_dist.items() if t > line)
        lines.append({"line": line, "over": round(over, 4), "under": round(1.0 - over, 4)})
    p_h, p_d, p_a = outcome_probabilities(matrix)
    return {
        "lines": lines,
        "expected_total_goals": round(expected_total, 3),
        "btts": {"yes": round(btts, 4), "no": round(1.0 - btts, 4)},
        "double_chance": {"1X": round(p_h + p_d, 4), "12": round(p_h + p_a, 4), "X2": round(p_d + p_a, 4)},
    }


def _fmt_line(x: float) -> str:
    return f"{x:.1f}".replace(".", ",")


def build_verdict(prediction: dict, home_name: str = "Chủ nhà", away_name: str = "Đội khách") -> dict:
    """Bản nhận định có cấu trúc từ một kết quả `predict()` (dict có available=True).

    Trả về {"picks": [...], "score": {...}, "reasoning": [...], "summary": str, "disclaimer": str}.
    Mỗi pick: {"market", "selection", "probability", "strength"} — chỉ chứa lựa chọn >= 0,50 như đã
    ghi ở đầu module; "reasoning" gồm 2-4 dòng diễn giải lấy từ factors/quality của chính dự đoán."""
    mk = prediction.get("markets") or goal_lines(lambda_home=prediction["lambda_home"],
                                                lambda_away=prediction["lambda_away"],
                                                rho=prediction.get("dixon_coles_rho", -0.08))
    candidates: list[dict] = []

    # 1X2: lấy kết quả có xác suất cao nhất.
    outcomes = [("home", prediction["p_home"], f"{home_name} thắng"),
                ("draw", prediction["p_draw"], "Hòa"),
                ("away", prediction["p_away"], f"{away_name} thắng")]
    _, p_best, sel_best = max(outcomes, key=lambda x: x[1])
    candidates.append({"market": "1x2", "selection": sel_best, "probability": round(p_best, 4)})

    # Tài/Xỉu bàn thắng: với mỗi mốc lấy phía (Tài hoặc Xỉu) có xác suất cao hơn, rồi lấy mốc tốt nhất.
    ou_best = None
    for ln in mk["lines"]:
        for side, prob in (("Tài", ln["over"]), ("Xỉu", ln["under"])):
            if ou_best is None or prob > ou_best["probability"]:
                ou_best = {"market": "goals_ou", "selection": f"{side} { _fmt_line(ln['line'])} bàn",
                           "probability": round(prob, 4)}
    if ou_best:
        candidates.append(ou_best)

    # BTTS: lấy phía cao hơn (cả hai đội ghi bàn / ít nhất một đội không ghi bàn).
    b = mk["btts"]
    btts_sel, btts_p = ("Cả hai đội cùng ghi bàn", b["yes"]) if b["yes"] >= b["no"] \
        else ("Ít nhất một đội không ghi bàn", b["no"])
    candidates.append({"market": "btts", "selection": btts_sel, "probability": round(btts_p, 4)})

    candidates.sort(key=lambda c: c["probability"], reverse=True)
    picks: list[dict] = []
    for c in candidates:
        label = strength_label(c["probability"])
        if label:
            picks.append({**c, "strength": label})
    fallback_note = None
    if not picks and candidates and candidates[0]["probability"] >= PICK_FLOOR:
        picks = [{**candidates[0], "strength": "Cân nhắc"}]
        fallback_note = ("Chưa có lựa chọn nào đủ mạnh theo ngưỡng của mô hình (cần ≥ 57%); lựa chọn nêu trên "
                         "chỉ ở mức cân nhắc, là lựa chọn tốt nhất hiện có.")
    picks = picks[:4]

    quality = prediction.get("quality") or {}
    reasoning: list[str] = []
    lam_h, lam_a = prediction.get("lambda_home"), prediction.get("lambda_away")
    if lam_h is not None and lam_a is not None:
        reasoning.append(f"Bàn thắng kỳ vọng: {home_name} {lam_h:.2f} — {away_name} {lam_a:.2f} "
                         f"(tổng kỳ vọng {mk['expected_total_goals']:.2f} bàn).")
    for f in (prediction.get("factors") or [])[:2]:
        reasoning.append(f["text"])
    if quality:
        reasoning.append(f"Độ tin cậy mô hình: {quality.get('reliability', '—')} — dựa trên "
                         f"{quality.get('league_games', '—')} trận của giải, {quality.get('home_games', '—')} trận "
                         f"của {home_name}, {quality.get('away_games', '—')} trận của {away_name}.")
    if fallback_note:
        reasoning.append(fallback_note)
    reasoning = reasoning[:4]

    score = prediction.get("predicted_score") or {}
    score_out = {"home": score.get("home"), "away": score.get("away"), "prob": score.get("prob")}
    if picks:
        top = picks[0]
        summary = (f"Nhận định chính: {top['selection']} ({top['probability'] * 100:.0f}%, mức {top['strength']}). "
                   f"Tỷ số dự đoán: {score_out['home']}-{score_out['away']}.")
    else:
        summary = (f"Không có lựa chọn nào đạt xác suất 50% — trận cân bằng/khó lường theo mô hình. "
                   f"Tỷ số dự đoán: {score_out['home']}-{score_out['away']}.")
    return {"picks": picks, "score": score_out, "reasoning": reasoning,
            "summary": summary, "disclaimer": DISCLAIMER}
