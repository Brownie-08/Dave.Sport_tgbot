import asyncio
from unittest.mock import AsyncMock, MagicMock
from handlers.predictions import create_match_command
from telegram import Update, User, Chat, Message
from telegram.ext import ContextTypes
import sys
import os

# Add current dir to path
sys.path.append(os.getcwd())

async def test_newmatch():
    # Mock Update
    update = MagicMock(spec=Update)
    update.effective_user = MagicMock(spec=User)
    update.effective_user.id = 12345
    update.effective_user.first_name = "Admin"
    
    update.effective_chat = MagicMock(spec=Chat)
    update.effective_chat.id = -10012345
    
    update.message = AsyncMock(spec=Message)
    
    # Mock Context
    context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
    context.args = ["Arsenal", "vs", "Chelsea"]
    
    # Mock database and role checks
    with MagicMock() as mock_roles:
        import handlers.predictions
        # We need to mock the functions imported into predictions.py or the module itself
        handlers.predictions.get_user_role = AsyncMock(return_value="ADMIN")
        handlers.predictions.check_role = MagicMock(return_value=True)
        handlers.predictions.create_match_db = MagicMock(return_value=1)
        
        print("Testing /newmatch Arsenal vs Chelsea...")
        await create_match_command(update, context)
    
    # Check if reply_text was called
    print(f"Reply count: {update.message.reply_text.call_count}")
    for call in update.message.reply_text.call_args_list:
        print(f"Replied with: {call.args[0][:50]}...")

if __name__ == "__main__":
    asyncio.run(test_newmatch())
