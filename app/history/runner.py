"""Chạy nhập lịch sử cho nhiều giải/mùa từ các nguồn miễn phí. Lỗi của một nguồn không làm hỏng cả lần chạy."""
from __future__ import annotations

from datetime import date
from typing import Callable

from ..utils import to_iso, utcnow
from .importer import import_matches
from .leagues import BY_CODE, HIST_LEAGUES, season_start_year
from .sources import (
    co_uk_url, decode_bytes, openfootball_url, parse_co_uk_csv, parse_openfootball,
)
from .teams import TeamResolver

SRC_CO_UK, SRC_OF = "football-data.co.uk", "openfootball"
# Tăng số này khi cách ghép tên đội đổi: lần chạy kế tiếp sẽ xóa phần lịch sử cũ (ghép sai) và nhập lại một lần
RESOLVER_VERSION = 4


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


def run_history(repo, *, seasons: int = 5, league_codes: list[str] | None = None, sources: tuple[str, ...] = (SRC_CO_UK, SRC_OF),
                today: date | None = None, fetch: Callable[[str], bytes | None] = default_fetch,
                log: Callable[[str], None] = print) -> dict:
    today = today or utcnow().date()
    cur = season_start_year(today)
    specs = [BY_CODE[c] for c in (league_codes or [x["code"] for x in HIST_LEAGUES]) if c in BY_CODE]
    if not repo.history_import_done("resolver", "version", RESOLVER_VERSION):
        removed = repo.reset_history_matches((SRC_CO_UK, SRC_OF))
        repo.mark_history_import("resolver", "version", RESOLVER_VERSION, 0, 0)
        if removed:
            log(f"  * Đặt lại lịch sử (đổi cách ghép tên đội): xóa {removed} trận cũ, nhập lại từ đầu")
    resolver = TeamResolver(repo)
    totals = {"added": 0, "duplicates": 0, "odds": 0, "errors": []}
    now_iso = to_iso(utcnow())
    for spec in specs:
        for season in range(cur - seasons + 1, cur + 1):
            for source in sources:
                # mùa đã kết thúc và đã nhập rồi thì không tải lại; mùa hiện tại luôn tải để lấy trận mới
                if season < cur and repo.history_import_done(source, spec["code"], season):
                    continue
                try:
                    if source == SRC_CO_UK:
                        raw = fetch(co_uk_url(spec["co_uk"], season))
                        rows = parse_co_uk_csv(decode_bytes(raw), div=spec["co_uk"], season=season, tz=spec["tz"]) if raw else []
                    else:
                        raw = fetch(openfootball_url(spec["openfootball"], season))
                        rows = parse_openfootball(decode_bytes(raw), code=spec["openfootball"], season=season,
                                                  tz=spec["tz"], today_iso=now_iso) if raw else []
                except Exception as exc:   # noqa: BLE001
                    msg = f"{source} {spec['code']} {season}: {exc}"
                    totals["errors"].append(msg); log("  ! " + msg)
                    continue
                if not rows:
                    log(f"  - {source} {spec['code']} {season}: không có dữ liệu")
                    if raw is None and season < cur:
                        pass
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
