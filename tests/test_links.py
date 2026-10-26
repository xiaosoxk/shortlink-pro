"""短链全流程接口测试：创建 -> 跳转 -> 统计 -> 删除，含缓存行为。"""
import asyncio
import time

from sqlalchemy import update

from app.models import Link, utcnow


class TestCreate:
    async def test_create_returns_base62_code(self, client, auth_headers):
        resp = await client.post(
            "/api/links",
            json={"target_url": "https://example.com/docs"},
            headers=auth_headers,
        )
        assert resp.status_code == 201
        body = resp.json()
        assert 8 <= len(body["code"]) <= 12  # base62(snowflake)
        assert body["short_url"].endswith("/" + body["code"])
        assert body["target_url"].rstrip("/") == "https://example.com/docs"
        assert body["click_count"] == 0

    async def test_custom_alias_and_conflict(self, client, auth_headers):
        payload = {"target_url": "https://example.com", "custom_alias": "my-docs"}
        assert (
            await client.post("/api/links", json=payload, headers=auth_headers)
        ).status_code == 201
        resp = await client.post("/api/links", json=payload, headers=auth_headers)
        assert resp.status_code == 409

    async def test_requires_auth(self, client):
        resp = await client.post("/api/links", json={"target_url": "https://example.com"})
        assert resp.status_code == 401

    async def test_invalid_url_422(self, client, auth_headers):
        resp = await client.post(
            "/api/links", json={"target_url": "not-a-url"}, headers=auth_headers
        )
        assert resp.status_code == 422


class TestRedirect:
    async def _create(self, client, headers, **extra):
        resp = await client.post(
            "/api/links",
            json={"target_url": "https://example.com/page", **extra},
            headers=headers,
        )
        return resp.json()

    async def test_redirect_302_and_click_counted(self, client, app, auth_headers):
        link = await self._create(client, auth_headers)
        resp = await client.get(f"/{link['code']}", follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["location"].startswith("https://example.com")
        assert resp.headers["x-request-id"]  # 中间件注入链路 ID

        await asyncio.sleep(0.3)  # 等待批写 flush
        detail = await client.get(f"/api/links/{link['code']}", headers=auth_headers)
        assert detail.json()["click_count"] == 1

    async def test_unknown_code_404_then_negative_cache(self, client, app):
        resp = await client.get("/zzzzzz9999", follow_redirects=False)
        assert resp.status_code == 404
        # 第二次直接命中负缓存（防穿透），不再查库 —— 通过指标可观测
        resp2 = await client.get("/zzzzzz9999", follow_redirects=False)
        assert resp2.status_code == 404
        metrics = (await client.get("/metrics")).text
        assert "cache_hits_total" in metrics

    async def test_expired_410(self, client, app, auth_headers):
        link = await self._create(client, auth_headers, custom_alias="expiring")
        # 直接改库制造"已过期"，再手动失效缓存（模拟 TTL 到期后的回源）
        async with app.state.session_factory() as session, session.begin():
            await session.execute(
                update(Link)
                .where(Link.code == "expiring")
                .values(expires_at=utcnow().replace(year=2020))
            )
        await app.state.cache.delete("link:expiring")
        resp = await client.get("/expiring", follow_redirects=False)
        assert resp.status_code == 410

    async def test_deleted_404_and_cache_evicted(self, client, app, auth_headers):
        link = await self._create(client, auth_headers, custom_alias="delme")
        assert (
            await client.delete(f"/api/links/{link['code']}", headers=auth_headers)
        ).status_code == 204
        # 删除后缓存已失效：跳转必须 404 而不是继续放行
        assert (await client.get("/delme", follow_redirects=False)).status_code == 404


class TestListAndOwnership:
    async def test_pagination(self, client, auth_headers):
        for i in range(3):
            await client.post(
                "/api/links",
                json={"target_url": f"https://example.com/{i}"},
                headers=auth_headers,
            )
        resp = await client.get("/api/links?page=1&size=2", headers=auth_headers)
        body = resp.json()
        assert body["total"] == 3 and len(body["items"]) == 2

    async def test_others_link_invisible_404(self, client, auth_headers):
        # alice 创建
        resp = await client.post(
            "/api/links",
            json={"target_url": "https://example.com", "custom_alias": "alice-only"},
            headers=auth_headers,
        )
        code = resp.json()["code"]
        # bob 视角：详情/统计/删除一律 404，不泄露存在性
        token_bob = None
        await client.post(
            "/api/auth/register", json={"username": "bob2", "password": "password123"}
        )
        token_bob = (
            await client.post(
                "/api/auth/login", json={"username": "bob2", "password": "password123"}
            )
        ).json()["access_token"]
        headers_bob = {"Authorization": f"Bearer {token_bob}"}
        assert (await client.get(f"/api/links/{code}", headers=headers_bob)).status_code == 404
        assert (
            await client.get(f"/api/links/{code}/stats", headers=headers_bob)
        ).status_code == 404
        assert (await client.delete(f"/api/links/{code}", headers=headers_bob)).status_code == 404


class TestStats:
    async def test_stats_after_flush(self, client, app, auth_headers):
        resp = await client.post(
            "/api/links",
            json={"target_url": "https://example.com/news", "custom_alias": "news"},
            headers=auth_headers,
        )
        assert resp.status_code == 201
        for _ in range(3):
            await client.get("/news", follow_redirects=False)
        await asyncio.sleep(0.3)  # flush 间隔 0.05s，留足余量
        stats = await client.get("/api/links/news/stats?bucket=day", headers=auth_headers)
        assert stats.status_code == 200
        body = stats.json()
        assert body["total"] == 3
        assert body["buckets"] and body["buckets"][0]["count"] == 3
