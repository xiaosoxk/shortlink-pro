"""短链接口：创建 / 列表 / 详情 / 统计 / 删除 / 302 跳转（热路径）。"""
import hashlib

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.dependencies import get_current_user
from app.models import User, utcnow
from app.schemas import LinkCreate, LinkOut, Page, StatsOut
from app.services.link_service import (
    AliasConflict,
    LinkGone,
    LinkNotFound,
    LinkService,
)

router = APIRouter(tags=["links"])


def _client_hash(request: Request) -> str:
    """IP 加盐哈希：统计可去重，但不存原始 IP。"""
    settings = request.app.state.settings
    ip = request.client.host if request.client else "unknown"
    return hashlib.sha256(f"{ip}:{settings.secret_key}".encode()).hexdigest()[:16]


def _to_out(link, base_url: str) -> LinkOut:
    return LinkOut(
        id=link.id,
        code=link.code,
        short_url=f"{base_url}/{link.code}",
        target_url=link.target_url,
        created_at=link.created_at,
        expires_at=link.expires_at,
        is_active=link.is_active,
        click_count=link.click_count,
    )


@router.post("/api/links", status_code=201, response_model=LinkOut)
async def create_link(
    data: LinkCreate,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> LinkOut:
    service: LinkService = request.app.state.links
    try:
        link = await service.create(session, user.id, data)
    except AliasConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    return _to_out(link, request.app.state.settings.public_base_url)


@router.get("/api/links", response_model=Page[LinkOut])
async def my_links(
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
) -> Page[LinkOut]:
    service: LinkService = request.app.state.links
    items, total = await service.list_owned(session, user.id, page, size)
    base = request.app.state.settings.public_base_url
    return Page(
        items=[_to_out(link, base) for link in items], total=total, page=page, size=size
    )


@router.get("/api/links/{code}/stats", response_model=StatsOut)
async def link_stats(
    code: str,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    window_hours: int = Query(default=None, ge=1, le=24 * 365),
    bucket: str = Query(default="day", pattern="^(day|hour)$"),
) -> StatsOut:
    service: LinkService = request.app.state.links
    settings = request.app.state.settings
    try:
        data = await service.stats(
            session,
            code,
            user.id,
            window_hours or settings.stats_default_window_hours,
            bucket,
        )
    except LinkNotFound as exc:
        raise HTTPException(404, "link not found") from exc
    return StatsOut(**data)


@router.get("/api/links/{code}", response_model=LinkOut)
async def link_detail(
    code: str,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> LinkOut:
    service: LinkService = request.app.state.links
    try:
        link = await service.get_owned(session, code, user.id)
    except LinkNotFound as exc:
        raise HTTPException(404, "link not found") from exc
    return _to_out(link, request.app.state.settings.public_base_url)


@router.delete("/api/links/{code}", status_code=204)
async def delete_link(
    code: str,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    service: LinkService = request.app.state.links
    try:
        await service.delete(session, code, user.id)
    except LinkNotFound as exc:
        raise HTTPException(404, "link not found") from exc


# ---------------- 跳转热路径 ----------------
# 注意：必须最后注册。/{code} 是通配单段路径，放在 API 路由之后才不会遮蔽它们。


@router.get("/{code}", include_in_schema=False)
async def redirect(
    request: Request,
    code: str = Path(pattern=r"^[0-9A-Za-z_-]{4,32}$"),
    session: AsyncSession = Depends(get_session),
):
    service: LinkService = request.app.state.links
    try:
        target = await service.resolve(session, code, _client_hash(request))
    except LinkNotFound as exc:
        raise HTTPException(404, "short link not found") from exc
    except LinkGone as exc:
        raise HTTPException(410, "short link expired or disabled") from exc

    # 实时推送点击事件给订阅了该短码的主人（WebSocket 房间）
    await request.app.state.ws.broadcast_click(code)
    # 302 而非 301：浏览器会永久缓存 301，改址/统计都会失效（面试考点）
    return RedirectResponse(
        target, status_code=302, headers={"Cache-Control": "no-store"}
    )
