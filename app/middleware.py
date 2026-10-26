"""两个手写纯 ASGI 中间件（不用 BaseHTTPMiddleware）。

为什么不用 BaseHTTPMiddleware？它会把请求包进额外的任务与内存流，
有性能开销和流式响应的坑；纯 ASGI 中间件只是两层函数调用，面试可以
借这里讲清 ASGI 协议本身（scope/receive/send 三件套）。

链路：RequestContextMiddleware（最外层，注入 request_id/耗时/访问日志/指标）
      -> RateLimitMiddleware（令牌桶限流，命中直接 429 短路）
      -> FastAPI 路由。
"""
import json
import logging
import time
import uuid

from starlette.datastructures import Headers, MutableHeaders

from app.core.logging_conf import request_id_var

logger = logging.getLogger("shortlink.access")

SKIP_EXACT = {"/", "/health", "/metrics", "/docs", "/redoc", "/openapi.json"}


class RequestContextMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        rid = uuid.uuid4().hex[:12]
        token = request_id_var.set(rid)
        start = time.perf_counter()
        status_holder = {"status": 0}

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
                headers = MutableHeaders(scope=message)
                headers.append("x-request-id", rid)
                headers.append("x-process-time-ms", f"{(time.perf_counter() - start) * 1000:.1f}")
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000
            status = status_holder["status"] or 0
            logger.info(
                '%s %s -> %s (%.1f ms)', scope.get("method", "-"), scope.get("path", "-"),
                status or "-", elapsed_ms,
            )
            metrics = getattr(getattr(scope.get("app", None), "state", None), "metrics", None)
            if metrics is not None:
                metrics.inc("http_requests_total")
                metrics.inc(f"http_status_{status // 100 if status else 0}xx_total")
            request_id_var.reset(token)


class RateLimitMiddleware:
    def __init__(self, app, settings):
        self.app = app
        self.settings = settings

    @staticmethod
    def _skip(path: str) -> bool:
        if path in SKIP_EXACT or path.startswith("/static"):
            return True
        # 带 . 的最后一段（favicon.ico / openapi.json 等）不属于短码
        return "." in path.rsplit("/", 1)[-1]

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope["path"]
        if self._skip(path):
            await self.app(scope, receive, send)
            return

        state = scope["app"].state
        headers = Headers(scope=scope)
        # 反向代理场景取 X-Forwarded-For 第一跳；仅在可信代理下允许覆盖
        forwarded = headers.get("x-forwarded-for", "")
        ip = forwarded.split(",")[0].strip() if forwarded else (scope.get("client") or ("unknown",))[0]

        if path.startswith("/api/") or path.startswith("/ws"):
            key, limit = f"api:{ip}", self.settings.rate_limit_api_per_minute
        else:
            key, limit = f"redirect:{ip}", self.settings.rate_limit_redirect_per_minute

        allowed, retry_after = await state.limiter.allow(key, limit)
        if allowed:
            await self.app(scope, receive, send)
            return

        state.metrics.inc("rate_limited_total")
        body = json.dumps({"detail": "Too Many Requests"}).encode()
        await send({
            "type": "http.response.start",
            "status": 429,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
                (b"retry-after", str(int(retry_after) + 1).encode()),
                (b"x-request-id", request_id_var.get().encode()),
            ],
        })
        await send({"type": "http.response.body", "body": body})
