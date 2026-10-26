"""分布式锁：Redis SET NX EX + Lua 校验 token 释放；无 Redis 时退化为
进程内 asyncio 锁。

三个必讲的细节（对应复习手册 4.2 分布式锁一节）：
1. value 必须是唯一 token —— 防止自己的锁过期后误删别人的锁；
2. 释放必须用 Lua 做"比较再删除"的原子操作（GET+DEL 两步有竞态窗口）；
3. 锁要带 TTL 兜底 —— 持有者崩溃时锁能自动过期。
（生产还需看门狗续期与 Redlock 争议讨论，README 有展开。）
"""
import asyncio
import logging
import secrets
import time
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)

RELEASE_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
else
    return 0
end
"""


class LockBackend(ABC):
    @abstractmethod
    async def acquire(self, key: str, ttl: float = 5.0) -> str | None:
        """抢到返回唯一 token（用于释放校验），抢不到返回 None（调用方决定报 409）。"""

    @abstractmethod
    async def release(self, key: str, token: str) -> bool: ...

    @abstractmethod
    async def close(self) -> None: ...


class RedisLockBackend(LockBackend):
    def __init__(self, client, prefix: str = "sl:lock"):
        self._client = client
        self._prefix = prefix
        self._release = client.register_script(RELEASE_SCRIPT)

    async def acquire(self, key: str, ttl: float = 5.0) -> str | None:
        token = secrets.token_hex(16)
        ok = await self._client.set(
            f"{self._prefix}:{key}", token, nx=True, ex=max(1, int(ttl))
        )
        return token if ok else None

    async def release(self, key: str, token: str) -> bool:
        result = await self._release(keys=[f"{self._prefix}:{key}"], args=[token])
        return bool(result)

    async def close(self) -> None:
        await self._client.aclose()


class AsyncioLockBackend(LockBackend):
    """单进程降级：每 key 一把 asyncio.Lock（非阻塞 try-acquire）。"""

    def __init__(self) -> None:
        self._locks: dict[str, tuple[asyncio.Lock, str | None]] = {}

    async def acquire(self, key: str, ttl: float = 5.0) -> str | None:
        lock = self._locks.get(key)
        if lock is None:
            lock = (asyncio.Lock(), None)
            self._locks[key] = lock
        if lock[0].locked():
            return None
        await lock[0].acquire()
        token = secrets.token_hex(16)
        self._locks[key] = (lock[0], token)
        return token

    async def release(self, key: str, token: str) -> bool:
        entry = self._locks.get(key)
        if entry and entry[1] == token:
            entry[0].release()
            self._locks[key] = (entry[0], None)
            return True
        return False

    async def close(self) -> None:
        for lock, _ in self._locks.values():
            if lock.locked():
                lock.release()
        self._locks.clear()


async def create_lock_backend(redis_url: str) -> LockBackend:
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
            logger.info("lock backend: redis (set-nx + lua release)")
            return RedisLockBackend(client)
        except Exception as exc:  # noqa: BLE001
            logger.warning("redis unavailable (%s), fallback to asyncio lock", exc)
    logger.info("lock backend: asyncio (per-key)")
    return AsyncioLockBackend()
