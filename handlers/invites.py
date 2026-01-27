from telegram import Update
from telegram.ext import ContextTypes
import config
from handlers.utils import private_only, send_ephemeral_reply, send_webapp_link
from handlers.api_client import api_bot_post

@private_only
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = context.args
    
    invited_by = None
    
    # Check if this is a deep linked start (e.g. /start 12345)
    if args and args[0].isdigit():
        referrer_id = int(args[0])
        # basic checks: cannot invite self
        if referrer_id != user.id:
            invited_by = referrer_id

    # Ensure user via backend (handles invite reward)
    try:
        result = await api_bot_post("/admin/users/ensure", json_body={
            "user_id": user.id,
            "username": user.username,
            "invited_by": invited_by
        })
    except Exception:
        result = {}
    rewarded = result.get("rewarded", False)
    
    if rewarded and invited_by:
        
        # Notify Referrer (if they have a chat with bot, might fail if blocked)
        try:
            await context.bot.send_message(
                chat_id=invited_by,
                text=f"🎉 <b>New Referral!</b>\n\nUser {user.mention_html()} joined using your link.\nYou earned <b>{config.INVITE_REWARD}</b> coins!",
                parse_mode="HTML"
            )
        except:
            pass # Referrer blocked bot or cannot be reached

    from handlers.menu import main_menu_keyboard
    welcome_msg = (
        "👋 <b>Welcome to Dave.sports</b>\n\n"
        "Your football & sports intelligence hub."
    )
    try:
        await update.message.reply_text(
            welcome_msg,
            parse_mode="HTML",
            reply_markup=main_menu_keyboard()
        )
    except Exception:
        await send_ephemeral_reply(update, context, welcome_msg, parse_mode="HTML", delete_in_private=False)

@private_only
async def invite_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_webapp_link(update, context, text="🌐 Open the Web App for invites & referral stats.", path="/profile")
