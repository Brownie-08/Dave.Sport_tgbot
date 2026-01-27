import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import ContextTypes, CallbackQueryHandler, CommandHandler
from handlers.api_client import api_bot_get, api_bot_post
from handlers.utils import private_only, delete_message_later, EPHEMERAL_DELAY, send_webapp_link, edit_or_ephemeral, build_webapp_url
import config
from shared_constants import CLUBS_DATA, INTERESTS

async def get_general_broadcast_chat_ids() -> list:
    """
    Return chat IDs for General broadcasts.
    Uses chat_category_routing so we only target the main group (no topic threads).
    """
    try:
        data = await api_bot_get("/admin/groups")
        groups = data.get("groups", [])
        chat_ids = [g["chat_id"] for g in groups if isinstance(g, dict) and g.get("enabled")]
        return chat_ids
    except Exception:
        return []

def format_user_display(user) -> str:
    if user.username:
        return user.first_name or user.username
    return user.first_name or "User"

async def broadcast_general(context: ContextTypes.DEFAULT_TYPE, text: str):
    chat_ids = await get_general_broadcast_chat_ids()
    for chat_id in chat_ids:
        try:
            await context.bot.send_message(chat_id=chat_id, text=text)
        except Exception:
            pass

def get_club_badge_url(club_name: str) -> str:
    """
    Get the badge URL for a club name.
    Handles both the stored format (emoji + name) and plain name lookup.
    Returns None if not found.
    """
    if not club_name:
        return None
    
    # Direct lookup by key
    if club_name in CLUBS_DATA:
        club_data = CLUBS_DATA[club_name]
        return club_data.get("badge") if isinstance(club_data, dict) else None
    
    # Search by display name (stored in DB as emoji + name)
    for key, data in CLUBS_DATA.items():
        if isinstance(data, dict):
            if data.get("name") == club_name or key in club_name:
                return data.get("badge")
    
    return None

def get_club_emoji(club_name: str) -> str:
    """
    Get just the emoji prefix for a club.
    Returns empty string if not found.
    """
    if not club_name:
        return ""
    
    # If the club_name already has emoji, extract it
    if club_name and len(club_name) > 0:
        # Check if starts with emoji (most emojis are 1-2 chars but can be longer with modifiers)
        for key, data in CLUBS_DATA.items():
            if isinstance(data, dict):
                name = data.get("name", "")
                if name == club_name:
                    # Extract emoji part (everything before the space + club name)
                    parts = name.split(" ", 1)
                    if len(parts) > 1:
                        return parts[0] + " "
    
    return ""

@private_only
async def setup_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends the profile setup menu"""
    await send_webapp_link(update, context, text="🌐 Open the Web App to manage your profile & identity.", path="/profile")

async def show_main_menu(message, is_new=False, context=None):
    keyboard = [
        [InlineKeyboardButton("👕 Set My Club", callback_data="menu_club")],
        [InlineKeyboardButton("📰 Set News Interests", callback_data="menu_interests")],
        [InlineKeyboardButton("❌ Close", callback_data="close")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    text = "⚙️ <b>Profile Setup</b>\nChoose an option below:"
    
    if is_new:
        msg = await message.reply_text(text, reply_markup=reply_markup, parse_mode="HTML")
        asyncio.create_task(delete_message_later(msg, EPHEMERAL_DELAY))
    else:
        # Check if this is a photo message (can't edit_text on photos)
        if message.photo:
            # Delete the photo and send a new text message
            try:
                chat_id = message.chat_id
                await message.delete()
                if context:
                    msg = await context.bot.send_message(
                        chat_id=chat_id,
                        text=text,
                        reply_markup=reply_markup,
                        parse_mode="HTML"
                    )
                    asyncio.create_task(delete_message_later(msg, EPHEMERAL_DELAY))
            except Exception:
                pass
        else:
            # Edit existing text message
            try:
                await message.edit_text(text, reply_markup=reply_markup, parse_mode="HTML")
                asyncio.create_task(delete_message_later(message, EPHEMERAL_DELAY))
            except Exception:
                pass # Content didn't change

async def profile_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    data = query.data
    
    await query.answer()
    
    if data == "close":
        await query.message.delete()
        return
    
    if config.WEBAPP_URL:
        await edit_or_ephemeral(
            query.message,
            "🌐 <b>Open the Web App</b> to manage your profile & identity:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🌐 Open Web App", web_app=WebAppInfo(url=build_webapp_url("/profile")))]]),
            parse_mode="HTML"
        )
        return

    if data == "menu_main":
        await show_main_menu(query.message, context=context)
        return

    if data == "menu_club":
        # Generate buttons for all clubs
        keyboard = []
        row = []
        # Sort clubs alphabetically
        sorted_clubs = sorted(CLUBS_DATA.keys())
        
        for club in sorted_clubs:
            # Display with emoji in the button
            club_data = CLUBS_DATA[club]
            label = club_data["name"] if isinstance(club_data, dict) else club_data
            row.append(InlineKeyboardButton(label, callback_data=f"set_club_{club}"))
            if len(row) == 2: # 2 buttons per row
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
        
        keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="menu_main")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        text = "👕 <b>Select Your Club</b>\nThis badge will appear on your profile."
        
        # Handle photo messages - can't edit_text on photos
        if query.message.photo:
            try:
                chat_id = query.message.chat_id
                await query.message.delete()
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    reply_markup=reply_markup,
                    parse_mode="HTML"
                )
            except Exception:
                pass
        else:
            await query.message.edit_text(text, reply_markup=reply_markup, parse_mode="HTML")
        return

    if data == "menu_interests":
        await show_interests_menu(query, user.id, context)
        return

    if data.startswith("set_club_"):
        club_key = data.replace("set_club_", "")
        # Get club data
        club_data = CLUBS_DATA.get(club_key, {"name": club_key, "badge": None})
        if isinstance(club_data, str):
            club_data = {"name": club_data, "badge": None}
        
        badge_display = club_data["name"]
        badge_url = club_data.get("badge")
        
        # Save to backend
        try:
            await api_bot_post(f"/admin/users/{user.id}/profile", {
                "club": badge_display
            })
        except Exception:
            pass
        
        # Show success confirmation
        keyboard = [[InlineKeyboardButton("❌ Close", callback_data="close")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        success_text = f"✅ <b>Club updated!</b>\n\nYou are now supporting: {badge_display}"
        
        # Try to send with badge image
        if badge_url:
            try:
                await query.message.delete()
                await context.bot.send_photo(
                    chat_id=query.message.chat_id,
                    photo=badge_url,
                    caption=success_text,
                    reply_markup=reply_markup,
                    parse_mode="HTML"
                )
                return
            except Exception:
                pass  # Fall back to text-only
        
        await query.message.edit_text(success_text, reply_markup=reply_markup, parse_mode="HTML")
        return

    if data.startswith("toggle_int_"):
        interest = data.replace("toggle_int_", "")
        
        # Get current interests from backend
        try:
            user_data = await api_bot_get(f"/admin/users/{user.id}")
            current_interests = user_data.get("interests", "").split(',') if user_data.get("interests") else []
        except Exception:
            current_interests = []
        
        if interest in current_interests:
            current_interests.remove(interest) # Toggle Off
        else:
            current_interests.append(interest) # Toggle On
            
        new_interests_str = ",".join(current_interests)
        try:
            await api_bot_post(f"/admin/users/{user.id}/profile", {
                "interests": new_interests_str
            })
        except Exception:
            pass
        
        # Refresh the menu instantly
        await show_interests_menu(query, user.id, context)
        return

async def show_interests_menu(query, user_id, context=None):
    try:
        user_data = await api_bot_get(f"/admin/users/{user_id}")
        current_interests = user_data.get("interests", "").split(',') if user_data.get("interests") else []
    except Exception:
        current_interests = []
    
    keyboard = []
    row = []
    for item in INTERESTS:
        # Add Checkmark if selected
        label = f"✅ {item}" if item in current_interests else item
        row.append(InlineKeyboardButton(label, callback_data=f"toggle_int_{item}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
        
    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="menu_main")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    text = "📰 <b>Select News Interests</b>\nClick to toggle on/off."
    
    # Handle photo messages - can't edit_text on photos
    if query.message.photo:
        try:
            chat_id = query.message.chat_id
            await query.message.delete()
            if context:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    reply_markup=reply_markup,
                    parse_mode="HTML"
                )
        except Exception:
            pass
    else:
        try:
            await query.message.edit_text(text, reply_markup=reply_markup, parse_mode="HTML")
        except Exception:
            pass # Message content identical, ignore warning
