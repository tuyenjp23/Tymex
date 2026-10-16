"""Tải danh sách CLB chuẩn (tên chính + các tên gọi khác) từ openfootball/clubs rồi lưu thành app/history/club_names.csv.

Chạy lại khi cần cập nhật:  python scripts/build_club_names.py
Tệp CSV có 3 cột: country, canonical, alias (mỗi tên gọi một dòng; tên chính cũng có một dòng riêng).
Bộ ghép tên đội dùng tệp này làm cơ sở: hai tên cùng thuộc một CLB thì ghép chắc chắn, hai CLB khác nhau thì không bao giờ bị gộp.
"""
from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

import httpx

BASE = "https://raw.githubusercontent.com/openfootball/clubs/master/{path}.clubs.txt"
# (tên nước dùng trong HIST_LEAGUES, đường dẫn trong repo)
FILES = [
    ("England", "europe/england/eng"), ("Wales", "europe/wales/wal"), ("Scotland", "europe/scotland/sco"),
    ("Ireland", "europe/ireland/ie"), ("Spain", "europe/spain/es"), ("Germany", "europe/germany/de"),
    ("Italy", "europe/italy/it"), ("France", "europe/france/fr"), ("Netherlands", "europe/netherlands/nl"),
    ("Portugal", "europe/portugal/pt"), ("Belgium", "europe/belgium/be"), ("Turkey", "europe/turkey/tr"),
    ("Greece", "europe/greece/gr"), ("Austria", "europe/austria/at"), ("Switzerland", "europe/switzerland/ch"),
    ("Denmark", "europe/denmark/dk"), ("Sweden", "europe/sweden/se"), ("Norway", "europe/norway/no"),
    ("Poland", "europe/poland/pl"), ("Romania", "europe/romania/ro"), ("Finland", "europe/finland/fi"),
    ("Brazil", "south-america/brazil/br"), ("Argentina", "south-america/argentina/ar"),
    ("Colombia", "south-america/colombia/co"), ("Chile", "south-america/chile/cl"),
    ("Uruguay", "south-america/uruguay/uy"), ("Ecuador", "south-america/ecuador/ec"), ("Peru", "south-america/peru/pe"),
    ("Japan", "asia/japan/jp"), ("China", "asia/china/cn"), ("South Korea", "asia/south-korea/kr"),
    ("USA", "north-america/united-states/us"), ("Canada", "north-america/canada/ca"), ("Mexico", "north-america/mexico/mx"),
]
OUT = Path(__file__).resolve().parent.parent / "app" / "history" / "club_names.csv"


def clean(name: str) -> str:
    name = re.sub(r"\[[a-z]{2,3}\]", "", name)          # nhãn ngôn ngữ như [de]
    name = name.split("#", 1)[0]
    return re.sub(r"\s+", " ", name).strip(" ,")


def parse(text: str) -> list[tuple[str, list[str]]]:
    """Trả về [(tên_chính, [tên_khác...])]. Dòng CLB: 'Tên, năm, @ sân, thành phố'; dòng tên khác bắt đầu bằng '|'."""
    clubs: list[tuple[str, list[str]]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", "=")):
            continue
        if line.startswith("|"):
            if clubs:
                clubs[-1][1].extend(a for a in (clean(x) for x in line.split("|")) if a)
            continue
        name = clean(line.split(",", 1)[0])
        if name:
            clubs.append((name, []))
    return clubs


def main() -> int:
    rows: list[tuple[str, str, str]] = []
    with httpx.Client(timeout=30, follow_redirects=True) as c:
        for country, path in FILES:
            r = c.get(BASE.format(path=path))
            if r.status_code != 200:
                print(f"! {country}: {r.status_code}", file=sys.stderr)
                continue
            for canonical, aliases in parse(r.text):
                for a in dict.fromkeys([canonical, *aliases]):
                    rows.append((country, canonical, a))
            print(f"{country}: ok")
    with OUT.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["country", "canonical", "alias"])
        w.writerows(rows)
    print(f"Đã ghi {len(rows)} dòng vào {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
