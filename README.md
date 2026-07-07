# ghormanagmentBot# Telegram Group Management Bot — Phase 1 Foundation

Built with **aiogram 3.x** (async) + **SQLite** (`aiosqlite`, non-blocking).

## Project structure

```
tg_group_manager/
├── bot.py                     # entry point — wires everything together
├── config.py                  # settings, loaded from .env
├── database.py                # ALL SQL lives here (Database class)
├── requirements.txt
├── .env.example                # copy to .env and fill in
├── handlers/
│   ├── tracking.py             # middleware: logs every message / new member
│   ├── admin_commands.py       # کیک، میوت، تنظیم ویژه
│   ├── stats_commands.py       # آمار روزانه، آمار کل
│   ├── profile_command.py      # پروفایل / /profile
│   ├── antispam.py             # centralized "Normal Member Restrictions"
│   └── help_command.py         # /help — Persian, user-facing docs
└── utils/
    └── permissions.py          # is_group_admin / is_normal_member helpers
```

## 1. Install dependencies

Requires Python 3.10+.

```bash
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## 2. Configure the bot

1. Talk to [@BotFather](https://t.me/BotFather) on Telegram, create a bot, copy the token.
2. Copy the env template and fill it in:
   ```bash
   cp .env.example .env
   ```
3. Open `.env` and paste your token into `BOT_TOKEN=`.

## 3. Add the bot to your group with the right permissions

In your Telegram group: **Group settings → Administrators → Add Admin** → add your bot, and enable at least:

- Ban users
- Delete messages
- Restrict members (needed for mute)

Without these, kick/mute/link-deletion will silently fail.

## 4. Run it

```bash
python bot.py
```

The database file (`bot_database.db` by default) is created automatically on first run — no manual migration step needed.

## 5. How it works in the group

Send `راهنما` or `/help` in the group any time for the full Persian user guide (also reproduced below). Quick summary:

| Trigger (reply to a user's message) | Who can use it | What it does |
|---|---|---|
| `کیک` / `بن` | Admins | Kicks the replied-to user |
| `میوت` / `سکوت` | Admins | Mutes the replied-to user for 24h |
| `تنظیم ویژه` | Admins | Promotes the replied-to user to VIP |
| `آمار روزانه` | Everyone | Group stats for the last 24 hours |
| `آمار کل` | Everyone | All-time group stats |
| `پروفایل` / `/profile` | Everyone | Profile + stats of replied-to user (or yourself) |

**Automatic, always-on for Normal members** (not admin, not VIP):
- Links and forwarded messages are deleted instantly.
- Sending too many messages too fast → automatic mute.

## Extending the anti-spam rules

Everything Normal-member-related funnels through one function:

```python
# handlers/antispam.py
async def apply_normal_member_restrictions(message, bot) -> bool:
    if await _check_link_or_forward(message):
        return True
    if await _check_spam_rate(message, bot):
        return True
    # <-- add new checks here
    return False
```

To add a new rule (e.g. banned words, media-type restrictions, mention limits):
1. Write `async def _check_your_rule(message) -> bool` in `antispam.py`.
2. Call it inside `apply_normal_member_restrictions`.
That's it — no other file needs to change.

## Notes on scaling beyond Phase 1

- `database.py` is the only file touching SQL. Swapping SQLite for Postgres/Supabase later means rewriting the internals of the `Database` class only — every handler already talks to it through the same method calls.
- Spam-rate tracking is kept in memory (not the DB) since it's short-lived, high-frequency data — restarting the bot simply resets everyone's rate-limit window, which is safe behavior.
- Stats are scoped per `chat_id`, so one bot instance can serve multiple groups with fully independent statistics.

## Keeping `/help` up to date

`handlers/help_command.py` contains `HELP_TEXT` — the exact message shown in Telegram. **Update it whenever you add, change, or remove a feature** so group admins always see accurate, current instructions.
