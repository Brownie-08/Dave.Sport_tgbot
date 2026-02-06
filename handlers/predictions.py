from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from telegram.ext import ContextTypes
from handlers.api_client import api_get, api_post, api_bot_get, api_bot_post, api_bot_delete
from handlers.roles import get_user_role, check_role, ROLE_ADMIN, is_admin_or_owner
from handlers.utils import send_ephemeral_reply, send_webapp_link, edit_or_ephemeral, ADMIN_EPHEMERAL_DELAY
import config
from datetime import datetime, timedelta
import asyncio
import logging

# Store for match creation wizard state
MATCH_CREATION_STATE = {}

# --- Backend API Helpers for Predictions ---

async def create_match_api(team_a, team_b, match_time=None):
    data = await api_bot_post("/admin/matches", json_body={
        "team_a": team_a,
        "team_b": team_b,
        "match_time": match_time
    })
    return int(data.get("match_id"))


async def get_match_api(match_id: int):
    return await api_bot_get(f"/admin/matches/{match_id}")


async def close_match_api(match_id: int):
    await api_bot_post(f"/admin/matches/{match_id}/close", json_body={})


async def resolve_match_api(match_id: int, winner_code: str, score_a=None, score_b=None):
    payload = {"winner_code": winner_code, "score_a": score_a, "score_b": score_b, "reward": config.PREDICTION_REWARD}
    return await api_bot_post(f"/admin/matches/{match_id}/resolve", json_body=payload)


async def get_all_active_matches_api():
    data = await api_bot_get("/admin/matches/active")
    return data.get("items", [])


async def update_match_time_api(match_id: int, match_time: str):
    await api_bot_post(f"/admin/matches/{match_id}/time", json_body={"match_time": match_time})


async def delete_match_api(match_id: int):
    await api_bot_delete(f"/admin/matches/{match_id}")

async def get_open_matches_api(user_id: int):
    data = await api_get("/api/predictions/open", user_id=user_id)
    return data.get("items", []) if isinstance(data, dict) else []

async def get_open_match_api(user_id: int, match_id: int):
    matches = await get_open_matches_api(user_id)
    for match in matches:
        if int(match.get("match_id", 0)) == match_id:
            return match
    return None


async def auto_close_match(context, match_id, delay_seconds):
    """Auto-close betting before match starts"""
    await asyncio.sleep(delay_seconds)
    try:
        match = await get_match_api(match_id)
    except Exception:
        match = None
    if match and match.get("status") == "OPEN":
        await close_match_api(match_id)
        logging.info(f"Auto-closed match #{match_id}")

# --- Handlers ---

async def create_match_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Create a new match prediction
    Usage: /newmatch Team A vs Team B [time]
    Time formats: 15:00, 3:00PM, tomorrow 15:00, 2024-01-20 15:00
    """
    is_admin = await is_admin_or_owner(context.bot, update.effective_chat.id, update.effective_user.id)
    if not is_admin:
        await send_ephemeral_reply(update, context, "⛔ Admin only command.")
        return

    full_text = " ".join(context.args)
    
    if not full_text:
        # Show interactive creation wizard
        await start_match_wizard(update, context)
        return
    
    import re
    
    # Try to extract time from the end (formats: HH:MM, tomorrow HH:MM, YYYY-MM-DD HH:MM)
    match_time = None
    time_pattern = r'\s+(\d{4}-\d{2}-\d{2}\s+\d{1,2}:\d{2}|tomorrow\s+\d{1,2}:\d{2}|\d{1,2}:\d{2}(?:AM|PM)?|today\s+\d{1,2}:\d{2})\s*$'
    time_match = re.search(time_pattern, full_text, re.IGNORECASE)
    
    if time_match:
        time_str = time_match.group(1).strip()
        full_text = full_text[:time_match.start()].strip()
        match_time = parse_match_time(time_str)
    
    # Parse teams
    teams = re.split(r'\s+vs\s+', full_text, flags=re.IGNORECASE)
    
    if len(teams) != 2:
        await send_ephemeral_reply(
            update,
            context,
            "📝 <b>Usage:</b>\n"
            "<code>/newmatch Team A vs Team B [time]</code>\n\n"
            "<b>Time formats:</b>\n"
            "• <code>15:00</code> (today)\n"
            "• <code>tomorrow 15:00</code>\n"
            "• <code>2024-01-20 15:00</code>\n\n"
            "Or just type /newmatch for wizard!",
            parse_mode="HTML",
            delay=ADMIN_EPHEMERAL_DELAY
        )
        return
        
    team_a = teams[0].strip()
    team_b = teams[1].strip()
    
    await create_and_post_match(update, context, team_a, team_b, match_time)

def parse_match_time(time_str):
    """Parse various time formats into datetime string"""
    now = datetime.utcnow()
    time_str = time_str.lower().strip()
    
    try:
        # Full datetime: 2024-01-20 15:00
        if '-' in time_str and len(time_str) > 10:
            dt = datetime.strptime(time_str, '%Y-%m-%d %H:%M')
            return dt.strftime('%Y-%m-%d %H:%M:%S')
        
        # Tomorrow HH:MM
        if time_str.startswith('tomorrow'):
            time_part = time_str.replace('tomorrow', '').strip()
            hour, minute = map(int, time_part.split(':'))
            dt = now + timedelta(days=1)
            dt = dt.replace(hour=hour, minute=minute, second=0)
            return dt.strftime('%Y-%m-%d %H:%M:%S')
        
        # Today HH:MM
        if time_str.startswith('today'):
            time_part = time_str.replace('today', '').strip()
            hour, minute = map(int, time_part.split(':'))
            dt = now.replace(hour=hour, minute=minute, second=0)
            return dt.strftime('%Y-%m-%d %H:%M:%S')
        
        # Just HH:MM (assume today)
        if ':' in time_str:
            # Handle AM/PM
            time_str = time_str.upper().replace('AM', '').replace('PM', '')
            hour, minute = map(int, time_str.split(':'))
            if 'PM' in time_str.upper() and hour < 12:
                hour += 12
            dt = now.replace(hour=hour, minute=minute, second=0)
            # If time has passed, assume tomorrow
            if dt < now:
                dt += timedelta(days=1)
            return dt.strftime('%Y-%m-%d %H:%M:%S')
    except:
        pass
    
    return None

async def start_match_wizard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start interactive match creation"""
    user_id = update.effective_user.id
    
    # Popular quick picks
    keyboard = [
        [InlineKeyboardButton("🏴󠁧󠁢󠁥󠁮󠁧󠁿 Premier League", callback_data="wizard_league_epl")],
        [InlineKeyboardButton("🇪🇸 La Liga", callback_data="wizard_league_laliga")],
        [InlineKeyboardButton("🇮🇹 Serie A", callback_data="wizard_league_seriea")],
        [InlineKeyboardButton("🇩🇪 Bundesliga", callback_data="wizard_league_bundesliga")],
        [InlineKeyboardButton("🇫🇷 Ligue 1", callback_data="wizard_league_ligue1")],
        [InlineKeyboardButton("⚽ Champions League", callback_data="wizard_league_ucl")],
        [InlineKeyboardButton("✏️ Custom Teams", callback_data="wizard_custom")],
        [InlineKeyboardButton("❌ Cancel", callback_data="wizard_cancel")]
    ]
    
    target_chat_id = update.effective_chat.id
    if update.effective_chat.type in ["group", "supergroup"]:
        context.user_data["match_target_chat_id"] = update.effective_chat.id
        target_chat_id = update.effective_user.id
        await send_ephemeral_reply(update, context, "✅ Check your private chat to finish match setup.")
    await context.bot.send_message(
        chat_id=target_chat_id,
        text="⚽ <b>Create New Match</b>\\n\\nSelect a league or enter custom teams:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )

async def create_and_post_match(update, context, team_a, team_b, match_time=None):
    """Create match in DB and post to chat"""
    match_id = await create_match_api(team_a, team_b, match_time)
    
    # Format time display
    time_display = ""
    if match_time:
        try:
            dt = datetime.strptime(match_time, '%Y-%m-%d %H:%M:%S')
            time_display = f"\n⏰ <b>Kickoff:</b> {dt.strftime('%d %b %Y, %H:%M')} UTC"
            
            # Schedule auto-close 5 minutes before kickoff
            now = datetime.utcnow()
            close_time = dt - timedelta(minutes=5)
            if close_time > now:
                delay = (close_time - now).total_seconds()
                asyncio.create_task(auto_close_match(context, match_id, delay))
        except:
            pass
    
    # Prediction buttons
    keyboard = [
        [
            InlineKeyboardButton(f"🏠 {team_a}", callback_data=f"pred_{match_id}_A"),
            InlineKeyboardButton("🤝 Draw", callback_data=f"pred_{match_id}_DRAW"),
            InlineKeyboardButton(f"✈️ {team_b}", callback_data=f"pred_{match_id}_B")
        ],
        [
            InlineKeyboardButton("🔢 Predict Exact Score", callback_data=f"pred_{match_id}_SCORE")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    match_text = (f"⚽ <b>New Match Prediction!</b>\n\n"
                  f"🆔 Match #{match_id}\n"
                  f"🏟️ <b>{team_a}</b> vs <b>{team_b}</b>{time_display}\n\n"
                  f"🎯 Correct prediction: <b>+{config.PREDICTION_REWARD} coins</b>\n\n"
                  f"👇 <b>Make your prediction:</b>")
    
    # Determine target chat(s) for broadcasting
    target_chats = []
    
    # Check if there's a stored target chat ID from the wizard
    if "match_target_chat_id" in context.user_data:
        target_chats.append(context.user_data["match_target_chat_id"])
        # Clean up after use
        del context.user_data["match_target_chat_id"]
    elif update.effective_chat.type in ["group", "supergroup"]:
        # Match created directly in a group
        target_chats.append(update.effective_chat.id)
    else:
        # Created from private chat, broadcast to all groups
        try:
            groups_data = await api_bot_get("/admin/groups")
            all_groups = groups_data.get("chat_ids", [])
            target_chats.extend(all_groups)
        except Exception as e:
            logging.error(f"Failed to get groups for broadcasting: {e}")
            # Fallback: send to current chat only
            target_chats.append(update.effective_chat.id)
    
    # Broadcast match card to all target chats
    broadcast_success = False
    for chat_id in target_chats:
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=match_text,
                reply_markup=reply_markup,
                parse_mode="HTML"
            )
            broadcast_success = True
            logging.info(f"Match #{match_id} broadcast to chat {chat_id}")
        except Exception as e:
            logging.error(f"Failed to broadcast match #{match_id} to chat {chat_id}: {e}")
    
    # If broadcast failed to all groups, try sending to current chat as fallback
    if not broadcast_success:
        try:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=match_text,
                reply_markup=reply_markup,
                parse_mode="HTML"
            )
        except Exception as e:
            logging.error(f"Failed to send match #{match_id} even to current chat: {e}")
    
    # Admin Control Panel
    admin_keyboard = [
        [
            InlineKeyboardButton("🔒 Close Bets", callback_data=f"adm_close_{match_id}"),
            InlineKeyboardButton("⏰ Set Time", callback_data=f"adm_settime_{match_id}")
        ],
        [
            InlineKeyboardButton(f"🏆 {team_a}", callback_data=f"adm_res_{match_id}_A"),
            InlineKeyboardButton("🤝 Draw", callback_data=f"adm_res_{match_id}_DRAW"),
            InlineKeyboardButton(f"🏆 {team_b}", callback_data=f"adm_res_{match_id}_B")
        ],
        [
            InlineKeyboardButton("📊 Set Score", callback_data=f"adm_score_{match_id}"),
            InlineKeyboardButton("🗑️ Delete", callback_data=f"adm_delete_{match_id}")
        ]
    ]
    
    # Send admin panel to admin's private chat to avoid group clutter
    try:
        await context.bot.send_message(
            chat_id=update.effective_user.id,
            text=f"🛠️ <b>Match #{match_id} Admin Panel</b>\\n"
                 f"{team_a} vs {team_b}\\n\\n"
                 "Manage this match:",
            reply_markup=InlineKeyboardMarkup(admin_keyboard),
            parse_mode="HTML"
        )
    except:
        pass

async def admin_prediction_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    chat_id = update.effective_chat.id
    
    # Permission Check - check both bot role and Telegram admin status
    is_admin = await is_admin_or_owner(context.bot, chat_id, user_id)
    if not is_admin:
        await query.answer("🚫 Admin only!", show_alert=True)
        return

    data = query.data  # e.g. adm_close_1 or adm_res_1_A
    parts = data.split("_")
    action = parts[1]
    match_id = int(parts[2])
    
    try:
        match = await get_match_api(match_id)
    except Exception:
        match = None
    if not match:
        await query.answer("Match not found!", show_alert=True)
        return

    if action == "close":
        await close_match_api(match_id)
        await query.answer(f"🔒 Match #{match_id} closed!", show_alert=True)
        await edit_or_ephemeral(
            query.message,
            f"✅ Match #{match_id} is <b>CLOSED</b> for bets.\n\n"
            f"{match.get('team_a')} vs {match.get('team_b')}",
            parse_mode="HTML",
            delay=ADMIN_EPHEMERAL_DELAY
        )
        
    elif action == "res":
        winner_code = parts[3]
        result = await resolve_match_api(match_id, winner_code)
        winners = result.get("winners", []) if isinstance(result, dict) else []
            
        winner_name = winner_code
        if winner_code == 'A': winner_name = match.get("team_a")
        elif winner_code == 'B': winner_name = match.get("team_b")
        else: winner_name = "Draw"

        await query.answer(f"🏁 Match #{match_id} Resolved!", show_alert=True)
        await edit_or_ephemeral(
            query.message,
            f"✅ Match #{match_id} Resolved!\n\n"
            f"{match.get('team_a')} vs {match.get('team_b')}\n"
            f"🏆 Winner: <b>{winner_name}</b>\n"
            f"🎉 {len(winners)} users won {config.PREDICTION_REWARD} coins!",
            parse_mode="HTML",
            delay=ADMIN_EPHEMERAL_DELAY
        )
        
        # Announcement in chat
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"🏁 <b>Match Result!</b>\n\n"
                 f"Match #{match_id}: {match.get('team_a')} vs {match.get('team_b')}\n"
                 f"🏆 Winner: <b>{winner_name}</b>\n"
                 f"🎉 {len(winners)} correct predictions earned {config.PREDICTION_REWARD} coins!",
            parse_mode="HTML"
        )
    
    elif action == "settime":
        await query.answer()
        await edit_or_ephemeral(
            query.message,
            f"⏰ <b>Set Match Time for #{match_id}</b>\n\n"
            f"Reply with time in one of these formats:\n"
            f"• <code>15:00</code> (today)\n"
            f"• <code>tomorrow 15:00</code>\n"
            f"• <code>2024-01-20 15:00</code>\n\n"
            f"Or use: <code>/settime {match_id} 15:00</code>",
            parse_mode="HTML",
            delay=ADMIN_EPHEMERAL_DELAY
        )
    
    elif action == "score":
        await query.answer()
        keyboard = [
            [
                InlineKeyboardButton("1-0", callback_data=f"adm_setscore_{match_id}_1_0"),
                InlineKeyboardButton("2-0", callback_data=f"adm_setscore_{match_id}_2_0"),
                InlineKeyboardButton("3-0", callback_data=f"adm_setscore_{match_id}_3_0"),
            ],
            [
                InlineKeyboardButton("0-1", callback_data=f"adm_setscore_{match_id}_0_1"),
                InlineKeyboardButton("0-2", callback_data=f"adm_setscore_{match_id}_0_2"),
                InlineKeyboardButton("0-3", callback_data=f"adm_setscore_{match_id}_0_3"),
            ],
            [
                InlineKeyboardButton("1-1", callback_data=f"adm_setscore_{match_id}_1_1"),
                InlineKeyboardButton("2-2", callback_data=f"adm_setscore_{match_id}_2_2"),
                InlineKeyboardButton("2-1", callback_data=f"adm_setscore_{match_id}_2_1"),
            ],
            [
                InlineKeyboardButton("1-2", callback_data=f"adm_setscore_{match_id}_1_2"),
                InlineKeyboardButton("3-1", callback_data=f"adm_setscore_{match_id}_3_1"),
                InlineKeyboardButton("3-2", callback_data=f"adm_setscore_{match_id}_3_2"),
            ],
            [InlineKeyboardButton("✏️ Custom Score", callback_data=f"adm_customscore_{match_id}")],
            [InlineKeyboardButton("🔙 Cancel", callback_data=f"adm_cancel_{match_id}")]
        ]
        await edit_or_ephemeral(
            query.message,
            f"📊 <b>Set Final Score for Match #{match_id}</b>\n\n"
            f"{match.get('team_a')} vs {match.get('team_b')}\n\n"
            "Select the final score:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML",
            delay=ADMIN_EPHEMERAL_DELAY
        )
    
    elif action == "setscore":
        score_a = int(parts[3])
        score_b = int(parts[4])
        
        # Determine winner
        if score_a > score_b:
            winner_code = 'A'
        elif score_b > score_a:
            winner_code = 'B'
        else:
            winner_code = 'DRAW'
        
        result = await resolve_match_api(match_id, winner_code, score_a, score_b)
        winners = result.get("winners", []) if isinstance(result, dict) else []
        
        await query.answer(f"✅ Score set: {score_a}-{score_b}", show_alert=True)
        await edit_or_ephemeral(
            query.message,
            f"✅ Match #{match_id} Resolved!\n\n"
            f"{match.get('team_a')} <b>{score_a}</b> - <b>{score_b}</b> {match.get('team_b')}\n\n"
            f"🎉 {len(winners)} users won {config.PREDICTION_REWARD} coins!",
            parse_mode="HTML",
            delay=ADMIN_EPHEMERAL_DELAY
        )
        
        # Announcement
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"🏁 <b>Match Result!</b>\n\n"
                 f"Match #{match_id}\n"
                 f"{match.get('team_a')} <b>{score_a}</b> - <b>{score_b}</b> {match.get('team_b')}\n\n"
                 f"🎉 {len(winners)} correct predictions!",
            parse_mode="HTML"
        )
    
    elif action == "customscore":
        await query.answer()
        await edit_or_ephemeral(
            query.message,
            f"✏️ <b>Enter Custom Score</b>\n\n"
            f"Use: <code>/setresult {match_id} X-Y</code>\n"
            f"Example: <code>/setresult {match_id} 4-2</code>",
            parse_mode="HTML",
            delay=ADMIN_EPHEMERAL_DELAY
        )
    
    elif action == "delete":
        keyboard = [
            [
                InlineKeyboardButton("✅ Yes, Delete", callback_data=f"adm_confirmdelete_{match_id}"),
                InlineKeyboardButton("❌ Cancel", callback_data=f"adm_cancel_{match_id}")
            ]
        ]
        await edit_or_ephemeral(
            query.message,
            f"⚠️ <b>Delete Match #{match_id}?</b>\n\n"
            f"{match[1]} vs {match[2]}\n\n"
            "This will delete all predictions for this match!",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML",
            delay=ADMIN_EPHEMERAL_DELAY
        )
    
    elif action == "confirmdelete":
        await delete_match_api(match_id)
        await query.answer("🗑️ Match deleted!", show_alert=True)
        await edit_or_ephemeral(
            query.message,
            f"🗑️ Match #{match_id} has been deleted.",
            parse_mode="HTML",
            delay=ADMIN_EPHEMERAL_DELAY
        )
    
    elif action == "cancel":
        # Rebuild admin panel
        admin_keyboard = [
            [
                InlineKeyboardButton("🔒 Close Bets", callback_data=f"adm_close_{match_id}"),
                InlineKeyboardButton("⏰ Set Time", callback_data=f"adm_settime_{match_id}")
            ],
            [
                InlineKeyboardButton(f"🏆 {match[1]}", callback_data=f"adm_res_{match_id}_A"),
                InlineKeyboardButton("🤝 Draw", callback_data=f"adm_res_{match_id}_DRAW"),
                InlineKeyboardButton(f"🏆 {match[2]}", callback_data=f"adm_res_{match_id}_B")
            ],
            [
                InlineKeyboardButton("📊 Set Score", callback_data=f"adm_score_{match_id}"),
                InlineKeyboardButton("🗑️ Delete", callback_data=f"adm_delete_{match_id}")
            ]
        ]
        await edit_or_ephemeral(
            query.message,
            f"🛠️ <b>Match #{match_id} Admin Panel</b>\n"
            f"{match.get('team_a')} vs {match.get('team_b')}\n\n"
            "Manage this match:",
            reply_markup=InlineKeyboardMarkup(admin_keyboard),
            parse_mode="HTML",
            delay=ADMIN_EPHEMERAL_DELAY
        )

async def prediction_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    data = query.data
    
    parts = data.split("_")
    
    # Handle pred_show_MATCHID from menu (show prediction buttons)
    if len(parts) == 3 and parts[1] == "show":
        match_id = int(parts[2])
        match = await get_open_match_api(user.id, match_id)
        if not match:
            await query.answer("🛑 Match not found or closed.", show_alert=True)
            return

        team_a, team_b = match.get("team_a"), match.get("team_b")
        
        keyboard = [
            [
                InlineKeyboardButton(f"🏠 {team_a}", callback_data=f"pred_{match_id}_A"),
                InlineKeyboardButton("🤝 Draw", callback_data=f"pred_{match_id}_DRAW"),
                InlineKeyboardButton(f"✈️ {team_b}", callback_data=f"pred_{match_id}_B")
            ],
            [
                InlineKeyboardButton("🔢 Predict Exact Score", callback_data=f"pred_{match_id}_SCORE")
            ]
        ]
        await query.answer()
        await edit_or_ephemeral(
            query.message,
            f"⚽ <b>Match #{match_id}</b>\n\n"
            f"🏟️ {team_a} vs {team_b}\n\n"
            "👇 Make your prediction:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML"
        )
        return
    
    # Format: pred_MATCHID_CHOICE
    if len(parts) != 3:
        await query.answer("Invalid data", show_alert=True)
        return
        
    match_id = int(parts[1])
    choice = parts[2]  # A, B, DRAW, SCORE, notify, stats
    
    match = await get_open_match_api(user.id, match_id)
    if not match:
        await query.answer("🛑 Match not found or closed.", show_alert=True)
        return
    
    # Handle Notify Me button
    if choice == "notify":
        await query.answer("🔔 You'll be notified when this match starts!", show_alert=True)
        return
    
    # Handle View Stats button
    if choice == "stats":
        await query.answer("Open the Web App for stats.", show_alert=True)
        await send_webapp_link(update, context, text="🌐 Open the Web App for match stats.", path="/leaderboards")
        return
        

    if choice == "SCORE":
        await query.answer()
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"🔢 <b>Exact Score Prediction for Match #{match_id}</b>\n\n"
                 f"Reply to this message with the score in format: <code>{match_id} score 2-1</code>",
            parse_mode="HTML"
        )
        return
        
    # Map choice code to meaningful text for alert
    team_name = choice
    if choice == 'A':
        team_name = match.get("team_a")
    elif choice == 'B':
        team_name = match.get("team_b")

    try:
        await api_post("/api/predictions/place", user_id=user.id, json_body={
            "match_id": match_id,
            "choice": choice
        })
        await query.answer(f"✅ Voted for {team_name}!", show_alert=True)
    except Exception as exc:
        message = str(exc)
        if message == "already_predicted":
            message = "❌ You already voted on this match!"
        elif message == "match_closed":
            message = "🛑 Predictions are closed for this match!"
        await query.answer(message, show_alert=True)

async def score_prediction_msg_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handles messages like '1 score 2-1'
    """
    text = update.message.text.strip()
    import re
    # Pattern: MatchID score ScoreA-ScoreB (e.g. 1 score 2-1)
    match = re.match(r'^(\d+)\s+score\s+(\d+)-(\d+)$', text, re.IGNORECASE)
    if not match:
        return # Not a score prediction format, ignore

    match_id = int(match.group(1))
    sa = int(match.group(2))
    sb = int(match.group(3))
    user = update.effective_user

    match = await get_open_match_api(user.id, match_id)
    if not match:
        await send_ephemeral_reply(update, context, "🛑 Match not found or closed.")
        return

    try:
        await api_post("/api/predictions/place", user_id=user.id, json_body={
            "match_id": match_id,
            "choice": "SCORE",
            "score_a": sa,
            "score_b": sb
        })
        await send_ephemeral_reply(
            update,
            context,
            f"✅ Your prediction for Match #{match_id} ({match.get('team_a')} vs {match.get('team_b')}) has been saved: <b>{sa}-{sb}</b>",
            parse_mode="HTML"
        )
    except Exception as exc:
        message = str(exc)
        if message == "already_predicted":
            message = "❌ You already voted on this match!"
        elif message == "match_closed":
            message = "🛑 Predictions are closed for this match."
        await send_ephemeral_reply(update, context, message)

async def predict_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Legacy command, but kept for fallback. Redirects to buttons preferably."""
    await send_ephemeral_reply(update, context, "⚠️ Please use the buttons on the match post to predict!")

async def close_match_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    is_admin = await is_admin_or_owner(context.bot, update.effective_chat.id, update.effective_user.id)
    if not is_admin:
        await send_ephemeral_reply(update, context, "⛔ Admin only command.")
        return

    if not context.args:
        await send_ephemeral_reply(update, context, "Usage: /closematch <MatchID>", delay=ADMIN_EPHEMERAL_DELAY)
        return
        
    try:
        match_id = int(context.args[0])
        await close_match_api(match_id)
        await send_ephemeral_reply(update, context, f"🔒 Match #{match_id} bets are now CLOSED.", delay=ADMIN_EPHEMERAL_DELAY)
    except ValueError:
        await send_ephemeral_reply(update, context, "Invalid Match ID.", delay=ADMIN_EPHEMERAL_DELAY)

async def resolve_match_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Admin Only
    is_admin = await is_admin_or_owner(context.bot, update.effective_chat.id, update.effective_user.id)
    if not is_admin:
        await send_ephemeral_reply(update, context, "⛔ Admin only command.")
        return
        
    # Usage: /setresult <ID> <A/B/DRAW or ScoreA-ScoreB>
    if len(context.args) < 2:
        await send_ephemeral_reply(update, context, "Usage: /setresult <MatchID> <A | B | DRAW | ScoreA-ScoreB>", delay=ADMIN_EPHEMERAL_DELAY)
        return
        
    try:
        match_id = int(context.args[0])
    except ValueError:
        await send_ephemeral_reply(update, context, "Match ID must be a number.", delay=ADMIN_EPHEMERAL_DELAY)
        return
        
    result_input = context.args[1].upper().strip()
    winner_code = None
    score_a = None
    score_b = None

    import re
    score_match = re.match(r'^(\d+)-(\d+)$', result_input)

    if score_match:
        score_a = int(score_match.group(1))
        score_b = int(score_match.group(2))
        if score_a > score_b: winner_code = 'A'
        elif score_b > score_a: winner_code = 'B'
        else: winner_code = 'DRAW'
    elif result_input in ['A', 'B', 'DRAW']:
        winner_code = result_input
    else:
        await send_ephemeral_reply(update, context, "❌ Invalid Result. Use: A, B, DRAW or 2-1", delay=ADMIN_EPHEMERAL_DELAY)
        return
    
    result = await resolve_match_api(match_id, winner_code, score_a, score_b)
    winners = result.get("winners", []) if isinstance(result, dict) else []
    
    try:
        match = await get_match_api(match_id)
    except Exception:
        match = None
    winner_display = winner_code
    if match:
        if winner_code == 'A': winner_display = match.get("team_a")
        elif winner_code == 'B': winner_display = match.get("team_b")
        if score_a is not None:
            winner_display = f"{match.get('team_a')} {score_a} - {score_b} {match.get('team_b')}"
    
    count = len(winners)
        
    await send_ephemeral_reply(
        update,
        context,
        f"🏁 <b>Match Resolved!</b>\n\n"
        f"🏆 Result: <b>{winner_display}</b>\n"
        f"🎉 {count} users guessed correctly and earned {config.PREDICTION_REWARD} coins!",
        parse_mode="HTML",
        delay=ADMIN_EPHEMERAL_DELAY
    )

async def list_matches_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    matches = await get_open_matches_api(update.effective_user.id)
    if not matches:
        await send_ephemeral_reply(update, context, "No open matches right now.")
        return
        
    text = "📅 <b>Open Matches:</b>\n\n"
    keyboard = []
    
    for m in matches:
        text += f"🆔 <b>{m.get('match_id')}</b>: {m.get('team_a')} vs {m.get('team_b')}\n"
        # Optional: Add a "Vote" button that re-sends the prediction keyboard?
        # For now, just listing is fine as per "Basic flow".
        
    await send_ephemeral_reply(update, context, text, parse_mode="HTML")
