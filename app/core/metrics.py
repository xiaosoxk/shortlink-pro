"""极简指标器：计数器 + /metrics 输出 Prometheus 文本格式。

不引 prometheus-client 是刻意的：演示"指标其实只是带约定的计数器"，
生产环境替换为官方客户端 + Histogram（P99 分位数）即可，接口不变。
"""
from collections import Counter


class Metrics:
    def __init__(self) -> None:
        self._counters: Counter[str] = Counter()

    def inc(self, name: str, n: int = 1) -> None:
        self._counters[name] += n

    def snapshot(self) -> dict[str, int]:
        return dict(self._counters)

    def render(self, gauges: dict[str, float] | None = None) -> str:
        lines: list[str] = []
        for name, value in sorted(self._counters.items()):
            lines.append(f"# TYPE {name} counter")
            lines.append(f"{name} {value}")
        for name, value in sorted((gauges or {}).items()):
            lines.append(f"# TYPE {name} gauge")
            lines.append(f"{name} {value}")
        return "\n".join(lines) + "\n"
