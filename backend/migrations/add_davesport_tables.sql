-- Migration: Add Dave.sport feed tables
-- This adds the tables needed for WordPress article routing to sub-topic groups

-- Subscribers table: tracks which chats are subscribed to Dave.sport feeds
CREATE TABLE IF NOT EXISTS davesport_subscribers (
    chat_id INTEGER PRIMARY KEY,
    twitter_enabled INTEGER DEFAULT 0,
    website_enabled INTEGER DEFAULT 1,
    sport_filter TEXT DEFAULT 'all',
    subscribed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Category routing table: maps content categories to specific chat topics/threads
CREATE TABLE IF NOT EXISTS chat_category_routing (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    category TEXT NOT NULL,
    thread_id INTEGER,
    enabled INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(chat_id, category)
);

-- Posted content tracking: prevents duplicate posts
CREATE TABLE IF NOT EXISTS davesport_posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id TEXT NOT NULL,
    chat_id INTEGER NOT NULL,
    source TEXT NOT NULL,
    message_id INTEGER DEFAULT 0,
    posted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(post_id, chat_id)
);

-- Create indexes for better query performance
CREATE INDEX IF NOT EXISTS idx_davesport_subscribers_chat ON davesport_subscribers(chat_id);
CREATE INDEX IF NOT EXISTS idx_chat_category_routing_chat ON chat_category_routing(chat_id);
CREATE INDEX IF NOT EXISTS idx_chat_category_routing_category ON chat_category_routing(category);
CREATE INDEX IF NOT EXISTS idx_davesport_posts_post ON davesport_posts(post_id, chat_id);
