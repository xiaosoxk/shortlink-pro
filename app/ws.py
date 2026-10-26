"""WebSocket 实时点击流：房间制连接管理 + 鉴权。

- 房间 = 短码：只有链接主人能订阅自己的链接（token 经查询串传入，
  因为浏览器 WebSocket 无法自定义请求头 —— 这本身就是个面试小考点）；
- 广播时快照房间列表再逐个发送，发送失败的连接即时清理；
- 心跳：客户端可发任意文本当 ping，服务端忽略即可保持连接。
"""
import logging
from collections import defaultdict

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from app.core.security import TokenError, jwt_decode
from app.models import Link

logger = logging.getLogger(__name__)
router = APIRouter()

CLOSE_UNAUTHENTICATED = 4401
CLOSE_FORBIDDEN = 4403


class ConnectionManager:
    def __init__(self) -> None:
        self._rooms: dict[str, set[WebSocket]] = defaultdict(set)

    async def connect(self, code: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self._rooms[code].add(websocket)

    def disconnect(self, code: str, websocket: WebSocket) -> None:
        room = self._rooms.get(code)
        if room is not None:
            room.discard(websocket)
            if not room:
                self._rooms.pop(code, None)

    def connections(self) -> int:
        return sum(len(room) for room in self._rooms.values())

    async def broadcast_click(self, code: str, delta: int = 1) -> None:
        room = self._rooms.get(code)
        if not room:
            return
        message = {"type": "click", "code": code, "delta": delta}
        dead = []
        for websocket in list(room):
            try:
                await websocket.send_json(message)
            except Exception:  # noqa: BLE001 - 单个客户端掉线不影响其他订阅者
                dead.append(websocket)
        for websocket in dead:
            self.disconnect(code, websocket)


@router.websocket("/ws/links/{code}")
async def link_click_feed(websocket: WebSocket, code: str, token: str = Query(default="")):
    state = websocket.scope["app"].state
    try:
        payload = jwt_decode(token, state.settings.secret_key)
    except TokenError:
        await websocket.close(code=CLOSE_UNAUTHENTICATED)
        return

    async with state.session_factory() as session:
        link = await session.scalar(
            select(Link).where(Link.code == code, Link.owner_id == int(payload.get("uid", 0)))
        )
    if link is None:
        await websocket.close(code=CLOSE_FORBIDDEN)
        return

    await state.ws.connect(code, websocket)
    logger.info("ws subscribe: %s", code)
    try:
        while True:
            await websocket.receive_text()  # 忽略客户端心跳，仅维持连接
    except WebSocketDisconnect:
        state.ws.disconnect(code, websocket)
        logger.info("ws unsubscribe: %s", code)
