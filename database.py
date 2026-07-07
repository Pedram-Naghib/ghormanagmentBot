"""
database.py
-------------
Direct asyncpg connection to your Supabase Postgres database (bypassing the
Supabase REST/PostgREST layer entirely - lower latency, no REST rate
limits, full SQL control). This is the ONLY file that talks to the
database - every handler goes through the `Database` class methods below.

Table creation lives in connect() below and runs once at bot startup (see
bot.py) - there's no separate schema.sql to run manually anymore; this file
IS the schema.

--------------------------------------------------------------------------
ROLE MODEL - single `role` column on group_users, scoped per (chat_id, user_id)
--------------------------------------------------------------------------
    'owner'  -> whoever added the bot to this specific group. Auto-set by
                handlers/tracking.py the moment the bot joins.
    'admin'  -> appointed by that group's owner (or a Global Owner).
    'vip'    -> exempt from anti-spam restrictions, in this group only.
    'normal' -> default for everyone else.

Global Owners (OWNER_USER_IDS in .env) are NOT stored in the database at
all - they're an env-level bootstrap checked in utils/permissions.py, so
they always work regardless of database state.
"""

from datetime import datetime
from typing import List, Optional, Tuple

import asyncpg

from config import (
    DB_HOST,
    DB_NAME,
    DB_PASSWORD,
    DB_PORT,
    DB_USER,
    DEFAULT_SPAM_MESSAGE_LIMIT,
    DEFAULT_SPAM_MUTE_MINUTES,
    DEFAULT_SPAM_TIME_WINDOW_SECONDS,
    STATS_TOP_N,
)


class Database:
    def __init__(self):
        self.pool: Optional[asyncpg.Pool] = None

    async def connect(self):
        if not DB_HOST or not DB_PASSWORD:
            raise RuntimeError(
                "DB_HOST / DB_PASSWORD are not set. Copy .env.example to .env and fill in "
                "your Supabase Postgres connection details (Project Settings -> Database)."
            )
        self.pool = await asyncpg.create_pool(
            user=DB_USER,
            password=DB_PASSWORD,
            host=DB_HOST,
            port=DB_PORT,
            database=DB_NAME,
            min_size=2,
            max_size=10,
            ssl="require",
            # If you point DB_PORT at Supabase's pooler (6543 / pgbouncer
            # transaction mode) instead of the direct connection (5432),
            # uncomment this - pgbouncer transaction mode can't handle
            # asyncpg's prepared statement cache:
            # statement_cache_size=0,
        )
        await self._init_schema()

    async def close(self):
        if self.pool is not None:
            await self.pool.close()
            self.pool = None

    async def _init_schema(self):
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS group_users (
                    chat_id BIGINT,
                    user_id BIGINT,
                    first_name TEXT,
                    last_name TEXT,
                    username TEXT,
                    role TEXT NOT NULL DEFAULT 'normal',  -- 'normal' | 'vip' | 'admin' | 'owner'
                    messages_all_time INT NOT NULL DEFAULT 0,
                    members_added_count INT NOT NULL DEFAULT 0,
                    joined_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    PRIMARY KEY (chat_id, user_id)
                );
                """
            )
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS message_logs (
                    id BIGSERIAL PRIMARY KEY,
                    chat_id BIGINT NOT NULL,
                    user_id BIGINT NOT NULL,
                    sent_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                """
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_msg_logs_chat_user_time "
                "ON message_logs (chat_id, user_id, sent_at);"
            )
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS member_logs (
                    id BIGSERIAL PRIMARY KEY,
                    chat_id BIGINT NOT NULL,
                    adder_id BIGINT NOT NULL,
                    new_member_id BIGINT NOT NULL,
                    added_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                """
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_member_logs_chat_adder_time "
                "ON member_logs (chat_id, adder_id, added_at);"
            )
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_settings (
                    chat_id BIGINT PRIMARY KEY,
                    spam_message_limit INT NOT NULL DEFAULT 6,
                    spam_time_window_seconds INT NOT NULL DEFAULT 8,
                    spam_mute_minutes INT NOT NULL DEFAULT 30
                );
                """
            )

    # ---------------------------------------------------------------- #
    # USERS / PROFILE  (all scoped per chat_id, since group_users is)
    # ---------------------------------------------------------------- #

    async def upsert_user(
        self,
        chat_id: int,
        user_id: int,
        username: Optional[str],
        first_name: Optional[str],
        last_name: Optional[str],
    ):
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO group_users (chat_id, user_id, username, first_name, last_name)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (chat_id, user_id) DO UPDATE
                    SET username = EXCLUDED.username,
                        first_name = EXCLUDED.first_name,
                        last_name = EXCLUDED.last_name
                """,
                chat_id, user_id, username, first_name, last_name,
            )

    async def get_user_display_name(self, chat_id: int, user_id: int) -> str:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT username, first_name, last_name FROM group_users WHERE chat_id=$1 AND user_id=$2",
                chat_id, user_id,
            )
        if not row:
            return str(user_id)
        name = " ".join(filter(None, [row["first_name"], row["last_name"]])).strip()
        return name or (f"@{row['username']}" if row["username"] else str(user_id))

    async def get_user_id_by_username(self, username: str) -> Optional[int]:
        """Look up a numeric user_id by @username (case-insensitive), across any chat."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT user_id FROM group_users WHERE username ILIKE $1 LIMIT 1", username
            )
        return row["user_id"] if row else None

    # ---------------------------------------------------------------- #
    # ROLES: owner / admin / vip / normal
    # ---------------------------------------------------------------- #

    async def get_user_role(self, chat_id: int, user_id: int) -> str:
        async with self.pool.acquire() as conn:
            role = await conn.fetchval(
                "SELECT role FROM group_users WHERE chat_id=$1 AND user_id=$2", chat_id, user_id
            )
        return role or "normal"

    async def set_user_role(
        self,
        chat_id: int,
        user_id: int,
        role: str,
        username: Optional[str] = None,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
    ):
        """Upsert - also creates the row if this user hasn't been seen in this chat yet."""
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO group_users (chat_id, user_id, username, first_name, last_name, role)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (chat_id, user_id) DO UPDATE SET role = EXCLUDED.role
                """,
                chat_id, user_id, username, first_name, last_name, role,
            )

    async def list_users_by_role(self, chat_id: int, role: str) -> List[int]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT user_id FROM group_users WHERE chat_id=$1 AND role=$2", chat_id, role
            )
        return [r["user_id"] for r in rows]

    async def get_chat_owner(self, chat_id: int) -> Optional[int]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT user_id FROM group_users WHERE chat_id=$1 AND role='owner' LIMIT 1", chat_id
            )
        return row["user_id"] if row else None

    # ---------------------------------------------------------------- #
    # MESSAGE TRACKING
    # ---------------------------------------------------------------- #

    async def log_message(self, chat_id: int, user_id: int):
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """
                    INSERT INTO group_users (chat_id, user_id, messages_all_time)
                    VALUES ($1, $2, 1)
                    ON CONFLICT (chat_id, user_id) DO UPDATE
                        SET messages_all_time = group_users.messages_all_time + 1
                    """,
                    chat_id, user_id,
                )
                await conn.execute(
                    "INSERT INTO message_logs (chat_id, user_id) VALUES ($1, $2)", chat_id, user_id
                )

    async def get_user_message_count(
        self, chat_id: int, user_id: int, since: Optional[datetime] = None
    ) -> int:
        async with self.pool.acquire() as conn:
            if since is None:
                value = await conn.fetchval(
                    "SELECT messages_all_time FROM group_users WHERE chat_id=$1 AND user_id=$2",
                    chat_id, user_id,
                )
                return value or 0
            return await conn.fetchval(
                "SELECT COUNT(*) FROM message_logs WHERE chat_id=$1 AND user_id=$2 AND sent_at >= $3",
                chat_id, user_id, since,
            )

    # ---------------------------------------------------------------- #
    # MEMBER-ADDED TRACKING
    # ---------------------------------------------------------------- #

    async def log_member_added(self, chat_id: int, adder_id: int, new_member_id: int):
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """
                    INSERT INTO group_users (chat_id, user_id, members_added_count)
                    VALUES ($1, $2, 1)
                    ON CONFLICT (chat_id, user_id) DO UPDATE
                        SET members_added_count = group_users.members_added_count + 1
                    """,
                    chat_id, adder_id,
                )
                await conn.execute(
                    "INSERT INTO member_logs (chat_id, adder_id, new_member_id) VALUES ($1, $2, $3)",
                    chat_id, adder_id, new_member_id,
                )

    # ---------------------------------------------------------------- #
    # AGGREGATE STATS (آمار روزانه / آمار کل)
    # ---------------------------------------------------------------- #

    async def get_top_message_senders(
        self, chat_id: int, since: Optional[datetime] = None, limit: int = STATS_TOP_N
    ) -> List[Tuple[int, int]]:
        async with self.pool.acquire() as conn:
            if since is None:
                rows = await conn.fetch(
                    """
                    SELECT user_id, messages_all_time AS c FROM group_users
                    WHERE chat_id=$1 AND messages_all_time > 0
                    ORDER BY c DESC LIMIT $2
                    """,
                    chat_id, limit,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT user_id, COUNT(*) AS c FROM message_logs
                    WHERE chat_id=$1 AND sent_at >= $2
                    GROUP BY user_id ORDER BY c DESC LIMIT $3
                    """,
                    chat_id, since, limit,
                )
        return [(r["user_id"], r["c"]) for r in rows]

    async def get_top_adders(
        self, chat_id: int, since: Optional[datetime] = None, limit: int = STATS_TOP_N
    ) -> List[Tuple[int, int]]:
        async with self.pool.acquire() as conn:
            if since is None:
                rows = await conn.fetch(
                    """
                    SELECT user_id, members_added_count AS c FROM group_users
                    WHERE chat_id=$1 AND members_added_count > 0
                    ORDER BY c DESC LIMIT $2
                    """,
                    chat_id, limit,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT adder_id AS user_id, COUNT(*) AS c FROM member_logs
                    WHERE chat_id=$1 AND added_at >= $2
                    GROUP BY adder_id ORDER BY c DESC LIMIT $3
                    """,
                    chat_id, since, limit,
                )
        return [(r["user_id"], r["c"]) for r in rows]

    # ---------------------------------------------------------------- #
    # PER-CHAT ANTI-SPAM SETTINGS (admins tune these live, no .env edits)
    # ---------------------------------------------------------------- #

    async def get_chat_settings(self, chat_id: int) -> dict:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM chat_settings WHERE chat_id=$1", chat_id)
        if row:
            return {
                "spam_message_limit": row["spam_message_limit"],
                "spam_time_window_seconds": row["spam_time_window_seconds"],
                "spam_mute_minutes": row["spam_mute_minutes"],
            }
        return {
            "spam_message_limit": DEFAULT_SPAM_MESSAGE_LIMIT,
            "spam_time_window_seconds": DEFAULT_SPAM_TIME_WINDOW_SECONDS,
            "spam_mute_minutes": DEFAULT_SPAM_MUTE_MINUTES,
        }

    async def set_chat_settings(
        self, chat_id: int, spam_message_limit: int, spam_time_window_seconds: int, spam_mute_minutes: int
    ):
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO chat_settings (chat_id, spam_message_limit, spam_time_window_seconds, spam_mute_minutes)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (chat_id) DO UPDATE SET
                    spam_message_limit = EXCLUDED.spam_message_limit,
                    spam_time_window_seconds = EXCLUDED.spam_time_window_seconds,
                    spam_mute_minutes = EXCLUDED.spam_mute_minutes
                """,
                chat_id, spam_message_limit, spam_time_window_seconds, spam_mute_minutes,
            )