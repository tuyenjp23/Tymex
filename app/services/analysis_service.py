"""Gom số liệu, dự đoán và kết luận thành một bản phân tích hoàn chỉnh cho một trận."""
from __future__ import annotations

from ..analytics.availability import build_availability_block
from ..analytics.conclusions import build_conclusions
from ..analytics.stats import head_to_head, team_form, venue_stats
from ..database.repository import Repository
from ..odds.compare import build_market_block
from ..utils import to_iso
from .prediction_service import PredictionService

DATA_SCOPE_NOTE = "Chỉ tính các trận thuộc những giải đã đồng bộ vào hệ thống và đã kết thúc trước giờ bóng lăn của trận này."


class AnalysisService:
    def __init__(self, repo: Repository, predictions: PredictionService):
        self.repo, self.predictions = repo, predictions

    def build(self, match_id: int, form_n: int = 5) -> dict | None:
        match = self.repo.get_match(match_id)
        if not match:
            return None
        form_n = 10 if form_n >= 10 else 5
        kickoff = match["utc_date"]
        home_id, away_id = match["home_team_id"], match["away_team_id"]
        # Một lần truy vấn: mọi trận đã kết thúc của hai đội, TRƯỚC giờ bóng lăn (không có dữ liệu tương lai).
        pool = self.repo.finished_matches(team_ids=[home_id, away_id], before=kickoff, limit=600)

        home_form = team_form(pool, home_id, kickoff, form_n, exclude_id=match["id"])
        away_form = team_form(pool, away_id, kickoff, form_n, exclude_id=match["id"])
        home_venue = venue_stats(pool, home_id, "home", kickoff, 10, exclude_id=match["id"])
        away_venue = venue_stats(pool, away_id, "away", kickoff, 10, exclude_id=match["id"])
        h2h = head_to_head(pool, home_id, away_id, kickoff, 10, exclude_id=match["id"])
        prediction = self._prediction_block(match)
        advanced = self._advanced(match)
        market = self._market(match, prediction)
        availability = build_availability_block(self.repo.get_absences(match["id"]), prediction, match,
                                                upcoming=self.predictions.is_upcoming(match))
        conclusions = build_conclusions(match["home_name"], match["away_name"], home_form, away_form, home_venue,
                                        away_venue, h2h, prediction, advanced["available"])
        return {
            "match": match, "form_n": form_n, "data_scope_note": DATA_SCOPE_NOTE,
            "form": {"home": home_form, "away": away_form},
            "venue": {"home": home_venue, "away": away_venue},
            "head_to_head": h2h, "advanced": advanced, "prediction": prediction, "market": market, "availability": availability, "conclusions": conclusions,
            "is_test_data": match["provider"] == "fixture",
        }

    # ------------------------------------------------------------------ dự đoán
    def _prediction_block(self, match: dict) -> dict:
        if self.predictions.is_upcoming(match):
            stored = self.predictions.ensure_stored(match)
            if stored:
                block = dict(stored["details"])
                block.update(mode="stored_pre_match", created_at=stored["created_at"], prediction_id=stored["id"],
                             label="Dự đoán đã lưu trước trận")
                return block
            out, _ = self.predictions.compute(match)
            out["mode"] = "unavailable"
            return out
        # Trận đã/đang diễn ra: ưu tiên bản dự đoán đã lưu TRƯỚC giờ bóng lăn.
        stored = self.repo.latest_prediction(match["id"], "live", before=match["utc_date"])
        if stored:
            block = dict(stored["details"])
            block.update(mode="stored_pre_match", created_at=stored["created_at"], prediction_id=stored["id"],
                         label="Dự đoán đã lưu trước trận")
            return block
        out, _ = self.predictions.compute(match)
        out["mode"] = "recomputed_pre_match"
        out["label"] = ("Tính lại sau trận bằng dữ liệu có trước giờ bóng lăn. Đây KHÔNG phải dự đoán đã được lưu "
                        "trước trận nên không được đưa vào thống kê độ chính xác.")
        out["created_at"] = to_iso(self.predictions.now())
        return out

    def _market(self, match: dict, prediction: dict) -> dict:
        """So sánh với tỷ lệ cược (nếu có). Trận đã đá dùng tỷ lệ cược lúc đóng cửa nếu đã nhập từ football-data.co.uk."""
        return build_market_block(self.repo.get_odds(match["id"]), prediction, match["home_name"], match["away_name"])

    def _advanced(self, match: dict) -> dict:
        stats = self.repo.get_match_statistics(match["id"])
        if not stats:
            return {"available": False,
                    "reason": "Nguồn dữ liệu hiện tại không cung cấp xG, cú sút, kiểm soát bóng, cơ hội tạo ra hay đội hình dự kiến "
                              "(tin chấn thương/vắng mặt, nếu có, nằm ở khối riêng). Hệ thống không suy đoán các thông tin này."}
        return {"available": True, "stats": stats}
