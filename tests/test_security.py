"""安全原语单元测试：JWT / 密码 / 雪花 ID / Base62。"""
import threading

import pytest

from app.core.security import (
    TokenError,
    TokenExpiredError,
    hash_password,
    jwt_decode,
    jwt_encode,
    verify_password,
)
from app.core.snowflake import Snowflake, base62_decode, base62_encode

SECRET = "unit-test-secret"


class TestPassword:
    def test_roundtrip(self):
        stored = hash_password("s3cret-password", iterations=1000)
        assert stored.startswith("pbkdf2_sha256$1000$")
        assert verify_password("s3cret-password", stored)

    def test_wrong_password(self):
        stored = hash_password("correct", iterations=1000)
        assert not verify_password("wrong", stored)

    def test_malformed_stored_hash_is_false_not_crash(self):
        assert not verify_password("x", "not-a-valid-hash")
        assert not verify_password("x", "")


class TestJwt:
    def test_roundtrip(self):
        token = jwt_encode({"sub": "alice", "uid": 1}, SECRET, expire_seconds=60)
        payload = jwt_decode(token, SECRET)
        assert payload["sub"] == "alice" and payload["uid"] == 1
        assert "exp" in payload and "iat" in payload

    def test_expired(self):
        token = jwt_encode({"sub": "alice"}, SECRET, expire_seconds=-1)
        with pytest.raises(TokenExpiredError):
            jwt_decode(token, SECRET)

    def test_wrong_secret(self):
        token = jwt_encode({"sub": "alice"}, SECRET, expire_seconds=60)
        with pytest.raises(TokenError):
            jwt_decode(token, "another-secret")

    def test_tampered_payload(self):
        token = jwt_encode({"sub": "alice", "uid": 1}, SECRET, expire_seconds=60)
        header, payload_b64, sig = token.split(".")
        # 翻转 payload 一个字符，签名必然对不上
        flipped = "A" if payload_b64[0] != "A" else "B"
        tampered = f"{header}.{flipped + payload_b64[1:]}.{sig}"
        with pytest.raises(TokenError):
            jwt_decode(tampered, SECRET)

    def test_rejects_alg_none(self):
        # alg 混淆攻击防御：伪造 alg=none 的令牌必须被拒绝
        import base64
        import json

        def b64(obj):
            return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()

        forged = f"{b64({'alg': 'none', 'typ': 'JWT'})}.{b64({'sub': 'eve', 'uid': 1})}."
        with pytest.raises(TokenError):
            jwt_decode(forged, SECRET)

    def test_malformed(self):
        with pytest.raises(TokenError):
            jwt_decode("not-a-jwt", SECRET)


class TestSnowflake:
    def test_thread_safety_uniqueness(self):
        gen = Snowflake(machine_id=7)
        ids: list[int] = []
        lock = threading.Lock()

        def worker():
            local = [gen.next_id() for _ in range(2000)]
            with lock:
                ids.extend(local)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(ids) == 8000
        assert len(set(ids)) == 8000  # 无重复
        assert ids == sorted(ids)  # 单调递增

    def test_invalid_machine_id(self):
        with pytest.raises(ValueError):
            Snowflake(machine_id=1024)


class TestBase62:
    def test_roundtrip(self):
        for n in (0, 1, 61, 62, 12345, 2**63 - 1):
            assert base62_decode(base62_encode(n)) == n

    def test_no_negative(self):
        with pytest.raises(ValueError):
            base62_encode(-1)
