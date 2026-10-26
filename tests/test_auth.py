"""认证流程接口测试。"""


class TestRegister:
    async def test_register_ok(self, client):
        resp = await client.post(
            "/api/auth/register", json={"username": "alice", "password": "password123"}
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["username"] == "alice"
        assert "password" not in body and "password_hash" not in body  # 不泄露凭据字段

    async def test_duplicate_username_409(self, client):
        payload = {"username": "bob", "password": "password123"}
        assert (await client.post("/api/auth/register", json=payload)).status_code == 201
        assert (await client.post("/api/auth/register", json=payload)).status_code == 409

    async def test_weak_password_422(self, client):
        resp = await client.post(
            "/api/auth/register", json={"username": "carol", "password": "short"}
        )
        assert resp.status_code == 422

    async def test_bad_username_422(self, client):
        resp = await client.post(
            "/api/auth/register", json={"username": "bad name!", "password": "password123"}
        )
        assert resp.status_code == 422


class TestLogin:
    async def test_login_ok(self, client):
        await client.post(
            "/api/auth/register", json={"username": "alice", "password": "password123"}
        )
        resp = await client.post(
            "/api/auth/login", json={"username": "alice", "password": "password123"}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["token_type"] == "bearer"
        assert body["access_token"].count(".") == 2  # JWT 三段式

    async def test_wrong_password_401_same_message(self, client):
        await client.post(
            "/api/auth/register", json={"username": "alice", "password": "password123"}
        )
        # 密码错误与用户不存在返回同一文案：防用户名枚举
        wrong_pw = await client.post(
            "/api/auth/login", json={"username": "alice", "password": "wrong-password"}
        )
        no_user = await client.post(
            "/api/auth/login", json={"username": "ghost", "password": "wrong-password"}
        )
        assert wrong_pw.status_code == no_user.status_code == 401
        assert wrong_pw.json()["detail"] == no_user.json()["detail"]


class TestMe:
    async def test_me_with_token(self, client, auth_headers):
        resp = await client.get("/api/auth/me", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["username"] == "alice"

    async def test_me_without_token_401(self, client):
        assert (await client.get("/api/auth/me")).status_code == 401

    async def test_me_with_garbage_token_401(self, client):
        resp = await client.get(
            "/api/auth/me", headers={"Authorization": "Bearer garbage.token.here"}
        )
        assert resp.status_code == 401
