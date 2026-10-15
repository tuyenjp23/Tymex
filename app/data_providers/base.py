"""Giao diện chung cho mọi nhà cung cấp dữ liệu bóng đá.

Phần phân tích/dự đoán chỉ làm việc với các DTO dưới đây, không biết gì về định dạng JSON của API cụ thể.
Muốn đổi nhà cung cấp (ví dụ API-Football): viết một lớp mới kế thừa `FootballDataProvider`.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class TeamDTO:
    external_id: str
    name: str
    short_name: str | None = None
    tla: str | None = None
    crest_url: str | None = None


@dataclass(frozen=True)
class LeagueDTO:
    code: str
    name: str
    country: str | None = None
    type: str | None = None
    emblem_url: str | None = None
    current_season: int | None = None


@dataclass(frozen=True)
class MatchDTO:
    external_id: str
    season: int | None
    matchday: int | None
    stage: str | None
    utc_date: str               # ISO 8601 UTC: YYYY-MM-DDTHH:MM:SSZ
    status: str                 # SCHEDULED | TIMED | IN_PLAY | PAUSED | FINISHED | POSTPONED | SUSPENDED | CANCELLED | AWARDED
    home: TeamDTO
    away: TeamDTO
    home_score: int | None = None
    away_score: int | None = None
    home_ht: int | None = None
    away_ht: int | None = None
    winner: str | None = None   # HOME_TEAM | AWAY_TEAM | DRAW | None


@dataclass(frozen=True)
class StandingDTO:
    group_name: str | None
    position: int
    team: TeamDTO
    played: int
    won: int
    draw: int
    lost: int
    points: int
    goals_for: int
    goals_against: int
    goal_diff: int
    form: str | None = None


class ProviderError(Exception):
    """Lỗi chung khi lấy dữ liệu. `code` dùng để phân loại lỗi trên giao diện và trong nhật ký."""
    code = "provider_error"


class ProviderNotConfigured(ProviderError):
    code = "not_configured"


class ProviderAuthError(ProviderError):
    code = "auth_error"


class ProviderAccessError(ProviderError):
    """Khóa hợp lệ nhưng gói hiện tại không được phép truy cập dữ liệu này (HTTP 403/404)."""
    code = "access_denied"


class ProviderRateLimitError(ProviderError):
    code = "rate_limited"


class ProviderConnectionError(ProviderError):
    code = "connection_error"


class ProviderResponseError(ProviderError):
    code = "bad_response"


class FootballDataProvider(ABC):
    name: str = "unknown"

    @abstractmethod
    def is_configured(self) -> bool: ...

    def set_api_key(self, api_key: str) -> None:
        """Cập nhật khóa khi người dùng nhập trên trang Cài đặt (nhà cung cấp không dùng khóa có thể bỏ qua)."""

    @abstractmethod
    def get_matches(self, code: str, season: int | None = None) -> tuple[LeagueDTO, list[MatchDTO]]:
        """Toàn bộ trận của một giải trong một mùa (season = năm bắt đầu mùa; None = mùa hiện tại)."""

    @abstractmethod
    def get_standings(self, code: str) -> tuple[int | None, list[StandingDTO]]:
        """Trả về (năm bắt đầu mùa, các dòng bảng xếp hạng)."""
