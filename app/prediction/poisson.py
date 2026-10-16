"""Mô hình dự đoán thống kê: sức mạnh tấn công/phòng ngự + phân phối Poisson.

Các bước:
 1. Từ các trận đã kết thúc của giải (trước giờ bóng lăn, trong `lookback_days`), tính trung bình bàn thắng
    sân nhà (lh) và sân khách (la) của giải, có trọng số giảm dần theo thời gian (nửa đời `half_life_days`).
 2. Với mỗi đội, tính tỷ lệ ghi bàn / để thủng lưới RIÊNG cho sân nhà và sân khách, co về mức trung bình giải
    (shrinkage, `shrink_k`) để tránh kết luận từ mẫu quá nhỏ.
 3. Bàn thắng kỳ vọng:
       λ_nhà  = lh × Tấn công_nhà(sân nhà) × Phòng ngự_khách(sân khách)
       λ_khách = la × Tấn công_khách(sân khách) × Phòng ngự_nhà(sân nhà)
 4. Ma trận tỷ số P(i, j) = Poisson(i; λ_nhà) × Poisson(j; λ_khách), chuẩn hóa lại sau khi cắt ở `max_goals`.
 5. Xác suất thắng/hòa/thua là tổng các ô tương ứng; làm tròn bằng phương pháp phần dư lớn nhất để tổng = 100%.

Mô hình giả định hai đội ghi bàn độc lập và KHÔNG biết chấn thương, đội hình, động lực, thời tiết, lịch dồn.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import timedelta

from ..analytics.stats import is_finished
from ..utils import parse_iso, to_iso

MODEL_VERSION = "poisson-v1"


@dataclass(frozen=True)
class ModelParams:
    lookback_days: int = 400
    half_life_days: float = 180.0
    shrink_k: float = 5.0
    min_team_games: int = 6
    min_league_games: int = 40
    max_goals: int = 10
    min_lambda: float = 0.15
    max_lambda: float = 5.0


# ---------------------------------------------------------------------- phần toán thuần
def poisson_pmf(k: int, lam: float) -> float:
    return math.exp(-lam + k * math.log(lam) - math.lgamma(k + 1)) if lam > 0 else (1.0 if k == 0 else 0.0)


def score_matrix(lam_home: float, lam_away: float, max_goals: int = 10) -> list[list[float]]:
    """Ma trận (max_goals+1)² đã chuẩn hóa để tổng = 1. Hàng = bàn của chủ nhà, cột = bàn của khách."""
    ph = [poisson_pmf(i, lam_home) for i in range(max_goals + 1)]
    pa = [poisson_pmf(j, lam_away) for j in range(max_goals + 1)]
    m = [[a * b for b in pa] for a in ph]
    total = sum(sum(r) for r in m)
    return [[v / total for v in r] for r in m]


def outcome_probabilities(matrix: list[list[float]]) -> tuple[float, float, float]:
    home = draw = away = 0.0
    for i, row in enumerate(matrix):
        for j, v in enumerate(row):
            if i > j:
                home += v
            elif i == j:
                draw += v
            else:
                away += v
    s = home + draw + away
    return home / s, draw / s, away / s


def round_to_100(probs: list[float], decimals: int = 1) -> list[float]:
    """Làm tròn các xác suất (tổng 1) thành phần trăm sao cho tổng đúng bằng 100 (phần dư lớn nhất)."""
    unit = 10 ** decimals
    total_units = 100 * unit
    raw = [p * total_units for p in probs]
    floors = [int(math.floor(x)) for x in raw]
    remaining = total_units - sum(floors)
    order = sorted(range(len(raw)), key=lambda i: raw[i] - floors[i], reverse=True)
    for i in order[:remaining]:
        floors[i] += 1
    return [f / unit for f in floors]


# ---------------------------------------------------------------------- ước lượng sức mạnh
def _weight(age_days: float, half_life: float) -> float:
    return 0.5 ** (max(age_days, 0.0) / half_life)


def _shrunk(weighted_sum: float, weight: float, prior_mean: float, k: float) -> float:
    return (weighted_sum + k * prior_mean) / (weight + k)


def _estimate(league_matches: list[dict], home_id: int, away_id: int, kickoff: str, p: ModelParams) -> dict | None:
    ko = parse_iso(kickoff)
    since = to_iso(ko - timedelta(days=p.lookback_days))
    usable = [m for m in league_matches if is_finished(m) and since <= m["utc_date"] < kickoff]
    if len(usable) < p.min_league_games:
        return {"error": "league", "league_games": len(usable)}

    def w(m):
        return _weight((ko - parse_iso(m["utc_date"])).total_seconds() / 86400, p.half_life_days)

    wsum = hw = aw = 0.0
    for m in usable:
        x = w(m)
        wsum += x
        hw += x * m["home_score"]
        aw += x * m["away_score"]
    lh, la = hw / wsum, aw / wsum
    if lh <= 0 or la <= 0:
        return {"error": "league", "league_games": len(usable)}

    def venue_totals(team_id: int, venue: str):
        n = gf = ga = 0.0
        for m in usable:
            if venue == "home" and m["home_team_id"] == team_id:
                x = w(m); n += x; gf += x * m["home_score"]; ga += x * m["away_score"]
            elif venue == "away" and m["away_team_id"] == team_id:
                x = w(m); n += x; gf += x * m["away_score"]; ga += x * m["home_score"]
        return n, gf, ga

    def games_played(team_id: int) -> int:
        return sum(1 for m in usable if team_id in (m["home_team_id"], m["away_team_id"]))

    gh, ga_ = games_played(home_id), games_played(away_id)
    if gh < p.min_team_games or ga_ < p.min_team_games:
        return {"error": "team", "home_games": gh, "away_games": ga_, "league_games": len(usable)}

    k = p.shrink_k
    hn, hgf, hga = venue_totals(home_id, "home")
    an, agf, aga = venue_totals(away_id, "away")
    home_attack = _shrunk(hgf, hn, lh, k) / lh      # bàn ghi tại sân nhà so với TB bàn sân nhà của giải
    home_defence = _shrunk(hga, hn, la, k) / la     # bàn thủng tại sân nhà so với TB bàn sân khách của giải
    away_attack = _shrunk(agf, an, la, k) / la
    away_defence = _shrunk(aga, an, lh, k) / lh
    lam_h = min(max(lh * home_attack * away_defence, p.min_lambda), p.max_lambda)
    lam_a = min(max(la * away_attack * home_defence, p.min_lambda), p.max_lambda)
    return {
        "lambda_home": lam_h, "lambda_away": lam_a, "league_avg_home": lh, "league_avg_away": la,
        "home_attack": home_attack, "home_defence": home_defence, "away_attack": away_attack, "away_defence": away_defence,
        "league_games": len(usable), "home_games": gh, "away_games": ga_,
        "home_venue_games": round(hn, 1), "away_venue_games": round(an, 1),
    }


def _factors(est: dict, home: str, away: str) -> list[dict]:
    """Các yếu tố làm tăng/giảm đánh giá, diễn giải trực tiếp từ các hệ số của mô hình."""
    def pct(x: float) -> int:
        return int(round((x - 1) * 100))

    items = [
        (est["home_attack"], f"Tấn công trên sân nhà của {home}", "bàn thắng kỳ vọng của chủ nhà", "home"),
        (est["away_defence"], f"Phòng ngự trên sân khách của {away}", "bàn thắng kỳ vọng của chủ nhà", "home"),
        (est["away_attack"], f"Tấn công trên sân khách của {away}", "bàn thắng kỳ vọng của đội khách", "away"),
        (est["home_defence"], f"Phòng ngự trên sân nhà của {home}", "bàn thắng kỳ vọng của đội khách", "away"),
    ]
    out = []
    for ratio, label, target, side in items:
        if abs(ratio - 1) < 0.08:
            continue
        up = ratio > 1
        is_defence = "Phòng ngự" in label
        # với phòng ngự: hệ số > 1 nghĩa là thủng lưới nhiều hơn mức TB (xấu cho đội đó)
        if is_defence:
            desc = f"thủng lưới {'nhiều hơn' if up else 'ít hơn'} trung bình giải {abs(pct(ratio))}%"
        else:
            desc = f"ghi bàn {'nhiều hơn' if up else 'ít hơn'} trung bình giải {abs(pct(ratio))}%"
        out.append({"text": f"{label}: {desc} → {'tăng' if up else 'giảm'} {target}.", "direction": "up" if up else "down", "side": side})
    ha = est["league_avg_home"] / est["league_avg_away"]
    out.append({"text": f"Lợi thế sân nhà của giải: chủ nhà ghi trung bình {est['league_avg_home']:.2f} bàn, "
                        f"đội khách {est['league_avg_away']:.2f} bàn (tỷ lệ {ha:.2f}).", "direction": "up", "side": "home"})
    return out


def _reliability(est: dict, p: ModelParams) -> str:
    n = min(est["home_games"], est["away_games"])
    if n < 10:
        return "thấp"
    if n < 20:
        return "trung bình"
    return "khá"


def predict(league_matches: list[dict], home_id: int, away_id: int, kickoff: str, home_name: str, away_name: str,
            params: ModelParams = ModelParams()) -> dict:
    """Dự đoán một trận. Không đủ dữ liệu => {"available": False, "reason": ...}, không bịa ra con số."""
    est = _estimate(league_matches, home_id, away_id, kickoff, params)
    if est is None or "error" in est:
        if est and est["error"] == "team":
            reason = (f"Chưa đủ dữ liệu: cần ít nhất {params.min_team_games} trận đã kết thúc của mỗi đội trong giải "
                      f"(hiện có {est['home_games']} trận của {home_name}, {est['away_games']} trận của {away_name}).")
        else:
            reason = (f"Chưa đủ dữ liệu của giải: cần ít nhất {params.min_league_games} trận đã kết thúc "
                      f"(hiện có {est['league_games'] if est else 0}). Hãy đồng bộ thêm dữ liệu hoặc mùa trước.")
        return {"available": False, "reason": reason, "model_version": MODEL_VERSION}

    lam_h, lam_a = est["lambda_home"], est["lambda_away"]
    matrix = score_matrix(lam_h, lam_a, params.max_goals)
    p_h, p_d, p_a = outcome_probabilities(matrix)
    pct = round_to_100([p_h, p_d, p_a])
    cells = sorted(((matrix[i][j], i, j) for i in range(len(matrix)) for j in range(len(matrix))), reverse=True)
    top = [{"home": i, "away": j, "prob": round(pr, 4)} for pr, i, j in cells[:5]]
    over25 = sum(v for i, r in enumerate(matrix) for j, v in enumerate(r) if i + j >= 3)
    btts = sum(v for i, r in enumerate(matrix) for j, v in enumerate(r) if i >= 1 and j >= 1)
    return {
        "available": True, "model_version": MODEL_VERSION,
        "lambda_home": round(lam_h, 3), "lambda_away": round(lam_a, 3),
        "p_home": p_h, "p_draw": p_d, "p_away": p_a,
        "percent": {"home": pct[0], "draw": pct[1], "away": pct[2]},
        "predicted_score": {"home": top[0]["home"], "away": top[0]["away"], "prob": top[0]["prob"]},
        "top_scores": top, "over_2_5": round(over25, 4), "both_teams_score": round(btts, 4),
        "matrix": [[round(v, 5) for v in row[:6]] for row in matrix[:6]],
        "factors": _factors(est, home_name, away_name),
        "quality": {"league_games": est["league_games"], "home_games": est["home_games"],
                    "away_games": est["away_games"], "reliability": _reliability(est, params),
                    "lookback_days": params.lookback_days},
        "strengths": {k: round(est[k], 3) for k in ("home_attack", "home_defence", "away_attack", "away_defence",
                                                    "league_avg_home", "league_avg_away")},
        "notes": ["Mô hình chỉ dựa trên tỷ số các trận đã kết thúc; không tự biết chấn thương, treo giò, đội hình, lịch dồn, thời tiết (tin vắng mặt nếu có chỉ hiện ở khối riêng, không đổi con số này)."],
    }
