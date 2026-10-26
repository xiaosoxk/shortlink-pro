"""日志体系（对应复习手册 6.4）。

- 唯一入口 configure_logging()，子模块一律 logging.getLogger(__name__)；
- request_id 存 ContextVar：同一请求内所有日志自动带上链路 ID，
  纯 ASGI 中间件在请求入口 set，finally 里 reset（异步安全）；
- dev 输出人类可读格式，prod 输出 JSON（供 ELK/Loki 采集）；
- 关闭 uvicorn 自带 access log，由我们的中间件统一输出（含耗时）。
"""
import json
import logging
import sys
from contextvars import ContextVar
from datetime import datetime, timezone

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": request_id_var.get(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


class DevFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        return f"{base} [rid={request_id_var.get()}]"


_configured = False


def configure_logging(environment: str = "dev") -> None:
    global _configured
    if _configured:
        return
    _configured = True

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter() if environment == "prod" else DevFormatter(
        fmt="%(asctime)s %(levelname)-7s %(name)s %(message)s"))
    root.handlers = [handler]

    # 自己的中间件负责 access log，避免重复输出
    logging.getLogger("uvicorn.access").disabled = True
