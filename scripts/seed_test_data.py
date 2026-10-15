"""Tạo DATABASE KIỂM THỬ RIÊNG (data/test.db) chứa dữ liệu giả để thử giao diện khi chưa có khóa API.

Cách dùng:  python scripts/seed_test_data.py   rồi   python run.py --db test
Dữ liệu này luôn bị gắn cờ và giao diện hiển thị banner đỏ "DỮ LIỆU KIỂM THỬ". Không bao giờ trộn vào football.db.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.database.db import Database  # noqa: E402
from app.database.repository import Repository  # noqa: E402
from app.main import build_container  # noqa: E402
from app.config import load_settings  # noqa: E402
from tests.fixtures import seed  # noqa: E402

if __name__ == "__main__":
    path = ROOT / "data" / "test.db"
    if path.exists():
        path.unlink()
    db = Database(path)
    db.init()
    seed(Repository(db))
    settings = load_settings()
    settings.database_path = path
    ct = build_container(settings)
    created = ct.predictions.generate_upcoming(days=7)
    print(f"Đã tạo {path} với dữ liệu KIỂM THỬ; {created} dự đoán trước trận.")
