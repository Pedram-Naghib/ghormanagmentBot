"""
config.py
----------
Central place for all bot configuration. Values are loaded from environment
variables (see .env.example) so secrets never live in the code.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# --- Core ---
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
DB_PATH = os.getenv("DB_PATH", "bot_database.db")

# --- Anti-spam settings (apply to Normal members only) ---
# If a normal member sends more than SPAM_MESSAGE_LIMIT messages within
# SPAM_TIME_WINDOW_SECONDS seconds, they get muted for SPAM_MUTE_MINUTES.
SPAM_MESSAGE_LIMIT = int(os.getenv("SPAM_MESSAGE_LIMIT", 6))
SPAM_TIME_WINDOW_SECONDS = int(os.getenv("SPAM_TIME_WINDOW_SECONDS", 8))
SPAM_MUTE_MINUTES = int(os.getenv("SPAM_MUTE_MINUTES", 30))

# --- Stats ---
# How many top users to list in /آمار روزانه and /آمار کل
STATS_TOP_N = int(os.getenv("STATS_TOP_N", 15))
