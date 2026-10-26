"""Thu thập dữ liệu PHẠT GÓC từ ESPN (nguồn cho mô hình góc ở app/prediction/corners.py).

Vì sao cần script riêng: football-data.org (nguồn đồng bộ chính) KHÔNG có phạt góc, còn ESPN công khai
số góc (wonCorners) trong bản tóm tắt (summary) của từng trận đã đá. Script này:
  - lặp qua từng NGÀY một (endpoint scoreboard theo ngày đơn lẻ; dạng khoảng ngày bị ESPN trả 400),
  - lấy các trận ĐÃ KẾT THÚC của giải, gọi summary của từng trận để lấy wonCorners hai đội,
  - ghi data/corners/<slug>.json: tỷ lệ góc được/bị của từng đội TÁCH sân nhà/sân khách, trung bình
    giải, số trận và thời điểm tạo — đúng định dạng đầu vào mà corners.estimate_from_matches /
    predict_corners cần (sau khi đổi tên đội thành id ở bước tích hợp sau này).

CHƯA nối vào scripts/cloud_sync.py / Supabase trong đợt này — đây là nguồn dữ liệu để dành cho bước
tích hợp pipeline tiếp theo (xem README, mục Nhận định dự đoán). Lỗi ở từng trận/ngày được bỏ qua và
báo ở cuối, không làm hỏng cả lần chạy.

Cách chạy:
    python scripts/fetch_corners_espn.py --league eng.1 --days 14
    python scripts/fetch_corners_espn.py --league uefa.champions --days 30 --out data/corners
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer"
HEADERS = {"User-Agent": "Mozilla/5.0 (Tymex corners collector)"}


def _get(client: httpx.Client, url: str) -> dict | None:
    try:
        r = client.get(url)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def _team_stats(summary: dict) -> dict[str, dict]:
    """boxscore.teams[] -> {homeAway: {tên đội, wonCorners}}; thiếu wonCorners thì đội đó vắng mặt."""
    out = {}
    for t in (summary.get("boxscore") or {}).get("teams") or []:
        stats = {s.get("name"): s.get("displayValue") for s in t.get("statistics") or []}
        corners = stats.get("wonCorners")
        if corners is None:
            continue
        try:
            out[t.get("homeAway")] = {"name": (t.get("team") or {}).get("displayName") or "", "corners": int(corners)}
        except (TypeError, ValueError):
            continue
    return out


def collect(client: httpx.Client, slug: str, days: int) -> tuple[list[dict], list[str]]:
    matches: list[dict] = []
    errors: list[str] = []
    today = datetime.now(timezone.utc).date()
    for back in range(days + 1):
        day = today - timedelta(days=back)
        sb = _get(client, f"{ESPN_BASE}/{slug}/scoreboard?dates={day.strftime('%Y%m%d')}")
        if sb is None:
            errors.append(f"{day}: không tải được scoreboard")
            continue
        for ev in sb.get("events") or []:
            comp = (ev.get("competitions") or [{}])[0]
            state = ((comp.get("status") or {}).get("type") or {}).get("state")
            if state != "post":
                continue
            summary = _get(client, f"{ESPN_BASE}/{slug}/summary?event={ev.get('id')}")
            if summary is None:
                errors.append(f"{day}: trận {ev.get('id')} không tải được summary")
                continue
            sides = _team_stats(summary)
            if "home" not in sides or "away" not in sides:
                errors.append(f"{day}: trận {ev.get('id')} thiếu wonCorners")
                continue
            matches.append({
                "event_id": str(ev.get("id")), "date": day.isoformat(),
                "home_name": sides["home"]["name"], "away_name": sides["away"]["name"],
                "home_corners": sides["home"]["corners"], "away_corners": sides["away"]["corners"],
            })
    return matches, errors


def aggregate(matches: list[dict]) -> dict:
    teams: dict[str, dict] = {}

    def slot(name: str) -> dict:
        return teams.setdefault(name, {"home": {"games": 0, "for": 0, "against": 0},
                                       "away": {"games": 0, "for": 0, "against": 0}})

    for m in matches:
        h, a = slot(m["home_name"]), slot(m["away_name"])
        h["home"]["games"] += 1; h["home"]["for"] += m["home_corners"]; h["home"]["against"] += m["away_corners"]
        a["away"]["games"] += 1; a["away"]["for"] += m["away_corners"]; a["away"]["against"] += m["home_corners"]
    for t in teams.values():
        for venue in ("home", "away"):
            s = t[venue]
            s["for_per_game"] = round(s["for"] / s["games"], 3) if s["games"] else None
            s["against_per_game"] = round(s["against"] / s["games"], 3) if s["games"] else None
    n = len(matches)
    return {
        "matches": n,
        "league_avg_home_corners": round(sum(m["home_corners"] for m in matches) / n, 3) if n else None,
        "league_avg_away_corners": round(sum(m["away_corners"] for m in matches) / n, 3) if n else None,
        "teams": teams,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Thu thập tỷ lệ phạt góc từ ESPN cho mô hình góc của Tymex.")
    ap.add_argument("--league", required=True, help="slug giải trên ESPN, ví dụ eng.1, uefa.champions, jpn.1")
    ap.add_argument("--days", type=int, default=14, help="số ngày nhìn lại từ hôm nay (mặc định 14)")
    ap.add_argument("--out", default="data/corners", help="thư mục ghi file JSON (mặc định data/corners)")
    args = ap.parse_args(argv)

    with httpx.Client(headers=HEADERS, timeout=20.0) as client:
        matches, errors = collect(client, args.league, max(0, args.days))
    agg = aggregate(matches)
    payload = {
        "league": args.league, "source": "ESPN (site.api.espn.com summary: wonCorners)",
        "generated_at": datetime.now(timezone.utc).isoformat(), "days_back": args.days,
        **agg, "matches_detail": matches, "errors": errors,
    }
    out_path = Path(args.out) / f"{args.league}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Đã ghi {out_path}: {agg['matches']} trận, TB góc sân nhà {agg['league_avg_home_corners']}, "
          f"TB góc sân khách {agg['league_avg_away_corners']}, {len(payload['teams'])} đội, {len(errors)} lỗi bỏ qua.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
