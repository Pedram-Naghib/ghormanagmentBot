"""
config.py
----------
Central configuration, loaded from environment variables (see .env.example).
"""

import os
from dotenv import load_dotenv

load_dotenv()

# --- Telegram ---
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

# --- Optional outbound proxy for reaching api.telegram.org ---
# Leave empty if you can reach Telegram directly. If you're somewhere that
# blocks it, point this at a local SOCKS5/HTTP proxy you already have
# running, e.g. "socks5://127.0.0.1:10808". Requires the aiohttp-socks
# package (already in requirements.txt) for socks5:// URLs.
PROXY_URL = os.getenv("PROXY_URL", "")

# --- Database: direct asyncpg connection to your Supabase Postgres ---
# Find these in Supabase: Project Settings -> Database -> Connection info.
# Using the direct connection (port 5432) is recommended here since the bot
# keeps its own connection pool open for its whole lifetime. If you use the
# pooler instead (port 6543 / pgbouncer transaction mode), asyncpg needs
# statement_cache_size=0 - see the note in database.py's connect().
DB_HOST = os.getenv("DB_HOST", "")
DB_PORT = int(os.getenv("DB_PORT", 5432))
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_NAME = os.getenv("DB_NAME", "postgres")

# --- Owners ---
# Comma-separated Telegram numeric user IDs (get yours from @userinfobot).
# Full access, every group, always - this bootstrap never depends on the
# database, so it always works even if something else is misconfigured.
OWNER_USER_IDS = {
    int(uid) for uid in os.getenv("OWNER_USER_IDS", "").split(",") if uid.strip().isdigit()
}

# --- Run mode: webhook (server) vs polling (local) ---
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").rstrip("/")
WEBHOOK_PATH = f"/webhook/{BOT_TOKEN}"
WEBAPP_HOST = os.getenv("WEBAPP_HOST", "0.0.0.0")
WEBAPP_PORT = int(os.getenv("PORT", os.getenv("WEBAPP_PORT", 8080)))

# --- Anti-spam fallback defaults ---
# Only used for a chat that hasn't set its own thresholds yet.
# NOTE: the time window is intentionally fixed at 3 seconds and no longer
# admin-configurable (see handlers/admin_commands.py) - simpler for a
# normal admin than tuning three separate numbers.
DEFAULT_SPAM_MESSAGE_LIMIT = int(os.getenv("SPAM_MESSAGE_LIMIT", 6))
DEFAULT_SPAM_TIME_WINDOW_SECONDS = int(os.getenv("SPAM_TIME_WINDOW_SECONDS", 3))
DEFAULT_SPAM_MUTE_MINUTES = int(os.getenv("SPAM_MUTE_MINUTES", 30))

# --- Stats ---
STATS_TOP_N = int(os.getenv("STATS_TOP_N", 15))

# --- Optional: shown as a button on /start if set ---
SUPPORT_URL = os.getenv("SUPPORT_URL", "")