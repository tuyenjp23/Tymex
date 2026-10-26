"""Ghi mẫu KIỂM SOÁT BÓNG theo thời gian cho các trận đang đá — chạy TRÊN MÁY CHỦ (GitHub Actions).

Vì sao phải ghi ở máy chủ: ESPN chỉ cho % kiểm soát bóng LŨY KẾ tại thời điểm gọi (không có lịch sử
theo phút). Muốn có biểu đồ theo thời gian thì phải tự gọi ESPN định kỳ và lưu lại từng mẫu, kể cả
khi không có ai mở trang web — đó là việc của script này. Workflow .github/workflows/sample-live.yml
khởi động mỗi giờ và chạy script ở chế độ vòng lặp 52 phút, chu kỳ mục tiêu 90 giây; vì vậy mẫu thực
tế cách nhau khoảng 1–2 phút. Lịch khởi động của GitHub Actions vẫn có thể trễ vài phút và quanh thời
điểm chuyển ca mỗi giờ có thể khuyết vài phút.

Luồng: với từng giải trong danh sách ESPN đã kiểm chứng (đọc trực tiếp từ web/live.js để hai nơi
không lệch nhau), lấy scoreboard; với mỗi trận có status state="in", gọi summary lấy possessionPct
của đội nhà, tạo một mẫu rồi đọc-sửa-ghi (read-modify-write) vào bảng `kv` của Supabase:
    khóa  = "possession:<espn_event_id>"
    payload = {"event": {thông tin trận}, "samples": [mẫu...]}

Hai chế độ khử trùng/giới hạn:
- Chạy một lần (mặc định, gồm --dry-run và kiểm thử): khử trùng theo "xô" 5 phút, tối đa 40 mẫu/trận.
- Vòng lặp (--loop-minutes N): TẮT xô 5 phút; chỉ bỏ mẫu cách mẫu đã lưu gần nhất dưới 45 giây,
  tối đa 130 mẫu/trận — đủ dày cho một trận bóng đá ở chu kỳ ~90 giây.
Script cũng dọn các khóa possession:* có updated_at cũ hơn 3 ngày bằng chính mẫu truy vấn của
SupabaseClient (ở chế độ vòng lặp chỉ dọn ở chu kỳ đầu).

Bí mật đọc từ biến môi trường SUPABASE_URL / SUPABASE_SERVICE_KEY (giống scripts/cloud_sync.py);
khóa service role KHÔNG bao giờ xuống trình duyệt. `--dry-run` chỉ in mẫu ra stdout, không ghi gì
và không cần hai biến môi trường trên.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer"
HEADERS = {"User-Agent": "Mozilla/5.0 (Tymex possession sampler)"}
KV_PREFIX = "possession:"
MAX_SAMPLES_PER_MATCH = 40              # chạy một lần (mặc định)
LOOP_MAX_SAMPLES_PER_MATCH = 130        # chế độ vòng lặp ~90 giây/chu kỳ
DEDUPE_BUCKET_SECONDS = 5 * 60          # chạy một lần: hai mẫu cùng xô 5 phút coi là trùng
LOOP_DEDUPE_SECONDS = 45                # vòng lặp: bỏ mẫu cách mẫu đã lưu < 45 giây
DEFAULT_LOOP_MINUTES = 0                # 0 = chỉ chạy một chu kỳ rồi thoát
DEFAULT_INTERVAL_SECONDS = 90
PRUNE_AFTER_DAYS = 3
DEFAULT_PRUNE = True


def load_leagues(text: str | None = None) -> list[dict]:
    """Danh sách giải ESPN: bóc trực tiếp từ LIVE_LEAGUE_GROUPS trong web/live.js (nguồn sự thật duy nhất)."""
    if text is None:
        text = (Path(__file__).resolve().parent.parent / "web" / "live.js").read_text(encoding="utf-8")
    out = []
    for m in re.finditer(r'\{\s*slug:\s*"([^"]+)",\s*name:\s*"([^"]+)"(\s*,\s*featured:\s*true)?\s*\}', text):
        out.append({"slug": m.group(1), "name": m.group(2), "featured": bool(m.group(3))})
    if not out:
        raise ValueError("Không bóc được danh sách giải ESPN từ web/live.js")
    return out


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_ts(value) -> datetime | None:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc)
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def parse_clock(display, value_seconds=None) -> tuple[str, int | None]:
    """'45'+2'' -> ('45'+2'', 47); '67'' -> 67. Không đọc được thì suy từ giây, vẫn không có thì (nhãn, None)."""
    label = str(display or "").strip()
    if label:
        parts = [p for p in label.replace("'", "").split("+") if p.strip().isdigit()]
        if parts:
            return label, sum(int(p) for p in parts)
    if value_seconds is not None:
        try:
            minute = int(float(value_seconds) // 60)
            return f"{minute}'", minute
        except (TypeError, ValueError):
            pass
    return label, None


def extract_live_events(scoreboard: dict, league: dict) -> list[dict]:
    """Các trận ĐANG ĐÁ (state='in') trong một scoreboard ESPN, kèm thông tin cần cho mẫu."""
    out = []
    for ev in (scoreboard or {}).get("events") or []:
        comp = (ev.get("competitions") or [{}])[0]
        status = ev.get("status") or comp.get("status") or {}
        st_type = status.get("type") or {}
        if st_type.get("state") != "in":
            continue
        competitors = comp.get("competitors") or []
        home = next((c for c in competitors if c.get("homeAway") == "home"), None)
        away = next((c for c in competitors if c.get("homeAway") == "away"), None)
        if not home or not away or ev.get("id") is None:
            continue
        clock_obj = status.get("clock")
        clock_seconds = clock_obj.get("value") if isinstance(clock_obj, dict) else clock_obj
        clock_label, minute = parse_clock(status.get("displayClock"), clock_seconds)
        def score(c):
            try:
                return int(c.get("score"))
            except (TypeError, ValueError):
                return None
        out.append({
            "espn_event_id": str(ev["id"]),
            "league_slug": league["slug"],
            "league_name": league["name"],
            "home": (home.get("team") or {}).get("displayName") or "",
            "away": (away.get("team") or {}).get("displayName") or "",
            "home_score": score(home), "away_score": score(away),
            "start_iso": ev.get("date"),
            "clock": clock_label, "minute": minute,
            "status_detail": st_type.get("shortDetail") or st_type.get("description") or "",
        })
    return out


def extract_possession_sample(summary: dict, event_meta: dict, sampled_at: datetime) -> dict | None:
    """Một mẫu kiểm soát bóng từ ESPN summary; thiếu possessionPct của một trong hai đội -> None."""
    stats = {}
    for team in ((summary or {}).get("boxscore") or {}).get("teams") or []:
        side = team.get("homeAway")
        if side not in ("home", "away"):
            continue
        values = {s.get("name"): s.get("displayValue") for s in team.get("statistics") or []}
        if values.get("possessionPct") is not None:
            stats[side] = values["possessionPct"]
    if "home" not in stats or "away" not in stats:
        return None
    try:
        home_pct = float(stats["home"])
        away_pct = float(stats["away"])
    except (TypeError, ValueError):
        return None
    if not (0.0 <= home_pct <= 100.0) or not (0.0 <= away_pct <= 100.0):
        return None
    return {
        "espn_event_id": event_meta["espn_event_id"],
        "league_slug": event_meta["league_slug"],
        "league_name": event_meta["league_name"],
        "home": event_meta["home"], "away": event_meta["away"],
        "clock": event_meta.get("clock") or "", "minute": event_meta.get("minute"),
        "home_score": event_meta.get("home_score"), "away_score": event_meta.get("away_score"),
        "possession_home_pct": round(home_pct, 1), "possession_away_pct": round(away_pct, 1),
        "ts_utc": _iso(sampled_at),
    }


def _bucket(ts: datetime) -> int:
    return math.floor(ts.timestamp() / DEDUPE_BUCKET_SECONDS)


def merge_payload(existing_payload, event_meta: dict, sample: dict, *,
                  max_samples: int = MAX_SAMPLES_PER_MATCH,
                  min_interval_seconds: float | None = None) -> dict:
    """Đọc-sửa-ghi một khóa kv: gộp mẫu mới vào payload cũ và giữ các mẫu mới nhất.

    Mặc định giữ đúng hành vi chạy một lần: khử trùng theo xô 5 phút, tối đa 40 mẫu.
    Khi `min_interval_seconds` được truyền (chế độ vòng lặp), KHÔNG dùng xô 5 phút nữa;
    mẫu mới chỉ bị bỏ nếu cách bất kỳ mẫu đã lưu nào dưới ngưỡng đó (mặc định vòng lặp: 45 giây).
    """
    payload = existing_payload if isinstance(existing_payload, dict) else {}
    event = dict(payload.get("event") or {})
    event.update({k: event_meta.get(k) for k in
                  ("espn_event_id", "league_slug", "league_name", "home", "away", "start_iso")})
    samples = [s for s in (payload.get("samples") or []) if isinstance(s, dict) and _parse_ts(s.get("ts_utc"))]
    new_ts = _parse_ts(sample.get("ts_utc"))
    if new_ts is not None:
        if min_interval_seconds is None:
            duplicate = any(_bucket(_parse_ts(s["ts_utc"])) == _bucket(new_ts) for s in samples)
        else:
            duplicate = any(abs((_parse_ts(s["ts_utc"]) - new_ts).total_seconds()) < min_interval_seconds
                            for s in samples)
        if not duplicate:
            samples.append(sample)
    samples.sort(key=lambda s: s["ts_utc"])
    cap = max(1, int(max_samples))
    return {"event": event, "samples": samples[-cap:]}


def _get_json(client: httpx.Client, url: str) -> dict | None:
    try:
        resp = client.get(url)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:  # noqa: BLE001 — lỗi một giải/trận không được làm hỏng cả lần chạy
        print(f"Cảnh báo: không tải được {url}: {type(exc).__name__}")
        return None


def collect_samples(espn: httpx.Client, leagues: list[dict], now: datetime) -> list[tuple[dict, dict]]:
    """Quét mọi giải; trả [(event_meta, sample)]. Lỗi từng giải/trận được bỏ qua có in cảnh báo."""
    found: list[tuple[dict, dict]] = []
    for league in leagues:
        board = _get_json(espn, f"{ESPN_BASE}/{league['slug']}/scoreboard")
        if board is None:
            continue
        for meta in extract_live_events(board, league):
            summary = _get_json(espn, f"{ESPN_BASE}/{league['slug']}/summary?event={meta['espn_event_id']}")
            if summary is None:
                continue
            sample = extract_possession_sample(summary, meta, now)
            if sample is None:
                print(f"Cảnh báo: trận {meta['espn_event_id']} ({meta['home']} - {meta['away']}) "
                      "không có possessionPct trong summary ESPN, bỏ qua.")
                continue
            found.append((meta, sample))
    return found


def run_sampling_cycle(*, dry_run: bool = False, loop_mode: bool = False,
                       prune: bool = True, now: datetime | None = None) -> int:
    """Một chu kỳ quét ESPN và (trừ --dry-run) ghi mẫu vào Supabase kv."""
    now = now or datetime.now(timezone.utc)
    leagues = load_leagues()
    with httpx.Client(headers=HEADERS, timeout=20.0) as espn:
        found = collect_samples(espn, leagues, now)
    if not found:
        print(f"Không có trận nào đang đá ở {len(leagues)} giải ESPN tại {_iso(now)} — không ghi gì.")
        return 0
    print(f"Có {len(found)} trận đang đá có số liệu kiểm soát bóng.")
    if dry_run:
        for _, sample in found:
            print(json.dumps(sample, ensure_ascii=False))
        return 0

    from app.cloud.supabase import SupabaseClient  # noqa: PLC0415 — chỉ cần khi thật sự ghi
    client = SupabaseClient(os.environ.get("SUPABASE_URL", ""), os.environ.get("SUPABASE_SERVICE_KEY", ""))
    if prune:
        try:
            pruned = client.prune_kv_prefix(KV_PREFIX, _iso(now - timedelta(days=PRUNE_AFTER_DAYS)))
            if pruned:
                print(f"Đã dọn {pruned} khóa possession cũ hơn {PRUNE_AFTER_DAYS} ngày.")
        except Exception as exc:  # noqa: BLE001 — dọn dẹp hỏng không được chặn việc ghi mẫu mới
            print("Cảnh báo: không dọn được khóa possession cũ:", type(exc).__name__)
    stamp = _iso(now)
    written = 0
    for meta, sample in found:
        key = f"{KV_PREFIX}{meta['espn_event_id']}"
        try:
            existing = client.get_kv(key)
            if loop_mode:
                payload = merge_payload(existing["payload"] if existing else None, meta, sample,
                                        max_samples=LOOP_MAX_SAMPLES_PER_MATCH,
                                        min_interval_seconds=LOOP_DEDUPE_SECONDS)
            else:
                payload = merge_payload(existing["payload"] if existing else None, meta, sample)
            client.upsert("kv", [{"key": key, "payload": payload, "updated_at": stamp}], "key")
            written += 1
        except Exception as exc:  # noqa: BLE001
            print(f"Cảnh báo: không ghi được {key}: {type(exc).__name__}")
    print(f"Đã ghi {written}/{len(found)} khóa possession vào Supabase kv.")
    return 0 if written else 1


def run_loop(cycle, *, loop_minutes: float, interval_seconds: float,
             monotonic=time.monotonic, sleep=time.sleep, log=print) -> int:
    """Lặp `cycle` mỗi ~interval_seconds trong loop_minutes phút; trả số chu kỳ đã chạy.

    Chỉ ngủ PHẦN CÒN LẠI của chu kỳ sau khi trừ thời gian cycle chạy. Nếu một chu kỳ chạy quá
    interval thì không ngủ, ghi log và bắt đầu chu kỳ kế tiếp ngay (trừ khi đã hết thời lượng lặp).
    """
    total_seconds = max(0.0, float(loop_minutes)) * 60.0
    if total_seconds <= 0:
        cycle()
        return 1
    deadline = monotonic() + total_seconds
    cycles = 0
    while True:
        started = monotonic()
        cycle()
        cycles += 1
        elapsed = monotonic() - started
        if elapsed > interval_seconds:
            log(f"Cảnh báo: chu kỳ ghi mẫu chạy {elapsed:.1f} giây, lâu hơn chu kỳ mục tiêu "
                f"{interval_seconds:g} giây — bắt đầu chu kỳ kế tiếp ngay, không ngủ.")
        remaining = deadline - monotonic()
        if remaining <= 0:
            break
        delay = max(0.0, float(interval_seconds) - elapsed)
        if delay > 0:
            sleep(min(delay, remaining))
    return cycles


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Ghi mẫu kiểm soát bóng của các trận đang đá vào Supabase kv.")
    parser.add_argument("--dry-run", action="store_true", help="chỉ in mẫu ra stdout, không ghi Supabase")
    parser.add_argument("--loop-minutes", type=float, default=DEFAULT_LOOP_MINUTES,
                        help="lặp việc ghi mẫu trong N phút (mặc định 0 = chỉ chạy một lần)")
    parser.add_argument("--interval-seconds", type=float, default=DEFAULT_INTERVAL_SECONDS,
                        help="chu kỳ mục tiêu giữa các lần ghi mẫu ở chế độ vòng lặp (mặc định 90 giây)")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.loop_minutes < 0:
        parser.error("--loop-minutes không được âm")
    if args.interval_seconds <= 0:
        parser.error("--interval-seconds phải lớn hơn 0")
    if args.loop_minutes <= 0:
        return run_sampling_cycle(dry_run=args.dry_run, loop_mode=False, prune=True)

    print(f"Bắt đầu chế độ vòng lặp ghi mẫu: {args.loop_minutes:g} phút, chu kỳ mục tiêu "
          f"{args.interval_seconds:g} giây (khử trùng < {LOOP_DEDUPE_SECONDS} giây, tối đa "
          f"{LOOP_MAX_SAMPLES_PER_MATCH} mẫu/trận).")
    results: list[int] = []
    first_cycle = True

    def cycle() -> None:
        nonlocal first_cycle
        try:
            code = run_sampling_cycle(dry_run=args.dry_run, loop_mode=True,
                                       prune=first_cycle and not args.dry_run)
        except Exception as exc:  # noqa: BLE001 — một chu kỳ hỏng không được kết thúc cả ca ghi mẫu
            print(f"Cảnh báo: chu kỳ ghi mẫu lỗi ({type(exc).__name__}: {exc}) — tiếp tục chu kỳ sau.")
            code = 1
        results.append(code)
        first_cycle = False

    cycles = run_loop(cycle, loop_minutes=args.loop_minutes, interval_seconds=args.interval_seconds)
    print(f"Kết thúc chế độ vòng lặp sau {cycles} chu kỳ.")
    return 0 if any(code == 0 for code in results) else 1


if __name__ == "__main__":
    sys.exit(main())
