"""
admin_panel_page.py
----------------------
A password-protected web page at /admin/messages for editing the bot's
customizable response templates (see utils/messages.py) without touching
code or redeploying - built for handing the bot off to someone who isn't a
developer.

WHY A WEB PAGE INSTEAD OF A TELEGRAM COMMAND: welcome/goodbye already have
their own dedicated Telegram commands (تنظیم خوش آمدگویی/تنظیم بدرود) since
those are the single most commonly customized thing and a chat command
with the whole new text as its argument is fine for ONE template. Editing
dozens of different messages that way would mean memorizing dozens of
command names; a page listing everything at once with a text box each is
a much better fit for "go through all of these and adjust the wording".

AUTH: plain HTTP Basic Auth against ADMIN_PANEL_USERNAME/PASSWORD in .env.
If either is empty, the page is disabled entirely (404) rather than ever
accepting a blank or guessable login - see register_admin_panel_routes().

AVAILABILITY: registered in bot.py regardless of run mode (polling OR
webhook) - see _build_admin_app() there - so it works the same whether
you're running locally or on a server.
"""

import base64
import html

from aiohttp import web

from config import ADMIN_PANEL_PASSWORD, ADMIN_PANEL_USERNAME
from utils import messages

PAGE_STYLE = """
<style>
  :root { --bg:#0f1115; --card:#171a21; --border:#262b36; --text:#e7e9ee; --muted:#9aa3b2; --accent:#5b9dff; --green:#37c978; }
  * { box-sizing: border-box; }
  body { margin:0; background:var(--bg); color:var(--text); font-family:"Vazirmatn","Tahoma","Segoe UI",sans-serif; line-height:1.8; padding:24px; }
  h1 { font-size:1.4rem; margin:0 0 6px 0; }
  p.sub { color:var(--muted); margin:0 0 24px 0; }
  .card { background:var(--card); border:1px solid var(--border); border-radius:10px; padding:16px; margin-bottom:16px; }
  .key { font-family:monospace; color:var(--accent); font-size:0.85rem; margin-bottom:8px; }
  .badge { display:inline-block; font-size:0.7rem; padding:2px 8px; border-radius:20px; margin-right:8px; }
  .badge.custom { background:rgba(55,201,120,0.15); color:var(--green); }
  .badge.default { background:rgba(154,163,178,0.15); color:var(--muted); }
  textarea { width:100%; min-height:90px; background:#0c0e12; color:var(--text); border:1px solid var(--border); border-radius:6px; padding:10px; font-family:monospace; font-size:0.9rem; resize:vertical; }
  .row { display:flex; gap:8px; margin-top:8px; }
  button { cursor:pointer; border:none; border-radius:6px; padding:8px 16px; font-size:0.85rem; }
  button.save { background:var(--accent); color:#fff; }
  button.reset { background:transparent; color:var(--muted); border:1px solid var(--border); }
  .flash { background:rgba(55,201,120,0.15); color:var(--green); padding:10px 16px; border-radius:8px; margin-bottom:20px; }
</style>
"""


def _check_auth(request: web.Request) -> bool:
    if not ADMIN_PANEL_USERNAME or not ADMIN_PANEL_PASSWORD:
        return False  # page disabled - see register_admin_panel_routes()
    header = request.headers.get("Authorization", "")
    if not header.startswith("Basic "):
        return False
    try:
        decoded = base64.b64decode(header[len("Basic "):]).decode("utf-8")
        username, _, password = decoded.partition(":")
    except Exception:
        return False
    return username == ADMIN_PANEL_USERNAME and password == ADMIN_PANEL_PASSWORD


def _unauthorized() -> web.Response:
    return web.Response(
        status=401,
        text="Authentication required.",
        headers={"WWW-Authenticate": 'Basic realm="Bot Message Editor"'},
    )


def _render_page(flash: str = "") -> str:
    flash_html = f'<div class="flash">{html.escape(flash)}</div>' if flash else ""
    cards = []
    for key in messages.all_keys():
        current = html.escape(messages.effective(key))
        overridden = messages.is_overridden(key)
        badge = '<span class="badge custom">سفارشی</span>' if overridden else '<span class="badge default">پیش‌فرض</span>'
        reset_button = (
            f'<button class="reset" formaction="/admin/messages/reset" formmethod="post">بازگردانی به پیش‌فرض</button>'
            if overridden else ""
        )
        cards.append(f"""
        <div class="card">
          <div class="key">{html.escape(key)} {badge}</div>
          <form method="post" action="/admin/messages/save">
            <input type="hidden" name="key" value="{html.escape(key)}">
            <textarea name="template">{current}</textarea>
            <div class="row">
              <button class="save" type="submit">ذخیره</button>
              {reset_button}
            </div>
          </form>
        </div>
        """)
    return f"""<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ویرایش پیام‌های ربات</title>
{PAGE_STYLE}
</head>
<body>
<h1>✏️ ویرایش پیام‌های ربات</h1>
<p class="sub">هر پیام را ویرایش کنید و «ذخیره» بزنید - بلافاصله برای پیام‌های بعدی اعمال می‌شود، بدون نیاز به ری‌استارت ربات. جای‌گذاری‌های داخل آکولاد (مثل <code>{{name}}</code>) را دست‌نخورده نگه دارید.</p>
{flash_html}
{"".join(cards)}
</body>
</html>"""


async def _handle_get(request: web.Request) -> web.Response:
    if not _check_auth(request):
        return _unauthorized()
    flash = request.query.get("saved", "")
    flash_text = f"ذخیره شد: {flash}" if flash else ""
    return web.Response(text=_render_page(flash_text), content_type="text/html", charset="utf-8")


async def _handle_save(request: web.Request) -> web.Response:
    if not _check_auth(request):
        return _unauthorized()
    data = await request.post()
    key = data.get("key", "")
    template = data.get("template", "")
    if key in messages.DEFAULTS:
        from core import db
        await messages.set_override(db, key, template)
    raise web.HTTPFound(f"/admin/messages?saved={key}")


async def _handle_reset(request: web.Request) -> web.Response:
    if not _check_auth(request):
        return _unauthorized()
    data = await request.post()
    key = data.get("key", "")
    if key in messages.DEFAULTS:
        from core import db
        await messages.reset_override(db, key)
    raise web.HTTPFound(f"/admin/messages?saved={key}")


def register_admin_panel_routes(app: web.Application):
    """Call from bot.py to expose the editor at /admin/messages. Does
    nothing (page stays 404) if ADMIN_PANEL_USERNAME/PASSWORD aren't set -
    see _check_auth()."""
    app.router.add_get("/admin/messages", _handle_get)
    app.router.add_post("/admin/messages/save", _handle_save)
    app.router.add_post("/admin/messages/reset", _handle_reset)