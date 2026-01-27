import os
from pathlib import Path
from typing import Optional, List

from fastapi import FastAPI, HTTPException, Depends, Header, Query
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import config
from backend import auth as auth_utils
from backend.db import init_db
from backend import service
from shared_constants import CLUBS_DATA, INTERESTS


app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify the actual frontend URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

WEBAPP_DIR = Path(__file__).resolve().parents[1] / "webapp"


class TelegramAuthPayload(BaseModel):
    initData: str


class PredictionPayload(BaseModel):
    match_id: int
    choice: str
    score_a: Optional[int] = None
    score_b: Optional[int] = None


class MatchCreatePayload(BaseModel):
    team_a: str
    team_b: str
    match_time: Optional[str] = None
    sport_type: Optional[str] = "football"
    chat_id: Optional[int] = None


class MatchResolvePayload(BaseModel):
    winner_code: str
    score_a: Optional[int] = None
    score_b: Optional[int] = None
    reward: Optional[int] = 0


class MatchTimePayload(BaseModel):
    match_time: str


class BalanceAdjustPayload(BaseModel):
    amount: int


class RolePayload(BaseModel):
    role: str


class ModerationPayload(BaseModel):
    actor_id: int
    target_id: int
    reason: Optional[str] = ""


class EnsureUserPayload(BaseModel):
    user_id: int
    username: Optional[str] = None
    invited_by: Optional[int] = None


class PreferencePayload(BaseModel):
    pref_name: str
    value: int

class AdminProfilePayload(BaseModel):
    club: Optional[str] = None
    interests: Optional[str] = None


class LinkPayload(BaseModel):
    url: str
    chat_id: int
    message_id: int


class LinkClickPayload(BaseModel):
    user_id: int


class ReactionPayload(BaseModel):
    user_id: int
    message_id: int
    chat_id: int


class GroupPayload(BaseModel):
    chat_id: int
    chat_title: Optional[str] = ""
    chat_type: Optional[str] = ""


class DavesportSubscribePayload(BaseModel):
    chat_id: int
    twitter: Optional[bool] = True
    website: Optional[bool] = True
    sport_filter: Optional[str] = "all"


class DavesportCategoryPayload(BaseModel):
    chat_id: int
    category: str
    thread_id: Optional[int] = None


class DavesportPostPayload(BaseModel):
    post_id: str
    chat_id: int
    source: str
    message_id: Optional[int] = 0


def get_current_user(authorization: str = Header(default="")) -> int:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing_token")
    token = authorization.replace("Bearer ", "", 1).strip()
    try:
        payload = auth_utils.verify_jwt(token)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    return int(payload.get("sub"))


def require_bot(x_bot_token: Optional[str] = Header(default=None), authorization: str = Header(default="")) -> None:
    bot_token = (os.getenv("BOT_SERVICE_TOKEN") or "").strip()
    if not bot_token:
        raise HTTPException(status_code=500, detail="bot_service_token_missing")
    
    # Check for bot service token
    if x_bot_token and x_bot_token == bot_token:
        return None
    if authorization.startswith("Bot "):
        token = authorization.replace("Bot ", "", 1).strip()
        if token == bot_token:
            return None
            
    # Also allow authenticated admins/owners
    if authorization.startswith("Bearer "):
        token = authorization.replace("Bearer ", "", 1).strip()
        try:
            payload = auth_utils.verify_jwt(token)
            role = (payload.get("role") or "MEMBER").upper()
            if role in ["ADMIN", "OWNER"]:
                return None
        except Exception:
            pass

    raise HTTPException(status_code=403, detail="invalid_bot_token_or_not_admin")


def get_admin_user(user_id: int = Depends(get_current_user)) -> int:
    role = service.get_user_role(user_id)
    if role not in ["ADMIN", "OWNER"]:
        raise HTTPException(status_code=403, detail="admin_only")
    return user_id


@app.on_event("startup")
def on_startup():
    init_db()


@app.get("/api/health")
def health():
    return {"ok": True}


def _telegram_auth(payload: TelegramAuthPayload):
    if not config.BOT_TOKEN:
        raise HTTPException(status_code=500, detail="bot_token_missing")
    try:
        parsed = auth_utils.verify_init_data(payload.initData, config.BOT_TOKEN)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    tg_user = parsed.get("user") or {}
    user_id = int(tg_user.get("id"))
    username = tg_user.get("username") or tg_user.get("first_name") or ""
    service.ensure_user(user_id, username)
    role = service.get_user_role(user_id)
    token = auth_utils.create_jwt({"sub": user_id, "username": username, "role": role})
    return {
        "token": token,
        "user": {"id": user_id, "username": username, "role": role},
    }


@app.post("/auth/telegram")
def auth_telegram(payload: TelegramAuthPayload):
    return _telegram_auth(payload)


@app.post("/api/auth/telegram")
def auth_telegram_legacy(payload: TelegramAuthPayload):
    return _telegram_auth(payload)


@app.get("/api/user/me")
def api_user_me(user_id: int = Depends(get_current_user)):
    return service.build_me_response(user_id)


@app.get("/api/balance")
def api_balance(user_id: int = Depends(get_current_user)):
    return {"coins": service.get_balance(user_id)}


@app.get("/api/matches")
def api_matches(user_id: int = Depends(get_current_user)):
    return {"items": service.get_open_matches()}


@app.post("/api/predictions")
def api_predictions_place_v2(payload: PredictionPayload, user_id: int = Depends(get_current_user)):
    try:
        service.add_prediction(user_id, payload.match_id, payload.choice, payload.score_a, payload.score_b)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"success": True}


@app.get("/api/leaderboards")
def api_leaderboards_combined(
    type: str = Query(default="global"),
    page: int = Query(default=1),
    limit: int = Query(default=25),
    user_id: int = Depends(get_current_user),
):
    if type == "predictions":
        return service.get_leaderboard_predictions(page, limit, user_id)
    return service.get_leaderboard_global(page, limit, user_id)


@app.get("/api/me")
def api_me(user_id: int = Depends(get_current_user)):
    data = service.build_me_response(user_id)
    data["clubs"] = [
        {"key": key, "label": info.get("name", key), "badge": info.get("badge")}
        for key, info in CLUBS_DATA.items()
    ]
    data["interests_options"] = INTERESTS
    return data


@app.patch("/api/me")
def api_me_update(payload: dict, user_id: int = Depends(get_current_user)):
    club = payload.get("club")
    interests = payload.get("interests")
    try:
        data = service.update_me(user_id, club, interests)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    data["clubs"] = [
        {"key": key, "label": info.get("name", key), "badge": info.get("badge")}
        for key, info in CLUBS_DATA.items()
    ]
    data["interests_options"] = INTERESTS
    return data


@app.get("/user/balance")
def user_balance(user_id: int = Depends(get_current_user)):
    return {"coins": service.get_balance(user_id)}


@app.get("/api/wallet")
def api_wallet(user_id: int = Depends(get_current_user)):
    return {"coins": service.get_balance(user_id)}


@app.post("/api/rewards/daily")
def api_daily(user_id: int = Depends(get_current_user)):
    return service.claim_daily(user_id, reward_amount=2)


@app.get("/user/predictions")
def user_predictions(user_id: int = Depends(get_current_user)):
    items = service.get_predictions_history(user_id)
    return {"items": items}


@app.get("/api/predictions/history")
def api_predictions_history(user_id: int = Depends(get_current_user)):
    return {"items": service.get_predictions_history(user_id)}


@app.get("/api/predictions/stats")
def api_predictions_stats(user_id: int = Depends(get_current_user)):
    return service.get_predictions_stats(user_id)


@app.get("/api/predictions/open")
def api_predictions_open(user_id: int = Depends(get_current_user)):
    return {"items": service.get_open_matches()}


@app.post("/prediction")
def prediction(payload: PredictionPayload, user_id: int = Depends(get_current_user)):
    try:
        service.add_prediction(user_id, payload.match_id, payload.choice, payload.score_a, payload.score_b)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"success": True}


@app.post("/api/predictions/place")
def api_prediction(payload: PredictionPayload, user_id: int = Depends(get_current_user)):
    try:
        service.add_prediction(user_id, payload.match_id, payload.choice, payload.score_a, payload.score_b)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"success": True}


@app.get("/leaderboards")
def leaderboards(
    type: str = Query(default="global"),
    page: int = Query(default=1),
    limit: int = Query(default=25),
    user_id: int = Depends(get_current_user),
):
    if type == "predictions":
        return service.get_leaderboard_predictions(page, limit, user_id)
    return service.get_leaderboard_global(page, limit, user_id)


@app.get("/api/leaderboards/global")
def api_leaderboard_global(page: int = 1, limit: int = 25, user_id: int = Depends(get_current_user)):
    return service.get_leaderboard_global(page, limit, user_id)


@app.get("/api/leaderboards/predictions")
def api_leaderboard_predictions(page: int = 1, limit: int = 25, user_id: int = Depends(get_current_user)):
    return service.get_leaderboard_predictions(page, limit, user_id)


@app.post("/api/moderation/warn")
def api_warn(payload: ModerationPayload, _: None = Depends(require_bot)):
    count = service.warn_user(payload.actor_id, payload.target_id, payload.reason or "")
    return {"warnings": count}


@app.post("/api/moderation/mute")
def api_mute(payload: ModerationPayload, _: None = Depends(require_bot)):
    service.log_mute(payload.actor_id, payload.target_id, payload.reason or "")
    return {"ok": True}


@app.post("/api/moderation/ban")
def api_ban(payload: ModerationPayload, _: None = Depends(require_bot)):
    service.log_ban(payload.actor_id, payload.target_id, payload.reason or "")
    return {"ok": True}


# === Admin endpoints ===
@app.post("/admin/users/ensure")
def admin_ensure_user(payload: EnsureUserPayload, _: None = Depends(require_bot)):
    is_new = service.ensure_user(payload.user_id, payload.username, payload.invited_by)
    rewarded = False
    if is_new and payload.invited_by and payload.invited_by != payload.user_id:
        # reward referrer if exists
        if service.get_user(payload.invited_by):
            service.adjust_balance(payload.invited_by, config.INVITE_REWARD)
            rewarded = True
    return {"is_new": is_new, "rewarded": rewarded}


@app.post("/admin/users/{user_id}/balance")
def admin_adjust_balance(user_id: int, payload: BalanceAdjustPayload, _: None = Depends(require_bot)):
    balance = service.adjust_balance(user_id, payload.amount)
    return {"balance": balance}


@app.post("/admin/users/{user_id}/role")
def admin_set_role(user_id: int, payload: RolePayload, _: None = Depends(require_bot)):
    service.set_user_role(user_id, payload.role.upper())
    return {"role": payload.role.upper()}

@app.get("/admin/users/{user_id}")
def admin_get_user(user_id: int, _: None = Depends(require_bot)):
    user = service.get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="user_not_found")
    return user


@app.post("/admin/users/{user_id}/profile")
def admin_update_profile(user_id: int, payload: AdminProfilePayload, _: None = Depends(require_bot)):
    user = service.update_user_profile_raw(user_id, payload.club, payload.interests)
    if not user:
        raise HTTPException(status_code=404, detail="user_not_found")
    return user


@app.get("/admin/users/{user_id}/preferences")
def admin_get_preferences(user_id: int, _: None = Depends(require_bot)):
    return service.get_user_preferences(user_id)


@app.post("/admin/users/{user_id}/preferences")
def admin_set_preferences(user_id: int, payload: PreferencePayload, _: None = Depends(require_bot)):
    service.update_user_preference(user_id, payload.pref_name, payload.value)
    return {"ok": True}


@app.post("/admin/users/{user_id}/warnings/reset")
def admin_reset_warnings(user_id: int, _: None = Depends(require_bot)):
    service.reset_warnings(user_id)
    return {"ok": True}


@app.get("/admin/users/by-username")
def admin_get_user_by_username(username: str, _: None = Depends(require_bot)):
    user = service.get_user_by_username(username)
    if not user:
        raise HTTPException(status_code=404, detail="user_not_found")
    return user


@app.post("/admin/matches")
def admin_create_match(payload: MatchCreatePayload, _: None = Depends(require_bot)):
    match_id = service.create_match(payload.team_a, payload.team_b, payload.match_time, payload.sport_type or "football", payload.chat_id)
    return {"match_id": match_id}


@app.get("/admin/matches/active")
def admin_active_matches(_: None = Depends(require_bot)):
    return {"items": service.get_active_matches()}


@app.get("/admin/matches/{match_id}")
def admin_get_match(match_id: int, _: None = Depends(require_bot)):
    match = service.get_match(match_id)
    if not match:
        raise HTTPException(status_code=404, detail="match_not_found")
    return match


@app.post("/admin/matches/{match_id}/close")
def admin_close_match(match_id: int, _: None = Depends(require_bot)):
    service.close_match(match_id)
    return {"ok": True}


@app.post("/admin/matches/{match_id}/resolve")
def admin_resolve_match(match_id: int, payload: MatchResolvePayload, _: None = Depends(require_bot)):
    winners = service.resolve_match(match_id, payload.winner_code, payload.score_a, payload.score_b, payload.reward or 0)
    return {"winners": winners, "count": len(winners)}


@app.post("/admin/matches/{match_id}/time")
def admin_set_match_time(match_id: int, payload: MatchTimePayload, _: None = Depends(require_bot)):
    service.update_match_time(match_id, payload.match_time)
    return {"ok": True}


@app.delete("/admin/matches/{match_id}")
def admin_delete_match(match_id: int, _: None = Depends(require_bot)):
    service.delete_match(match_id)
    return {"ok": True}


@app.post("/admin/links")
def admin_create_link(payload: LinkPayload, _: None = Depends(require_bot)):
    link_id = service.create_tracked_link(payload.url, payload.chat_id, payload.message_id)
    return {"link_id": link_id}


@app.post("/admin/links/{link_id}/click")
def admin_record_link_click(link_id: int, payload: LinkClickPayload, _: None = Depends(require_bot)):
    created = service.record_link_click(payload.user_id, link_id)
    return {"created": created}

@app.post("/admin/links/{link_id}/clicks")
def admin_record_link_clicks(link_id: int, payload: LinkClickPayload, _: None = Depends(require_bot)):
    created = service.record_link_click(payload.user_id, link_id)
    return {"created": created}


@app.get("/admin/links/{link_id}/clicked")
def admin_has_clicked(link_id: int, user_id: int, _: None = Depends(require_bot)):
    clicked = service.has_user_clicked_link(user_id, link_id)
    return {"clicked": clicked, "already_clicked": clicked}


@app.get("/admin/links/{link_id}/clicks")
def admin_has_clicked_v2(link_id: int, user_id: int, _: None = Depends(require_bot)):
    clicked = service.has_user_clicked_link(user_id, link_id)
    return {"already_clicked": clicked}



@app.post("/admin/reactions")
def admin_record_reaction(payload: ReactionPayload, _: None = Depends(require_bot)):
    created = service.record_reaction_reward(payload.user_id, payload.message_id, payload.chat_id)
    return {"created": created}


@app.get("/admin/reactions/check")
def admin_has_reacted(user_id: int, message_id: int, _: None = Depends(require_bot)):
    reacted = service.has_user_reacted(user_id, message_id)
    return {"reacted": reacted, "already_reacted": reacted}


@app.get("/admin/notifications/users")
def admin_notification_users(pref: str = "match_reminders", _: None = Depends(require_bot)):
    return {"user_ids": service.get_users_for_notification(pref)}


@app.get("/admin/notifications/result-recipients")
def admin_result_recipients(match_id: int, _: None = Depends(require_bot)):
    return {"user_ids": service.get_result_notification_users(match_id)}


@app.post("/admin/groups")
def admin_add_group(payload: GroupPayload, _: None = Depends(require_bot)):
    service.add_group(payload.chat_id, payload.chat_title or "", payload.chat_type or "")
    return {"ok": True}


@app.delete("/admin/groups/{chat_id}")
def admin_remove_group(chat_id: int, _: None = Depends(require_bot)):
    service.remove_group(chat_id)
    return {"ok": True}


@app.get("/admin/groups/{chat_id}/feed-status")
def admin_feed_status(chat_id: int, _: None = Depends(require_bot)):
    return service.get_feed_status(chat_id)


@app.get("/admin/groups")
def admin_list_groups(_: None = Depends(require_bot)):
    groups = service.get_groups()
    chat_ids = [g["chat_id"] for g in groups]
    return {"chat_ids": chat_ids, "groups": groups}


@app.post("/admin/davesport/subscribe")
def admin_davesport_sub(payload: DavesportSubscribePayload, _: None = Depends(require_bot)):
    service.subscribe_chat(payload.chat_id, payload.twitter, payload.website, payload.sport_filter or "all")
    return {"ok": True}


@app.post("/admin/davesport/unsubscribe")
def admin_davesport_unsub(payload: DavesportSubscribePayload, _: None = Depends(require_bot)):
    service.unsubscribe_chat(payload.chat_id)
    return {"ok": True}


@app.get("/admin/davesport/subscribers")
def admin_davesport_subscribers(_: None = Depends(require_bot)):
    return {"items": service.get_subscribed_chats()}


@app.post("/admin/davesport/category")
def admin_davesport_category(payload: DavesportCategoryPayload, _: None = Depends(require_bot)):
    service.set_chat_category(payload.chat_id, payload.category, payload.thread_id)
    return {"ok": True}


@app.post("/admin/davesport/category/remove")
def admin_davesport_category_remove(payload: DavesportCategoryPayload, _: None = Depends(require_bot)):
    service.remove_chat_category(payload.chat_id, payload.category)
    return {"ok": True}


@app.get("/admin/davesport/chats")
def admin_davesport_chats(category: str, _: None = Depends(require_bot)):
    return {"items": service.get_chats_for_category(category)}


@app.get("/admin/davesport/categories")
def admin_davesport_categories(chat_id: int, _: None = Depends(require_bot)):
    return {"items": service.get_chat_categories(chat_id)}


@app.get("/admin/davesport/posts/sent")
def admin_davesport_post_sent(post_id: str, chat_id: int, _: None = Depends(require_bot)):
    return {"sent": service.is_post_sent(post_id, chat_id)}


@app.post("/admin/davesport/posts/mark")
def admin_davesport_post_mark(payload: DavesportPostPayload, _: None = Depends(require_bot)):
    service.mark_post_sent(payload.post_id, payload.chat_id, payload.source, payload.message_id or 0)
    return {"ok": True}


# Serve the existing static webapp (temporary until Next.js replaces it)
if WEBAPP_DIR.exists():
    app.mount("/", StaticFiles(directory=str(WEBAPP_DIR), html=True), name="webapp")
else:
    @app.get("/{path:path}")
    def fallback(path: str):
        raise HTTPException(status_code=404, detail="not_found")
