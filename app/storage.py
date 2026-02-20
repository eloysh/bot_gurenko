from __future__ import annotations
import aiosqlite
from dataclasses import dataclass
from typing import Optional, Dict, Any
from datetime import datetime

@dataclass
class User:
    tg_id: int
    username: Optional[str]
    first_name: Optional[str]
    credits_free: int
    credits_pro: int
    referred_by: Optional[int]

class Storage:
    def __init__(self, db_path: str):
        self.db_path = db_path

    async def init(self):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                tg_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                credits_free INTEGER NOT NULL DEFAULT 0,
                credits_pro INTEGER NOT NULL DEFAULT 0,
                referred_by INTEGER,
                created_at TEXT NOT NULL
            );
            """)
            await db.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tg_id INTEGER NOT NULL,
                kind TEXT NOT NULL, -- chat/image/video
                request_id TEXT,
                status TEXT NOT NULL,
                payload_json TEXT,
                created_at TEXT NOT NULL
            );
            """)
            await db.commit()

    async def get_user(self, tg_id: int) -> Optional[User]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT * FROM users WHERE tg_id=?", (tg_id,))
            row = await cur.fetchone()
            if not row:
                return None
            return User(
                tg_id=row["tg_id"],
                username=row["username"],
                first_name=row["first_name"],
                credits_free=row["credits_free"],
                credits_pro=row["credits_pro"],
                referred_by=row["referred_by"],
            )

    async def upsert_user(self, tg_id: int, username: Optional[str], first_name: Optional[str], credits_free: int, referred_by: Optional[int]):
        async with aiosqlite.connect(self.db_path) as db:
            now = datetime.utcnow().isoformat()
            await db.execute(
                """
                INSERT INTO users (tg_id, username, first_name, credits_free, credits_pro, referred_by, created_at)
                VALUES (?, ?, ?, ?, 0, ?, ?)
                ON CONFLICT(tg_id) DO UPDATE SET
                    username=excluded.username,
                    first_name=excluded.first_name
                """,
                (tg_id, username, first_name, credits_free, referred_by, now),
            )
            await db.commit()

    async def add_credits(self, tg_id: int, free_delta: int = 0, pro_delta: int = 0):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE users SET credits_free = credits_free + ?, credits_pro = credits_pro + ? WHERE tg_id=?",
                (free_delta, pro_delta, tg_id),
            )
            await db.commit()

    async def consume_credit(self, tg_id: int) -> bool:
        """Consume one credit. Prefer PRO credits, then free. Return True if consumed."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT credits_pro, credits_free FROM users WHERE tg_id=?", (tg_id,))
            row = await cur.fetchone()
            if not row:
                return False
            pro = row["credits_pro"]
            free = row["credits_free"]
            if pro > 0:
                await db.execute("UPDATE users SET credits_pro = credits_pro - 1 WHERE tg_id=?", (tg_id,))
                await db.commit()
                return True
            if free > 0:
                await db.execute("UPDATE users SET credits_free = credits_free - 1 WHERE tg_id=?", (tg_id,))
                await db.commit()
                return True
            return False
