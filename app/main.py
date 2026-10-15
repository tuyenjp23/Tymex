"""Điểm vào của ứng dụng: lắp ráp các module và phục vụ giao diện web."""
from __future__ import annotations

import threading
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .ai_analysis.writer import ArticleService
from .api.routes import router
from .config import BASE_DIR, Settings, load_settings
from .data_providers.base import FootballDataProvider
from .data_providers.football_data_org import FootballDataOrgProvider, RateLimiter
from .database.db import Database
from .database.repository import Repository
from .prediction.poisson import ModelParams
from .services.analysis_service import AnalysisService
from .services.prediction_service import PredictionService
from .services.sync_service import SyncService

FRONTEND_DIR = BASE_DIR / "frontend"


@dataclass
class Container:
    settings: Settings
    db: Database
    repo: Repository
    provider: FootballDataProvider
    predictions: PredictionService
    analysis: AnalysisService
    sync: SyncService
    articles: ArticleService


def build_container(settings: Settings, provider: FootballDataProvider | None = None, writer=None) -> Container:
    db = Database(settings.database_path)
    db.init()
    repo = Repository(db)
    provider = provider or FootballDataOrgProvider(
        settings.football_data_api_key, timeout=settings.request_timeout,
        rate_limiter=RateLimiter(max_calls=settings.rate_limit_per_minute))
    predictions = PredictionService(repo, ModelParams())
    analysis = AnalysisService(repo, predictions)
    sync = SyncService(repo, provider, settings, predictions)
    articles = ArticleService(repo, analysis, settings, writer)
    return Container(settings, db, repo, provider, predictions, analysis, sync, articles)


def _auto_sync_loop(container: Container, stop: threading.Event) -> None:
    minutes = container.settings.auto_sync_minutes
    while not stop.wait(minutes * 60):
        if container.provider.is_configured():
            container.sync.run(force=False)


def create_app(settings: Settings | None = None, provider: FootballDataProvider | None = None, writer=None,
               start_scheduler: bool = True) -> FastAPI:
    settings = settings or load_settings()
    container = build_container(settings, provider, writer)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        stop = threading.Event()
        if start_scheduler and settings.auto_sync_minutes > 0:
            threading.Thread(target=_auto_sync_loop, args=(container, stop), daemon=True, name="auto-sync").start()
        yield
        stop.set()

    app = FastAPI(title="Personal Football Analytics", lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.state.container = container
    app.include_router(router)

    @app.exception_handler(HTTPException)
    async def http_error(_: Request, exc: HTTPException):
        detail = exc.detail if isinstance(exc.detail, dict) else {"code": "http_error", "message": str(exc.detail)}
        return JSONResponse({"error": detail}, status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError):
        first = exc.errors()[0] if exc.errors() else {}
        loc = ".".join(str(x) for x in first.get("loc", []) if x != "query")
        return JSONResponse({"error": {"code": "invalid_input", "message": f"Dữ liệu đầu vào không hợp lệ ({loc}): {first.get('msg', '')}"}},
                            status_code=422)

    @app.middleware("http")
    async def no_cache_api(request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    if FRONTEND_DIR.exists():
        app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
    return app


def app_factory() -> FastAPI:
    return create_app()
