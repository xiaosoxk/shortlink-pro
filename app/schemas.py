"""Pydantic v2 请求/响应模型：校验规则即接口文档（自动生成 OpenAPI）。"""
from datetime import datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

T = TypeVar("T")


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=32, pattern=r"^[A-Za-z0-9_]+$")
    password: str = Field(min_length=8, max_length=128)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    created_at: datetime


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class LinkCreate(BaseModel):
    target_url: HttpUrl
    custom_alias: str | None = Field(
        default=None, min_length=4, max_length=32, pattern=r"^[A-Za-z0-9_-]+$"
    )
    expires_in_seconds: int | None = Field(default=None, ge=0, le=10 * 365 * 86400)


class LinkOut(BaseModel):
    id: int
    code: str
    short_url: str
    target_url: str
    created_at: datetime
    expires_at: datetime | None
    is_active: bool
    click_count: int


class StatBucket(BaseModel):
    bucket: str
    count: int


class StatsOut(BaseModel):
    code: str
    total: int  # 已落库计数 + 缓冲区未落库计数（实时性说明见 README）
    window_hours: int
    buckets: list[StatBucket]


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    size: int


class HealthOut(BaseModel):
    status: str
    environment: str
    cache: str
    limiter: str
    lock: str
    click_queue_depth: int
