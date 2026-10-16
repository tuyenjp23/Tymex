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

CO_UK_NEW_URL = "https://www.football-data.co.uk/new/{code}.csv"
ESPN_HOSTS = ("site.api.espn.com", "site.web.api.espn.com")
ESPN_URL = "https://{host}/apis/site/v2/sports/soccer/{slug}/scoreboard?dates={dates}"
ODDS_COLUMNS_NEW = [("AvgH", "AvgD", "AvgA", "Avg"), ("PH", "PD", "PA", "Pinn"), ("B365H", "B365D", "B365A", "B365")]

# (cột chủ, hòa, khách, nhãn nguồn): ưu tiên trung bình thị trường lúc đóng cửa
ODDS_COLUMNS = [
    ("AvgCH", "AvgCD", "AvgCA", "AvgC"), ("AvgH", "AvgD", "AvgA", "Avg"),
    ("PSCH", "PSCD", "PSCA", "PinnC"), ("PSH", "PSD", "PSA", "Pinn"),
    ("B365CH", "B365CD", "B365CA", "B365C"), ("B365H", "B365D", "B365A", "B365"),
    ("BbAvH", "BbAvD", "BbAvA", "BbAv"),
]


def co_uk_url(div: str, season: int) -> str:
    return CO_UK_URL.format(yy=f"{season % 100:02d}", zz=f"{(season + 1) % 100:02d}", div=div)


def openfootball_url(code: str, season: int, calendar: bool = False) -> str:
    folder = str(season) if calendar else f"{season}-{(season + 1) % 100:02d}"
    return OPENFOOTBALL_URL.format(season=folder, code=code)


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
        ft = score.get("ft") if isinstance(score, dict) else (score if isinstance(score, list) else None)
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


def co_uk_new_url(code: str) -> str:
    return CO_UK_NEW_URL.format(code=code)


def espn_url(slug: str, d1: str, d2: str | None = None, host: str = ESPN_HOSTS[0]) -> str:
    """d2 = None hoặc trùng d1: hỏi đúng một ngày (dates=YYYYMMDD); ngược lại hỏi cả khoảng (dates=YYYYMMDD-YYYYMMDD)."""
    return ESPN_URL.format(host=host, slug=slug, dates=d1 if (d2 is None or d2 == d1) else f"{d1}-{d2}")


def parse_co_uk_new_csv(text: str, *, code: str, season: int, tz: str) -> list[dict]:
    """Giải 'mở rộng' của football-data.co.uk (Nhật, Trung Quốc, Brazil, Argentina, Mỹ, Mexico...): một tệp chứa mọi mùa.

    Cột: Country, League, Season, Date, Time, Home, Away, HG, AG, Res, PH/PD/PA, AvgH/AvgD/AvgA ...
    Mùa ghi '2025' (giải theo năm) hoặc '2024/2025'.
    """
    out: list[dict] = []
    want = {str(season), f"{season}/{season + 1}", f"{season}/{(season + 1) % 100:02d}"}
    for row in csv.DictReader(io.StringIO(text)):
        row = {(k or "").strip(): (v or "").strip() for k, v in row.items() if k}
        if row.get("Season") not in want:
            continue
        home, away = row.get("Home"), row.get("Away")
        hg, ag = _int(row.get("HG")), _int(row.get("AG"))
        if not (home and away and row.get("Date")) or hg is None or ag is None:
            continue
        d = None
        for fmt in ("%d/%m/%Y", "%d/%m/%y"):
            try:
                d = datetime.strptime(row["Date"], fmt).strftime("%Y-%m-%d")
                break
            except ValueError:
                pass
        if d is None:
            continue
        odds, src = None, None
        for ch, cd, ca, label in ODDS_COLUMNS_NEW:
            trio = (_float(row.get(ch)), _float(row.get(cd)), _float(row.get(ca)))
            if all(trio):
                odds, src = trio, label
                break
        out.append({
            "external_id": f"cn:{code}:{season}:{d.replace('-', '')}:{_slug(home)}:{_slug(away)}",
            "season": season, "matchday": None, "utc_date": _to_utc(d, row.get("Time"), tz), "status": "FINISHED",
            "home": home, "away": away, "home_score": hg, "away_score": ag, "home_ht": None, "away_ht": None,
            "winner": _winner(hg, ag), "odds": odds, "odds_source": src,
        })
    return out


def parse_espn(text: str, *, slug: str, season: int, today_iso: str) -> list[dict]:
    """Bảng kết quả/lịch của ESPN (API công khai không chính thức): trận xong → FINISHED, chưa đá → SCHEDULED."""
    data = json.loads(text)
    out: list[dict] = []
    for ev in data.get("events", []) or []:
        try:
            comp = (ev.get("competitions") or [None])[0] or {}
            teams = {c.get("homeAway"): c for c in comp.get("competitors", [])}
            h, a = teams.get("home"), teams.get("away")
            if not (h and a):
                continue
            hn = (h.get("team") or {}).get("displayName") or (h.get("team") or {}).get("name")
            an = (a.get("team") or {}).get("displayName") or (a.get("team") or {}).get("name")
            raw_date = ev.get("date") or comp.get("date")
            if not (hn and an and raw_date):
                continue
            utc = to_iso(datetime.fromisoformat(raw_date.replace("Z", "+00:00")))
            st = ((comp.get("status") or ev.get("status") or {}).get("type") or {})
            state, completed = st.get("state"), bool(st.get("completed"))
            hg, ag = _int(h.get("score")), _int(a.get("score"))
            if completed and hg is not None and ag is not None and state == "post":
                status = "FINISHED"
            elif state == "pre" and utc > today_iso:
                status, hg, ag = "SCHEDULED", None, None
            else:
                continue                      # đang đá, hoãn, hủy: bỏ qua, không bịa trạng thái
            out.append({
                "external_id": f"espn:{slug}:{ev.get('id')}",
                "season": season, "matchday": None, "utc_date": utc, "status": status,
                "home": str(hn), "away": str(an), "home_score": hg, "away_score": ag, "home_ht": None, "away_ht": None,
                "winner": _winner(hg, ag) if status == "FINISHED" else None, "odds": None, "odds_source": None,
            })
        except (AttributeError, TypeError, ValueError):
            continue
    return out


# ---------------------------------------------------------------- openfootball/world (Football.TXT)
WORLD_URL = "https://raw.githubusercontent.com/openfootball/world/master/{path}/{season}_{code}.txt"
_MONTHS = {m: i for i, m in enumerate(["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}
_DATE_RE = re.compile(r"^\s+(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+([A-Z][a-z]{2})\s+(\d{1,2})(?:\s+(\d{4}))?\s*$")
_DATE_DMY_RE = re.compile(r"^\s+(\d{1,2})\.(\d{1,2})\.(?:(\d{4}))?\s*$")
_WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
_ROUND_RE = re.compile(r"^[▪»]\s*(.+?)\s*$")
_MATCH_RE = re.compile(r"^\s+(?:(\d{1,2}[:.]\d{2})\s+)?(.+?)\s+v\s+(.+?)\s*$")
_SCORE_TAIL = re.compile(r"^(.*?)\s+(\d{1,2})-(\d{1,2})(?:\s+\((\d{1,2})-(\d{1,2})\))?(?:\s+(.*))?$")


def world_url(spec_world: dict, season: int, calendar: bool) -> str:
    folder = str(season) if calendar else f"{season}-{(season + 1) % 100:02d}"
    return WORLD_URL.format(path=spec_world["path"], season=folder, code=spec_world["code"])


def _guess_year(season: int, mon: int, dd: int, wd: str | None) -> int:
    """Dòng ngày không ghi năm: chọn năm (mùa hoặc mùa+1) mà thứ trong tuần khớp; không có thứ thì theo tháng (từ tháng 7 là năm bắt đầu mùa)."""
    if wd:
        for y in (season, season + 1):
            try:
                if _WEEKDAYS[datetime(y, mon, dd).weekday()] == wd:
                    return y
            except ValueError:
                pass
    return season if mon >= 7 else season + 1


def parse_world_txt(text: str, *, code: str, season: int, tz: str, today_iso: str) -> list[dict]:
    """Đọc file Football.TXT của openfootball/world.

    Dòng ngày có thể không ghi năm ("Fri Aug 23", hoặc kiểu "08.09."): xem _guess_year.
    Trận có ghi chú kéo dài (a.e.t., pen.) bị bỏ vì tỷ số khi đó không phải kết quả 90 phút.
    """
    out: list[dict] = []
    day: str | None = None
    last_time: str | None = None
    matchday: int | None = None
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#") or line.startswith("="):
            continue
        r = _ROUND_RE.match(line)
        if r:
            n = re.search(r"(\d+)", r.group(1))
            matchday = int(n.group(1)) if n and "atchday" in r.group(1) else None
            continue
        d = _DATE_RE.match(line)
        dm = None if d else _DATE_DMY_RE.match(line)
        if d or dm:
            if d:
                wd, mon, dd, yy = d.group(1), _MONTHS.get(d.group(2)), int(d.group(3)), d.group(4)
            else:
                wd, mon, dd, yy = None, int(dm.group(2)), int(dm.group(1)), dm.group(3)
            if not mon:
                continue
            year = int(yy) if yy else _guess_year(season, mon, dd, wd)
            try:
                day = f"{year:04d}-{mon:02d}-{dd:02d}"
                datetime.strptime(day, "%Y-%m-%d")
            except ValueError:
                day = None
            last_time = None
            continue
        m = _MATCH_RE.match(line)
        if not (m and day):
            continue
        hhmm, home, rest = m.group(1), m.group(2).strip(), m.group(3).strip()
        if hhmm:
            last_time = hhmm
        else:
            hhmm = last_time                  # dòng không ghi giờ: dùng giờ của dòng trước cùng ngày
        hg = ag = hh = ha = None
        t = _SCORE_TAIL.match(rest)
        if t:
            extra = (t.group(6) or "").lower()
            if "a.e.t" in extra or "aet" in extra or "pen" in extra:
                continue
            away = t.group(1).strip()
            hg, ag = int(t.group(2)), int(t.group(3))
            if t.group(4) is not None:
                hh, ha = int(t.group(4)), int(t.group(5))
        else:
            away = rest
        if not home or not away:
            continue
        utc = _to_utc(day, hhmm.replace(".", ":") if hhmm else None, tz)
        if hg is None and utc <= today_iso:
            continue
        out.append({
            "external_id": f"ow:{code}:{season}:{day.replace('-', '')}:{_slug(home)}:{_slug(away)}",
            "season": season, "matchday": matchday, "utc_date": utc,
            "status": "FINISHED" if hg is not None else "SCHEDULED",
            "home": home, "away": away, "home_score": hg, "away_score": ag,
            "home_ht": hh, "away_ht": ha,
            "winner": _winner(hg, ag) if hg is not None else None, "odds": None, "odds_source": None,
        })
    return out
