# Bug Fixes: Daily Rewards and WordPress Article Routing

## Summary
This document describes two critical bug fixes implemented for the Dave.sport Telegram bot:

1. **Daily Reward Race Condition** - Users could claim daily rewards multiple times
2. **WordPress Articles Not Routing to Sub-Topics** - Articles weren't being delivered to topic groups

---

## Fix 1: Daily Reward Race Condition ✅

### Problem
Users could click the daily reward button multiple times and claim rewards repeatedly. This was caused by:
- A race condition where multiple concurrent requests could pass the time check before any update occurred
- The check used `> timedelta(days=1)` (more than 24 hours) instead of checking for a new calendar day
- No atomic database operation to prevent simultaneous claims

### Solution
Implemented an **atomic UPDATE with WHERE clause** that:
1. **Checks and updates in a single database operation** - prevents race conditions
2. **Uses calendar day comparison** - `DATE(last_daily_claim) < DATE('now')` instead of 24-hour intervals
3. **Validates rowcount** - only returns success if a row was actually updated

### Changes Made
- **File**: `backend/service.py` (lines 162-212)
- **Key Changes**:
  ```python
  # Atomic operation - check and update in one query
  cur.execute(
      """UPDATE users 
         SET coin_balance = coin_balance + %s, 
             last_daily_claim = CURRENT_TIMESTAMP 
         WHERE user_id = %s 
         AND (last_daily_claim IS NULL 
              OR DATE(last_daily_claim) < DATE('now'))""",
      (reward_amount, user_id),
  )
  updated = cur.rowcount > 0
  ```

### Testing
```bash
# Test daily reward claiming
# 1. User claims daily reward - should succeed
# 2. User tries to claim again immediately - should fail with retry time
# 3. Wait until next day (or change system date) - should succeed again
```

---

## Fix 2: WordPress Articles Not Routing to Sub-Topics ✅

### Problem
WordPress articles from davedotsport.com were not being delivered to the configured topic groups. The routing system requires three database tables that were missing:
- `davesport_subscribers` - tracks which chats subscribe to Dave.sport feeds
- `chat_category_routing` - maps content categories to specific chat topics/threads
- `davesport_posts` - prevents duplicate article posts

### Solution
Added the missing database tables to all database initialization files with proper indexes for performance.

### Changes Made

#### 1. Database Schema Files
- **`backend/db.py`** - Added tables to backend initialization (lines 81-130)
- **`database.py`** - Added tables to main database init (lines 189-228)
- **`async_database.py`** - Added tables to async database init (lines 251-291)

#### 2. Migration Files
- **`backend/migrations/add_davesport_tables.sql`** - SQL migration script
- **`migrate_davesport_tables.py`** - Python migration script for existing databases

### Database Tables Created

#### `davesport_subscribers`
Tracks which chats are subscribed to Dave.sport feeds:
```sql
CREATE TABLE davesport_subscribers (
    chat_id INTEGER PRIMARY KEY,
    twitter_enabled INTEGER DEFAULT 0,
    website_enabled INTEGER DEFAULT 1,
    sport_filter TEXT DEFAULT 'all',
    subscribed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### `chat_category_routing`
Maps content categories to specific chat topics/threads:
```sql
CREATE TABLE chat_category_routing (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    category TEXT NOT NULL,
    thread_id INTEGER,
    enabled INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(chat_id, category)
);
```

#### `davesport_posts`
Prevents duplicate posts:
```sql
CREATE TABLE davesport_posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id TEXT NOT NULL,
    chat_id INTEGER NOT NULL,
    source TEXT NOT NULL,
    message_id INTEGER DEFAULT 0,
    posted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(post_id, chat_id)
);
```

---

## Deployment Instructions

### For Existing Databases (Already Running)

Run the migration script:
```bash
python migrate_davesport_tables.py
```

This will:
- Create the three missing tables
- Add necessary indexes
- Verify the tables were created successfully

### For New Deployments

The tables will be created automatically on first run since they're now included in all initialization scripts.

---

## How WordPress Article Routing Works

### 1. Subscribe a Chat
```
/subscribe
```
This creates a subscription in the `davesport_subscribers` table.

### 2. Configure Topic Routing
Open the target topic (e.g., "Football News") and run:
```
/setchatchannel football_news
```

This creates a mapping in `chat_category_routing`:
- `chat_id`: The group ID
- `category`: "football_news"
- `thread_id`: The topic thread ID
- `enabled`: 1

### 3. Articles Are Auto-Routed
Every 5 minutes, the bot:
1. Fetches latest articles from WordPress
2. Detects categories using WordPress category IDs/names
3. Looks up which chats/topics should receive each category
4. Posts articles to the correct topics
5. Marks them as posted in `davesport_posts` to prevent duplicates

### Available Categories
- `football_news` - General football/soccer news
- `transfer_news` - Transfer updates
- `epl_news` - English Premier League
- `wsl_news` - Women's Super League
- `live_scores` - Live score updates
- `f1_news` - Formula 1
- `boxing_news` - Boxing
- `golf_news` - Golf
- `darts_news` - Darts
- `ufc_news` - UFC/MMA

---

## Verification

### Check Daily Rewards
1. Claim daily reward: `/daily`
2. Try to claim again immediately - should show retry time
3. Check database:
   ```sql
   SELECT user_id, last_daily_claim FROM users WHERE user_id = YOUR_USER_ID;
   ```

### Check Article Routing
1. Verify tables exist:
   ```bash
   sqlite3 dave_sports.db
   .tables
   ```
   Should show: `davesport_subscribers`, `chat_category_routing`, `davesport_posts`

2. Subscribe a chat: `/subscribe`

3. Configure a topic:
   ```
   # In a topic thread:
   /setchatchannel football_news
   ```

4. Check configuration:
   ```sql
   SELECT * FROM chat_category_routing;
   ```

5. Wait for next feed check (every 5 minutes) or restart the bot

6. New articles should appear in the configured topic

---

## Troubleshooting

### Daily Rewards Still Claiming Multiple Times
- Restart the backend service to load the new code
- Check `backend/service.py` line 162 has the new atomic UPDATE logic

### Articles Still Not Routing
1. **Check tables exist**:
   ```bash
   python migrate_davesport_tables.py
   ```

2. **Verify subscription**:
   ```sql
   SELECT * FROM davesport_subscribers WHERE chat_id = YOUR_CHAT_ID;
   ```

3. **Verify topic configuration**:
   ```sql
   SELECT * FROM chat_category_routing WHERE chat_id = YOUR_CHAT_ID;
   ```

4. **Check bot logs** for WordPress fetch errors or routing issues

5. **Verify categories are detected**:
   - WordPress articles must have categories assigned
   - Category IDs or names must match the routing mappings in `davesport_feed.py` (lines 483-560)

---

## Files Modified

### Core Fixes
- `backend/service.py` - Fixed daily reward race condition
- `backend/db.py` - Added Dave.sport tables to initialization
- `database.py` - Added Dave.sport tables to main DB init
- `async_database.py` - Added Dave.sport tables to async DB init

### New Files
- `backend/migrations/add_davesport_tables.sql` - SQL migration
- `migrate_davesport_tables.py` - Python migration script
- `FIXES_README.md` - This documentation

---

## Questions?

If you encounter any issues:
1. Check the bot logs for errors
2. Run the migration script if upgrading from an older version
3. Verify database tables exist and contain expected data
4. Restart all services after deploying changes
