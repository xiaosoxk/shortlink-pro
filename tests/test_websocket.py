"""WebSocket 实时点击推送测试（TestClient 自带 lifespan 管理）。

注意：服务端"未 accept 就 close"发生在握手阶段，TestClient 会在
websocket_connect() 进入时直接抛 WebSocketDisconnect，而不是等 receive。
"""
import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.main import create_app
from tests.conftest import make_settings


def _make_client(tmp_path):
    settings = make_settings(
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'ws.db').as_posix()}"
    )
    return TestClient(create_app(settings))


def _prepare(tc: TestClient, alias: str):
    tc.post("/api/auth/register", json={"username": "owner", "password": "password123"})
    token = tc.post(
        "/api/auth/login", json={"username": "owner", "password": "password123"}
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    link = tc.post(
        "/api/links",
        json={"target_url": "https://example.com/live", "custom_alias": alias},
        headers=headers,
    ).json()
    return token, link["code"]


def test_click_event_pushed_to_owner(tmp_path):
    with _make_client(tmp_path) as tc:  # with 语句自动运行 lifespan
        token, code = _prepare(tc, "wslive")
        with tc.websocket_connect(f"/ws/links/{code}?token={token}") as ws:
            tc.get(f"/{code}", follow_redirects=False)
            message = ws.receive_json()
            assert message == {"type": "click", "code": code, "delta": 1}


def test_ws_requires_valid_token(tmp_path):
    with _make_client(tmp_path) as tc:
        # 无 token：握手阶段即被服务端以 4401 关闭
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with tc.websocket_connect("/ws/links/anything?token="):
                pass
        assert exc_info.value.code == 4401


def test_ws_cannot_watch_others_link(tmp_path):
    with _make_client(tmp_path) as tc:
        _prepare(tc, "alices")
        # 另一个用户注册登录，试图监听 alice 的短链
        tc.post("/api/auth/register", json={"username": "mallory", "password": "password123"})
        mallory_token = tc.post(
            "/api/auth/login", json={"username": "mallory", "password": "password123"}
        ).json()["access_token"]
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with tc.websocket_connect(f"/ws/links/alices?token={mallory_token}"):
                pass
        assert exc_info.value.code == 4403
