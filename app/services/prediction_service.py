"""Điều phối mô hình dự đoán với database: lưu dự đoán trước trận, chấm điểm sau trận, kiểm tra lại (backtest)."""
from __future__ import annotations

from datetime import timedelta
from typing import Callable

from ..database.repository import Repository
from ..prediction.evaluation import evaluate_prediction, summarize_results
from ..prediction.poisson import MODEL_VERSION, ModelParams, predict
from ..utils import parse_iso, to_iso, utcnow

UPCOMING = ("SCHEDULED", "TIMED")


class PredictionService:
    def __init__(self, repo: Repository, params: ModelParams = ModelParams(), now: Callable = utcnow):
        self.repo, self.params, self.now = repo, params, now

    # ------------------------------------------------------------------ tính toán
    def _league_matches(self, match: dict) -> list[dict]:
        since = to_iso(parse_iso(match["utc_date"]) - timedelta(days=self.params.lookback_days))
        return self.repo.finished_matches(league_id=match["league_id"], before=match["utc_date"], since=since)

    def compute(self, match: dict, league_matches: list[dict] | None = None) -> tuple[dict, str]:
        """Dự đoán chỉ bằng dữ liệu TRƯỚC giờ bóng lăn của `match`. Trả về (kết quả, dấu vân tay dữ liệu)."""
        pool = league_matches if league_matches is not None else self._league_matches(match)
        out = predict(pool, match["home_team_id"], match["away_team_id"], match["utc_date"],
                      match["home_name"], match["away_name"], self.params)
        latest = max((m["utc_date"] for m in pool), default="none")
        return out, f"{len(pool)}:{latest}:{MODEL_VERSION}"

    # ------------------------------------------------------------------ lưu dự đoán trước trận
    def is_upcoming(self, match: dict) -> bool:
        return match["status"] in UPCOMING and match["utc_date"] > to_iso(self.now())

    def ensure_stored(self, match: dict, league_matches: list[dict] | None = None) -> dict | None:
        """Tạo và lưu dự đoán 'live' cho trận chưa bắt đầu, chỉ khi dữ liệu đầu vào đã thay đổi so với bản lưu gần nhất.
        Không bao giờ ghi đè hoặc xóa bản cũ. Trả về dòng dự đoán mới nhất (hoặc None nếu không đủ dữ liệu)."""
        if not self.is_upcoming(match):
            return self.repo.latest_prediction(match["id"], "live", before=match["utc_date"])
        out, fp = self.compute(match, league_matches)
        last = self.repo.latest_prediction(match["id"], "live")
        if not out.get("available"):
            return last
        if last and last["data_fingerprint"] == fp:
            return last
        self.repo.save_prediction(match["id"], "live", MODEL_VERSION, to_iso(self.now()), fp, out)
        return self.repo.latest_prediction(match["id"], "live")

    def generate_upcoming(self, days: int = 7) -> int:
        """Sau mỗi lần đồng bộ: tạo dự đoán cho các trận trong `days` ngày tới."""
        now = self.now()
        matches = self.repo.query_matches(date_from=to_iso(now), date_to=to_iso(now + timedelta(days=days)),
                                          statuses=UPCOMING, limit=500)
        created = 0
        for m in matches:
            before = self.repo.count_predictions("live")
            self.ensure_stored(m)
            created += self.repo.count_predictions("live") - before
        return created

    # ------------------------------------------------------------------ chấm điểm
    def resolve_results(self) -> int:
        """Chấm điểm các dự đoán 'live' (tạo trước giờ bóng lăn) của những trận đã có kết quả."""
        n = 0
        for row in self.repo.finished_matches_with_unscored_live_prediction():
            match = self.repo.get_match(row["match_id"])
            pred = self.repo.latest_prediction(match["id"], "live", before=match["utc_date"])
            if not pred:
                continue
            self.repo.save_result(pred["id"], match["id"], evaluate_prediction(pred, match["home_score"], match["away_score"]))
            n += 1
        return n

    # ------------------------------------------------------------------ kiểm tra lại trên trận cũ
    def backtest(self, league_id: int | None = None, limit: int = 100) -> dict:
        """Dự đoán lại các trận ĐÃ KẾT THÚC bằng đúng dữ liệu có trước giờ bóng lăn của từng trận.
        Lưu với kind='backtest' và tách riêng khỏi dự đoán thật; created_at là hiện tại nên KHÔNG tính là dự đoán trước trận."""
        finished = self.repo.finished_matches(league_id=league_id, limit=limit)
        done = skipped = 0
        for m in finished:
            if self.repo.has_prediction(m["id"], "backtest", MODEL_VERSION):
                continue
            out, fp = self.compute(m)
            if not out.get("available"):
                skipped += 1
                continue
            pid = self.repo.save_prediction(m["id"], "backtest", MODEL_VERSION, to_iso(self.now()), fp, out)
            pred = self.repo.latest_prediction(m["id"], "backtest")
            self.repo.save_result(pid, m["id"], evaluate_prediction(pred, m["home_score"], m["away_score"]))
            done += 1
        return {"evaluated": done, "skipped_insufficient_data": skipped, "considered": len(finished)}

    def summary(self, kind: str) -> dict:
        s = summarize_results(self.repo.result_rows(kind))
        s["kind"] = kind
        s["total_predictions"] = self.repo.count_predictions(kind)
        return s
