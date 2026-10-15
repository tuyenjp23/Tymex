"""Ghép tên đội của nguồn lịch sử với đội đã có trong CSDL (tránh một đội bị tách thành hai).

Thứ tự: khớp chính xác (sau chuẩn hóa) → bí danh viết tay → tên nguồn là tập con của tên đội (duy nhất)
→ giống nhau gần đúng (duy nhất). Không chắc chắn thì KHÔNG đoán: tạo đội mới và báo lại để bạn thêm bí danh.
"""
from __future__ import annotations

import difflib
import re

from ..data_providers.base import TeamDTO
from ..utils import search_key
from .leagues import MAIN_PROVIDER

STOP = {
    "fc", "afc", "cf", "sc", "ssc", "ss", "ac", "acf", "as", "us", "rc", "rcd", "ud", "cd", "ca", "sd", "sv", "fsv",
    "vfl", "vfb", "tsg", "uc", "de", "del", "di", "da", "the", "club", "calcio", "balompie", "futbol",
}

# khóa = tên (đã chuẩn hóa) trong football-data.co.uk / openfootball; giá trị = dạng chuẩn hóa của tên trong football-data.org
ALIASES = {
    "man united": "manchester united", "man city": "manchester city", "nottm forest": "nottingham forest",
    "spurs": "tottenham hotspur", "tottenham": "tottenham hotspur", "wolves": "wolverhampton wanderers",
    "sheffield utd": "sheffield united", "sheffield weds": "sheffield wednesday", "qpr": "queens park rangers",
    "west brom": "west bromwich albion", "leeds": "leeds united",
    "ath madrid": "atletico madrid", "ath bilbao": "athletic", "athletic bilbao": "athletic", "espanol": "espanyol",
    "sp gijon": "sporting gijon", "la coruna": "deportivo la coruna", "vallecano": "rayo vallecano",
    "mgladbach": "borussia monchengladbach", "bayern munich": "bayern munchen", "ein frankfurt": "eintracht frankfurt",
    "hamburg": "hamburger", "karlsruhe": "karlsruher", "fortuna dusseldorf": "fortuna dusseldorf",
    "nurnberg": "nurnberg", "greuther furth": "greuther furth",
    "inter": "internazionale milano", "milan": "milan", "verona": "hellas verona",
    "paris sg": "paris saint germain", "lyon": "lyonnais", "rennes": "rennais", "brest": "brestois",
    "st etienne": "saint etienne", "marseille": "marseille",
}


def norm(name: str | None) -> str:
    s = search_key(name or "")
    s = s.replace("&", " and ").replace("'", "").replace("’", "")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    toks = [t for t in s.split() if t not in STOP and not t.isdigit()]
    return " ".join(toks)


def _tokens(key: str) -> set[str]:
    return set(key.split())


class TeamResolver:
    """Nhận tên đội từ nguồn lịch sử, trả về id đội trong CSDL (tạo mới nếu không ghép được)."""

    def __init__(self, repo, new_provider: str = MAIN_PROVIDER):
        self.repo = repo
        self.new_provider = new_provider
        self.teams = repo.all_teams_min()
        self._rebuild()
        self.created: list[str] = []
        self.fuzzy: list[tuple[str, str]] = []
        self._cache: dict[str, int] = {}

    def _rebuild(self) -> None:
        self.keys: dict[int, set[str]] = {}
        for t in self.teams:
            ks = {norm(t["name"]), norm(t.get("short_name")), norm(t.get("tla"))}
            self.keys[t["id"]] = {k for k in ks if k}
        self.names = {t["id"]: t["name"] for t in self.teams}

    def _exact(self, form: str) -> list[int]:
        return [tid for tid, ks in self.keys.items() if form in ks]

    def _subset(self, form: str) -> list[int]:
        """Tên nguồn ngắn hơn và là tập con các từ của tên đội (vd 'newcastle' ⊂ 'newcastle united')."""
        ft = _tokens(form)
        if not ft or len(form) < 4:
            return []
        return [tid for tid, ks in self.keys.items() if any(ft <= _tokens(k) for k in ks)]

    def _close(self, form: str) -> list[int]:
        scored = []
        for tid, ks in self.keys.items():
            best = max((difflib.SequenceMatcher(None, form, k).ratio() for k in ks), default=0)
            if best >= 0.88:
                scored.append((best, tid))
        scored.sort(reverse=True)
        if len(scored) >= 2 and scored[0][0] - scored[1][0] < 0.05:
            return []
        return [scored[0][1]] if scored else []

    def lookup(self, raw_name: str) -> int | None:
        """Tìm đội đã có trong CSDL; KHÔNG tạo đội mới. None nếu không chắc chắn."""
        base = norm(raw_name)
        forms = [base] + ([ALIASES[base]] if base in ALIASES else [])
        for f in forms:                                  # 1) chính xác (kể cả bí danh)
            hit = self._exact(f)
            if len(hit) == 1:
                return hit[0]
        for f in forms:                                  # 2) tập con duy nhất
            hit = self._subset(f)
            if len(hit) == 1:
                self.fuzzy.append((raw_name, self.names[hit[0]]))
                return hit[0]
        hit = self._close(base)                          # 3) gần đúng duy nhất
        if hit:
            self.fuzzy.append((raw_name, self.names[hit[0]]))
            return hit[0]
        return None

    def resolve_existing(self, raw_name: str) -> int | None:
        return self.lookup((raw_name or "").strip())

    def resolve(self, raw_name: str) -> int:
        raw_name = (raw_name or "").strip()
        if raw_name in self._cache:
            return self._cache[raw_name]
        tid = self.lookup(raw_name)
        if tid is None:                                  # 4) không chắc → tạo đội mới, báo lại
            base = norm(raw_name)
            tid = self.repo.upsert_team(self.new_provider, TeamDTO(external_id=f"hist:{base or raw_name.lower()}", name=raw_name))
            self.teams.append({"id": tid, "provider": self.new_provider, "external_id": f"hist:{base}", "name": raw_name,
                               "short_name": None, "tla": None})
            self._rebuild()
            self.created.append(raw_name)
        self._cache[raw_name] = tid
        return tid
