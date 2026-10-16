"""Ghép tên đội của nguồn lịch sử với đội đã có trong CSDL (tránh một đội bị tách thành hai).

Thứ tự: khớp chính xác (sau chuẩn hóa) → bí danh viết tay → tên nguồn là tập con của tên đội (duy nhất)
→ giống nhau gần đúng (duy nhất). Không chắc chắn thì KHÔNG đoán: tạo đội mới và báo lại để bạn thêm bí danh.
"""
from __future__ import annotations

import csv
import difflib
import re
from functools import lru_cache
from pathlib import Path

from ..data_providers.base import TeamDTO
from ..utils import search_key
from .leagues import MAIN_PROVIDER

STOP = {
    "fc", "afc", "cf", "sc", "ssc", "ss", "ac", "acf", "as", "us", "rc", "rcd", "ud", "cd", "ca", "sd", "sv", "fsv",
    "vfl", "vfb", "tsg", "uc", "de", "del", "di", "da", "the", "club", "calcio", "balompie", "futbol",
    "ssv", "tsv", "spvgg", "bsc", "hsc",
}

# Từ chung chung (đứng một mình không đủ xác định một CLB): không dùng làm "tên ngắn" để gộp tên dài vào
# (vd 'athletic' của Athletic Club không được hút 'Charlton Athletic' / 'Wigan Athletic')
GENERIC_TOKENS = {
    "athletic", "atletico", "united", "city", "town", "rovers", "wanderers", "county", "albion", "rangers", "wednesday",
    "argyle", "hotspur", "forest", "villa", "real", "racing", "sporting", "dynamo", "olympique", "borussia", "eintracht",
    "fortuna", "hansa", "inter", "internazionale",
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
    # --- các cặp cùng một CLB bị tách đôi trong log (tên viết khác nhau giữa nguồn co.uk và openfootball/ESPN)
    "sp lisbon": "sporting cp", "sporting clube portugal": "sporting cp",
    "sp braga": "sporting clube braga", "sporting braga": "sporting clube braga",
    "psv": "psv eindhoven", "az": "az alkmaar",
    "argentinos jrs": "argentinos juniors", "urawa reds": "urawa red diamonds",
    "peterboro": "peterborough united", "gornik z": "gornik zabrze", "heart midlothian": "hearts",
    "kasimpasa sk": "kasimpasa", "willem ii tilburg": "willem ii", "gimnasia la plata": "gimnasia l p",
    "atl tucuman": "atletico tucuman", "atl san luis": "atletico san luis", "ind rivadavia": "independiente rivadavia",
    "atletico goianiense": "atletico go", "athletico pr": "paranaense", "athletico paranaense": "paranaense",
    "remo pa": "clube remo", "remo": "clube remo", "atletico mg": "mineiro",
    "heart of midlothian": "hearts", "buyuksehyr": "istanbul basaksehir", "dep riestra": "deportivo riestra",
    "ae larissa": "larisa", "ofi heraklion": "ofi crete", "gs kallithea": "athens kallithea", "ae kifisias": "kifisia",
    "accrington": "accrington stanley", "karagumruk": "fatih karagumruk",
    "st gilloise": "union saint gilloise", "rb bragantino": "bragantino", "olympiakos piraeus": "olympiakos",
    "bodrum fk": "bodrumspor", "cr flamengo": "flamengo rj", "shenzhen xinpengcheng": "shenzhen peng city",
}


# Đội dự bị/trẻ (Real Sociedad B, Villarreal II...) là đội KHÁC với đội chính: không bao giờ ghép gần đúng giữa hai nhóm này
RESERVE_TOKENS = {"b", "ii", "c", "u19", "u21", "u23"}

# Tên thành phố có NHIỀU CLB (Barcelona: FC Barcelona / Espanyol; Paris: PSG / Paris FC...): không bao giờ tự ghép theo tập con từ,
# chỉ khớp chính xác hoặc qua bí danh
AMBIGUOUS_CITIES = {
    "barcelona", "madrid", "paris", "milan", "manchester", "sheffield", "london", "liverpool", "nottingham", "bristol",
    "berlin", "genoa", "turin", "rome", "seville", "glasgow",
    # nhiều CLB cùng gốc tên trong một nước (Dundee/Dundee United, Independiente/Independiente Rivadavia, Yokohama FC/F. Marinos...)
    "dundee", "wisla", "independiente", "yokohama", "tokyo", "cordoba", "santa fe", "nacional", "central", "union", "deportivo",
}

# Cặp tên giống nhau nhưng là hai CLB khác nhau: cấm ghép (dạng đã chuẩn hóa)
DENY_PAIRS = {
    frozenset({"reggiana", "reggina"}),
    frozenset({"gremio", "gremio novorizontino"}),     # hai CLB khác nhau (Grêmio Novorizontino SP)
    frozenset({"gremio", "gremio novorizontino sp"}),
    frozenset({"atletico mg", "atletico go"}),          # Atlético Mineiro ≠ Atlético Goianiense
    frozenset({"athletic mg", "atletico mg"}),          # Athletic Club (MG) ≠ Atlético Mineiro
    frozenset({"cercle brugge", "brugge"}), frozenset({"cercle brugge", "brugge kv"}),       # Cercle Brugge ≠ Club Brugge
    frozenset({"guangzhou city", "guangzhou"}),         # Guangzhou City ≠ Guangzhou FC (Evergrande)
    frozenset({"wuhan", "wuhan three towns"}),          # Wuhan FC (Zall) ≠ Wuhan Three Towns
    frozenset({"los angeles galaxy", "los angeles"}),   # LA Galaxy ≠ LAFC
    frozenset({"lausanne", "lausanne ouchy"}),          # Lausanne-Sport ≠ Lausanne Ouchy
    frozenset({"shenzhen peng city", "shenzhen"}), frozenset({"shenzhen xinpengcheng", "shenzhen"}),
}


_TRANSLIT = str.maketrans({"ı": "i", "İ": "i", "ł": "l", "Ł": "l", "ø": "o", "Ø": "o", "æ": "ae", "Æ": "ae", "ß": "ss",
                           "ð": "d", "þ": "th"})


@lru_cache(maxsize=200_000)
def norm(name: str | None) -> str:
    s = search_key((name or "").translate(_TRANSLIT))
    s = s.replace("&", " and ").replace("'", "").replace("’", "")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    toks = [t for t in s.split() if t not in STOP and not t.isdigit()]
    return " ".join(toks)


def _tokens(key: str) -> set[str]:
    return set(key.split())


def is_reserve(key: str) -> bool:
    toks = key.split()
    return len(toks) >= 2 and toks[-1] in RESERVE_TOKENS


# Nhóm nước dùng chung một danh sách CLB (Cardiff/Swansea đá ở Anh; Toronto/Vancouver đá ở MLS)
COUNTRY_GROUP = {"Wales": "England", "Canada": "USA"}
CLUB_CSV = Path(__file__).with_name("club_names.csv")


class ClubDirectory:
    """Bảng CLB chuẩn (openfootball/clubs, xem scripts/build_club_names.py): tên chính + các tên gọi khác theo từng nước.

    `club_id(tên, nước)` trả về mã CLB chắc chắn (hai tên cùng CLB cho cùng mã, hai CLB khác nhau cho mã khác nhau)
    hoặc None nếu tên chưa có trong bảng. Tên gọi trùng cho nhiều CLB trong cùng nước bị bỏ qua (không đoán).
    """

    def __init__(self, rows: list[tuple[str, str, str]]):
        cand: dict[str, dict[str, set[str]]] = {}
        own: dict[str, dict[str, set[str]]] = {}
        self.display: dict[str, dict[str, str]] = {}
        for country, canonical, alias in rows:
            g = COUNTRY_GROUP.get(country, country)
            cn, an = norm(canonical), norm(alias)
            if not cn or len(an) < 2:
                continue
            cand.setdefault(g, {}).setdefault(an, set()).add(cn)
            self.display.setdefault(g, {}).setdefault(cn, canonical)
            if an == cn:
                own.setdefault(g, {}).setdefault(an, set()).add(cn)
        self.alias: dict[str, dict[str, str]] = {}
        for g, table in cand.items():
            out = {}
            for an, clubs in table.items():
                if len(clubs) == 1:
                    out[an] = next(iter(clubs))
                elif len(own.get(g, {}).get(an, ())) == 1:          # trùng với tên chính của đúng một CLB → ưu tiên CLB đó
                    out[an] = next(iter(own[g][an]))
            self.alias[g] = out

    @classmethod
    def load(cls, path: Path = CLUB_CSV) -> "ClubDirectory":
        rows: list[tuple[str, str, str]] = []
        try:
            with path.open(encoding="utf-8-sig", newline="") as f:
                rows = [(r["country"], r["canonical"], r["alias"]) for r in csv.DictReader(f)]
        except OSError:
            pass
        return cls(rows)

    def club_id(self, name: str | None, country: str | None) -> str | None:
        if not name or not country:
            return None
        g = COUNTRY_GROUP.get(country, country)
        cn = self.alias.get(g, {}).get(norm(name))
        return f"{g}|{cn}" if cn else None

    def canonical_name(self, club_id: str) -> str:
        g, cn = club_id.split("|", 1)
        return self.display.get(g, {}).get(cn, cn)


_DIRECTORY: ClubDirectory | None = None


def get_directory() -> ClubDirectory:
    global _DIRECTORY
    if _DIRECTORY is None:
        _DIRECTORY = ClubDirectory.load()
    return _DIRECTORY


class TeamResolver:
    """Nhận tên đội từ nguồn lịch sử, trả về id đội trong CSDL (tạo mới nếu không ghép được)."""

    def __init__(self, repo, new_provider: str = MAIN_PROVIDER):
        self.repo = repo
        self.new_provider = new_provider
        self.teams = repo.all_teams_min()
        self.countries: dict[int, set[str]] = repo.team_countries()
        self.dir = get_directory()
        self._unknown_only = False
        self._rebuild()
        self.created: list[str] = []
        self.fuzzy: list[tuple[str, str]] = []
        self._cache: dict[tuple, int] = {}
        self._scope: str | None = None

    def _rebuild(self) -> None:
        self.keys: dict[int, set[str]] = {}
        self.name_keys: dict[int, set[str]] = {}
        for t in self.teams:
            ks = {norm(t["name"]), norm(t.get("short_name")), norm(t.get("tla"))}
            self.keys[t["id"]] = {k for k in ks if k}
            self.name_keys[t["id"]] = {k for k in (norm(t["name"]), norm(t.get("short_name")))
                                       if k and len(k) >= 3 and not _tokens(k) <= GENERIC_TOKENS}
        self.names = {t["id"]: t["name"] for t in self.teams}
        self.reserve_ids = {t["id"] for t in self.teams if is_reserve(norm(t["name"]))}
        self._club_index: dict[str, set[int]] = {}
        self._team_cids: dict[int, set[str]] = {}
        for t in self.teams:
            self._index_team(t["id"], t)

    def _index_team(self, tid: int, team: dict | None = None) -> None:
        """Ghi nhận mã CLB chuẩn của đội (theo các nước đội đã đá) để tra nhanh."""
        team = team or next((t for t in self.teams if t["id"] == tid), None)
        if not team:
            return
        for country in self.countries.get(tid, ()):
            for nm in (team["name"], team.get("short_name")):
                cid = self.dir.club_id(nm, country)
                if cid:
                    self._club_index.setdefault(cid, set()).add(tid)
                    self._team_cids.setdefault(tid, set()).add(cid)

    def _allowed(self, form: str, tid: int) -> bool:
        """Đội dự bị chỉ ghép với đội dự bị, đội chính chỉ ghép với đội chính; cùng quốc gia; và không nằm trong danh sách cấm."""
        if is_reserve(form) != (tid in self.reserve_ids):
            return False
        if self._scope and self.countries.get(tid) and self._scope not in self.countries[tid]:
            return False
        if self._unknown_only and self._team_cids.get(tid):
            return False
        return not any(frozenset({form, k}) in DENY_PAIRS for k in self.keys[tid])

    def _exact(self, form: str) -> list[int]:
        return [tid for tid, ks in self.keys.items() if form in ks and self._in_scope(tid)
                and not (self._unknown_only and self._team_cids.get(tid))]

    def _in_scope(self, tid: int) -> bool:
        return not (self._scope and self.countries.get(tid) and self._scope not in self.countries[tid])

    def _subset(self, form: str) -> list[int]:
        """Tên nguồn ngắn hơn và là tập con các từ của tên đội (vd 'newcastle' ⊂ 'newcastle united')."""
        ft = _tokens(form)
        if not ft or len(form) < 4 or form in AMBIGUOUS_CITIES:
            return []
        out = []
        for tid, ks in self.keys.items():
            if not self._allowed(form, tid):
                continue
            # tên nguồn ngắn hơn tên đội ('newcastle' ⊂ 'newcastle united') hoặc dài hơn ('birmingham city' ⊃ 'birmingham')
            if any(ft <= _tokens(k) for k in ks) or any(_tokens(k) <= ft for k in self.name_keys[tid] if k not in AMBIGUOUS_CITIES):
                out.append(tid)
        return out

    def _close(self, form: str) -> list[int]:
        scored = []
        for tid, ks in self.keys.items():
            if not self._allowed(form, tid):
                continue
            best = max((difflib.SequenceMatcher(None, form, k).ratio() for k in ks), default=0)
            if best >= 0.88:
                scored.append((best, tid))
        scored.sort(reverse=True)
        if len(scored) >= 2 and scored[0][0] - scored[1][0] < 0.05:
            return []
        return [scored[0][1]] if scored else []

    def lookup(self, raw_name: str, country: str | None = None) -> int | None:
        """Tìm đội đã có trong CSDL; KHÔNG tạo đội mới. None nếu không chắc chắn. Có `country` thì chỉ xét đội của nước đó."""
        self._scope = country
        cid = self.dir.club_id(raw_name, country)
        if cid:                                          # 0) tên có trong bảng CLB chuẩn: ghép chắc chắn, không đoán
            hit = self._club_index.get(cid)
            if hit:
                return min(hit)
            self._unknown_only = True                    # CLB chuẩn chưa có trong CSDL: chỉ thử khớp với đội chưa có trong bảng
            try:
                return self._lookup_old(raw_name)
            finally:
                self._unknown_only = False
        return self._lookup_old(raw_name)

    def _lookup_old(self, raw_name: str) -> int | None:
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

    def resolve(self, raw_name: str, country: str | None = None) -> int:
        raw_name = (raw_name or "").strip()
        ck = (country, raw_name)
        if ck in self._cache:
            return self._cache[ck]
        tid = self.lookup(raw_name, country)
        if tid is None:                                  # 4) không chắc → tạo đội mới, báo lại
            base = norm(raw_name)
            cid = self.dir.club_id(raw_name, country)
            canon = self.dir.canonical_name(cid) if cid else ALIASES.get(base)   # tên chuẩn của CLB (bảng chuẩn) hoặc bí danh viết tay
            if canon and norm(canon) == norm(raw_name):
                canon = None
            # (cũ) tên viết tắt có bí danh ('Sheffield Weds') → nhớ luôn dạng đầy đủ để tên dài sau này khớp
            ext = f"hist:{base or raw_name.lower()}"
            if country and any(t["external_id"] == ext for t in self.teams):   # cùng tên nhưng khác nước (Santa Fe, Independiente...)
                ext = f"hist:{search_key(country).replace(' ', '-')}:{base}"
            tid = self.repo.upsert_team(self.new_provider, TeamDTO(external_id=ext, name=raw_name, short_name=canon))
            self.teams.append({"id": tid, "provider": self.new_provider, "external_id": ext, "name": raw_name,
                               "short_name": canon, "tla": None})
            if country:
                self.countries[tid] = {country}
            self._rebuild()
            self.created.append(raw_name)
        self._cache[ck] = tid
        if country:
            self.countries.setdefault(tid, set()).add(country)
            self._index_team(tid)
        return tid
