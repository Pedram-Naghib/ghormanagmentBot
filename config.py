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

# --- Supabase ---
# Use the "service_role" key (Project Settings -> API in Supabase dashboard).
# This key bypasses Row Level Security, which is what we want here since the
# bot itself is the only thing talking to the DB. NEVER expose this key
# client-side or commit it to git.
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

# --- Owners ---
# Comma-separated Telegram numeric user IDs (get yours from @userinfobot).
# Owners can add/remove "Bot Admins" (see utils/permissions.py). This is the
# bootstrap mechanism - it never depends on the database.
OWNER_USER_IDS = {
    int(uid) for uid in os.getenv("OWNER_USER_IDS", "").split(",") if uid.strip().isdigit()
}

# --- Run mode: webhook (server) vs polling (local) ---
# Leave WEBHOOK_URL empty to run polling (e.g. on your local PC).
# Set WEBHOOK_URL to your server's public https URL to run a webhook server.
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").rstrip("/")
WEBHOOK_PATH = f"/webhook/{BOT_TOKEN}"
WEBAPP_HOST = os.getenv("WEBAPP_HOST", "0.0.0.0")
# Most PaaS providers (Render, Railway, Fly.io, etc.) inject $PORT automatically.
WEBAPP_PORT = int(os.getenv("PORT", os.getenv("WEBAPP_PORT", 8080)))

# --- Anti-spam fallback defaults ---
# Only used for a chat that hasn't set its own thresholds yet via
# "تنظیم اسپم" (see handlers/admin_commands.py) - admins can change these
# per-group from inside Telegram, no redeploy or .env edit needed.
DEFAULT_SPAM_MESSAGE_LIMIT = int(os.getenv("SPAM_MESSAGE_LIMIT", 6))
DEFAULT_SPAM_TIME_WINDOW_SECONDS = int(os.getenv("SPAM_TIME_WINDOW_SECONDS", 8))
DEFAULT_SPAM_MUTE_MINUTES = int(os.getenv("SPAM_MUTE_MINUTES", 30))

# --- Stats ---
STATS_TOP_N = int(os.getenv("STATS_TOP_N", 15))