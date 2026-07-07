"""
database.py
-------------
All persistence logic, backed by Supabase (Postgres) via supabase-py.

supabase-py's client is synchronous under the hood (httpx sync client), so
every call is wrapped with `asyncio.to_thread(...)` to avoid blocking the
bot's event loop. This is the ONLY file that talks to the database - every
handler goes through the `Database` class methods below.

Run schema.sql once in your Supabase project's SQL Editor before starting
the bot - it creates all required tables, indexes, and the two aggregate
RPC functions used for group-wide stats (Postgres GROUP BY isn't reachable
through the plain REST query builder, so we use small SQL functions for it).
"""

import asyncio
from typing import List, Optional, Tuple

from supabase import Client, create_client

from config import (
    DEFAULT_SPAM_MESSAGE_LIMIT,
    DEFAULT_SPAM_MUTE_MINUTES,
    DEFAULT_SPAM_TIME_WINDOW_SECONDS,
    STATS_TOP_N,
    SUPABASE_KEY,
    SUPABASE_URL,
)


class Database:
    def __init__(self):
        if not SUPABASE_URL or not SUPABASE_KEY:
            raise RuntimeError(
                "SUPABASE_URL / SUPABASE_KEY are not set. Copy .env.example to .env, "
                "create a Supabase project, and fill these in."
            )
        self.client: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

    async def _run(self, fn, *args, **kwargs):
        """Run a blocking supabase-py call in a worker thread."""
        return await asyncio.to_thread(fn, *args, **kwargs)

    # ---------------------------------------------------------------- #
    # USERS
    # ---------------------------------------------------------------- #

    async def upsert_user(
        self,
        user_id: int,
        username: Optional[str],
        first_name: Optional[str],
        last_name: Optional[str],
    ):
        def _do():
            self.client.table("users").upsert(
                {
                    "user_id": user_id,
                    "username": username,
                    "first_name": first_name,
                    "last_name": last_name,
                }
            ).execute()

        await self._run(_do)

    async def set_vip(self, user_id: int, is_vip: bool = True):
        def _do():
            self.client.table("users").update({"is_vip": is_vip}).eq("user_id", user_id).execute()

        await self._run(_do)

    async def is_vip(self, user_id: int) -> bool:
        def _do():
            res = self.client.table("users").select("is_vip").eq("user_id", user_id).limit(1).execute()
            return res.data

        data = await self._run(_do)
        return bool(data and data[0].get("is_vip"))

    async def get_user_display_name(self, user_id: int) -> str:
        def _do():
            res = (
                self.client.table("users")
                .select("username, first_name, last_name")
                .eq("user_id", user_id)
                .limit(1)
                .execute()
            )
            return res.data

        data = await self._run(_do)
        if not data:
            return str(user_id)
        row = data[0]
        name = " ".join(filter(None, [row.get("first_name"), row.get("last_name")])).strip()
        return name or (f"@{row['username']}" if row.get("username") else str(user_id))

    async def get_user_id_by_username(self, username: str) -> Optional[int]:
        """Look up a numeric user_id by @username (case-insensitive)."""
        def _do():
            res = (
                self.client.table("users")
                .select("user_id")
                .ilike("username", username)
                .limit(1)
                .execute()
            )
            return res.data

        data = await self._run(_do)
        return data[0]["user_id"] if data else None

    # ---------------------------------------------------------------- #
    # BOT ADMINS (bot-wide, separate from Telegram group-admin status)
    # ---------------------------------------------------------------- #

    async def add_bot_admin(self, user_id: int, added_by: Optional[int] = None):
        def _do():
            self.client.table("bot_admins").upsert({"user_id": user_id, "added_by": added_by}).execute()

        await self._run(_do)

    async def remove_bot_admin(self, user_id: int):
        def _do():
            self.client.table("bot_admins").delete().eq("user_id", user_id).execute()

        await self._run(_do)

    async def is_bot_admin(self, user_id: int) -> bool:
        def _do():
            res = self.client.table("bot_admins").select("user_id").eq("user_id", user_id).limit(1).execute()
            return res.data

        data = await self._run(_do)
        return bool(data)

    async def list_bot_admins(self) -> List[int]:
        def _do():
            res = self.client.table("bot_admins").select("user_id").execute()
            return res.data

        data = await self._run(_do)
        return [row["user_id"] for row in data]

    # ---------------------------------------------------------------- #
    # MESSAGE TRACKING
    # ---------------------------------------------------------------- #

    async def log_message(self, user_id: int, chat_id: int):
        def _do():
            self.client.table("message_log").insert({"user_id": user_id, "chat_id": chat_id}).execute()

        await self._run(_do)

    async def get_user_message_count(
        self, user_id: int, chat_id: int, since_iso: Optional[str] = None
    ) -> int:
        def _do():
            q = (
                self.client.table("message_log")
                .select("id", count="exact")
                .eq("user_id", user_id)
                .eq("chat_id", chat_id)
            )
            if since_iso:
                q = q.gte("created_at", since_iso)
            res = q.execute()
            return res.count or 0

        return await self._run(_do)

    # ---------------------------------------------------------------- #
    # MEMBER-ADDED TRACKING
    # ---------------------------------------------------------------- #

    async def log_member_added(self, adder_id: int, new_member_id: int, chat_id: int):
        def _do():
            self.client.table("member_log").insert(
                {"adder_id": adder_id, "new_member_id": new_member_id, "chat_id": chat_id}
            ).execute()

        await self._run(_do)

    # ---------------------------------------------------------------- #
    # AGGREGATE STATS (via Postgres RPC functions - see schema.sql)
    # ---------------------------------------------------------------- #

    async def get_top_message_senders(
        self, chat_id: int, since_iso: Optional[str] = None, limit: int = STATS_TOP_N
    ) -> List[Tuple[int, int]]:
        def _do():
            res = self.client.rpc(
                "top_message_senders",
                {"p_chat_id": chat_id, "p_since": since_iso, "p_limit": limit},
            ).execute()
            return res.data

        data = await self._run(_do)
        return [(row["user_id"], row["message_count"]) for row in data]

    async def get_top_adders(
        self, chat_id: int, since_iso: Optional[str] = None, limit: int = STATS_TOP_N
    ) -> List[Tuple[int, int]]:
        def _do():
            res = self.client.rpc(
                "top_member_adders",
                {"p_chat_id": chat_id, "p_since": since_iso, "p_limit": limit},
            ).execute()
            return res.data

        data = await self._run(_do)
        return [(row["adder_id"], row["added_count"]) for row in data]

    # ---------------------------------------------------------------- #
    # PER-CHAT ANTI-SPAM SETTINGS (admins tune these live, no .env edits)
    # ---------------------------------------------------------------- #

    async def get_chat_settings(self, chat_id: int) -> dict:
        def _do():
            res = self.client.table("chat_settings").select("*").eq("chat_id", chat_id).limit(1).execute()
            return res.data

        data = await self._run(_do)
        if data:
            row = data[0]
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
        def _do():
            self.client.table("chat_settings").upsert(
                {
                    "chat_id": chat_id,
                    "spam_message_limit": spam_message_limit,
                    "spam_time_window_seconds": spam_time_window_seconds,
                    "spam_mute_minutes": spam_mute_minutes,
                }
            ).execute()

        await self._run(_do)