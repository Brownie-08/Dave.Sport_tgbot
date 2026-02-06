"""
Utility functions for Dave.sports bot
"""
import asyncio
import time
from functools import wraps
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import ContextTypes

import config

# Cache-busting for Telegram WebApp (Telegram can cache aggressively).
# Using a date-based version keeps the URL stable for a day while still allowing quick refreshes.
WEBAPP_VERSION = getattr(config, "WEBAPP_VERSION", "") or time.strftime("%Y%m%d")

# Auto-delete delay for ephemeral messages (in seconds)
EPHEMERAL_DELAY = 60
# Auto-delete delay for admin actions (in seconds)
ADMIN_EPHEMERAL_DELAY = 300
# Recent command tracking (for auto-cleaning replies)
COMMAND_TTL = 10  # seconds to consider a command "recent"
RECENT_COMMANDS = {}
def _append_webapp_version(url: str) -> str:
    if not url or not WEBAPP_VERSION:
        return url
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.setdefault("v", WEBAPP_VERSION)
    new_query = urlencode(query)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, new_query, parts.fragment))


def build_webapp_url(path: str = "") -> str:
    base = getattr(config, "WEBAPP_URL", "") or ""
    base = base.strip()
    if not base:
        return ""

    if not path:
        return _append_webapp_version(base)

    if not path.startswith("/"):
        path = "/" + path

    return _append_webapp_version(base.rstrip("/") + path)

def build_webapp_url_with_query(path: str = "", query: str = "", fragment: str = "") -> str:
    url = build_webapp_url(path)
    if not url:
        return ""
    if query:
        if not query.startswith("?"):
            query = "?" + query
        url += query
    if fragment:
        if not fragment.startswith("#"):
            fragment = "#" + fragment
        url += fragment
    return url

async def delete_message_later(message, delay: int = EPHEMERAL_DELAY):
    """Delete a message after a delay"""
    try:
        await asyncio.sleep(delay)
        await message.delete()
    except Exception:
        pass  # Message may already be deleted or bot lacks permissions

async def handle_group_command(update: Update, context: ContextTypes.DEFAULT_TYPE, bot_username: str = None):
    """
    Handle a command that was triggered in a group chat.
    Deletes the command message and sends an ephemeral prompt to use private chat.
    Returns True if handled (was in group), False if private chat.
    """
    chat = update.effective_chat
    
    # Allow in private chats
    if chat.type == "private":
        return False
    
    # In group - delete command and send ephemeral notice
    try:
        await update.message.delete()
    except Exception:
        pass  # Bot may not have delete permissions
    
    if bot_username is None:
        bot_username = context.bot.username
    
    # Send ephemeral notice
    try:
        notice = await context.bot.send_message(
            chat_id=chat.id,
            text=f"💬 Please use this command in <a href=\"https://t.me/{bot_username}\">private chat</a> with me.",
            parse_mode="HTML",
            disable_web_page_preview=True
        )
        # Auto-delete the notice
        asyncio.create_task(delete_message_later(notice, EPHEMERAL_DELAY))
    except Exception:
        pass
    
    return True
def register_command(chat_id: int, message_id: int):
    chat_map = RECENT_COMMANDS.setdefault(chat_id, {})
    chat_map[message_id] = time.time()

def is_recent_command(chat_id: int, message_id: int) -> bool:
    chat_map = RECENT_COMMANDS.get(chat_id, {})
    if not chat_map:
        return False
    now = time.time()
    # Cleanup expired entries
    for mid, ts in list(chat_map.items()):
        if now - ts > COMMAND_TTL:
            chat_map.pop(mid, None)
    return message_id in chat_map

async def register_and_delete_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Track command messages and auto-delete them in all chats."""
    if not update.message or not update.effective_chat:
        return
    chat = update.effective_chat
    register_command(chat.id, update.message.message_id)
    # Auto-delete the command message shortly after
    asyncio.create_task(delete_message_later(update.message, EPHEMERAL_DELAY))

def private_only(func):
    """
    Decorator to restrict a command to private chats only.
    If used in a group, deletes the command and prompts user to use private chat.
    """
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        if await handle_group_command(update, context):
            return  # Was handled as group command, don't proceed
        return await func(update, context, *args, **kwargs)
    return wrapper

async def send_ephemeral_message(context: ContextTypes.DEFAULT_TYPE, chat_id: int, text: str, delay: int = EPHEMERAL_DELAY, **kwargs):
    """Send a message that auto-deletes after a delay"""
    try:
        message = await context.bot.send_message(chat_id=chat_id, text=text, **kwargs)
        asyncio.create_task(delete_message_later(message, delay))
        return message
    except Exception:
        return None
async def send_ephemeral_reply(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, delay: int = EPHEMERAL_DELAY, delete_in_private: bool = True, **kwargs):
    """Reply (or send) and auto-delete to keep chat clean."""
    try:
        if update.message:
            msg = await update.message.reply_text(text, **kwargs)
        else:
            msg = await context.bot.send_message(chat_id=update.effective_chat.id, text=text, **kwargs)
        if update.effective_chat and (update.effective_chat.type in ["group", "supergroup"] or delete_in_private):
            asyncio.create_task(delete_message_later(msg, delay))
        return msg
    except Exception:
        return None

async def edit_or_ephemeral(message, text: str, reply_markup=None, parse_mode=None, delay: int = EPHEMERAL_DELAY):
    """Try editing a message; if not possible, reply and auto-delete quickly."""
    try:
        await message.edit_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
        asyncio.create_task(delete_message_later(message, delay))
        return True
    except Exception:
        try:
            msg = await message.reply_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
            asyncio.create_task(delete_message_later(msg, delay))
        except Exception:
            pass
        return False

async def send_webapp_link(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str = "Open the web app", button_text: str = "🌐 Open Web App", delete_in_private: bool = False, path: str = ""):
    """Send a Telegram Web App button if configured."""
    url = build_webapp_url(path)
    if not url:
        return await send_ephemeral_reply(update, context, "⚠️ Web app is not configured yet.", delete_in_private=delete_in_private)
    keyboard = [[InlineKeyboardButton(button_text, web_app=WebAppInfo(url=url))]]
    return await send_ephemeral_reply(
        update,
        context,
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        delete_in_private=delete_in_private
    )
