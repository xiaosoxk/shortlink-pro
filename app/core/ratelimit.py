"""令牌桶限流器：内存版 + Redis Lua 原子版（策略模式，同 cache.py）。

令牌桶 vs 固定窗口 vs 滑动窗口：
- 固定窗口实现最简单，但窗口边界处可通过 2 倍流量（临界突刺）；
- 令牌桶允许突发、长期速率受控，是网关限流最常用选择，故选它；
- Redis 版把"读桶-补币-扣币-写回"压进一个 Lua 脚本，利用 Redis 单线程
  原子执行，多进程/多实例共享同一个桶。
"""
import logging
import time
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)

# KEYS[1]=桶名  ARGV: 补币速率(个/秒) 容量 当前秒数
ALLOW_SCRIPT = """
local key      = KEYS[1]
local rate     = tonumber(ARGV[1])
local capacity = tonumber(ARGV[2])
local now      = tonumber(ARGV[3])

local bucket   = redis.call('HMGET', key, 'tokens', 'ts')
local tokens   = tonumber(bucket[1]) or capacity
local ts       = tonumber(bucket[2]) or now

tokens = math.min(capacity, tokens + math.max(0, now - ts) * rate)
local allowed = 0
if tokens >= 1 then
    tokens = tokens - 1
    allowed = 1
end
redis.call('HSET', key, 'tokens', tokens, 'ts', now)
redis.call('PEXPIRE', key, math.ceil(capacity / rate * 2000))
return allowed
"""


class RateLimiter(ABC):
    """返回 (是否放行, 建议重试等待秒数)。"""

    @abstractmethod
    async def allow(self, key: str, per_minute: int) -> tuple[bool, float]: ...

    @abstractmethod
    async def close(self) -> None: ...


class MemoryTokenBucketLimiter(RateLimiter):
    """单进程版。key -> [剩余令牌, 上次时间戳(monotonic)]。"""

    def __init__(self) -> None:
        self._buckets: dict[str, list[float]] = {}

    async def allow(self, key: str, per_minute: int) -> tuple[bool, float]:
        rate = per_minute / 60.0
        now = time.monotonic()
        tokens, last_ts = self._buckets.get(key, (float(per_minute), now))
        tokens = min(float(per_minute), tokens + (now - last_ts) * rate)
        if tokens >= 1.0:
            tokens -= 1.0
            allowed, retry_after = True, 0.0
        else:
            allowed, retry_after = False, (1.0 - tokens) / rate
        self._buckets[key] = (tokens, now)
        return allowed, retry_after

    async def close(self) -> None:
        self._buckets.clear()


class RedisTokenBucketLimiter(RateLimiter):
    def __init__(self, client, prefix: str = "sl:rl"):
        self._client = client
        self._prefix = prefix
        self._script = client.register_script(ALLOW_SCRIPT)

    async def allow(self, key: str, per_minute: int) -> tuple[bool, float]:
        rate = per_minute / 60.0
        allowed = await self._script(
            keys=[f"{self._prefix}:{key}"],
            args=[rate, per_minute, time.time()],
        )
        return bool(allowed), 0.0 if allowed else max(1.0, 60.0 / per_minute)

    async def close(self) -> None:
        await self._client.aclose()


async def create_limiter(redis_url: str) -> RateLimiter:
    if redis_url:
        try:
            import redis.asyncio as aioredis

            client = aioredis.from_url(
                redis_url,
                decode_responses=True,
                socket_connect_timeout=2,
                socket_timeout=2,
            )
            await client.ping()
            logger.info("rate limiter backend: redis (lua token bucket)")
            return RedisTokenBucketLimiter(client)
        except Exception as exc:  # noqa: BLE001
            logger.warning("redis unavailable (%s), fallback to in-memory limiter", exc)
    logger.info("rate limiter backend: memory (token bucket)")
    return MemoryTokenBucketLimiter()
