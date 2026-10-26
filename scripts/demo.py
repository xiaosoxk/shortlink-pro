"""并发演示脚本：先启动服务，再运行本脚本。

    python -m uvicorn app.main:app --port 8000
    python scripts/demo.py http://127.0.0.1:8000

演示内容（对应面试题"asyncio 适合什么场景"）：
1. 信号量限流下并发创建 60 条短链；
2. 1200 次并发跳转 —— 观察吞吐与限流器 429 的自动熔断行为；
3. 打印吞吐报告。
"""
import asyncio
import sys
import time
from collections import Counter

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
USERNAME = "demo_user"
PASSWORD = "demo-password-123"


async def main() -> None:
    limits = httpx.Limits(max_connections=200)
    async with httpx.AsyncClient(base_url=BASE, timeout=15, limits=limits) as client:
        # 登录（幂等：已注册则直接登录）
        await client.post(
            "/api/auth/register", json={"username": USERNAME, "password": PASSWORD}
        )
        token = (
            await client.post(
                "/api/auth/login", json={"username": USERNAME, "password": PASSWORD}
            )
        ).json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        sem = asyncio.Semaphore(30)

        async def create(i: int) -> str:
            async with sem:
                resp = await client.post(
                    "/api/links",
                    json={"target_url": f"https://example.com/demo/{i}"},
                    headers=headers,
                )
                resp.raise_for_status()
                return resp.json()["code"]

        t0 = time.perf_counter()
        codes = await asyncio.gather(*(create(i) for i in range(60)))
        t1 = time.perf_counter()
        print(f"[1] 并发创建 {len(codes)} 条短链，耗时 {t1 - t0:.2f}s")

        async def hit(code: str) -> int:
            async with sem:
                resp = await client.get(f"/{code}", follow_redirects=False)
                return resp.status_code

        t2 = time.perf_counter()
        statuses = await asyncio.gather(*(hit(c) for c in codes for _ in range(20)))
        t3 = time.perf_counter()
        dist = Counter(statuses)
        total = len(statuses)
        elapsed = t3 - t2
        print(f"[2] 并发跳转 {total} 次，耗时 {elapsed:.2f}s，吞吐 {total / elapsed:.0f} req/s")
        print(f"    状态码分布: {dict(sorted(dist.items()))}")
        print("    (429 为令牌桶限流生效；调大 SL_RATE_LIMIT_REDIRECT_PER_MINUTE 可放开)")
        print(f"[3] 示例短链: {BASE}/{codes[0]}")


if __name__ == "__main__":
    asyncio.run(main())
