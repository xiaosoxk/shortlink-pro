"""限流中间件行为测试：内存令牌桶阈值触发 429。"""
import pytest
from httpx import ASGITransport, AsyncClient

from tests.conftest import make_settings


@pytest.fixture
async def tight_client(tmp_path):
    """API 每分钟只放行 3 次的独立 app。"""
    from app.main import create_app

    settings = make_settings(
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'rl.db').as_posix()}",
        rate_limit_api_per_minute=3,
    )
    application = create_app(settings)
    async with application.router.lifespan_context(application):
        transport = ASGITransport(app=application)
        async with AsyncClient(transport=transport, base_url="http://testserver") as c:
            yield c


class TestTokenBucket:
    async def test_429_after_threshold_with_retry_after(self, tight_client):
        # 1 注册 + 2 登录 = 3 次调用，第 4 次必须 429
        assert (
            await tight_client.post(
                "/api/auth/register", json={"username": "rlimit", "password": "password123"}
            )
        ).status_code == 201
        login = await tight_client.post(
            "/api/auth/login", json={"username": "rlimit", "password": "password123"}
        )
        assert login.status_code == 200
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        create = await tight_client.post(
            "/api/links", json={"target_url": "https://example.com"}, headers=headers
        )
        assert create.status_code == 201

        blocked = await tight_client.post(
            "/api/links", json={"target_url": "https://example.com/2"}, headers=headers
        )
        assert blocked.status_code == 429
        assert "retry-after" in blocked.headers
        assert blocked.json()["detail"] == "Too Many Requests"

    async def test_health_not_limited(self, client):
        for _ in range(10):
            assert (await client.get("/health")).status_code == 200
