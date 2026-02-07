import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple

from backend.db import get_conn
import config
from shared_constants import CLUBS_DATA, INTERESTS


def resolve_club_entry(club_value: Optional[str]) -> Optional[Dict[str, Any]]:
    if not club_value:
        return None
    if club_value in CLUBS_DATA:
        data = CLUBS_DATA[club_value]
        if isinstance(data, dict):
            return {"key": club_value, "label": data.get("name", club_value), "badge": data.get("badge")}
        return {"key": club_value, "label": str(data), "badge": None}
    for key, data in CLUBS_DATA.items():
        if not isinstance(data, dict):
            continue
        name = data.get("name", "")
        if name == club_value or key.lower() in str(club_value).lower() or str(club_value) in name:
            return {"key": key, "label": name or key, "badge": data.get("badge")}
    return None


def ensure_user(user_id: int, username: Optional[str] = None, invited_by: Optional[int] = None) -> bool:
    """Insert user if new. Returns True if created."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT user_id, invited_by FROM users WHERE user_id = %s", (user_id,))
            row = cur.fetchone()
            is_new = row is None
            if is_new:
                cur.execute(
                    "INSERT INTO users (user_id, username, invited_by) VALUES (%s, %s, %s)",
                    (user_id, username, invited_by),
                )
            else:
                cur.execute("UPDATE users SET username = %s WHERE user_id = %s", (username, user_id))
                if invited_by and row.get("invited_by") is None:
                    cur.execute(
                        "UPDATE users SET invited_by = %s WHERE user_id = %s AND invited_by IS NULL",
                        (invited_by, user_id),
                    )
        conn.commit()
    return is_new


def get_user(user_id: int) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
            return cur.fetchone()


def get_active_matches() -> List[Dict[str, Any]]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT m.*,
                       COALESCE(p.prediction_count, 0) AS prediction_count
                FROM matches m
                LEFT JOIN (
                    SELECT match_id, COUNT(*) AS prediction_count
                    FROM predictions
                    GROUP BY match_id
                ) p ON p.match_id = m.match_id
                WHERE m.status IN ('OPEN','CLOSED')
                ORDER BY m.match_id DESC
                """
            )
            return cur.fetchall() or []


def update_match_time(match_id: int, match_time: str):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE matches SET match_time = %s WHERE match_id = %s", (match_time, match_id))
        conn.commit()


def get_user_by_username(username: str) -> Optional[Dict[str, Any]]:
    clean = username.lstrip("@")
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM users WHERE LOWER(username) = LOWER(%s)", (clean,))
            return cur.fetchone()


def get_user_role(user_id: int) -> str:
    # Owner override from .env
    if user_id and user_id == getattr(config, "OWNER_ID", 0):
        return "OWNER"

    user = get_user(user_id)
    if not user:
        return "MEMBER"
    return (user.get("role") or "MEMBER").upper()


def set_user_role(user_id: int, role: str) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET role = %s WHERE user_id = %s", (role, user_id))
        conn.commit()


def adjust_balance(user_id: int, amount: int) -> int:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO users (user_id, coin_balance) VALUES (%s, %s) "
                "ON CONFLICT (user_id) DO UPDATE SET coin_balance = coin_balance + EXCLUDED.coin_balance",
                (user_id, amount),
            )
            cur.execute("SELECT coin_balance FROM users WHERE user_id = %s", (user_id,))
            row = cur.fetchone()
        conn.commit()
    return int(row.get("coin_balance") or 0) if row else 0


def get_balance(user_id: int) -> int:
    user = get_user(user_id)
    return int(user.get("coin_balance") or 0) if user else 0


def build_me_response(user_id: int) -> Dict[str, Any]:
    user = get_user(user_id)
    if not user:
        role = "owner" if user_id and user_id == getattr(config, "OWNER_ID", 0) else "member"
        return {"id": user_id, "username": None, "role": role, "club": None, "interests": [], "coins": 0}

    club_value = user.get("club")
    club_entry = resolve_club_entry(club_value)

    interests_raw = user.get("interests") or ""
    interests = [i for i in interests_raw.split(",") if i]

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS cnt FROM users WHERE invited_by = %s", (user_id,))
            row = cur.fetchone()
            invite_count = int(row.get("cnt") or 0) if row else 0

    role = (user.get("role") or "MEMBER").lower()
    if user_id and user_id == getattr(config, "OWNER_ID", 0):
        role = "owner"

    return {
        "id": user_id,
        "username": user.get("username"),
        "role": role,
        "club": club_entry,
        "interests": interests,
        "coins": int(user.get("coin_balance") or 0),
        "referrals": {
            "invite_count": invite_count,
            "coins_earned": invite_count * config.INVITE_REWARD,
        },
    }


def update_me(user_id: int, club_key: Optional[str], interests: Optional[List[str]]) -> Dict[str, Any]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            if club_key is not None:
                if club_key == "":
                    club_value = None
                elif club_key in CLUBS_DATA:
                    club_value = CLUBS_DATA[club_key]["name"]
                else:
                    raise ValueError("invalid_club")
                cur.execute("UPDATE users SET club = %s WHERE user_id = %s", (club_value, user_id))
            if interests is not None:
                filtered = [i for i in interests if i in INTERESTS]
                interests_value = ",".join(filtered)
                cur.execute("UPDATE users SET interests = %s WHERE user_id = %s", (interests_value, user_id))
        conn.commit()
    return build_me_response(user_id)


def claim_daily(user_id: int, reward_amount: int = 2) -> Dict[str, Any]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            # Use a single atomic UPDATE with WHERE clause to prevent race conditions
            # This checks and updates in one operation, preventing concurrent claims
            now = datetime.utcnow()
            today_start = datetime(now.year, now.month, now.day)  # Start of current day
            
            # Try to claim: update only if last_daily_claim is NULL or older than today
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
            conn.commit()
            
            # Get current balance and last claim time
            cur.execute("SELECT coin_balance, last_daily_claim FROM users WHERE user_id = %s", (user_id,))
            row = cur.fetchone()
            if not row:
                return {"claimed": False, "error": "user_not_found"}
            
            balance = int(row.get("coin_balance") or 0)
            last_claim = row.get("last_daily_claim")
            
            if updated:
                return {"claimed": True, "coins_added": reward_amount, "balance": balance}
            
            # Already claimed today - calculate retry time
            retry_in = {}
            if last_claim:
                if isinstance(last_claim, str):
                    try:
                        last_claim = datetime.fromisoformat(last_claim.replace('Z', '+00:00'))
                    except:
                        last_claim = None
                
                if isinstance(last_claim, datetime):
                    # Calculate time until next day (midnight UTC)
                    next_claim = datetime(now.year, now.month, now.day) + timedelta(days=1)
                    remaining = next_claim - now
                    hours, remainder = divmod(int(remaining.total_seconds()), 3600)
                    minutes, _ = divmod(remainder, 60)
                    retry_in = {"hours": hours, "minutes": minutes}
            
            return {"claimed": False, "retry_in": retry_in, "balance": balance}


def get_open_matches() -> List[Dict[str, Any]]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM matches WHERE status = 'OPEN' ORDER BY match_time ASC NULLS LAST")
            return cur.fetchall() or []


def create_match(team_a: str, team_b: str, match_time: Optional[str] = None, sport_type: str = "football", chat_id: Optional[int] = None) -> int:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO matches (team_a, team_b, match_time, sport_type, chat_id) VALUES (%s, %s, %s, %s, %s) RETURNING match_id",
                (team_a, team_b, match_time, sport_type, chat_id),
            )
            row = cur.fetchone()
        conn.commit()
    return int(row.get("match_id"))


def get_match(match_id: int) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM matches WHERE match_id = %s", (match_id,))
            return cur.fetchone()


def close_match(match_id: int) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE matches SET status = 'CLOSED' WHERE match_id = %s AND status = 'OPEN'", (match_id,))
        conn.commit()


def delete_match(match_id: int) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM predictions WHERE match_id = %s", (match_id,))
            cur.execute("DELETE FROM matches WHERE match_id = %s", (match_id,))
        conn.commit()


def resolve_match(match_id: int, winner_code: str, score_a: Optional[int] = None, score_b: Optional[int] = None, reward: int = 0) -> List[int]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE matches SET status = 'RESOLVED', result = %s, score_a = %s, score_b = %s WHERE match_id = %s",
                (winner_code, score_a, score_b, match_id),
            )
            cur.execute(
                "SELECT user_id, prediction, pred_score_a, pred_score_b FROM predictions WHERE match_id = %s",
                (match_id,),
            )
            predictions = cur.fetchall() or []
            winners: List[int] = []
            for pred in predictions:
                uid = int(pred["user_id"])
                p_choice = pred["prediction"]
                p_sa = pred.get("pred_score_a")
                p_sb = pred.get("pred_score_b")
                won = False
                if p_choice == winner_code:
                    won = True
                elif p_choice == "SCORE" and score_a is not None and score_b is not None:
                    if p_sa == score_a and p_sb == score_b:
                        won = True
                status = "WON" if won else "LOST"
                cur.execute(
                    "UPDATE predictions SET status = %s WHERE user_id = %s AND match_id = %s",
                    (status, uid, match_id),
                )
                if won:
                    winners.append(uid)
            if reward and winners:
                for uid in winners:
                    cur.execute(
                        "UPDATE users SET coin_balance = coin_balance + %s WHERE user_id = %s",
                        (reward, uid),
                    )
        conn.commit()
    return winners


def add_prediction(user_id: int, match_id: int, prediction: str, score_a: Optional[int] = None, score_b: Optional[int] = None) -> bool:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT status FROM matches WHERE match_id = %s", (match_id,))
            match = cur.fetchone()
            if not match or match.get("status") != "OPEN":
                raise ValueError("match_closed")
            cur.execute("SELECT 1 FROM predictions WHERE user_id = %s AND match_id = %s", (user_id, match_id))
            if cur.fetchone():
                raise ValueError("already_predicted")
            cur.execute(
                "INSERT INTO predictions (user_id, match_id, prediction, pred_score_a, pred_score_b) VALUES (%s, %s, %s, %s, %s)",
                (user_id, match_id, prediction, score_a, score_b),
            )
        conn.commit()
    return True


def get_predictions_history(user_id: int) -> List[Dict[str, Any]]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT p.match_id, p.prediction, p.pred_score_a, p.pred_score_b, p.status,
                       m.team_a, m.team_b, m.score_a, m.score_b, m.result, m.match_time, m.sport_type
                FROM predictions p
                JOIN matches m ON p.match_id = m.match_id
                WHERE p.user_id = %s
                ORDER BY m.match_time DESC NULLS LAST, m.match_id DESC
                """,
                (user_id,),
            )
            rows = cur.fetchall() or []
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
        if r.get("result") == "A":
            result = r["team_a"]
        elif r.get("result") == "B":
            result = r["team_b"]
        elif r.get("result") == "DRAW":
            result = "Draw"
        items.append(
            {
                "match_id": r["match_id"],
                "match": f"{r['team_a']} vs {r['team_b']}",
                "prediction": pred_display,
                "status": r["status"],
                "result": result,
                "coins_earned": config.PREDICTION_REWARD if r["status"] == "WON" else 0,
                "match_time": r["match_time"],
                "sport_type": r.get("sport_type"),
            }
        )
    return items


def get_predictions_stats(user_id: int) -> Dict[str, Any]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) as total,
                       SUM(CASE WHEN status = 'WON' THEN 1 ELSE 0 END) as wins,
                       SUM(CASE WHEN status = 'LOST' THEN 1 ELSE 0 END) as losses
                FROM predictions WHERE user_id = %s
                """,
                (user_id,),
            )
            row = cur.fetchone() or {}
            total = int(row.get("total") or 0)
            wins = int(row.get("wins") or 0)
            losses = int(row.get("losses") or 0)
            win_rate = round((wins / total * 100), 1) if total else 0
            cur.execute(
                """
                SELECT status FROM predictions
                WHERE user_id = %s AND status IN ('WON','LOST')
                ORDER BY ROWID DESC LIMIT 20
                """,
                (user_id,),
            )
            statuses = [r["status"] for r in (cur.fetchall() or [])]
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
    return {"total": total, "wins": wins, "losses": losses, "win_rate": win_rate, "streak": {"type": streak_type, "count": streak_count}}


def get_leaderboard_global(page: int, limit: int, user_id: Optional[int] = None) -> Dict[str, Any]:
    offset = (page - 1) * limit
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS total FROM users")
            total_users = int((cur.fetchone() or {}).get("total") or 0)
            cur.execute(
                "SELECT user_id, username, coin_balance, club FROM users ORDER BY coin_balance DESC, user_id ASC LIMIT %s OFFSET %s",
                (limit, offset),
            )
            rows = cur.fetchall() or []
            current_rank = None
            if user_id:
                cur.execute("SELECT coin_balance FROM users WHERE user_id = %s", (user_id,))
                row = cur.fetchone()
                coins = int(row.get("coin_balance") or 0) if row else 0
                cur.execute("SELECT COUNT(*) AS higher FROM users WHERE coin_balance > %s", (coins,))
                higher = int((cur.fetchone() or {}).get("higher") or 0)
                current_rank = higher + 1 if total_users else None
    items = []
    for idx, r in enumerate(rows):
        club_entry = resolve_club_entry(r.get("club"))
        items.append(
            {
                "rank": offset + idx + 1,
                "user_id": r["user_id"],
                "username": r.get("username") or "Unknown",
                "coins": int(r.get("coin_balance") or 0),
                "club_label": (club_entry or {}).get("label"),
                "club_badge": (club_entry or {}).get("badge"),
            }
        )
    return {"items": items, "total_users": total_users, "current_user_rank": current_rank}


def get_leaderboard_predictions(page: int, limit: int, user_id: Optional[int] = None) -> Dict[str, Any]:
    offset = (page - 1) * limit
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT u.user_id, u.username, u.club,
                       SUM(CASE WHEN p.status = 'WON' THEN 1 ELSE 0 END) as wins,
                       SUM(CASE WHEN p.status IN ('WON','LOST') THEN 1 ELSE 0 END) as total
                FROM predictions p JOIN users u ON p.user_id = u.user_id
                WHERE p.status IN ('WON','LOST')
                GROUP BY p.user_id
                HAVING SUM(CASE WHEN p.status IN ('WON','LOST') THEN 1 ELSE 0 END) >= 3
                ORDER BY (SUM(CASE WHEN p.status = 'WON' THEN 1 ELSE 0 END) * 1.0 / SUM(CASE WHEN p.status IN ('WON','LOST') THEN 1 ELSE 0 END)) DESC,
                         total DESC,
                         u.user_id ASC
                LIMIT %s OFFSET %s
                """,
                (limit, offset),
            )
            rows = cur.fetchall() or []

            current_rank = None
            if user_id:
                cur.execute(
                    """
                    SELECT SUM(CASE WHEN status = 'WON' THEN 1 ELSE 0 END) as wins,
                           SUM(CASE WHEN status IN ('WON','LOST') THEN 1 ELSE 0 END) as total
                    FROM predictions WHERE user_id = %s AND status IN ('WON','LOST')
                    """,
                    (user_id,),
                )
                row = cur.fetchone() or {}
                wins = int(row.get("wins") or 0)
                total = int(row.get("total") or 0)
                if total >= 3:
                    win_rate = wins / total if total else 0
                    cur.execute(
                        """
                        SELECT COUNT(*) AS higher FROM (
                            SELECT p.user_id,
                                   SUM(CASE WHEN p.status = 'WON' THEN 1 ELSE 0 END) AS wins,
                                   SUM(CASE WHEN p.status IN ('WON','LOST') THEN 1 ELSE 0 END) AS total
                            FROM predictions p
                            WHERE p.status IN ('WON','LOST')
                            GROUP BY p.user_id HAVING SUM(CASE WHEN p.status IN ('WON','LOST') THEN 1 ELSE 0 END) >= 3
                        ) t WHERE (wins * 1.0 / total) > %s OR ((wins * 1.0 / total) = %s AND total > %s)
                        """,
                        (win_rate, win_rate, total),
                    )
                    higher = int((cur.fetchone() or {}).get("higher") or 0)
                    current_rank = higher + 1

    items = []
    for idx, r in enumerate(rows):
        wins = int(r.get("wins") or 0)
        total = int(r.get("total") or 0)
        win_rate = round((wins / total * 100), 1) if total else 0
        club_entry = resolve_club_entry(r.get("club"))
        items.append(
            {
                "rank": offset + idx + 1,
                "user_id": r["user_id"],
                "username": r.get("username") or "Unknown",
                "wins": wins,
                "total": total,
                "win_rate": win_rate,
                "club_label": (club_entry or {}).get("label"),
                "club_badge": (club_entry or {}).get("badge"),
            }
        )
    return {"items": items, "current_user_rank": current_rank}


def log_moderation(actor_id: int, target_id: int, action: str, reason: str = ""):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO moderation_audit (actor_id, target_id, action, reason) VALUES (%s, %s, %s, %s)",
                (actor_id, target_id, action, reason or ""),
            )
        conn.commit()


def warn_user(actor_id: int, target_id: int, reason: str = "") -> int:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET warning_count = warning_count + 1 WHERE user_id = %s", (target_id,))
            cur.execute("SELECT warning_count FROM users WHERE user_id = %s", (target_id,))
            row = cur.fetchone()
        conn.commit()
    log_moderation(actor_id, target_id, "warn", reason)
    return int(row.get("warning_count") or 0) if row else 0


def log_mute(actor_id: int, target_id: int, reason: str = ""):
    log_moderation(actor_id, target_id, "mute", reason)


def log_ban(actor_id: int, target_id: int, reason: str = ""):
    log_moderation(actor_id, target_id, "ban", reason)


def reset_warnings(user_id: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET warning_count = 0 WHERE user_id = %s", (user_id,))
        conn.commit()


# === Tracking / Rewards ===
def create_tracked_link(url: str, chat_id: int, message_id: int) -> int:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO posted_links (url, chat_id, message_id) VALUES (%s, %s, %s) RETURNING link_id",
                (url, chat_id, message_id),
            )
            row = cur.fetchone()
        conn.commit()
    return int(row.get("link_id"))


def record_link_click(user_id: int, link_id: int) -> bool:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO link_clicks (user_id, link_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (user_id, link_id),
            )
            inserted = cur.rowcount > 0
        conn.commit()
    return inserted


def has_user_clicked_link(user_id: int, link_id: int) -> bool:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM link_clicks WHERE user_id = %s AND link_id = %s", (user_id, link_id))
            return cur.fetchone() is not None


def record_reaction_reward(user_id: int, message_id: int, chat_id: int) -> bool:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO reaction_rewards (user_id, message_id, chat_id) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                (user_id, message_id, chat_id),
            )
            inserted = cur.rowcount > 0
        conn.commit()
    return inserted


def has_user_reacted(user_id: int, message_id: int) -> bool:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM reaction_rewards WHERE user_id = %s AND message_id = %s", (user_id, message_id))
            return cur.fetchone() is not None


# === Preferences / Notifications ===
def get_user_preferences(user_id: int) -> Dict[str, Any]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM user_preferences WHERE user_id = %s", (user_id,))
            prefs = cur.fetchone()
            if not prefs:
                cur.execute("INSERT INTO user_preferences (user_id) VALUES (%s)", (user_id,))
                cur.execute("SELECT * FROM user_preferences WHERE user_id = %s", (user_id,))
                prefs = cur.fetchone()
        conn.commit()
    return prefs or {}


def update_user_preference(user_id: int, pref_name: str, value: int):
    valid = ["match_reminders", "result_notifications", "daily_reminder", "prediction_updates", "favorite_sports"]
    if pref_name not in valid:
        return
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO user_preferences (user_id) VALUES (%s) ON CONFLICT DO NOTHING", (user_id,))
            cur.execute(
                f"UPDATE user_preferences SET {pref_name} = %s, updated_at = CURRENT_TIMESTAMP WHERE user_id = %s",
                (value, user_id),
            )
        conn.commit()


def get_users_for_notification(pref_name: str = "match_reminders") -> List[int]:
    valid = ["match_reminders", "result_notifications", "daily_reminder", "prediction_updates", "favorite_sports"]
    if pref_name not in valid:
        return []
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT u.user_id FROM users u
                LEFT JOIN user_preferences p ON u.user_id = p.user_id
                WHERE p.{pref_name} = 1 OR p.user_id IS NULL
                """
            )
            rows = cur.fetchall() or []
    return [int(r["user_id"]) for r in rows]


def get_result_notification_users(match_id: int) -> List[int]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT p.user_id FROM predictions p
                LEFT JOIN user_preferences up ON p.user_id = up.user_id
                WHERE p.match_id = %s AND (up.result_notifications = 1 OR up.user_id IS NULL)
                """,
                (match_id,),
            )
            rows = cur.fetchall() or []
    return [int(r["user_id"]) for r in rows]


# === Group tracking ===
def add_group(chat_id: int, title: str, chat_type: str):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO groups (chat_id, chat_title, chat_type) VALUES (%s, %s, %s) ON CONFLICT (chat_id) DO UPDATE SET chat_title = EXCLUDED.chat_title, chat_type = EXCLUDED.chat_type",
                (chat_id, title, chat_type),
            )
        conn.commit()


def remove_group(chat_id: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM groups WHERE chat_id = %s", (chat_id,))
        conn.commit()


def get_all_groups() -> List[int]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT chat_id FROM groups")
            rows = cur.fetchall() or []
    return [int(r["chat_id"]) for r in rows]


def get_groups() -> List[Dict[str, Any]]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT chat_id, chat_title, chat_type, sport_focus, added_at FROM groups")
            rows = cur.fetchall() or []
    items: List[Dict[str, Any]] = []
    for r in rows:
        items.append(
            {
                "chat_id": int(r["chat_id"]),
                "chat_title": r.get("chat_title") or "",
                "chat_type": r.get("chat_type") or "",
                "sport_focus": r.get("sport_focus"),
                "enabled": True,
            }
        )
    return items


def update_user_profile_raw(user_id: int, club: Optional[str] = None, interests: Optional[str] = None) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO users (user_id) VALUES (%s) ON CONFLICT DO NOTHING", (user_id,))
            if club is not None:
                cur.execute("UPDATE users SET club = %s WHERE user_id = %s", (club or None, user_id))
            if interests is not None:
                cur.execute("UPDATE users SET interests = %s WHERE user_id = %s", (interests, user_id))
        conn.commit()
    return get_user(user_id)


def get_feed_status(chat_id: int) -> Dict[str, Any]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT twitter_enabled, website_enabled, sport_filter FROM davesport_subscribers WHERE chat_id = %s",
                (chat_id,),
            )
            row = cur.fetchone()
    if not row:
        return {"subscribed": False, "twitter_enabled": False, "website_enabled": False, "sport_filter": "all"}
    return {
        "subscribed": True,
        "twitter_enabled": bool(row.get("twitter_enabled")),
        "website_enabled": bool(row.get("website_enabled")),
        "sport_filter": row.get("sport_filter") or "all",
    }


# === Dave.sport routing ===
def subscribe_chat(chat_id: int, twitter: bool = True, website: bool = True, sport_filter: str = "all"):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO davesport_subscribers (chat_id, twitter_enabled, website_enabled, sport_filter) VALUES (%s, %s, %s, %s) "
                "ON CONFLICT (chat_id) DO UPDATE SET twitter_enabled = EXCLUDED.twitter_enabled, website_enabled = EXCLUDED.website_enabled, sport_filter = EXCLUDED.sport_filter",
                (chat_id, 1 if twitter else 0, 1 if website else 0, sport_filter.lower()),
            )
        conn.commit()


def unsubscribe_chat(chat_id: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM davesport_subscribers WHERE chat_id = %s", (chat_id,))
        conn.commit()


def get_subscribed_chats() -> List[Dict[str, Any]]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT chat_id, twitter_enabled, website_enabled, sport_filter FROM davesport_subscribers WHERE chat_id < 0")
            rows = cur.fetchall() or []
    return [{"chat_id": r["chat_id"], "twitter": r["twitter_enabled"], "website": r["website_enabled"], "sport": r.get("sport_filter") or "all"} for r in rows]


def set_chat_category(chat_id: int, category: str, thread_id: Optional[int]):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO chat_category_routing (chat_id, category, thread_id, enabled) VALUES (%s, %s, %s, 1) "
                "ON CONFLICT (chat_id, category) DO UPDATE SET thread_id = EXCLUDED.thread_id, enabled = 1",
                (chat_id, category.lower(), thread_id),
            )
        conn.commit()


def remove_chat_category(chat_id: int, category: str):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM chat_category_routing WHERE chat_id = %s AND category = %s", (chat_id, category.lower()))
        conn.commit()


def get_chats_for_category(category: str) -> List[Dict[str, Any]]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT chat_id, thread_id FROM chat_category_routing WHERE category = %s AND enabled = 1 AND chat_id < 0",
                (category.lower(),),
            )
            rows = cur.fetchall() or []
    return [{"chat_id": r["chat_id"], "thread_id": r["thread_id"]} for r in rows]


def get_match_predictions(match_id: int) -> List[Dict[str, Any]]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT p.user_id,
                       u.username,
                       u.club,
                       p.prediction,
                       p.pred_score_a,
                       p.pred_score_b,
                       p.status
                FROM predictions p
                LEFT JOIN users u ON p.user_id = u.user_id
                WHERE p.match_id = %s
                ORDER BY p.user_id ASC
                """,
                (match_id,),
            )
            rows = cur.fetchall() or []
    items: List[Dict[str, Any]] = []
    for r in rows:
        club_entry = resolve_club_entry(r.get("club"))
        items.append(
            {
                "user_id": int(r.get("user_id")),
                "username": r.get("username"),
                "prediction": r.get("prediction"),
                "pred_score_a": r.get("pred_score_a"),
                "pred_score_b": r.get("pred_score_b"),
                "status": r.get("status"),
                "club_label": (club_entry or {}).get("label"),
                "club_badge": (club_entry or {}).get("badge"),
            }
        )
    return items


def get_chat_categories(chat_id: int) -> List[Dict[str, Any]]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT category, thread_id FROM chat_category_routing WHERE chat_id = %s AND enabled = 1", (chat_id,))
            rows = cur.fetchall() or []
    return [{"category": r["category"], "thread_id": r["thread_id"]} for r in rows]


def is_post_sent(post_id: str, chat_id: int) -> bool:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM davesport_posts WHERE post_id = %s AND chat_id = %s", (post_id, chat_id))
            return cur.fetchone() is not None


def mark_post_sent(post_id: str, chat_id: int, source: str, message_id: int = 0):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO davesport_posts (post_id, chat_id, source, message_id) VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
                (post_id, chat_id, source, message_id),
            )
        conn.commit()
