"""应用工厂 + lifespan（启动/优雅停机编排）。

为什么用工厂函数 create_app 而不是裸 app？
1. 测试可注入独立 Settings（独立 SQLite/限流阈值），互不污染；
2. engine、缓存、限流器等有状态对象全部在 lifespan 里创建并挂到
   app.state，模块导入零副作用 —— 这就是十二要素应用的"可丢弃性"。

优雅停机顺序（面试考点）：
停止消费者任务 -> flush 残余点击缓冲 -> 关闭缓存/限流连接 -> dispose 引擎池。
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.cache import create_cache
from app.core.lock import create_lock_backend
from app.core.logging_conf import configure_logging
from app.core.metrics import Metrics
from app.core.ratelimit import create_limiter
from app.core.snowflake import Snowflake
from app.database import build_engine, build_session_factory
from app.middleware import RateLimitMiddleware, RequestContextMiddleware
from app.routers import auth, links, system
from app.services.analytics import AnalyticsService
from app.services.link_service import LinkService
from app.ws import ConnectionManager, router as ws_router

logger = logging.getLogger(__name__)


def create_app(settings=None) -> FastAPI:
    from app.config import Settings

    settings = settings or Settings()
    configure_logging(settings.environment)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine = build_engine(settings.database_url)
        async with engine.begin() as conn:
            from app.models import Base

            # 演示项目用 create_all；生产应使用 Alembic 迁移管理 schema
            await conn.run_sync(Base.metadata.create_all)

        app.state.settings = settings
        app.state.engine = engine
        app.state.session_factory = build_session_factory(engine)
        app.state.metrics = Metrics()
        app.state.cache = await create_cache(settings.redis_url)
        app.state.limiter = await create_limiter(settings.redis_url)
        app.state.locks = await create_lock_backend(settings.redis_url)
        app.state.snowflake = Snowflake(settings.machine_id)
        app.state.ws = ConnectionManager()
        app.state.analytics = AnalyticsService(
            app.state.session_factory, settings, app.state.metrics
        )
        app.state.links = LinkService(
            app.state.cache,
            app.state.locks,
            app.state.snowflake,
            app.state.analytics,
            settings,
        )
        await app.state.analytics.start()
        logger.info(
            "%s started (env=%s, cache=%s, limiter=%s, lock=%s)",
            settings.app_name,
            settings.environment,
            type(app.state.cache).__name__,
            type(app.state.limiter).__name__,
            type(app.state.locks).__name__,
        )
        yield
        await app.state.analytics.stop()
        await app.state.cache.close()
        await app.state.limiter.close()
        await app.state.locks.close()
        await engine.dispose()
        logger.info("shutdown complete")

    app = FastAPI(
        title=settings.app_name,
        version="1.0.0",
        description="面试演示项目：短链接全栈服务（FastAPI + SQLAlchemy 2.0 async + Redis 可选）",
        lifespan=lifespan,
    )
    app.state.settings = settings  # lifespan 之前中间件/路由也可能读

    # add_middleware 顺序 = 后加的在外层；RequestContext 必须最外层（含限流日志）
    app.add_middleware(RateLimitMiddleware, settings=settings)
    app.add_middleware(RequestContextMiddleware)

    app.include_router(system.router)
    app.include_router(auth.router)
    app.include_router(links.router)
    app.include_router(ws_router)
    return app


app = create_app()
