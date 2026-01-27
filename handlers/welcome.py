from telegram import Update, ChatMember
from telegram.ext import ContextTypes, ChatMemberHandler
from handlers.api_client import api_bot_post, api_bot_delete, api_get
import config
import asyncio

async def track_chats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Tracks the chats the bot is in."""
    if not update.my_chat_member:
        return
        
    result = extract_status_change(update.my_chat_member)
    if result is None:
        return

    was_member, is_member = result
    chat = update.effective_chat
    
    if not was_member and is_member:
        # Bot added to group
        await api_bot_post("/admin/groups", json_body={"chat_id": chat.id, "chat_title": chat.title, "chat_type": chat.type})
        print(f"DEBUG: Bot added to {chat.title} ({chat.id})")
    elif was_member and not is_member:
        # Bot removed from group
        await api_bot_delete(f"/admin/groups/{chat.id}")
        print(f"DEBUG: Bot removed from {chat.title} ({chat.id})")

def extract_status_change(chat_member_update):
    """Takes a ChatMemberUpdated instance and extracts whether the 'old_chat_member'
    was a member of the chat and whether the 'new_chat_member' is a member of the chat.
    """
    status_change = chat_member_update.difference().get("status")
    old_is_member, new_is_member = chat_member_update.difference().get("is_member", (None, None))

    if status_change is None:
        return None

    old_status, new_status = status_change
    was_member = old_status in [
        ChatMember.MEMBER,
        ChatMember.OWNER,
        ChatMember.ADMINISTRATOR,
    ] or (old_status == ChatMember.RESTRICTED and old_is_member is True)

    is_member = new_status in [
        ChatMember.MEMBER,
        ChatMember.OWNER,
        ChatMember.ADMINISTRATOR,
    ] or (new_status == ChatMember.RESTRICTED and new_is_member is True)

    return was_member, is_member

async def greet_chat_members(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Greets new users in chats and announces when someone leaves"""
    result = extract_status_change(update.chat_member)
    if result is None:
        return

    was_member, is_member = result
    
    # DEBUG: Print status change to console
    print(f"DEBUG: Status Change - Was: {was_member}, Is: {is_member}")
    
    # User Joined
    if not was_member and is_member:
        user = update.chat_member.new_chat_member.user
        try:
            await api_bot_post("/admin/users/ensure", json_body={"user_id": user.id, "username": user.username})
        except Exception:
            pass
        
        # Check if user has a club set
        club_badge = ""
        badge_url = None
        try:
            me = await api_get("/user/me", user_id=user.id)
        except Exception:
            me = {}
        club_entry = me.get("club") if isinstance(me, dict) else None
        if club_entry:
            club_badge = f" {club_entry.get('label')}"
            try:
                badge_url = club_entry.get("badge")
            except Exception:
                pass
        
        welcome_text = (
            f"Welcome to Dave.sports, {user.mention_html()}{club_badge}! ⚽🥊⛳\n\n"
            "We are the community for The News From The Sports Dave Loves – "
            "Football, Darts, Golf, F1, Boxing & UFC.\n\n"
            "<b>Get Started:</b>\n"
            "Open /web to set your profile, club badge, and interests.\n\n"
            "<b>Rules:</b>\n"
            "• No spamming\n"
            "• No unauthorized links\n"
            "• Be respectful\n\n"
            "Enjoy the conversation!"
        )
        
        # Send welcome with badge image if user has a club
        if badge_url:
            try:
                msg = await update.effective_chat.send_photo(
                    photo=badge_url,
                    caption=welcome_text,
                    parse_mode="HTML"
                )
            except:
                msg = await update.effective_chat.send_message(
                    welcome_text,
                    parse_mode="HTML"
                )
        else:
            msg = await update.effective_chat.send_message(
                welcome_text,
                parse_mode="HTML"
            )
        
        # Schedule deletion
        if config.WELCOME_DELETE_DELAY > 0:
            asyncio.create_task(delete_message_later(msg, config.WELCOME_DELETE_DELAY))

async def delete_message_later(message, delay):
    await asyncio.sleep(delay)
    try:
        await message.delete()
    except Exception:
        pass # Message might already be deleted
