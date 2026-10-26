"""认证接口：注册 / 登录 / 当前用户。"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password, jwt_encode, verify_password
from app.database import get_session
from app.dependencies import get_current_user
from app.models import User
from app.schemas import TokenOut, UserCreate, UserOut

logger = logging.getLogger(__name__)
router = APIRouter(tags=["auth"])


@router.post("/api/auth/register", status_code=201, response_model=UserOut)
async def register(
    data: UserCreate,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> User:
    settings = request.app.state.settings
    existing = await session.scalar(select(User).where(User.username == data.username))
    if existing is not None:
        raise HTTPException(409, "username already taken")
    user = User(
        username=data.username,
        password_hash=hash_password(
            data.password, iterations=settings.password_pbkdf2_iterations
        ),
    )
    session.add(user)
    try:
        await session.commit()
    except IntegrityError as exc:
        # 并发注册同名用户的兜底：唯一索引是最终防线
        await session.rollback()
        raise HTTPException(409, "username already taken") from exc
    logger.info("user registered: %s", user.username)
    return user


@router.post("/api/auth/login", response_model=TokenOut)
async def login(
    data: UserCreate,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> TokenOut:
    settings = request.app.state.settings
    user = await session.scalar(select(User).where(User.username == data.username))
    # 统一 401 文案：不区分"用户不存在"与"密码错误"，防用户名枚举
    if user is None or not verify_password(data.password, user.password_hash):
        raise HTTPException(401, "incorrect username or password")
    expires_in = settings.access_token_expire_minutes * 60
    token = jwt_encode(
        {"sub": user.username, "uid": user.id},
        settings.secret_key,
        expire_seconds=expires_in,
    )
    return TokenOut(access_token=token, expires_in=expires_in)


@router.get("/api/auth/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)) -> User:
    return user
