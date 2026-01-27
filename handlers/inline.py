from telegram import Update, InlineQueryResultArticle, InputTextMessageContent, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from handlers.api_client import api_get
import hashlib

async def inline_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle inline queries - users can type @botusername in any chat
    to see open matches and share/predict
    """
    query = update.inline_query
    user = query.from_user
    search_text = query.query.lower().strip()
    
    results = []
    try:
        data = await api_get("/api/predictions/open", user_id=user.id)
        matches = data.get("items", []) if isinstance(data, dict) else []
    except Exception:
        matches = []
    
    if not matches:
        # No open matches - show info message
        results.append(
            InlineQueryResultArticle(
                id="no_matches",
                title="📅 No Open Matches",
                description="No matches available for prediction right now",
                input_message_content=InputTextMessageContent(
                    message_text="📅 <b>No open matches right now!</b>\n\nCheck back later for new predictions.",
                    parse_mode="HTML"
                )
            )
        )
    else:
        for match in matches:
            match_id = match.get("match_id")
            team_a = match.get("team_a")
            team_b = match.get("team_b")
            match_time = match.get("match_time")
            
            # Filter by search text if provided
            if search_text:
                if search_text not in team_a.lower() and search_text not in team_b.lower():
                    continue
            
            # Format time display
            time_str = ""
            if match_time:
                try:
                    from datetime import datetime
                    dt = datetime.strptime(match_time, '%Y-%m-%d %H:%M:%S')
                    time_str = f"⏰ {dt.strftime('%d %b, %H:%M')} UTC"
                except:
                    pass
            
            # Create unique ID for this result
            result_id = hashlib.md5(f"match_{match_id}_{user.id}".encode()).hexdigest()
            
            # Prediction buttons that will work in any chat
            keyboard = [
                [
                    InlineKeyboardButton(f"🏠 {team_a}", callback_data=f"pred_{match_id}_A"),
                    InlineKeyboardButton("🤝 Draw", callback_data=f"pred_{match_id}_DRAW"),
                    InlineKeyboardButton(f"✈️ {team_b}", callback_data=f"pred_{match_id}_B")
                ],
                [
                    InlineKeyboardButton("🔢 Exact Score", callback_data=f"pred_{match_id}_SCORE")
                ]
            ]
            
            description = f"Click to predict • {time_str}" if time_str else "Click to make your prediction"
            
            results.append(
                InlineQueryResultArticle(
                    id=result_id,
                    title=f"⚽ {team_a} vs {team_b}",
                    description=description,
                    thumbnail_url="https://img.icons8.com/color/96/football2--v1.png",
                    input_message_content=InputTextMessageContent(
                        message_text=(
                            f"⚽ <b>Match Prediction</b>\n\n"
                            f"🆔 Match #{match_id}\n"
                            f"🏟️ <b>{team_a}</b> vs <b>{team_b}</b>\n"
                            f"{time_str}\n\n"
                            f"👇 Make your prediction:"
                        ),
                        parse_mode="HTML"
                    ),
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            )
    
    # Add quick actions at the end
    results.append(
        InlineQueryResultArticle(
            id="view_all",
            title="📋 View All Matches",
            description="See all open matches in the bot",
            input_message_content=InputTextMessageContent(
                message_text="📋 <b>View all matches:</b>\n\nOpen @" + (context.bot.username or "Dave_sportsBot") + " to see all available predictions!",
                parse_mode="HTML"
            )
        )
    )
    
    results.append(
        InlineQueryResultArticle(
            id="my_predictions",
            title="📊 My Predictions",
            description="Check your prediction history",
            input_message_content=InputTextMessageContent(
                message_text="📊 <b>Check your predictions:</b>\n\nUse /web (or /mypredictions) in @" + (context.bot.username or "Dave_sportsBot") + " to open the Web App.",
                parse_mode="HTML"
            )
        )
    )
    
    results.append(
        InlineQueryResultArticle(
            id="leaderboard",
            title="🏆 Leaderboard",
            description="See top predictors",
            input_message_content=InputTextMessageContent(
                message_text="🏆 <b>Prediction Leaderboard:</b>\n\nUse /web (or /predboard) in @" + (context.bot.username or "Dave_sportsBot") + " to open the Web App.",
                parse_mode="HTML"
            )
        )
    )
    
    await query.answer(results, cache_time=30, is_personal=True)


async def chosen_inline_result_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Called when user selects an inline result
    Can be used for analytics/tracking
    """
    result = update.chosen_inline_result
    user = result.from_user
    result_id = result.result_id
    
    # Log for analytics (optional)
    import logging
    logging.info(f"Inline result chosen: {result_id} by user {user.id}")
