"""缓存后端：策略模式。Redis 可用 -> RedisCache；不可用 -> 内存 TTL-LRU。

这是"优雅降级"的完整实现：业务代码只依赖 CacheBackend 抽象，
create_cache 工厂在启动时探测 Redis（ping），失败则打日志降级，
同一份代码既能零依赖单机跑通，也能上生产接 Redis。

面试点（对应复习手册 4.2）：
- cache-aside 读写路径在 services/link_service.py；
- 负缓存（NEG 哨兵）防缓存穿透；
- 删除/下线时主动失效缓存，保证最终一致。
"""
import logging
import time
from abc import ABC, abstractmethod
from collections import OrderedDict

logger = logging.getLogger(__name__)

NEG = "\u0000NEG"  # 负缓存哨兵：key 一定不存在（防穿透）


class CacheBackend(ABC):
    @abstractmethod
    async def get(self, key: str) -> str | None: ...

    @abstractmethod
    async def set(self, key: str, value: str, ttl: float | None = None) -> None: ...

    @abstractmethod
    async def delete(self, key: str) -> None: ...

    @abstractmethod
    async def close(self) -> None: ...

    def size(self) -> int:
        return 0


class MemoryCache(CacheBackend):
    """TTL + LRU 的 OrderedDict 实现。

    无锁说明：所有调用都发生在同一个事件循环线程内，且这些方法体内没有
    await 让出点，因此天然原子（单线程事件循环的并发模型，面试高频考点）。
    """

    def __init__(self, max_size: int = 4096):
        self._data: OrderedDict[str, tuple[str, float | None]] = OrderedDict()
        self._max_size = max_size

    def _expired(self, expire_at: float | None) -> bool:
        return expire_at is not None and time.monotonic() > expire_at

    async def get(self, key: str) -> str | None:
        item = self._data.get(key)
        if item is None:
            return None
        value, expire_at = item
        if self._expired(expire_at):
            del self._data[key]
            return None
        self._data.move_to_end(key)  # LRU 触碰
        return value

    async def set(self, key: str, value: str, ttl: float | None = None) -> None:
        expire_at = time.monotonic() + ttl if ttl is not None else None
        self._data[key] = (value, expire_at)
        self._data.move_to_end(key)
        while len(self._data) > self._max_size:
            self._data.popitem(last=False)  # 淘汰最久未使用

    async def delete(self, key: str) -> None:
        self._data.pop(key, None)

    async def close(self) -> None:
        self._data.clear()

    def size(self) -> int:
        return len(self._data)


class RedisCache(CacheBackend):
    def __init__(self, client, prefix: str = "sl"):
        self._client = client
        self._prefix = prefix

    def _k(self, key: str) -> str:
        return f"{self._prefix}:{key}"

    async def get(self, key: str) -> str | None:
        return await self._client.get(self._k(key))

    async def set(self, key: str, value: str, ttl: float | None = None) -> None:
        await self._client.set(self._k(key), value, ex=max(1, int(ttl)) if ttl else None)

    async def delete(self, key: str) -> None:
        await self._client.delete(self._k(key))

    async def close(self) -> None:
        await self._client.aclose()


async def create_cache(redis_url: str) -> CacheBackend:
    """工厂：探测 Redis，失败降级内存实现（只打警告，不让服务起不来）。"""
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
            logger.info("cache backend: redis")
            return RedisCache(client)
        except Exception as exc:  # noqa: BLE001 - 任何 Redis 故障都降级
            logger.warning("redis unavailable (%s), fallback to in-memory cache", exc)
    logger.info("cache backend: memory (TTL-LRU)")
    return MemoryCache()
