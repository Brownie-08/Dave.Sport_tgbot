from telegram import Update, ChatPermissions, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from telegram.constants import ChatMemberStatus
import re
import time
import asyncio
import config
from handlers.roles import get_user_role, check_role, ROLE_MOD, ROLE_VIP
from handlers.api_client import api_bot_post

# Flood & Cooldown Control
# FLOOD_CACHE: {user_id: [timestamp1, timestamp2]}
FLOOD_CACHE = {}
FLOOD_WINDOW = 5
FLOOD_LIMIT = 5

# COMMENT_COOLDOWN: {user_id: last_comment_timestamp}
COMMENT_COOLDOWN = {}
COMMENT_COOLDOWN_SEC = 5 # Minimum seconds between rewarded comments

async def is_user_admin(chat, user_id):
    try:
        member = await chat.get_member(user_id)
        return member.status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]
    except:
        return False

async def moderate_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.from_user:
        return

    # Ignore bot's own messages to prevent loops
    if update.message.from_user.id == context.bot.id:
        return

    user = update.message.from_user
    chat = update.effective_chat
    message_text = update.message.text or update.message.caption or ""
    
    # 1. Track User (ensure user exists in backend)
    try:
        await api_bot_post("/admin/users/ensure", {
            "user_id": user.id,
            "username": user.username or ""
        })
    except Exception:
        pass
    
    # 2. Get User Role
    user_role = await get_user_role(user.id)
    is_privileged = check_role(user_role, ROLE_MOD) or await is_user_admin(chat, user.id)
    
    # 3. URL Detection & Auto-Conversion (Admins/Mods Only)
    # Regex for http/https links
    url_pattern = re.compile(r'(https?://\S+)')
    found_urls = url_pattern.findall(message_text)
    
    if found_urls:
        if is_privileged:
            # -- ADMIN POSTED LINK --
            # Strategy: Add reward buttons so users can earn coins for engaging
            
            target_url = found_urls[0]  # Take the first link
            
            # Create Database Entry for tracking via backend
            try:
                data = await api_bot_post("/admin/links", {
                    "url": target_url,
                    "chat_id": chat.id,
                    "message_id": update.message.id
                })
                link_id = data.get("link_id")
            except Exception as e:
                print(f"Failed to create tracked link: {e}")
                return
            
            # Reward button UI - user must open link then claim
            keyboard = [
                [InlineKeyboardButton("🚀 Open Link", url=target_url)],
                [InlineKeyboardButton(f"🎁 Claim +{config.LINK_CLICK_REWARD} Coins", callback_data=f"clk_{link_id}")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # Send reward panel as reply to the link message
            try:
                await context.bot.send_message(
                    chat_id=chat.id,
                    reply_to_message_id=update.message.id,
                    text="👇 <b>Open the link above, then claim your reward!</b>",
                    reply_markup=reply_markup,
                    parse_mode="HTML"
                )
            except Exception as e:
                print(f"Failed to reply with rewards: {e}")
                
            return  # Stop processing, we handled the link

        else:
            # -- REGULAR USER POSTED LINK --
            # "Either blocked Or ignored"
            # We will Block (Delete) to enforce clean chat, unless VIP?
            # Let's delete for now to prevent spam.
            if not check_role(user_role, ROLE_VIP):
                try:
                    await update.message.delete()
                    warning_count = await warn_user_via_api(context, user.id, "sending links")
                    await handle_warning(update, context, user, warning_count, "sending links")
                except:
                    pass
                return

    # 4. Comment Rewards (Anti-Spam)
    # Only reward if text is long enough? or just any text.
    # Check cooldown.
    current_time = time.time()
    last_comment_time = COMMENT_COOLDOWN.get(user.id, 0)
    
    if current_time - last_comment_time > COMMENT_COOLDOWN_SEC:
        try:
            await api_bot_post(f"/admin/users/{user.id}/balance", {
                "amount": config.COMMENT_REWARD,
                "reason": "comment"
            })
            COMMENT_COOLDOWN[user.id] = current_time
        except Exception:
            pass
        
    # 5. Flood Control (For everyone except Admins)
    if not is_privileged:
        user_timestamps = FLOOD_CACHE.get(user.id, [])
        user_timestamps = [t for t in user_timestamps if current_time - t < FLOOD_WINDOW]
        user_timestamps.append(current_time)
        FLOOD_CACHE[user.id] = user_timestamps
        
        if len(user_timestamps) > FLOOD_LIMIT:
            try:
                await update.message.delete()
            except:
                pass
            if len(user_timestamps) == FLOOD_LIMIT + 1:
                warning_count = await warn_user_via_api(context, user.id, "flooding")
                await handle_warning(update, context, user, warning_count, "flooding")

async def warn_user_via_api(context: ContextTypes.DEFAULT_TYPE, target_id: int, reason: str) -> int:
    actor_id = getattr(context.bot, "id", 0) if context and context.bot else 0
    try:
        data = await api_bot_post("/api/moderation/warn", json_body={
            "actor_id": actor_id,
            "target_id": target_id,
            "reason": reason
        })
        return data.get("warnings", 0)
    except Exception:
        return 0

async def handle_warning(update, context, user, warning_count, reason):
    chat = update.effective_chat
    
    if warning_count >= config.WARNING_LIMIT:
        # Mute User
        try:
            await chat.restrict_member(
                user.id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=time.time() + (config.MUTE_DURATION_MINUTES * 60)
            )
            await chat.send_message(
                f"🚫 {user.mention_html()} has been muted for {config.MUTE_DURATION_MINUTES} minutes due to repeated violations ({warning_count} warnings).",
                parse_mode="HTML"
            )
            actor_id = getattr(context.bot, "id", 0) if context and context.bot else 0
            try:
                await api_bot_post("/api/moderation/mute", json_body={
                    "actor_id": actor_id,
                    "target_id": user.id,
                    "reason": reason
                })
            except Exception:
                pass
        except Exception as e:
            await chat.send_message(f"Failed to mute user: {e}")
    else:
        msg = await chat.send_message(
            f"⚠️ {user.mention_html()}, warning {warning_count}/{config.WARNING_LIMIT} for {reason}. Read the rules!",
            parse_mode="HTML"
        )
        # Delete warning after a short time
        asyncio.create_task(delete_later(msg))

async def delete_later(message, delay=10):
    await asyncio.sleep(delay)
    try:
        await message.delete()
    except:
        pass
