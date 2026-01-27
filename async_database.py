"""
Async Database Module using aiosqlite
- Connection pooling for better performance
- Indexes on frequently queried columns
- Non-blocking database operations
"""

import aiosqlite
import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Optional, List, Tuple, Any

DB_NAME = "dave_sports.db"

# Connection pool
class ConnectionPool:
    def __init__(self, db_name: str, pool_size: int = 5):
        self.db_name = db_name
        self.pool_size = pool_size
        self._pool: asyncio.Queue = asyncio.Queue(maxsize=pool_size)
        self._initialized = False
    
    async def initialize(self):
        """Initialize the connection pool"""
        if self._initialized:
            return
        
        for _ in range(self.pool_size):
            conn = await aiosqlite.connect(self.db_name)
            conn.row_factory = aiosqlite.Row
            await self._pool.put(conn)
        
        self._initialized = True
        logging.info(f"Database pool initialized with {self.pool_size} connections")
    
    @asynccontextmanager
    async def acquire(self):
        """Acquire a connection from the pool"""
        if not self._initialized:
            await self.initialize()
        
        conn = await self._pool.get()
        try:
            yield conn
        finally:
            await self._pool.put(conn)
    
    async def close_all(self):
        """Close all connections in the pool"""
        while not self._pool.empty():
            conn = await self._pool.get()
            await conn.close()
        self._initialized = False

# Global connection pool
_pool: Optional[ConnectionPool] = None

async def get_pool() -> ConnectionPool:
    """Get or create the connection pool"""
    global _pool
    if _pool is None:
        _pool = ConnectionPool(DB_NAME)
        await _pool.initialize()
    return _pool

async def init_db():
    """Initialize the database schema with indexes"""
    async with aiosqlite.connect(DB_NAME) as conn:
        cursor = await conn.cursor()
        
        # Users table
        await cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            join_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            role TEXT DEFAULT 'MEMBER',
            warning_count INTEGER DEFAULT 0,
            coin_balance INTEGER DEFAULT 0,
            last_daily_claim TIMESTAMP,
            club TEXT DEFAULT NULL,
            interests TEXT DEFAULT NULL,
            invited_by INTEGER DEFAULT NULL
        )
        ''')
        
        # Matches table with sport_type
        await cursor.execute('''
        CREATE TABLE IF NOT EXISTS matches (
            match_id INTEGER PRIMARY KEY AUTOINCREMENT,
            team_a TEXT,
            team_b TEXT,
            score_a INTEGER DEFAULT NULL,
            score_b INTEGER DEFAULT NULL,
            status TEXT DEFAULT 'OPEN',
            result TEXT DEFAULT NULL,
            match_time TIMESTAMP DEFAULT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            sport_type TEXT DEFAULT 'football',
            chat_id INTEGER DEFAULT NULL
        )
        ''')
        
        # Predictions table
        await cursor.execute('''
        CREATE TABLE IF NOT EXISTS predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            match_id INTEGER,
            prediction TEXT,
            pred_score_a INTEGER DEFAULT NULL,
            pred_score_b INTEGER DEFAULT NULL,
            status TEXT DEFAULT 'PENDING',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(match_id) REFERENCES matches(match_id)
        )
        ''')
        
        # Link tracking
        await cursor.execute('''
        CREATE TABLE IF NOT EXISTS posted_links (
            link_id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT,
            chat_id INTEGER,
            message_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        
        await cursor.execute('''
        CREATE TABLE IF NOT EXISTS link_clicks (
            user_id INTEGER,
            link_id INTEGER,
            clicked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, link_id),
            FOREIGN KEY(link_id) REFERENCES posted_links(link_id)
        )
        ''')
        
        # Reaction tracking
        await cursor.execute('''
        CREATE TABLE IF NOT EXISTS reaction_rewards (
            user_id INTEGER,
            message_id INTEGER,
            chat_id INTEGER,
            PRIMARY KEY (user_id, message_id)
        )
        ''')
        
        # Groups
        await cursor.execute('''
        CREATE TABLE IF NOT EXISTS groups (
            chat_id INTEGER PRIMARY KEY,
            chat_title TEXT,
            chat_type TEXT,
            sport_focus TEXT DEFAULT NULL,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        
        # User preferences
        await cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_preferences (
            user_id INTEGER PRIMARY KEY,
            match_reminders INTEGER DEFAULT 1,
            result_notifications INTEGER DEFAULT 1,
            daily_reminder INTEGER DEFAULT 0,
            prediction_updates INTEGER DEFAULT 1,
            favorite_sports TEXT DEFAULT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')

        # Moderation audit log
        await cursor.execute('''
        CREATE TABLE IF NOT EXISTS moderation_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            actor_id INTEGER NOT NULL,
            target_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            reason TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        
        # Twitter feed tracking
        await cursor.execute('''
        CREATE TABLE IF NOT EXISTS twitter_feeds (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            twitter_username TEXT NOT NULL,
            chat_id INTEGER NOT NULL,
            sport_type TEXT DEFAULT 'general',
            last_tweet_id TEXT DEFAULT NULL,
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(twitter_username, chat_id)
        )
        ''')
        
        await cursor.execute('''
        CREATE TABLE IF NOT EXISTS posted_tweets (
            tweet_id TEXT PRIMARY KEY,
            chat_id INTEGER,
            message_id INTEGER,
            posted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        
        # === CREATE INDEXES ===
        
        # User indexes
        await cursor.execute('CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)')
        await cursor.execute('CREATE INDEX IF NOT EXISTS idx_users_role ON users(role)')
        await cursor.execute('CREATE INDEX IF NOT EXISTS idx_users_balance ON users(coin_balance DESC)')
        
        # Match indexes
        await cursor.execute('CREATE INDEX IF NOT EXISTS idx_matches_status ON matches(status)')
        await cursor.execute('CREATE INDEX IF NOT EXISTS idx_matches_sport ON matches(sport_type)')
        await cursor.execute('CREATE INDEX IF NOT EXISTS idx_matches_chat ON matches(chat_id)')
        await cursor.execute('CREATE INDEX IF NOT EXISTS idx_matches_time ON matches(match_time)')
        
        # Prediction indexes
        await cursor.execute('CREATE INDEX IF NOT EXISTS idx_predictions_user ON predictions(user_id)')
        await cursor.execute('CREATE INDEX IF NOT EXISTS idx_predictions_match ON predictions(match_id)')
        await cursor.execute('CREATE INDEX IF NOT EXISTS idx_predictions_status ON predictions(status)')
        
        # Groups index
        await cursor.execute('CREATE INDEX IF NOT EXISTS idx_groups_sport ON groups(sport_focus)')
        
        # Twitter feeds index
        await cursor.execute('CREATE INDEX IF NOT EXISTS idx_twitter_username ON twitter_feeds(twitter_username)')
        await cursor.execute('CREATE INDEX IF NOT EXISTS idx_twitter_active ON twitter_feeds(is_active)')
        
        # Migration: Add new columns if they don't exist
        try:
            await cursor.execute('ALTER TABLE matches ADD COLUMN sport_type TEXT DEFAULT "football"')
        except:
            pass
        
        try:
            await cursor.execute('ALTER TABLE matches ADD COLUMN chat_id INTEGER DEFAULT NULL')
        except:
            pass
        
        try:
            await cursor.execute('ALTER TABLE groups ADD COLUMN sport_focus TEXT DEFAULT NULL')
        except:
            pass
        
        await conn.commit()
        logging.info("Async database initialized with indexes")

# ============ USER FUNCTIONS ============

async def add_user(user_id: int, username: str, invited_by: int = None):
    """Add or update a user"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            'INSERT OR IGNORE INTO users (user_id, username, invited_by) VALUES (?, ?, ?)',
            (user_id, username, invited_by)
        )
        await conn.execute(
            'UPDATE users SET username = ? WHERE user_id = ?',
            (username, user_id)
        )
        if invited_by:
            await conn.execute(
                'UPDATE users SET invited_by = ? WHERE user_id = ? AND invited_by IS NULL',
                (invited_by, user_id)
            )
        await conn.commit()

async def get_user(user_id: int) -> Optional[aiosqlite.Row]:
    """Get a user by ID"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        cursor = await conn.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
        return await cursor.fetchone()

async def get_user_by_username(username: str) -> Optional[aiosqlite.Row]:
    """Get a user by username"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        clean_username = username.lstrip('@')
        cursor = await conn.execute(
            'SELECT * FROM users WHERE username = ? COLLATE NOCASE',
            (clean_username,)
        )
        return await cursor.fetchone()

async def update_user_profile(user_id: int, club: str = None, interests: str = None):
    """Update user profile"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        if club is not None:
            await conn.execute('UPDATE users SET club = ? WHERE user_id = ?', (club, user_id))
        if interests is not None:
            await conn.execute('UPDATE users SET interests = ? WHERE user_id = ?', (interests, user_id))
        await conn.commit()

async def update_user_role(user_id: int, role: str):
    """Update user role"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute('UPDATE users SET role = ? WHERE user_id = ?', (role, user_id))
        await conn.commit()

async def add_warning(user_id: int) -> int:
    """Add a warning and return new count"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            'UPDATE users SET warning_count = warning_count + 1 WHERE user_id = ?',
            (user_id,)
        )
        await conn.commit()
        cursor = await conn.execute(
            'SELECT warning_count FROM users WHERE user_id = ?',
            (user_id,)
        )
        row = await cursor.fetchone()
        return row[0] if row else 0

async def reset_warnings(user_id: int):
    """Reset user warnings"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute('UPDATE users SET warning_count = 0 WHERE user_id = ?', (user_id,))
        await conn.commit()

async def update_balance(user_id: int, amount: int) -> bool:
    """Update user coin balance"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            await conn.execute(
                'UPDATE users SET coin_balance = coin_balance + ? WHERE user_id = ?',
                (amount, user_id)
            )
            await conn.commit()
            return True
        except Exception as e:
            logging.error(f"Balance update error: {e}")
            return False

async def get_top_users(limit: int = 10) -> List[Tuple]:
    """Get top users by coin balance"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        cursor = await conn.execute(
            'SELECT username, coin_balance FROM users ORDER BY coin_balance DESC LIMIT ?',
            (limit,)
        )
        return await cursor.fetchall()

async def set_daily_claim(user_id: int):
    """Set daily claim timestamp"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            'UPDATE users SET last_daily_claim = CURRENT_TIMESTAMP WHERE user_id = ?',
            (user_id,)
        )
        await conn.commit()

# ============ GROUP FUNCTIONS ============

async def add_group(chat_id: int, title: str, chat_type: str, sport_focus: str = None):
    """Add or update a group"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            'INSERT OR REPLACE INTO groups (chat_id, chat_title, chat_type, sport_focus) VALUES (?, ?, ?, ?)',
            (chat_id, title, chat_type, sport_focus)
        )
        await conn.commit()

async def remove_group(chat_id: int):
    """Remove a group"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute('DELETE FROM groups WHERE chat_id = ?', (chat_id,))
        await conn.commit()

async def get_all_groups() -> List[int]:
    """Get all group IDs"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        cursor = await conn.execute('SELECT chat_id FROM groups')
        rows = await cursor.fetchall()
        return [row[0] for row in rows]

async def get_groups_by_sport(sport_type: str) -> List[int]:
    """Get groups focused on a specific sport"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        cursor = await conn.execute(
            'SELECT chat_id FROM groups WHERE sport_focus = ? OR sport_focus IS NULL',
            (sport_type,)
        )
        rows = await cursor.fetchall()
        return [row[0] for row in rows]

async def set_group_sport_focus(chat_id: int, sport_type: str):
    """Set the sport focus for a group"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            'UPDATE groups SET sport_focus = ? WHERE chat_id = ?',
            (sport_type, chat_id)
        )
        await conn.commit()

# ============ MATCH FUNCTIONS ============

async def create_match(team_a: str, team_b: str, match_time: str = None, 
                       sport_type: str = 'football', chat_id: int = None) -> int:
    """Create a new match"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        cursor = await conn.execute(
            'INSERT INTO matches (team_a, team_b, match_time, sport_type, chat_id) VALUES (?, ?, ?, ?, ?)',
            (team_a, team_b, match_time, sport_type, chat_id)
        )
        await conn.commit()
        return cursor.lastrowid

async def get_match(match_id: int) -> Optional[aiosqlite.Row]:
    """Get a match by ID"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        cursor = await conn.execute('SELECT * FROM matches WHERE match_id = ?', (match_id,))
        return await cursor.fetchone()

async def get_open_matches(sport_type: str = None, chat_id: int = None) -> List[aiosqlite.Row]:
    """Get open matches, optionally filtered by sport or chat"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        query = 'SELECT * FROM matches WHERE status = "OPEN"'
        params = []
        
        if sport_type:
            query += ' AND sport_type = ?'
            params.append(sport_type)
        
        if chat_id:
            query += ' AND (chat_id = ? OR chat_id IS NULL)'
            params.append(chat_id)
        
        query += ' ORDER BY match_time ASC'
        
        cursor = await conn.execute(query, params)
        return await cursor.fetchall()

async def close_match_bets(match_id: int):
    """Close betting on a match"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            'UPDATE matches SET status = "CLOSED" WHERE match_id = ? AND status = "OPEN"',
            (match_id,)
        )
        await conn.commit()

async def resolve_match(match_id: int, winner_code: str, score_a: int = None, score_b: int = None) -> List[int]:
    """Resolve a match and return winner user IDs"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        # Update match
        await conn.execute(
            'UPDATE matches SET status = "RESOLVED", result = ?, score_a = ?, score_b = ? WHERE match_id = ?',
            (winner_code, score_a, score_b, match_id)
        )
        
        # Get predictions
        cursor = await conn.execute(
            'SELECT user_id, prediction, pred_score_a, pred_score_b FROM predictions WHERE match_id = ?',
            (match_id,)
        )
        predictions = await cursor.fetchall()
        
        winners = []
        for pred in predictions:
            uid, p_choice, p_sa, p_sb = pred[0], pred[1], pred[2], pred[3]
            won = False
            
            if p_choice == winner_code:
                won = True
            elif p_choice == "SCORE" and score_a is not None and score_b is not None:
                if p_sa == score_a and p_sb == score_b:
                    won = True
            
            status = "WON" if won else "LOST"
            await conn.execute(
                'UPDATE predictions SET status = ? WHERE user_id = ? AND match_id = ?',
                (status, uid, match_id)
            )
            
            if won:
                winners.append(uid)
        
        await conn.commit()
        return winners

async def delete_match(match_id: int):
    """Delete a match and its predictions"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute('DELETE FROM predictions WHERE match_id = ?', (match_id,))
        await conn.execute('DELETE FROM matches WHERE match_id = ?', (match_id,))
        await conn.commit()

# ============ PREDICTION FUNCTIONS ============

async def add_prediction(user_id: int, match_id: int, prediction: str, 
                         score_a: int = None, score_b: int = None) -> bool:
    """Add a prediction, returns False if already exists"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        cursor = await conn.execute(
            'SELECT 1 FROM predictions WHERE user_id = ? AND match_id = ?',
            (user_id, match_id)
        )
        if await cursor.fetchone():
            return False
        
        await conn.execute(
            'INSERT INTO predictions (user_id, match_id, prediction, pred_score_a, pred_score_b) VALUES (?, ?, ?, ?, ?)',
            (user_id, match_id, prediction, score_a, score_b)
        )
        await conn.commit()
        return True

async def get_user_predictions(user_id: int, limit: int = 10) -> List[aiosqlite.Row]:
    """Get user's prediction history"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        cursor = await conn.execute('''
            SELECT p.match_id, p.prediction, p.pred_score_a, p.pred_score_b, p.status,
                   m.team_a, m.team_b, m.score_a, m.score_b, m.status as match_status, m.sport_type
            FROM predictions p
            JOIN matches m ON p.match_id = m.match_id
            WHERE p.user_id = ?
            ORDER BY p.match_id DESC
            LIMIT ?
        ''', (user_id, limit))
        return await cursor.fetchall()

async def get_user_prediction_stats(user_id: int) -> Tuple[int, int]:
    """Get user's total predictions and wins"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        cursor = await conn.execute('''
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN status = 'WON' THEN 1 ELSE 0 END) as wins
            FROM predictions WHERE user_id = ?
        ''', (user_id,))
        row = await cursor.fetchone()
        return (row[0] or 0, row[1] or 0)

async def get_prediction_leaderboard(limit: int = 10) -> List[Tuple]:
    """Get prediction leaderboard"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        cursor = await conn.execute('''
            SELECT u.username, 
                   COUNT(*) as total,
                   SUM(CASE WHEN p.status = 'WON' THEN 1 ELSE 0 END) as wins
            FROM predictions p
            JOIN users u ON p.user_id = u.user_id
            GROUP BY p.user_id
            HAVING total >= 3
            ORDER BY wins DESC, total ASC
            LIMIT ?
        ''', (limit,))
        return await cursor.fetchall()

# ============ TWITTER FEED FUNCTIONS ============

async def add_twitter_feed(twitter_username: str, chat_id: int, sport_type: str = 'general') -> bool:
    """Add a Twitter feed to track"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            await conn.execute(
                'INSERT OR REPLACE INTO twitter_feeds (twitter_username, chat_id, sport_type) VALUES (?, ?, ?)',
                (twitter_username.lower(), chat_id, sport_type)
            )
            await conn.commit()
            return True
        except:
            return False

async def remove_twitter_feed(twitter_username: str, chat_id: int):
    """Remove a Twitter feed"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            'DELETE FROM twitter_feeds WHERE twitter_username = ? AND chat_id = ?',
            (twitter_username.lower(), chat_id)
        )
        await conn.commit()

async def get_active_twitter_feeds() -> List[aiosqlite.Row]:
    """Get all active Twitter feeds"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        cursor = await conn.execute(
            'SELECT * FROM twitter_feeds WHERE is_active = 1'
        )
        return await cursor.fetchall()

async def update_last_tweet_id(twitter_username: str, chat_id: int, tweet_id: str):
    """Update the last processed tweet ID"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            'UPDATE twitter_feeds SET last_tweet_id = ? WHERE twitter_username = ? AND chat_id = ?',
            (tweet_id, twitter_username.lower(), chat_id)
        )
        await conn.commit()

async def is_tweet_posted(tweet_id: str, chat_id: int) -> bool:
    """Check if a tweet was already posted"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        cursor = await conn.execute(
            'SELECT 1 FROM posted_tweets WHERE tweet_id = ? AND chat_id = ?',
            (tweet_id, chat_id)
        )
        return await cursor.fetchone() is not None

async def mark_tweet_posted(tweet_id: str, chat_id: int, message_id: int):
    """Mark a tweet as posted"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            'INSERT OR IGNORE INTO posted_tweets (tweet_id, chat_id, message_id) VALUES (?, ?, ?)',
            (tweet_id, chat_id, message_id)
        )
        await conn.commit()

# ============ USER PREFERENCES ============

async def get_user_preferences(user_id: int) -> Optional[aiosqlite.Row]:
    """Get user preferences"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        cursor = await conn.execute(
            'SELECT * FROM user_preferences WHERE user_id = ?',
            (user_id,)
        )
        prefs = await cursor.fetchone()
        
        if not prefs:
            await conn.execute('INSERT INTO user_preferences (user_id) VALUES (?)', (user_id,))
            await conn.commit()
            cursor = await conn.execute(
                'SELECT * FROM user_preferences WHERE user_id = ?',
                (user_id,)
            )
            prefs = await cursor.fetchone()
        
        return prefs

async def update_user_preference(user_id: int, pref_name: str, value: int):
    """Update a user preference"""
    valid_prefs = ['match_reminders', 'result_notifications', 'daily_reminder', 
                   'prediction_updates', 'favorite_sports']
    if pref_name not in valid_prefs:
        return
    
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute('INSERT OR IGNORE INTO user_preferences (user_id) VALUES (?)', (user_id,))
        await conn.execute(
            f'UPDATE user_preferences SET {pref_name} = ?, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?',
            (value, user_id)
        )
        await conn.commit()

async def get_users_for_notification(pref_name: str = 'match_reminders') -> List[int]:
    """Get users with a notification preference enabled"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        cursor = await conn.execute(f'''
            SELECT u.user_id FROM users u
            LEFT JOIN user_preferences p ON u.user_id = p.user_id
            WHERE p.{pref_name} = 1 OR p.user_id IS NULL
        ''')
        rows = await cursor.fetchall()
        return [row[0] for row in rows]

# ============ LINK/REACTION TRACKING ============

async def create_tracked_link(url: str, chat_id: int, message_id: int) -> int:
    """Create a tracked link"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        cursor = await conn.execute(
            'INSERT INTO posted_links (url, chat_id, message_id) VALUES (?, ?, ?)',
            (url, chat_id, message_id)
        )
        await conn.commit()
        return cursor.lastrowid

async def get_tracked_link(link_id: int) -> Optional[str]:
    """Get tracked link URL"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        cursor = await conn.execute(
            'SELECT url FROM posted_links WHERE link_id = ?',
            (link_id,)
        )
        row = await cursor.fetchone()
        return row[0] if row else None

async def record_link_click(user_id: int, link_id: int) -> bool:
    """Record a link click, returns False if already clicked"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            await conn.execute(
                'INSERT INTO link_clicks (user_id, link_id) VALUES (?, ?)',
                (user_id, link_id)
            )
            await conn.commit()
            return True
        except:
            return False

async def has_user_reacted(user_id: int, message_id: int) -> bool:
    """Check if user already reacted to a message"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        cursor = await conn.execute(
            'SELECT 1 FROM reaction_rewards WHERE user_id = ? AND message_id = ?',
            (user_id, message_id)
        )
        return await cursor.fetchone() is not None

async def record_reaction_reward(user_id: int, message_id: int, chat_id: int):
    """Record a reaction reward"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            await conn.execute(
                'INSERT OR IGNORE INTO reaction_rewards (user_id, message_id, chat_id) VALUES (?, ?, ?)',
                (user_id, message_id, chat_id)
            )
            await conn.commit()
        except:
            pass

# Sport type constants
SPORT_TYPES = {
    'football': '⚽ Football',
    'boxing': '🥊 Boxing',
    'ufc': '🥋 UFC/MMA',
    'f1': '🏎️ Formula 1',
    'golf': '⛳ Golf',
    'darts': '🎯 Darts',
    'tennis': '🎾 Tennis',
    'basketball': '🏀 Basketball',
    'general': '🏟️ General'
}

def get_sport_emoji(sport_type: str) -> str:
    """Get emoji for a sport type"""
    mapping = {
        'football': '⚽',
        'boxing': '🥊',
        'ufc': '🥋',
        'f1': '🏎️',
        'golf': '⛳',
        'darts': '🎯',
        'tennis': '🎾',
        'basketball': '🏀',
        'general': '🏟️'
    }
    return mapping.get(sport_type, '🏟️')
