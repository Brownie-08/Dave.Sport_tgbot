from database import get_connection

# --- Link Tracking ---
def create_tracked_link(url, chat_id, message_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('INSERT INTO posted_links (url, chat_id, message_id) VALUES (?, ?, ?)', (url, chat_id, message_id))
    link_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return link_id

def get_tracked_link(link_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT url FROM posted_links WHERE link_id = ?', (link_id,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None

def has_user_clicked_link(user_id, link_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT 1 FROM link_clicks WHERE user_id = ? AND link_id = ?', (user_id, link_id))
    exists = cursor.fetchone()
    conn.close()
    return exists is not None

def record_link_click(user_id, link_id):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('INSERT OR IGNORE INTO link_clicks (user_id, link_id) VALUES (?, ?)', (user_id, link_id))
        conn.commit()
        # rowcount is 1 if inserted, 0 if ignored
        return cursor.rowcount > 0
    except:
        return False
    finally:
        conn.close()

# --- Reaction Tracking ---
def has_user_reacted(user_id, message_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT 1 FROM reaction_rewards WHERE user_id = ? AND message_id = ?', (user_id, message_id))
    exists = cursor.fetchone()
    conn.close()
    return exists is not None

def record_reaction_reward(user_id, message_id, chat_id):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('INSERT OR IGNORE INTO reaction_rewards (user_id, message_id, chat_id) VALUES (?, ?, ?)', (user_id, message_id, chat_id))
        conn.commit()
    except:
        pass
    finally:
        conn.close()
