"""系统接口：健康检查 / Prometheus 指标 / 前端 dashboard。"""
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, PlainTextResponse
from sqlalchemy import text

router = APIRouter(tags=["system"])

STATIC_DIR = Path(__file__).resolve().parents[2] / "static"


@router.get("/", include_in_schema=False)
async def dashboard() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@router.get("/health", response_model_exclude_none=True)
async def health(request: Request) -> dict:
    state = request.app.state
    db_status = "ok"
    try:
        async with state.session_factory() as session:
            await session.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001
        db_status = "error"
    body = {
        "status": "ok" if db_status == "ok" else "degraded",
        "environment": state.settings.environment,
        "cache": type(state.cache).__name__,
        "limiter": type(state.limiter).__name__,
        "lock": type(state.locks).__name__,
        "click_queue_depth": state.analytics.queue.qsize(),
    }
    return body


@router.get("/metrics", response_class=PlainTextResponse)
async def metrics(request: Request) -> PlainTextResponse:
    state = request.app.state
    gauges = {
        "click_queue_depth": float(state.analytics.queue.qsize()),
        "ws_connections": float(state.ws.connections()),
        "cache_entries": float(state.cache.size()),
    }
    return PlainTextResponse(state.metrics.render(gauges), media_type="text/plain")
