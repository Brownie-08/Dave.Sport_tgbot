import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
owner_env = os.getenv("OWNER_ID")
OWNER_ID = int(owner_env) if owner_env and owner_env.strip() else 0
WEBAPP_URL = os.getenv("WEBAPP_URL", "").strip()
API_BASE_URL = os.getenv("API_BASE_URL", "").strip()
BOT_SERVICE_TOKEN = os.getenv("BOT_SERVICE_TOKEN", "").strip()
WELCOME_DELETE_DELAY = 300  # Seconds (5 minutes)
INVITE_REWARD = 5
REACTION_REWARD = 2
LINK_CLICK_REWARD = 5
LINK_SHARE_REWARD = 2
COMMENT_REWARD = 1
PREDICTION_REWARD = 10
WARNING_LIMIT = 3
MUTE_DURATION_MINUTES = 60
