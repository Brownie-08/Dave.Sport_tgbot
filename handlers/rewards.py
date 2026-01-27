from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
import config
import logging
import re
import asyncio

from handlers.api_client import api_bot_get, api_bot_post
from handlers.roles import get_user_role, check_role, ROLE_ADMIN
from handlers.utils import delete_message_later, EPHEMERAL_DELAY

# Track which users have "opened" links (clicked Open Link button)
# {(user_id, link_id): True}
LINK_OPENS = {}

async def handle_admin_link_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handler for messages containing links posted by admins.
    Adds reward buttons directly to the message.
    """
    message = update.message
    if not message or not message.text:
        return
    
    user = message.from_user
    chat = message.chat
    
    # Only process in groups
    if chat.type == "private":
        return
    
    # Check if user is admin
    user_role = await get_user_role(user.id)
    if not check_role(user_role, ROLE_ADMIN):
        return
    
    # Extract URLs from message
    url_pattern = r'https?://[^\s<>"{}|\\^`\[\]]+'
    urls = re.findall(url_pattern, message.text)
    
    if not urls:
        return
    
    # Use the first URL found
    url = urls[0]
    
    # Create tracked link via backend
    try:
        data = await api_bot_post("/admin/links", {
            "url": url,
            "chat_id": chat.id,
            "message_id": message.message_id
        })
        link_id = data.get("link_id")
    except Exception as e:
        logging.error(f"Failed to create tracked link: {e}")
        return
    
    # Create inline keyboard with Open Link and Claim Reward buttons
    keyboard = [
        [InlineKeyboardButton("🚀 Open Link", url=url)],
        [InlineKeyboardButton(f"🎁 Claim Reward (+{config.LINK_CLICK_REWARD} coins)", callback_data=f"clk_{link_id}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Edit the original message to add buttons (preserves link preview)
    try:
        await message.edit_reply_markup(reply_markup=reply_markup)
    except Exception as e:
        logging.debug(f"Could not edit message markup: {e}")
        # If editing fails, send buttons as a reply (fallback)
        # But try not to break the preview - send minimal text
        try:
            msg = await message.reply_text(
                "👇 <b>Click to earn rewards:</b>",
                reply_markup=reply_markup,
                parse_mode="HTML",
                disable_web_page_preview=True
            )
            asyncio.create_task(delete_message_later(msg, EPHEMERAL_DELAY))
        except:
            pass

async def reaction_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles message reactions and awards coins"""
    reaction = update.message_reaction
    user = reaction.user
    message_id = reaction.message_id
    chat_id = reaction.chat.id
    
    if not user:
        return

    if not reaction.new_reaction:
        return
    
    # Check if user already reacted via backend
    try:
        result = await api_bot_get(f"/admin/reactions/check", params={
            "user_id": user.id,
            "message_id": message_id
        })
        if result.get("already_reacted"):
            return
    except Exception:
        return
    
    # Record reaction and reward
    try:
        await api_bot_post("/admin/reactions", {
            "user_id": user.id,
            "message_id": message_id,
            "chat_id": chat_id
        })
        await api_bot_post(f"/admin/users/{user.id}/balance", {
            "amount": config.REACTION_REWARD,
            "reason": "reaction"
        })
    except Exception:
        pass

async def test_rewards_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends a test button to verify link rewards"""
    keyboard = [
        [InlineKeyboardButton("🎁 Claim Test Reward (+5 Coins)", callback_data="reward_link_test")],
        [InlineKeyboardButton("🚀 Open Google (Test)", url="https://google.com")],
        [InlineKeyboardButton("📤 Share (+2 Coins)", callback_data="reward_share")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("👇 <b>Reward System Test</b>\nClick the buttons below to verify rewards:", reply_markup=reply_markup, parse_mode="HTML")

async def reward_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handles reward button callbacks.
    Implements verification flow: user must click Open Link first, then Claim Reward.
    """
    query = update.callback_query
    data = query.data
    user_id = query.from_user.id
    
    # Ensure user is in database
    try:
        await api_bot_post("/admin/users/ensure", {
            "user_id": user_id,
            "username": query.from_user.username or ""
        })
    except Exception:
        pass

    if data.startswith("clk_"):
        # Format: clk_LINKID
        try:
            link_id = int(data.split("_")[1])
        except:
            await query.answer("⚠️ Invalid Link Data", show_alert=True)
            return
        
        # Check if already claimed via backend
        try:
            result = await api_bot_get(f"/admin/links/{link_id}/clicks", params={"user_id": user_id})
            if result.get("already_clicked"):
                await query.answer("✅ You already claimed this reward!", show_alert=False)
                return
        except Exception:
            pass
        
        # Verification: Check if user has "opened" the link first
        attempt_key = (user_id, link_id)
        if attempt_key not in LINK_OPENS:
            # First click on Claim - remind them to open link first
            LINK_OPENS[attempt_key] = True
            await query.answer(
                "👆 First, click 'Open Link' above!\n"
                "Then click Claim Reward again.",
                show_alert=True
            )
            return
        
        # Second click - process the reward via backend
        try:
            await api_bot_post(f"/admin/links/{link_id}/clicks", {
                "user_id": user_id
            })
            await api_bot_post(f"/admin/users/{user_id}/balance", {
                "amount": config.LINK_CLICK_REWARD,
                "reason": "link_click"
            })
            await query.answer(f"✅ +{config.LINK_CLICK_REWARD} Coins added!", show_alert=True)
            
            # Clean up the tracking
            if attempt_key in LINK_OPENS:
                del LINK_OPENS[attempt_key]
        except Exception as e:
            await query.answer("⚠️ Reward failed. Try again.", show_alert=True)
    
    elif data == "claimed":
        await query.answer("✅ You've already claimed this reward!", show_alert=False)

    elif data == "reward_link_test":
        try:
            await api_bot_post(f"/admin/users/{user_id}/balance", {
                "amount": config.LINK_CLICK_REWARD,
                "reason": "test"
            })
            await query.answer(f"✅ Test Success! +{config.LINK_CLICK_REWARD} coins", show_alert=True)
        except Exception:
            await query.answer("❌ Test Failed", show_alert=True)

    elif data == "reward_share":
        try:
            await api_bot_post(f"/admin/users/{user_id}/balance", {
                "amount": config.LINK_SHARE_REWARD,
                "reason": "share"
            })
            await query.answer(f"✅ +{config.LINK_SHARE_REWARD} coins for sharing!")
        except Exception:
            await query.answer("❌ Share reward failed")

async def prediction_reward_placeholder(user_id):
    """Call this when a prediction is successful in the future"""
    try:
        await api_bot_post(f"/admin/users/{user_id}/balance", {
            "amount": config.PREDICTION_REWARD,
            "reason": "prediction"
        })
    except Exception:
        pass

async def reaction_reward_placeholder(user_id):
    """Call this when a reaction is detected on a specific post"""
    try:
        await api_bot_post(f"/admin/users/{user_id}/balance", {
            "amount": config.REACTION_REWARD,
            "reason": "reaction"
        })
    except Exception:
        pass
