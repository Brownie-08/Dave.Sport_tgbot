from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import ContextTypes
from handlers.roles import get_user_role, check_role, ROLE_MOD, ROLE_ADMIN
from handlers.utils import (
    private_only,
    send_webapp_link,
    edit_or_ephemeral,
    send_ephemeral_reply,
    send_ephemeral_message,
    ADMIN_EPHEMERAL_DELAY,
    build_webapp_url,
    build_webapp_url_with_query
)
from handlers.api_client import api_get, api_post
import config
from shared_constants import EPL_TEAMS, CLUBS_DATA

def webapp_button(label: str, path: str):
    url = build_webapp_url(path)
    if not url:
        return None
    return InlineKeyboardButton(label, web_app=WebAppInfo(url=url))

def main_menu_keyboard():
    def row(*buttons):
        return [b for b in buttons if b]

    keyboard = [
        row(
            webapp_button("🧍 Profile", "/profile"),
            webapp_button("⚽ Predictions", "/predictions")
        ),
        row(
            webapp_button("🏆 Leaderboards", "/leaderboards")
        ),
        [
            InlineKeyboardButton("➕ New Prediction", callback_data="menu_new_prediction"),
            InlineKeyboardButton("📊 My Rank", callback_data="menu_my_rank")
        ],
        [InlineKeyboardButton("❌ Close", callback_data="close")]
    ]
    # Remove any empty rows (e.g., if Web App URL not configured)
    keyboard = [r for r in keyboard if r]
    return InlineKeyboardMarkup(keyboard)

@private_only
async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows the main interactive menu with buttons"""
    await send_ephemeral_reply(
        update,
        context,
        "🏟️ <b>Dave.sports Menu</b>\n\nSelect an option below:",
        reply_markup=main_menu_keyboard(),
        parse_mode="HTML"
    )

@private_only
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows comprehensive help"""
    bot_username = context.bot.username or "Dave_sportsBot"
    user_role = await get_user_role(update.effective_user.id)
    help_text = f"""
🏟️ <b>Dave.sports Bot Help</b>

<b>📱 Quick Access:</b>
/menu - Interactive button menu
@{bot_username} - Inline predictions (any chat!)

<b>💰 Economy:</b>
/daily - Claim daily check-in (2 coins)
/balance - Check your coins

<b>⚽ Predictions:</b>
/matches - View open matches

<b>🌐 Web App (Profile, History & Rankings):</b>
/web - Open Telegram Web App
/leaderboard - (Web App)
/predboard - (Web App)
/mypredictions - (Web App)
/userinfo - (Web App)
/setup - (Web App)
/notifications - (Web App)
/invite - (Web App)

"""
    if check_role(user_role, ROLE_MOD):
        help_text += """

<b>🛡️ Moderation (Mods):</b>
/warn - Warn a user
/mute - Mute a user
/unmute - Unmute a user
/resetwarn - Reset warnings
"""

    if check_role(user_role, ROLE_ADMIN):
        help_text += """

<b>⚡ Admin Commands:</b>
/ban - Ban a user
/newmatch - Create prediction
/setresult - Set match result
/closematch - Close betting
/givecoins - Give coins
/setrole - Change user role
/postarticle - Broadcast message

<b>📡 Dave.sport Feed:</b>
/subscribe - Enable feed
/unsubscribe - Disable feed
/feedstatus - Check feed status
Articles are delivered only to Telegram topics
"""

    help_text += f"""

<b>💡 Tip:</b> Type @{bot_username} in any chat to make predictions!
"""
    await send_ephemeral_reply(update, context, help_text, parse_mode="HTML")

async def menu_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles menu button clicks"""
    query = update.callback_query
    user = query.from_user
    data = query.data
    
    await query.answer()
    
    if data == "menu_new_prediction":
        await show_open_matches_for_prediction(query, user.id)
        return

    if data == "menu_my_rank":
        await show_my_rank(query, user.id)
        return
    if data == "cmd_balance":
        from handlers.economy import balance_command
        # Create a fake update with message for balance command
        await show_balance_inline(query, user.id)
        
    elif data == "cmd_daily":
        from handlers.economy import daily_command
        await show_daily_inline(query, context, user)

    elif data == "main_predictions":
        await show_predictions_menu(query)

    elif data == "pred_menu_new":
        await show_open_matches_for_prediction(query, user.id)

    elif data == "pred_menu_open":
        await show_open_picks_summary(query, user.id)

    elif data == "main_news":
        await show_news_menu(query)

    elif data == "news_top":
        await show_top_headlines(query)

    elif data == "main_profile":
        await show_profile_menu(query)

    elif data == "profile_change_club":
        await show_club_selection(query)

    elif data == "profile_invite":
        await show_invite_link(query, context)

    elif data == "main_leaderboard":
        await show_leaderboard_menu(query)

    elif data == "leaderboard_my_rank":
        await show_my_rank(query, user.id)
        
    elif data == "cmd_leaderboard":
        if config.WEBAPP_URL:
            await edit_or_ephemeral(
                query.message,
                "🌐 <b>Open the Web App</b> for leaderboards and history:",
                reply_markup=InlineKeyboardMarkup([[webapp_button("🌐 Open Web App", "/leaderboards")]]),
                parse_mode="HTML"
            )
        else:
            await query.answer("Web app not configured.", show_alert=True)
        
    elif data == "cmd_matches":
        await show_matches_inline(query)
        
    elif data == "cmd_mypredictions":
        if config.WEBAPP_URL:
            await edit_or_ephemeral(
                query.message,
                "🌐 <b>Open the Web App</b> for your prediction history:",
                reply_markup=InlineKeyboardMarkup([[webapp_button("🌐 Open Web App", "/predictions")]]),
                parse_mode="HTML"
            )
        else:
            await query.answer("Web app not configured.", show_alert=True)
        
    elif data == "cmd_predboard":
        if config.WEBAPP_URL:
            await edit_or_ephemeral(
                query.message,
                "🌐 <b>Open the Web App</b> for prediction analytics:",
                reply_markup=InlineKeyboardMarkup([[webapp_button("🌐 Open Web App", "/leaderboards")]]),
                parse_mode="HTML"
            )
        else:
            await query.answer("Web app not configured.", show_alert=True)
        
    elif data == "cmd_invite":
        if config.WEBAPP_URL:
            await edit_or_ephemeral(
                query.message,
                "🌐 <b>Open the Web App</b> for invites & referrals:",
                reply_markup=InlineKeyboardMarkup([[webapp_button("🌐 Open Web App", "/profile")]]),
                parse_mode="HTML"
            )
        else:
            await query.answer("Web app not configured.", show_alert=True)
        
    elif data == "cmd_setup":
        if config.WEBAPP_URL:
            await edit_or_ephemeral(
                query.message,
                "🌐 <b>Open the Web App</b> to manage your profile & identity:",
                reply_markup=InlineKeyboardMarkup([[webapp_button("🌐 Open Web App", "/profile")]]),
                parse_mode="HTML"
            )
        else:
            await query.answer("Web app not configured.", show_alert=True)
        
    elif data == "cmd_userinfo":
        if config.WEBAPP_URL:
            await edit_or_ephemeral(
                query.message,
                "🌐 <b>Open the Web App</b> for profile details:",
                reply_markup=InlineKeyboardMarkup([[webapp_button("🌐 Open Web App", "/profile")]]),
                parse_mode="HTML"
            )
        else:
            await query.answer("Web app not configured.", show_alert=True)
        
    elif data == "cmd_help":
        await show_help_inline(query)
    
    elif data == "cmd_notifications":
        if config.WEBAPP_URL:
            await edit_or_ephemeral(
                query.message,
                "🌐 <b>Open the Web App</b> to manage notifications:",
                reply_markup=InlineKeyboardMarkup([[webapp_button("🌐 Open Web App", "/profile")]]),
                parse_mode="HTML"
            )
        else:
            await query.answer("Web app not configured.", show_alert=True)
        
    elif data == "cmd_modpanel":
        await show_mod_panel(query)
        
    elif data == "cmd_adminpanel":
        await show_admin_panel(query)
    
    elif data == "admin_davesport_feed":
        await show_davesport_feed_panel(query)
    
    elif data == "admin_feed_sub":
        from handlers.davesport_feed import subscribe_chat
        await subscribe_chat(query.message.chat_id)
        await query.answer("✅ Subscribed to Dave.sport!")
        await show_davesport_feed_panel(query)
    
    elif data == "admin_feed_unsub":
        from handlers.davesport_feed import unsubscribe_chat
        await unsubscribe_chat(query.message.chat_id)
        await query.answer("Unsubscribed from Dave.sport")
        await show_davesport_feed_panel(query)
    
    elif data == "admin_feed_fetch":
        await edit_or_ephemeral(
            query.message,
            "📰 <b>News Delivery</b>\n\n"
            "Articles are delivered only to Telegram topics based on WordPress categories.\n"
            "Open a topic and run <code>/setchatchannel &lt;category&gt;</code> to configure routing.",
            parse_mode="HTML",
            delay=ADMIN_EPHEMERAL_DELAY
        )
        
    elif data == "cmd_back_menu":
        await show_main_menu_edit(query)
    
    # Admin panel handlers
    elif data == "admin_newmatch_start":
        # Check admin permission
        user_role = await get_user_role(user.id)
        if not check_role(user_role, ROLE_ADMIN):
            await query.answer("🚫 Admin only!", show_alert=True)
            return
        await show_newmatch_wizard(query, context)
    
    elif data == "admin_manage_matches":
        user_role = await get_user_role(user.id)
        if not check_role(user_role, ROLE_ADMIN):
            await query.answer("🚫 Admin only!", show_alert=True)
            return
        await show_manage_matches(query)
    
    # Match creation wizard handlers
    elif data.startswith("wizard_league_"):
        league = data.replace("wizard_league_", "")
        await show_league_teams(query, context, league)
    
    elif data == "wizard_custom":
        await edit_or_ephemeral(
            query.message,
            "✏️ <b>Custom Match</b>\n\n"
            "Send the match in this format:\n"
            "<code>/newmatch Team A vs Team B</code>\n\n"
            "<b>Examples:</b>\n"
            "<code>/newmatch Arsenal vs Chelsea 15:00</code>\n"
            "<code>/newmatch Real Madrid vs Barcelona tomorrow 20:00</code>",
            parse_mode="HTML",
            delay=ADMIN_EPHEMERAL_DELAY
        )
    
    elif data.startswith("wizard_team1_"):
        # First team selected, show opponents
        parts = data.split("_")
        league = parts[2]
        team1 = "_".join(parts[3:])  # Handle team names with underscores
        context.user_data["wizard_team1"] = team1
        context.user_data["wizard_league"] = league
        await show_opponent_selection(query, context, league, team1)
    
    elif data.startswith("wizard_team2_"):
        # Second team selected, create match
        team2 = data.replace("wizard_team2_", "").replace("_", " ")
        team1 = context.user_data.get("wizard_team1", "").replace("_", " ")
        league = context.user_data.get("wizard_league", "epl")
        
        if not team1:
            await query.answer("Error: Please start over", show_alert=True)
            return
        
        # Create the match via backend
        from handlers.predictions import create_match_db
        import config
        
        match_id = create_match_db(team1, team2)
        league_name = LEAGUE_NAMES.get(league, "⚽ Football")
        
        # Confirm to admin in private chat
        await edit_or_ephemeral(
            query.message,
            f"✅ <b>Match Created & Announced!</b>\n\n"
            f"🆔 Match #{match_id}\n"
            f"🏟️ <b>{team1}</b> vs <b>{team2}</b>\n\n"
            f"📢 Broadcasting to all groups...",
            parse_mode="HTML",
            delay=ADMIN_EPHEMERAL_DELAY
        )
        
        # Send admin panel to private chat
        admin_keyboard = [
            [
                InlineKeyboardButton("🔒 Close Bets", callback_data=f"adm_close_{match_id}"),
                InlineKeyboardButton("📊 Set Score", callback_data=f"adm_score_{match_id}")
            ],
            [
                InlineKeyboardButton(f"🏆 {team1} Wins", callback_data=f"adm_res_{match_id}_A"),
                InlineKeyboardButton("🤝 Draw", callback_data=f"adm_res_{match_id}_DRAW"),
                InlineKeyboardButton(f"🏆 {team2} Wins", callback_data=f"adm_res_{match_id}_B")
            ],
            [InlineKeyboardButton("🗑️ Delete Match", callback_data=f"adm_delete_{match_id}")]
        ]
        
        await send_ephemeral_message(
            context,
            chat_id=query.message.chat_id,
            text=f"🛠️ <b>Match #{match_id} Admin Panel</b>\n"
                 f"{team1} vs {team2}\n\n"
                 f"<i>Use these buttons to manage the match</i>",
            reply_markup=InlineKeyboardMarkup(admin_keyboard),
            parse_mode="HTML",
            delay=ADMIN_EPHEMERAL_DELAY
        )
        
        # === GLOBAL ANNOUNCEMENT TO ALL GROUPS ===
        # Professional match card for groups
        stats_button = None
        if config.WEBAPP_URL:
            stats_button = InlineKeyboardButton(
                "📊 View Stats",
                web_app=WebAppInfo(url=build_webapp_url("/leaderboards"))
            )

        stats_row = [InlineKeyboardButton("🔔 Notify Me", callback_data=f"pred_{match_id}_notify")]
        if stats_button:
            stats_row.append(stats_button)

        group_keyboard = [
            [
                InlineKeyboardButton(f"🏠 {team1}", callback_data=f"pred_{match_id}_A"),
                InlineKeyboardButton("🤝 Draw", callback_data=f"pred_{match_id}_DRAW"),
                InlineKeyboardButton(f"✈️ {team2}", callback_data=f"pred_{match_id}_B")
            ],
            [
                InlineKeyboardButton("🔢 Predict Exact Score", callback_data=f"pred_{match_id}_SCORE")
            ],
            stats_row
        ]
        
        match_card = (
            f"🏆 <b>NEW MATCH PREDICTION!</b>\n"
            f"────────────────────\n\n"
            f"{league_name}\n\n"
            f"🏠 <b>{team1}</b>\n"
            f"       ⚡ VS ⚡\n"
            f"✈️ <b>{team2}</b>\n\n"
            f"────────────────────\n"
            f"🟢 Status: <b>OPEN</b>\n"
            f"🎯 Reward: <b>+{config.PREDICTION_REWARD} coins</b>\n"
            f"🆔 Match ID: #{match_id}\n\n"
            f"👇 <b>Make your prediction now!</b>"
        )
        
        # Get all groups and post
        try:
            data = await api_bot_get("/admin/groups")
            groups_data = data.get("groups", [])
            groups = [g["chat_id"] for g in groups_data if isinstance(g, dict) and g.get("enabled")]
        except Exception:
            groups = []
        posted_count = 0
        
        for chat_id in groups:
            try:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=match_card,
                    reply_markup=InlineKeyboardMarkup(group_keyboard),
                    parse_mode="HTML"
                )
                posted_count += 1
            except Exception as e:
                # Group might have kicked the bot or doesn't exist
                pass
        
        # Update admin with broadcast result
        await send_ephemeral_message(
            context,
            chat_id=query.message.chat_id,
            text=f"✅ <b>Broadcast Complete!</b>\n\n"
                 f"📢 Match #{match_id} announced to <b>{posted_count}</b> group(s)",
            parse_mode="HTML",
            delay=ADMIN_EPHEMERAL_DELAY
        )
        
        # Clear wizard state
        context.user_data.pop("wizard_team1", None)
        context.user_data.pop("wizard_league", None)
    
    elif data == "info_broadcast":
        await edit_or_ephemeral(
            query.message,
            "📢 <b>Broadcast Message</b>\n\n"
            "<b>Usage:</b>\n"
            "• <code>/postarticle Your message here</code>\n"
            "• Or reply to any message with <code>/postarticle</code>\n\n"
            "This will send the message to all groups where the bot is active.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="cmd_adminpanel")]]),
            parse_mode="HTML",
            delay=ADMIN_EPHEMERAL_DELAY
        )
    
    elif data == "info_givecoins":
        await edit_or_ephemeral(
            query.message,
            "💰 <b>Give Coins</b>\n\n"
            "<b>Usage:</b> Reply to a user's message with:\n"
            "<code>/givecoins &lt;amount&gt;</code>\n\n"
            "Example: <code>/givecoins 100</code>",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="cmd_adminpanel")]]),
            parse_mode="HTML",
            delay=ADMIN_EPHEMERAL_DELAY
        )
    
    elif data == "info_setrole":
        await edit_or_ephemeral(
            query.message,
            "👑 <b>Set User Role</b>\n\n"
            "<b>Usage:</b> Reply to a user's message with:\n"
            "<code>/setrole &lt;role&gt;</code>\n\n"
            "<b>Available roles:</b>\n"
            "• <code>MEMBER</code> - Regular user\n"
            "• <code>MOD</code> - Moderator\n"
            "• <code>ADMIN</code> - Administrator\n"
            "• <code>OWNER</code> - Bot owner",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="cmd_adminpanel")]]),
            parse_mode="HTML",
            delay=ADMIN_EPHEMERAL_DELAY
        )
    
    elif data.startswith("info_"):
        # Generic info handler for mod panel buttons
        await query.answer("Use the command shown on the button")

async def show_predictions_menu(query):
    keyboard = [
        [InlineKeyboardButton("➕ New Prediction", callback_data="pred_menu_new")],
        [InlineKeyboardButton("📌 My Open Picks", callback_data="pred_menu_open")],
        [InlineKeyboardButton("❌ Close", callback_data="close")]
    ]
    await edit_or_ephemeral(
        query.message,
        "⚽ <b>Predictions</b>\n\nChoose an action:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )

async def show_news_menu(query):
    keyboard = [[InlineKeyboardButton("❌ Close", callback_data="close")]]
    await edit_or_ephemeral(
        query.message,
        "📰 <b>News Delivery</b>\n\n"
        "Articles are delivered only to Telegram topics based on WordPress categories.\n"
        "Open a topic and run <code>/setchatchannel &lt;category&gt;</code> to configure routing.",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )

async def show_profile_menu(query):
    keyboard = [
        [InlineKeyboardButton("🧍 View Profile", web_app=WebAppInfo(url=build_webapp_url("/profile")))],
        [InlineKeyboardButton("🏟 Change Club", callback_data="profile_change_club")],
        [InlineKeyboardButton("🎯 Interests", web_app=WebAppInfo(url=build_webapp_url_with_query("/profile", fragment="interests")))],
        [InlineKeyboardButton("🔗 Invite Friends", callback_data="profile_invite")],
        [InlineKeyboardButton("❌ Close", callback_data="close")]
    ]
    await edit_or_ephemeral(
        query.message,
        "👤 <b>Profile</b>\n\nChoose an action:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )

async def show_leaderboard_menu(query):
    keyboard = [
        [InlineKeyboardButton("🥇 View Rankings", web_app=WebAppInfo(url=build_webapp_url("/leaderboards")))],
        [InlineKeyboardButton("📈 My Rank", callback_data="leaderboard_my_rank")],
        [InlineKeyboardButton("❌ Close", callback_data="close")]
    ]
    await edit_or_ephemeral(
        query.message,
        "🏆 <b>Leaderboard</b>\n\nChoose an action:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )

async def show_open_matches_for_prediction(query, user_id):
    try:
        data = await api_get("/api/predictions/open", user_id=user_id)
        matches = data.get("items", []) if isinstance(data, dict) else []
    except Exception:
        matches = []
    matches = matches[:3]
    if not matches:
        await edit_or_ephemeral(query.message, "📅 No open matches right now.")
        return
    text = "⚽ <b>New Prediction</b>\n\nShowing up to 3 open matches:\n\n"
    keyboard = []
    for m in matches:
        match_id = m.get("match_id")
        team_a = m.get("team_a")
        team_b = m.get("team_b")
        match_time = m.get("match_time") or "TBD"
        text += f"🆔 <b>#{match_id}</b>: {team_a} vs {team_b}\n⏰ {match_time}\n\n"
        keyboard.append([InlineKeyboardButton(f"Predict #{match_id}", callback_data=f"pred_show_{match_id}")])
    keyboard.append([InlineKeyboardButton("View full history", web_app=WebAppInfo(url=build_webapp_url("/predictions")))])
    keyboard.append([InlineKeyboardButton("❌ Close", callback_data="close")])
    await edit_or_ephemeral(query.message, text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

async def show_open_picks_summary(query, user_id):
    keyboard = [
        [InlineKeyboardButton("View Predictions", web_app=WebAppInfo(url=build_webapp_url("/predictions")))],
        [InlineKeyboardButton("❌ Close", callback_data="close")]
    ]
    await edit_or_ephemeral(
        query.message,
        "🌐 <b>Open the Web App</b> to view your predictions and history.",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )

async def show_top_headlines(query):
    await edit_or_ephemeral(
        query.message,
        "📰 <b>News Delivery</b>\n\n"
        "Articles are delivered only to Telegram topics based on WordPress categories.\n"
        "Open a topic and run <code>/setchatchannel &lt;category&gt;</code> to configure routing.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Close", callback_data="close")]]),
        parse_mode="HTML"
    )

async def show_my_rank(query, user_id):
    try:
        data = await api_get("/api/leaderboards/global", user_id=user_id, params={"page": 1, "limit": 1})
    except Exception:
        data = {}
    total_users = data.get("total_users") or 0
    rank_position = data.get("current_user_rank")
    if total_users == 0 or not rank_position:
        await edit_or_ephemeral(query.message, "🏆 No ranking data available yet.")
        return
    top_percent = round((rank_position / total_users) * 100, 1)
    text = (
        "🏆 <b>Your Rank</b>\n\n"
        f"#{rank_position} / {total_users} users\n"
        f"Top {top_percent}%"
    )
    keyboard = [
        [InlineKeyboardButton("🥇 View Rankings", web_app=WebAppInfo(url=build_webapp_url("/leaderboards")))],
        [InlineKeyboardButton("❌ Close", callback_data="close")]
    ]
    await edit_or_ephemeral(query.message, text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

async def show_club_selection(query):
    keyboard = []
    row = []
    for club in sorted(CLUBS_DATA.keys()):
        label = CLUBS_DATA[club]["name"]
        row.append(InlineKeyboardButton(label, callback_data=f"set_club_{club}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("❌ Close", callback_data="close")])
    await edit_or_ephemeral(
        query.message,
        "🏟️ <b>Change Club</b>\nSelect your club:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )

async def show_invite_link(query, context):
    bot_username = context.bot.username or "Dave_sportsBot"
    invite_link = f"https://t.me/{bot_username}?start={query.from_user.id}"
    keyboard = [
        [InlineKeyboardButton("🔗 Open Invite Link", url=invite_link)],
        [InlineKeyboardButton("❌ Close", callback_data="close")]
    ]
    text = (
        "🔗 <b>Invite Friends</b>\n\n"
        f"{invite_link}"
    )
    await edit_or_ephemeral(query.message, text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

async def show_balance_inline(query, user_id):
    try:
        data = await api_get("/api/wallet", user_id=user_id)
        coins = data.get("coins", 0)
        await edit_or_ephemeral(
            query.message,
            f"💰 <b>Your Balance</b>\n\nCoins: <b>{coins}</b>",
            parse_mode="HTML"
        )
    except Exception as exc:
        await edit_or_ephemeral(query.message, f"⚠️ Failed to fetch balance: {exc}")

async def show_daily_inline(query, context, user):
    try:
        data = await api_post("/api/rewards/daily", user_id=user.id)
    except Exception as exc:
        await edit_or_ephemeral(query.message, f"⚠️ Failed to claim daily reward: {exc}")
        return

    if data.get("claimed"):
        added = data.get("coins_added", 2)
        balance = data.get("balance", 0)
        msg_text = (
            f"💰 <b>Daily Reward!</b>\n\n"
            f"You've claimed <b>{added}</b> coins!\n"
            f"New Balance: <b>{balance}</b>"
        )
    else:
        retry = data.get("retry_in") or {}
        hours = retry.get("hours", 0)
        minutes = retry.get("minutes", 0)
        msg_text = f"⏳ Already claimed!\nTry again in <b>{hours}h {minutes}m</b>."

    await edit_or_ephemeral(query.message, msg_text, parse_mode="HTML")

async def show_leaderboard_inline(query):
    keyboard = [
        [InlineKeyboardButton("View Leaderboards", web_app=WebAppInfo(url=build_webapp_url("/leaderboards")))],
        [InlineKeyboardButton("❌ Close", callback_data="close")]
    ]
    await edit_or_ephemeral(
        query.message,
        "🌐 <b>Open the Web App</b> to view leaderboards.",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )

async def show_matches_inline(query):
    try:
        data = await api_get("/api/predictions/open", user_id=query.from_user.id)
        matches = data.get("items", []) if isinstance(data, dict) else []
    except Exception:
        matches = []
    matches = matches[:3]
    
    if not matches:
        await edit_or_ephemeral(query.message, "📅 No open matches right now.")
        return
    
    text = "📅 <b>Open Matches:</b>\n\nShowing up to 3 matches:\n\n"
    keyboard = []
    
    for m in matches:
        match_time = m.get("match_time") or "TBD"
        match_id = m.get("match_id")
        text += f"🆔 <b>#{match_id}</b>: {m.get('team_a')} vs {m.get('team_b')}\n⏰ {match_time}\n\n"
        keyboard.append([
            InlineKeyboardButton(f"Predict #{match_id}", callback_data=f"pred_show_{match_id}")
        ])
    keyboard.append([InlineKeyboardButton("View full history", web_app=WebAppInfo(url=build_webapp_url("/predictions")))])
    keyboard.append([InlineKeyboardButton("❌ Close", callback_data="close")])
    
    reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
    await edit_or_ephemeral(query.message, text, reply_markup=reply_markup, parse_mode="HTML")

async def show_mypredictions_inline(query, user_id):
    keyboard = [
        [InlineKeyboardButton("View Predictions", web_app=WebAppInfo(url=build_webapp_url("/predictions")))],
        [InlineKeyboardButton("❌ Close", callback_data="close")]
    ]
    await edit_or_ephemeral(
        query.message,
        "🌐 <b>Open the Web App</b> to view your predictions and stats.",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )

async def show_prediction_leaderboard_inline(query):
    keyboard = [
        [InlineKeyboardButton("View Leaderboards", web_app=WebAppInfo(url=build_webapp_url("/leaderboards")))],
        [InlineKeyboardButton("❌ Close", callback_data="close")]
    ]
    await edit_or_ephemeral(
        query.message,
        "🌐 <b>Open the Web App</b> to view leaderboards.",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )

async def show_userinfo_inline(query, user_id):
    try:
        data = await api_get("/api/me", user_id=user_id)
    except Exception:
        data = {}
    if not data:
        await edit_or_ephemeral(query.message, "User not found.")
        return

    club = data.get("club")
    club_label = club.get("label") if isinstance(club, dict) else None
    interests = data.get("interests") or []
    interests_text = ", ".join(interests) if interests else "Not set"

    info = (
        f"👤 <b>Your Profile</b>\n\n"
        f"🆔 ID: <code>{data.get('id', user_id)}</code>\n"
        f"🔰 Role: {data.get('role', 'user')}\n"
        f"🛡️ Club: <b>{club_label or 'Not set'}</b>\n"
        f"💰 Coins: {data.get('coins', 0)}\n"
        f"📺 Interests: {interests_text}"
    )
    await edit_or_ephemeral(query.message, info, parse_mode="HTML")

async def show_help_inline(query):
    user_role = await get_user_role(query.from_user.id)
    help_text = """
🏟️ <b>Quick Help</b>

<b>💰 Economy:</b>
/daily, /balance

<b>⚽ Predictions:</b>
/matches

<b>🌐 Web App (Profile, History & Rankings):</b>
/web
/leaderboard, /predboard, /mypredictions
/userinfo, /setup, /notifications, /invite

<i>Use /menu for button access!</i>
"""
    if check_role(user_role, ROLE_MOD):
        help_text += """

<b>🛡️ Moderation:</b>
/warn, /mute, /unmute, /resetwarn
"""
    if check_role(user_role, ROLE_ADMIN):
        help_text += """

<b>⚡ Admin:</b>
/ban, /newmatch, /setresult, /closematch, /givecoins, /setrole, /postarticle

<b>📡 Feed:</b>
/subscribe, /unsubscribe, /feedstatus
Articles are delivered only to Telegram topics
"""
    await edit_or_ephemeral(query.message, help_text, parse_mode="HTML")

@private_only
async def web_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_webapp_link(update, context, text="🌐 Open the Web App for history & analytics.", path="/")

async def show_mod_panel(query):
    keyboard = [
        [InlineKeyboardButton("ℹ️ Warn: /warn @user", callback_data="info_warn")],
        [InlineKeyboardButton("ℹ️ Mute: /mute @user [mins]", callback_data="info_mute")],
        [InlineKeyboardButton("ℹ️ Unmute: /unmute @user", callback_data="info_unmute")],
        [InlineKeyboardButton("ℹ️ Reset Warns: /resetwarn @user", callback_data="info_reset")],
        [InlineKeyboardButton("🔙 Back", callback_data="cmd_back_menu")]
    ]
    await edit_or_ephemeral(
        query.message,
        "🛡️ <b>Mod Panel</b>\n\n"
        "Reply to a user's message or mention @username:\n",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )

async def show_admin_panel(query):
    keyboard = [
        [InlineKeyboardButton("➕ New Match", callback_data="admin_newmatch_start")],
        [InlineKeyboardButton("📋 Manage Matches", callback_data="admin_manage_matches")],
        [InlineKeyboardButton("📡 Dave.sport Feed", callback_data="admin_davesport_feed")],
        [InlineKeyboardButton("📢 Broadcast", callback_data="info_broadcast")],
        [InlineKeyboardButton("💰 Give Coins", callback_data="info_givecoins")],
        [InlineKeyboardButton("👑 Set Role", callback_data="info_setrole")],
        [InlineKeyboardButton("🔙 Back", callback_data="cmd_back_menu")]
    ]
    await edit_or_ephemeral(
        query.message,
        "⚡ <b>Admin Panel</b>\n\n"
        "Select an action:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML",
        delay=ADMIN_EPHEMERAL_DELAY
    )

async def show_newmatch_wizard(query, context):
    """Shows the new match creation wizard"""
    keyboard = [
        [InlineKeyboardButton("🏴‍☠️ Premier League", callback_data="wizard_league_epl")],
        [InlineKeyboardButton("🇪🇸 La Liga", callback_data="wizard_league_laliga")],
        [InlineKeyboardButton("🇮🇹 Serie A", callback_data="wizard_league_seriea")],
        [InlineKeyboardButton("🇩🇪 Bundesliga", callback_data="wizard_league_bundesliga")],
        [InlineKeyboardButton("🇫🇷 Ligue 1", callback_data="wizard_league_ligue1")],
        [InlineKeyboardButton("⚽ Champions League", callback_data="wizard_league_ucl")],
        [InlineKeyboardButton("✏️ Custom Teams", callback_data="wizard_custom")],
        [InlineKeyboardButton("🔙 Back", callback_data="cmd_adminpanel")]
    ]
    
    await edit_or_ephemeral(
        query.message,
        "⚽ <b>Create New Match</b>\n\n"
        "Select a league or enter custom teams:\n\n"
        "<i>Or use command:</i>\n"
        "<code>/newmatch Team A vs Team B 15:00</code>",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML",
        delay=ADMIN_EPHEMERAL_DELAY
    )

async def show_manage_matches(query):
    """Shows list of active matches with management options"""
    from handlers.predictions import get_all_active_matches_api
    
    matches = await get_all_active_matches_api()
    
    if not matches:
        keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="cmd_adminpanel")]]
        await edit_or_ephemeral(
            query.message,
            "📋 <b>Manage Matches</b>\n\n"
            "No active matches found.\n\n"
            "Use <b>➕ New Match</b> to create one.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML",
            delay=ADMIN_EPHEMERAL_DELAY
        )
        return
    
    text = "📋 <b>Active Matches</b>\n\n"
    keyboard = []
    
    for m in matches[:10]:  # Limit to 10 matches
        match_id = m.get("match_id")
        team_a = m.get("team_a")
        team_b = m.get("team_b")
        status = m.get("status") or "OPEN"
        
        status_icon = "🟢" if status == "OPEN" else "🟡" if status == "CLOSED" else "⚪"
        text += f"{status_icon} <b>#{match_id}</b>: {team_a} vs {team_b} ({status})\n"
        
        # Add manage button for each match
        keyboard.append([InlineKeyboardButton(
            f"⚙️ Manage #{match_id}", 
            callback_data=f"adm_cancel_{match_id}"  # This will show the admin panel for this match
        )])
    
    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="cmd_adminpanel")])
    
    text += "\n<i>Click to manage a match</i>"
    
    await edit_or_ephemeral(query.message, text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML", delay=ADMIN_EPHEMERAL_DELAY)

# League team data for the wizard
LEAGUE_TEAMS = {
    "epl": EPL_TEAMS,
    "laliga": [
        "Real Madrid", "Barcelona", "Atletico Madrid", "Athletic Bilbao",
        "Real Sociedad", "Villarreal", "Real Betis", "Sevilla", "Valencia",
        "Girona", "Celta Vigo", "Osasuna", "Getafe", "Mallorca"
    ],
    "seriea": [
        "Inter Milan", "AC Milan", "Juventus", "Napoli", "Roma",
        "Lazio", "Atalanta", "Fiorentina", "Bologna", "Torino"
    ],
    "bundesliga": [
        "Bayern Munich", "Dortmund", "RB Leipzig", "Leverkusen",
        "Frankfurt", "Wolfsburg", "Freiburg", "Union Berlin", "Stuttgart"
    ],
    "ligue1": [
        "PSG", "Monaco", "Marseille", "Lyon", "Lille",
        "Nice", "Lens", "Rennes", "Strasbourg"
    ],
    "ucl": [
        "Real Madrid", "Man City", "Bayern Munich", "PSG", "Barcelona",
        "Liverpool", "Arsenal", "Inter Milan", "Dortmund", "Atletico Madrid",
        "Chelsea", "Juventus", "AC Milan", "Napoli", "Benfica"
    ]
}

LEAGUE_NAMES = {
    "epl": "🏴‍☠️ Premier League",
    "laliga": "🇪🇸 La Liga",
    "seriea": "🇮🇹 Serie A",
    "bundesliga": "🇩🇪 Bundesliga",
    "ligue1": "🇫🇷 Ligue 1",
    "ucl": "⭐ Champions League"
}

async def show_league_teams(query, context, league):
    """Show teams from a league for selection"""
    teams = LEAGUE_TEAMS.get(league, [])
    league_name = LEAGUE_NAMES.get(league, league.upper())
    
    if not teams:
        await query.answer("League not found", show_alert=True)
        return
    
    keyboard = []
    row = []
    for team in teams:
        team_safe = team.replace(" ", "_")
        row.append(InlineKeyboardButton(team, callback_data=f"wizard_team1_{league}_{team_safe}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    
    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="admin_newmatch_start")])
    
    await edit_or_ephemeral(
        query.message,
        f"⚽ <b>{league_name}</b>\n\n"
        "Select the <b>HOME</b> team:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML",
        delay=ADMIN_EPHEMERAL_DELAY
    )

async def show_opponent_selection(query, context, league, team1):
    """Show opponent selection after first team is chosen"""
    teams = LEAGUE_TEAMS.get(league, [])
    league_name = LEAGUE_NAMES.get(league, league.upper())
    team1_display = team1.replace("_", " ")
    
    keyboard = []
    row = []
    for team in teams:
        if team.replace(" ", "_") == team1:  # Skip the already selected team
            continue
        team_safe = team.replace(" ", "_")
        row.append(InlineKeyboardButton(team, callback_data=f"wizard_team2_{team_safe}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    
    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data=f"wizard_league_{league}")])
    
    await edit_or_ephemeral(
        query.message,
        f"⚽ <b>{league_name}</b>\n\n"
        f"🏠 Home: <b>{team1_display}</b>\n\n"
        "Select the <b>AWAY</b> team:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML",
        delay=ADMIN_EPHEMERAL_DELAY
    )

async def show_davesport_feed_panel(query):
    """Shows Dave.sport feed management panel"""
    chat_id = query.message.chat_id
    
    # Check subscription status via backend
    try:
        data = await api_bot_get(f"/admin/groups/{chat_id}/feed-status")
        is_subscribed = data.get("subscribed", False)
        twitter_on = data.get("twitter_enabled", False)
        website_on = data.get("website_enabled", False)
    except Exception:
        is_subscribed = False
        twitter_on = False
        website_on = False
    
    status = "✅ Active" if is_subscribed else "❌ Inactive"
    
    keyboard = []
    

    if is_subscribed:
        keyboard.append([InlineKeyboardButton("❌ Unsubscribe", callback_data="admin_feed_unsub")])
    else:
        keyboard.append([InlineKeyboardButton("✅ Subscribe", callback_data="admin_feed_sub")])
    
    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="cmd_adminpanel")])
    
    text = (
        "📡 <b>Dave.sport Feed</b>\n\n"
        f"Status: {status}\n\n"
        "<b>Sources (locked):</b>\n"
        "• 📱 X/Twitter: @davedotsport\n"
        "• 📰 Website: davedotsport.com\n\n"
        "<i>New content is auto-posted every 5 minutes</i>\n"
        "<i>Articles are delivered only to Telegram topics</i>\n\n"
        "<b>Commands:</b>\n"
        "/subscribe - Enable feed\n"
        "/unsubscribe - Disable feed\n"
        "/feedstatus - Check status"
    )
    
    await edit_or_ephemeral(query.message, text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML", delay=ADMIN_EPHEMERAL_DELAY)

async def show_main_menu_edit(query):
    await edit_or_ephemeral(
        query.message,
        "🏟️ <b>Dave.sports Menu</b>\n\nSelect an option below:",
        reply_markup=main_menu_keyboard(),
        parse_mode="HTML"
    )

# Standalone commands for direct access
@private_only
async def mypredictions_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Redirect to Web App for prediction history"""
    await send_webapp_link(update, context, text="🌐 Open the Web App for your prediction history.", path="/predictions")

@private_only
async def predboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Redirect to Web App for prediction leaderboard"""
    await send_webapp_link(update, context, text="🌐 Open the Web App for prediction analytics.", path="/leaderboards")
