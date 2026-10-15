"""Chạy trên GitHub Actions: đồng bộ dữ liệu bóng đá, tạo/chấm dự đoán, rồi đẩy kết quả lên Supabase.

Biến môi trường bắt buộc (đặt trong GitHub → Settings → Secrets):
  FOOTBALL_DATA_API_KEY, SUPABASE_URL, SUPABASE_SERVICE_KEY
Tùy chọn: LEAGUES (mặc định PL,PD,BL1,SA,FL1), SYNC_PREVIOUS_SEASON.
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
    parser.add_argument("--no-sync", action="store_true", help="chỉ xuất lại dữ liệu đang có, không gọi API bóng đá")
    args = parser.parse_args()

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
