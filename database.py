import os
import sqlite3
import logging

# Database Setup
DB_NAME = "dave_sports.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Users table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        join_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        role TEXT DEFAULT 'MEMBER',
        warning_count INTEGER DEFAULT 0,
        coin_balance INTEGER DEFAULT 0,
        last_daily_claim TIMESTAMP,
        club TEXT DEFAULT NULL,
        interests TEXT DEFAULT NULL
    )
    ''')
    
    # Check for new columns (for migration)
    cursor.execute("PRAGMA table_info(users)")
    columns = [column[1] for column in cursor.fetchall()]
    
    if 'last_daily_claim' not in columns:
        cursor.execute('ALTER TABLE users ADD COLUMN last_daily_claim TIMESTAMP')
    if 'club' not in columns:
        cursor.execute('ALTER TABLE users ADD COLUMN club TEXT DEFAULT NULL')
    if 'interests' not in columns:
        cursor.execute('ALTER TABLE users ADD COLUMN interests TEXT DEFAULT NULL')
    if 'invited_by' not in columns:
        cursor.execute('ALTER TABLE users ADD COLUMN invited_by INTEGER DEFAULT NULL')

    # Predictions System Tables
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS matches (
        match_id INTEGER PRIMARY KEY AUTOINCREMENT,
        team_a TEXT,
        team_b TEXT,
        score_a INTEGER DEFAULT NULL,
        score_b INTEGER DEFAULT NULL,
        status TEXT DEFAULT 'OPEN', -- OPEN, CLOSED, RESOLVED
        result TEXT DEFAULT NULL,
        match_time TIMESTAMP DEFAULT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    # Migration: Add match_time if not exists
    cursor.execute("PRAGMA table_info(matches)")
    match_columns = [column[1] for column in cursor.fetchall()]
    if 'match_time' not in match_columns:
        cursor.execute('ALTER TABLE matches ADD COLUMN match_time TIMESTAMP DEFAULT NULL')
    if 'created_at' not in match_columns:
        cursor.execute('ALTER TABLE matches ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP')
    if 'score_a' not in match_columns:
        cursor.execute('ALTER TABLE matches ADD COLUMN score_a INTEGER DEFAULT NULL')
    if 'score_b' not in match_columns:
        cursor.execute('ALTER TABLE matches ADD COLUMN score_b INTEGER DEFAULT NULL')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS predictions (
        user_id INTEGER,
        match_id INTEGER,
        prediction TEXT, -- A, B, DRAW, or SCORE
        pred_score_a INTEGER DEFAULT NULL,
        pred_score_b INTEGER DEFAULT NULL,
        status TEXT DEFAULT 'PENDING', -- PENDING, WON, LOST
        FOREIGN KEY(match_id) REFERENCES matches(match_id)
    )
    ''')
    
    # Migration: Add pred_score_a and pred_score_b if not exists
    cursor.execute("PRAGMA table_info(predictions)")
    pred_columns = [column[1] for column in cursor.fetchall()]
    if 'pred_score_a' not in pred_columns:
        cursor.execute('ALTER TABLE predictions ADD COLUMN pred_score_a INTEGER DEFAULT NULL')
    if 'pred_score_b' not in pred_columns:
        cursor.execute('ALTER TABLE predictions ADD COLUMN pred_score_b INTEGER DEFAULT NULL')

    # Link Tracking System
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS posted_links (
        link_id INTEGER PRIMARY KEY AUTOINCREMENT,
        url TEXT,
        chat_id INTEGER,
        message_id INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS link_clicks (
        user_id INTEGER,
        link_id INTEGER,
        clicked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (user_id, link_id),
        FOREIGN KEY(link_id) REFERENCES posted_links(link_id)
    )
    ''')
    
    # Reaction Tracking
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS reaction_rewards (
        user_id INTEGER,
        message_id INTEGER,
        chat_id INTEGER,
        PRIMARY KEY (user_id, message_id)
    )
    ''')

    # Group tracking for Broadcast/Articles
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS groups (
        chat_id INTEGER PRIMARY KEY,
        chat_title TEXT,
        chat_type TEXT,
        added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    # User notification preferences
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS user_preferences (
        user_id INTEGER PRIMARY KEY,
        match_reminders INTEGER DEFAULT 1,
        result_notifications INTEGER DEFAULT 1,
        daily_reminder INTEGER DEFAULT 0,
        prediction_updates INTEGER DEFAULT 1,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    # Moderation audit log
    cursor.execute('''
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
    cursor.execute('''
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
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS posted_tweets (
        tweet_id TEXT PRIMARY KEY,
        chat_id INTEGER,
        message_id INTEGER,
        posted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    # Add sport_type to matches if not exists
    cursor.execute("PRAGMA table_info(matches)")
    match_columns = [column[1] for column in cursor.fetchall()]
    if 'sport_type' not in match_columns:
        cursor.execute('ALTER TABLE matches ADD COLUMN sport_type TEXT DEFAULT "football"')
    if 'chat_id' not in match_columns:
        cursor.execute('ALTER TABLE matches ADD COLUMN chat_id INTEGER DEFAULT NULL')
    
    # Add sport_focus to groups if not exists
    cursor.execute("PRAGMA table_info(groups)")
    group_columns = [column[1] for column in cursor.fetchall()]
    if 'sport_focus' not in group_columns:
        cursor.execute('ALTER TABLE groups ADD COLUMN sport_focus TEXT DEFAULT NULL')
    
    # Dave.sport feed tables
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS davesport_subscribers (
        chat_id INTEGER PRIMARY KEY,
        twitter_enabled INTEGER DEFAULT 0,
        website_enabled INTEGER DEFAULT 1,
        sport_filter TEXT DEFAULT 'all',
        subscribed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS chat_category_routing (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id INTEGER NOT NULL,
        category TEXT NOT NULL,
        thread_id INTEGER,
        enabled INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(chat_id, category)
    )
    ''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS davesport_posts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        post_id TEXT NOT NULL,
        chat_id INTEGER NOT NULL,
        source TEXT NOT NULL,
        message_id INTEGER DEFAULT 0,
        posted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(post_id, chat_id)
    )
    ''')
    
    # Create indexes for Dave.sport tables
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_davesport_subscribers_chat ON davesport_subscribers(chat_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_chat_category_routing_chat ON chat_category_routing(chat_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_chat_category_routing_category ON chat_category_routing(category)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_davesport_posts_post ON davesport_posts(post_id, chat_id)')

    conn.commit()
    conn.close()

def get_connection():
    return sqlite3.connect(DB_NAME)

# Group Management
def add_group(chat_id, title, chat_type):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('INSERT OR REPLACE INTO groups (chat_id, chat_title, chat_type) VALUES (?, ?, ?)', (chat_id, title, chat_type))
    conn.commit()
    conn.close()

def remove_group(chat_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM groups WHERE chat_id = ?', (chat_id,))
    conn.commit()
    conn.close()

def get_all_groups():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT chat_id FROM groups')
    groups = [row[0] for row in cursor.fetchall()]
    conn.close()
    return groups

# User Management
def add_user(user_id, username, invited_by=None):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('INSERT OR IGNORE INTO users (user_id, username, invited_by) VALUES (?, ?, ?)', (user_id, username, invited_by))
        # Update username if it changed
        cursor.execute('UPDATE users SET username = ? WHERE user_id = ?', (username, user_id))
        
        # If invited_by is provided and user was just inserted (or invited_by was null), update it?
        # For now, simplistic: if invited_by provided and current is null, set it.
        if invited_by:
            cursor.execute('UPDATE users SET invited_by = ? WHERE user_id = ? AND invited_by IS NULL', (invited_by, user_id))
            
        conn.commit()
    except Exception as e:
        logging.error(f"Error adding user: {e}")
    finally:
        conn.close()

def get_user(user_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
    user = cursor.fetchone()
    conn.close()
    return user

def get_user_by_username(username):
    conn = get_connection()
    cursor = conn.cursor()
    # Remove @ if present
    clean_username = username.lstrip('@')
    cursor.execute('SELECT * FROM users WHERE username = ? COLLATE NOCASE', (clean_username,))
    user = cursor.fetchone()
    conn.close()
    return user

def update_user_profile(user_id, club=None, interests=None):
    conn = get_connection()
    cursor = conn.cursor()
    if club is not None:
        cursor.execute('UPDATE users SET club = ? WHERE user_id = ?', (club, user_id))
    if interests is not None:
        cursor.execute('UPDATE users SET interests = ? WHERE user_id = ?', (interests, user_id))
    conn.commit()
    conn.close()

def update_user_role(user_id, role):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET role = ? WHERE user_id = ?', (role, user_id))
    conn.commit()
    conn.close()

# Warnings
def add_warning(user_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET warning_count = warning_count + 1 WHERE user_id = ?', (user_id,))
    conn.commit()
    
    cursor.execute('SELECT warning_count FROM users WHERE user_id = ?', (user_id,))
    count = cursor.fetchone()[0]
    conn.close()
    return count

def reset_warnings(user_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET warning_count = 0 WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()

# Economy
def update_balance(user_id, amount):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('UPDATE users SET coin_balance = coin_balance + ? WHERE user_id = ?', (amount, user_id))
        conn.commit()
        return cursor.rowcount > 0
    except Exception as e:
        logging.error(f"Balance update error: {e}")
        return False
    finally:
        conn.close()

def get_top_users(limit=10):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT username, coin_balance FROM users ORDER BY coin_balance DESC LIMIT ?', (limit,))
    top_users = cursor.fetchall()
    conn.close()
    return top_users

def set_daily_claim(user_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET last_daily_claim = CURRENT_TIMESTAMP WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()

# User Preferences
def get_user_preferences(user_id):
    """Get user notification preferences, create default if not exists"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM user_preferences WHERE user_id = ?', (user_id,))
    prefs = cursor.fetchone()
    
    if not prefs:
        # Create default preferences
        cursor.execute('INSERT INTO user_preferences (user_id) VALUES (?)', (user_id,))
        conn.commit()
        cursor.execute('SELECT * FROM user_preferences WHERE user_id = ?', (user_id,))
        prefs = cursor.fetchone()
    
    conn.close()
    # Returns: (user_id, match_reminders, result_notifications, daily_reminder, prediction_updates, updated_at)
    return prefs

def update_user_preference(user_id, pref_name, value):
    """Update a specific preference"""
    conn = get_connection()
    cursor = conn.cursor()
    
    # Ensure user has preferences row
    cursor.execute('INSERT OR IGNORE INTO user_preferences (user_id) VALUES (?)', (user_id,))
    
    # Update the specific preference
    valid_prefs = ['match_reminders', 'result_notifications', 'daily_reminder', 'prediction_updates']
    if pref_name in valid_prefs:
        cursor.execute(f'UPDATE user_preferences SET {pref_name} = ?, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?', 
                      (value, user_id))
    conn.commit()
    conn.close()

def get_users_with_preference(pref_name, value=1):
    """Get all user IDs who have a specific preference enabled"""
    conn = get_connection()
    cursor = conn.cursor()
    
    valid_prefs = ['match_reminders', 'result_notifications', 'daily_reminder', 'prediction_updates']
    if pref_name not in valid_prefs:
        conn.close()
        return []
    
    cursor.execute(f'SELECT user_id FROM user_preferences WHERE {pref_name} = ?', (value,))
    users = [row[0] for row in cursor.fetchall()]
    conn.close()
    return users

def get_all_users_for_notification():
    """Get all users who have match_reminders enabled (or haven't set preferences = default on)"""
    conn = get_connection()
    cursor = conn.cursor()
    
    # Get users with explicit preference ON, plus users without any preference record (default is ON)
    cursor.execute('''
        SELECT u.user_id FROM users u
        LEFT JOIN user_preferences p ON u.user_id = p.user_id
        WHERE p.match_reminders = 1 OR p.user_id IS NULL
    ''')
    users = [row[0] for row in cursor.fetchall()]
    conn.close()
    return users
