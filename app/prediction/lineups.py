"""Yếu tố ĐỘI HÌNH XUẤT PHÁT cho mô hình dự đoán — hàm thuần, không I/O.

Định nghĩa dùng trong toàn hệ thống (bản web ở web/live.js GIỮ ĐÚNG các hằng số và quy tắc này):

- Một "trụ cột" (regular) là cầu thủ đã đá chính ở trận đã kết thúc gần nhất của đội.
- Trụ cột bị coi là "thiếu" ở trận mới nếu anh ta không có trong đội hình xuất phát mới VÀ
  cũng không có trong danh sách dự bị mới. Nếu nguồn không cho danh sách dự bị, chỉ đối chiếu
  với đội hình xuất phát và ghi rõ giới hạn đó trong kết quả — không suy đoán lý do vắng mặt
  (chấn thương, treo giò hay xoay tua đều có thể xảy ra; module này không biết lý do).
- Điều chỉnh λ (bàn thắng kỳ vọng trước trận):
    * Thiếu một cầu thủ FWD/MID của một đội  -> λ của CHÍNH đội đó nhân 0,96 (tấn công yếu đi).
    * Thiếu một cầu thủ DEF/GK của một đội   -> λ của ĐỐI THỦ nhân 1,04 (hàng thủ dễ thủng hơn).
  Các hệ số nhân dồn theo số cầu thủ, nhưng tổng mức thay đổi của từng λ bị chặn ở ±15%
  (hệ số cuối cùng luôn nằm trong [0,85; 1,15]) để một danh sách vắng mặt dài không làm
  mô hình đi quá xa khỏi dữ kiện ghi bàn dài hạn.
- Chưa có đội hình (hoặc chưa có đội hình trận trước để đối chiếu) -> λ giữ nguyên,
  trạng thái "chưa công bố" / "thiếu dữ kiện", không bịa cầu thủ vắng mặt.

Định dạng cầu thủ chấp nhận được (cả dict lẫn chuỗi tên):
    {"name": "...", "position_group": "GK|DEF|MID|FWD"} — position_group có thể thay bằng
    "position"/"role" dạng chữ (ví dụ "Center Back", "Attacking Midfielder", "Forward",
    "Thủ môn"...) hoặc viết tắt ("CB", "AM", "ST"...); hàm tự suy nhóm vị trí.
Đội hình hiện tại (`current_roster`) chấp nhận:
    - list cầu thủ của đội hình xuất phát (không biết dự bị -> bench_known=False), hoặc
    - list lẫn lộn có cờ "starter" (True = xuất phát, False = dự bị), hoặc
    - dict {"starters"/"starting_xi"/"xi": [...], "substitutes"/"bench"/"subs": [...]}.
"""
from __future__ import annotations

import re

from ..utils import search_key

POSITION_GROUPS = ("GK", "DEF", "MID", "FWD")
ATTACK_DROP_PER_MISSING = 0.04       # thiếu 1 trụ cột FWD/MID: λ của chính đội × (1 − 0,04)
DEFENCE_LEAK_PER_MISSING = 0.04      # thiếu 1 trụ cột DEF/GK: λ của đối thủ × (1 + 0,04)
MIN_FACTOR = 0.85                    # chặn tổng điều chỉnh của mỗi λ: −15%
MAX_FACTOR = 1.15                    # chặn tổng điều chỉnh của mỗi λ: +15%

_GROUP_LABEL = {"GK": "thủ môn", "DEF": "hậu vệ", "MID": "tiền vệ", "FWD": "tiền đạo"}


def normalize_position_group(value) -> str | None:
    """Suy nhóm vị trí GK/DEF/MID/FWD từ mã hoặc tên vị trí; None nếu không suy được."""
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    upper = raw.upper()
    if upper in POSITION_GROUPS:
        return upper
    text = search_key(raw)
    if "goalkeeper" in text or "thu mon" in text:
        return "GK"
    if "midfield" in text or "tien ve" in text:
        return "MID"
    if ("defend" in text or "defence" in text or "defense" in text or "back" in text
            or "hau ve" in text):
        return "DEF"
    if ("forward" in text or "striker" in text or "winger" in text or "tien dao" in text):
        return "FWD"
    base = re.split(r"[-/\s]", upper)[0]
    if base in ("G", "GK"):
        return "GK"
    if base in ("CB", "LB", "RB", "LWB", "RWB", "DF", "DEF"):
        return "DEF"
    if base in ("DM", "CM", "LM", "RM", "AM", "MF", "MID"):
        return "MID"
    if base in ("ST", "CF", "FW", "FWD", "LW", "RW", "SS"):
        return "FWD"
    return None


def _player_name(player) -> str:
    if isinstance(player, str):
        return player.strip()
    if isinstance(player, dict):
        for key in ("name", "player_name", "displayName", "display_name", "fullName"):
            if player.get(key):
                return str(player[key]).strip()
    return ""


def _player_id(player):
    if isinstance(player, dict):
        for key in ("id", "player_id", "athlete_id"):
            if player.get(key) not in (None, ""):
                return str(player[key])
    return None


def _player_group(player) -> str | None:
    if isinstance(player, dict):
        for key in ("position_group", "positionGroup", "group"):
            group = normalize_position_group(player.get(key))
            if group:
                return group
        pos = player.get("position")
        if isinstance(pos, dict):
            group = normalize_position_group(pos.get("abbreviation") or pos.get("name"))
            if group:
                return group
        for key in ("position", "role", "position_name"):
            group = normalize_position_group(player.get(key))
            if group:
                return group
    return None


def _norm_player(player) -> dict | None:
    name = _player_name(player)
    if not name:
        return None
    return {"name": name, "id": _player_id(player), "position_group": _player_group(player),
            "key": _player_id(player) or search_key(name)}


def _roster_parts(current_roster) -> tuple[list, list, bool]:
    """Tách (đội hình xuất phát, danh sách dự bị, có_biết_dự_bị_không) từ các định dạng chấp nhận."""
    if current_roster is None:
        return [], [], False
    if isinstance(current_roster, dict):
        starters = None
        for key in ("starters", "starting_xi", "startingXi", "xi", "lineup", "players"):
            if isinstance(current_roster.get(key), list):
                starters = current_roster[key]
                break
        subs = None
        for key in ("substitutes", "bench", "subs", "reserves"):
            if isinstance(current_roster.get(key), list):
                subs = current_roster[key]
                break
        if starters is None and subs is None:
            return [], [], False
        return starters or [], subs or [], subs is not None
    if isinstance(current_roster, (list, tuple)):
        rows = list(current_roster)
        if any(isinstance(p, dict) and "starter" in p for p in rows):
            starters = [p for p in rows if p.get("starter")]
            subs = [p for p in rows if not p.get("starter")]
            return starters, subs, True
        return rows, [], False
    return [], [], False


def missing_regulars(current_roster, previous_xi) -> dict:
    """Tìm các trụ cột của trận trước (`previous_xi`) vắng mặt trong đội hình hiện tại.

    `current_roster` là đội hình của MỘT đội ở trận sắp đá (xem định dạng ở đầu module);
    `previous_xi` là danh sách cầu thủ đá chính của chính đội đó ở trận đã kết thúc gần nhất.
    Trả về {"status", "bench_known", "missing": [{"name", "position_group"}...], "notes": [...]}.
    status: "available" khi đối chiếu được; "chưa công bố" khi chưa có đội hình hiện tại;
    "thiếu dữ kiện" khi không có đội hình trận trước để biết ai là trụ cột."""
    starters_raw, subs_raw, bench_known = _roster_parts(current_roster)
    starters = [p for p in (_norm_player(x) for x in starters_raw) if p]
    subs = [p for p in (_norm_player(x) for x in subs_raw) if p]
    previous = [p for p in (_norm_player(x) for x in (previous_xi or [])) if p]
    if not starters:
        return {"status": "chưa công bố", "bench_known": bench_known, "missing": [],
                "notes": ["Đội hình xuất phát chưa công bố — chưa thể đối chiếu trụ cột vắng mặt."]}
    if not previous:
        return {"status": "thiếu dữ kiện", "bench_known": bench_known, "missing": [],
                "notes": ["Chưa có đội hình xuất phát của trận gần nhất — không biết ai là trụ cột để đối chiếu."]}
    present = {p["key"] for p in starters + subs}
    missing = []
    for p in previous:
        if p["key"] not in present:
            missing.append({"name": p["name"], "position_group": p["position_group"]})
    notes = []
    if not bench_known:
        notes.append("Nguồn chưa cho danh sách dự bị — chỉ đối chiếu với đội hình xuất phát, "
                     "cầu thủ ngồi dự bị vẫn bị tính là vắng mặt.")
    if missing:
        names = ", ".join(f"{m['name']} ({_GROUP_LABEL.get(m['position_group'], 'chưa rõ vị trí')})"
                          for m in missing)
        notes.append(f"Thiếu {len(missing)} trụ cột so với trận gần nhất: {names}.")
    else:
        notes.append("Không thiếu trụ cột nào so với đội hình xuất phát trận gần nhất.")
    return {"status": "available", "bench_known": bench_known, "missing": missing, "notes": notes}


def _missing_list(value) -> list[dict]:
    """Chấp nhận list cầu thủ hoặc nguyên dict kết quả của missing_regulars()."""
    if value is None:
        return []
    if isinstance(value, dict):
        if value.get("status") not in (None, "available"):
            return []
        value = value.get("missing") or []
    out = []
    for p in value:
        norm = _norm_player(p)
        if norm:
            out.append({"name": norm["name"], "position_group": norm["position_group"]})
    return out


def adjust_lambdas(lambda_home: float, lambda_away: float, home_missing, away_missing) -> dict:
    """Điều chỉnh cặp λ trước trận theo trụ cột vắng mặt của hai đội (quy tắc ở đầu module).

    `home_missing` / `away_missing`: list các cầu thủ thiếu của chủ nhà / đội khách
    (dict {"name", "position_group"}) hoặc nguyên kết quả của `missing_regulars`.
    Trả về λ đã điều chỉnh (làm tròn 3 chữ số), hệ số đã áp (đã chặn ±15%), danh sách thiếu
    đã chuẩn hóa và các dòng diễn giải tiếng Việt. Không có ai thiếu -> λ giữ nguyên."""
    home_missing_n = _missing_list(home_missing)
    away_missing_n = _missing_list(away_missing)
    lam_h, lam_a = max(0.0, float(lambda_home)), max(0.0, float(lambda_away))

    explanations: list[str] = []
    factor_home = 1.0
    factor_away = 1.0
    for side, missing in (("home", home_missing_n), ("away", away_missing_n)):
        team_label = "Chủ nhà" if side == "home" else "Đội khách"
        opp_label = "Đội khách" if side == "home" else "Chủ nhà"
        for p in missing:
            group = p["position_group"]
            label = _GROUP_LABEL.get(group, "chưa rõ vị trí")
            if group in ("FWD", "MID"):
                if side == "home":
                    factor_home *= 1.0 - ATTACK_DROP_PER_MISSING
                else:
                    factor_away *= 1.0 - ATTACK_DROP_PER_MISSING
                explanations.append(
                    f"{team_label} thiếu {p['name']} ({label}) so với trận gần nhất: "
                    f"λ của {team_label.lower()} giảm 4% (tấn công yếu đi).")
            elif group in ("DEF", "GK"):
                if side == "home":
                    factor_away *= 1.0 + DEFENCE_LEAK_PER_MISSING
                else:
                    factor_home *= 1.0 + DEFENCE_LEAK_PER_MISSING
                explanations.append(
                    f"{team_label} thiếu {p['name']} ({label}) so với trận gần nhất: "
                    f"λ của {opp_label.lower()} tăng 4% (hàng thủ {team_label.lower()} dễ thủng hơn).")
            else:
                explanations.append(
                    f"{team_label} thiếu {p['name']} so với trận gần nhất nhưng chưa rõ nhóm vị trí "
                    "— không điều chỉnh λ cho cầu thủ này.")

    raw_home, raw_away = factor_home, factor_away
    factor_home = min(max(factor_home, MIN_FACTOR), MAX_FACTOR)
    factor_away = min(max(factor_away, MIN_FACTOR), MAX_FACTOR)
    if factor_home != raw_home:
        explanations.append("Tổng điều chỉnh λ của chủ nhà bị chặn ở ±15% để không đi quá xa dữ kiện dài hạn.")
    if factor_away != raw_away:
        explanations.append("Tổng điều chỉnh λ của đội khách bị chặn ở ±15% để không đi quá xa dữ kiện dài hạn.")
    if not home_missing_n and not away_missing_n:
        explanations.append("Đội hình xuất phát không thiếu trụ cột nào so với trận gần nhất — giữ nguyên λ.")

    return {
        "status": "available",
        "lambda_home": round(lam_h * factor_home, 3),
        "lambda_away": round(lam_a * factor_away, 3),
        "lambda_home_before": round(lam_h, 3),
        "lambda_away_before": round(lam_a, 3),
        "factor_home": round(factor_home, 4),
        "factor_away": round(factor_away, 4),
        "change_home_pct": round((factor_home - 1.0) * 100, 1),
        "change_away_pct": round((factor_away - 1.0) * 100, 1),
        "home_missing": home_missing_n,
        "away_missing": away_missing_n,
        "explanations": explanations,
        "notes": ["Điều chỉnh chỉ dựa trên việc trụ cột có mặt hay không trong đội hình công bố; "
                  "module không biết lý do vắng mặt (ESPN không có nguồn chấn thương đáng tin cậy ở đây)."],
    }
