import json
import time
import hmac
import hashlib
import logging
import os
import base64
import asyncio
from pathlib import Path
from typing import Dict, Any
from urllib.parse import parse_qsl

from aiohttp import web

import config
import api_service
from shared_constants import CLUBS_DATA, INTERESTS


JWT_SECRET = os.getenv("JWT_SECRET") or (config.BOT_TOKEN or "change_me")

def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")

def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)

def create_jwt(payload: Dict[str, Any], secret: str, exp_seconds: int = 86400) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    now = int(time.time())
    payload = {**payload, "iat": now, "exp": now + exp_seconds}
    header_b64 = _b64url_encode(json.dumps(header, separators=(",", ":")).encode())
    payload_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode())
    signing_input = f"{header_b64}.{payload_b64}".encode()
    signature = hmac.new(secret.encode(), signing_input, hashlib.sha256).digest()
    signature_b64 = _b64url_encode(signature)
    return f"{header_b64}.{payload_b64}.{signature_b64}"

def verify_jwt(token: str, secret: str) -> Dict[str, Any]:
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



@web.middleware
async def auth_middleware(request: web.Request, handler):
    if request.path.startswith("/api/") and request.path not in ["/api/health", "/api/auth/telegram"]:
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return web.json_response({"error": "missing_token"}, status=401)
        token = auth.replace("Bearer ", "", 1).strip()
        try:
            payload = verify_jwt(token, JWT_SECRET)
        except ValueError as exc:
            return web.json_response({"error": str(exc)}, status=403)
        request["auth"] = payload
    return await handler(request)

routes = web.RouteTableDef()

@routes.get("/api/health")
async def health(request: web.Request):
    return web.json_response({"ok": True})

@routes.post("/api/auth/telegram")
async def auth_telegram(request: web.Request):
    payload = await request.json()
    init_data = payload.get("initData", "")
    if not init_data:
        return web.json_response({"error": "missing_init_data"}, status=400)
    if not config.BOT_TOKEN:
        return web.json_response({"error": "bot_token_missing"}, status=500)
    try:
        parsed = verify_init_data(init_data, config.BOT_TOKEN)
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=403)
    tg_user = parsed.get("user") or {}
    user_id = int(tg_user.get("id"))
    username = tg_user.get("username") or tg_user.get("first_name") or ""
    await asyncio.to_thread(api_service.upsert_user, user_id, username)
    role = await asyncio.to_thread(api_service.get_user_role, user_id)
    token = create_jwt({"sub": user_id, "username": username, "role": role}, JWT_SECRET)
    return web.json_response({
        "token": token,
        "user": {
            "id": user_id,
            "username": username,
            "role": role
        }
    })

@routes.get("/api/me")
async def me(request: web.Request):
    user_id = int(request["auth"].get("sub"))
    data = await asyncio.to_thread(api_service.get_me, user_id)
    data["clubs"] = [
        {"key": key, "label": info.get("name", key), "badge": info.get("badge")}
        for key, info in CLUBS_DATA.items()
    ]
    data["interests_options"] = INTERESTS
    return web.json_response(data)

@routes.patch("/api/me")
async def update_me(request: web.Request):
    user_id = int(request["auth"].get("sub"))
    payload = await request.json()
    club = payload.get("club")
    interests = payload.get("interests")
    try:
        data = await asyncio.to_thread(api_service.update_me, user_id, club, interests)
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    data["clubs"] = [
        {"key": key, "label": info.get("name", key), "badge": info.get("badge")}
        for key, info in CLUBS_DATA.items()
    ]
    data["interests_options"] = INTERESTS
    return web.json_response(data)

@routes.get("/api/predictions/open")
async def predictions_open(request: web.Request):
    items = await asyncio.to_thread(api_service.get_open_matches)
    return web.json_response({"items": items})

@routes.post("/api/predictions/place")
async def predictions_place(request: web.Request):
    user_id = int(request["auth"].get("sub"))
    payload = await request.json()
    match_id = int(payload.get("match_id", 0))
    choice = payload.get("choice")
    score_a = payload.get("score_a")
    score_b = payload.get("score_b")
    result = await asyncio.to_thread(api_service.place_prediction, user_id, match_id, choice, score_a, score_b)
    status = 200 if result.get("success") else 400
    return web.json_response(result, status=status)

@routes.get("/api/predictions/history")
async def predictions_history(request: web.Request):
    user_id = int(request["auth"].get("sub"))
    items = await asyncio.to_thread(api_service.get_predictions_history, user_id)
    return web.json_response({"items": items})

@routes.get("/api/predictions/stats")
async def predictions_stats(request: web.Request):
    user_id = int(request["auth"].get("sub"))
    stats = await asyncio.to_thread(api_service.get_predictions_stats, user_id)
    return web.json_response(stats)

@routes.get("/api/leaderboards/global")
async def leaderboard_global(request: web.Request):
    user_id = int(request["auth"].get("sub"))
    page = max(int(request.query.get("page", 1)), 1)
    limit = min(max(int(request.query.get("limit", 25)), 1), 100)
    data = await asyncio.to_thread(api_service.get_leaderboard_global, page, limit, user_id)
    return web.json_response({
        **data,
        "page": page,
        "limit": limit
    })

@routes.get("/api/leaderboards/predictions")
async def leaderboard_predictions(request: web.Request):
    user_id = int(request["auth"].get("sub"))
    page = max(int(request.query.get("page", 1)), 1)
    limit = min(max(int(request.query.get("limit", 25)), 1), 100)
    data = await asyncio.to_thread(api_service.get_leaderboard_predictions, page, limit, user_id)
    return web.json_response({
        **data,
        "page": page,
        "limit": limit
    })

@routes.get("/api/wallet")
async def wallet(request: web.Request):
    user_id = int(request["auth"].get("sub"))
    data = await asyncio.to_thread(api_service.get_wallet, user_id)
    return web.json_response(data)

@routes.post("/api/rewards/daily")
async def rewards_daily(request: web.Request):
    user_id = int(request["auth"].get("sub"))
    data = await asyncio.to_thread(api_service.claim_daily, user_id)
    return web.json_response(data)

@routes.post("/api/moderation/warn")
async def moderation_warn(request: web.Request):
    payload = await request.json()
    actor_id = int(payload.get("actor_id", 0))
    target_id = int(payload.get("target_id", 0))
    reason = payload.get("reason", "")
    count = await asyncio.to_thread(api_service.warn_user, actor_id, target_id, reason)
    return web.json_response({"warnings": count})

@routes.post("/api/moderation/mute")
async def moderation_mute(request: web.Request):
    payload = await request.json()
    actor_id = int(payload.get("actor_id", 0))
    target_id = int(payload.get("target_id", 0))
    reason = payload.get("reason", "")
    await asyncio.to_thread(api_service.log_mute, actor_id, target_id, reason)
    return web.json_response({"ok": True})

@routes.post("/api/moderation/ban")
async def moderation_ban(request: web.Request):
    payload = await request.json()
    actor_id = int(payload.get("actor_id", 0))
    target_id = int(payload.get("target_id", 0))
    reason = payload.get("reason", "")
    await asyncio.to_thread(api_service.log_ban, actor_id, target_id, reason)
    return web.json_response({"ok": True})

@routes.get("/{tail:.*}")
async def serve_index(request: web.Request):
    index_path = request.app["index_path"]
    return web.FileResponse(index_path)

async def start_webapp_server():
    app = web.Application(middlewares=[auth_middleware])
    app.add_routes(routes)
    app["index_path"] = str(Path(__file__).parent / "webapp" / "index.html")
    runner = web.AppRunner(app)
    await runner.setup()
    host = os.getenv("WEBAPP_HOST", "0.0.0.0")
    port = int(os.getenv("WEBAPP_PORT", "8080"))
    site = web.TCPSite(runner, host=host, port=port)
    await site.start()
    logging.info(f"WebApp server running on http://{host}:{port}")
    return runner

async def stop_webapp_server(runner: web.AppRunner):
    if runner:
        await runner.cleanup()
