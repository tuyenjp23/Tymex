"""Khởi động website: python run.py  (mặc định chỉ truy cập được từ máy này)."""
import argparse
import os
import webbrowser

import uvicorn

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Personal Football Analytics")
    parser.add_argument("--host", default="127.0.0.1", help="Dùng 0.0.0.0 để mở cho điện thoại cùng mạng Wi-Fi")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--db", choices=["real", "test"], default="real",
                        help="test = dùng data/test.db (dữ liệu KIỂM THỬ giả, tạo bằng scripts/seed_test_data.py)")
    args = parser.parse_args()
    if args.db == "test":
        os.environ["DATABASE_PATH"] = "data/test.db"
    if not args.no_browser:
        webbrowser.open(f"http://127.0.0.1:{args.port}")
    uvicorn.run("app.main:app_factory", factory=True, host=args.host, port=args.port, log_level="info")
