"""测试基建：每个用例独立的 app + 独立 SQLite + 内存后端。

不依赖真实服务器与真实 Redis —— ASGITransport 在进程内跑完整 ASGI 栈
（含中间件），这是 FastAPI 官方推荐的现代测试姿势。
"""
import pytest
from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.main import create_app

TEST_SETTINGS = dict(
    environment="test",
    database_url="sqlite+aiosqlite:///./test-shortlink.db",
    redis_url="",
    secret_key="test-secret",
    public_base_url="http://test",
    password_pbkdf2_iterations=1000,
    click_flush_interval=0.05,
    click_flush_batch=5,
    stats_default_window_hours=168,
)


def make_settings(**overrides) -> Settings:
    return Settings(**{**TEST_SETTINGS, **overrides})


@pytest.fixture
async def app(tmp_path):
    settings = make_settings(database_url=f"sqlite+aiosqlite:///{(tmp_path / 't.db').as_posix()}")
    application = create_app(settings)
    async with application.router.lifespan_context(application):
        yield application


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


async def register_and_login(client, username="alice", password="password123") -> str:
    await client.post("/api/auth/register", json={"username": username, "password": password})
    resp = await client.post(
        "/api/auth/login", json={"username": username, "password": password}
    )
    return resp.json()["access_token"]


@pytest.fixture
async def auth_headers(client):
    token = await register_and_login(client)
    return {"Authorization": f"Bearer {token}"}
