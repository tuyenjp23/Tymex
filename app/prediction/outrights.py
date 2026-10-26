"""Dự đoán ĐỘI VÔ ĐỊCH của từng giải từ hai nguồn độc lập, đặt cạnh nhau để đối chiếu:

 1. THỊ TRƯỜNG: kèo vô địch (outright) của The Odds API — tỉ lệ thập phân của nhiều nhà cái quốc tế,
    lấy TRUNG VỊ theo từng đội rồi quy đổi thành xác suất và chuẩn hóa (tổng = 1, đã loại phần lãi
    nhà cái). Đây là dữ liệu thị trường thật; KHÔNG phải của riêng nhà cái nào và không bao giờ được
    gán nhãn là của nhà cái khác.
 2. MÔ HÌNH TYMEX: mô phỏng Monte Carlo phần còn lại của mùa giải — mỗi trận chưa đá được rút tỉ số
    từ chính ma trận Poisson/Dixon-Coles mà mô hình dùng để dự đoán từng trận, cộng vào bảng điểm
    hiện tại; đội đứng đầu sau khi đá hết lịch là nhà vô địch của lần mô phỏng đó.

Không đủ dữ liệu ở phía nào thì phía đó trả {"available": False, "reason"/"note": ...} — không bịa số.
"""
from __future__ import annotations

import bisect
import random
import statistics
from datetime import timedelta

from ..analytics.stats import is_finished
from ..utils import parse_iso, to_iso, utcnow
from .poisson import ModelParams, predict, score_matrix

MARKET_SOURCE = "The Odds API"
MARKET_MAX_AGE_HOURS = 36        # kèo vô địch biến động chậm: chỉ lấy mới khi dữ liệu cũ hơn ngưỡng này
MARKET_MIN_REMAINING = 60        # dừng lấy kèo khi hạn mức The Odds API còn dưới mức này (giữ cho kèo trận)
TOP_N = 10                       # số đội tối đa đưa vào payload mỗi phía

# Các giải mô phỏng được (giải VĐQG đá vòng tròn, có bảng điểm) + giải cúp chỉ có kèo thị trường.
LEAGUE_NAMES = {
    "PL": "Premier League (Anh)", "PD": "La Liga (Tây Ban Nha)", "BL1": "Bundesliga (Đức)",
    "SA": "Serie A (Ý)", "FL1": "Ligue 1 (Pháp)", "UCL": "UEFA Champions League",
}
MODEL_LEAGUE_CODES = ["PL", "PD", "BL1", "SA", "FL1"]
MARKET_LEAGUE_CODES = MODEL_LEAGUE_CODES + ["UCL"]
CUP_NOTE = "Giải cúp — chỉ có tỉ lệ thị trường."

# Ánh xạ giải theo TIÊU ĐỀ môn của The Odds API (khóa môn outright không được tài liệu hóa ổn định,
# nên nhận diện bằng từ khóa trong tiêu đề; bảng này cố ý nhỏ và rõ ràng). "exclude" lọc các giải
# hạng dưới/trùng tiền tố: "German Bundesliga 2" chứa "Bundesliga" nhưng là giải hạng 2.
_SPORT_TITLE_RULES = [
    ("Premier League", "PL", ()),
    ("La Liga", "PD", ()),
    ("Bundesliga", "BL1", ("2",)),
    ("Serie A", "SA", ()),
    ("Ligue 1", "FL1", ()),
    ("Champions League", "UCL", ("Women",)),
]


def map_sport_to_league(sport) -> str | None:
    """The Odds API outright sport (dict có 'title' hoặc chuỗi tiêu đề) -> mã giải Tymex; None nếu không khớp."""
    title = sport.get("title") if isinstance(sport, dict) else str(sport or "")
    if not title:
        return None
    for keyword, code, excludes in _SPORT_TITLE_RULES:
        if keyword in title and not any(x in title for x in excludes):
            return code
    return None


# ---------------------------------------------------------------------- thị trường (hàm thuần)
def consensus_outrights(events: list[dict]) -> dict:
    """Gộp kèo outright từ mọi sự kiện/nhà cái: mỗi đội lấy TRUNG VỊ tỉ lệ thập phân, quy đổi 1/tỉ lệ
    rồi chuẩn hóa để tổng xác suất = 1 (loại phần lãi nhà cái). Bỏ kết quả không có giá hợp lệ > 1.0."""
    prices: dict[str, list[float]] = {}
    bookmakers: set[str] = set()
    for ev in events or []:
        for bk in ev.get("bookmakers") or []:
            offered = False
            for mk in bk.get("markets") or []:
                if mk.get("key") != "outrights":
                    continue
                for o in mk.get("outcomes") or []:
                    name, price = o.get("name"), o.get("price")
                    try:
                        price = float(price)
                    except (TypeError, ValueError):
                        continue
                    if not name or price <= 1.0:
                        continue
                    prices.setdefault(str(name), []).append(price)
                    offered = True
            if offered:
                bookmakers.add(str(bk.get("key") or bk.get("title") or len(bookmakers)))
    outcomes = []
    for team, ps in prices.items():
        median = statistics.median(ps)
        outcomes.append({"team": team, "odds": round(median, 3), "raw": 1.0 / median})
    total = sum(o["raw"] for o in outcomes)
    if not outcomes or total <= 0:
        return {"available": False, "bookmakers": len(bookmakers), "outcomes": [],
                "reason": "Không có nhà cái nào mở kèo vô địch cho giải này."}
    for o in outcomes:
        o["prob"] = round(o.pop("raw") / total, 4)
    outcomes.sort(key=lambda o: (-o["prob"], o["team"]))
    return {"available": True, "bookmakers": len(bookmakers), "outcomes": outcomes}


def align_market_names(outcomes: list[dict], db_team_names: list[str]) -> list[dict]:
    """Ghép tên đội của thị trường về tên trong CSDL khi KHỚP CHẮC CHẮN (chuẩn hóa bỏ tiền/hậu tố kiểu
    FC/CF... như normalize_export_team_name của khâu xuất Supabase, hoặc biến thể rút gọn/đầy đủ duy nhất).
    Không khớp chắc chắn thì giữ nguyên tên thị trường — không đoán."""
    from ..cloud.export import normalize_export_team_name   # noqa: PLC0415 (tránh vòng import lúc nạp module)

    by_norm: dict[str, str] = {}
    for name in db_team_names or []:
        by_norm.setdefault(normalize_export_team_name(name), name)
    variant_tokens = {"b", "ii", "2", "u19", "u20", "u21", "u23", "women", "woman", "nu", "reserves", "reserve"}

    def tokens(norm: str) -> set[str]:
        return set(norm.split())

    out = []
    for o in outcomes or []:
        team = o.get("team") or ""
        norm = normalize_export_team_name(team)
        aligned = by_norm.get(norm)
        if aligned is None and norm:
            cands = []
            mine = tokens(norm)
            for db_norm, db_name in by_norm.items():
                theirs = tokens(db_norm)
                small, big = (mine, theirs) if len(mine) <= len(theirs) else (theirs, mine)
                if small and small <= big and not any(t in variant_tokens for t in big - small):
                    cands.append(db_name)
            if len(cands) == 1:
                aligned = cands[0]
        out.append({**o, "team": aligned or team})
    return out


# ---------------------------------------------------------------------- mô phỏng Monte Carlo
def fixture_cdf(lam_home: float, lam_away: float, params: ModelParams = ModelParams()) -> list[float]:
    """CDF phẳng (hàng = bàn chủ nhà, cột = bàn khách, 0..max_goals) của ma trận tỉ số Dixon-Coles."""
    matrix = score_matrix(lam_home, lam_away, params.max_goals, rho=params.dixon_coles_rho)
    cdf, acc = [], 0.0
    for row in matrix:
        for v in row:
            acc += v
            cdf.append(acc)
    if cdf:
        cdf[-1] = 1.0
    return cdf


def _rank_key(points: int, gf: int, ga: int):
    """Khóa xếp hạng vô địch: điểm, hiệu số, bàn thắng (hòa cả ba thì phân định bằng tên đội)."""
    return (points, gf - ga, gf)


def simulate_title_race(current_table: dict, fixtures: list[dict], n_sims: int = 3000, seed: int = 20261026) -> dict:
    """Mô phỏng phần còn lại của mùa giải.

    current_table: {tên đội: {"points": int, "gf": int, "ga": int}} tính từ các trận ĐÃ kết thúc.
    fixtures: [{"home": tên, "away": tên, "cdf": CDF phẳng từ fixture_cdf}] — CDF tính MỘT lần ngoài vòng lặp.
    Mỗi lần mô phỏng rút tỉ số bằng một lần bisect trên CDF của trận, cộng điểm/hiệu số vào bảng sao chép;
    nhà vô địch là đội đầu bảng theo (điểm, hiệu số, bàn thắng, rồi tên đội cho tất định).
    Cùng seed => cùng kết quả."""
    teams = sorted(current_table or {})
    if not teams:
        return {"available": False, "reason": "Chưa có bảng điểm hiện tại (chưa có trận nào đã kết thúc)."}
    index = {t: i for i, t in enumerate(teams)}
    base_pts = [int(current_table[t].get("points") or 0) for t in teams]
    base_gf = [int(current_table[t].get("gf") or 0) for t in teams]
    base_ga = [int(current_table[t].get("ga") or 0) for t in teams]
    size = (ModelParams().max_goals + 1)
    games = []
    for f in fixtures or []:
        for t in (f.get("home"), f.get("away")):
            if t and t not in index:
                index[t] = len(teams)
                teams.append(t)
                base_pts.append(0)
                base_gf.append(0)
                base_ga.append(0)
        cdf = f.get("cdf") or []
        if f.get("home") in index and f.get("away") in index and len(cdf) == size * size:
            games.append((index[f["home"]], index[f["away"]], cdf))
    if not games:
        # Không còn trận nào: nhà vô địch là đội đang dẫn đầu bảng hiện tại, xác suất 1.0.
        best = max(_rank_key(base_pts[i], base_gf[i], base_ga[i]) for i in range(len(teams)))
        champ = min((i for i in range(len(teams))
                     if _rank_key(base_pts[i], base_gf[i], base_ga[i]) == best), key=lambda i: teams[i])
        return {"available": True, "n_sims": 0,
                "outcomes": [{"team": t, "prob": 1.0 if i == champ else 0.0} for i, t in enumerate(teams)]}
    rng = random.Random(seed)
    titles = [0] * len(teams)
    for _ in range(max(1, int(n_sims))):
        pts, gf, ga = list(base_pts), list(base_gf), list(base_ga)
        for h, a, cdf in games:
            cell = bisect.bisect_left(cdf, rng.random())
            if cell >= size * size:
                cell = size * size - 1
            hg, ag = divmod(cell, size)
            gf[h] += hg
            ga[h] += ag
            gf[a] += ag
            ga[a] += hg
            if hg > ag:
                pts[h] += 3
            elif hg < ag:
                pts[a] += 3
            else:
                pts[h] += 1
                pts[a] += 1
        best_i, best_key = 0, None
        for i in range(len(teams)):
            key = (pts[i], gf[i] - ga[i], gf[i])
            if best_key is None or key > best_key or (key == best_key and teams[i] < teams[best_i]):
                best_i, best_key = i, key
        titles[best_i] += 1
    n = max(1, int(n_sims))
    outcomes = [{"team": t, "prob": round(titles[i] / n, 4)} for i, t in enumerate(teams)]
    outcomes.sort(key=lambda o: (-o["prob"], o["team"]))
    return {"available": True, "n_sims": n, "outcomes": outcomes}


def league_table(matches: list[dict]) -> dict:
    """Bảng điểm {tên đội: {points, gf, ga, played}} từ các trận ĐÃ KẾT THÚC (kèm mọi đội từng ra sân)."""
    table: dict[str, dict] = {}
    for m in matches or []:
        for name in (m.get("home_name"), m.get("away_name")):
            if name:
                table.setdefault(name, {"points": 0, "gf": 0, "ga": 0, "played": 0})
        if not is_finished(m):
            continue
        h, a = table[m["home_name"]], table[m["away_name"]]
        hs, as_ = int(m["home_score"]), int(m["away_score"])
        h["gf"] += hs
        h["ga"] += as_
        a["gf"] += as_
        a["ga"] += hs
        h["played"] += 1
        a["played"] += 1
        if hs > as_:
            h["points"] += 3
        elif hs < as_:
            a["points"] += 3
        else:
            h["points"] += 1
            a["points"] += 1
    return table


def default_sims(n_fixtures: int) -> int:
    """Số lần mô phỏng mặc định: 3000 khi lịch còn lại <= 300 trận, 2000 nếu nhiều hơn (giữ thời gian chạy gọn)."""
    return 3000 if n_fixtures <= 300 else 2000


def build_league_title_model(repo, code: str, *, params: ModelParams = ModelParams(),
                             n_sims: int | None = None, seed: int = 20261026) -> dict:
    """Dựng phần MÔ HÌNH cho một giải VĐQG từ CSDL: bảng hiện tại của mùa đang đá + λ từng trận còn lại
    lấy đúng theo đường dự đoán của mô hình (poisson.predict, chỉ dùng dữ liệu trước giờ bóng lăn từng trận)."""
    from ..history.leagues import MAIN_PROVIDER   # noqa: PLC0415
    if code not in MODEL_LEAGUE_CODES:
        return {"available": False, "note": CUP_NOTE}
    league = repo.get_league_by_code(MAIN_PROVIDER, code)
    if not league:
        return {"available": False, "reason": f"Chưa có giải {code} trong CSDL."}
    finished = repo.finished_matches(league_id=league["id"])
    upcoming = repo.query_matches(league_id=league["id"], statuses=("SCHEDULED", "TIMED"), limit=1000)
    if upcoming:
        season = upcoming[0].get("season")
    elif finished:
        season = finished[0].get("season")
    else:
        return {"available": False, "reason": "Chưa có dữ liệu trận đấu của giải này."}
    season_finished = [m for m in finished if m.get("season") == season]
    season_fixtures = [m for m in upcoming if m.get("season") == season]
    table = league_table(season_finished)
    if not table:
        return {"available": False, "reason": "Mùa giải hiện tại chưa có trận nào đã kết thúc."}
    priced, skipped = [], 0
    for m in season_fixtures:
        out = predict(finished, m["home_team_id"], m["away_team_id"], m["utc_date"],
                      m["home_name"], m["away_name"], params)
        if not out.get("available"):
            skipped += 1
            continue
        priced.append({"home": m["home_name"], "away": m["away_name"],
                       "cdf": fixture_cdf(out["lambda_home"], out["lambda_away"], params)})
    if season_fixtures and not priced:
        return {"available": False,
                "reason": "Chưa đủ dữ liệu để định giá các trận còn lại của mùa giải (mô hình cần thêm lịch sử trận)."}
    sims = n_sims if n_sims is not None else default_sims(len(priced))
    result = simulate_title_race(table, priced, n_sims=sims, seed=seed)
    if not result.get("available"):
        return result
    result["fixtures_remaining"] = len(priced)
    notes = []
    if skipped:
        notes.append(f"Bỏ qua {skipped} trận còn lại chưa đủ dữ liệu để định giá.")
    if not priced:
        notes.append("Mùa giải đã đá hết lịch — kết quả theo bảng điểm cuối cùng hiện có.")
    if notes:
        result["note"] = " ".join(notes)
    return result


# ---------------------------------------------------------------------- lấy kèo thị trường (điều phối)
def market_fetch_due(previous_payload: dict | None, now=None, max_age_hours: float = MARKET_MAX_AGE_HOURS) -> bool:
    """True khi cần lấy kèo mới: chưa từng có payload, payload không có mốc lấy kèo, hoặc đã cũ hơn ngưỡng."""
    if not previous_payload:
        return True
    fetched = previous_payload.get("fetched_at")
    if not fetched:
        return True
    try:
        age = (now or utcnow()) - parse_iso(fetched)
    except (TypeError, ValueError):
        return True
    return age >= timedelta(hours=max_age_hours)


def market_from_payload(payload: dict | None) -> dict:
    """Trích phần thị trường theo mã giải từ payload đã lưu (để dùng lại khi chưa tới hạn lấy mới)."""
    out = {}
    for lg in (payload or {}).get("leagues") or []:
        market = lg.get("market") or {}
        if lg.get("code") and market.get("available"):
            out[lg["code"]] = market
    return out


def fetch_market_outrights(api, *, log=print, min_remaining: int = MARKET_MIN_REMAINING) -> tuple[dict, dict]:
    """Lấy kèo vô địch cho các giải đã ánh xạ. Trả (market theo mã giải, meta {calls, remaining}).

    Tôn trọng hạn mức: sau mỗi lần gọi, nếu số credit còn lại < min_remaining thì dừng hẳn (kèo vô địch
    không được ăn vào hạn mức dành cho kèo từng trận). Lỗi từng giải được ghi nhận riêng, không làm hỏng cả bước."""
    sports = api.list_outright_sports()
    by_code: dict[str, dict] = {}
    for sport in sports:
        code = map_sport_to_league(sport)
        if code is None:
            log(f"Kèo vô địch: bỏ qua môn outright không ánh xạ được: {sport.get('title') if isinstance(sport, dict) else sport}")
            continue
        if code in by_code:
            log(f"Kèo vô địch: môn {sport.get('key')} trùng mã giải {code} với môn đã chọn, bỏ qua.")
            continue
        by_code[code] = sport
    markets: dict[str, dict] = {}
    meta = {"calls": 0, "remaining": None}
    for code in MARKET_LEAGUE_CODES:
        sport = by_code.get(code)
        if sport is None:
            markets[code] = {"available": False, "source": MARKET_SOURCE,
                             "reason": "The Odds API hiện không mở môn kèo vô địch cho giải này."}
            continue
        try:
            events, info = api.fetch_outrights(sport.get("key"))
        except Exception as exc:   # noqa: BLE001 - thông báo của OddsApiError đã được làm sạch (không chứa khóa)
            markets[code] = {"available": False, "source": MARKET_SOURCE, "reason": str(exc)}
            if getattr(exc, "code", "") in ("auth", "quota"):
                log(f"Kèo vô địch: dừng lấy kèo ({exc})")
                break
            continue
        meta["calls"] += 1
        if info.get("remaining") is not None:
            meta["remaining"] = info["remaining"]
        cons = consensus_outrights(events)
        if cons["available"]:
            markets[code] = {"available": True, "source": MARKET_SOURCE,
                             "bookmakers": cons["bookmakers"], "outcomes": cons["outcomes"]}
        else:
            markets[code] = {"available": False, "source": MARKET_SOURCE, "reason": cons["reason"]}
        if meta["remaining"] is not None and meta["remaining"] < min_remaining:
            log(f"Kèo vô địch: dừng lấy kèo để giữ hạn mức The Odds API (còn {meta['remaining']} < {min_remaining}).")
            break
    return markets, meta


# ---------------------------------------------------------------------- lắp payload hoàn chỉnh
def build_outrights_payload(repo, *, market_by_code: dict | None = None, market_fetched_at: str | None = None,
                            now=None, codes: list[str] | None = None, n_sims: int | None = None,
                            params: ModelParams = ModelParams(), log=print) -> dict:
    """Payload kv 'outrights': mỗi giải gồm phần thị trường (nếu có) + phần mô hình (5 giải VĐQG).

    market_by_code: {mã giải: khối market đã chuẩn hóa} — tên đội thị trường được ghép về tên CSDL khi
    khớp chắc chắn. Giải nào lỗi riêng thì ghi available False, không làm hỏng payload của các giải khác."""
    now = now or utcnow()
    market_by_code = market_by_code or {}
    leagues = []
    for code in (codes or MARKET_LEAGUE_CODES):
        name = LEAGUE_NAMES.get(code, code)
        entry = {"code": code, "name": name}
        market = dict(market_by_code.get(code) or {})
        if market.get("available"):
            outcomes = market.get("outcomes") or []
            db_names: list[str] = []
            try:
                from ..history.leagues import MAIN_PROVIDER   # noqa: PLC0415
                league = repo.get_league_by_code(MAIN_PROVIDER, "CL" if code == "UCL" else code)
                if league:
                    db_names = [t["name"] for t in repo.list_teams(league["id"])]
            except Exception:   # noqa: BLE001 - ghép tên chỉ là phần tô điểm, lỗi thì giữ tên thị trường
                db_names = []
            if db_names:
                outcomes = align_market_names(outcomes, db_names)
            market = {"available": True, "source": MARKET_SOURCE, "fetched_at": market_fetched_at,
                      "bookmakers": market.get("bookmakers"),
                      "outcomes": [{"team": o["team"], "odds": o["odds"], "prob": o["prob"]} for o in outcomes[:TOP_N]]}
        else:
            market = {"available": False, "source": MARKET_SOURCE,
                      "reason": market.get("reason") or "Chưa có dữ liệu tỉ lệ vô địch cho giải này."}
        entry["market"] = market
        if code == "UCL":
            entry["model"] = {"available": False, "note": CUP_NOTE}
        else:
            try:
                model = build_league_title_model(repo, code, params=params, n_sims=n_sims)
            except Exception as exc:   # noqa: BLE001 - một giải lỗi không được làm hỏng cả payload
                log(f"Dự đoán vô địch: mô phỏng giải {code} thất bại: {type(exc).__name__}")
                model = {"available": False, "reason": "Mô phỏng thất bại ở lần đồng bộ này."}
            if model.get("available"):
                entry["model"] = {"available": True, "n_sims": model.get("n_sims"),
                                  "fixtures_remaining": model.get("fixtures_remaining"),
                                  "note": model.get("note"),
                                  "outcomes": [{"team": o["team"], "prob": o["prob"]}
                                               for o in model["outcomes"][:TOP_N]]}
            else:
                entry["model"] = {"available": False,
                                  "reason": model.get("reason") or model.get("note") or "Chưa đủ dữ liệu để mô phỏng."}
        leagues.append(entry)
    return {"fetched_at": market_fetched_at, "simulated_at": to_iso(now), "leagues": leagues}
