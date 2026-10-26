"""点击埋点：生产者-消费者 + 批量落库。

为什么不让重定向接口直接写库？
- 每次跳转一条 INSERT，热点链接会把 DB 写 QPS 打爆；
- 正确姿势：请求路径只做 put_nowait（非阻塞、微秒级），两个后台任务
  异步消费：_consume 从队列搬进内存缓冲，_flush_loop 按间隔/批量
  合并成一次 executemany + 一次计数 UPDATE。

背压策略：队列满时丢弃并计数（点击统计允许少量丢失，绝不能反压拖垮
跳转主链路）—— 这条取舍本身就是面试加分项。
优雅停机：lifespan 结束时 stop() 先取消任务、再 flush 残留缓冲，不丢数据。
"""
import asyncio
import logging
from collections import Counter
from datetime import datetime

from sqlalchemy import insert, update

from app.core.logging_conf import request_id_var  # noqa: F401 (供日志格式使用)
from app.models import ClickEvent, Link

logger = logging.getLogger(__name__)


class AnalyticsService:
    def __init__(self, session_factory, settings, metrics):
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=settings.click_queue_size)
        self._session_factory = session_factory
        self._settings = settings
        self._metrics = metrics
        self._buffer: list[dict] = []
        self._deltas: Counter[str] = Counter()  # code -> 未落库点击数
        self._tasks: list[asyncio.Task] = []
        self._flush_lock = asyncio.Lock()

    # ---------- 生产端（重定向路径调用，非阻塞） ----------

    def record(self, link_id: int, code: str, client_hash: str) -> None:
        from app.models import utcnow

        self._metrics.inc("clicks_recorded_total")
        try:
            self.queue.put_nowait({"link_id": link_id, "code": code, "client_hash": client_hash, "clicked_at": utcnow()})
        except asyncio.QueueFull:
            self._metrics.inc("clicks_dropped_total")

    def pending_count(self, code: str) -> int:
        return self._deltas.get(code, 0)

    # ---------- 消费端 ----------

    async def start(self) -> None:
        self._tasks = [
            asyncio.create_task(self._consume(), name="click-consumer"),
            asyncio.create_task(self._flush_loop(), name="click-flusher"),
        ]

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        await self.flush()
        logger.info("analytics stopped, residual clicks flushed")

    async def _consume(self) -> None:
        while True:
            item = await self.queue.get()
            self._buffer.append(item)
            self._deltas[item["code"]] += 1
            self.queue.task_done()
            if len(self._buffer) >= self._settings.click_flush_batch:
                await self.flush()

    async def _flush_loop(self) -> None:
        while True:
            await asyncio.sleep(self._settings.click_flush_interval)
            await self.flush()

    async def flush(self) -> None:
        async with self._flush_lock:  # 消费者与定时器可能同时触发
            if not self._buffer:
                return
            rows, deltas = self._buffer, self._deltas
            self._buffer, self._deltas = [], Counter()
        async with self._session_factory() as session, session.begin():
            await session.execute(insert(ClickEvent), rows)
            # 按 link_id 聚合更新反范式计数
            by_link: Counter[int] = Counter(int(r["link_id"]) for r in rows)
            for link_id, delta in by_link.items():
                await session.execute(
                    update(Link)
                    .where(Link.id == link_id)
                    .values(click_count=Link.click_count + delta)
                )
        self._metrics.inc("clicks_flushed_total", len(rows))
