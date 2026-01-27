import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import ContextTypes
from handlers.api_client import api_bot_get, api_bot_post
import logging
from handlers.utils import private_only, edit_or_ephemeral, delete_message_later, EPHEMERAL_DELAY, send_webapp_link, build_webapp_url
import config

@private_only
async def notifications_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show notification preferences menu"""
    await send_webapp_link(update, context, text="🌐 Open the Web App to manage notifications.", path="/profile")

async def show_notification_settings(message, user_id, is_new=False):
    """Display notification settings with toggle buttons"""
    try:
        prefs = await api_bot_get(f"/admin/users/{user_id}/preferences")
    except Exception:
        prefs = {}
    match_reminders = prefs.get("match_reminders", 1)
    result_notifications = prefs.get("result_notifications", 1)
    daily_reminder = prefs.get("daily_reminder", 0)
    prediction_updates = prefs.get("prediction_updates", 1)
    
    def status_icon(val):
        return "✅" if val else "❌"
    
    keyboard = [
        [InlineKeyboardButton(
            f"{status_icon(match_reminders)} Match Reminders",
            callback_data="notif_toggle_match_reminders"
        )],
        [InlineKeyboardButton(
            f"{status_icon(result_notifications)} Result Notifications",
            callback_data="notif_toggle_result_notifications"
        )],
        [InlineKeyboardButton(
            f"{status_icon(daily_reminder)} Daily Coin Reminder",
            callback_data="notif_toggle_daily_reminder"
        )],
        [InlineKeyboardButton(
            f"{status_icon(prediction_updates)} Prediction Updates",
            callback_data="notif_toggle_prediction_updates"
        )],
        [InlineKeyboardButton("🔙 Back to Menu", callback_data="cmd_back_menu")]
    ]
    
    text = (
        "🔔 <b>Notification Settings</b>\n\n"
        "Tap to toggle each notification type:\n\n"
        f"📅 <b>Match Reminders</b> {status_icon(match_reminders)}\n"
        "   Get notified when new matches are posted\n\n"
        f"🏁 <b>Result Notifications</b> {status_icon(result_notifications)}\n"
        "   Get notified when match results are announced\n\n"
        f"💰 <b>Daily Coin Reminder</b> {status_icon(daily_reminder)}\n"
        "   Reminder to claim your daily coins\n\n"
        f"📊 <b>Prediction Updates</b> {status_icon(prediction_updates)}\n"
        "   Get updates about your predictions"
    )
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if is_new:
        msg = await message.reply_text(text, reply_markup=reply_markup, parse_mode="HTML")
        asyncio.create_task(delete_message_later(msg, EPHEMERAL_DELAY))
    else:
        await edit_or_ephemeral(message, text, reply_markup=reply_markup, parse_mode="HTML")

async def notification_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle notification preference toggle callbacks"""
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data
    
    if data.startswith("notif_toggle_"):
        await query.answer()
        if not config.WEBAPP_URL:
            await query.answer("Web app not configured.", show_alert=True)
            return
        await edit_or_ephemeral(
            query.message,
            "🌐 <b>Open the Web App</b> to manage notifications:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🌐 Open Web App", web_app=WebAppInfo(url=build_webapp_url("/profile")))]]),
            parse_mode="HTML"
        )
        return

async def send_match_notification(context: ContextTypes.DEFAULT_TYPE, match_id, team_a, team_b, match_time=None):
    """Send notification to all users with match_reminders enabled"""
    try:
        data = await api_bot_get("/admin/notifications/users", params={"pref": "match_reminders"})
        users = data.get("user_ids", []) if isinstance(data, dict) else []
    except Exception:
        users = []
    
    time_str = ""
    if match_time:
        try:
            from datetime import datetime
            dt = datetime.strptime(match_time, '%Y-%m-%d %H:%M:%S')
            time_str = f"\n⏰ Kickoff: {dt.strftime('%d %b, %H:%M')} UTC"
        except:
            pass
    
    keyboard = [
        [InlineKeyboardButton("⚽ Make Prediction", callback_data=f"pred_show_{match_id}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = (
        f"🔔 <b>New Match Alert!</b>\n\n"
        f"🆔 Match #{match_id}\n"
        f"🏟️ <b>{team_a}</b> vs <b>{team_b}</b>{time_str}\n\n"
        f"Make your prediction now!"
    )
    
    sent_count = 0
    for user_id in users:
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=text,
                reply_markup=reply_markup,
                parse_mode="HTML"
            )
            sent_count += 1
        except Exception as e:
            # User may have blocked bot or deleted account
            logging.debug(f"Failed to notify user {user_id}: {e}")
    
    return sent_count

async def send_result_notification(context: ContextTypes.DEFAULT_TYPE, match_id, team_a, team_b, 
                                   winner_name, score_a=None, score_b=None, winners_count=0):
    """Send match result notification to users who predicted"""
    try:
        data = await api_bot_get("/admin/notifications/result-recipients", params={"match_id": match_id})
        users = data.get("user_ids", []) if isinstance(data, dict) else []
    except Exception:
        users = []
    
    score_str = f"\n📊 Score: {score_a} - {score_b}" if score_a is not None else ""
    
    text = (
        f"🏁 <b>Match Result!</b>\n\n"
        f"Match #{match_id}: {team_a} vs {team_b}\n"
        f"🏆 Winner: <b>{winner_name}</b>{score_str}\n\n"
        f"🎉 {winners_count} correct predictions!"
    )
    
    keyboard = [
        [InlineKeyboardButton("📊 My Predictions", callback_data="cmd_mypredictions")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    sent_count = 0
    for user_id in users:
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=text,
                reply_markup=reply_markup,
                parse_mode="HTML"
            )
            sent_count += 1
        except:
            pass
    
    return sent_count
