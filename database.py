import os
import asyncpg
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

class Database:
    def __init__(self):
        # ── DB configuration from .env ────────────────────────────
        self.user = os.getenv("DB_USER", "postgres")
        self.password = os.getenv("DB_PASS")
        self.host = os.getenv("DB_HOST", "db.ohqdocodrbljclngudce.supabase.co")
        self.port = int(os.getenv("DB_PORT", "5432"))
        self.db_name = os.getenv("DB_NAME", "postgres")
        self.pool = None

    async def get_connection_pool(self):
        """Initializes or returns the active asyncpg connection pool."""
        if self.pool is None:
            self.pool = await asyncpg.create_pool(
                user=self.user,
                password=self.password,
                host=self.host,
                port=self.port,
                database=self.db_name,
                min_size=2,
                max_size=10
            )
        return self.pool

    async def close(self):
        """Safely closes the connection pool when the bot shuts down."""
        if self.pool is not None:
            await self.pool.close()
            self.pool = None

    # ── Schema init ───────────────────────────────────────────
    async def init_db(self):
        """Creates the management bot schema tables on startup."""
        pool = await self.get_connection_pool()
        async with pool.acquire() as conn:
            
            # 1. Main Users Table (Tracks roles and all-time stats per group)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS group_users (
                    chat_id BIGINT,
                    user_id BIGINT,
                    first_name TEXT,
                    last_name TEXT,
                    username TEXT,
                    role TEXT DEFAULT 'normal', -- Roles: 'normal', 'vip', 'admin'
                    messages_all_time INT DEFAULT 0,
                    members_added_count INT DEFAULT 0,
                    joined_at TIMESTAMPTZ DEFAULT NOW(),
                    PRIMARY KEY (chat_id, user_id)
                )
            """)

            # 2. 24-Hour Tracking Table (Logs individual messages for accurate 24h stats)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS message_logs (
                    id SERIAL PRIMARY KEY,
                    chat_id BIGINT,
                    user_id BIGINT,
                    sent_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            
            # Index to make 24h queries and cleanups blazing fast
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_msg_logs_time ON message_logs(sent_at);")

            print("🚀 Database initialized successfully.")

    # ── User Management & Tracking ────────────────────────────
    async def register_or_update_user(self, chat_id: int, user_id: int, first_name: str, last_name: str, username: str):
        pool = await self.get_connection_pool()
        async with pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO group_users (chat_id, user_id, first_name, last_name, username)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (chat_id, user_id) DO UPDATE
                    SET first_name = EXCLUDED.first_name,
                        last_name = EXCLUDED.last_name,
                        username = EXCLUDED.username
            """, chat_id, user_id, first_name, last_name, username)

    async def log_message(self, chat_id: int, user_id: int):
        pool = await self.get_connection_pool()
        async with pool.acquire() as conn:
            await conn.execute("""
                UPDATE group_users 
                SET messages_all_time = messages_all_time + 1 
                WHERE chat_id = $1 AND user_id = $2
            """, chat_id, user_id)
            
            await conn.execute("""
                INSERT INTO message_logs (chat_id, user_id) VALUES ($1, $2)
            """, chat_id, user_id)

    async def log_member_added(self, chat_id: int, user_id: int, count: int = 1):
        pool = await self.get_connection_pool()
        async with pool.acquire() as conn:
            await conn.execute("""
                UPDATE group_users 
                SET members_added_count = members_added_count + $3 
                WHERE chat_id = $1 AND user_id = $2
            """, chat_id, user_id, count)

    # ── Roles & Permissions ───────────────────────────────────
    async def set_user_role(self, chat_id: int, user_id: int, role: str) -> bool:
        pool = await self.get_connection_pool()
        async with pool.acquire() as conn:
            result = await conn.execute("""
                UPDATE group_users SET role = $3 
                WHERE chat_id = $1 AND user_id = $2
            """, chat_id, user_id, role)
            return result.endswith("1")

    async def get_user_role(self, chat_id: int, user_id: int) -> str:
        pool = await self.get_connection_pool()
        async with pool.acquire() as conn:
            role = await conn.fetchval("""
                SELECT role FROM group_users WHERE chat_id = $1 AND user_id = $2
            """, chat_id, user_id)
            return role if role else 'normal'

    # ── Statistics & Profiles ─────────────────────────────────
    async def get_user_profile(self, chat_id: int, user_id: int) -> dict:
        pool = await self.get_connection_pool()
        async with pool.acquire() as conn:
            user_info = await conn.fetchrow("""
                SELECT first_name, last_name, role, messages_all_time, members_added_count
                FROM group_users WHERE chat_id = $1 AND user_id = $2
            """, chat_id, user_id)
            
            if not user_info:
                return None

            msgs_24h = await conn.fetchval("""
                SELECT COUNT(*) FROM message_logs 
                WHERE chat_id = $1 AND user_id = $2 AND sent_at >= NOW() - INTERVAL '24 hours'
            """, chat_id, user_id)

            return {
                "first_name": user_info["first_name"],
                "last_name": user_info["last_name"],
                "role": user_info["role"],
                "messages_all_time": user_info["messages_all_time"],
                "members_added_count": user_info["members_added_count"],
                "messages_24h": msgs_24h
            }

    async def get_group_stats_24h(self, chat_id: int) -> list:
        pool = await self.get_connection_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT u.first_name, COUNT(m.id) as msg_count
                FROM message_logs m
                JOIN group_users u ON m.user_id = u.user_id AND m.chat_id = u.chat_id
                WHERE m.chat_id = $1 AND m.sent_at >= NOW() - INTERVAL '24 hours'
                GROUP BY u.user_id, u.first_name
                ORDER BY msg_count DESC
                LIMIT 10
            """, chat_id)
            return [dict(r) for r in rows]

    async def get_group_stats_all_time(self, chat_id: int) -> list:
        pool = await self.get_connection_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT first_name, messages_all_time 
                FROM group_users 
                WHERE chat_id = $1 
                ORDER BY messages_all_time DESC 
                LIMIT 10
            """, chat_id)
            return [dict(r) for r in rows]

    # ── Maintenance ───────────────────────────────────────────
    async def prune_old_message_logs(self) -> int:
        pool = await self.get_connection_pool()
        async with pool.acquire() as conn:
            result = await conn.execute("""
                DELETE FROM message_logs WHERE sent_at < NOW() - INTERVAL '48 hours'
            """)
            try:
                return int(result.split()[-1])
            except Exception:
                return 0