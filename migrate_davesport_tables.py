#!/usr/bin/env python3
"""
Migration script to add Dave.sport feed tables to existing database
Run this once to update your database with the new tables
"""

import sqlite3
import sys
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "dave_sports.db"

def migrate():
    print(f"Migrating database: {DB_PATH}")
    
    if not DB_PATH.exists():
        print(f"❌ Database not found at {DB_PATH}")
        sys.exit(1)
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        print("Creating davesport_subscribers table...")
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS davesport_subscribers (
            chat_id INTEGER PRIMARY KEY,
            twitter_enabled INTEGER DEFAULT 0,
            website_enabled INTEGER DEFAULT 1,
            sport_filter TEXT DEFAULT 'all',
            subscribed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        
        print("Creating chat_category_routing table...")
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
        
        print("Creating davesport_posts table...")
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
        
        print("Creating indexes...")
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_davesport_subscribers_chat ON davesport_subscribers(chat_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_chat_category_routing_chat ON chat_category_routing(chat_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_chat_category_routing_category ON chat_category_routing(category)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_davesport_posts_post ON davesport_posts(post_id, chat_id)')
        
        conn.commit()
        print("✅ Migration completed successfully!")
        
        # Verify tables exist
        print("\nVerifying tables...")
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'davesport%' OR name LIKE 'chat_category%'")
        tables = cursor.fetchall()
        for table in tables:
            print(f"  ✓ {table[0]}")
        
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        conn.rollback()
        sys.exit(1)
    finally:
        conn.close()

if __name__ == "__main__":
    migrate()
