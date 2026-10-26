"""Mô hình Tài/Xỉu PHẠT GÓC — hàm thuần, cùng phong cách với `poisson.py` (tỷ lệ tấn công/phòng ngự + co về TB giải).

football-data.org (nguồn đồng bộ chính của dự án) KHÔNG có dữ liệu phạt góc, nên module này không tự
lấy dữ liệu ở đâu cả: nó nhận các TỶ LỆ GÓC đã tính ở ngoài (hiện tại từ ESPN qua
`scripts/fetch_corners_espn.py`, xem README) rồi suy ra số góc kỳ vọng:

    Góc kỳ vọng của chủ nhà  = TB góc sân nhà của giải × Tấn-công-góc_nhà(sân nhà) × Phòng-ngự-góc_khách(sân khách)
    Góc kỳ vọng của đội khách = TB góc sân khách của giải × Tấn-công-góc_khách(sân khách) × Phòng-ngự-góc_nhà(sân nhà)

trong đó mỗi tỷ lệ đội được co (shrinkage) về mức trung bình giải theo số trận mẫu, như `poisson.py`.
Tổng số góc được coi là Poisson(λ = tổng kỳ vọng) để tính Tài/Xỉu ở các mốc 7,5 … 12,5.
Ngưỡng nêu lựa chọn (pick) dùng CHUNG với `markets.py`: "Mạnh" ≥ 0,65, "Khá" ≥ 0,57, sàn tuyệt đối 0,50.
"""
from __future__ import annotations

from .markets import strength_label
from .poisson import poisson_pmf

CORNER_LINES = (7.5, 8.5, 9.5, 10.5, 11.5, 12.5)
CORNER_SHRINK_K = 3.0          # số "trận ảo" của mức trung bình giải khi co tỷ lệ của một đội
MIN_TEAM_CORNERS = 0.5
MAX_TEAM_CORNERS = 14.0
MIN_TOTAL_MATCHES = 8          # mẫu tối thiểu của giải trong estimate_from_matches
MIN_TEAM_MATCHES = 3           # mẫu tối thiểu của một đội ở đúng sân (nhà/khách) tương ứng


def _shrunk(rate: float, games: float, prior_mean: float, k: float = CORNER_SHRINK_K) -> float:
    """Co một tỷ lệ (trung bình mỗi trận) về mức trung bình giải, trọng số k trận ảo — như poisson._shrunk."""
    return (rate * games + k * prior_mean) / (games + k)


def _poisson_over(lam: float, line: float, max_k: int = 40) -> float:
    """P(X > line) với X ~ Poisson(lam); line luôn dạng ,5 nên không có trường hợp hòa mốc."""
    return sum(poisson_pmf(k, lam) for k in range(int(line) + 1, max_k + 1))


def _mode(lam: float) -> int:
    return int(lam)  # mode của Poisson(lam) là floor(lam) (khi lam nguyên có hai mode, lấy lam-1 cũng được)


def _likely_band(lam: float, cover: float = 0.5) -> list[int]:
    """Khoảng tổng số góc ngắn nhất chứa ít nhất `cover` xác suất, mở rộng dần từ mode."""
    mode = _mode(lam)
    lo = hi = mode
    p = poisson_pmf(mode, lam)
    while p < cover and (lo > 0 or hi < 40):
        p_lo = poisson_pmf(lo - 1, lam) if lo > 0 else -1.0
        p_hi = poisson_pmf(hi + 1, lam) if hi < 40 else -1.0
        if p_hi >= p_lo:
            hi += 1; p += max(p_hi, 0.0)
        else:
            lo -= 1; p += max(p_lo, 0.0)
    return [lo, hi]


def predict_corners(home_corner_for_home: float, home_corner_against_home: float,
                    away_corner_for_away: float, away_corner_against_away: float,
                    league_avg_home_corners: float, league_avg_away_corners: float,
                    home_games: float = 0, away_games: float = 0,
                    shrink_k: float = CORNER_SHRINK_K) -> dict:
    """Dự đoán phạt góc từ các tỷ lệ thô (trung bình mỗi trận) + số trận mẫu của từng đội ở đúng sân.

    - home_corner_for_home / home_corner_against_home: góc đội chủ nhà ĐƯỢC / BỊ khi đá sân nhà.
    - away_corner_for_away / away_corner_against_away: góc đội khách ĐƯỢC / BỊ khi đá sân khách.
    - home_games / away_games: số trận mẫu tương ứng (0 = không có mẫu → tỷ lệ co hết về trung bình giải,
      kết quả là trận "hai đội trung bình" chứ không phải số bịa cho đội đó)."""
    lah, laa = float(league_avg_home_corners), float(league_avg_away_corners)
    if lah <= 0 or laa <= 0:
        return {"available": False, "reason": "Trung bình phạt góc của giải không hợp lệ (<= 0)."}
    hf = _shrunk(home_corner_for_home, home_games, lah, shrink_k)
    hag = _shrunk(home_corner_against_home, home_games, laa, shrink_k)
    af = _shrunk(away_corner_for_away, away_games, laa, shrink_k)
    aag = _shrunk(away_corner_against_away, away_games, lah, shrink_k)
    exp_home = lah * (hf / lah) * (aag / lah)
    exp_away = laa * (af / laa) * (hag / laa)
    exp_home = min(max(exp_home, MIN_TEAM_CORNERS), MAX_TEAM_CORNERS)
    exp_away = min(max(exp_away, MIN_TEAM_CORNERS), MAX_TEAM_CORNERS)
    total = exp_home + exp_away

    lines = []
    for line in CORNER_LINES:
        over = _poisson_over(total, line)
        lines.append({"line": line, "over": round(over, 4), "under": round(1.0 - over, 4)})

    best = None
    for ln in lines:
        for side, prob in (("Tài", ln["over"]), ("Xỉu", ln["under"])):
            if best is None or prob > best["probability"]:
                best = {"market": "corners_ou", "selection": f"{side} góc {ln['line']:.1f}".replace(".", ","),
                        "probability": prob, "line": ln["line"], "side": side}
    pick = None
    if best is not None:
        label = strength_label(best["probability"])
        if label:
            pick = {**best, "strength": label}
        elif best["probability"] >= 0.50:
            pick = {**best, "strength": "Cân nhắc"}

    return {
        "available": True,
        "expected": {"home": round(exp_home, 2), "away": round(exp_away, 2), "total": round(total, 2)},
        "lines": lines,
        "most_likely_total": _mode(total),
        "likely_band": _likely_band(total),
        "most_likely_home": _mode(exp_home),
        "most_likely_away": _mode(exp_away),
        "pick": pick,
        "inputs": {"home_corner_for": round(hf, 3), "home_corner_against": round(hag, 3),
                   "away_corner_for": round(af, 3), "away_corner_against": round(aag, 3),
                   "league_avg_home_corners": round(lah, 3), "league_avg_away_corners": round(laa, 3),
                   "home_games": home_games, "away_games": away_games, "shrink_k": shrink_k},
        "notes": ["Số góc kỳ vọng suy từ tỷ lệ góc được/bị của hai đội (đã co về trung bình giải); "
                  "nguồn tỷ lệ góc hiện tại là ESPN — football-data.org không cung cấp phạt góc."],
    }


def estimate_from_matches(matches: list[dict], home_id: int | None = None, away_id: int | None = None,
                          min_total: int = MIN_TOTAL_MATCHES, min_team: int = MIN_TEAM_MATCHES) -> dict:
    """Tính các tỷ lệ đầu vào + trung bình giải từ danh sách trận ĐÃ ĐÁ có trường home_corners/away_corners.

    Mỗi trận là dict kiểu của dự án (home_team_id, away_team_id) cộng home_corners/away_corners (số góc
    của đội nhà / đội khách trong trận đó). Nếu truyền home_id/away_id thì tính thêm tỷ lệ sân nhà của
    đội chủ nhà và sân khách của đội khách, rồi gắn luôn kết quả `predict_corners` vào khóa "prediction".
    Mẫu không đủ thì trả {"available": False, ...} kèm số đếm thật — KHÔNG bịa số."""
    rows = [m for m in matches if m.get("home_corners") is not None and m.get("away_corners") is not None]
    n = len(rows)
    out: dict = {"matches": n}
    if n:
        out["league_avg_home_corners"] = round(sum(m["home_corners"] for m in rows) / n, 3)
        out["league_avg_away_corners"] = round(sum(m["away_corners"] for m in rows) / n, 3)
    if n < min_total:
        return {**out, "available": False,
                "reason": f"Chưa đủ dữ liệu phạt góc: cần ít nhất {min_total} trận có số liệu góc (hiện có {n})."}
    lah, laa = out["league_avg_home_corners"], out["league_avg_away_corners"]

    if home_id is None or away_id is None:
        out["available"] = True
        out["scope"] = "league"
        out["prediction"] = predict_corners(lah, laa, laa, lah, lah, laa, home_games=0, away_games=0)
        return out

    home_rows = [m for m in rows if m.get("home_team_id") == home_id]
    away_rows = [m for m in rows if m.get("away_team_id") == away_id]
    out["home_games"] = len(home_rows)
    out["away_games"] = len(away_rows)
    if len(home_rows) < min_team or len(away_rows) < min_team:
        return {**out, "available": False,
                "reason": (f"Chưa đủ dữ liệu phạt góc của từng đội: cần ít nhất {min_team} trận sân nhà của chủ nhà "
                           f"(hiện {len(home_rows)}) và {min_team} trận sân khách của đội khách (hiện {len(away_rows)}).")}
    inputs = {
        "home_corner_for_home": sum(m["home_corners"] for m in home_rows) / len(home_rows),
        "home_corner_against_home": sum(m["away_corners"] for m in home_rows) / len(home_rows),
        "away_corner_for_away": sum(m["away_corners"] for m in away_rows) / len(away_rows),
        "away_corner_against_away": sum(m["home_corners"] for m in away_rows) / len(away_rows),
        "league_avg_home_corners": lah, "league_avg_away_corners": laa,
        "home_games": len(home_rows), "away_games": len(away_rows),
    }
    out["available"] = True
    out["scope"] = "teams"
    out["inputs"] = {k: (round(v, 3) if isinstance(v, float) else v) for k, v in inputs.items()}
    out["prediction"] = predict_corners(**inputs)
    return out
