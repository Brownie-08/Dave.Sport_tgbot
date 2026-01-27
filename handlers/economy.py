from telegram import Update
from telegram.ext import ContextTypes
import config
from handlers.roles import get_user_role, check_role, ROLE_ADMIN
from handlers.utils import private_only, send_webapp_link, send_ephemeral_reply, ADMIN_EPHEMERAL_DELAY
from handlers.api_client import api_get, api_post, api_bot_post

DAILY_AMOUNT = 2

@private_only
async def daily_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    try:
        data = await api_post("/api/rewards/daily", user_id=user.id)
    except Exception as exc:
        await send_ephemeral_reply(update, context, f"⚠️ Failed to claim daily reward: {exc}", delete_in_private=True)
        return

    if data.get("claimed"):
        added = data.get("coins_added", DAILY_AMOUNT)
        balance = data.get("balance", 0)
        msg_text = (
            f"💰 <b>Daily Reward!</b>\n\nYou've claimed <b>{added}</b> Dave Coins. Come back in 24 hours!\n"
            f"New Balance: <b>{balance}</b>"
        )
    else:
        retry = data.get("retry_in") or {}
        hours = retry.get("hours", 0)
        minutes = retry.get("minutes", 0)
        msg_text = f"⏳ You've already claimed your daily reward!\nTry again in <b>{hours}h {minutes}m</b>."

    await send_ephemeral_reply(update, context, msg_text, parse_mode="HTML", delete_in_private=True)

@private_only
async def balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    try:
        data = await api_get("/api/wallet", user_id=user.id)
        coins = data.get("coins", 0)
        msg_text = f"💰 <b>{user.first_name}'s Balance</b>\n\nCoins: <b>{coins}</b>"
    except Exception as exc:
        msg_text = f"⚠️ Failed to fetch balance: {exc}"

    await send_ephemeral_reply(update, context, msg_text, parse_mode="HTML", delete_in_private=True)

@private_only
async def leaderboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_webapp_link(update, context, text="🌐 Open the Web App for leaderboards and analytics.", path="/leaderboards")

async def gamble_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    try:
        data = await api_get("/user/balance", user_id=user.id)
        coins = int(data.get("coins", 0))
    except Exception:
        coins = 0
    
    if not context.args:
        await send_ephemeral_reply(update, context, "Usage: /gamble <amount>", delete_in_private=True)
        return
        
    try:
        bet = int(context.args[0])
    except ValueError:
        await send_ephemeral_reply(update, context, "Please enter a valid number for the bet.", delete_in_private=True)
        return
        
    if bet <= 0:
        await send_ephemeral_reply(update, context, "Bet must be greater than 0.", delete_in_private=True)
        return
        
    if coins < bet:
        await send_ephemeral_reply(update, context, "You don't have enough coins!", delete_in_private=True)
        return
        
    # Telegram Dice
    msg = await update.message.reply_dice(emoji="🎲")
    value = msg.dice.value
    
    # Logic: 1-3 Lose, 4-6 Win 2x
    if value >= 4:
        win_amount = bet
        await api_bot_post(f"/admin/users/{user.id}/balance", json_body={"amount": win_amount})
        result_text = f"🎉 <b>YOU WON!</b>\n\nYou rolled a {value} and won <b>{bet}</b> coins!"
    else:
        await api_bot_post(f"/admin/users/{user.id}/balance", json_body={"amount": -bet})
        result_text = f"💀 <b>YOU LOST!</b>\n\nYou rolled a {value} and lost <b>{bet}</b> coins."
        
    # Wait for animation to finish
    import asyncio
    await asyncio.sleep(4)
    await send_ephemeral_reply(update, context, result_text, parse_mode="HTML", delete_in_private=True)

async def give_coins_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Permission Check: ADMIN or higher
    user_role = await get_user_role(update.effective_user.id)
    if not check_role(user_role, ROLE_ADMIN):
        return
        
    if not update.message.reply_to_message or not context.args:
        await send_ephemeral_reply(update, context, "Usage: Reply to a user with /givecoins <amount>", delay=ADMIN_EPHEMERAL_DELAY)
        return
        
    target = update.message.reply_to_message.from_user
    try:
        amount = int(context.args[0])
    except ValueError:
        await send_ephemeral_reply(update, context, "Invalid amount.", delay=ADMIN_EPHEMERAL_DELAY)
        return
        
    await api_bot_post(f"/admin/users/{target.id}/balance", json_body={"amount": amount})
    await send_ephemeral_reply(
        update,
        context,
        f"✅ Gave <b>{amount}</b> coins to {target.mention_html()}.",
        parse_mode="HTML",
        delay=ADMIN_EPHEMERAL_DELAY
    )
