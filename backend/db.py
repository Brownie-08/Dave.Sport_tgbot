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
    # Schema should match async_database.py largely, but we rely on the bot to init it mostly.
    # However, we can ensure tables exist.
    # For now, since we are piggybacking on the bot's DB, we assume it's initialized.
    pass