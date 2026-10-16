"""Chạy nhập lịch sử cho nhiều giải/mùa từ các nguồn miễn phí. Lỗi của một nguồn không làm hỏng cả lần chạy."""
from __future__ import annotations

import time
from datetime import date, timedelta
from typing import Callable

from ..utils import to_iso, utcnow
from .importer import import_matches
from .leagues import BY_CODE, HIST_LEAGUES, current_season
from .sources import (
    co_uk_new_url, co_uk_url, decode_bytes, espn_url, openfootball_url, parse_co_uk_csv, parse_co_uk_new_csv, parse_espn,
    parse_openfootball,
)
from .teams import TeamResolver

SRC_CO_UK, SRC_OF = "football-data.co.uk", "openfootball"
SRC_CO_NEW, SRC_ESPN = "football-data.co.uk/new", "espn"
ALL_SOURCES = (SRC_CO_UK, SRC_OF, SRC_CO_NEW, SRC_ESPN)
ESPN_SEASONS = 3          # ESPN gọi theo từng tháng nên chỉ lấy 3 mùa gần nhất để nhẹ
# Tăng số này khi cách ghép tên đội đổi: lần chạy kế tiếp sẽ xóa phần lịch sử cũ (ghép sai) và nhập lại một lần
RESOLVER_VERSION = 4   # (thêm giải/nguồn mới không cần tăng số này)


def default_fetch(url: str) -> bytes | None:
    """Tải một URL. 404 → None (mùa chưa có). Lỗi mạng khác → ném lỗi để runner ghi nhận."""
    import httpx
    last = None
    for _ in range(3):
        try:
            r = httpx.get(url, timeout=30, follow_redirects=True, headers={"User-Agent": "tymex-history/1.0"})
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.content
        except Exception as exc:   # noqa: BLE001
            last = exc
    raise RuntimeError(f"{url}: {last}")


def _espn_rows(spec: dict, season: int, cur: int, today: date, now_iso: str, fetch, repo) -> list[dict]:
    """ESPN trả theo khoảng ngày: gọi từng tháng. Mùa hiện tại: lần đầu lấy cả mùa, các lần sau chỉ lấy [hôm nay-45 ngày, hôm nay+75 ngày]."""
    if spec.get("calendar"):
        start, end = date(season, 1, 1), date(season, 12, 31)
    else:
        start, end = date(season, 7, 1), date(season + 1, 6, 30)
    if season == cur:
        marker = spec["code"] + "#espn-backfill"
        if repo.history_import_done(SRC_ESPN, marker, season):
            start = max(start, today - timedelta(days=45))
        end = min(end, today + timedelta(days=75))
    rows: list[dict] = []
    seen: set[str] = set()
    d = start
    while d <= end:
        nxt = min((d.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1), end)
        raw = fetch(espn_url(spec["espn"], d.strftime("%Y%m%d"), nxt.strftime("%Y%m%d")))
        if raw:
            for r in parse_espn(decode_bytes(raw), slug=spec["espn"], season=season, today_iso=now_iso):
                if r["external_id"] not in seen:
                    seen.add(r["external_id"]); rows.append(r)
        d = nxt + timedelta(days=1)
        if fetch is default_fetch:
            time.sleep(0.1)
    if season == cur and rows:
        repo.mark_history_import(SRC_ESPN, spec["code"] + "#espn-backfill", season, len(rows), 0)
    return rows


def run_history(repo, *, seasons: int = 5, league_codes: list[str] | None = None, sources: tuple[str, ...] = ALL_SOURCES,
                today: date | None = None, fetch: Callable[[str], bytes | None] = default_fetch,
                log: Callable[[str], None] = print) -> dict:
    today = today or utcnow().date()
    specs = [BY_CODE[c] for c in (league_codes or [x["code"] for x in HIST_LEAGUES]) if c in BY_CODE]
    if not repo.history_import_done("resolver", "version", RESOLVER_VERSION):
        removed = repo.reset_history_matches(ALL_SOURCES)
        repo.mark_history_import("resolver", "version", RESOLVER_VERSION, 0, 0)
        if removed:
            log(f"  * Đặt lại lịch sử (đổi cách ghép tên đội): xóa {removed} trận cũ, nhập lại từ đầu")
    resolver = TeamResolver(repo)
    new_cache: dict = {}
    totals = {"added": 0, "duplicates": 0, "odds": 0, "errors": []}
    now_iso = to_iso(utcnow())
    for spec in specs:
        cur = current_season(spec, today)
        for season in range(cur - seasons + 1, cur + 1):
            for source in sources:
                # mùa đã kết thúc và đã nhập rồi thì không tải lại; mùa hiện tại luôn tải để lấy trận mới
                if season < cur and repo.history_import_done(source, spec["code"], season):
                    continue
                if source == SRC_CO_UK and not spec.get("co_uk"):
                    continue
                if source == SRC_OF and not spec.get("openfootball"):
                    continue
                if source == SRC_CO_NEW and not spec.get("co_uk_new"):
                    continue
                if source == SRC_ESPN and (not spec.get("espn") or season <= cur - ESPN_SEASONS):
                    continue
                try:
                    raw = True
                    if source == SRC_CO_UK:
                        raw = fetch(co_uk_url(spec["co_uk"], season))
                        rows = parse_co_uk_csv(decode_bytes(raw), div=spec["co_uk"], season=season, tz=spec["tz"]) if raw else []
                    elif source == SRC_OF:
                        raw = fetch(openfootball_url(spec["openfootball"], season, bool(spec.get("calendar"))))
                        rows = parse_openfootball(decode_bytes(raw), code=spec["openfootball"], season=season,
                                                  tz=spec["tz"], today_iso=now_iso) if raw else []
                    elif source == SRC_CO_NEW:
                        url = co_uk_new_url(spec["co_uk_new"])
                        if url not in new_cache:
                            new_cache[url] = fetch(url)
                        raw = new_cache[url]
                        rows = parse_co_uk_new_csv(decode_bytes(raw), code=spec["co_uk_new"], season=season, tz=spec["tz"]) if raw else []
                    else:
                        rows = _espn_rows(spec, season, cur, today, now_iso, fetch, repo)
                        raw = True if rows else None
                except Exception as exc:   # noqa: BLE001
                    msg = f"{source} {spec['code']} {season}: {exc}"
                    totals["errors"].append(msg); log("  ! " + msg)
                    continue
                if not rows:
                    log(f"  - {source} {spec['code']} {season}: không có dữ liệu")
                    if raw is None and season < cur:
                        repo.mark_history_import(source, spec["code"], season, 0, 0)   # mùa cũ không tồn tại: khỏi hỏi lại mỗi lần chạy
                    continue
                res = import_matches(repo, source=source, spec=spec, matches=rows, resolver=resolver)
                repo.mark_history_import(source, spec["code"], season, res["seen"], res["added"])
                for k in ("added", "duplicates", "odds"):
                    totals[k] += res[k]
                log(f"  + {source} {spec['code']} {season}: đọc {res['seen']}, thêm {res['added']}, trùng {res['duplicates']}, tỷ lệ cược {res['odds']}")
    totals["new_teams_created"] = sorted(set(resolver.created))
    totals["fuzzy_matches"] = sorted({f"{a} -> {b}" for a, b in resolver.fuzzy})
    totals["summary"] = (f"thêm {totals['added']} trận, trùng {totals['duplicates']}, tỷ lệ cược {totals['odds']}, "
                         f"đội mới {len(totals['new_teams_created'])}, lỗi {len(totals['errors'])}")
    return totals
