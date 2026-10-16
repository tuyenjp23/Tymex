"""Chạy thử việc nhập lịch sử NGAY TRÊN MÁY (không cần khóa API, không đụng Supabase/GitHub).

Dùng CSDL SQLite tạm, tải dữ liệu thật qua mạng của máy bạn, rồi in: log từng nguồn/giải, lỗi (kể cả dòng `! espn`),
danh sách đội mới và ghép gần đúng. Xong ghi `team_names_test.csv` (mở bằng Excel).

Ví dụ:
  python scripts/thu_lich_su.py                     # mọi giải, 2 mùa gần nhất
  python scripts/thu_lich_su.py KR1 AU1 SA1         # chỉ vài giải
  python scripts/thu_lich_su.py KR1 --seasons 1
  python scripts/thu_lich_su.py --sources espn      # chỉ thử ESPN (co.uk, openfootball, co.uk/new, espn, world)
"""
from __future__ import annotations

import argparse
import csv
import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database.db import Database                   # noqa: E402
from app.database.repository import Repository         # noqa: E402
from app.history.audit import audit, format_audit      # noqa: E402
from app.history.leagues import HIST_LEAGUES           # noqa: E402
from app.history.runner import ALL_SOURCES, run_history  # noqa: E402

ALIAS = {"co.uk": "football-data.co.uk", "openfootball": "openfootball", "co.uk/new": "football-data.co.uk/new",
         "espn": "espn", "world": "openfootball/world"}


class Tee:
    """In ra màn hình đồng thời ghi vào file log; ghi và đẩy xuống đĩa NGAY từng dòng, nên dù cửa sổ bị đóng giữa chừng vẫn còn log."""

    def __init__(self, path: Path, out):
        self.f = path.open("w", encoding="utf-8", buffering=1)
        self.out = out

    def write(self, text):
        try:
            self.out.write(text)
        except UnicodeEncodeError:
            self.out.write(text.encode("ascii", "replace").decode())
        self.f.write(text)
        self.f.flush()
        return len(text)

    def flush(self):
        self.out.flush(); self.f.flush()


def main() -> int:
    import traceback   # noqa: PLC0415
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:   # noqa: BLE001
            pass
    logs = Path(__file__).resolve().parent.parent / "logs"
    logs.mkdir(exist_ok=True)
    log_path = logs / f"thu_lich_su_{datetime.now():%Y%m%d_%H%M%S}.log"
    real_out, real_err = sys.stdout, sys.stderr
    sys.stdout = sys.stderr = Tee(log_path, real_out)
    print(f"Bắt đầu {datetime.now():%Y-%m-%d %H:%M:%S}  |  tham số: {' '.join(sys.argv[1:]) or '(mặc định)'}")
    code = 1
    try:
        code = _run()
    except SystemExit as e:
        code = int(e.code or 0)
    except BaseException:   # noqa: BLE001  - ghi cả lỗi sập chương trình và Ctrl+C vào log
        print("\n!!! CHƯƠNG TRÌNH BỊ DỪNG VÌ LỖI:")
        traceback.print_exc()
    finally:
        print(f"\nKết thúc {datetime.now():%H:%M:%S}. Đã lưu log: {log_path}")
        tee = sys.stdout
        sys.stdout, sys.stderr = real_out, real_err
        tee.f.close()
    (logs / "moi_nhat.log").write_text(log_path.read_text(encoding="utf-8"), encoding="utf-8")   # luôn có bản mới nhất, tên cố định
    return code


def _run() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("leagues", nargs="*", help="mã giải (mặc định: tất cả). Mã hợp lệ: " + ",".join(x["code"] for x in HIST_LEAGUES))
    ap.add_argument("--seasons", type=int, default=2, help="số mùa gần nhất (mặc định 2, trên Actions là 5)")
    ap.add_argument("--sources", default="", help="co.uk,openfootball,co.uk/new,espn,world (mặc định tất cả)")
    args = ap.parse_args()
    srcs = tuple(ALIAS.get(s.strip(), s.strip()) for s in args.sources.split(",") if s.strip()) or ALL_SOURCES
    bad = [s for s in srcs if s not in ALL_SOURCES]
    if bad:
        print("Nguồn không hợp lệ:", bad, "- hợp lệ:", list(ALIAS)); return 2
    with tempfile.TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "test.db"); db.init()
        repo = Repository(db)
        out = run_history(repo, seasons=args.seasons, league_codes=[c.upper() for c in args.leagues] or None, sources=srcs)
        report = format_audit(audit(repo))
    print("\nTÓM TẮT:", out["summary"])
    if out["errors"]:
        print("\nLỖI (gửi các dòng này cho Claude):")
        for e in out["errors"][:20]:
            print("  !", e)
        if len(out["errors"]) > 20:
            print(f"  ... và {len(out['errors']) - 20} lỗi nữa")
    rows = [("doi_moi", n, "") for n in out["new_teams_created"]] + [("ghep_gan_dung", *p.split(" -> ", 1)) for p in out["fuzzy_matches"] if " -> " in p]
    print()
    print("\n".join(report))
    path = Path(__file__).resolve().parent.parent / "logs" / "team_names_test.csv"
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f); w.writerow(["loai", "ten_nguon", "khop_voi"]); w.writerows(rows)
    print(f"\nĐã ghi {path.resolve()} ({len(rows)} dòng). Ghép gần đúng cần kiểm tra:")
    for r in rows:
        if r[0] == "ghep_gan_dung":
            print("  ", r[1], "->", r[2])
    return 1 if out["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
