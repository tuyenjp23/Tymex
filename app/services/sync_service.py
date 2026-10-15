"""Đồng bộ dữ liệu từ nhà cung cấp vào database, có cache theo thời gian, nhật ký và trạng thái tiến độ."""
from __future__ import annotations

import threading
from datetime import timedelta
from typing import Callable

from ..config import Settings
from ..data_providers.base import (
    FootballDataProvider, ProviderAccessError, ProviderAuthError, ProviderError, ProviderNotConfigured,
    ProviderRateLimitError,
)
from ..database.repository import Repository
from ..utils import parse_iso, to_iso, utcnow
from .prediction_service import PredictionService


class SyncService:
    def __init__(self, repo: Repository, provider: FootballDataProvider, settings: Settings,
                 predictions: PredictionService | None = None, now: Callable = utcnow):
        self.repo, self.provider, self.settings, self.predictions, self.now = repo, provider, settings, predictions, now
        self._lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._state: dict = {"running": False, "started_at": None, "finished_at": None, "leagues": [], "summary": None}

    # ------------------------------------------------------------------ trạng thái
    def status(self) -> dict:
        with self._state_lock:
            return {**self._state, "leagues": [dict(x) for x in self._state["leagues"]]}

    def _set(self, **kw) -> None:
        with self._state_lock:
            self._state.update(kw)

    def _update_league(self, code: str, **kw) -> None:
        with self._state_lock:
            for row in self._state["leagues"]:
                if row["code"] == code:
                    row.update(kw)

    # ------------------------------------------------------------------ chạy
    def start_background(self, force: bool = False) -> bool:
        """Chạy đồng bộ ở luồng nền. False nếu đang có một lần đồng bộ khác chạy."""
        if self._lock.locked():
            return False
        threading.Thread(target=self.run, kwargs={"force": force}, daemon=True, name="sync").start()
        return True

    def run(self, force: bool = False) -> dict:
        if not self._lock.acquire(blocking=False):
            return {"ok": False, "error_code": "already_running", "message": "Đang có một lần đồng bộ khác chạy."}
        try:
            codes = self.settings.league_codes
            self._set(running=True, started_at=to_iso(self.now()), finished_at=None, summary=None,
                      leagues=[{"code": c, "state": "pending", "message": "", "matches": 0} for c in codes])
            try:
                summary = self._run_all(codes, force)
            except Exception as exc:  # không để luồng nền chết âm thầm
                summary = {"ok": False, "error_code": "internal_error", "message": f"Lỗi nội bộ: {exc}"}
            self._set(running=False, finished_at=to_iso(self.now()), summary=summary)
            return summary
        finally:
            self._lock.release()

    def _run_all(self, codes: list[str], force: bool) -> dict:
        if not self.provider.is_configured():
            for c in codes:
                self._update_league(c, state="error", message="Chưa cấu hình khóa API.")
            return {"ok": False, "error_code": ProviderNotConfigured.code,
                    "message": "Chưa cấu hình FOOTBALL_DATA_API_KEY. Hãy vào trang Cài đặt để nhập khóa."}
        total, ok_count, errors, abort = 0, 0, [], None
        for code in codes:
            if abort:
                self._update_league(code, state="skipped", message="Bỏ qua do lỗi trước đó.")
                continue
            try:
                result = self.sync_league(code, force)
            except (ProviderAuthError, ProviderRateLimitError, ProviderNotConfigured) as exc:
                abort = exc
                errors.append(f"{code}: {exc}")
                self._update_league(code, state="error", message=str(exc))
                continue
            except ProviderError as exc:
                errors.append(f"{code}: {exc}")
                self._update_league(code, state="error", message=str(exc))
                continue
            if result["status"] == "ok":
                ok_count += 1
                total += result["matches"]
        extra = {}
        if self.predictions and ok_count:
            try:
                extra["predictions_created"] = self.predictions.generate_upcoming()
                extra["results_scored"] = self.predictions.resolve_results()
            except Exception as exc:
                errors.append(f"Dự đoán: {exc}")
        ok = not errors
        return {"ok": ok, "leagues_synced": ok_count, "matches": total, "errors": errors,
                "error_code": abort.code if abort else (None if ok else "partial_failure"),
                "message": "Đồng bộ hoàn tất." if ok else "Đồng bộ xong một phần, có lỗi: " + " | ".join(errors), **extra}

    def sync_league(self, code: str, force: bool = False) -> dict:
        name = self.provider.name
        last = self.repo.last_successful_sync(name, code)
        if not force and last:
            age = self.now() - parse_iso(last)
            if age < timedelta(minutes=self.settings.min_sync_interval_minutes):
                self.repo.finish_sync_log(self.repo.start_sync_log(name, code), "skipped",
                                          message=f"Dữ liệu còn mới ({int(age.total_seconds() // 60)} phút trước).")
                self._update_league(code, state="skipped", message="Dữ liệu còn mới, không gọi lại API.")
                return {"status": "skipped", "matches": 0}
        log_id = self.repo.start_sync_log(name, code)
        self._update_league(code, state="running", message="Đang tải lịch thi đấu...")
        try:
            league, matches = self.provider.get_matches(code, None)
            league_id = self.repo.upsert_league(name, league)
            count = self.repo.upsert_matches(name, league_id, matches)
            notes = []

            prev = (league.current_season - 1) if league.current_season else None
            if self.settings.sync_previous_season and prev and not self.repo.has_matches(league_id, prev):
                self._update_league(code, message="Đang tải mùa giải trước...")
                try:
                    _, prev_matches = self.provider.get_matches(code, prev)
                    count += self.repo.upsert_matches(name, league_id, prev_matches)
                except ProviderAccessError:
                    notes.append("Gói API hiện tại không cho tải mùa trước.")

            self._update_league(code, message="Đang tải bảng xếp hạng...")
            try:
                season, rows = self.provider.get_standings(code)
                self.repo.replace_standings(league_id, name, season, rows)
            except ProviderAccessError:
                notes.append("Không có quyền tải bảng xếp hạng.")

            msg = " ".join(notes) or f"Đã lưu {count} trận."
            self.repo.finish_sync_log(log_id, "ok", matches=count, message=msg)
            self._update_league(code, state="ok", message=msg, matches=count)
            return {"status": "ok", "matches": count}
        except ProviderAccessError as exc:
            self.repo.finish_sync_log(log_id, "error", error_code=exc.code, message=str(exc))
            self._update_league(code, state="error", message=str(exc))
            raise
        except ProviderError as exc:
            self.repo.finish_sync_log(log_id, "error", error_code=exc.code, message=str(exc))
            self._update_league(code, state="error", message=str(exc))
            raise
