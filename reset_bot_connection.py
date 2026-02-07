#!/usr/bin/env python3
"""
Script to check and reset Telegram bot connection.
This helps diagnose and fix 409 Conflict errors by:
1. Checking if a webhook is set
2. Deleting any existing webhook
3. Checking for pending updates
4. Clearing pending updates
"""
import asyncio
import logging
import sys
from telegram import Bot
from telegram.error import TelegramError
import config

logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

async def reset_bot_connection():
    """Reset the bot connection to clear any conflicts."""
    try:
        if not config.BOT_TOKEN:
            logging.error("No BOT_TOKEN found in config!")
            return
        
        bot = Bot(token=config.BOT_TOKEN)
        
        # Get bot info
        logging.info("Getting bot information...")
        bot_info = await bot.get_me()
        logging.info(f"Bot: @{bot_info.username} (ID: {bot_info.id})")
        
        # Check webhook status
        logging.info("\nChecking webhook status...")
        webhook_info = await bot.get_webhook_info()
        
        if webhook_info.url:
            logging.warning(f"⚠️  Webhook is SET to: {webhook_info.url}")
            logging.warning(f"   Pending updates: {webhook_info.pending_update_count}")
            logging.warning(f"   Last error: {webhook_info.last_error_message}")
            logging.info("\nDeleting webhook...")
            result = await bot.delete_webhook(drop_pending_updates=True)
            if result:
                logging.info("✓ Webhook deleted successfully!")
            else:
                logging.error("✗ Failed to delete webhook")
        else:
            logging.info("✓ No webhook is set (using polling mode)")
        
        # Get pending updates count
        logging.info("\nChecking for pending updates...")
        try:
            updates = await bot.get_updates(limit=1, timeout=5)
            if updates:
                logging.info(f"Found {len(updates)} pending update(s)")
                # Get the latest update ID
                latest_update_id = updates[-1].update_id
                # Clear all updates up to and including this one
                await bot.get_updates(offset=latest_update_id + 1, timeout=5)
                logging.info("✓ Cleared pending updates")
            else:
                logging.info("✓ No pending updates")
        except TelegramError as e:
            if "Conflict" in str(e):
                logging.error("⚠️  409 CONFLICT ERROR DETECTED!")
                logging.error("   This means another bot instance is actively polling for updates.")
                logging.error("\nPossible causes:")
                logging.error("   1. Another terminal/process running the bot on THIS machine")
                logging.error("   2. Bot running on ANOTHER machine/server")
                logging.error("   3. Cloud deployment (Heroku, Railway, VPS, etc.)")
                logging.error("   4. Development environment (Replit, Gitpod, etc.)")
                logging.error("\nTo fix this:")
                logging.error("   - Check all terminals and Task Manager for python.exe processes")
                logging.error("   - Check your cloud hosting dashboard")
                logging.error("   - Check your deployment services")
                logging.error("   - Wait 1-2 minutes and try again")
            else:
                logging.error(f"Error getting updates: {e}")
        
        logging.info("\n" + "="*60)
        logging.info("Bot connection reset complete!")
        logging.info("You can now start the bot with: python main.py")
        logging.info("="*60)
        
    except Exception as e:
        logging.error(f"Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(reset_bot_connection())
