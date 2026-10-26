"""雪花 ID 生成器 + Base62 编码。

64 位布局：1 符号位 | 41 毫秒时间戳 | 10 位机器号 | 12 位序列号
- 单机每毫秒 4096 个，理论可用 69 年
- 时钟回拨处理：小幅回拨沿用上次时间戳并继续消耗序列号（序列耗尽则自旋等待）
- Base62(11~12 字符) 全局唯一，无需查库确认；README 讨论更短码位的取号方案
"""
import threading
import time

EPOCH_MS = 1_735_689_600_000  # 2025-01-01T00:00:00Z，自定义纪元

MACHINE_BITS = 10
SEQUENCE_BITS = 12
MACHINE_MAX = (1 << MACHINE_BITS) - 1
SEQUENCE_MAX = (1 << SEQUENCE_BITS) - 1

BASE62_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"


class Snowflake:
    def __init__(self, machine_id: int = 1):
        if not 0 <= machine_id <= MACHINE_MAX:
            raise ValueError(f"machine_id must be in [0, {MACHINE_MAX}]")
        self._machine_id = machine_id
        self._lock = threading.Lock()
        self._last_ts = -1
        self._sequence = 0

    def next_id(self) -> int:
        with self._lock:
            ts = int(time.time() * 1000)
            if ts < self._last_ts:
                # 时钟回拨：借用上次时间戳继续发号（序列号耗尽则等待追平）
                ts = self._last_ts
            if ts == self._last_ts:
                self._sequence = (self._sequence + 1) & SEQUENCE_MAX
                if self._sequence == 0:
                    while ts <= self._last_ts:
                        ts = int(time.time() * 1000)
            else:
                self._sequence = 0
            self._last_ts = ts
            return ((ts - EPOCH_MS) << (MACHINE_BITS + SEQUENCE_BITS)) | (
                self._machine_id << SEQUENCE_BITS
            ) | self._sequence


def base62_encode(number: int) -> str:
    if number < 0:
        raise ValueError("base62 expects non-negative int")
    if number == 0:
        return BASE62_ALPHABET[0]
    chars = []
    while number:
        number, rem = divmod(number, 62)
        chars.append(BASE62_ALPHABET[rem])
    return "".join(reversed(chars))


def base62_decode(text: str) -> int:
    number = 0
    for ch in text:
        idx = BASE62_ALPHABET.find(ch)
        if idx < 0:
            raise ValueError(f"invalid base62 character: {ch!r}")
        number = number * 62 + idx
    return number
