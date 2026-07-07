# ghormanagmentBot

Built with **pyTelegramBotAPI** (`AsyncTeleBot`) + **Supabase** (Postgres).

## What changed from the aiogram/SQLite version

| Area | Before | Now |
|---|---|---|
| Framework | aiogram 3.x | pyTelegramBotAPI (`telebot.async_telebot.AsyncTeleBot`) |
| Database | SQLite (local file) | Supabase (hosted Postgres) |
| Run mode | polling only | **auto-detects**: webhook if `WEBHOOK_URL` is set, polling otherwise |
| Admin access | Telegram group admins only | Telegram group admins **+** bot-wide "Bot Admins" you manage yourself |
| Ban command | kick (ban+immediate unban) | real ban (kick **and** stays banned) - see "کیک vs بن" below |
| Unban | — (new) | reply to an old message, or `رفع بن @username` |
| Anti-spam threshold | fixed in `.env` | adjustable per-group from inside Telegram (`تنظیم اسپم`) |

## Project structure

```
.
├── bot.py                     # entry point - picks webhook or polling automatically
├── core.py                    # shared `bot` and `db` singletons (avoids circular imports)
├── config.py                  # settings, loaded from .env
├── database.py                # ALL Supabase queries live here (Database class)
├── schema.sql                 # run this once in the Supabase SQL Editor
├── requirements.txt
├── .env.example
├── handlers/
│   ├── tracking.py             # middleware: logs every message / new member
│   ├── admin_commands.py       # ban/unban/mute/vip, bot-admin mgmt, spam threshold
│   ├── stats_commands.py       # آمار روزانه، آمار کل
│   ├── profile_command.py      # پروفایل / /profile
│   ├── antispam.py             # centralized "Normal Member Restrictions"
│   └── help_command.py         # /help — Persian, user-facing docs
└── utils/
    └── permissions.py          # Owner / Bot Admin / Group Admin / VIP / Normal
```

## 1. Install dependencies

Requires Python 3.10+.

```bash
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## 2. Set up Supabase

1. Create a free project at [supabase.com](https://supabase.com).
2. Go to **Project Settings -> API** and copy the **Project URL** and the **`service_role` key**
   (not the `anon` key — the bot needs to bypass Row Level Security since it's the only thing
   talking to this database).
3. Go to **SQL Editor -> New query**, paste the contents of `schema.sql`, and run it once.
   This creates all tables, indexes, and the two stats aggregation functions.

## 3. Configure the bot

1. Talk to [@BotFather](https://t.me/BotFather), create a bot, copy the token.
2. Copy the env template:
   ```bash
   cp .env.example .env
   ```
3. Fill in `BOT_TOKEN`, `SUPABASE_URL`, `SUPABASE_KEY`.
4. Get your own numeric Telegram user ID from [@userinfobot](https://t.me/userinfobot) and put it
   in `OWNER_USER_IDS` (comma-separate multiple owners). This lets you manage "Bot Admins" — see below.

## 4. Add the bot to your group(s)

**Group settings -> Administrators -> Add Admin** -> add your bot, enabling at least:
- Ban users
- Delete messages
- Restrict members (needed for mute)

Without these, ban/mute/link-deletion will silently fail. The bot can be added to as many
groups as you like — every group's stats and anti-spam settings are stored independently.

## 5. Run it

### Local development (polling)
Leave `WEBHOOK_URL` empty in `.env`, then:
```bash
python bot.py
```
You'll see `Starting in POLLING mode...` in the logs.

### On a server (webhook)
Set `WEBHOOK_URL` to your server's public **https** URL (e.g. `https://yourdomain.com`), then:
```bash
python bot.py
```
You'll see `Starting in WEBHOOK mode...`. This assumes you're behind something that terminates
HTTPS for you — a reverse proxy (nginx, Caddy) or a PaaS that already gives you HTTPS
(Render, Railway, Fly.io, etc.). Point that proxy/service at this process's `WEBAPP_HOST:WEBAPP_PORT`
(most PaaS providers set `$PORT` for you automatically, which `config.py` already picks up).

If you're instead exposing this process directly to the internet with your own self-signed
certificate (an old-school VPS setup), see
[pyTelegramBotAPI's webhook example](https://github.com/eternnoir/pyTelegramBotAPI/blob/master/examples/webhook_examples/webhook_aiohttp_echo_bot.py)
for the extra SSL context step — `bot.py` doesn't include that since it's an uncommon setup today.

## 6. How it works in the group

Send `راهنما` or `/help` any time for the full Persian user guide. Quick summary:

| Trigger (reply to a user's message) | Who can use it | What it does |
|---|---|---|
| `کیک` / `بن` / `اخراج` | Admins | Kicks **and bans** the user (see note below) |
| `رفع بن` / `آنبن` (or `رفع بن @username`) | Admins | Unbans the user |
| `میوت` / `سکوت` | Admins | Mutes the user for 24h |
| `تنظیم ویژه` | Admins | Promotes the user to VIP |
| `افزودن ادمین` | Owners only | Makes the user a Bot Admin (bot-wide) |
| `حذف ادمین` | Owners only | Removes Bot Admin status |
| `لیست ادمین ها` | Admins | Lists current Bot Admins |
| `تنظیم اسپم 6 8 30` | Admins | Sets this group's spam threshold (max msgs, window secs, mute mins) |
| `تنظیمات اسپم` | Everyone | Shows this group's current spam threshold |
| `آمار روزانه` / `آمار کل` | Everyone | Group stats: 24h / all-time |
| `پروفایل` / `/profile` | Everyone | Profile + stats of the replied-to user (or yourself) |

**"Admins" above** = a real Telegram admin of that specific group, **or** a Bot Admin (added via
`افزودن ادمین`), **or** an Owner. This is requirement #4 from your list: a Bot Admin doesn't need
to be a Telegram admin of any particular group to use these commands there.

### کیک vs بن — why there's only one command now

Telegram only really has one underlying action: `banChatMember`, which removes the user **and**
blocks them from rejoining via invite link until someone unbans them. A "kick" (as many bots
implement it) is just a ban immediately followed by an unban, so the user is removed but can
rejoin right away. Per your request, this bot keeps it simple: `کیک`, `بن`, and `اخراج` all do
the same thing now — remove **and** keep the user banned — and `رفع بن` reverses it.

## Extending the anti-spam rules

Everything Normal-member-related funnels through one function:

```python
# handlers/antispam.py
async def apply_normal_member_restrictions(message) -> bool:
    if await _check_link_or_forward(message):
        return True
    if await _check_spam_rate(message):
        return True
    # <-- add new checks here
    return False
```

To add a new rule: write `async def _check_your_rule(message) -> bool` in `antispam.py` and call
it inside `apply_normal_member_restrictions`. No other file needs to change.

## Notes on scaling

- `database.py` is the only file touching Supabase. If you ever need to change providers, this
  is the only file that changes.
- Every table is scoped by `chat_id`, so one bot instance serves multiple groups with fully
  independent stats and anti-spam settings — requirement #8 from your list.
- Spam-rate tracking stays in memory (not Supabase) since it's short-lived, high-frequency data —
  a restart just resets everyone's rate-limit window, which is safe.
- Bot Admins (`bot_admins` table) are intentionally **not** scoped per chat — they're bot-wide, per
  requirement #4. If you'd rather have per-group bot admins instead, that's a one-column change
  (`chat_id` on the `bot_admins` table) plus updating `is_authorized_admin`.

## Keeping `/help` up to date

`handlers/help_command.py` contains `HELP_TEXT`. **Update it whenever you add, change, or remove
a feature** so group admins always see accurate, current instructions.