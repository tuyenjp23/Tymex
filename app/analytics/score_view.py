"""Tỷ số gợi ý theo từng góc nhìn: bàn thắng kỳ vọng + 3 tỷ số có xác suất cao nhất (phân phối Poisson).

Mỗi nhận xét dùng số liệu RIÊNG của nó (phong độ, ghi bàn, phòng ngự, sân bãi, đối đầu, mô hình) nên các
con số khác nhau giữa các nhận xét và giữa các trận. Đây là gợi ý theo góc nhìn đó, không phải lời hứa:
tỷ số chính xác hiếm khi vượt 15%.
"""
from __future__ import annotations

from ..prediction.poisson import score_matrix

MIN_L, MAX_L = 0.2, 4.5


def score_view(lam_home: float | None, lam_away: float | None, basis: str) -> dict | None:
    if lam_home is None or lam_away is None:
        return None
    lh = min(max(float(lam_home), MIN_L), MAX_L)
    la = min(max(float(lam_away), MIN_L), MAX_L)
    m = score_matrix(lh, la, 8)
    cells = sorted(((m[i][j], i, j) for i in range(len(m)) for j in range(len(m))), reverse=True)[:3]
    return {"lambda_home": round(lh, 2), "lambda_away": round(la, 2), "basis": basis,
            "top": [{"home": i, "away": j, "prob": round(p, 4)} for p, i, j in cells]}


def _avg(*xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None
