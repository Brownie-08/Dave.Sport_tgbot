import sqlite3
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

from database import get_connection
import config
from shared_constants import CLUBS_DATA, INTERESTS


def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    return {k: row[k] for k in row.keys()}


def ensure_moderation_tables():
    conn = get_connection()
    cursor = conn.cursor()
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
    conn.commit()
    conn.close()


def upsert_user(user_id: int, username: str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)', (user_id, username))
    cursor.execute('UPDATE users SET username = ? WHERE user_id = ?', (username, user_id))
    conn.commit()
    conn.close()


def get_user(user_id: int) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    conn.close()
    return _row_to_dict(row) if row else None


def get_user_role(user_id: int) -> str:
    user = get_user(user_id)
    if not user:
        return "user"
    return (user.get("role") or "user").lower()


def get_me(user_id: int) -> Dict[str, Any]:
    user = get_user(user_id)
    if not user:
        return {"id": user_id, "username": None, "role": "user", "club": None, "interests": [], "coins": 0}
    club_value = user.get("club")
    club_entry = None
    if club_value:
        if club_value in CLUBS_DATA:
            club_entry = {"key": club_value, "label": CLUBS_DATA[club_value]["name"], "badge": CLUBS_DATA[club_value].get("badge")}
        else:
            for key, data in CLUBS_DATA.items():
                if data.get("name") == club_value or key.lower() in club_value.lower():
                    club_entry = {"key": key, "label": data.get("name", key), "badge": data.get("badge")}
                    break
    interests_raw = user.get("interests") or ""
    interests = [i for i in interests_raw.split(",") if i]
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM users WHERE invited_by = ?', (user_id,))
    invite_count = cursor.fetchone()[0] or 0
    conn.close()
    return {
        "id": user_id,
        "username": user.get("username"),
        "role": (user.get("role") or "user").lower(),
        "club": club_entry,
        "interests": interests,
        "coins": user.get("coin_balance") or 0,
        "referrals": {
            "invite_count": invite_count,
            "coins_earned": invite_count * config.INVITE_REWARD
        }
    }


def update_me(user_id: int, club_key: Optional[str] = None, interests: Optional[List[str]] = None) -> Dict[str, Any]:
    conn = get_connection()
    cursor = conn.cursor()
    if club_key is not None:
        if club_key == "":
            club_value = None
        elif club_key in CLUBS_DATA:
            club_value = CLUBS_DATA[club_key]["name"]
        else:
            raise ValueError("invalid_club")
        cursor.execute('UPDATE users SET club = ? WHERE user_id = ?', (club_value, user_id))
    if interests is not None:
        filtered = [i for i in interests if i in INTERESTS]
        interests_value = ",".join(filtered)
        cursor.execute('UPDATE users SET interests = ? WHERE user_id = ?', (interests_value, user_id))
    conn.commit()
    conn.close()
    return get_me(user_id)


def get_wallet(user_id: int) -> Dict[str, Any]:
    user = get_user(user_id)
    return {"coins": user.get("coin_balance") if user else 0}


def claim_daily(user_id: int) -> Dict[str, Any]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT coin_balance, last_daily_claim FROM users WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return {"claimed": False, "error": "user_not_found"}
    balance, last_claim_str = row
    can_claim = False
    if not last_claim_str:
        can_claim = True
    else:
        try:
            last_claim = datetime.strptime(last_claim_str, '%Y-%m-%d %H:%M:%S')
            if datetime.utcnow() - last_claim > timedelta(days=1):
                can_claim = True
        except ValueError:
            can_claim = True
    if can_claim:
        cursor.execute('UPDATE users SET coin_balance = coin_balance + ?, last_daily_claim = CURRENT_TIMESTAMP WHERE user_id = ?', (2, user_id))
        conn.commit()
        conn.close()
        return {"claimed": True, "coins_added": 2, "balance": (balance or 0) + 2}
    last_claim = datetime.strptime(last_claim_str, '%Y-%m-%d %H:%M:%S')
    next_claim = last_claim + timedelta(days=1)
    remaining = next_claim - datetime.utcnow()
    hours, remainder = divmod(int(remaining.total_seconds()), 3600)
    minutes, _ = divmod(remainder, 60)
    conn.close()
    return {"claimed": False, "retry_in": {"hours": hours, "minutes": minutes}, "balance": balance or 0}


def get_open_matches(limit: Optional[int] = None) -> List[Dict[str, Any]]:
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    query = 'SELECT * FROM matches WHERE status = "OPEN" ORDER BY match_time ASC'
    if limit:
        query += f' LIMIT {int(limit)}'
    cursor.execute(query)
    rows = cursor.fetchall()
    conn.close()
    return [
        {
            "match_id": r["match_id"],
            "team_a": r["team_a"],
            "team_b": r["team_b"],
            "match_time": r["match_time"],
            "sport_type": r["sport_type"]
        }
        for r in rows
    ]


def place_prediction(user_id: int, match_id: int, prediction: str, score_a: Optional[int] = None, score_b: Optional[int] = None) -> Dict[str, Any]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT status FROM matches WHERE match_id = ?', (match_id,))
    match = cursor.fetchone()
    if not match or match[0] != "OPEN":
        conn.close()
        return {"success": False, "error": "match_closed"}
    cursor.execute('SELECT 1 FROM predictions WHERE user_id = ? AND match_id = ?', (user_id, match_id))
    if cursor.fetchone():
        conn.close()
        return {"success": False, "error": "already_predicted"}
    cursor.execute(
        'INSERT INTO predictions (user_id, match_id, prediction, pred_score_a, pred_score_b) VALUES (?, ?, ?, ?, ?)',
        (user_id, match_id, prediction, score_a, score_b)
    )
    conn.commit()
    conn.close()
    return {"success": True}


def get_predictions_history(user_id: int) -> List[Dict[str, Any]]:
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute('''
        SELECT p.match_id, p.prediction, p.pred_score_a, p.pred_score_b, p.status,
               m.team_a, m.team_b, m.score_a, m.score_b, m.result, m.match_time, m.sport_type
        FROM predictions p
        JOIN matches m ON p.match_id = m.match_id
        WHERE p.user_id = ?
        ORDER BY m.match_time DESC, m.match_id DESC
    ''', (user_id,))
    rows = cursor.fetchall()
    conn.close()
    items = []
    for r in rows:
        if r["prediction"] == "SCORE":
            pred_display = f"{r['pred_score_a']}-{r['pred_score_b']}"
        elif r["prediction"] == "A":
            pred_display = r["team_a"]
        elif r["prediction"] == "B":
            pred_display = r["team_b"]
        else:
            pred_display = "Draw"
        result = "Pending"
        if r["result"] == "A":
            result = r["team_a"]
        elif r["result"] == "B":
            result = r["team_b"]
        elif r["result"] == "DRAW":
            result = "Draw"
        items.append({
            "match_id": r["match_id"],
            "match": f"{r['team_a']} vs {r['team_b']}",
            "prediction": pred_display,
            "status": r["status"],
            "result": result,
            "coins_earned": config.PREDICTION_REWARD if r["status"] == "WON" else 0,
            "match_time": r["match_time"],
            "sport_type": r["sport_type"]
        })
    return items


def get_predictions_stats(user_id: int) -> Dict[str, Any]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT COUNT(*) as total,
               SUM(CASE WHEN status = 'WON' THEN 1 ELSE 0 END) as wins,
               SUM(CASE WHEN status = 'LOST' THEN 1 ELSE 0 END) as losses
        FROM predictions WHERE user_id = ?
    ''', (user_id,))
    row = cursor.fetchone()
    total = row[0] or 0
    wins = row[1] or 0
    losses = row[2] or 0
    win_rate = round((wins / total * 100), 1) if total else 0
    cursor.execute('''
        SELECT status FROM predictions
        WHERE user_id = ? AND status IN ('WON','LOST')
        ORDER BY match_id DESC LIMIT 20
    ''', (user_id,))
    statuses = [r[0] for r in cursor.fetchall()]
    conn.close()
    streak_type = None
    streak_count = 0
    if statuses:
        first = statuses[0]
        for s in statuses:
            if s == first:
                streak_count += 1
            else:
                break
        streak_type = "W" if first == "WON" else "L"
    return {
        "total": total,
        "wins": wins,
        "losses": losses,
        "win_rate": win_rate,
        "streak": {"type": streak_type, "count": streak_count}
    }


def get_leaderboard_global(page: int, limit: int, user_id: Optional[int] = None) -> Dict[str, Any]:
    offset = (page - 1) * limit
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM users')
    total_users = cursor.fetchone()[0] or 0
    cursor.execute('SELECT user_id, username, coin_balance FROM users ORDER BY coin_balance DESC, user_id ASC LIMIT ? OFFSET ?', (limit, offset))
    rows = cursor.fetchall()
    current_rank = None
    if user_id:
        cursor.execute('SELECT coin_balance FROM users WHERE user_id = ?', (user_id,))
        row = cursor.fetchone()
        coins = row[0] if row else 0
        cursor.execute('SELECT COUNT(*) FROM users WHERE coin_balance > ?', (coins,))
        higher = cursor.fetchone()[0] or 0
        current_rank = higher + 1 if total_users else None
    conn.close()
    items = []
    for idx, r in enumerate(rows):
        items.append({
            "rank": offset + idx + 1,
            "user_id": r[0],
            "username": r[1] or "Unknown",
            "coins": r[2] or 0
        })
    return {"items": items, "total_users": total_users, "current_user_rank": current_rank}


def get_leaderboard_predictions(page: int, limit: int, user_id: Optional[int] = None) -> Dict[str, Any]:
    offset = (page - 1) * limit
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT u.user_id, u.username,
               SUM(CASE WHEN p.status = 'WON' THEN 1 ELSE 0 END) as wins,
               SUM(CASE WHEN p.status IN ('WON','LOST') THEN 1 ELSE 0 END) as total
        FROM predictions p JOIN users u ON p.user_id = u.user_id
        WHERE p.status IN ('WON','LOST')
        GROUP BY p.user_id
        HAVING total >= 3
        ORDER BY (wins * 1.0 / total) DESC, total DESC, u.user_id ASC
        LIMIT ? OFFSET ?
    ''', (limit, offset))
    rows = cursor.fetchall()
    current_rank = None
    if user_id:
        cursor.execute('''
            SELECT SUM(CASE WHEN status = 'WON' THEN 1 ELSE 0 END) as wins,
                   SUM(CASE WHEN status IN ('WON','LOST') THEN 1 ELSE 0 END) as total
            FROM predictions WHERE user_id = ? AND status IN ('WON','LOST')
        ''', (user_id,))
        row = cursor.fetchone()
        if row and row[1] and row[1] >= 3:
            wins, total = row[0] or 0, row[1] or 0
            win_rate = wins / total if total else 0
            cursor.execute('''
                SELECT COUNT(*) FROM (
                    SELECT p.user_id,
                           SUM(CASE WHEN p.status = 'WON' THEN 1 ELSE 0 END) AS wins,
                           SUM(CASE WHEN p.status IN ('WON','LOST') THEN 1 ELSE 0 END) AS total
                    FROM predictions p
                    WHERE p.status IN ('WON','LOST')
                    GROUP BY p.user_id HAVING total >= 3
                ) t WHERE (wins * 1.0 / total) > ? OR ((wins * 1.0 / total) = ? AND total > ?)
            ''', (win_rate, win_rate, total))
            higher = cursor.fetchone()[0] or 0
            current_rank = higher + 1
    conn.close()
    items = []
    for idx, r in enumerate(rows):
        wins = r[2] or 0
        total = r[3] or 0
        win_rate = round((wins / total * 100), 1) if total else 0
        items.append({
            "rank": offset + idx + 1,
            "user_id": r[0],
            "username": r[1] or "Unknown",
            "wins": wins,
            "total": total,
            "win_rate": win_rate
        })
    return {"items": items, "current_user_rank": current_rank}


def log_moderation(actor_id: int, target_id: int, action: str, reason: str = ""):
    ensure_moderation_tables()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO moderation_audit (actor_id, target_id, action, reason) VALUES (?, ?, ?, ?)',
        (actor_id, target_id, action, reason or "")
    )
    conn.commit()
    conn.close()


def warn_user(actor_id: int, target_id: int, reason: str = "") -> int:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET warning_count = warning_count + 1 WHERE user_id = ?', (target_id,))
    conn.commit()
    cursor.execute('SELECT warning_count FROM users WHERE user_id = ?', (target_id,))
    row = cursor.fetchone()
    count = row[0] if row else 0
    conn.close()
    log_moderation(actor_id, target_id, "warn", reason)
    return count


def log_mute(actor_id: int, target_id: int, reason: str = ""):
    log_moderation(actor_id, target_id, "mute", reason)


def log_ban(actor_id: int, target_id: int, reason: str = ""):
    log_moderation(actor_id, target_id, "ban", reason)


def get_open_picks(user_id: int, limit: int = 3) -> List[Dict[str, Any]]:
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute('''
        SELECT p.match_id, p.prediction, p.pred_score_a, p.pred_score_b, p.status,
               m.team_a, m.team_b, m.status as match_status
        FROM predictions p
        JOIN matches m ON p.match_id = m.match_id
        WHERE p.user_id = ? AND m.status IN ('OPEN','CLOSED')
        ORDER BY m.match_time ASC, m.match_id DESC
        LIMIT ?
    ''', (user_id, limit))
    rows = cursor.fetchall()
    conn.close()
    items = []
    for r in rows:
        if r["prediction"] == "SCORE" and r["pred_score_a"] is not None and r["pred_score_b"] is not None:
            pred_display = f"{r['pred_score_a']}-{r['pred_score_b']}"
        elif r["prediction"] == "A":
            pred_display = r["team_a"]
        elif r["prediction"] == "B":
            pred_display = r["team_b"]
        else:
            pred_display = "Draw"
        items.append({
            "match_id": r["match_id"],
            "team_a": r["team_a"],
            "team_b": r["team_b"],
            "prediction": pred_display,
            "status": r["status"]
        })
    return items
