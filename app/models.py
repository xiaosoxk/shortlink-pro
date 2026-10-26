"""SQLAlchemy 2.0 风格 ORM 模型。

约定：所有数据库时间戳一律存"去掉时区的 UTC"（naive UTC）。SQLite 没有
真正的时区类型，混用 aware/naive 会导致比较错乱，因此统一在应用层约定。
"""
from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    """统一时间源：naive UTC。生产环境建议时区转换只发生在展示层。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Link(Base):
    __tablename__ = "links"

    # 主键 = 雪花 ID（趋势递增，避免 UUID 导致的 B+ 树页分裂）
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    target_url: Mapped[str] = mapped_column(Text)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # 反范式计数：列表页免聚合查询；由批写 worker 单点更新，天然无竞态
    click_count: Mapped[int] = mapped_column(Integer, default=0)


class ClickEvent(Base):
    __tablename__ = "click_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    link_id: Mapped[int] = mapped_column(BigInteger)
    clicked_at: Mapped[datetime] = mapped_column(DateTime)
    # 只存 IP 的加盐哈希：能做去重分析，又不落原始 PII（合规卖点）
    client_hash: Mapped[str] = mapped_column(String(32))

    __table_args__ = (
        Index("ix_click_link_time", "link_id", "clicked_at"),
    )
