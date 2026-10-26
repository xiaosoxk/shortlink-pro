"""数据库基建。

注意：engine 不做成模块级全局变量，而是在 create_app 的 lifespan 里按
Settings 创建并挂到 app.state —— 这样测试可以为每个用例创建独立数据库。
"""
from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.models import Base  # noqa: F401  (re-export 便于 alembic 迁移引用)


def build_engine(database_url: str):
    return create_async_engine(database_url, pool_pre_ping=True)


def build_session_factory(engine) -> async_sessionmaker[AsyncSession]:
    # expire_on_commit=False：commit 后属性仍可用，避免异步环境下意外触发
    # 惰性加载（惰性 IO 在事件循环里会阻塞或直接报错）
    return async_sessionmaker(engine, expire_on_commit=False)


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """FastAPI 依赖：每请求一个 Session，请求结束自动归还连接池。

    注意 request 必须带类型注解：FastAPI 只认类型，无注解参数会被
    当成必需的 query 参数（一个隐蔽但经典的坑）。
    """
    async with request.app.state.session_factory() as session:
        yield session
