from telegram import Update, Bot
from telegram.ext import ContextTypes
from telegram.constants import ChatMemberStatus
from handlers.api_client import api_get, api_bot_get, api_bot_post
import config
import logging
from handlers.utils import send_ephemeral_reply, ADMIN_EPHEMERAL_DELAY

# Role Constants
ROLE_OWNER = 'OWNER'
ROLE_ADMIN = 'ADMIN'
ROLE_MOD = 'MOD'
ROLE_VIP = 'VIP'
ROLE_MEMBER = 'MEMBER'

# Hierarchy: Higher number = Higher privilege
ROLE_HIERARCHY = {
    ROLE_OWNER: 100,
    ROLE_ADMIN: 80,
    ROLE_MOD: 60,
    ROLE_VIP: 40,
    ROLE_MEMBER: 20
}

def get_role_value(role_name):
    return ROLE_HIERARCHY.get(role_name, 0)

async def is_telegram_admin(bot: Bot, chat_id: int, user_id: int) -> bool:
    """
    Check if a user is an admin/owner in a Telegram chat.
    Returns True if user is admin/owner, or if chat is private (private chats have no admins).
    """
    # Private chats - user is always "admin" of their own chat
    if chat_id > 0:
        return True
    
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]
    except Exception as e:
        logging.debug(f"Error checking Telegram admin status: {e}")
        return False

async def is_admin_or_owner(bot: Bot, chat_id: int, user_id: int) -> bool:
    """
    Check if user has admin permissions. Returns True if:
    - User is the bot OWNER (from config)
    - User has ADMIN role in the bot's database
    - User is a Telegram admin/owner in the chat (for group commands)
    
    This function should be used for admin commands that can work in groups.
    """
    # 1. Check if user is the bot owner
    if user_id == config.OWNER_ID:
        return True
    
    # 2. Check backend role
    try:
        data = await api_get("/user/me", user_id=user_id)
        role = (data.get("role") or "").upper()
        if role in [ROLE_OWNER, ROLE_ADMIN]:
            return True
    except Exception:
        pass
    
    # 3. For group chats, also check if user is a Telegram admin
    if chat_id < 0:  # Negative chat_id means group/supergroup
        return await is_telegram_admin(bot, chat_id, user_id)
    
    return False

async def get_user_role(user_id):
    # 1. Check Config Owner
    if user_id == config.OWNER_ID:
        return ROLE_OWNER
        
    # 2. Check Backend
    try:
        data = await api_get("/user/me", user_id=user_id)
        role = (data.get("role") or "").upper()
        if role in ROLE_HIERARCHY:
            return role
    except Exception:
        pass
            
    return ROLE_MEMBER

def check_role(user_role, required_role):
    """
    Returns True if user_role has equal or higher privilege than required_role.
    """
    return get_role_value(user_role) >= get_role_value(required_role)

async def set_role_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    
    # 1. Check permission of the caller
    caller_role = await get_user_role(user.id)
    if not check_role(caller_role, ROLE_ADMIN):
        await send_ephemeral_reply(update, context, "⛔ You do not have permission to manage roles.")
        return

    # 2. Parse arguments: /setrole @user ROLE
    if len(context.args) < 2:
        await send_ephemeral_reply(update, context, "Usage: /setrole @user ROLE\nAvailable roles: OWNER, ADMIN, MOD, VIP, MEMBER", delay=ADMIN_EPHEMERAL_DELAY)
        return

    target_username = context.args[0]
    new_role = context.args[1].upper()

    # 3. Validate Role
    if new_role not in ROLE_HIERARCHY:
        await send_ephemeral_reply(update, context, f"❌ Invalid role. Choose from: {', '.join(ROLE_HIERARCHY.keys())}", delay=ADMIN_EPHEMERAL_DELAY)
        return

    # 4. Get Target User
    try:
        db_target = await api_bot_get("/admin/users/by-username", params={"username": target_username})
    except Exception:
        db_target = None
    if not db_target:
        await send_ephemeral_reply(update, context, f"❌ User {target_username} not found in database (they must have spoken in the chat).", delay=ADMIN_EPHEMERAL_DELAY)
        return
    
    target_id = db_target.get("user_id")
    current_target_role = db_target.get("role", ROLE_MEMBER)

    # 5. Hierarchy Checks
    # Caller must be higher than the role they are trying to assign (unless Owner)
    # AND Caller must be higher than the target's current role
    
    caller_val = get_role_value(caller_role)
    new_role_val = get_role_value(new_role)
    target_role_val = get_role_value(current_target_role)

    # Prevent self-demotion accidentally or managing equal/higher ranks
    if caller_val <= target_role_val and user.id != config.OWNER_ID:
        await send_ephemeral_reply(update, context, "⛔ You cannot modify the role of someone with equal or higher rank.", delay=ADMIN_EPHEMERAL_DELAY)
        return

    if caller_val <= new_role_val and user.id != config.OWNER_ID:
        await send_ephemeral_reply(update, context, "⛔ You cannot promote someone to a rank equal to or higher than your own.", delay=ADMIN_EPHEMERAL_DELAY)
        return

    # 6. Execute
    await api_bot_post(f"/admin/users/{target_id}/role", json_body={"role": new_role})
    await send_ephemeral_reply(update, context, f"✅ Role for {target_username} updated to <b>{new_role}</b>.", parse_mode="HTML", delay=ADMIN_EPHEMERAL_DELAY)

async def list_roles_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    caller_role = await get_user_role(update.effective_user.id)
    if not check_role(caller_role, ROLE_ADMIN):
        await send_ephemeral_reply(update, context, "⛔ You do not have permission to view roles.", delete_in_private=True)
        return
    roles_text = "\n".join([f"• {role}" for role in ROLE_HIERARCHY.keys()])
    await send_ephemeral_reply(update, context, f"📋 <b>Available Roles:</b>\n{roles_text}", parse_mode="HTML", delete_in_private=True, delay=ADMIN_EPHEMERAL_DELAY)
