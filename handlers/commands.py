from telegram import Update, ChatPermissions, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
import time
import asyncio
from handlers.api_client import api_post, api_get, api_bot_get, api_bot_post
import config
from handlers.roles import get_user_role, check_role, ROLE_MOD, ROLE_ADMIN
from handlers.utils import send_ephemeral_reply, delete_message_later, EPHEMERAL_DELAY, edit_or_ephemeral, ADMIN_EPHEMERAL_DELAY, private_only

# Helper to get target user (Returns DB User Tuple or Telegram User Object)
async def get_target_user_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Returns a tuple: (user_id, first_name_or_username)
    """
    # 1. Reply
    if update.message.reply_to_message:
        u = update.message.reply_to_message.from_user
        return (u.id, u.first_name)
    
    # 2. Argument (@username)
    if context.args:
        username = context.args[0]
        try:
            db_user = await api_bot_get("/admin/users/by-username", params={"username": username})
        except Exception:
            db_user = None
        if db_user:
            return (db_user.get("user_id"), db_user.get("username") or username.lstrip("@"))
        
    return None

async def warn_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Permission Check: MOD or higher
    user_role = await get_user_role(update.effective_user.id)
    if not check_role(user_role, ROLE_MOD):
        return # Silent ignore

    target_info = await get_target_user_info(update, context)
    if not target_info:
        await send_ephemeral_reply(update, context, "Please reply to a user or mention them (@username) to warn.")
        return

    user_id, name = target_info
    reason = ""
    if context.args:
        if update.message.reply_to_message:
            reason = " ".join(context.args)
        elif len(context.args) > 1:
            reason = " ".join(context.args[1:])
    try:
        data = await api_bot_post("/api/moderation/warn", json_body={
            "actor_id": update.effective_user.id,
            "target_id": user_id,
            "reason": reason
        })
        count = data.get("warnings", 0)
    except Exception as exc:
        await send_ephemeral_reply(update, context, f"⚠️ Failed to warn user: {exc}")
        return
    
    await send_ephemeral_reply(
        update,
        context,
        f"⚠️ User <b>{name}</b> warned.\\nTotal: <b>{count}/{config.WARNING_LIMIT}</b>",
        parse_mode="HTML"
    )
    
    # Check for mute threshold
    if count >= config.WARNING_LIMIT:
        try:
            await mute_user_logic_by_id(update.effective_chat, user_id, name, config.MUTE_DURATION_MINUTES, context=context)
            try:
                await api_bot_post("/api/moderation/mute", json_body={
                    "actor_id": update.effective_user.id,
                    "target_id": user_id,
                    "reason": reason or "auto mute after warnings"
                })
            except Exception:
                pass
        except Exception as e:
            await send_ephemeral_reply(update, context, f"Warned, but failed to mute: {e}")

async def moderation_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    
    # Permission Check
    user_role = await get_user_role(user_id)
    if not check_role(user_role, ROLE_MOD):
        await query.answer("🚫 You don't have permission!", show_alert=True)
        return

    data = query.data # mod_action_targetid_opt
    parts = data.split("_")
    action = parts[1]
    target_id = int(parts[2])
    
    if action == "reset":
        await api_bot_post(f"/admin/users/{target_id}/warnings/reset", json_body={})
        await query.answer("✅ Warnings reset!", show_alert=True)
        await edit_or_ephemeral(query.message, f"✅ Warnings reset for user ID: {target_id}")
        
    elif action == "ban":
        try:
            await update.effective_chat.ban_member(target_id)
            await query.answer("🔨 Banned!", show_alert=True)
            await edit_or_ephemeral(query.message, f"🔨 User ID {target_id} has been banned.")
            try:
                await api_bot_post("/api/moderation/ban", json_body={
                    "actor_id": user_id,
                    "target_id": target_id,
                    "reason": "callback ban"
                })
            except Exception:
                pass
        except Exception as e:
            await query.answer(f"Error: {e}", show_alert=True)
            
    elif action == "mute":
        duration = int(parts[3])
        try:
            await update.effective_chat.restrict_member(
                target_id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=time.time() + (duration * 60)
            )
            await query.answer(f"🔇 Muted for {duration}m", show_alert=True)
            await edit_or_ephemeral(query.message, f"🚫 User ID {target_id} muted for {duration} minutes.")
            try:
                await api_bot_post("/api/moderation/mute", json_body={
                    "actor_id": user_id,
                    "target_id": target_id,
                    "reason": f"callback mute {duration}m"
                })
            except Exception:
                pass
        except Exception as e:
            await query.answer(f"Error: {e}", show_alert=True)

async def mute_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Permission Check: MOD or higher
    user_role = await get_user_role(update.effective_user.id)
    if not check_role(user_role, ROLE_MOD):
        return

    target_info = await get_target_user_info(update, context)
    if not target_info:
        await send_ephemeral_reply(update, context, "Please reply to a user or mention them to mute.")
        return
        
    user_id, name = target_info
    
    # Default to config, or parse args
    duration = config.MUTE_DURATION_MINUTES
    # Check args for duration (args[1] if username provided, args[0] if reply)
    # This basic logic assumes duration is the last arg if present and numeric
    if context.args:
        try:
            if context.args[-1].isdigit():
                duration = int(context.args[-1])
        except:
            pass
            
    await mute_user_logic_by_id(update.effective_chat, user_id, name, duration, context=context)
    reason = ""
    if context.args:
        if update.message.reply_to_message:
            reason = " ".join(context.args)
        elif len(context.args) > 1:
            reason = " ".join(context.args[1:-1]) if context.args[-1].isdigit() else " ".join(context.args[1:])
    try:
        await api_bot_post("/api/moderation/mute", json_body={
            "actor_id": update.effective_user.id,
            "target_id": user_id,
            "reason": reason or f"mute {duration}m"
        })
    except Exception:
        pass

async def mute_user_logic_by_id(chat, user_id, name, duration_minutes, context=None):
    try:
        await chat.restrict_member(
            user_id,
            permissions=ChatPermissions(can_send_messages=False),
            until_date=time.time() + (duration_minutes * 60)
        )
        msg = await chat.send_message(f"🚫 <b>{name}</b> muted for {duration_minutes} minutes.", parse_mode="HTML")
        try:
            if context and getattr(chat, "type", None) in ["group", "supergroup"]:
                asyncio.create_task(delete_message_later(msg, EPHEMERAL_DELAY))
        except Exception:
            pass
    except Exception as e:
        if context:
            await context.bot.send_message(chat_id=chat.id, text=f"Failed to mute: {e}")

async def ban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Permission Check: ADMIN or higher
    user_role = await get_user_role(update.effective_user.id)
    if not check_role(user_role, ROLE_ADMIN):
        return

    target_info = await get_target_user_info(update, context)
    if not target_info:
        await send_ephemeral_reply(update, context, "Please reply to a user or mention them to ban.", delay=ADMIN_EPHEMERAL_DELAY)
        return
    
    user_id, name = target_info
    try:
        await update.effective_chat.ban_member(user_id)
        await send_ephemeral_reply(update, context, f"🔨 <b>{name}</b> has been banned.", parse_mode="HTML", delay=ADMIN_EPHEMERAL_DELAY)
        reason = ""
        if context.args:
            if update.message.reply_to_message:
                reason = " ".join(context.args)
            elif len(context.args) > 1:
                reason = " ".join(context.args[1:])
        try:
            await api_bot_post("/api/moderation/ban", json_body={
                "actor_id": update.effective_user.id,
                "target_id": user_id,
                "reason": reason
            })
        except Exception:
            pass
    except Exception as e:
        await send_ephemeral_reply(update, context, f"Failed to ban: {e}", delay=ADMIN_EPHEMERAL_DELAY)

async def unmute_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Permission Check: MOD or higher (assuming Mods can unmute too, usually yes, or Admin?)
    # Prompt says "MOD -> warn, mute". Usually Mod implies unmute too. 
    # But let's restrict Unmute to MOD as well.
    user_role = await get_user_role(update.effective_user.id)
    if not check_role(user_role, ROLE_MOD):
        return

    target_info = await get_target_user_info(update, context)
    if not target_info:
        await send_ephemeral_reply(update, context, "Please reply to a user or mention them to unmute.")
        return
        
    user_id, name = target_info
    try:
        permissions = ChatPermissions(
            can_send_messages=True,
            can_send_media_messages=True,
            can_send_other_messages=True,
            can_send_polls=True
        )
        await update.effective_chat.restrict_member(user_id, permissions=permissions)
        await send_ephemeral_reply(update, context, f"🔊 <b>{name}</b> unmuted.", parse_mode="HTML")
    except Exception as e:
        await send_ephemeral_reply(update, context, f"Failed to unmute: {e}")

async def reset_warn_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Permission Check: MOD or higher (Managing warnings is mod duty)
    user_role = await get_user_role(update.effective_user.id)
    if not check_role(user_role, ROLE_MOD):
        return

    target_info = await get_target_user_info(update, context)
    if not target_info:
        await send_ephemeral_reply(update, context, "Please reply to a user or mention them.")
        return

    user_id, name = target_info
    await api_bot_post(f"/admin/users/{user_id}/warnings/reset", json_body={})
    await send_ephemeral_reply(update, context, f"Warnings reset for <b>{name}</b>.", parse_mode="HTML")

@private_only
async def user_info_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        data = await api_get("/api/me", user_id=update.effective_user.id)
    except Exception as exc:
        await send_ephemeral_reply(update, context, f"⚠️ Failed to load profile: {exc}")
        return

    club = data.get("club")
    club_label = club.get("label") if isinstance(club, dict) else None
    interests = data.get("interests") or []
    interests_text = ", ".join(interests) if interests else "Not set"

    text = (
        "👤 <b>Your Profile</b>\n\n"
        f"🆔 ID: <code>{data.get('id')}</code>\n"
        f"🔰 Role: {data.get('role', 'user')}\n"
        f"🛡️ Club: <b>{club_label or 'Not set'}</b>\n"
        f"💰 Coins: {data.get('coins', 0)}\n"
        f"📺 Interests: {interests_text}"
    )
    await send_ephemeral_reply(update, context, text, parse_mode="HTML", delete_in_private=True)
