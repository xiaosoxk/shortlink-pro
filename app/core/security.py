"""安全原语：密码哈希（PBKDF2）+ 手写 HS256 JWT。

为什么不用 bcrypt/passlib？
- bcrypt 依赖 C 扩展且 passlib 与 bcrypt>=4.1 存在兼容性警告；
- PBKDF2-HMAC-SHA256 是 NIST 认可的 KDF，纯标准库实现，跨平台零依赖；
- 工程上更重要的是：加盐、迭代次数可调、常数时间比较，这三点这里全做到了。

为什么手写 JWT？
- HS256 的线格式只有三段 base64url，手写一遍 = 能对着字节讲清 JWT 结构，
  同时天然覆盖"alg 混淆攻击"防御（解码时强制校验 alg）。
"""
import base64
import hashlib
import hmac
import json
import secrets
import time


# ---------------- 密码 ----------------

def hash_password(password: str, *, iterations: int = 200_000) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """常数时间比较防时序攻击；格式错误一律返回 False 而不是抛异常。"""
    try:
        algo, iterations, salt_hex, hash_hex = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt_hex), int(iterations)
        )
        return hmac.compare_digest(dk.hex(), hash_hex)
    except (ValueError, TypeError):
        return False


# ---------------- JWT (HS256) ----------------

class TokenError(Exception):
    """JWT 无效（格式/签名）。"""


class TokenExpiredError(TokenError):
    """JWT 已过期（单独区分，便于前端引导刷新登录）。"""


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64url_decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def jwt_encode(
    payload: dict,
    secret: str,
    *,
    algorithm: str = "HS256",
    expire_seconds: int = 86_400,
) -> str:
    header = {"alg": algorithm, "typ": "JWT"}
    now = int(time.time())
    body = {**payload, "iat": now, "exp": now + expire_seconds}
    signing_input = "{}.{}".format(
        _b64url_encode(json.dumps(header, separators=(",", ":")).encode()),
        _b64url_encode(json.dumps(body, separators=(",", ":")).encode()),
    )
    signature = hmac.new(secret.encode(), signing_input.encode(), hashlib.sha256).digest()
    return f"{signing_input}.{_b64url_encode(signature)}"


def jwt_decode(token: str, secret: str) -> dict:
    try:
        header_b64, payload_b64, signature_b64 = token.split(".")
    except ValueError as exc:
        raise TokenError("malformed token") from exc

    # 解码/签名校验全程兜底：任何二进制垃圾都必须落成 TokenError，
    # 决不能让 UnicodeDecodeError 之类裸异常穿透成 500
    try:
        header = json.loads(_b64url_decode(header_b64))
        if header.get("alg") != "HS256":
            # 防 alg 混淆攻击：不接受 "none" / RS256 等
            raise TokenError("unexpected algorithm")

        signing_input = f"{header_b64}.{payload_b64}".encode()
        expected = hmac.new(secret.encode(), signing_input, hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _b64url_decode(signature_b64)):
            raise TokenError("bad signature")

        payload = json.loads(_b64url_decode(payload_b64))
    except TokenError:
        raise
    except Exception as exc:  # noqa: BLE001 - 统一归一为 TokenError
        raise TokenError("malformed token") from exc

    exp = payload.get("exp")
    if not isinstance(exp, (int, float)) or time.time() > exp:
        raise TokenExpiredError("token expired")
    return payload
