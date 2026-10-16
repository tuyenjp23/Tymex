"""Chạy trên GitHub Actions: đồng bộ dữ liệu bóng đá, tạo/chấm dự đoán, rồi đẩy kết quả lên Supabase.

Biến môi trường bắt buộc (đặt trong GitHub → Settings → Secrets):
  FOOTBALL_DATA_API_KEY, SUPABASE_URL, SUPABASE_SERVICE_KEY
Tùy chọn: LEAGUES (mặc định PL,PD,BL1,SA,FL1), SYNC_PREVIOUS_SEASON.
Nhập lịch sử miễn phí (football-data.co.uk, openfootball): HISTORY_ENABLED (mặc định bật), HISTORY_SEASONS (mặc định 5),
HISTORY_LEAGUES (mặc định tất cả: PL,ELC,PD,SD,BL1,BL2,SA,SB,FL1). Lỗi của phần lịch sử KHÔNG làm hỏng lần chạy.
Tỷ lệ cược trận sắp đá, chuỗi nguồn dự phòng (đặt khóa nào thì dùng nguồn đó, mỗi nguồn MỘT khóa):
  THE_ODDS_API_KEY (500 credit/tháng; ODDS_MAX_CALLS=3, ODDS_MIN_REMAINING=40) rồi API_FOOTBALL_KEY (100 request/ngày;
  API_FOOTBALL_MAX_CALLS=12, API_FOOTBALL_MIN_REMAINING=15). Đổi thứ tự bằng ODDS_PROVIDER_ORDER="the-odds-api,api-football".
  ODDS_LEAGUES (mặc định PL,PD,BL1,SA,FL1), ODDS_HOURS_AHEAD (30), ODDS_NEAR_INTERVAL_MIN (120), ODDS_FAR_INTERVAL_MIN (1440). Lỗi phần này cũng KHÔNG làm hỏng lần chạy.
Vắng mặt/chấn thương (cần API_FOOTBALL_KEY): ABSENCES_ENABLED (1; đặt 0 để tắt), ABSENCES_MAX_CALLS (6 request/lần chạy, 1 request/giải/ngày có trận),
  ABSENCES_INTERVAL_MIN (360). AVAILABILITY_ADJUST=0 tắt xác suất điều chỉnh tham khảo trên trang trận.
File SQLite làm việc được lưu trong Supabase Storage (bucket riêng tư) để giữ lịch sử dự đoán giữa các lần chạy.
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.cloud.export import publish          # noqa: E402
from app.cloud.supabase import SupabaseClient  # noqa: E402
from app.config import load_settings           # noqa: E402
from app.main import build_container          # noqa: E402

BUCKET, OBJECT = "tymex-private", "football.db"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="bỏ qua bộ nhớ đệm 15 phút")
    parser.add_argument("--odds-only", action="store_true", help="chỉ cập nhật tỷ lệ cược + xuất dữ liệu (chạy nhẹ, dùng gần giờ đá)")
    parser.add_argument("--no-history", action="store_true", help="không nhập dữ liệu lịch sử từ nguồn miễn phí")
    parser.add_argument("--no-sync", action="store_true", help="chỉ xuất lại dữ liệu đang có, không gọi API bóng đá")
    args = parser.parse_args()
    if args.odds_only:
        args.no_sync = args.no_history = True

    client = SupabaseClient(os.environ.get("SUPABASE_URL", ""), os.environ.get("SUPABASE_SERVICE_KEY", ""))
    workdir = Path(tempfile.mkdtemp(prefix="tymex-"))
    db_file = workdir / "football.db"
    os.environ["DATABASE_PATH"] = str(db_file)
    os.environ["AUTO_SYNC_MINUTES"] = "0"

    client.ensure_bucket(BUCKET)
    blob = client.download_object(BUCKET, OBJECT)
    if blob:
        db_file.write_bytes(blob)
        print(f"Đã tải CSDL cũ ({len(blob) // 1024} KB).")
    else:
        print("Chưa có CSDL cũ, bắt đầu mới.")

    container = build_container(load_settings(env_path=workdir / ".env"))
    exit_code = 0
    if not args.no_sync:
        result = container.sync.run(force=args.force)
        print("Đồng bộ:", result.get("message"))
        if not result.get("ok"):
            exit_code = 1   # vẫn tiếp tục xuất dữ liệu đang có, nhưng đánh dấu lần chạy là lỗi để bạn nhận email của GitHub
    history_on = os.environ.get("HISTORY_ENABLED", "true").strip().lower() not in ("0", "false", "no", "off")
    if history_on and not args.no_history:
        try:
            from app.history.runner import run_history   # noqa: PLC0415
            leagues = [c.strip() for c in os.environ.get("HISTORY_LEAGUES", "").split(",") if c.strip()] or None
            hist = run_history(container.repo, seasons=int(os.environ.get("HISTORY_SEASONS") or 5), league_codes=leagues)
            print("Lịch sử:", hist["summary"])
            report = [("doi_moi", n, "") for n in hist["new_teams_created"]]
            report += [("ghep_gan_dung", *p.split(" -> ", 1)) for p in hist["fuzzy_matches"] if " -> " in p]
            if report:
                import csv, io   # noqa: PLC0415,E401
                buf = io.StringIO()
                w = csv.writer(buf, lineterminator="\n")
                w.writerow(["loai", "ten_nguon", "khop_voi"])
                w.writerows(report)
                print("--- DANH SÁCH TÊN ĐỘI CẦN KIỂM TRA (loai,ten_nguon,khop_voi) ---")
                print(buf.getvalue().rstrip("\n"))
                print("--- HẾT DANH SÁCH ---")
                try:   # bản CSV đầy đủ, mở được bằng Excel (Supabase > Storage > tymex-private > team_names.csv)
                    client.upload_object(BUCKET, "team_names.csv", buf.getvalue().encode("utf-8-sig"))
                except Exception as exc:   # noqa: BLE001
                    print("Cảnh báo: không lưu được team_names.csv:", type(exc).__name__)
            try:   # kiểm tra trận lặp / đội bị tách đôi; bản đầy đủ lưu ở Supabase Storage > tymex-private > history_audit.txt
                from app.history.audit import audit, format_audit   # noqa: PLC0415
                lines = format_audit(audit(container.repo), limit=200)
                print("\n".join(lines[:80]))
                client.upload_object(BUCKET, "history_audit.txt", "\n".join(lines).encode("utf-8"))
            except Exception as exc:   # noqa: BLE001
                print("Cảnh báo: không chạy được kiểm tra trận lặp:", type(exc).__name__, exc)
            from app.prediction.benchmark import compare_with_odds   # noqa: PLC0415
            bench = compare_with_odds(container.repo)
            o = bench["overall"]
            if o.get("matches"):
                print(f"So với nhà cái ({o['matches']} trận, số nhỏ hơn = tốt hơn): "
                      f"log loss mô hình {o['model_ll']} | nhà cái {o['bookmaker_ll']} | đoán đều {o['uniform_ll']}; "
                      f"Brier mô hình {o['model_brier']} | nhà cái {o['bookmaker_brier']}")
        except Exception as exc:   # noqa: BLE001  - dữ liệu lịch sử chỉ bổ sung, không được làm hỏng đồng bộ chính
            print("Cảnh báo: nhập lịch sử thất bại:", exc)
    env = os.environ.get
    providers = []
    if (env("THE_ODDS_API_KEY") or "").strip():
        from app.odds.the_odds_api import TheOddsApi   # noqa: PLC0415
        providers.append(TheOddsApi(env("THE_ODDS_API_KEY"), max_calls_per_run=int(env("ODDS_MAX_CALLS") or 3),
                                    min_remaining=int(env("ODDS_MIN_REMAINING") or 40)))
    if (env("API_FOOTBALL_KEY") or "").strip():
        from app.odds.api_football import ApiFootball   # noqa: PLC0415
        providers.append(ApiFootball(env("API_FOOTBALL_KEY"), max_calls_per_run=int(env("API_FOOTBALL_MAX_CALLS") or 12),
                                     min_remaining=int(env("API_FOOTBALL_MIN_REMAINING") or 15)))
    order = [x.strip() for x in (env("ODDS_PROVIDER_ORDER") or "the-odds-api,api-football").split(",") if x.strip()]
    providers.sort(key=lambda p: order.index(p.name) if p.name in order else len(order))
    if providers:
        try:
            from app.odds.runner import refresh_upcoming_odds   # noqa: PLC0415
            res = refresh_upcoming_odds(
                container.repo, providers,
                codes=[c.strip() for c in (env("ODDS_LEAGUES") or "PL,PD,BL1,SA,FL1").split(",") if c.strip()],
                hours_ahead=float(env("ODDS_HOURS_AHEAD") or 30), near_interval_min=int(env("ODDS_NEAR_INTERVAL_MIN") or 120),
                far_interval_min=int(env("ODDS_FAR_INTERVAL_MIN") or 1440))
            print(f"Tỷ lệ cược: {res['calls']} request, ghép được {res['matched']} trận, "
                  f"đã dùng {res['used']}, còn lại {res['remaining']}")
            for line in (res["skipped"] + res["errors"])[:20]:
                print("  -", line)
            for name in sorted(set(res["unmatched"]))[:20]:
                print("  (không ghép được trận):", name)
        except Exception as exc:   # noqa: BLE001  - tỷ lệ cược chỉ bổ sung, không được làm hỏng đồng bộ chính
            print("Cảnh báo: cập nhật tỷ lệ cược thất bại:", type(exc).__name__)
    api_fb = next((p for p in providers if p.name == "api-football"), None)
    if api_fb and (env("ABSENCES_ENABLED") or "1").strip() != "0":
        try:
            from app.odds.absences import refresh_absences   # noqa: PLC0415
            res = refresh_absences(
                container.repo, api_fb,
                codes=[c.strip() for c in (env("ODDS_LEAGUES") or "PL,PD,BL1,SA,FL1").split(",") if c.strip()],
                hours_ahead=float(env("ODDS_HOURS_AHEAD") or 30), interval_min=int(env("ABSENCES_INTERVAL_MIN") or 360),
                max_calls=int(env("ABSENCES_MAX_CALLS") or 6), min_remaining=int(env("API_FOOTBALL_MIN_REMAINING") or 15))
            print(f"Vắng mặt: {res['calls']} request, {res['matched']} cầu thủ")
            for line in (res["skipped"] + res["errors"])[:10]:
                print("  -", line)
            for name in sorted(set(res["unmatched"]))[:10]:
                print("  (không ghép được đội):", name)
        except Exception as exc:   # noqa: BLE001  - chỉ bổ sung, không được làm hỏng đồng bộ chính
            print("Cảnh báo: cập nhật vắng mặt thất bại:", type(exc).__name__)
    container.predictions.generate_upcoming()
    container.predictions.resolve_results()

    stats = publish(container, client)
    print("Đã đẩy lên Supabase:", stats)

    # SQLite ở chế độ WAL: gộp về file chính trước khi tải lên
    with container.db.connect() as conn:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    client.upload_object(BUCKET, OBJECT, db_file.read_bytes())
    print("Đã lưu CSDL lên Supabase Storage.")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
