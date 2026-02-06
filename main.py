import logging
import asyncio
import os
import sys
import atexit
import signal
from pathlib import Path
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ChatMemberHandler, MessageHandler, CallbackQueryHandler, MessageReactionHandler, InlineQueryHandler, ChosenInlineResultHandler, filters, ContextTypes
from telegram.error import NetworkError
import config
from handlers.welcome import greet_chat_members, track_chats
from handlers.moderation import moderate_message
from handlers.commands import (
    warn_command, mute_command, ban_command, unmute_command, 
    reset_warn_command, user_info_command, moderation_callback_handler
)
from handlers.roles import set_role_command, list_roles_command
from handlers.economy import daily_command, balance_command, leaderboard_command, give_coins_command
from handlers.profile import setup_command, profile_callback
from handlers.invites import start_command, invite_command
from handlers.rewards import reward_callback_handler, reaction_handler, test_rewards_command, handle_admin_link_post
from handlers.predictions import (
    create_match_command, predict_command, resolve_match_command, 
    list_matches_command, close_match_command, prediction_callback_handler, 
    admin_prediction_callback, score_prediction_msg_handler
)
from handlers.articles import post_article_command, auto_track_group, broadcast_callback_handler
from handlers.menu import menu_command, help_command, menu_callback_handler, mypredictions_command, predboard_command, web_command
from handlers.inline import inline_query_handler, chosen_inline_result_handler
from handlers.notifications import notifications_command, notification_callback_handler
from handlers.davesport_feed import subscribe_command, unsubscribe_command, fetch_latest_command, feed_status_command, setsport_command, setchatchannel_command, removechatchannel_command, setup_davesport_job
from handlers.utils import register_and_delete_command

# Logging Setup
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Lock file management
LOCK_FILE = Path("bot.lock")

def acquire_lock():
    """Acquire a lock file to ensure only one bot instance runs at a time."""
    if LOCK_FILE.exists():
        try:
            with open(LOCK_FILE, 'r') as f:
                pid = int(f.read().strip())
            
            # Check if the process with this PID is still running
            try:
                # On Windows, try to open the process
                import ctypes
                kernel32 = ctypes.windll.kernel32
                PROCESS_QUERY_INFORMATION = 0x0400
                handle = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION, False, pid)
                if handle:
                    kernel32.CloseHandle(handle)
                    logging.error(f"Another bot instance is already running (PID: {pid})")
                    logging.error("Please stop the existing instance before starting a new one.")
                    logging.error("If you're sure no other instance is running, delete the 'bot.lock' file.")
                    sys.exit(1)
                else:
                    # Process doesn't exist, remove stale lock file
                    logging.warning(f"Removing stale lock file (PID {pid} not found)")
                    LOCK_FILE.unlink()
            except Exception:
                # If we can't check the process, assume it's not running
                logging.warning("Could not verify old process, removing stale lock file")
                LOCK_FILE.unlink()
        except (ValueError, FileNotFoundError):
            # Invalid lock file, remove it
            logging.warning("Invalid lock file found, removing it")
            LOCK_FILE.unlink()
    
    # Create lock file with current PID
    with open(LOCK_FILE, 'w') as f:
        f.write(str(os.getpid()))
    
    logging.info(f"Lock acquired (PID: {os.getpid()})")
    
    # Register cleanup function
    atexit.register(release_lock)

def release_lock():
    """Release the lock file on exit."""
    if LOCK_FILE.exists():
        try:
            LOCK_FILE.unlink()
            logging.info("Lock file removed")
        except Exception as e:
            logging.warning(f"Failed to remove lock file: {e}")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log the error and handle specific cases like NetworkError."""
    logging.error(msg="Exception while handling an update:", exc_info=context.error)
    
    if isinstance(context.error, NetworkError):
        logging.warning("Network Error: Connection to Telegram API failed. Retrying...")

async def start_services(application):
    """Start background services (FastAPI)."""
    # Allow running bot-only (useful when FastAPI is already started separately)
    if os.getenv("DISABLE_FASTAPI", "").strip() in {"1", "true", "TRUE", "yes", "YES"}:
        logging.info("FastAPI startup disabled via DISABLE_FASTAPI")
        return
    try:
        from backend.server import start_fastapi_server
        server, task = await start_fastapi_server()
        application.bot_data["api_server"] = server
        application.bot_data["api_task"] = task
    except Exception as exc:
        logging.error(f"FastAPI server failed to start: {exc}")


async def stop_services(application):
    """Stop background services (FastAPI)."""
    server = application.bot_data.get("api_server")
    task = application.bot_data.get("api_task")
    if server or task:
        try:
            from backend.server import stop_fastapi_server
            await stop_fastapi_server(server, task)
        except Exception as exc:
            logging.error(f"FastAPI server failed to stop cleanly: {exc}")

async def run_application(application):
    """Run PTB app with explicit init/start to avoid ExtBot initialization issues."""
    await start_services(application)
    try:
        await application.initialize()
        await application.start()
        # Start polling in the background
        await application.updater.start_polling(allowed_updates=Update.ALL_TYPES)

        # Keep the process alive until cancelled (Ctrl+C)
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        pass
    finally:
        try:
            await application.updater.stop()
        except Exception:
            pass
        try:
            await application.stop()
        except Exception:
            pass
        try:
            await application.shutdown()
        except Exception:
            pass
        await stop_services(application)


def main():
    # Acquire lock to ensure only one bot instance runs at a time
    acquire_lock()

    if not config.BOT_TOKEN:
        logging.error("No BOT_TOKEN found in .env file!")
        release_lock()
        return

    application = ApplicationBuilder().token(config.BOT_TOKEN).build()

    # Register Error Handler
    application.add_error_handler(error_handler)

    # Handlers
    # Global command cleanup in groups (run before command handlers)
    application.add_handler(MessageHandler(filters.COMMAND, register_and_delete_command), group=-1)
    
    # 1. Admin Commands
    application.add_handler(CommandHandler("warn", warn_command))
    application.add_handler(CommandHandler("mute", mute_command))
    application.add_handler(CommandHandler("ban", ban_command))
    application.add_handler(CommandHandler("unmute", unmute_command))
    application.add_handler(CommandHandler("resetwarn", reset_warn_command))
    application.add_handler(CommandHandler("userinfo", user_info_command))
    application.add_handler(CommandHandler("setrole", set_role_command))
    application.add_handler(CommandHandler("roles", list_roles_command))

    # 2. Economy Commands
    application.add_handler(CommandHandler("daily", daily_command))
    application.add_handler(CommandHandler("balance", balance_command))
    application.add_handler(CommandHandler("leaderboard", leaderboard_command))
    application.add_handler(CommandHandler("givecoins", give_coins_command))

    # 3. Profile / Setup
    application.add_handler(CommandHandler("setup", setup_command))
    # Profile patterns: menu_..., set_club_..., toggle_int_..., close
    application.add_handler(CallbackQueryHandler(profile_callback, pattern="^(menu_|set_club_|toggle_int_|close)"))
    
    # Reward patterns: clk_..., reward_...
    application.add_handler(CallbackQueryHandler(reward_callback_handler, pattern="^(clk_|reward_)"))
    
    # Prediction patterns: pred_... (users), adm_... (admins)
    application.add_handler(CallbackQueryHandler(prediction_callback_handler, pattern="^pred_"))
    application.add_handler(CallbackQueryHandler(admin_prediction_callback, pattern="^adm_"))
    
    # Moderation patterns: mod_...
    application.add_handler(CallbackQueryHandler(moderation_callback_handler, pattern="^mod_"))
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("invite", invite_command))
    application.add_handler(CommandHandler("testrewards", test_rewards_command))
    
    # Menu and Help
    application.add_handler(CommandHandler("menu", menu_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("web", web_command))
    application.add_handler(CommandHandler("mypredictions", mypredictions_command))
    application.add_handler(CommandHandler("predboard", predboard_command))
    application.add_handler(CallbackQueryHandler(menu_callback_handler, pattern="^(cmd_|info_|admin_|wizard_|main_|pred_menu_|news_|profile_|leaderboard_)"))
    
    # Notifications
    application.add_handler(CommandHandler("notifications", notifications_command))
    application.add_handler(CallbackQueryHandler(notification_callback_handler, pattern="^notif_"))
    
    # Inline Queries (predict from any chat by typing @botusername)
    application.add_handler(InlineQueryHandler(inline_query_handler))
    application.add_handler(ChosenInlineResultHandler(chosen_inline_result_handler))
    
    # Dave.sport Feed Integration (X/Twitter + Website - LOCKED to @davedotsport only)
    application.add_handler(CommandHandler("subscribe", subscribe_command))
    application.add_handler(CommandHandler("unsubscribe", unsubscribe_command))
    application.add_handler(CommandHandler("fetchlatest", fetch_latest_command))
    application.add_handler(CommandHandler("feedstatus", feed_status_command))
    application.add_handler(CommandHandler("setsport", setsport_command))
    application.add_handler(CommandHandler("setchatchannel", setchatchannel_command))
    application.add_handler(CommandHandler("removechatchannel", removechatchannel_command))
    
    # Setup Dave.sport background job
    setup_davesport_job(application)
    
    # Articles / Broadcast
    application.add_handler(CommandHandler("postarticle", post_article_command))
    application.add_handler(CommandHandler("broadcast", post_article_command))  # Alias
    application.add_handler(CallbackQueryHandler(broadcast_callback_handler, pattern="^broadcast_"))

    # 6. Predictions
    application.add_handler(CommandHandler("newmatch", create_match_command))
    application.add_handler(CommandHandler("predict", predict_command))
    application.add_handler(CommandHandler("setresult", resolve_match_command))
    application.add_handler(CommandHandler("closematch", close_match_command))
    application.add_handler(CommandHandler("matches", list_matches_command))
    # Note: prediction_callback_handler already registered above at line 80
    
    # Handle text-based score predictions (e.g., "1 score 2-1")
    application.add_handler(MessageHandler(filters.Regex(r'^\d+\s+score\s+\d+-\d+$'), score_prediction_msg_handler))

    # 5. Welcome / Chat Member Updates
    # ChatMemberHandler.CHAT_MEMBER triggers on join/leave/privilege changes of users
    application.add_handler(ChatMemberHandler(greet_chat_members, ChatMemberHandler.CHAT_MEMBER))
    # ChatMemberHandler.MY_CHAT_MEMBER triggers when the BOT's status changes
    application.add_handler(ChatMemberHandler(track_chats, ChatMemberHandler.MY_CHAT_MEMBER))
    
    # 5. Moderation & Tracking (Text messages, excluding commands)
    application.add_handler(MessageReactionHandler(reaction_handler))
    
    # Admin link rewards handler (checks for URLs in admin messages in groups)
    application.add_handler(MessageHandler(
        filters.TEXT & (~filters.COMMAND) & filters.ChatType.GROUPS & filters.Entity("url"),
        handle_admin_link_post
    ), group=1)  # Run in separate group to not block other handlers
    
    # filters.TEXT & (~filters.COMMAND) ensures we don't double-process commands
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), moderate_message))
    # Auto-track groups on any message
    application.add_handler(MessageHandler(filters.ChatType.GROUPS, auto_track_group))
    
    # Also track updates for general "chat status" if needed, but greet_chat_members covers joins.

    logging.info("Dave.sports Bot is running...")

    # Run (explicit init/start sequence)
    try:
        asyncio.run(run_application(application))
    except KeyboardInterrupt:
        pass
    finally:
        release_lock()

if __name__ == '__main__':
    main()
