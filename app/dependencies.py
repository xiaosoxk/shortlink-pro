"""FastAPI 依赖注入：鉴权、会话。

依赖链：get_session(每请求一个 AsyncSession) -> get_current_user(解析 JWT 后查库)。
路由只声明 Depends，测试时可以任意覆写 —— 这是框架级 DI 的价值。
"""
from collections.abc import AsyncIterator

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import TokenError, TokenExpiredError, jwt_decode
from app.database import get_session  # noqa: F401 (re-export)
from app.models import User

bearer_scheme = HTTPBearer(auto_error=False)

UNAUTHORIZED = {"WWW-Authenticate": "Bearer"}


async def get_current_user(
    request: Request,
    session: AsyncSession = Depends(get_session),
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> User:
    if credentials is None:
        raise HTTPException(401, "Not authenticated", headers=UNAUTHORIZED)

    settings = request.app.state.settings
    try:
        payload = jwt_decode(credentials.credentials, settings.secret_key)
    except TokenExpiredError as exc:
        raise HTTPException(401, "Token expired", headers=UNAUTHORIZED) from exc
    except TokenError as exc:
        raise HTTPException(401, "Invalid token", headers=UNAUTHORIZED) from exc

    user = await session.scalar(select(User).where(User.id == int(payload.get("uid", 0))))
    if user is None:
        raise HTTPException(401, "Unknown user", headers=UNAUTHORIZED)
    return user
