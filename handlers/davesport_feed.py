"""
Dave.sport Content Feed Integration
Fetches articles from:
- X/Twitter: @davedotsport
- Website: davedotsport.com

This is locked to official Dave.sport sources only.
"""

import os
import asyncio
import aiohttp
import logging
import re
from datetime import datetime
from typing import List, Dict, Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from handlers.roles import get_user_role, check_role, ROLE_ADMIN, is_admin_or_owner
from handlers.utils import send_ephemeral_reply, ADMIN_EPHEMERAL_DELAY
from handlers.api_client import api_bot_get, api_bot_post

# Official Dave.sport sources - LOCKED, cannot be changed by admins
DAVESPORT_TWITTER = "davedotsport"
DAVESPORT_WEBSITE = "https://www.davedotsport.com"
DAVESPORT_RSS_URLS = [
    "https://www.davedotsport.com/feed/",
    "https://www.davedotsport.com/rss/",
    "https://www.davedotsport.com/feed/rss/",
    "https://davedotsport.com/feed/",
]

# Sport categories for routing articles to correct groups
# Supported: Football, UFC, Boxing, F1, Golf, Darts
SPORT_CATEGORIES = [
    "football", "soccer", "premier league", "la liga", "champions league", "epl", "wsl", "transfer",
    "ufc", "mma",
    "boxing", "fight",
    "f1", "formula 1", "formula one", "motorsport", "racing",
    "golf", "darts",
    "general", "all"  # 'all' receives everything
]

# Twitter API (optional - works without it via Nitter)
TWITTER_BEARER_TOKEN = os.getenv("TWITTER_BEARER_TOKEN")

# Nitter instances for Twitter fallback
NITTER_INSTANCES = [
    "https://nitter.net",
    "https://nitter.privacydev.net", 
    "https://nitter.poast.org",
    "https://nitter.cz"
]

# Default headers for WordPress endpoints (avoid 403 from WP API)
WORDPRESS_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; DaveSportBot/1.0)",
    "Accept": "application/json"
}

class DaveSportFetcher:
    """Fetches content from official Dave.sport sources"""
    
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
        self.bearer_token = TWITTER_BEARER_TOKEN
    
    async def get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            timeout = aiohttp.ClientTimeout(total=15)
            self.session = aiohttp.ClientSession(timeout=timeout)
        return self.session
    
    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()
    
    # ========== TWITTER/X FETCHING ==========
    
    async def get_twitter_posts(self, since_id: str = None, limit: int = 5) -> List[Dict]:
        """Get posts from @davedotsport"""
        if self.bearer_token:
            posts = await self._fetch_twitter_api(since_id, limit)
            if posts:
                return posts
        
        # Fallback to Nitter
        return await self._fetch_twitter_nitter(limit)
    
    async def _fetch_twitter_api(self, since_id: str, limit: int) -> List[Dict]:
        """Fetch using official Twitter API v2"""
        session = await self.get_session()
        headers = {"Authorization": f"Bearer {self.bearer_token}"}
        
        try:
            # Get user ID
            user_url = f"https://api.twitter.com/2/users/by/username/{DAVESPORT_TWITTER}"
            async with session.get(user_url, headers=headers) as resp:
                if resp.status != 200:
                    logging.warning(f"Twitter API user lookup failed: {resp.status}")
                    return []
                data = await resp.json()
                user_id = data.get("data", {}).get("id")
                if not user_id:
                    return []
            
            # Get tweets
            tweets_url = f"https://api.twitter.com/2/users/{user_id}/tweets"
            params = {
                "max_results": min(limit, 100),
                "tweet.fields": "created_at,text,entities,attachments",
                "expansions": "attachments.media_keys",
                "media.fields": "url,preview_image_url,type"
            }
            if since_id:
                params["since_id"] = since_id
            
            async with session.get(tweets_url, headers=headers, params=params) as resp:
                if resp.status != 200:
                    logging.warning(f"Twitter API tweets failed: {resp.status}")
                    return []
                
                data = await resp.json()
                tweets = data.get("data", [])
                
                # Build media lookup
                media_map = {}
                for media in data.get("includes", {}).get("media", []):
                    media_map[media["media_key"]] = media.get("url") or media.get("preview_image_url")
                
                results = []
                for tweet in tweets:
                    # Skip retweets
                    if tweet["text"].startswith("RT @"):
                        continue
                    
                    post = {
                        "id": tweet["id"],
                        "text": tweet["text"],
                        "url": f"https://twitter.com/{DAVESPORT_TWITTER}/status/{tweet['id']}",
                        "created_at": tweet.get("created_at"),
                        "images": [],
                        "source": "twitter"
                    }
                    
                    # Add images
                    if "attachments" in tweet:
                        for key in tweet["attachments"].get("media_keys", []):
                            if key in media_map and media_map[key]:
                                post["images"].append(media_map[key])
                    
                    results.append(post)
                
                return results
                
        except Exception as e:
            logging.error(f"Twitter API error: {e}")
            return []
    
    async def _fetch_twitter_nitter(self, limit: int) -> List[Dict]:
        """Fetch using Nitter (no API key needed)"""
        session = await self.get_session()
        
        for instance in NITTER_INSTANCES:
            try:
                url = f"{instance}/{DAVESPORT_TWITTER}/rss"
                async with session.get(url) as resp:
                    if resp.status != 200:
                        continue
                    
                    content = await resp.text()
                    return self._parse_nitter_rss(content, limit)
                    
            except Exception as e:
                logging.debug(f"Nitter {instance} failed: {e}")
                continue
        
        logging.warning("All Nitter instances failed for @davedotsport")
        return []
    
    def _parse_nitter_rss(self, content: str, limit: int) -> List[Dict]:
        """Parse Nitter RSS feed"""
        import xml.etree.ElementTree as ET
        
        try:
            root = ET.fromstring(content)
            items = root.findall(".//item")[:limit]
            
            results = []
            for item in items:
                title = item.find("title")
                link = item.find("link")
                description = item.find("description")
                pub_date = item.find("pubDate")
                
                # Extract categories from RSS
                categories = [c.text.strip() for c in item.findall("category") if c is not None and c.text]
                
                if title is None or link is None:
                    continue
                
                text = title.text or ""
                
                # Skip retweets
                if text.startswith("RT by") or text.startswith("R to"):
                    continue
                
                # Extract tweet ID
                link_text = link.text or ""
                id_match = re.search(r'/status/(\d+)', link_text)
                tweet_id = id_match.group(1) if id_match else None
                
                if not tweet_id:
                    continue
                
                # Extract images from description
                images = []
                if description is not None and description.text:
                    img_matches = re.findall(r'src="([^"]+)"', description.text)
                    for img in img_matches:
                        if '/pic/' in img or '/media/' in img:
                            # Convert nitter URL to Twitter URL
                            images.append(img)
                
                results.append({
                    "id": tweet_id,
                    "text": text,
                    "url": f"https://twitter.com/{DAVESPORT_TWITTER}/status/{tweet_id}",
                    "created_at": pub_date.text if pub_date is not None else None,
                    "images": images,
                    "source": "twitter"
                })
            
            return results
            
        except Exception as e:
            logging.error(f"Nitter RSS parse error: {e}")
            return []
    
    # ========== WEBSITE ARTICLE FETCHING (WordPress) ==========
    
    async def get_website_articles(self, limit: int = 5) -> List[Dict]:
        """Get latest articles from davedotsport.com via WordPress API"""
        
        # Try WordPress REST API first (most reliable)
        articles = await self._fetch_wordpress_api(limit)
        if articles:
            return articles
        
        # Fallback to RSS
        session = await self.get_session()
        for rss_url in DAVESPORT_RSS_URLS:
            try:
                async with session.get(rss_url, headers=WORDPRESS_HEADERS) as resp:
                    if resp.status == 200:
                        content = await resp.text()
                        articles = self._parse_website_rss(content, limit)
                        if articles:
                            return articles
            except:
                continue
        
        # Last fallback: scrape homepage
        return await self._scrape_website(limit)
    
    async def _fetch_wordpress_api(self, limit: int) -> List[Dict]:
        """Fetch articles using WordPress REST API"""
        session = await self.get_session()
        
        # WordPress REST API endpoints to try
        api_urls = [
            f"{DAVESPORT_WEBSITE}/wp-json/wp/v2/posts",
            f"https://davedotsport.com/wp-json/wp/v2/posts",
        ]
        
        for api_url in api_urls:
            try:
                params = {
                    "per_page": limit,
                    "orderby": "date",
                    "order": "desc",
                    "_embed": "1"  # Include featured images
                }
                
                async with session.get(api_url, params=params, headers=WORDPRESS_HEADERS) as resp:
                    if resp.status != 200:
                        continue
                    
                    posts = await resp.json()
                    
                    if not isinstance(posts, list):
                        continue
                    
                    results = []
                    for post in posts:
                        # Get featured image
                        image = None
                        embedded = post.get("_embedded", {})
                        
                        # Try to get featured media
                        featured_media = embedded.get("wp:featuredmedia", [])
                        if featured_media and len(featured_media) > 0:
                            media = featured_media[0]
                            # Try different image sizes
                            if "source_url" in media:
                                image = media["source_url"]
                            elif "media_details" in media:
                                sizes = media["media_details"].get("sizes", {})
                                # Prefer medium or large
                                for size in ["medium_large", "large", "medium", "full"]:
                                    if size in sizes:
                                        image = sizes[size].get("source_url")
                                        break
                        
                        # Clean HTML from excerpt
                        excerpt = post.get("excerpt", {}).get("rendered", "")
                        excerpt = re.sub(r'<[^>]+>', '', excerpt).strip()
                        excerpt = excerpt[:200] + "..." if len(excerpt) > 200 else excerpt
                        
                        # Clean title
                        title = post.get("title", {}).get("rendered", "New Article")
                        title = re.sub(r'<[^>]+>', '', title).strip()
                        
                        # Get categories
                        categories = []
                        wp_terms = embedded.get("wp:term", [])
                        for term_group in wp_terms:
                            if isinstance(term_group, list):
                                for term in term_group:
                                    if term.get("taxonomy") == "category":
                                        categories.append(term.get("name", ""))
                        # WordPress category IDs (authoritative for routing)
                        category_ids = post.get("categories", []) or []
                        
                        results.append({
                            "id": str(post.get("id", post.get("link"))),
                            "title": title,
                            "url": post.get("link", ""),
                            "description": excerpt,
                            "created_at": post.get("date", ""),
                            "image": image,
                            "categories": categories,
                            "category_ids": category_ids,
                            "source": "website"
                        })
                    
                    if results:
                        logging.info(f"Fetched {len(results)} articles from WordPress API")
                        return results
                        
            except Exception as e:
                logging.debug(f"WordPress API {api_url} failed: {e}")
                continue
        
        return []
    
    def _parse_website_rss(self, content: str, limit: int) -> List[Dict]:
        """Parse website RSS feed"""
        import xml.etree.ElementTree as ET
        
        try:
            root = ET.fromstring(content)
            items = root.findall(".//item")[:limit]
            
            results = []
            for item in items:
                title = item.find("title")
                link = item.find("link")
                description = item.find("description")
                pub_date = item.find("pubDate")
                
                # Try to find image
                image = None
                media_content = item.find(".//{http://search.yahoo.com/mrss/}content")
                if media_content is not None:
                    image = media_content.get("url")
                
                # Check enclosure
                enclosure = item.find("enclosure")
                if enclosure is not None and not image:
                    image = enclosure.get("url")
                
                # Extract from description
                if not image and description is not None and description.text:
                    img_match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', description.text)
                    if img_match:
                        image = img_match.group(1)
                
                if title is None or link is None:
                    continue
                
                # Extract categories (names only; RSS has no IDs)
                categories = [c.text.strip() for c in item.findall("category") if c is not None and c.text]

                # Clean description
                desc_text = ""
                if description is not None and description.text:
                    # Strip HTML tags
                    desc_text = re.sub(r'<[^>]+>', '', description.text)
                    desc_text = desc_text[:200] + "..." if len(desc_text) > 200 else desc_text
                
                results.append({
                    "id": link.text,
                    "title": title.text,
                    "url": link.text,
                    "description": desc_text.strip(),
                    "created_at": pub_date.text if pub_date is not None else None,
                    "image": image,
                    "categories": categories,
                    "source": "website"
                })
            
            return results
            
        except Exception as e:
            logging.error(f"Website RSS parse error: {e}")
            return []
    
    async def _scrape_website(self, limit: int) -> List[Dict]:
        """Scrape articles from website homepage"""
        session = await self.get_session()
        
        try:
            async with session.get(DAVESPORT_WEBSITE, headers=WORDPRESS_HEADERS) as resp:
                if resp.status != 200:
                    return []
                
                html = await resp.text()
                
                # Simple extraction of article links
                # This is a basic approach - adjust based on actual site structure
                articles = []
                
                # Find article links (common patterns)
                patterns = [
                    r'<a[^>]+href=["\']([^"\']*(?:/news/|/article/|/post/)[^"\']*)["\'][^>]*>([^<]+)</a>',
                    r'<h[23][^>]*><a[^>]+href=["\']([^"\']+)["\'][^>]*>([^<]+)</a></h[23]>',
                ]
                
                for pattern in patterns:
                    matches = re.findall(pattern, html, re.IGNORECASE)
                    for url, title in matches[:limit]:
                        if url.startswith('/'):
                            url = DAVESPORT_WEBSITE + url
                        
                        if any(a["url"] == url for a in articles):
                            continue
                        
                        articles.append({
                            "id": url,
                            "title": title.strip(),
                            "url": url,
                            "description": "",
                            "image": None,
                            "source": "website"
                        })
                        
                        if len(articles) >= limit:
                            break
                    
                    if len(articles) >= limit:
                        break
                
                return articles[:limit]
                
        except Exception as e:
            logging.error(f"Website scrape error: {e}")
            return []

# Global fetcher instance
_fetcher: Optional[DaveSportFetcher] = None

def get_fetcher() -> DaveSportFetcher:
    global _fetcher
    if _fetcher is None:
        _fetcher = DaveSportFetcher()
    return _fetcher

# ========== DATABASE HELPERS ==========

# WordPress category ID to routing category mapping (STRICT)
# IDs sourced from WP categories endpoint (https://www.davedotsport.com/wp-json/wp/v2/categories)
WP_CATEGORY_ID_TO_ROUTE = {
    # Football (general / Champions League / World Cup)
    2: "football_news",
    155: "football_news",  # Champions League News
    163: "football_news",  # Champions League Match Reports
    164: "football_news",  # Champions League Match Previews
    382: "football_news",  # Champions League
    157: "football_news",  # World Cup 2026
    597: "football_news",  # Emirates FA Cup

    # Transfer / UFC (kept for future categories if added)
    12: "transfer_news",
    1010: "transfer_news",
    40: "ufc_news",
    1011: "ufc_news",

    # EPL / Premier League
    154: "epl_news",  # Premier League News
    161: "epl_news",  # Premier League Match Reports
    162: "epl_news",  # Premier League Match Previews
    384: "epl_news",  # Premier League

    # WSL / Women's football
    156: "wsl_news",  # WSL News
    165: "wsl_news",  # WSL Match Reports
    166: "wsl_news",  # WSL Match Previews
    553: "wsl_news",  # Women's football
    556: "wsl_news",  # WSL POST MATCH REACTIONS
    562: "wsl_news",  # WSL PRESS CONFERENCES
    563: "wsl_news",  # WSL INTERVIEWS

    # Live updates (route to Live Scores topic)
    186: "live_scores",  # Boxing Live Updates
    192: "live_scores",  # Darts Live Updates
    199: "live_scores",  # Golf Live Updates
    205: "live_scores",  # F1 Live Updates
    66: "live_scores",   # Live News

    # F1
    200: "f1_news",
    201: "f1_news",
    203: "f1_news",
    204: "f1_news",

    # Boxing
    182: "boxing_news",
    183: "boxing_news",
    185: "boxing_news",

    # Golf
    193: "golf_news",
    194: "golf_news",
    195: "golf_news",
    196: "golf_news",
    197: "golf_news",
    198: "golf_news",

    # Darts
    187: "darts_news",
    189: "darts_news",
    190: "darts_news",
    191: "darts_news",
}

# WordPress category name to routing category mapping (for admin input normalization)
WP_CATEGORY_TO_ROUTE = {
    "football news": "football_news",
    "transfer news": "transfer_news",
    "epl news": "epl_news",
    "wsl news": "wsl_news",
    "live scores": "live_scores",
    "live score updates": "live_scores",
    "f1 news": "f1_news",
    "boxing news": "boxing_news",
    "golf news": "golf_news",
    "darts news": "darts_news",
    "ufc news": "ufc_news",
}

CANONICAL_CATEGORIES = set(WP_CATEGORY_TO_ROUTE.values()) | set(WP_CATEGORY_ID_TO_ROUTE.values())

# Routing priority: first match wins
CATEGORY_PRIORITY = [
    "transfer_news",
    "epl_news",
    "wsl_news",
    "live_scores",
    "f1_news",
    "boxing_news",
    "golf_news",
    "darts_news",
    "ufc_news",
    "football_news",
]

def normalize_category_input(raw: str) -> Optional[str]:
    """Normalize admin input into a canonical category key."""
    if not raw:
        return None
    key = raw.strip().lower()
    key = re.sub(r'[_-]+', ' ', key)
    if key in WP_CATEGORY_TO_ROUTE:
        return WP_CATEGORY_TO_ROUTE[key]
    # Allow direct canonical keys like "football_news"
    canonical = key.replace(' ', '_')
    if canonical in CANONICAL_CATEGORIES:
        return canonical
    # Extra aliases
    if key in ["live score update", "live score", "live scores"]:
        return "live_scores"
    return None

async def subscribe_chat(chat_id: int, twitter: bool = False, website: bool = True, sport_filter: str = "all"):
    """Subscribe a chat to Dave.sport feeds via backend"""
    await api_bot_post("/admin/davesport/subscribe", {
        "chat_id": chat_id,
        "twitter": twitter,
        "website": website,
        "sport_filter": sport_filter.lower(),
    })


async def set_sport_filter(chat_id: int, sport: str):
    """Set the sport filter for a chat via backend"""
    await api_bot_post("/admin/davesport/subscribe", {
        "chat_id": chat_id,
        "twitter": False,
        "website": True,
        "sport_filter": sport.lower(),
    })


async def unsubscribe_chat(chat_id: int):
    """Unsubscribe a chat from Dave.sport feeds via backend"""
    await api_bot_post("/admin/davesport/unsubscribe", {
        "chat_id": chat_id,
        "twitter": False,
        "website": False,
        "sport_filter": "all",
    })


async def get_subscribed_chats() -> List[Dict]:
    """Get all subscribed chats via backend"""
    data = await api_bot_get("/admin/davesport/subscribers")
    return data.get("items", []) if isinstance(data, dict) else []

def article_matches_sport(article: Dict, sport_filter: str) -> bool:
    """Check if an article matches the sport filter"""
    if sport_filter in ["all", "general", None, ""]:
        return True
    
    sport_filter = sport_filter.lower()
    
    # Check categories
    categories = [c.lower() for c in article.get("categories", [])]
    
    # Check title and description too
    title = article.get("title", "").lower()
    desc = article.get("description", "").lower()
    content = f"{title} {desc} {' '.join(categories)}"
    
    # Sport keyword mappings (Supported: Football, UFC, Boxing, F1, Golf, Darts)
    sport_keywords = {
        "football": ["football", "soccer", "premier league", "la liga", "serie a", "bundesliga", "champions league", "epl", "fifa", "wsl"],
        "transfer": ["transfer", "signing", "signs", "deal", "loan", "bid", "target"],
        "epl": ["premier league", "epl", "pl"],
        "wsl": ["wsl", "women's super league", "women super league"],
        "ufc": ["ufc", "mma", "mixed martial arts", "octagon"],
        "boxing": ["boxing", "boxer", "heavyweight", "fight night", "knockout"],
        "f1": ["f1", "formula 1", "formula one", "grand prix", "motorsport", "racing"],
        "golf": ["golf", "pga", "masters"],
        "darts": ["darts", "pdc"],
    }
    
    # Get keywords for this sport
    keywords = sport_keywords.get(sport_filter, [sport_filter])
    
    # Check if any keyword matches
    for keyword in keywords:
        if keyword in content:
            return True
    
    return False

async def is_post_sent(post_id: str, chat_id: int) -> bool:
    """Check if a post was already sent to a chat via backend"""
    data = await api_bot_get("/admin/davesport/posts/sent", params={"post_id": post_id, "chat_id": chat_id})
    return bool(data.get("sent")) if isinstance(data, dict) else False


async def mark_post_sent(post_id: str, chat_id: int, source: str, message_id: int = 0):
    """Mark a post as sent via backend"""
    await api_bot_post("/admin/davesport/posts/mark", {
        "post_id": post_id,
        "chat_id": chat_id,
        "source": source,
        "message_id": message_id,
    })


async def set_chat_category(chat_id: int, category: str, thread_id: Optional[int]):
    """Set a chat to receive articles of a specific category in a specific topic via backend"""
    await api_bot_post("/admin/davesport/category", {
        "chat_id": chat_id,
        "category": category,
        "thread_id": thread_id,
    })


async def remove_chat_category(chat_id: int, category: str):
    """Remove a category from a chat's routing via backend"""
    await api_bot_post("/admin/davesport/category/remove", {
        "chat_id": chat_id,
        "category": category,
    })


async def get_chats_for_category(category: str) -> List[Dict]:
    """Get all chat IDs + thread IDs for a specific category via backend"""
    data = await api_bot_get("/admin/davesport/chats", params={"category": category})
    return data.get("items", []) if isinstance(data, dict) else []


async def get_chat_categories(chat_id: int) -> List[Dict]:
    """Get all categories configured for a chat via backend"""
    data = await api_bot_get("/admin/davesport/categories", params={"chat_id": chat_id})
    return data.get("items", []) if isinstance(data, dict) else []

def detect_article_categories(article: Dict) -> List[str]:
    """
    Detect routing categories from WordPress.

    Primary: WordPress category IDs (most reliable)
    Fallback: WordPress category names (handles sites where IDs change)

    Returns a list of routing categories (e.g., ['football_news']).
    """
    categories_found: List[str] = []

    # 1) Try category IDs
    category_ids = article.get("category_ids", []) or []
    for raw_id in category_ids:
        try:
            cat_id = int(raw_id)
        except (TypeError, ValueError):
            continue
        route = WP_CATEGORY_ID_TO_ROUTE.get(cat_id)
        if route and route not in categories_found:
            categories_found.append(route)

    # 2) Fallback to category names
    if not categories_found:
        for name in (article.get("categories") or []):
            if not name:
                continue
            key = str(name).strip().lower()
            route = WP_CATEGORY_TO_ROUTE.get(key)
            if route and route not in categories_found:
                categories_found.append(route)

    if not categories_found:
        return []

    # First match wins by priority
    for preferred in CATEGORY_PRIORITY:
        if preferred in categories_found:
            return [preferred]
    return categories_found

async def get_target_chats_for_article(article: Dict) -> List[Dict]:
    """
    Get all chat + thread IDs that should receive a specific article based on WP categories.
    """
    detected_categories = detect_article_categories(article)
    targets: List[Dict] = []
    for category in detected_categories:
        chats = await get_chats_for_category(category)
        for chat in chats:
            targets.append({"chat_id": chat["chat_id"], "thread_id": chat["thread_id"], "category": category})
    return targets

# ========== COMMAND HANDLERS ==========

async def subscribe_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Subscribe this chat to Dave.sport updates: /subscribe [sport]"""
    is_admin = await is_admin_or_owner(context.bot, update.effective_chat.id, update.effective_user.id)
    if not is_admin:
        await send_ephemeral_reply(update, context, "⛔ Admin only command.")
        return
    
    chat_id = update.effective_chat.id
    # Check if sport filter provided
    sport_filter = "all"
    if context.args:
        sport_filter = context.args[0].lower()
    
    await subscribe_chat(chat_id, sport_filter=sport_filter)
    
    sport_display = sport_filter.upper() if sport_filter != "all" else "ALL SPORTS"
    
    await send_ephemeral_reply(
        update,
        context,
        f"✅ <b>Subscribed to Dave.sport!</b>\n\n"
        f"📌 Sport Filter: <b>{sport_display}</b>\n\n"
        "This chat will now receive:\n"
        "• 📰 Articles from davedotsport.com\n\n"
        "<b>Commands:</b>\n"
        "/setsport &lt;sport&gt; - Change sport filter\n"
        "/unsubscribe - Stop receiving updates",
        parse_mode="HTML",
        delay=ADMIN_EPHEMERAL_DELAY
    )

async def setsport_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set sport filter for this chat: /setsport <sport>"""
    is_admin = await is_admin_or_owner(context.bot, update.effective_chat.id, update.effective_user.id)
    if not is_admin:
        await send_ephemeral_reply(update, context, "⛔ Admin only command.")
        return
    
    if not context.args:
        sports_list = "\n".join([
            "• <code>all</code> - All sports",
            "• <code>football</code> - Football/Soccer",
            "• <code>epl</code> - English Premier League",
            "• <code>wsl</code> - Women's Super League",
            "• <code>transfer</code> - Transfer News",
            "• <code>ufc</code> - UFC/MMA",
            "• <code>boxing</code> - Boxing",
            "• <code>f1</code> - Formula 1",
            "• <code>golf</code> - Golf",
            "• <code>darts</code> - Darts",
        ])
        await send_ephemeral_reply(
            update,
            context,
            "⚽ <b>Set Sport Filter</b>\n\n"
            f"Usage: <code>/setsport &lt;sport&gt;</code>\n\n"
            f"<b>Available sports:</b>\n{sports_list}",
            parse_mode="HTML",
            delay=ADMIN_EPHEMERAL_DELAY
        )
        return
    
    sport = context.args[0].lower()
    chat_id = update.effective_chat.id
    
    await set_sport_filter(chat_id, sport)
    
    await send_ephemeral_reply(
        update,
        context,
        f"✅ Sport filter set to: <b>{sport.upper()}</b>\n\n"
        "Only articles matching this sport will be posted.",
        parse_mode="HTML",
        delay=ADMIN_EPHEMERAL_DELAY
    )

async def setchatchannel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Set this chat to receive specific category of news.
    Usage: /setchatchannel <category>
    
    Categories:
    - football_news: Football News
    - transfer_news: Transfer news
    - epl_news: English Premier League
    - wsl_news: Women's Super League
    - live_scores: Live score updates
    - f1_news: Formula 1
    - boxing_news: Boxing
    - golf_news: Golf
    - darts_news: Darts
    - ufc_news: UFC/MMA
    Note: This must be run inside the target topic so the bot can store the topic thread ID.
    """
    is_admin = await is_admin_or_owner(context.bot, update.effective_chat.id, update.effective_user.id)
    if not is_admin:
        await send_ephemeral_reply(update, context, "⛔ Admin only command.")
        return
    
    chat_id = update.effective_chat.id
    thread_id = update.message.message_thread_id if update.message else None
    
    if not context.args:
        # Show current categories and available options
        current_categories = await get_chat_categories(chat_id)
        display_entries = [
            f"{c['category']} (thread {c['thread_id']})"
            for c in current_categories
            if c.get("thread_id") is not None
        ]
        current_display = ", ".join(display_entries) if display_entries else "None"
        
        categories_list = "\n".join([
            "• <code>football_news</code> - Football News",
            "• <code>transfer_news</code> - Transfer News",
            "• <code>epl_news</code> - Premier League",
            "• <code>wsl_news</code> - Women's Super League",
            "• <code>live_scores</code> - Live Score Updates",
            "• <code>f1_news</code> - Formula 1",
            "• <code>boxing_news</code> - Boxing",
            "• <code>golf_news</code> - Golf",
            "• <code>darts_news</code> - Darts",
            "• <code>ufc_news</code> - UFC/MMA",
        ])
        
        await send_ephemeral_reply(
            update,
            context,
            "📢 <b>Set Chat Channel Category</b>\n\n"
            f"<b>Current categories:</b> {current_display}\n\n"
            "<b>Usage:</b>\n"
            "<code>/setchatchannel &lt;category&gt;</code> - Add category\n"
            "<code>/removechatchannel &lt;category&gt;</code> - Remove category\n\n"
            f"<b>Available categories:</b>\n{categories_list}\n\n"
            "<i>Articles are automatically routed to chats based on their content category.</i>",
            parse_mode="HTML",
            delay=ADMIN_EPHEMERAL_DELAY
        )
        return
    
    if thread_id is None:
        await send_ephemeral_reply(
            update,
            context,
            "❌ This command must be run inside the target topic.\n"
            "Open the topic (e.g., Football News) and run /setchatchannel there.",
            parse_mode="HTML",
            delay=ADMIN_EPHEMERAL_DELAY
        )
        return

    category = normalize_category_input(context.args[0])
    
    if category is None:
        await send_ephemeral_reply(
            update,
            context,
            f"❌ Invalid category.\n\n"
            "Use <code>/setchatchannel</code> to see valid categories.",
            parse_mode="HTML",
            delay=ADMIN_EPHEMERAL_DELAY
        )
        return
    
    await set_chat_category(chat_id, category, thread_id)
    
    await send_ephemeral_reply(
        update,
        context,
        f"✅ <b>Category added!</b>\n\n"
        f"This chat will now receive: <b>{category.replace('_', ' ').title()}</b>\n\n"
        "Articles matching this category will be automatically posted here.",
        parse_mode="HTML",
        delay=ADMIN_EPHEMERAL_DELAY
    )

async def removechatchannel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Remove a category from this chat's routing."""
    is_admin = await is_admin_or_owner(context.bot, update.effective_chat.id, update.effective_user.id)
    if not is_admin:
        await send_ephemeral_reply(update, context, "⛔ Admin only command.")
        return
    
    chat_id = update.effective_chat.id
    
    if not context.args:
        await send_ephemeral_reply(
            update,
            context,
            "<b>Usage:</b> <code>/removechatchannel &lt;category&gt;</code>",
            parse_mode="HTML",
            delay=ADMIN_EPHEMERAL_DELAY
        )
        return
    
    category = normalize_category_input(context.args[0])
    if category is None:
        await send_ephemeral_reply(
            update,
            context,
            "❌ Invalid category.\n\nUse <code>/setchatchannel</code> to see valid categories.",
            parse_mode="HTML",
            delay=ADMIN_EPHEMERAL_DELAY
        )
        return
    await remove_chat_category(chat_id, category)
    
    await send_ephemeral_reply(
        update,
        context,
        f"✅ Removed category: <b>{category}</b>\n\n"
        "This chat will no longer receive articles of this type.",
        parse_mode="HTML",
        delay=ADMIN_EPHEMERAL_DELAY
    )

async def unsubscribe_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Unsubscribe from Dave.sport updates: /unsubscribe"""
    is_admin = await is_admin_or_owner(context.bot, update.effective_chat.id, update.effective_user.id)
    if not is_admin:
        await send_ephemeral_reply(update, context, "⛔ Admin only command.")
        return
    
    chat_id = update.effective_chat.id
    await unsubscribe_chat(chat_id)
    
    await send_ephemeral_reply(update, context, "✅ Unsubscribed from Dave.sport updates.", delay=ADMIN_EPHEMERAL_DELAY)

async def fetch_latest_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show news delivery info: /fetchlatest"""
    is_admin = await is_admin_or_owner(context.bot, update.effective_chat.id, update.effective_user.id)
    if not is_admin:
        await send_ephemeral_reply(update, context, "⛔ Admin only command.")
        return
    await send_ephemeral_reply(
        update,
        context,
        "📰 <b>News Delivery</b>\n\n"
        "Articles are delivered only to Telegram topics based on WordPress categories.\n"
        "Open a topic and run <code>/setchatchannel &lt;category&gt;</code> to configure routing.",
        parse_mode="HTML",
        delay=ADMIN_EPHEMERAL_DELAY
    )

async def feed_status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check feed subscription status: /feedstatus"""
    chat_id = update.effective_chat.id
    
    try:
        data = await api_bot_get(f"/admin/groups/{chat_id}/feed-status")
    except Exception:
        data = {}
    if data.get("subscribed"):
        twitter_status = "❌ Disabled (WP only)"
        website_status = "✅ Enabled" if data.get("website_enabled") else "❌ Disabled"
        sport_filter = data.get("sport_filter") or "all"
        sport_display = sport_filter.upper() if sport_filter != "all" else "ALL SPORTS"
        await send_ephemeral_reply(
            update,
            context,
            "📡 <b>Dave.sport Feed Status</b>\\n\\n"
            f"📱 X/Twitter: {twitter_status}\\n"
            f"📰 Website: {website_status}\\n"
            f"⚽ Sport Filter: <b>{sport_display}</b>\\n\\n"
            "<i>New content is checked every 5 minutes</i>\\n\\n"
            "Use /setsport &lt;sport&gt; to change filter",
            parse_mode="HTML"
        )
    else:
        await send_ephemeral_reply(
            update,
            context,
            "📡 <b>Not Subscribed</b>\\n\\n"
            "This chat is not subscribed to Dave.sport feeds.\\n"
            "Use /subscribe to enable.",
            parse_mode="HTML"
        )

# ========== CONTENT POSTING ==========

async def post_content_to_chat(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    content: Dict,
    thread_id: Optional[int] = None,
    allow_general: bool = False,
) -> bool:
    """Post content (tweet or article) to a chat"""
    try:
        source = content.get("source", "unknown")
        
        # Twitter feed disabled entirely
        if source == "twitter":
            logging.info(f"Skipping twitter post to chat {chat_id} (Twitter disabled).")
            return False
        
        # By default we don't post feeds to the group's main chat (noise). However, if a chat is
        # subscribed but hasn't configured topics yet, allow_general enables a fallback delivery.
        if thread_id is None and source in ["website", "twitter"] and not allow_general:
            logging.info(f"Skipping {source} post to general chat {chat_id} (feeds blocked).")
            return False
        
        if source == "twitter":
            # Twitter post
            text = content.get("text", "")
            url = content.get("url", "")
            images = content.get("images", [])
            
            message = (
                f"📱 <b>@davedotsport</b>\n\n"
                f"{text}\n\n"
                f"<a href=\"{url}\">View on X →</a>"
            )
            
            keyboard = [[InlineKeyboardButton("🔗 Open on X", url=url)]]
            
        else:
            # Website article
            title = content.get("title", "New Article")
            url = content.get("url", "")
            description = content.get("description", "")
            images = [content.get("image")] if content.get("image") else []
            
            message = (
                f"📰 <b>{title}</b>\n\n"
                f"{description}\n\n"
                f"<a href=\"{url}\">Read more on Dave.sport →</a>"
            )
            
            keyboard = [[InlineKeyboardButton("📖 Read Article", url=url)]]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Try to send with image
        if images and images[0]:
            try:
                msg = await context.bot.send_photo(
                    chat_id=chat_id,
                    photo=images[0],
                    caption=message,
                    parse_mode="HTML",
                    reply_markup=reply_markup,
                    message_thread_id=thread_id
                )
                return True
            except Exception as e:
                logging.debug(f"Photo send failed: {e}")
        
        # Send as text
        await context.bot.send_message(
            chat_id=chat_id,
            text=message,
            parse_mode="HTML",
            reply_markup=reply_markup,
            disable_web_page_preview=False,
            message_thread_id=thread_id
        )
        return True
        
    except Exception as e:
        logging.error(f"Failed to post to {chat_id}: {e}")
        return False

# ========== BACKGROUND JOB ==========

async def check_davesport_feeds(context: ContextTypes.DEFAULT_TYPE):
    """
    Background job to check for new Dave.sport content.
    
    Uses two routing methods:
    1. Category-based routing: Articles are routed to specific chats based on content categories
    2. Sport filter routing: Legacy method using sport_filter on subscribers
    
    Category-based routing takes priority for articles.
    """
    logging.info("Checking Dave.sport feeds...")
    
    fetcher = get_fetcher()
    
    # Fetch new content (WordPress only)
    website_articles = await fetcher.get_website_articles(limit=3)
    
    # Track which articles have been processed
    processed_articles = set()
    
    # === CATEGORY-BASED ROUTING FOR WEBSITE ARTICLES ===
    # This is the primary routing method - articles go to chats based on content category
    if website_articles:
        for article in reversed(website_articles):  # Oldest first
            post_id_base = f"website_{article['id']}"
            
            # Get target chats based on article categories
            target_chats = await get_target_chats_for_article(article)
            
            if target_chats:
                processed_articles.add(post_id_base)
                
                for target in target_chats:
                    chat_id = target["chat_id"]
                    thread_id = target["thread_id"]
                    post_id = f"{post_id_base}_t{thread_id}"
                    if not await is_post_sent(post_id, chat_id):
                        success = await post_content_to_chat(context, chat_id, article, thread_id=thread_id)
                        if success:
                            await mark_post_sent(post_id, chat_id, "website")
                        await asyncio.sleep(1)  # Rate limit
    
    # === LEGACY SPORT FILTER ROUTING (FALLBACK) ===
    # If a chat subscribed but did NOT configure category routing (topics), deliver into the main chat.
    subscribers = await get_subscribed_chats()
    if not subscribers:
        logging.info("Dave.sport feed check complete (no subscribers)")
        return

    for sub in subscribers:
        try:
            chat_id = int(sub.get("chat_id"))
        except Exception:
            continue
        sport_filter = (sub.get("sport_filter") or "all").lower()

        # If this chat has at least one category routing entry, skip fallback to avoid duplicates.
        try:
            configured = await get_chat_categories(chat_id)
        except Exception:
            configured = []
        if configured:
            continue

        for article in reversed(website_articles or []):
            if not article_matches_sport(article, sport_filter):
                continue

            post_id_base = f"website_{article['id']}"
            post_id = f"{post_id_base}_t0"
            if await is_post_sent(post_id, chat_id):
                continue

            success = await post_content_to_chat(context, chat_id, article, thread_id=None, allow_general=True)
            if success:
                await mark_post_sent(post_id, chat_id, "website")
            await asyncio.sleep(1)

    logging.info("Dave.sport feed check complete")

def setup_davesport_job(application):
    """Setup the background job for checking Dave.sport feeds"""
    job_queue = application.job_queue
    
    # Check every 5 minutes
    job_queue.run_repeating(
        check_davesport_feeds,
        interval=300,  # 5 minutes
        first=30  # Start after 30 seconds
    )
    
    logging.info("Dave.sport feed job scheduled (every 5 minutes)")
