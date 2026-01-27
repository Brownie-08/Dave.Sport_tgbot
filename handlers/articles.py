from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from handlers.api_client import api_bot_get, api_bot_post
from handlers.roles import get_user_role, check_role, ROLE_ADMIN, is_admin_or_owner
from handlers.utils import send_ephemeral_reply, edit_or_ephemeral, ADMIN_EPHEMERAL_DELAY
import logging
import config

async def post_article_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Broadcasts a message to all groups the bot is in.
    Usage: 
    1. /postarticle <your text here>
    2. Reply to a message with /postarticle
    3. /broadcast (alias)
    """
    user_id = update.effective_user.id
    
    # Check if user is admin/owner (works from private chat too)
    is_admin = await is_admin_or_owner(context.bot, update.effective_chat.id, user_id)
    if not is_admin:
        await send_ephemeral_reply(update, context, "⛔ Only Admins can broadcast messages.", delay=ADMIN_EPHEMERAL_DELAY)
        return

    # Determine what to send
    if update.message.reply_to_message:
        pass  # Will copy the replied message
    elif context.args:
        pass  # Will use the text after command
    else:
        # Show usage help with quick options
        keyboard = [
            [InlineKeyboardButton("📝 Broadcast Help Menu", callback_data="broadcast_help")],
            [InlineKeyboardButton("🏆 Broadcast Match Info", callback_data="broadcast_matches")],
            [InlineKeyboardButton("📢 Broadcast Announcement", callback_data="broadcast_custom")]
        ]
        await send_ephemeral_reply(
            update,
            context,
            "📢 <b>Broadcast to All Groups</b>\n\n"
            "<b>Option 1:</b> Reply to any message with <code>/postarticle</code>\n\n"
            "<b>Option 2:</b> Type <code>/postarticle Your message here</code>\n\n"
            "<b>Option 3:</b> Use buttons below for quick broadcasts:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML",
            delay=ADMIN_EPHEMERAL_DELAY
        )
        return

    data = await api_bot_get("/admin/groups")
    groups = data.get("chat_ids", []) if isinstance(data, dict) else []
    if not groups:
        await send_ephemeral_reply(update, context, "❌ No groups found. Add the bot to groups first.", delay=ADMIN_EPHEMERAL_DELAY)
        return

    await send_ephemeral_reply(update, context, f"🚀 Broadcasting to {len(groups)} groups...", delay=ADMIN_EPHEMERAL_DELAY)

    success_count = 0
    fail_count = 0

    for chat_id in groups:
        try:
            if update.message.reply_to_message:
                await context.bot.copy_message(
                    chat_id=chat_id,
                    from_chat_id=update.effective_chat.id,
                    message_id=update.message.reply_to_message.message_id
                )
            else:
                # Extract text without the command
                text = update.message.text
                # Remove command from text
                for cmd in ['/postarticle', '/broadcast']:
                    if text.startswith(cmd):
                        text = text[len(cmd):].strip()
                        break
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    parse_mode="HTML"
                )
            success_count += 1
        except Exception as e:
            logging.error(f"Failed to post to {chat_id}: {e}")
            fail_count += 1

    await send_ephemeral_reply(
        update,
        context,
        f"✅ <b>Broadcast Complete!</b>\n\n"
        f"📢 Sent to: <b>{success_count}</b> groups\n"
        f"❌ Failed: <b>{fail_count}</b>",
        parse_mode="HTML",
        delay=ADMIN_EPHEMERAL_DELAY
    )

async def broadcast_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle broadcast button callbacks"""
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data
    
    # Check admin permission
    is_admin = await is_admin_or_owner(context.bot, query.message.chat_id, user_id)
    if not is_admin:
        await query.answer("🚫 Admin only!", show_alert=True)
        return
    
    await query.answer()
    
    if data == "broadcast_help":
        # Broadcast the help menu to all groups
        bot_username = context.bot.username or "Davesportbot"
        help_text = f"""
🏟️ <b>Dave.sport Bot Commands</b>

📱 <b>Quick Access:</b>
/menu - Interactive button menu
@{bot_username} - Inline predictions (any chat!)

💰 <b>Economy:</b>
/daily - Claim daily check-in (2 coins)
/balance - Check your coins
/leaderboard - (Web App)

⚽ <b>Predictions:</b>
/matches - View open matches
/mypredictions - (Web App)
/predboard - (Web App)

👤 <b>Profile & Identity (Web App):</b>
/userinfo - (Web App)
/setup - (Web App)
/notifications - (Web App)
/invite - (Web App)

🌐 <b>Web App:</b>
/web - Open the Web App

💡 <b>Tip:</b> Start a private chat with @{bot_username} for full features!
"""
        try:
            data = await api_bot_get("/admin/groups")
            groups = data.get("chat_ids", []) if isinstance(data, dict) else []
        except Exception:
            groups = []
        success = 0
        for chat_id in groups:
            try:
                await context.bot.send_message(chat_id=chat_id, text=help_text, parse_mode="HTML")
                success += 1
            except:
                pass
        
        await edit_or_ephemeral(
            query.message,
            f"✅ <b>Help Menu Broadcasted!</b>\n\n"
            f"📢 Sent to <b>{success}</b> groups",
            parse_mode="HTML",
            delay=ADMIN_EPHEMERAL_DELAY
        )
    
    elif data == "broadcast_matches":
        # Broadcast current open matches
        from handlers.api_client import api_get
        try:
            data = await api_get("/api/predictions/open", user_id=user_id)
            matches = data.get("items", []) if isinstance(data, dict) else []
        except Exception:
            matches = []
        
        if not matches:
            await edit_or_ephemeral(query.message, "❌ No open matches to broadcast.", delay=ADMIN_EPHEMERAL_DELAY)
            return
        
        text = "🏆 <b>OPEN PREDICTIONS!</b>\n────────────────────\n\n"
        for m in matches[:5]:
            match_id = m.get("match_id")
            team_a = m.get("team_a")
            team_b = m.get("team_b")
            text += f"🟢 <b>#{match_id}</b>: {team_a} vs {team_b}\n"
        
        text += f"\n────────────────────\n🎯 Win <b>+{config.PREDICTION_REWARD} coins</b> per correct prediction!\n\nUse /matches to predict!"
        
        try:
            data = await api_bot_get("/admin/groups")
            groups = data.get("chat_ids", []) if isinstance(data, dict) else []
        except Exception:
            groups = []
        success = 0
        for chat_id in groups:
            try:
                await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
                success += 1
            except:
                pass
        
        await edit_or_ephemeral(
            query.message,
            f"✅ <b>Matches Broadcasted!</b>\n\n"
            f"📢 Sent to <b>{success}</b> groups",
            parse_mode="HTML",
            delay=ADMIN_EPHEMERAL_DELAY
        )
    
    elif data == "broadcast_custom":
        await edit_or_ephemeral(
            query.message,
            "✏️ <b>Custom Broadcast</b>\n\n"
            "Send your message using:\n"
            "<code>/postarticle Your message here</code>\n\n"
            "Or reply to any message with <code>/postarticle</code>",
            parse_mode="HTML",
            delay=ADMIN_EPHEMERAL_DELAY
        )

async def auto_track_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Silent handler to ensure groups are in the DB even if bot was added while offline."""
    chat = update.effective_chat
    if chat and chat.type in ["group", "supergroup"]:
        # Only add if not already in some cache or just always add (INSERT OR REPLACE)
        await api_bot_post("/admin/groups", json_body={"chat_id": chat.id, "chat_title": chat.title, "chat_type": chat.type})
