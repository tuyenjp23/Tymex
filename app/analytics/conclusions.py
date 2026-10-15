"""Kết luận phân tích bằng quy tắc. Mỗi mục tách rõ DỮ KIỆN (số liệu) và SUY LUẬN (diễn giải từ số liệu)."""
from __future__ import annotations


def _better(a: float | None, b: float | None, threshold: float, higher_is_better: bool = True) -> str | None:
    """'a' / 'b' / 'even' / None (thiếu dữ liệu)."""
    if a is None or b is None:
        return None
    diff = (a - b) if higher_is_better else (b - a)
    if diff >= threshold:
        return "a"
    if diff <= -threshold:
        return "b"
    return "even"


def build_conclusions(home: str, away: str, home_form: dict, away_form: dict, home_venue: dict, away_venue: dict,
                      h2h: dict, prediction: dict, advanced_available: bool) -> dict:
    items: list[dict] = []
    gaps: list[str] = []
    hs, as_ = home_form["summary"], away_form["summary"]
    n_form = home_form["requested"]

    # --- phong độ
    if hs["played"] and as_["played"]:
        fact = (f"{home}: {hs['points']} điểm/{hs['played']} trận ({hs['wins']}T-{hs['draws']}H-{hs['losses']}B); "
                f"{away}: {as_['points']} điểm/{as_['played']} trận ({as_['wins']}T-{as_['draws']}H-{as_['losses']}B).")
        c = _better(hs["points_per_game"], as_["points_per_game"], 0.4)
        inf = {"a": f"{home} có phong độ tốt hơn rõ rệt.", "b": f"{away} có phong độ tốt hơn rõ rệt.",
               "even": "Phong độ hai đội tương đương (chênh lệch dưới 0,4 điểm/trận)."}[c]
        if hs["played"] < n_form or as_["played"] < n_form:
            inf += f" Lưu ý: không đủ {n_form} trận cho cả hai đội nên độ tin cậy thấp hơn."
        items.append({"topic": "Phong độ gần đây", "fact": fact, "inference": inf})
    else:
        gaps.append("Thiếu dữ liệu phong độ gần đây của ít nhất một đội.")

    # --- ghi bàn
    if hs["played"] and as_["played"]:
        fact = (f"Bàn thắng/trận: {home} {hs['avg_goals_for']}, {away} {as_['avg_goals_for']}; "
                f"số trận không ghi bàn: {hs['failed_to_score']} và {as_['failed_to_score']}.")
        c = _better(hs["avg_goals_for"], as_["avg_goals_for"], 0.3)
        inf = {"a": f"{home} ghi bàn đều và nhiều hơn.", "b": f"{away} ghi bàn đều và nhiều hơn.",
               "even": "Khả năng ghi bàn của hai đội tương đương."}[c]
        items.append({"topic": "Khả năng ghi bàn", "fact": fact, "inference": inf})

        # --- phòng ngự
        fact = (f"Bàn thua/trận: {home} {hs['avg_goals_against']}, {away} {as_['avg_goals_against']}; "
                f"giữ sạch lưới: {hs['clean_sheets']} và {as_['clean_sheets']} trận.")
        c = _better(hs["avg_goals_against"], as_["avg_goals_against"], 0.3, higher_is_better=False)
        inf = {"a": f"{home} phòng ngự chắc chắn hơn.", "b": f"{away} phòng ngự chắc chắn hơn.",
               "even": "Hai đội có hiệu quả phòng ngự tương đương."}[c]
        items.append({"topic": "Phòng ngự", "fact": fact, "inference": inf})

    # --- sân nhà / sân khách
    hv, av = home_venue["summary"], away_venue["summary"]
    if hv["played"] >= 3 and av["played"] >= 3:
        fact = (f"{home} trên sân nhà ({hv['played']} trận gần nhất): {hv['points_per_game']} điểm/trận, "
                f"{hv['avg_goals_for']} bàn ghi, {hv['avg_goals_against']} bàn thủng. "
                f"{away} trên sân khách ({av['played']} trận gần nhất): {av['points_per_game']} điểm/trận, "
                f"{av['avg_goals_for']} bàn ghi, {av['avg_goals_against']} bàn thủng.")
        c = _better(hv["points_per_game"], av["points_per_game"], 0.4)
        inf = {"a": f"Yếu tố sân bãi nghiêng về {home}: họ chơi tốt tại sân nhà hơn mức {away} thể hiện khi đá sân khách.",
               "b": f"{away} có thành tích sân khách tốt hơn thành tích sân nhà của {home}, lợi thế sân nhà không rõ.",
               "even": "Thành tích sân nhà của chủ nhà và sân khách của đội khách ở mức tương đương."}[c]
        items.append({"topic": "Sân nhà / sân khách", "fact": fact, "inference": inf})
    else:
        gaps.append("Số trận sân nhà/sân khách quá ít (dưới 3) để rút ra nhận định về yếu tố sân bãi.")

    # --- đối đầu
    hh = h2h["summary"]
    if hh["played"] >= 3:
        fact = (f"{h2h['available']} trận đối đầu gần nhất có dữ liệu: {home} thắng {hh['a_wins']}, hòa {hh['draws']}, "
                f"{away} thắng {hh['b_wins']}; bàn thắng {hh['a_goals']}-{hh['b_goals']}.")
        inf = ("Lịch sử đối đầu chỉ mang tính tham khảo vì đội hình và phong độ đã thay đổi theo thời gian; "
               + ("nghiêng về " + home if hh["a_wins"] - hh["b_wins"] >= 2 else
                  "nghiêng về " + away if hh["b_wins"] - hh["a_wins"] >= 2 else "không nghiêng rõ về đội nào") + ".")
        items.append({"topic": "Lịch sử đối đầu", "fact": fact, "inference": inf})
    else:
        gaps.append(f"Lịch sử đối đầu chỉ có {hh['played']} trận trong dữ liệu đã đồng bộ nên không đủ ý nghĩa thống kê.")

    # --- dự đoán mô hình
    if prediction.get("available"):
        pc = prediction["percent"]
        fact = (f"Mô hình Poisson: {home} thắng {pc['home']}%, hòa {pc['draw']}%, {away} thắng {pc['away']}%; "
                f"bàn thắng kỳ vọng {prediction['lambda_home']:.2f} - {prediction['lambda_away']:.2f}.")
        top = max(pc, key=pc.get)
        if pc[top] < 45:
            inf = "Trận đấu khá cân bằng: không kết quả nào vượt 45%, nên kết quả rất nhạy với các yếu tố ngoài số liệu."
        else:
            inf = f"Mô hình thiên về {'chủ nhà' if top == 'home' else 'đội khách' if top == 'away' else 'kết quả hòa'}, nhưng xác suất còn lại vẫn đáng kể."
        if prediction["quality"]["reliability"] == "thấp":
            inf += " Độ tin cậy của ước lượng thấp do mẫu dữ liệu nhỏ."
        items.append({"topic": "Dự đoán thống kê", "fact": fact, "inference": inf})
    else:
        gaps.append(prediction.get("reason", "Chưa có dự đoán do thiếu dữ liệu."))

    # --- những yếu tố có thể đổi kết quả
    factors = ["Chấn thương, treo giò và đội hình xuất phát (nguồn dữ liệu hiện tại không xác nhận)",
               "Lịch thi đấu dồn dập hoặc mục tiêu khác nhau của hai đội trong mùa giải",
               "Biến động ngẫu nhiên vốn có của bóng đá: trận ít bàn thắng rất dễ bị một tình huống đảo ngược"]
    items.append({"topic": "Yếu tố có thể thay đổi kết quả", "fact": "Không có dữ liệu xác nhận các yếu tố sau trong hệ thống.",
                  "inference": "; ".join(factors) + "."})

    if not advanced_available:
        gaps.append("Không có xG, cú sút, kiểm soát bóng, cơ hội tạo ra từ nguồn dữ liệu hiện tại.")
    gaps.append("Không có thông tin chấn thương, treo giò và đội hình dự kiến từ nguồn dữ liệu hiện tại.")
    return {"items": items, "data_gaps": gaps}
