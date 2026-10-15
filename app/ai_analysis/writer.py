"""Module tùy chọn: nhờ AI viết bài nhận định tiếng Việt từ dữ liệu có cấu trúc đã được tính sẵn.

- Không bắt buộc: thiếu ANTHROPIC_API_KEY thì ứng dụng vẫn chạy, chỉ không có nút "Viết bài bằng AI".
- AI chỉ nhận một bản JSON đã kiểm chứng; prompt cấm bổ sung thông tin ngoài bản đó.
- Muốn dùng nhà cung cấp AI khác: viết lớp mới có phương thức `generate(payload) -> str`.
"""
from __future__ import annotations

import hashlib
import json
from typing import Protocol

import httpx

from ..config import Settings
from ..database.repository import Repository
from ..services.analysis_service import AnalysisService
from ..utils import to_iso, utcnow

SYSTEM_PROMPT = """Bạn là biên tập viên phân tích bóng đá, viết tiếng Việt, giọng văn khách quan.
Bạn CHỈ được dùng dữ liệu trong khối JSON do người dùng cung cấp.
TUYỆT ĐỐI KHÔNG thêm: kết quả trận đấu, chấn thương, treo giò, đội hình, phát biểu của huấn luyện viên, số liệu hay thông tin cầu thủ
không có trong JSON. Nếu một thông tin không có trong JSON, hãy nói rõ là "chưa có dữ liệu".
Không cam đoan kết quả; trình bày xác suất như xác suất. Phân biệt rõ dữ kiện (số liệu) và suy luận.
Cấu trúc bài (dùng tiêu đề Markdown ##): Tiêu đề (dòng # ở đầu), Tổng quan trận đấu, Phân tích phong độ,
So sánh sân nhà/sân khách, Lịch sử đối đầu, Ưu điểm và điểm yếu, Xác suất và tỷ số dự đoán,
Những yếu tố chưa chắc chắn, Kết luận."""


class AIError(Exception):
    pass


class ArticleWriter(Protocol):
    model: str

    def generate(self, payload: dict) -> str: ...


class AnthropicWriter:
    URL = "https://api.anthropic.com/v1/messages"

    def __init__(self, api_key: str, model: str, timeout: float = 90.0, transport: httpx.BaseTransport | None = None):
        self.api_key, self.model = api_key, model
        self._client = httpx.Client(timeout=timeout, transport=transport)

    def generate(self, payload: dict) -> str:
        body = {"model": self.model, "max_tokens": 2500, "system": SYSTEM_PROMPT,
                "messages": [{"role": "user", "content":
                              "Viết bài nhận định từ dữ liệu sau (JSON):\n" + json.dumps(payload, ensure_ascii=False)}]}
        try:
            resp = self._client.post(self.URL, json=body, headers={
                "x-api-key": self.api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
        except httpx.HTTPError as exc:
            raise AIError(f"Không kết nối được dịch vụ AI: {exc.__class__.__name__}.") from exc
        if resp.status_code == 401:
            raise AIError("Dịch vụ AI từ chối khóa API (401). Kiểm tra ANTHROPIC_API_KEY.")
        if resp.status_code == 429:
            raise AIError("Dịch vụ AI báo vượt giới hạn (429). Thử lại sau.")
        if resp.status_code != 200:
            raise AIError(f"Dịch vụ AI trả về lỗi HTTP {resp.status_code}.")
        try:
            text = "".join(b.get("text", "") for b in resp.json().get("content", []) if b.get("type") == "text").strip()
        except ValueError as exc:
            raise AIError("Phản hồi AI không hợp lệ.") from exc
        if not text:
            raise AIError("AI không trả về nội dung.")
        return text


def build_payload(analysis: dict) -> dict:
    """Bản dữ liệu có cấu trúc gửi cho AI — chỉ chứa những gì đã được tính từ dữ liệu thật."""
    m = analysis["match"]

    def form(f):
        return {"summary": f["summary"], "form_string": f["form_string"],
                "games": [{k: g[k] for k in ("utc_date", "venue", "opponent", "gf", "ga", "result")} for g in f["games"]]}

    pred = analysis["prediction"]
    return {
        "match": {"league": m["league_name"], "home": m["home_name"], "away": m["away_name"], "kickoff_utc": m["utc_date"],
                  "status": m["status"], "matchday": m["matchday"], "season": m["season"]},
        "form": {"home": form(analysis["form"]["home"]), "away": form(analysis["form"]["away"])},
        "venue": {"home_at_home": analysis["venue"]["home"]["summary"], "away_away": analysis["venue"]["away"]["summary"]},
        "head_to_head": {"summary": analysis["head_to_head"]["summary"],
                         "games": analysis["head_to_head"]["games"]},
        "prediction": ({k: pred[k] for k in ("percent", "lambda_home", "lambda_away", "predicted_score", "top_scores",
                                              "quality", "factors") if k in pred} if pred.get("available")
                       else {"available": False, "reason": pred.get("reason")}),
        "conclusions": analysis["conclusions"],
        "not_available": analysis["advanced"].get("reason") if not analysis["advanced"]["available"] else None,
    }


def payload_hash(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


class ArticleService:
    def __init__(self, repo: Repository, analysis: AnalysisService, settings: Settings,
                 writer: ArticleWriter | None = None):
        self.repo, self.analysis, self.settings = repo, analysis, settings
        self._writer = writer

    @property
    def writer(self) -> ArticleWriter | None:
        if self._writer is not None:
            return self._writer
        if self.settings.ai_configured:
            return AnthropicWriter(self.settings.anthropic_api_key, self.settings.ai_model)
        return None

    def available(self) -> bool:
        return self.writer is not None

    def latest(self, match_id: int) -> dict | None:
        article = self.repo.latest_article(match_id)
        if not article:
            return None
        current = self._current_hash(match_id)
        article["is_stale"] = current is not None and current != article["data_hash"]
        return article

    def _current_hash(self, match_id: int) -> str | None:
        analysis = self.analysis.build(match_id)
        return payload_hash(build_payload(analysis)) if analysis else None

    def generate(self, match_id: int, force: bool = False) -> dict:
        writer = self.writer
        if writer is None:
            raise AIError("Chưa cấu hình ANTHROPIC_API_KEY nên chưa thể viết bài bằng AI.")
        analysis = self.analysis.build(match_id)
        if analysis is None:
            raise LookupError("Không tìm thấy trận đấu.")
        payload = build_payload(analysis)
        h = payload_hash(payload)
        latest = self.repo.latest_article(match_id)
        if latest and latest["data_hash"] == h and not force:
            return {**latest, "is_stale": False, "cached": True}
        content = writer.generate(payload)
        self.repo.save_article(match_id, content, writer.model, h, payload)
        return {**self.repo.latest_article(match_id), "is_stale": False, "cached": False}
