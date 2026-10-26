"""短链核心业务：创建 / 解析（cache-aside）/ 统计 / 删除。

自定义别名的并发安全（面试高频）：
- 无 Redis：DB 唯一索引兜底，IntegrityError -> 409（跨进程也安全）；
- 有 Redis：先拿 SET NX 分布式锁再查再插，把"冲突重试"提前到"抢占失败"，
  释放锁用 Lua 校验 token，两个后端对业务透明（策略模式）。

解析路径（对应复习手册 4.2 缓存三问）：
- cache-aside：先查缓存，miss 查库回填；
- 不存在的 code 写负缓存哨兵，防穿透；
- 删除后主动失效；命中缓存仍会校验 is_active/expires_at，避免脏放行。
"""
import json
import logging
from collections import Counter
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import NEG
from app.core.snowflake import base62_encode
from app.models import ClickEvent, Link, utcnow
from app.schemas import LinkCreate

logger = logging.getLogger(__name__)


class LinkError(Exception): ...


class LinkNotFound(LinkError): ...


class LinkGone(LinkError): ...


class AliasConflict(LinkError): ...


def _cache_payload(link: Link) -> str:
    return json.dumps({
        "id": link.id,
        "target_url": link.target_url,
        "is_active": link.is_active,
        "expires_at": link.expires_at.isoformat() if link.expires_at else None,
    })


class LinkService:
    def __init__(self, cache, lock_backend, snowflake, analytics, settings):
        self._cache = cache
        self._locks = lock_backend
        self._snowflake = snowflake
        self._analytics = analytics
        self._settings = settings

    # ---------------- 创建 ----------------

    async def create(self, session: AsyncSession, owner_id: int, data: LinkCreate) -> Link:
        expires_at = (
            utcnow() + timedelta(seconds=data.expires_in_seconds)
            if data.expires_in_seconds is not None
            else None
        )
        if data.custom_alias:
            return await self._create_with_alias(session, owner_id, data, expires_at)
        return await self._create_with_snowflake(session, owner_id, data, expires_at)

    async def _insert(self, session: AsyncSession, owner_id: int, data: LinkCreate, code: str, expires_at) -> Link:
        link = Link(
            id=self._snowflake.next_id(),
            code=code,
            target_url=str(data.target_url),
            owner_id=owner_id,
            expires_at=expires_at,
        )
        session.add(link)
        await session.commit()
        await self._cache.set(
            f"link:{code}", _cache_payload(link), ttl=self._settings.link_cache_ttl
        )
        return link

    async def _create_with_alias(self, session, owner_id, data: LinkCreate, expires_at) -> Link:
        code = data.custom_alias
        token = await self._locks.acquire(f"alias:{code}", ttl=5)
        if token is None:
            raise AliasConflict(f"alias {code!r} is being taken concurrently")
        try:
            existing = await session.scalar(select(Link).where(Link.code == code))
            if existing is not None:
                raise AliasConflict(f"alias {code!r} already exists")
            try:
                return await self._insert(session, owner_id, data, code, expires_at)
            except Exception:
                await session.rollback()
                raise
        finally:
            await self._locks.release(f"alias:{code}", token)

    async def _create_with_snowflake(self, session, owner_id, data: LinkCreate, expires_at) -> Link:
        last_exc: Exception | None = None
        for _ in range(3):  # base62(雪花) 全局唯一，冲突仅可能来自历史脏数据
            try:
                code = _int_to_code(self._snowflake.next_id())
                return await self._insert(session, owner_id, data, code, expires_at)
            except Exception as exc:  # noqa: PERF203
                await session.rollback()
                last_exc = exc
        raise AliasConflict("failed to allocate unique code") from last_exc

    # ---------------- 解析（跳转热路径） ----------------

    async def resolve(self, session: AsyncSession, code: str, client_hash: str) -> str:
        """返回目标 URL；不存在抛 LinkNotFound，过期/停用抛 LinkGone。"""
        cache_key = f"link:{code}"
        raw = await self._cache.get(cache_key)

        if raw == NEG:
            self._analytics._metrics.inc("cache_hits_total")
            raise LinkNotFound(code)
        if raw is not None:
            self._analytics._metrics.inc("cache_hits_total")
            data = json.loads(raw)
        else:
            self._analytics._metrics.inc("cache_misses_total")
            link = await session.scalar(select(Link).where(Link.code == code))
            if link is None:
                await self._cache.set(cache_key, NEG, ttl=self._settings.negative_cache_ttl)
                raise LinkNotFound(code)
            data = {
                "id": link.id,
                "target_url": link.target_url,
                "is_active": link.is_active,
                "expires_at": link.expires_at.isoformat() if link.expires_at else None,
            }
            await self._cache.set(cache_key, json.dumps(data), ttl=self._settings.link_cache_ttl)

        expires_at = data.get("expires_at")
        if not data["is_active"] or (
            expires_at and datetime_from_iso(expires_at) <= utcnow()
        ):
            raise LinkGone(code)

        self._analytics.record(data["id"], code, client_hash)
        return data["target_url"]

    # ---------------- 查询 / 统计 / 删除 ----------------

    async def get_owned(self, session: AsyncSession, code: str, owner_id: int) -> Link:
        """他人资源返回 404 而非 403：不向调用方泄露资源存在性。"""
        link = await session.scalar(
            select(Link).where(Link.code == code, Link.owner_id == owner_id)
        )
        if link is None:
            raise LinkNotFound(code)
        return link

    async def list_owned(self, session: AsyncSession, owner_id: int, page: int, size: int):
        total = await session.scalar(
            select(func.count()).select_from(Link).where(Link.owner_id == owner_id)
        )
        items = (
            await session.scalars(
                select(Link)
                .where(Link.owner_id == owner_id)
                .order_by(Link.created_at.desc(), Link.id.desc())
                .offset((page - 1) * size)
                .limit(size)
            )
        ).all()
        return list(items), int(total or 0)

    async def stats(self, session: AsyncSession, code: str, owner_id: int,
                    window_hours: int, bucket: str = "day") -> dict:
        link = await self.get_owned(session, code, owner_id)
        since = utcnow() - timedelta(hours=window_hours)
        rows = await session.execute(
            select(ClickEvent.clicked_at)
            .where(ClickEvent.link_id == link.id, ClickEvent.clicked_at >= since)
            .order_by(ClickEvent.clicked_at)
        )
        fmt = "%Y-%m-%d" if bucket == "day" else "%Y-%m-%dT%H:00"
        counter: Counter[str] = Counter(t.strftime(fmt) for (t,) in rows.all())
        return {
            "code": code,
            # 落库计数 + 缓冲区未落库计数，保证秒级实时
            "total": link.click_count + self._analytics.pending_count(code),
            "window_hours": window_hours,
            "buckets": [{"bucket": k, "count": v} for k, v in sorted(counter.items())],
        }

    async def delete(self, session: AsyncSession, code: str, owner_id: int) -> None:
        link = await self.get_owned(session, code, owner_id)
        await session.delete(link)
        await session.commit()
        await self._cache.delete(f"link:{code}")  # cache-aside 写后失效


# ---------------- helpers ----------------

def _int_to_code(number: int) -> str:
    return base62_encode(number)


def datetime_from_iso(text: str) -> datetime:
    return datetime.fromisoformat(text)
