import base64
import hashlib
import hmac
import json
import os
import time
from typing import Dict, Any
from urllib.parse import parse_qsl


JWT_SECRET = (os.getenv("JWT_SECRET") or os.getenv("BOT_TOKEN") or "").strip() or "change_me"


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def create_jwt(payload: Dict[str, Any], secret: str = JWT_SECRET, exp_seconds: int = 86400) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    now = int(time.time())
    payload = {**payload, "iat": now, "exp": now + exp_seconds}
    header_b64 = _b64url_encode(json.dumps(header, separators=(",", ":")).encode())
    payload_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode())
    signing_input = f"{header_b64}.{payload_b64}".encode()
    signature = hmac.new(secret.encode(), signing_input, hashlib.sha256).digest()
    signature_b64 = _b64url_encode(signature)
    return f"{header_b64}.{payload_b64}.{signature_b64}"


def verify_jwt(token: str, secret: str = JWT_SECRET) -> Dict[str, Any]:
    try:
        header_b64, payload_b64, signature_b64 = token.split(".")
    except ValueError:
        raise ValueError("invalid_token")
    signing_input = f"{header_b64}.{payload_b64}".encode()
    expected_sig = hmac.new(secret.encode(), signing_input, hashlib.sha256).digest()
    if not hmac.compare_digest(_b64url_encode(expected_sig), signature_b64):
        raise ValueError("invalid_token")
    payload = json.loads(_b64url_decode(payload_b64))
    exp = payload.get("exp")
    if exp and int(time.time()) > int(exp):
        raise ValueError("token_expired")
    return payload


def parse_init_data(init_data: str) -> Dict[str, Any]:
    data = dict(parse_qsl(init_data, strict_parsing=True))
    if "user" in data:
        try:
            data["user"] = json.loads(data["user"])
        except Exception:
            pass
    return data


def verify_init_data(init_data: str, bot_token: str, max_age: int = 86400) -> Dict[str, Any]:
    data = dict(parse_qsl(init_data, strict_parsing=True))
    received_hash = data.pop("hash", None)
    if not received_hash:
        raise ValueError("missing_hash")
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    
    # Correct Telegram Web App secret key calculation
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    
    if not hmac.compare_digest(calculated_hash, received_hash):
        raise ValueError("invalid_hash")
    auth_date = int(data.get("auth_date", "0") or 0)
    if max_age and auth_date and time.time() - auth_date > max_age:
        raise ValueError("init_data_expired")
    return parse_init_data(init_data)
