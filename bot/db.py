"""SQLite 저장소. 서버(guild)별로 데이터를 분리한다."""
from __future__ import annotations

import json
import time
from typing import Any

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS characters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    owner_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    avatar_url TEXT,
    stats TEXT NOT NULL DEFAULT '{}',
    skills TEXT NOT NULL DEFAULT '{}',
    resources TEXT NOT NULL DEFAULT '{}',
    notes TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    UNIQUE (guild_id, owner_id, name)
);
CREATE TABLE IF NOT EXISTS active_character (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    character_id INTEGER NOT NULL,
    PRIMARY KEY (guild_id, user_id)
);
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    gm_id INTEGER NOT NULL,
    scene TEXT NOT NULL DEFAULT '',
    initiative TEXT NOT NULL DEFAULT '{}',
    started_at REAL NOT NULL,
    ended_at REAL
);
CREATE TABLE IF NOT EXISTS session_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    ts REAL NOT NULL,
    kind TEXT NOT NULL,
    author TEXT NOT NULL,
    content TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS npcs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    avatar_url TEXT,
    description TEXT NOT NULL DEFAULT '',
    UNIQUE (guild_id, name)
);
CREATE TABLE IF NOT EXISTS lore_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    category TEXT NOT NULL,
    name TEXT NOT NULL,
    body TEXT NOT NULL,
    tags TEXT NOT NULL DEFAULT '[]',
    author_id INTEGER NOT NULL,
    UNIQUE (guild_id, name)
);
"""

_JSON_COLS = ("stats", "skills", "resources", "initiative", "tags")


def _row(row: aiosqlite.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    d = dict(row)
    for col in _JSON_COLS:
        if col in d and isinstance(d[col], str):
            d[col] = json.loads(d[col])
    return d


class Database:
    def __init__(self, path: str):
        self.path = path
        self.conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self.conn = await aiosqlite.connect(self.path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.executescript(SCHEMA)
        await self.conn.commit()

    async def close(self) -> None:
        if self.conn:
            await self.conn.close()

    async def _one(self, sql: str, args: tuple = ()) -> dict | None:
        async with self.conn.execute(sql, args) as cur:
            return _row(await cur.fetchone())

    async def _all(self, sql: str, args: tuple = ()) -> list[dict]:
        async with self.conn.execute(sql, args) as cur:
            return [_row(r) for r in await cur.fetchall()]

    async def _exec(self, sql: str, args: tuple = ()) -> int:
        cur = await self.conn.execute(sql, args)
        await self.conn.commit()
        return cur.lastrowid if cur.lastrowid else cur.rowcount

    # ---------- 캐릭터 ----------
    async def create_character(self, guild_id: int, owner_id: int, name: str,
                               stats: dict, resources: dict) -> int:
        cid = await self._exec(
            "INSERT INTO characters (guild_id, owner_id, name, stats, skills, resources, created_at)"
            " VALUES (?, ?, ?, ?, '{}', ?, ?)",
            (guild_id, owner_id, name, json.dumps(stats, ensure_ascii=False),
             json.dumps(resources, ensure_ascii=False), time.time()),
        )
        await self.set_active(guild_id, owner_id, cid)
        return cid

    async def get_character(self, cid: int) -> dict | None:
        return await self._one("SELECT * FROM characters WHERE id = ?", (cid,))

    async def find_character(self, guild_id: int, owner_id: int, name: str) -> dict | None:
        return await self._one(
            "SELECT * FROM characters WHERE guild_id = ? AND owner_id = ? AND name = ?",
            (guild_id, owner_id, name),
        )

    async def list_characters(self, guild_id: int, owner_id: int | None = None) -> list[dict]:
        if owner_id is None:
            return await self._all("SELECT * FROM characters WHERE guild_id = ? ORDER BY name", (guild_id,))
        return await self._all(
            "SELECT * FROM characters WHERE guild_id = ? AND owner_id = ? ORDER BY name",
            (guild_id, owner_id),
        )

    async def update_character(self, cid: int, **fields: Any) -> None:
        if not fields:
            return
        cols, vals = [], []
        for k, v in fields.items():
            cols.append(f"{k} = ?")
            vals.append(json.dumps(v, ensure_ascii=False) if k in _JSON_COLS else v)
        await self._exec(f"UPDATE characters SET {', '.join(cols)} WHERE id = ?", (*vals, cid))

    async def delete_character(self, cid: int) -> None:
        await self._exec("DELETE FROM characters WHERE id = ?", (cid,))
        await self._exec("DELETE FROM active_character WHERE character_id = ?", (cid,))

    async def set_active(self, guild_id: int, user_id: int, cid: int) -> None:
        await self._exec(
            "INSERT INTO active_character (guild_id, user_id, character_id) VALUES (?, ?, ?)"
            " ON CONFLICT (guild_id, user_id) DO UPDATE SET character_id = excluded.character_id",
            (guild_id, user_id, cid),
        )

    async def get_active(self, guild_id: int, user_id: int) -> dict | None:
        return await self._one(
            "SELECT c.* FROM characters c JOIN active_character a ON a.character_id = c.id"
            " WHERE a.guild_id = ? AND a.user_id = ?",
            (guild_id, user_id),
        )

    # ---------- 세션 ----------
    async def start_session(self, guild_id: int, channel_id: int, name: str, gm_id: int) -> int:
        return await self._exec(
            "INSERT INTO sessions (guild_id, channel_id, name, gm_id, started_at) VALUES (?, ?, ?, ?, ?)",
            (guild_id, channel_id, name, gm_id, time.time()),
        )

    async def active_session(self, channel_id: int) -> dict | None:
        return await self._one(
            "SELECT * FROM sessions WHERE channel_id = ? AND ended_at IS NULL ORDER BY id DESC LIMIT 1",
            (channel_id,),
        )

    async def all_active_sessions(self) -> list[dict]:
        return await self._all("SELECT * FROM sessions WHERE ended_at IS NULL")

    async def end_session(self, session_id: int) -> None:
        await self._exec("UPDATE sessions SET ended_at = ? WHERE id = ?", (time.time(), session_id))

    async def update_session(self, session_id: int, **fields: Any) -> None:
        cols, vals = [], []
        for k, v in fields.items():
            cols.append(f"{k} = ?")
            vals.append(json.dumps(v, ensure_ascii=False) if k in _JSON_COLS else v)
        await self._exec(f"UPDATE sessions SET {', '.join(cols)} WHERE id = ?", (*vals, session_id))

    async def log(self, session_id: int, kind: str, author: str, content: str) -> None:
        await self._exec(
            "INSERT INTO session_logs (session_id, ts, kind, author, content) VALUES (?, ?, ?, ?, ?)",
            (session_id, time.time(), kind, author, content),
        )

    async def get_logs(self, session_id: int) -> list[dict]:
        return await self._all("SELECT * FROM session_logs WHERE session_id = ? ORDER BY id", (session_id,))

    # ---------- NPC ----------
    async def upsert_npc(self, guild_id: int, name: str, avatar_url: str | None, description: str) -> None:
        await self._exec(
            "INSERT INTO npcs (guild_id, name, avatar_url, description) VALUES (?, ?, ?, ?)"
            " ON CONFLICT (guild_id, name) DO UPDATE SET avatar_url = excluded.avatar_url,"
            " description = excluded.description",
            (guild_id, name, avatar_url, description),
        )

    async def get_npc(self, guild_id: int, name: str) -> dict | None:
        return await self._one("SELECT * FROM npcs WHERE guild_id = ? AND name = ?", (guild_id, name))

    async def list_npcs(self, guild_id: int) -> list[dict]:
        return await self._all("SELECT * FROM npcs WHERE guild_id = ? ORDER BY name", (guild_id,))

    async def delete_npc(self, guild_id: int, name: str) -> int:
        cur = await self.conn.execute("DELETE FROM npcs WHERE guild_id = ? AND name = ?", (guild_id, name))
        await self.conn.commit()
        return cur.rowcount

    # ---------- 도감 ----------
    async def upsert_lore(self, guild_id: int, category: str, name: str, body: str,
                          tags: list[str], author_id: int) -> None:
        await self._exec(
            "INSERT INTO lore_entries (guild_id, category, name, body, tags, author_id) VALUES (?, ?, ?, ?, ?, ?)"
            " ON CONFLICT (guild_id, name) DO UPDATE SET category = excluded.category,"
            " body = excluded.body, tags = excluded.tags, author_id = excluded.author_id",
            (guild_id, category, name, body, json.dumps(tags, ensure_ascii=False), author_id),
        )

    async def list_lore(self, guild_id: int) -> list[dict]:
        return await self._all("SELECT * FROM lore_entries WHERE guild_id = ? ORDER BY category, name", (guild_id,))

    async def delete_lore(self, guild_id: int, name: str) -> int:
        cur = await self.conn.execute("DELETE FROM lore_entries WHERE guild_id = ? AND name = ?", (guild_id, name))
        await self.conn.commit()
        return cur.rowcount
