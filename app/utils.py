"""Tiện ích thời gian và văn bản dùng chung."""
from __future__ import annotations

import unicodedata
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

ISO_FMT = "%Y-%m-%dT%H:%M:%SZ"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def to_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime(ISO_FMT)


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def normalize_utc(value: str) -> str:
    return to_iso(parse_iso(value))


def day_range_utc(day: date, tz: ZoneInfo) -> tuple[str, str]:
    """Trả về [đầu ngày, đầu ngày kế tiếp) theo múi giờ tz, đổi sang UTC dạng ISO."""
    start = datetime.combine(day, time.min, tzinfo=tz)
    end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=tz)
    return to_iso(start), to_iso(end)


def search_key(text: str | None) -> str:
    """Chuẩn hóa để tìm kiếm: bỏ dấu, chữ thường."""
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return stripped.replace("đ", "d").replace("Đ", "D").lower().strip()
