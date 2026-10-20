"""SQLite 消息落库：实时监控所有群消息"""

import sqlite3
import threading
import time


class Storage:
    def __init__(self, db_path: str):
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self):
        with self._lock:
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts INTEGER NOT NULL,
                    msg_id INTEGER,
                    room TEXT,
                    sender_wxid TEXT,
                    sender_name TEXT,
                    kind TEXT,
                    content TEXT,
                    media_path TEXT,
                    at_me INTEGER DEFAULT 0,
                    replied INTEGER DEFAULT 0
                )
            """)
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_msg_room ON messages(room, ts)")
            self._conn.commit()

    def log(self, room: str, sender_wxid: str, sender_name: str, kind: str,
            content: str, msg_id: int = 0, media_path: str = "",
            at_me: bool = False, replied: bool = False):
        with self._lock:
            self._conn.execute(
                "INSERT INTO messages (ts, msg_id, room, sender_wxid, sender_name,"
                " kind, content, media_path, at_me, replied)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                (int(time.time()), msg_id, room, sender_wxid, sender_name,
                 kind, content[:4000], media_path, int(at_me), int(replied)),
            )
            self._conn.commit()

    def stats(self) -> dict:
        with self._lock:
            total = self._conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
            today = self._conn.execute(
                "SELECT COUNT(*) FROM messages WHERE ts > ?", (int(time.time()) - 86400,)
            ).fetchone()[0]
        return {"total": total, "today": today}

    def recent(self, room: str, limit: int = 20) -> list:
        with self._lock:
            cur = self._conn.execute(
                "SELECT ts, sender_name, kind, content FROM messages"
                " WHERE room=? ORDER BY id DESC LIMIT ?", (room, limit))
            return cur.fetchall()
