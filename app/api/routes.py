"""Các endpoint REST. Frontend chỉ nói chuyện với đây; không bao giờ chạm tới khóa API."""
from __future__ import annotations

import os
import re
from datetime import date, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from ..ai_analysis.writer import AIError
from ..config import set_env_value
from ..data_providers.base import ProviderError
from ..prediction.live import predict_live
from ..utils import day_range_utc, parse_iso, to_iso, utcnow

router = APIRouter(prefix="/api")

# Các giải có trong gói miễn phí của football-data.org (theo tài liệu công khai). Người dùng có thể nhập mã khác nếu gói của họ hỗ trợ.
KNOWN_LEAGUES = {
    "PL": "Premier League (Anh)", "PD": "La Liga (Tây Ban Nha)", "BL1": "Bundesliga (Đức)", "SA": "Serie A (Ý)",
    "FL1": "Ligue 1 (Pháp)", "CL": "UEFA Champions League", "DED": "Eredivisie (Hà Lan)", "PPL": "Primeira Liga (Bồ Đào Nha)",
    "ELC": "Championship (Anh)", "BSA": "Série A (Brazil)", "EC": "Euro", "WC": "FIFA World Cup",
}
LIVE = ("IN_PLAY", "PAUSED")
UPCOMING = ("SCHEDULED", "TIMED")


def err(status: int, code: str, message: str):
    raise HTTPException(status_code=status, detail={"code": code, "message": message})


def c(request: Request):
    return request.app.state.container


LOCAL_CLIENTS = {"127.0.0.1", "::1", "localhost", "testclient"}
LOCAL_HOSTNAMES = {"127.0.0.1", "localhost", "[::1]", "::1", "testserver"}


def require_local(request: Request) -> None:
    """Chỉ cho phép thao tác thay đổi/tốn tài nguyên từ chính máy chạy ứng dụng.
    Kiểm tra cả địa chỉ client lẫn tiêu đề Host (chặn tấn công DNS rebinding từ trang web bên ngoài)."""
    client = request.client.host if request.client else ""
    hostname = (request.headers.get("host") or "").rsplit(":", 1)[0] if not (request.headers.get("host") or "").startswith("[") \
        else (request.headers.get("host") or "").split("]")[0] + "]"
    if client not in LOCAL_CLIENTS or hostname.lower() not in LOCAL_HOSTNAMES:
        err(403, "local_only", "Thao tác này chỉ được phép từ chính máy đang chạy ứng dụng (điện thoại chỉ được xem).")


def get_tz(name: str | None, default: str) -> ZoneInfo:
    try:
        return ZoneInfo(name or default)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        err(400, "bad_timezone", f"Múi giờ không hợp lệ: {name!r}.")


def public_match(m: dict) -> dict:
    out = {k: m[k] for k in ("id", "league_id", "league_name", "league_code", "season", "matchday", "stage", "utc_date", "status",
                              "home_team_id", "away_team_id", "home_name", "away_name", "home_short", "away_short",
                              "home_crest", "away_crest", "home_score", "away_score", "home_ht", "away_ht", "winner")}
    out["is_test_data"] = m["provider"] == "fixture"
    return out


# ---------------------------------------------------------------------- trạng thái chung
@router.get("/status")
def status(request: Request):
    ct = c(request)
    counts = ct.repo.counts()
    leagues = ct.repo.list_leagues()
    return {
        "provider": ct.provider.name, "has_api_key": ct.settings.has_football_key or ct.provider.is_configured(),
        "ai_configured": ct.articles.available(), "default_timezone": ct.settings.default_timezone,
        "counts": counts, "has_data": counts["matches"] > 0, "last_sync": ct.repo.last_sync_overall(),
        "is_test_data": any(l["provider"] == "fixture" for l in leagues),
        "leagues": leagues, "server_time": to_iso(utcnow()), "sync": ct.sync.status(),
    }


@router.get("/leagues")
def leagues(request: Request):
    return {"leagues": c(request).repo.list_leagues()}


# ---------------------------------------------------------------------- trận đấu
@router.get("/matches")
def matches(request: Request, day: str | None = None, scope: str | None = Query(None, pattern="^(upcoming|live|finished|all)$"),
            tz: str | None = None, league_id: int | None = None, team_id: int | None = None,
            q: str | None = Query(None, max_length=60), limit: int = Query(100, ge=1, le=500)):
    ct = c(request)
    zone = get_tz(tz, ct.settings.default_timezone)
    now = utcnow()
    date_from = date_to = None
    if day:
        today = now.astimezone(zone).date()
        if day == "today":
            d = today
        elif day == "tomorrow":
            d = today + timedelta(days=1)
        elif day == "yesterday":
            d = today - timedelta(days=1)
        elif re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
            try:
                d = date.fromisoformat(day)
            except ValueError:
                err(400, "bad_date", "Ngày không hợp lệ.")
        else:
            err(400, "bad_date", "Tham số day phải là today, tomorrow, yesterday hoặc YYYY-MM-DD.")
        date_from, date_to = day_range_utc(d, zone)
    statuses, order = None, "asc"
    if scope == "upcoming":
        statuses = UPCOMING
        date_from = max(date_from, to_iso(now)) if date_from else to_iso(now)
    elif scope == "live":
        statuses = LIVE
    elif scope == "finished":
        statuses, order = ("FINISHED",), "desc"
    rows = ct.repo.query_matches(date_from=date_from, date_to=date_to, league_id=league_id, team_id=team_id,
                                 statuses=statuses, q=q, order=order, limit=limit)
    return {"matches": [public_match(m) for m in rows], "count": len(rows), "tz": zone.key,
            "range": {"from": date_from, "to": date_to}}


@router.get("/matches/{match_id}")
def match_detail(request: Request, match_id: int):
    m = c(request).repo.get_match(match_id)
    if not m:
        err(404, "not_found", "Không tìm thấy trận đấu.")
    return public_match(m)


@router.get("/matches/{match_id}/analysis")
def match_analysis(request: Request, match_id: int, form_n: int = Query(5, ge=5, le=10)):
    result = c(request).analysis.build(match_id, form_n)
    if result is None:
        err(404, "not_found", "Không tìm thấy trận đấu.")
    result["match"] = public_match(result["match"])
    return result


@router.get("/matches/{match_id}/article")
def get_article(request: Request, match_id: int):
    ct = c(request)
    if not ct.repo.get_match(match_id):
        err(404, "not_found", "Không tìm thấy trận đấu.")
    return {"article": ct.articles.latest(match_id), "ai_configured": ct.articles.available()}


@router.post("/matches/{match_id}/article")
def create_article(request: Request, match_id: int, force: bool = False):
    require_local(request)   # mỗi lần bấm tốn phí API AI
    try:
        return {"article": c(request).articles.generate(match_id, force)}
    except AIError as exc:
        err(400 if "Chưa cấu hình" in str(exc) else 502, "ai_error", str(exc))
    except LookupError as exc:
        err(404, "not_found", str(exc))


# ---------------------------------------------------------------------- bảng xếp hạng, đội bóng
@router.get("/standings")
def standings(request: Request, league_id: int):
    ct = c(request)
    league = ct.repo.get_league(league_id)
    if not league:
        err(404, "not_found", "Không tìm thấy giải đấu.")
    rows = ct.repo.get_standings(league_id)
    groups: dict[str, list] = {}
    for r in rows:
        groups.setdefault(r["group_name"], []).append(r)
    return {"league": league, "groups": [{"name": k, "rows": v} for k, v in groups.items()],
            "updated_at": rows[0]["updated_at"] if rows else None}


@router.get("/teams")
def teams(request: Request, league_id: int | None = None, q: str | None = Query(None, max_length=60)):
    return {"teams": c(request).repo.list_teams(league_id, q)}


# ---------------------------------------------------------------------- dự đoán
@router.get("/predictions")
def predictions(request: Request, kind: str = Query("live", pattern="^(live|backtest)$"), league_id: int | None = None,
                limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0)):
    rows = c(request).repo.list_predictions(kind=kind, league_id=league_id, limit=limit, offset=offset)
    return {"predictions": rows, "count": len(rows)}


@router.get("/predictions/summary")
def prediction_summary(request: Request, kind: str = Query("live", pattern="^(live|backtest)$")):
    return c(request).predictions.summary(kind)


# ---------------------------------------------------------------------- dự đoán vô địch
_OUTRIGHTS_MARKET_CACHE: dict = {"fetched_at": None, "by_code": None}


@router.get("/outrights")
def outrights(request: Request, n_sims: int = Query(1500, ge=100, le=10000)):
    """Dự đoán đội vô địch từng giải: kèo outright của thị trường (The Odds API, chỉ khi máy này có
    THE_ODDS_API_KEY; làm mới tối đa mỗi 36 giờ nhờ bộ nhớ đệm trong tiến trình) đặt cạnh mô phỏng
    Monte Carlo phần còn lại của mùa giải bằng chính mô hình Poisson/Dixon-Coles (tính tại chỗ).
    Cùng dạng dữ liệu với kv 'outrights' của bản đám mây. Không có khóa/thiếu dữ liệu => từng phần
    trả available=False kèm lý do, không bịa số."""
    from ..prediction import outrights as _o   # noqa: PLC0415
    now = utcnow()
    market_by_code, market_fetched_at = _OUTRIGHTS_MARKET_CACHE["by_code"], _OUTRIGHTS_MARKET_CACHE["fetched_at"]
    key = (os.environ.get("THE_ODDS_API_KEY") or "").strip()
    if key and _o.market_fetch_due({"fetched_at": market_fetched_at} if market_fetched_at else None, now):
        try:
            from ..odds.the_odds_api import TheOddsApi   # noqa: PLC0415
            api = TheOddsApi(key, max_calls_per_run=10, min_remaining=_o.MARKET_MIN_REMAINING)
            fresh, _meta = _o.fetch_market_outrights(api, log=lambda _msg: None)
            if any(m.get("available") for m in fresh.values()):
                market_by_code, market_fetched_at = fresh, to_iso(now)
                _OUTRIGHTS_MARKET_CACHE.update({"by_code": fresh, "fetched_at": market_fetched_at})
        except Exception:   # noqa: BLE001 - phần thị trường lỗi thì phần mô hình vẫn phải trả được
            pass
    if not key:
        market_by_code = {code: {"available": False, "source": _o.MARKET_SOURCE,
                                 "reason": "Máy này chưa cấu hình THE_ODDS_API_KEY nên chưa có tỉ lệ thị trường."}
                          for code in _o.MARKET_LEAGUE_CODES}
    return _o.build_outrights_payload(c(request).repo, market_by_code=market_by_code or {},
                                       market_fetched_at=market_fetched_at, now=now,
                                       n_sims=n_sims, log=lambda _msg: None)


def _estimate_match_minute(match: dict) -> float:
    """ƯỚC TÍNH phút thi đấu từ giờ bóng lăn, vì nguồn football-data.org không cung cấp phút thi đấu.

    Lấy số phút đồng hồ đã trôi qua kể từ giờ bóng lăn, trừ 15 phút nghỉ giữa hiệp khi đã qua phút 60
    của đồng hồ (hiệp 1 ~45+ phút + nghỉ 15 phút), kẹp trong [0, 95]. Trận đang PAUSED coi như phút 45.
    Đây là ước tính thô — giao diện phải ghi rõ điều này; truyền ?minute= để dùng phút chính xác."""
    if match["status"] == "PAUSED":
        return 45.0
    elapsed = (utcnow() - parse_iso(match["utc_date"])).total_seconds() / 60.0
    minute = elapsed - 15.0 if elapsed > 60 else elapsed
    return max(0.0, min(minute, 95.0))


@router.get("/matches/{match_id}/live-prediction")
def match_live_prediction(request: Request, match_id: int, minute: float | None = Query(None, ge=0, le=130)):
    """Dự đoán trực tiếp (kiểu FotMob) cho trận đang đá, từ λ của dự đoán TRƯỚC TRẬN đã lưu.

    Không có dự đoán đã lưu, trận không đang đá, hoặc chưa có tỷ số trực tiếp => {"available": False, "reason": ...},
    tuyệt đối không tự bịa λ hay tỷ số."""
    ct = c(request)
    m = ct.repo.get_match(match_id)
    if not m:
        err(404, "not_found", "Không tìm thấy trận đấu.")
    base = {"match": public_match(m)}
    if m["status"] not in LIVE:
        return {**base, "available": False,
                "reason": f"Trận không đang diễn ra (trạng thái: {m['status']}). Dự đoán trực tiếp chỉ tính khi trận đang đá."}
    if m["home_score"] is None or m["away_score"] is None:
        return {**base, "available": False,
                "reason": "Nguồn dữ liệu hiện tại chưa cung cấp tỷ số trực tiếp của trận này."}
    pred = ct.repo.latest_prediction(match_id, "live", before=m["utc_date"])
    if not pred:
        return {**base, "available": False,
                "reason": "Chưa có dự đoán trước trận đã lưu cho trận này nên không có λ trước trận để tính dự đoán trực tiếp. Hệ thống không tự bịa λ."}
    estimated = minute is None
    used_minute = _estimate_match_minute(m) if estimated else float(minute)
    out = predict_live(pred["lambda_home"], pred["lambda_away"], used_minute, m["home_score"], m["away_score"])
    out.update(base)
    out["minute_estimated"] = estimated
    out["pre_match_prediction"] = {"id": pred["id"], "created_at": pred["created_at"],
                                   "lambda_home": pred["lambda_home"], "lambda_away": pred["lambda_away"],
                                   "model_version": pred["model_version"]}
    if estimated:
        out["notes"] = out["notes"] + ["Phút thi đấu là ƯỚC TÍNH từ giờ bóng lăn (đã trừ ~15 phút nghỉ giữa hiệp) "
                                        "vì nguồn dữ liệu không cung cấp phút thi đấu; truyền tham số ?minute= để dùng phút chính xác."]
    out["notes"] = out["notes"] + ["Nguồn dữ liệu hiện tại không cung cấp thẻ đỏ trực tiếp nên mô hình tính với 0 thẻ đỏ."]
    return out


class BacktestBody(BaseModel):
    league_id: int | None = None
    limit: int = Field(100, ge=1, le=500)


@router.post("/predictions/backtest")
def backtest(request: Request, body: BacktestBody):
    require_local(request)
    return c(request).predictions.backtest(body.league_id, body.limit)


# ---------------------------------------------------------------------- đồng bộ
class SyncBody(BaseModel):
    force: bool = False


@router.post("/sync", status_code=202)
def start_sync(request: Request, body: SyncBody | None = None):
    require_local(request)   # đồng bộ dùng hạn mức gọi API của bạn
    ct = c(request)
    if not ct.provider.is_configured():
        err(400, "not_configured", "Chưa cấu hình FOOTBALL_DATA_API_KEY. Hãy nhập khóa ở trang Cài đặt.")
    if not ct.sync.start_background(force=bool(body and body.force)):
        err(409, "already_running", "Đang có một lần đồng bộ khác chạy.")
    return {"started": True}


@router.get("/sync/status")
def sync_status(request: Request):
    return c(request).sync.status()


@router.get("/sync/logs")
def sync_logs(request: Request, limit: int = Query(30, ge=1, le=200)):
    return {"logs": c(request).repo.list_sync_logs(limit)}


# ---------------------------------------------------------------------- cài đặt
class KeyBody(BaseModel):
    api_key: str = Field(min_length=16, max_length=64)


class LeaguesBody(BaseModel):
    codes: list[str] = Field(min_length=1, max_length=20)


def _mask(key: str) -> str:
    return ("•" * 8 + key[-4:]) if key else ""


@router.get("/settings")
def get_settings(request: Request):
    ct = c(request)
    return {"provider": ct.provider.name, "has_api_key": ct.provider.is_configured(),
            "api_key_hint": _mask(ct.settings.football_data_api_key), "league_codes": ct.settings.league_codes,
            "known_leagues": KNOWN_LEAGUES, "default_timezone": ct.settings.default_timezone,
            "ai_configured": ct.articles.available(), "ai_model": ct.settings.ai_model,
            "env_file": str(ct.settings.env_path), "env_file_exists": ct.settings.env_path.exists(),
            "rate_limit_per_minute": ct.settings.rate_limit_per_minute,
            "min_sync_interval_minutes": ct.settings.min_sync_interval_minutes,
            "auto_sync_minutes": ct.settings.auto_sync_minutes}


@router.post("/settings/football-key")
def set_key(request: Request, body: KeyBody):
    require_local(request)
    key = body.api_key.strip()
    if not re.fullmatch(r"[A-Za-z0-9]{16,64}", key):
        err(400, "bad_key", "Khóa API chỉ gồm chữ và số (16–64 ký tự).")
    ct = c(request)
    set_env_value(ct.settings.env_path, "FOOTBALL_DATA_API_KEY", key)
    os.environ["FOOTBALL_DATA_API_KEY"] = key
    ct.settings.football_data_api_key = key
    ct.provider.set_api_key(key)
    return {"saved": True, "api_key_hint": _mask(key)}


@router.post("/settings/test-key")
def test_key(request: Request):
    require_local(request)
    ct = c(request)
    if not ct.provider.is_configured():
        err(400, "not_configured", "Chưa có khóa API.")
    try:
        ct.provider.get_standings(ct.settings.league_codes[0])   # 1 lần gọi nhỏ để kiểm tra khóa
    except ProviderError as exc:
        err(502, exc.code, str(exc))
    return {"ok": True, "message": "Khóa API hoạt động."}


@router.post("/settings/leagues")
def set_leagues(request: Request, body: LeaguesBody):
    require_local(request)
    codes = []
    for raw in body.codes:
        code = raw.strip().upper()
        if not re.fullmatch(r"[A-Z0-9]{2,5}", code):
            err(400, "bad_league", f"Mã giải không hợp lệ: {raw!r}.")
        if code not in codes:
            codes.append(code)
    ct = c(request)
    set_env_value(ct.settings.env_path, "LEAGUES", ",".join(codes))
    ct.settings.league_codes = codes
    return {"saved": True, "league_codes": codes}
