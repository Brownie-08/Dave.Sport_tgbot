"""
Twitter/X Integration for Dave.sports Bot
Fetches tweets from specified accounts and posts them to Telegram groups.

SETUP REQUIRED:
1. Create a Twitter Developer account at https://developer.twitter.com
2. Create a project and get your API keys
3. Add to your .env file:
   TWITTER_BEARER_TOKEN=your_bearer_token_here

Alternative: Uses Nitter instances as fallback if no API key is provided.
"""

import os
import asyncio
import aiohttp
import logging
import re
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from handlers.roles import get_user_role, check_role, ROLE_ADMIN
from handlers.utils import send_ephemeral_reply, ADMIN_EPHEMERAL_DELAY

# Try to import async database, fallback to sync
try:
    from async_database import (
        add_twitter_feed, remove_twitter_feed, get_active_twitter_feeds,
        update_last_tweet_id, is_tweet_posted, mark_tweet_posted,
        SPORT_TYPES, get_sport_emoji
    )
    ASYNC_DB = True
except ImportError:
    ASYNC_DB = False
    SPORT_TYPES = {
        'football': '⚽ Football',
        'boxing': '🥊 Boxing',
        'ufc': '🥋 UFC/MMA',
        'f1': '🏎️ Formula 1',
        'golf': '⛳ Golf',
        'darts': '🎯 Darts',
        'general': '🏟️ General'
    }

# Twitter API configuration
TWITTER_BEARER_TOKEN = os.getenv("TWITTER_BEARER_TOKEN")
TWITTER_API_BASE = "https://api.twitter.com/2"

# Nitter instances (fallback if no API key)
NITTER_INSTANCES = [
    "https://nitter.net",
    "https://nitter.privacydev.net",
    "https://nitter.poast.org"
]

class TwitterClient:
    """Twitter API client with Nitter fallback"""
    
    def __init__(self, bearer_token: str = None):
        self.bearer_token = bearer_token or TWITTER_BEARER_TOKEN
        self.use_api = bool(self.bearer_token)
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session
    
    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()
    
    async def get_user_tweets(self, username: str, since_id: str = None, limit: int = 5) -> List[Dict]:
        """Get recent tweets from a user"""
        if self.use_api:
            return await self._get_tweets_api(username, since_id, limit)
        else:
            return await self._get_tweets_nitter(username, limit)
    
    async def _get_tweets_api(self, username: str, since_id: str = None, limit: int = 5) -> List[Dict]:
        """Fetch tweets using official Twitter API v2"""
        session = await self.get_session()
        
        headers = {
            "Authorization": f"Bearer {self.bearer_token}"
        }
        
        try:
            # First get user ID
            user_url = f"{TWITTER_API_BASE}/users/by/username/{username}"
            async with session.get(user_url, headers=headers) as resp:
                if resp.status != 200:
                    logging.error(f"Twitter API error getting user: {resp.status}")
                    return []
                user_data = await resp.json()
                user_id = user_data.get("data", {}).get("id")
                if not user_id:
                    return []
            
            # Get tweets
            tweets_url = f"{TWITTER_API_BASE}/users/{user_id}/tweets"
            params = {
                "max_results": limit,
                "tweet.fields": "created_at,text,entities,attachments",
                "expansions": "attachments.media_keys",
                "media.fields": "url,preview_image_url"
            }
            if since_id:
                params["since_id"] = since_id
            
            async with session.get(tweets_url, headers=headers, params=params) as resp:
                if resp.status != 200:
                    logging.error(f"Twitter API error getting tweets: {resp.status}")
                    return []
                
                data = await resp.json()
                tweets = data.get("data", [])
                media_dict = {}
                
                # Process media
                for media in data.get("includes", {}).get("media", []):
                    media_dict[media["media_key"]] = media.get("url") or media.get("preview_image_url")
                
                result = []
                for tweet in tweets:
                    tweet_data = {
                        "id": tweet["id"],
                        "text": tweet["text"],
                        "created_at": tweet.get("created_at"),
                        "url": f"https://twitter.com/{username}/status/{tweet['id']}",
                        "media": []
                    }
                    
                    # Add media URLs
                    if "attachments" in tweet and "media_keys" in tweet["attachments"]:
                        for key in tweet["attachments"]["media_keys"]:
                            if key in media_dict:
                                tweet_data["media"].append(media_dict[key])
                    
                    result.append(tweet_data)
                
                return result
                
        except Exception as e:
            logging.error(f"Twitter API error: {e}")
            return []
    
    async def _get_tweets_nitter(self, username: str, limit: int = 5) -> List[Dict]:
        """Fetch tweets using Nitter (fallback, no API key needed)"""
        session = await self.get_session()
        
        for instance in NITTER_INSTANCES:
            try:
                url = f"{instance}/{username}/rss"
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status != 200:
                        continue
                    
                    content = await resp.text()
                    tweets = self._parse_nitter_rss(content, username, limit)
                    if tweets:
                        return tweets
                        
            except Exception as e:
                logging.debug(f"Nitter instance {instance} failed: {e}")
                continue
        
        logging.warning(f"All Nitter instances failed for @{username}")
        return []
    
    def _parse_nitter_rss(self, content: str, username: str, limit: int) -> List[Dict]:
        """Parse Nitter RSS feed"""
        import xml.etree.ElementTree as ET
        
        try:
            root = ET.fromstring(content)
            items = root.findall(".//item")[:limit]
            
            tweets = []
            for item in items:
                title = item.find("title")
                link = item.find("link")
                pub_date = item.find("pubDate")
                description = item.find("description")
                
                if title is None or link is None:
                    continue
                
                # Extract tweet ID from link
                link_text = link.text or ""
                tweet_id_match = re.search(r'/status/(\d+)', link_text)
                tweet_id = tweet_id_match.group(1) if tweet_id_match else None
                
                if not tweet_id:
                    continue
                
                # Clean text
                text = title.text or ""
                if text.startswith("RT by"):
                    continue  # Skip retweets
                
                # Extract media from description
                media = []
                if description is not None and description.text:
                    img_matches = re.findall(r'src="([^"]+)"', description.text)
                    for img in img_matches:
                        if 'pic/' in img or 'media/' in img:
                            media.append(img)
                
                tweets.append({
                    "id": tweet_id,
                    "text": text,
                    "created_at": pub_date.text if pub_date is not None else None,
                    "url": f"https://twitter.com/{username}/status/{tweet_id}",
                    "media": media
                })
            
            return tweets
            
        except ET.ParseError as e:
            logging.error(f"RSS parse error: {e}")
            return []

# Global client instance
_twitter_client: Optional[TwitterClient] = None

def get_twitter_client() -> TwitterClient:
    global _twitter_client
    if _twitter_client is None:
        _twitter_client = TwitterClient()
    return _twitter_client

# ============ COMMAND HANDLERS ============

async def add_feed_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add a Twitter feed to track: /addfeed @username [sport]"""
    user_role = await get_user_role(update.effective_user.id)
    if not check_role(user_role, ROLE_ADMIN):
        await send_ephemeral_reply(update, context, "⛔ Admin only command.")
        return
    
    if not context.args:
        sports_list = "\n".join([f"• {k} - {v}" for k, v in SPORT_TYPES.items()])
        await send_ephemeral_reply(
            update,
            context,
            "📰 <b>Add Twitter Feed</b>\n\n"
            "Usage: <code>/addfeed @username [sport]</code>\n\n"
            f"<b>Available sports:</b>\n{sports_list}\n\n"
            "Example: <code>/addfeed @SkySportsNews football</code>",
            parse_mode="HTML",
            delay=ADMIN_EPHEMERAL_DELAY
        )
        return
    
    username = context.args[0].lstrip('@').lower()
    sport_type = context.args[1].lower() if len(context.args) > 1 else 'general'
    
    if sport_type not in SPORT_TYPES:
        sport_type = 'general'
    
    chat_id = update.effective_chat.id
    
    if ASYNC_DB:
        success = await add_twitter_feed(username, chat_id, sport_type)
    else:
        # Backend API handles this now
        success = False
    
    if success:
        await send_ephemeral_reply(
            update,
            context,
            f"✅ Now tracking <b>@{username}</b>\n"
            f"Category: {SPORT_TYPES.get(sport_type, sport_type)}\n\n"
            "New posts will be automatically shared to this chat!",
            parse_mode="HTML",
            delay=ADMIN_EPHEMERAL_DELAY
        )
    else:
        await send_ephemeral_reply(update, context, "❌ Failed to add feed. Try again later.", delay=ADMIN_EPHEMERAL_DELAY)

async def remove_feed_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Remove a Twitter feed: /removefeed @username"""
    user_role = await get_user_role(update.effective_user.id)
    if not check_role(user_role, ROLE_ADMIN):
        await send_ephemeral_reply(update, context, "⛔ Admin only command.")
        return
    
    if not context.args:
        await send_ephemeral_reply(update, context, "Usage: <code>/removefeed @username</code>", parse_mode="HTML", delay=ADMIN_EPHEMERAL_DELAY)
        return
    
    username = context.args[0].lstrip('@').lower()
    chat_id = update.effective_chat.id
    
    if ASYNC_DB:
        await remove_twitter_feed(username, chat_id)
    else:
        # Backend API handles this now
        pass
    
    await send_ephemeral_reply(update, context, f"✅ Stopped tracking <b>@{username}</b>", parse_mode="HTML", delay=ADMIN_EPHEMERAL_DELAY)

async def list_feeds_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all Twitter feeds for this chat: /listfeeds"""
    chat_id = update.effective_chat.id
    
    if ASYNC_DB:
        from async_database import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            cursor = await conn.execute(
                'SELECT twitter_username, sport_type FROM twitter_feeds WHERE chat_id = ? AND is_active = 1',
                (chat_id,)
            )
            feeds = await cursor.fetchall()
    else:
        # Backend API handles this now
        feeds = []
    
    if not feeds:
        await send_ephemeral_reply(update, context, "📰 No Twitter feeds configured for this chat.\n\nUse /addfeed to add one!", delay=ADMIN_EPHEMERAL_DELAY)
        return
    
    text = "📰 <b>Active Twitter Feeds</b>\n\n"
    for username, sport in feeds:
        emoji = SPORT_TYPES.get(sport, '🏟️').split()[0]
        text += f"{emoji} @{username}\n"
    
    text += "\n<i>Use /removefeed @username to remove</i>"
    await send_ephemeral_reply(update, context, text, parse_mode="HTML", delay=ADMIN_EPHEMERAL_DELAY)

async def fetch_tweet_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manually fetch and post latest tweet: /fetchtweet @username"""
    user_role = await get_user_role(update.effective_user.id)
    if not check_role(user_role, ROLE_ADMIN):
        await send_ephemeral_reply(update, context, "⛔ Admin only command.")
        return
    
    if not context.args:
        await send_ephemeral_reply(update, context, "Usage: <code>/fetchtweet @username</code>", parse_mode="HTML", delay=ADMIN_EPHEMERAL_DELAY)
        return
    
    username = context.args[0].lstrip('@').lower()
    chat_id = update.effective_chat.id
    
    await send_ephemeral_reply(update, context, f"🔄 Fetching latest from @{username}...", delay=ADMIN_EPHEMERAL_DELAY)
    
    client = get_twitter_client()
    tweets = await client.get_user_tweets(username, limit=1)
    
    if not tweets:
        await send_ephemeral_reply(update, context, f"❌ Could not fetch tweets from @{username}", delay=ADMIN_EPHEMERAL_DELAY)
        return
    
    tweet = tweets[0]
    await post_tweet_to_chat(context, chat_id, tweet, username)
    
async def post_tweet_to_chat(context: ContextTypes.DEFAULT_TYPE, chat_id: int, tweet: Dict, username: str):
    """Post a tweet to a Telegram chat"""
    text = tweet.get("text", "")
    url = tweet.get("url", "")
    media = tweet.get("media", [])
    
    # Format message
    message = (
        f"📰 <b>@{username}</b>\n\n"
        f"{text}\n\n"
        f"<a href=\"{url}\">View on X/Twitter →</a>"
    )
    
    keyboard = [[InlineKeyboardButton("🔗 Open Tweet", url=url)]]
    
    try:
        if media and len(media) > 0:
            # Try to send with photo
            try:
                await context.bot.send_photo(
                    chat_id=chat_id,
                    photo=media[0],
                    caption=message,
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            except:
                # Fallback to text
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=message,
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    disable_web_page_preview=False
                )
        else:
            await context.bot.send_message(
                chat_id=chat_id,
                text=message,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard),
                disable_web_page_preview=False
            )
        return True
    except Exception as e:
        logging.error(f"Failed to post tweet to {chat_id}: {e}")
        return False

# ============ BACKGROUND JOB ============

async def check_twitter_feeds(context: ContextTypes.DEFAULT_TYPE):
    """Background job to check Twitter feeds for new posts"""
    logging.info("Checking Twitter feeds...")
    
    if ASYNC_DB:
        feeds = await get_active_twitter_feeds()
    else:
        # Backend API handles this now
        feeds = []
    
    if not feeds:
        return
    
    client = get_twitter_client()
    
    for feed in feeds:
        try:
            # Unpack feed data
            if ASYNC_DB:
                username = feed['twitter_username']
                chat_id = feed['chat_id']
                last_tweet_id = feed['last_tweet_id']
            else:
                username = feed[1]  # twitter_username
                chat_id = feed[2]   # chat_id
                last_tweet_id = feed[4]  # last_tweet_id
            
            # Fetch new tweets
            tweets = await client.get_user_tweets(username, since_id=last_tweet_id, limit=3)
            
            if not tweets:
                continue
            
            # Post new tweets (oldest first)
            for tweet in reversed(tweets):
                tweet_id = tweet['id']
                
                # Check if already posted
                if ASYNC_DB:
                    already_posted = await is_tweet_posted(tweet_id, chat_id)
                else:
                    # Backend API handles this now
                    already_posted = False
                
                if already_posted:
                    continue
                
                # Post tweet
                success = await post_tweet_to_chat(context, chat_id, tweet, username)
                
                if success:
                    # Mark as posted
                    if ASYNC_DB:
                        await mark_tweet_posted(tweet_id, chat_id, 0)
                        await update_last_tweet_id(username, chat_id, tweet_id)
                    else:
                        # Backend API handles this now
                        pass
                
                # Rate limit between posts
                await asyncio.sleep(2)
                
        except Exception as e:
            logging.error(f"Error checking feed @{username}: {e}")
            continue
    
    logging.info("Twitter feed check complete")

def setup_twitter_job(application):
    """Setup the background job for checking Twitter feeds"""
    job_queue = application.job_queue
    
    # Check every 5 minutes
    job_queue.run_repeating(
        check_twitter_feeds,
        interval=300,  # 5 minutes
        first=60  # Start after 1 minute
    )
    
    logging.info("Twitter feed job scheduled (every 5 minutes)")
