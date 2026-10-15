"""Đọc dữ liệu từ các nguồn lịch sử miễn phí thành danh sách trận chuẩn (dict).

- football-data.co.uk: CSV theo mùa, có tỷ số, tỷ số hiệp 1 và tỷ lệ cược (dùng làm mốc so sánh).
- openfootball (football.json): JSON lịch + kết quả, không cần khóa.
"""
from __future__ import annotations

import csv
import io
import json
import re
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

from ..utils import to_iso

CO_UK_URL = "https://www.football-data.co.uk/mmz4281/{yy}{zz}/{div}.csv"
OPENFOOTBALL_URL = "https://raw.githubusercontent.com/openfootball/football.json/master/{season}/{code}.json"

# (cột chủ, hòa, khách, nhãn nguồn): ưu tiên trung bình thị trường lúc đóng cửa
ODDS_COLUMNS = [
    ("AvgCH", "AvgCD", "AvgCA", "AvgC"), ("AvgH", "AvgD", "AvgA", "Avg"),
    ("PSCH", "PSCD", "PSCA", "PinnC"), ("PSH", "PSD", "PSA", "Pinn"),
    ("B365CH", "B365CD", "B365CA", "B365C"), ("B365H", "B365D", "B365A", "B365"),
    ("BbAvH", "BbAvD", "BbAvA", "BbAv"),
]


def co_uk_url(div: str, season: int) -> str:
    return CO_UK_URL.format(yy=f"{season % 100:02d}", zz=f"{(season + 1) % 100:02d}", div=div)


def openfootball_url(code: str, season: int) -> str:
    return OPENFOOTBALL_URL.format(season=f"{season}-{(season + 1) % 100:02d}", code=code)


def _winner(h: int, a: int) -> str:
    return "HOME_TEAM" if h > a else ("AWAY_TEAM" if a > h else "DRAW")


def _to_utc(day: str, hhmm: str | None, tz: str) -> str:
    """day = YYYY-MM-DD; giờ địa phương của giải → UTC. Không có giờ thì lấy 12:00 giờ địa phương."""
    h, m = 12, 0
    if hhmm and re.fullmatch(r"\d{1,2}:\d{2}", hhmm.strip()):
        h, m = (int(x) for x in hhmm.strip().split(":"))
    local = datetime.combine(datetime.strptime(day, "%Y-%m-%d").date(), time(h, m), tzinfo=ZoneInfo(tz))
    return to_iso(local.astimezone(timezone.utc))


def _int(v) -> int | None:
    try:
        return int(float(str(v).strip()))
    except (TypeError, ValueError):
        return None


def _float(v) -> float | None:
    try:
        f = float(str(v).strip())
        return f if f > 1.0 else None
    except (TypeError, ValueError):
        return None


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def decode_bytes(raw: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", errors="replace")


def parse_co_uk_csv(text: str, *, div: str, season: int, tz: str = "Europe/London") -> list[dict]:
    out: list[dict] = []
    for row in csv.DictReader(io.StringIO(text)):
        row = {(k or "").strip(): (v or "").strip() for k, v in row.items() if k}
        home, away = row.get("HomeTeam"), row.get("AwayTeam")
        hg, ag = _int(row.get("FTHG")), _int(row.get("FTAG"))
        raw_date = row.get("Date")
        if not (home and away and raw_date) or hg is None or ag is None:
            continue
        d = None
        for fmt in ("%d/%m/%Y", "%d/%m/%y"):
            try:
                d = datetime.strptime(raw_date, fmt).strftime("%Y-%m-%d")
                break
            except ValueError:
                pass
        if d is None:
            continue
        odds, src = None, None
        for ch, cd, ca, label in ODDS_COLUMNS:
            trio = (_float(row.get(ch)), _float(row.get(cd)), _float(row.get(ca)))
            if all(trio):
                odds, src = trio, label
                break
        out.append({
            "external_id": f"{div}:{season}:{d.replace('-', '')}:{_slug(home)}:{_slug(away)}",
            "season": season, "matchday": None, "utc_date": _to_utc(d, row.get("Time"), tz), "status": "FINISHED",
            "home": home, "away": away, "home_score": hg, "away_score": ag,
            "home_ht": _int(row.get("HTHG")), "away_ht": _int(row.get("HTAG")), "winner": _winner(hg, ag),
            "odds": odds, "odds_source": src,
        })
    return out


def parse_openfootball(text: str, *, code: str, season: int, tz: str, today_iso: str) -> list[dict]:
    data = json.loads(text)
    out: list[dict] = []
    for m in data.get("matches", []):
        home, away, day = m.get("team1"), m.get("team2"), m.get("date")
        if isinstance(home, dict):
            home = home.get("name")
        if isinstance(away, dict):
            away = away.get("name")
        if not (home and away and day and re.fullmatch(r"\d{4}-\d{2}-\d{2}", day)):
            continue
        score = m.get("score") or {}
        ft = score.get("ft") if isinstance(score, dict) else None
        if not ft and m.get("score1") is not None and m.get("score2") is not None:
            ft = [m.get("score1"), m.get("score2")]
        hg = ag = None
        if ft and len(ft) == 2 and _int(ft[0]) is not None and _int(ft[1]) is not None:
            hg, ag = _int(ft[0]), _int(ft[1])
        ht = score.get("ht") if isinstance(score, dict) else None
        utc = _to_utc(day, (m.get("time") or "")[:5], tz)
        if hg is None and utc <= today_iso:
            continue                       # đã qua giờ đá nhưng chưa có tỷ số: bỏ qua, không bịa trạng thái
        rnd = re.search(r"(\d+)", str(m.get("round", "")))
        out.append({
            "external_id": f"of:{code}:{season}:{day.replace('-', '')}:{_slug(str(home))}:{_slug(str(away))}",
            "season": season, "matchday": int(rnd.group(1)) if rnd else None, "utc_date": utc,
            "status": "FINISHED" if hg is not None else "SCHEDULED",
            "home": str(home), "away": str(away), "home_score": hg, "away_score": ag,
            "home_ht": _int(ht[0]) if ht and len(ht) == 2 else None, "away_ht": _int(ht[1]) if ht and len(ht) == 2 else None,
            "winner": _winner(hg, ag) if hg is not None else None, "odds": None, "odds_source": None,
        })
    return out
