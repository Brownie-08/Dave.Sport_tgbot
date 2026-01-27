import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any, Dict, Optional

import aiohttp

import config

API_BASE_URL = (os.getenv("API_BASE_URL", "").strip() or config.API_BASE_URL or "http://localhost:8080").rstrip("/")
JWT_SECRET = os.getenv("JWT_SECRET") or (config.BOT_TOKEN or "change_me")
BOT_SERVICE_TOKEN = os.getenv("BOT_SERVICE_TOKEN") or config.BOT_SERVICE_TOKEN or ""


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def create_jwt(payload: Dict[str, Any], secret: str, exp_seconds: int = 3600) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    now = int(time.time())
    payload = {**payload, "iat": now, "exp": now + exp_seconds}
    header_b64 = _b64url_encode(json.dumps(header, separators=(",", ":")).encode())
    payload_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode())
    signing_input = f"{header_b64}.{payload_b64}".encode()
    signature = hmac.new(secret.encode(), signing_input, hashlib.sha256).digest()
    signature_b64 = _b64url_encode(signature)
    return f"{header_b64}.{payload_b64}.{signature_b64}"


async def api_request(
    method: str,
    path: str,
    user_id: Optional[int] = None,
    json_body: Optional[Dict[str, Any]] = None,
    params: Optional[Dict[str, Any]] = None,
    as_bot: bool = False
) -> Dict[str, Any]:
    if not API_BASE_URL:
        raise RuntimeError("API base URL not configured")
    url = f"{API_BASE_URL}{path}"
    headers = {}
    if as_bot:
        if not BOT_SERVICE_TOKEN:
            raise RuntimeError("Bot service token not configured")
        headers["X-Bot-Token"] = BOT_SERVICE_TOKEN
    if user_id is not None:
        token = create_jwt({"sub": int(user_id)}, JWT_SECRET)
        headers["Authorization"] = f"Bearer {token}"
    if json_body is not None:
        headers["Content-Type"] = "application/json"
    timeout = aiohttp.ClientTimeout(total=10)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.request(method, url, json=json_body, params=params, headers=headers) as resp:
            text = await resp.text()
            if resp.status >= 400:
                try:
                    data = json.loads(text) if text else {}
                except Exception:
                    data = {}
                error = data.get("error") or f"API error {resp.status}"
                raise RuntimeError(error)
            if not text:
                return {}
            try:
                return json.loads(text)
            except Exception:
                return {}


async def api_get(path: str, user_id: Optional[int] = None, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return await api_request("GET", path, user_id=user_id, params=params)


async def api_post(path: str, user_id: Optional[int] = None, json_body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return await api_request("POST", path, user_id=user_id, json_body=json_body)


async def api_bot_get(path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return await api_request("GET", path, params=params, as_bot=True)


async def api_bot_post(path: str, json_body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return await api_request("POST", path, json_body=json_body, as_bot=True)


async def api_bot_delete(path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return await api_request("DELETE", path, params=params, as_bot=True)
