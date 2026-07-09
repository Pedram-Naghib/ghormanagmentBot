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
            # message_id is needed so "حذف {عدد}"/"حذف کل" (bulk delete) can
            # actually find which real Telegram messages to delete. Only
            # rows logged AFTER this column existed will have it populated -
            # older rows (and any message sent before the bot ever saw it)
            # stay NULL and are simply skipped, since a bot can only ever
            # delete messages it has actually observed (Telegram gives bots
            # no "list this chat's history" API).
            await conn.execute(
                "ALTER TABLE message_logs ADD COLUMN IF NOT EXISTS message_id BIGINT;"
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_msg_logs_chat_time_id "
                "ON message_logs (chat_id, sent_at, message_id);"
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
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS bot_assets (
                    key TEXT PRIMARY KEY,
                    file_id TEXT NOT NULL,
                    set_by BIGINT,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                """
            )

            # --- Welcome/goodbye columns on chat_settings (migration-safe:
            # ADD COLUMN IF NOT EXISTS works fine on a table that already
            # exists in production from earlier versions). ---
            await conn.execute(
                "ALTER TABLE chat_settings ADD COLUMN IF NOT EXISTS welcome_enabled BOOLEAN NOT NULL DEFAULT TRUE;"
            )
            await conn.execute(
                "ALTER TABLE chat_settings ADD COLUMN IF NOT EXISTS welcome_text TEXT;"
            )
            await conn.execute(
                "ALTER TABLE chat_settings ADD COLUMN IF NOT EXISTS goodbye_enabled BOOLEAN NOT NULL DEFAULT TRUE;"
            )
            await conn.execute(
                "ALTER TABLE chat_settings ADD COLUMN IF NOT EXISTS goodbye_text TEXT;"
            )
            await conn.execute(
                "ALTER TABLE chat_settings ADD COLUMN IF NOT EXISTS welcome_media_file_id TEXT;"
            )
            await conn.execute(
                "ALTER TABLE chat_settings ADD COLUMN IF NOT EXISTS welcome_media_type TEXT;"
            )
            await conn.execute(
                "ALTER TABLE chat_settings ADD COLUMN IF NOT EXISTS goodbye_media_file_id TEXT;"
            )
            await conn.execute(
                "ALTER TABLE chat_settings ADD COLUMN IF NOT EXISTS goodbye_media_type TEXT;"
            )
            await conn.execute(
                "ALTER TABLE chat_settings ADD COLUMN IF NOT EXISTS join_captcha_enabled BOOLEAN NOT NULL DEFAULT FALSE;"
            )

            # --- Per-chat content-type locks (پنل -> قفل‌ها). Unknown/missing
            # keys fall back to DEFAULT_LOCK_STATE below, so adding a brand
            # new lock type later never requires a migration. ---
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_locks (
                    chat_id BIGINT NOT NULL,
                    lock_key TEXT NOT NULL,
                    enabled BOOLEAN NOT NULL DEFAULT FALSE,
                    PRIMARY KEY (chat_id, lock_key)
                );
                """
            )

            # --- Filtered words (فیلتر کلمات) ---
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS filtered_words (
                    chat_id BIGINT NOT NULL,
                    word TEXT NOT NULL,
                    added_by BIGINT,
                    added_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    PRIMARY KEY (chat_id, word)
                );
                """
            )

            # --- Warnings (اخطار) ---
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS warnings (
                    id BIGSERIAL PRIMARY KEY,
                    chat_id BIGINT NOT NULL,
                    user_id BIGINT NOT NULL,
                    warned_by BIGINT,
                    reason TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                """
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_warnings_chat_user ON warnings (chat_id, user_id);"
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

    async def log_message(self, chat_id: int, user_id: int, message_id: Optional[int] = None):
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
                    "INSERT INTO message_logs (chat_id, user_id, message_id) VALUES ($1, $2, $3)",
                    chat_id, user_id, message_id,
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

    async def get_recent_message_ids(self, chat_id: int, limit: int) -> List[int]:
        """Most recent `limit` message_ids the bot has actually logged for
        this chat (newest first), skipping rows from before this column
        existed (message_id IS NULL there - see _init_schema)."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT message_id FROM message_logs
                WHERE chat_id=$1 AND message_id IS NOT NULL
                ORDER BY sent_at DESC LIMIT $2
                """,
                chat_id, limit,
            )
        return [r["message_id"] for r in rows]

    async def get_all_logged_message_ids(self, chat_id: int) -> List[int]:
        """Every message_id the bot has ever logged for this chat - used by
        «حذف کل». NOTE: this can only ever cover messages sent since the bot
        started logging them; Telegram gives bots no way to enumerate a
        chat's full history from before that."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT message_id FROM message_logs WHERE chat_id=$1 AND message_id IS NOT NULL",
                chat_id,
            )
        return [r["message_id"] for r in rows]

    async def delete_logged_messages(self, chat_id: int, message_ids: List[int]):
        """Removes the log rows for message_ids we just deleted from Telegram,
        so a repeated «حذف کل» doesn't try to re-delete the same ids."""
        if not message_ids:
            return
        async with self.pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM message_logs WHERE chat_id=$1 AND message_id = ANY($2::bigint[])",
                chat_id, message_ids,
            )

    async def get_recently_joined_members(self, chat_id: int, since: datetime) -> List[Tuple[int, datetime]]:
        """[(user_id, joined_at), ...] for members who joined this chat at/after `since`."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT user_id, joined_at FROM group_users
                WHERE chat_id=$1 AND joined_at >= $2
                ORDER BY joined_at DESC
                """,
                chat_id, since,
            )
        return [(r["user_id"], r["joined_at"]) for r in rows]

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

    async def get_recently_added_members(
        self, chat_id: int, since: datetime, limit: int = 20
    ) -> List[Tuple[int, datetime]]:
        """Members who JOINED this chat since `since` (newest first) - used
        by the پروفایل screen's "اعضای تازه اضافه‌شده" panel."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT new_member_id AS user_id, added_at FROM member_logs
                WHERE chat_id=$1 AND added_at >= $2
                ORDER BY added_at DESC LIMIT $3
                """,
                chat_id, since, limit,
            )
        return [(r["user_id"], r["added_at"]) for r in rows]

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
                "welcome_enabled": row["welcome_enabled"],
                "welcome_text": row["welcome_text"],
                "welcome_media_file_id": row["welcome_media_file_id"],
                "welcome_media_type": row["welcome_media_type"],
                "goodbye_enabled": row["goodbye_enabled"],
                "goodbye_text": row["goodbye_text"],
                "goodbye_media_file_id": row["goodbye_media_file_id"],
                "goodbye_media_type": row["goodbye_media_type"],
                "join_captcha_enabled": row["join_captcha_enabled"],
            }
        return {
            "spam_message_limit": DEFAULT_SPAM_MESSAGE_LIMIT,
            "spam_time_window_seconds": DEFAULT_SPAM_TIME_WINDOW_SECONDS,
            "spam_mute_minutes": DEFAULT_SPAM_MUTE_MINUTES,
            "welcome_enabled": True,
            "welcome_text": None,
            "welcome_media_file_id": None,
            "welcome_media_type": None,
            "goodbye_enabled": True,
            "goodbye_text": None,
            "goodbye_media_file_id": None,
            "goodbye_media_type": None,
            "join_captcha_enabled": False,
        }

    async def _ensure_chat_settings_row(self, conn, chat_id: int):
        await conn.execute(
            "INSERT INTO chat_settings (chat_id) VALUES ($1) ON CONFLICT (chat_id) DO NOTHING", chat_id
        )

    async def set_welcome_settings(
        self,
        chat_id: int,
        *,
        enabled: Optional[bool] = None,
        text: Optional[str] = None,
        clear_media: bool = False,
        media_file_id: Optional[str] = None,
        media_type: Optional[str] = None,
    ):
        """Update only the fields that were actually passed in (None = leave unchanged)."""
        async with self.pool.acquire() as conn:
            await self._ensure_chat_settings_row(conn, chat_id)
            if enabled is not None:
                await conn.execute(
                    "UPDATE chat_settings SET welcome_enabled=$2 WHERE chat_id=$1", chat_id, enabled
                )
            if text is not None:
                await conn.execute(
                    "UPDATE chat_settings SET welcome_text=$2 WHERE chat_id=$1", chat_id, text
                )
            if clear_media:
                await conn.execute(
                    "UPDATE chat_settings SET welcome_media_file_id=NULL, welcome_media_type=NULL WHERE chat_id=$1",
                    chat_id,
                )
            elif media_file_id is not None:
                await conn.execute(
                    "UPDATE chat_settings SET welcome_media_file_id=$2, welcome_media_type=$3 WHERE chat_id=$1",
                    chat_id, media_file_id, media_type,
                )

    async def set_goodbye_settings(
        self,
        chat_id: int,
        *,
        enabled: Optional[bool] = None,
        text: Optional[str] = None,
        clear_media: bool = False,
        media_file_id: Optional[str] = None,
        media_type: Optional[str] = None,
    ):
        async with self.pool.acquire() as conn:
            await self._ensure_chat_settings_row(conn, chat_id)
            if enabled is not None:
                await conn.execute(
                    "UPDATE chat_settings SET goodbye_enabled=$2 WHERE chat_id=$1", chat_id, enabled
                )
            if text is not None:
                await conn.execute(
                    "UPDATE chat_settings SET goodbye_text=$2 WHERE chat_id=$1", chat_id, text
                )
            if clear_media:
                await conn.execute(
                    "UPDATE chat_settings SET goodbye_media_file_id=NULL, goodbye_media_type=NULL WHERE chat_id=$1",
                    chat_id,
                )
            elif media_file_id is not None:
                await conn.execute(
                    "UPDATE chat_settings SET goodbye_media_file_id=$2, goodbye_media_type=$3 WHERE chat_id=$1",
                    chat_id, media_file_id, media_type,
                )

    async def set_spam_limit(self, chat_id: int, limit: int):
        async with self.pool.acquire() as conn:
            await self._ensure_chat_settings_row(conn, chat_id)
            await conn.execute(
                "UPDATE chat_settings SET spam_message_limit=$2 WHERE chat_id=$1", chat_id, limit
            )

    async def set_spam_mute_minutes(self, chat_id: int, minutes: int):
        async with self.pool.acquire() as conn:
            await self._ensure_chat_settings_row(conn, chat_id)
            await conn.execute(
                "UPDATE chat_settings SET spam_mute_minutes=$2 WHERE chat_id=$1", chat_id, minutes
            )

    async def set_join_captcha_enabled(self, chat_id: int, enabled: bool):
        async with self.pool.acquire() as conn:
            await self._ensure_chat_settings_row(conn, chat_id)
            await conn.execute(
                "UPDATE chat_settings SET join_captcha_enabled=$2 WHERE chat_id=$1", chat_id, enabled
            )

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

    # ---------------------------------------------------------------- #
    # BOT ASSETS (cached Telegram file_ids - e.g. images for /start, /help)
    # ---------------------------------------------------------------- #
    # We NEVER store or serve raw image bytes ourselves. Telegram already
    # hosts every photo forever once it's been sent through the bot once;
    # a file_id is a tiny string that tells Telegram's own servers "resend
    # that exact file" - no re-upload, no bandwidth or storage cost on our
    # side no matter how many images you add or how large they are.

    async def get_asset(self, key: str) -> Optional[str]:
        async with self.pool.acquire() as conn:
            return await conn.fetchval("SELECT file_id FROM bot_assets WHERE key=$1", key)

    async def set_asset(self, key: str, file_id: str, set_by: Optional[int] = None):
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO bot_assets (key, file_id, set_by)
                VALUES ($1, $2, $3)
                ON CONFLICT (key) DO UPDATE SET file_id = EXCLUDED.file_id, set_by = EXCLUDED.set_by,
                    updated_at = now()
                """,
                key, file_id, set_by,
            )

    # ---------------------------------------------------------------- #
    # CONTENT-TYPE LOCKS (پنل -> قفل‌ها)
    # ---------------------------------------------------------------- #
    # A missing row means "use the default for that key" (see
    # utils/locks.py -> DEFAULT_LOCK_STATE), not "off" - this keeps
    # existing groups behaving exactly as before for link/forward
    # (which were hardcoded ON pre-panel) without a data migration.

    async def get_chat_locks(self, chat_id: int) -> dict:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT lock_key, enabled FROM chat_locks WHERE chat_id=$1", chat_id
            )
        return {r["lock_key"]: r["enabled"] for r in rows}

    async def set_chat_lock(self, chat_id: int, lock_key: str, enabled: bool):
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO chat_locks (chat_id, lock_key, enabled)
                VALUES ($1, $2, $3)
                ON CONFLICT (chat_id, lock_key) DO UPDATE SET enabled = EXCLUDED.enabled
                """,
                chat_id, lock_key, enabled,
            )

    # ---------------------------------------------------------------- #
    # FILTERED WORDS (فیلتر کلمات)
    # ---------------------------------------------------------------- #

    async def add_filtered_word(self, chat_id: int, word: str, added_by: Optional[int] = None):
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO filtered_words (chat_id, word, added_by)
                VALUES ($1, $2, $3)
                ON CONFLICT (chat_id, word) DO NOTHING
                """,
                chat_id, word, added_by,
            )

    async def remove_filtered_word(self, chat_id: int, word: str) -> bool:
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM filtered_words WHERE chat_id=$1 AND word=$2", chat_id, word
            )
        return result.endswith("1")

    async def list_filtered_words(self, chat_id: int) -> List[str]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT word FROM filtered_words WHERE chat_id=$1 ORDER BY added_at", chat_id
            )
        return [r["word"] for r in rows]

    # ---------------------------------------------------------------- #
    # WARNINGS (اخطار)
    # ---------------------------------------------------------------- #

    async def add_warning(self, chat_id: int, user_id: int, warned_by: int, reason: Optional[str] = None) -> int:
        """Inserts a warning and returns the user's new total warning count in this chat."""
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "INSERT INTO warnings (chat_id, user_id, warned_by, reason) VALUES ($1, $2, $3, $4)",
                    chat_id, user_id, warned_by, reason,
                )
                count = await conn.fetchval(
                    "SELECT COUNT(*) FROM warnings WHERE chat_id=$1 AND user_id=$2", chat_id, user_id
                )
        return count

    async def clear_warnings(self, chat_id: int, user_id: int):
        async with self.pool.acquire() as conn:
            await conn.execute("DELETE FROM warnings WHERE chat_id=$1 AND user_id=$2", chat_id, user_id)

    async def count_warnings(self, chat_id: int, user_id: int) -> int:
        async with self.pool.acquire() as conn:
            value = await conn.fetchval(
                "SELECT COUNT(*) FROM warnings WHERE chat_id=$1 AND user_id=$2", chat_id, user_id
            )
        return value or 0

    async def list_warned_users(self, chat_id: int) -> List[Tuple[int, int]]:
        """Returns [(user_id, warning_count), ...] for every user with >=1 warning, worst first."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT user_id, COUNT(*) AS c FROM warnings
                WHERE chat_id=$1 GROUP BY user_id ORDER BY c DESC
                """,
                chat_id,
            )
        return [(r["user_id"], r["c"]) for r in rows]