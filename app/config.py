"""集中配置：pydantic-settings，支持 SL_ 前缀环境变量与 .env 覆盖。

设计要点：
- get_settings() 用 lru_cache 做进程级单例，但 create_app 允许注入自定义
  Settings 实例（测试隔离的关键，见 tests/conftest.py）。
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SL_", env_file=".env", extra="ignore")

    app_name: str = "ShortLink Pro"
    environment: str = "dev"  # dev -> 人类可读日志, prod -> JSON 结构化日志

    # 安全
    secret_key: str = "dev-secret-change-me"
    access_token_expire_minutes: int = 60 * 24
    password_pbkdf2_iterations: int = 200_000

    # 存储
    database_url: str = "sqlite+aiosqlite:///./shortlink.db"
    redis_url: str = ""  # 留空 = 全部走内存版降级实现

    # 短链服务
    public_base_url: str = "http://127.0.0.1:8000"
    machine_id: int = 1  # 雪花 ID 机器号 0-1023
    link_cache_ttl: int = 300  # 热点短链缓存秒数
    negative_cache_ttl: int = 30  # 不存在 key 的负缓存（防缓存穿透）

    # 限流（令牌桶，按 IP）
    rate_limit_api_per_minute: int = 120
    rate_limit_redirect_per_minute: int = 600

    # 点击埋点批写
    click_queue_size: int = 10_000
    click_flush_interval: float = 2.0
    click_flush_batch: int = 500

    # 统计
    stats_default_window_hours: int = 168  # 默认近 7 天


@lru_cache
def get_settings() -> Settings:
    return Settings()
