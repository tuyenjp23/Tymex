"""So sánh xác suất của mô hình với thị trường cược cho MỘT trận, kèm diễn giải bằng tiếng Việt (không phải lời khuyên cá cược)."""
from __future__ import annotations

SMALL, LARGE = 0.05, 0.12   # chênh lệch tuyệt đối lớn nhất giữa mô hình và thị trường (đơn vị: xác suất)


def market_probabilities(odds_home: float, odds_draw: float, odds_away: float) -> tuple[float, float, float, float]:
    """Trả về (p_nhà, p_hòa, p_khách, biên lợi nhuận nhà cái) sau khi chuẩn hóa để tổng = 1."""
    inv = [1.0 / odds_home, 1.0 / odds_draw, 1.0 / odds_away]
    total = sum(inv)
    return inv[0] / total, inv[1] / total, inv[2] / total, total - 1.0


def build_market_block(odds: dict | None, prediction: dict | None, home_name: str, away_name: str) -> dict:
    if not odds:
        return {"available": False,
                "reason": "Chưa có tỷ lệ cược cho trận này. Tỷ lệ thị trường được cập nhật tự động cho các trận trong vòng 72 giờ trước giờ bóng lăn."}
    ph, pd, pa, margin = market_probabilities(odds["odds_home"], odds["odds_draw"], odds["odds_away"])
    block = {"available": True, "source": odds["source"], "updated_at": odds["updated_at"],
             "market": {"home": round(ph, 4), "draw": round(pd, 4), "away": round(pa, 4)},
             "odds": {"home": odds["odds_home"], "draw": odds["odds_draw"], "away": odds["odds_away"]},
             "margin": round(margin, 4), "model": None, "diff": None, "verdict": None, "level": None}
    if not prediction or not prediction.get("available"):
        block["verdict"] = "Mô hình chưa đủ dữ liệu để dự đoán nên chưa so sánh được. Tỷ lệ cược trên chỉ để tham khảo."
        block["level"] = "none"
        return block
    mine = {"home": prediction["p_home"], "draw": prediction["p_draw"], "away": prediction["p_away"]}
    diff = {k: round(mine[k] - block["market"][k], 4) for k in mine}
    biggest = max(diff, key=lambda k: abs(diff[k]))
    gap = abs(diff[biggest])
    names = {"home": f"{home_name} thắng", "draw": "Hòa", "away": f"{away_name} thắng"}
    direction = "cao hơn" if diff[biggest] > 0 else "thấp hơn"
    fav_model, fav_mkt = max(mine, key=mine.get), max(block["market"], key=block["market"].get)
    if gap < SMALL:
        level = "agree"
        text = ("Mô hình và thị trường cược gần như đồng thuận (chênh lệch lớn nhất dưới 5 điểm phần trăm). "
                "Thị trường đã tính cả chấn thương và đội hình, nên sự đồng thuận này làm nhận định đáng tin hơn.")
    elif gap < LARGE:
        level = "mild"
        text = (f"Mô hình đánh giá \"{names[biggest]}\" {direction} thị trường khoảng {gap * 100:.0f} điểm phần trăm. "
                "Mức chênh vừa phải, có thể do thị trường biết thêm tin chấn thương/đội hình mà mô hình (chỉ nhìn tỷ số cũ) không biết.")
    else:
        level = "large"
        text = (f"Mô hình đánh giá \"{names[biggest]}\" {direction} thị trường tới {gap * 100:.0f} điểm phần trăm. "
                "Chênh lệch lớn thường nghĩa là mô hình đang thiếu thông tin (chấn thương, treo giò, đội hình, lịch dồn): "
                "hãy kiểm tra tin tức trước khi tin vào con số của mô hình.")
    if fav_model != fav_mkt:
        text += f" Hai bên cũng không cùng chọn cửa được đánh giá cao nhất (mô hình: {names[fav_model]}; thị trường: {names[fav_mkt]})."
    text += " Đây là so sánh thống kê, không phải lời khuyên cá cược."
    block.update(model={k: round(v, 4) for k, v in mine.items()}, diff=diff, verdict=text, level=level)
    return block
