import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

# Point to the root directory's dave_sports.db
DB_PATH = Path(__file__).resolve().parents[1] / "dave_sports.db"

def dict_factory(cursor, row):
    d = {}
    for idx, col in enumerate(cursor.description):
        d[col[0]] = row[idx]
    return d

class CustomCursor:
    def __init__(self, cursor):
        self.cursor = cursor

    def execute(self, sql, params=None):
        # Convert %s to ? for SQLite
        sql = sql.replace("%s", "?")
        if params is None:
            return self.cursor.execute(sql)
        return self.cursor.execute(sql, params)

    def fetchone(self):
        return self.cursor.fetchone()

    def fetchall(self):
        return self.cursor.fetchall()

    @property
    def rowcount(self):
        return self.cursor.rowcount

    @property
    def description(self):
        return self.cursor.description
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.cursor.close()
        return False

@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = dict_factory
    
    # Wrap the cursor to handle %s -> ? conversion
    original_cursor_method = conn.cursor
    
    def cursor_wrapper():
        return CustomCursor(original_cursor_method())
    
    # Monkey patch cursor method for this connection instance (bit hacky but works for context manager)
    # Actually, better to just yield the connection and let the service layer get the cursor.
    # But the service layer expects: with conn.cursor() as cur:
    
    # We need a connection wrapper too to wrap the cursor method
    class ConnectionWrapper:
        def __init__(self, connection):
            self.connection = connection
        
        def cursor(self):
            return CustomCursor(self.connection.cursor())
        
        def commit(self):
            self.connection.commit()
            
        def close(self):
            self.connection.close()
            
    try:
        yield ConnectionWrapper(conn)
    finally:
        conn.close()

def init_db():
    """Initialize database schema including Dave.sport feed tables"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Dave.sport subscribers table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS davesport_subscribers (
        chat_id INTEGER PRIMARY KEY,
        twitter_enabled INTEGER DEFAULT 0,
        website_enabled INTEGER DEFAULT 1,
        sport_filter TEXT DEFAULT 'all',
        subscribed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    # Category routing table
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
    
    # Posted content tracking
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
    
    # Create indexes
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_davesport_subscribers_chat ON davesport_subscribers(chat_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_chat_category_routing_chat ON chat_category_routing(chat_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_chat_category_routing_category ON chat_category_routing(category)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_davesport_posts_post ON davesport_posts(post_id, chat_id)')
    
    conn.commit()
    conn.close()
