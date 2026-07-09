"""
docs_page.py
--------------
A single self-contained HTML page listing literally everything this bot
can do - every command, every permission rule, every default. Meant for
handing the bot off to someone else who doesn't want to read the source
code.

Served over plain HTTP (see register_docs_route() below, wired up in
bot.py's run_webhook()) so it's just a URL:

    https://<your-render-app>.onrender.com/docs

NOTE: this route only exists while the bot is running in WEBHOOK mode
(i.e. WEBHOOK_URL is set - which is how it runs on Render). It does NOT
exist in local polling mode, since there's no web server at all there.

Keep this in sync by hand whenever a command/behavior changes - it is
NOT generated from the handler code.
"""

from aiohttp import web

DOCS_HTML = """<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>راهنمای کامل ربات مدیریت گروه</title>
<style>
  :root {
    --bg: #0f1115;
    --card: #171a21;
    --border: #262b36;
    --text: #e7e9ee;
    --muted: #9aa3b2;
    --accent: #5b9dff;
    --green: #37c978;
    --red: #ff6b6b;
    --yellow: #ffb84d;
    --code-bg: #0c0e12;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    background: var(--bg);
    color: var(--text);
    font-family: "Vazirmatn", "Tahoma", "Segoe UI", sans-serif;
    line-height: 1.9;
    padding: 0 0 60px 0;
  }
  header {
    padding: 40px 20px 30px 20px;
    text-align: center;
    border-bottom: 1px solid var(--border);
    background: linear-gradient(180deg, rgba(91,157,255,0.08), transparent);
  }
  header h1 { margin: 0 0 8px 0; font-size: 1.8rem; }
  header p { margin: 0; color: var(--muted); font-size: 0.95rem; }
  .wrap { max-width: 880px; margin: 0 auto; padding: 0 18px; }
  nav.toc {
    margin: 28px auto; max-width: 880px; padding: 18px 22px;
    background: var(--card); border: 1px solid var(--border); border-radius: 14px;
  }
  nav.toc h2 { margin-top: 0; font-size: 1rem; color: var(--muted); font-weight: 600; }
  nav.toc ol { columns: 2; gap: 24px; padding-inline-start: 20px; margin: 0; }
  nav.toc a { color: var(--accent); text-decoration: none; }
  nav.toc a:hover { text-decoration: underline; }
  section {
    max-width: 880px; margin: 26px auto; padding: 22px 24px;
    background: var(--card); border: 1px solid var(--border); border-radius: 14px;
  }
  section h2 {
    margin-top: 0; font-size: 1.25rem; display: flex; align-items: center; gap: 10px;
    border-bottom: 1px solid var(--border); padding-bottom: 12px;
  }
  section h3 { font-size: 1.05rem; color: var(--accent); margin-bottom: 6px; }
  table { width: 100%; border-collapse: collapse; margin: 14px 0; font-size: 0.94rem; }
  th, td { text-align: right; padding: 9px 10px; border-bottom: 1px solid var(--border); vertical-align: top; }
  th { color: var(--muted); font-weight: 600; font-size: 0.85rem; }
  code {
    background: var(--code-bg); border: 1px solid var(--border); border-radius: 6px;
    padding: 2px 7px; font-family: "Courier New", monospace; font-size: 0.92em; color: var(--yellow);
    direction: ltr; unicode-bidi: embed; display: inline-block;
  }
  .badge {
    display: inline-block; font-size: 0.72rem; padding: 2px 9px; border-radius: 999px;
    margin-inline-start: 6px; font-weight: 600; vertical-align: middle;
  }
  .badge.owner   { background: rgba(255,107,107,0.15); color: var(--red); }
  .badge.admin   { background: rgba(91,157,255,0.15);  color: var(--accent); }
  .badge.groupowner { background: rgba(255,184,77,0.18); color: var(--yellow); }
  .badge.everyone{ background: rgba(55,201,120,0.15);  color: var(--green); }
  .note {
    margin: 14px 0; padding: 12px 14px; border-radius: 10px;
    background: rgba(255,184,77,0.08); border: 1px solid rgba(255,184,77,0.25); font-size: 0.92rem;
  }
  .note.danger { background: rgba(255,107,107,0.08); border-color: rgba(255,107,107,0.3); }
  .note.info   { background: rgba(91,157,255,0.08); border-color: rgba(91,157,255,0.3); }
  ul { padding-inline-start: 22px; }
  li { margin: 6px 0; }
  footer { text-align: center; color: var(--muted); font-size: 0.85rem; margin-top: 40px; }
  a.back-to-top { color: var(--muted); font-size: 0.8rem; text-decoration: none; }
</style>
</head>
<body>

<header>
  <h1>🤖 راهنمای کامل ربات مدیریت گروه</h1>
  <p>همه‌چیز درباره‌ی این ربات، از صفر تا صد - برای هرکسی که قرار است اداره‌اش را به دست بگیرد.</p>
</header>

<nav class="toc" id="top">
  <h2>فهرست مطالب</h2>
  <ol>
    <li><a href="#access">۱. سطوح دسترسی</a></li>
    <li><a href="#start">۲. شروع کار (/start)</a></li>
    <li><a href="#panel">۳. پنل تنظیمات («پنل»)</a></li>
    <li><a href="#moderation">۴. دستورات مدیریتی (بن/میوت/اخطار/...)</a></li>
    <li><a href="#ownership">۵. مالکیت و ادمین‌های گروه</a></li>
    <li><a href="#delete">۶. حذف پیام‌ها</a></li>
    <li><a href="#filters">۷. کلمات فیلترشده</a></li>
    <li><a href="#welcome">۸. خوش‌آمدگویی و بدرود</a></li>
    <li><a href="#spam">۹. ضد اسپم و قفل‌های محتوا</a></li>
    <li><a href="#captcha">۱۰. کپچای عضویت</a></li>
    <li><a href="#stats">۱۱. آمار و پروفایل</a></li>
    <li><a href="#images">۱۲. تصاویر ربات (بنرها)</a></li>
    <li><a href="#ping">۱۳. پینگ</a></li>
    <li><a href="#rules">۱۴. قوانین مهم فنی که باید بدانید</a></li>
  </ol>
</nav>

<div class="wrap">

<section id="access">
  <h2>👑 ۱. سطوح دسترسی</h2>
  <p>هر گروه کاملاً مستقل است. مثلاً کسی که در گروه A ادمین ربات است، در گروه B هیچ دسترسی خاصی ندارد مگر اینکه جداگانه در همان گروه هم تعیین شود.</p>
  <table>
    <tr><th>سطح</th><th>چطور تعیین می‌شود</th><th>محدوده</th></tr>
    <tr><td>👑 مالک ربات <span class="badge owner">Global Owner</span></td><td>در متغیر محیطی <code>OWNER_USER_IDS</code> روی سرور (Render) ثبت می‌شود، نه در دیتابیس</td><td>همه‌ی گروه‌ها، همیشه، دسترسی کامل</td></tr>
    <tr><td>مالک گروه <span class="badge groupowner">Group Owner</span></td><td>خودکار: هرکس ربات را به یک گروه اضافه کند</td><td>فقط همان گروه، دسترسی کامل</td></tr>
    <tr><td>ادمین گروه <span class="badge admin">Admin</span></td><td>با دستور «افزودن ادمین گروه» توسط مالک همان گروه</td><td>فقط همان گروه</td></tr>
    <tr><td>عضو ویژه (VIP)</td><td>با دستور «تنظیم ویژه»</td><td>فقط معافیت از ضد اسپم، در همان گروه</td></tr>
    <tr><td>عضو عادی</td><td>پیش‌فرض همه</td><td>مشمول همه‌ی قفل‌ها و محدودیت‌ها</td></tr>
  </table>
  <div class="note">
    ⚠️ <b>ادمین بودن در خود تلگرام کافی نیست.</b> کسی که در تنظیمات گروه تلگرام "ادمین" است، اگر توسط مالک گروه با «افزودن ادمین گروه» به ربات معرفی نشده باشد، هیچ دستوری از ربات اجرا نمی‌شود - فقط پیام "⛔️ دسترسی ندارید" می‌بیند.
  </div>
  <div class="note info">
    اگر ربات را به گروهی اضافه کردید که از قبل با نسخه‌های قدیمی‌تر این ربات کار می‌کرد و مالک ثبت‌شده ندارد، هرکس واقعاً در تلگرام Owner/Admin آن گروه است می‌تواند یک‌بار بنویسد <code>ادعای مالکیت</code> تا به‌عنوان مالک گروه در ربات ثبت شود.
  </div>
</section>

<section id="start">
  <h2>🚀 ۲. شروع کار</h2>
  <p>وقتی کسی در پیوی ربات دکمه‌ی Start را بزند یا از لینک دعوت گروه استفاده کند، ربات خودش را معرفی می‌کند و دو دکمه نشان می‌دهد: «افزودن به گروه» و «راهنمای کامل». اگر تصویری با کلید <code>start_banner</code> ثبت شده باشد (بخش ۱۲ را ببینید)، همراه با آن پیام به‌صورت عکس نمایش داده می‌شود.</p>
  <p><b>نکته‌ی فنی:</b> این تنها دستوری‌ست که هنوز به‌صورت <code>/start</code> کار می‌کند - نه چون یک دستور معمولی است، بلکه چون خود تلگرام همیشه دقیقاً همین متن را خودکار می‌فرستد وقتی کسی دکمه‌ی Start را می‌زند؛ این رفتار پلتفرم است و قابل تغییر نیست. جز این یک مورد، ربات دیگر هیچ دستور اسلش‌داری ندارد.</p>
</section>

<section id="panel">
  <h2>🛠 ۳. پنل تنظیمات</h2>
  <p>در هر گروه بنویسید: <code>پنل</code></p>
  <p>یک منوی دکمه‌ای باز می‌شود (فقط برای ادمین‌های ربات، و فقط همان کسی که پنل را باز کرده می‌تواند دکمه‌هایش را بزند):</p>
  <ul>
    <li><b>🔒 قفل‌ها</b> - روشن/خاموش کردن حذف خودکار انواع محتوا برای اعضای عادی (لیست کامل در بخش ۹)</li>
    <li><b>📋 لیست‌ها</b> - مالک و ادمین‌های گروه، اعضای ویژه، کلمات فیلترشده، اخطارهای فعال</li>
    <li><b>⚙️ تنظیمات پیشرفته</b> - روشن/خاموش کردن خوش‌آمدگویی، بدرود، کپچای عضویت + نمایش تنظیمات فعلی ضد اسپم</li>
    <li><b>📖 راهنما</b> - باز کردن همان راهنمای زیر دکمه‌ای که با «راهنما» هم قابل دسترسی است</li>
    <li><b>❌ بستن</b></li>
  </ul>
  <p>اگر تصویری با کلید <code>panel_banner</code> ثبت شده باشد، پنل هم مثل استارت/راهنما به‌صورت عکس با کپشن نمایش داده می‌شود.</p>
</section>

<section id="moderation">
  <h2>👮‍♂️ ۴. دستورات مدیریتی</h2>
  <p>همه‌ی این دستورات <b>ادمین ربات در همان گروه</b> لازم دارند. اکثرشان باید روی پیام کاربر مقصد <b>ریپلای</b> شوند.</p>
  <div class="note danger">
    <b>خیلی مهم - «تطبیق دقیق متن»:</b> این دستورات فقط زمانی اجرا می‌شوند که پیام <u>دقیقاً</u> همان کلمه باشد (یا فرمت ثابت مشخص‌شده) - نه بخشی از یک جمله‌ی عادی. مثلاً نوشتن «<b>بن شدم</b>» در یک جمله‌ی معمولی هیچ اتفاقی نمی‌افتد؛ فقط نوشتن دقیق «<b>بن</b>» (یا «بن @username») کار می‌کند. این عمداً این‌طور طراحی شده تا یک جمله‌ی روزمره باعث بن/میوت اشتباهی کسی نشود.
  </div>
  <table>
    <tr><th>دستور</th><th>کار</th><th>فرمت‌های مجاز</th></tr>
    <tr><td><code>کیک</code> / <code>بن</code> / <code>اخراج</code> / <code>سیک</code></td><td>اخراج + بن دائم از گروه (تا «رفع بن»)</td><td>ریپلای + دقیقاً این کلمه، یا <code>بن @username</code></td></tr>
    <tr><td><code>رفع بن</code> / <code>آنبن</code></td><td>خروج از لیست بن</td><td>ریپلای به پیام قدیمی کاربر، یا <code>رفع بن @username</code></td></tr>
    <tr><td><code>میوت</code> / <code>سکوت</code></td><td>سکوت کامل (بی‌نهایت تا رفع سکوت دستی)</td><td>ریپلای + دقیقاً این کلمه</td></tr>
    <tr><td><code>میوت 10</code></td><td>سکوت فقط برای عدد دقیقه‌ی داده‌شده</td><td>ریپلای + «میوت» + یک عدد</td></tr>
    <tr><td><code>رفع سکوت</code> / <code>آنمیوت</code></td><td>برداشتن سکوت (برمی‌گرداند به دسترسی‌های واقعی گروه)</td><td>ریپلای</td></tr>
    <tr><td><code>تنظیم ویژه</code></td><td>عضو ویژه (VIP) کردن - معافیت از ضد اسپم</td><td>ریپلای</td></tr>
    <tr><td><code>لغو ویژه</code></td><td>برداشتن VIP</td><td>ریپلای</td></tr>
    <tr><td><code>اخطار</code></td><td>یک اخطار می‌دهد؛ بعد از ۳ اخطار فعال خودکار بن می‌شود</td><td>ریپلای + دقیقاً این کلمه (بدون دلیل اضافه)</td></tr>
    <tr><td><code>حذف اخطار</code> / <code>پاک کردن اخطار</code></td><td>پاک کردن همه‌ی اخطارهای فعال کاربر</td><td>ریپلای</td></tr>
    <tr><td><code>لیست اخطار</code> / <code>لیست اخطارها</code></td><td>نمایش کاربرانی که اخطار فعال دارند</td><td>-</td></tr>
    <tr><td><code>پروفایل</code></td><td>نام، آیدی عددی، عکس، نقش، تعداد پیام‌ها (کل و ۲۴ ساعت اخیر) + اعضای جدید ۲۴ ساعت اخیر گروه + ۳ نفر برتر در اضافه‌کردن عضو</td><td>ریپلای برای دیدن پروفایل شخص دیگر، بدون ریپلای = پروفایل خودتان</td></tr>
    <tr><td><code>پینگ</code></td><td>بررسی زنده بودن ربات (بخش ۱۳)</td><td>برای همه، نه فقط ادمین‌ها</td></tr>
  </table>
  <div class="note">
    «کیک» با «بن» دقیقاً یک کار انجام می‌دهند: تلگرام کیک جداگانه ندارد؛ کیک یعنی بن و بلافاصله آنبن. این ربات ساده نگهش داشته: کیک/بن/اخراج/سیک همه به معنای «بن دائم تا رفع بن دستی» هستند.
  </div>
  <h3>سه روش تعیین «مقصد» یک دستور</h3>
  <ul>
    <li>روی پیام واقعی همان شخص ریپلای کنید (رایج‌ترین روش)</li>
    <li>روی پیامی که فقط یک <code>@username</code> در آن نوشته شده ریپلای کنید (یعنی «این یوزرنیم را می‌گویم»، نه «فرستنده‌ی این پیام»)</li>
    <li>یوزرنیم را مستقیم در همان دستور بنویسید، مثل <code>بن @username</code> - فقط برای «بن» کار می‌کند (این روش فقط وقتی جواب می‌دهد که آن کاربر قبلاً حداقل یک پیام در همین گروه فرستاده باشد، چون ربات یوزرنیم‌ها را فقط از پیام‌های واقعی می‌شناسد)</li>
  </ul>
</section>

<section id="ownership">
  <h2>🛠 ۵. مالکیت و ادمین‌های گروه</h2>
  <table>
    <tr><th>دستور</th><th>کار</th><th>چه کسی می‌تواند</th></tr>
    <tr><td><code>مالک این گروه</code> / <code>مالک گروه</code></td><td>نمایش مالک فعلی گروه</td><td>ادمین‌های ربات</td></tr>
    <tr><td><code>ادعای مالکیت</code></td><td>برای گروه‌های بدون مالک ثبت‌شده - اگر واقعاً در تلگرام ادمین/سازنده‌ی گروه باشید</td><td>هرکسی که واقعاً Owner/Admin تلگرامی گروه است</td></tr>
    <tr><td><code>افزودن ادمین گروه</code> / <code>افزودن ادمین</code></td><td>ریپلای روی کسی تا ادمین ربات در همین گروه شود</td><td>فقط مالک گروه (یا مالک ربات)</td></tr>
    <tr><td><code>حذف ادمین گروه</code> / <code>حذف ادمین</code></td><td>گرفتن دسترسی ادمین ربات از کسی</td><td>فقط مالک گروه (یا مالک ربات)</td></tr>
    <tr><td><code>لیست ادمین های گروه</code> / <code>لیست ادمین ها</code></td><td>نمایش مالک + همه‌ی ادمین‌های ربات این گروه</td><td>ادمین‌های ربات</td></tr>
    <tr><td><code>پیکربندی</code></td><td>همه‌ی ادمین‌های <u>واقعی تلگرام</u> این گروه را یک‌جا به‌عنوان ادمین ربات ثبت می‌کند (برای گروه‌های شلوغ که ادمین‌های زیادی دارند و نمی‌خواهید یکی‌یکی اضافه کنید)</td><td>فقط مالک گروه (یا مالک ربات)</td></tr>
    <tr><td><code>پاک سازی</code></td><td>دسترسی ادمین ربات را از <u>همه</u> می‌گیرد (مالک گروه دست‌نخورده می‌ماند؛ فقط روی دیتابیس ربات اثر دارد، ادمین‌بودن واقعی افراد در خودِ تلگرام تغییری نمی‌کند)</td><td>فقط مالک گروه (یا مالک ربات)</td></tr>
  </table>
  <div class="note">وقتی کسی تازه ادمین ربات می‌شود، خودِ ربات یک پیام خودکار برایش می‌فرستد و کامل توضیح می‌دهد الان چه کارهایی در این گروه می‌تواند انجام دهد.</div>
</section>

<section id="delete">
  <h2>🗑 ۶. حذف پیام‌ها</h2>
  <table>
    <tr><th>دستور</th><th>کار</th></tr>
    <tr><td><code>حذف 20</code> (یا هر عدد دیگر)</td><td>حذف همان تعداد پیام <u>اخیر</u> گروه</td></tr>
    <tr><td><code>حذف کل</code></td><td>حذف تمام پیام‌هایی که ربات از این گروه ثبت کرده - قبل از اجرا یک پیام تاییدیه با دو دکمه «بله»/«خیر» نشان می‌دهد که فقط خودِ همان ادمین می‌تواند بزند</td></tr>
  </table>
  <div class="note danger">
    ⚠️ <b>محدودیت خودِ تلگرام، نه ربات:</b> بات‌ها فقط اجازه دارند پیام‌های حداکثر ۴۸ ساعت اخیر را حذف کنند - این محدودیتی است که خودِ تلگرام روی همه‌ی بات‌ها می‌گذارد و هیچ رباتی نمی‌تواند دورش بزند. همچنین ربات فقط پیام‌هایی را می‌تواند حذف کند که خودش از زمان اضافه‌شدن به گروه دیده و ثبت کرده باشد؛ تاریخچه‌ی قبل از اضافه‌شدن ربات یا قبل از این آپدیت قابل دسترسی نیست.
  </div>
</section>

<section id="filters">
  <h2>🔒 ۷. کلمات فیلترشده</h2>
  <table>
    <tr><th>دستور</th><th>کار</th></tr>
    <tr><td><code>افزودن کلمه فیلتر [کلمه]</code></td><td>هر پیام عادی (نه از ادمین/مالک/VIP) که این کلمه را داشته باشد خودکار حذف می‌شود</td></tr>
    <tr><td><code>حذف کلمه فیلتر [کلمه]</code></td><td>برداشتن آن کلمه از لیست</td></tr>
    <tr><td><code>لیست کلمات فیلتر</code></td><td>نمایش همه‌ی کلمات فیلترشده‌ی این گروه</td></tr>
  </table>
</section>

<section id="welcome">
  <h2>👋 ۸. خوش‌آمدگویی و بدرود</h2>
  <p>هر دو به‌طور پیش‌فرض <b>فعال</b> هستند.</p>
  <table>
    <tr><th>دستور</th><th>کار</th></tr>
    <tr><td><code>تنظیم خوش آمدگویی [متن]</code></td><td>تغییر متن پیام خوش‌آمدگویی. جای‌گذاری‌های قابل‌استفاده: <code>{نام}</code>، <code>{منشن}</code>، <code>{گروه}</code></td></tr>
    <tr><td>ریپلای روی عکس/ویدیو/ویس + همان دستور بالا</td><td>آن رسانه را هم بخشی از پیام خوش‌آمدگویی می‌کند</td></tr>
    <tr><td><code>حذف رسانه خوش آمدگویی</code></td><td>برداشتن رسانه‌ی ضمیمه‌شده</td></tr>
    <tr><td><code>روشن کردن خوش آمدگویی</code> / <code>خاموش کردن خوش آمدگویی</code></td><td>-</td></tr>
    <tr><td><code>تنظیم بدرود [متن]</code></td><td>همین قابلیت‌ها برای پیام بدرود (وقتی کسی گروه را ترک می‌کند)</td></tr>
    <tr><td><code>روشن کردن بدرود</code> / <code>خاموش کردن بدرود</code></td><td>-</td></tr>
  </table>
</section>

<section id="spam">
  <h2>🛡 ۹. ضد اسپم و قفل‌های محتوا</h2>
  <h3>ضد اسپم (پیام‌های پشت‌سرهم)</h3>
  <table>
    <tr><th>دستور</th><th>کار</th></tr>
    <tr><td><code>تنظیم تعداد پیام مجاز [عدد]</code></td><td>مثلاً بیشتر از این تعداد پیام در ۳ ثانیه = اسپم (پیش‌فرض: ۶)</td></tr>
    <tr><td><code>تنظیم مدت سکوت اسپم [عدد]</code></td><td>مدت سکوت خودکار اسپم‌کننده، به دقیقه (پیش‌فرض: ۳۰ دقیقه)</td></tr>
    <tr><td><code>تنظیمات اسپم</code></td><td>نمایش تنظیمات فعلی این گروه</td></tr>
  </table>
  <p>واحد زمانی (۳ ثانیه) ثابت است و قابل تغییر نیست - فقط «چند پیام» و «چقدر سکوت» قابل تنظیم‌اند.</p>
  <h3>قفل‌های محتوا (از پنل → قفل‌ها قابل روشن/خاموش کردن)</h3>
  <p>این‌ها فقط روی اعضای <b>عادی</b> اثر دارند؛ مالک/ادمین/VIP همیشه معاف‌اند. پیش‌فرض: فقط «لینک» و «فوروارد» روشن‌اند.</p>
  <table>
    <tr><th>قفل</th><th>چه چیزی حذف می‌شود</th></tr>
    <tr><td>لینک</td><td>هر لینک وب یا دامنه‌ی داخل متن/کپشن</td></tr>
    <tr><td>فوروارد</td><td>هر پیام فوروارد شده</td></tr>
    <tr><td>فایل</td><td>هر سند/فایل ضمیمه</td></tr>
    <tr><td>استیکر</td><td>استیکر</td></tr>
    <tr><td>ویس</td><td>پیام صوتی و ویدیو-پیام (video note)</td></tr>
    <tr><td>گیف</td><td>انیمیشن/GIF</td></tr>
    <tr><td>مخاطب</td><td>اشتراک‌گذاری مخاطب (contact)</td></tr>
    <tr><td>نظرسنجی</td><td>نظرسنجی (poll)</td></tr>
    <tr><td>هشتگ</td><td>پیام‌های دارای #هشتگ</td></tr>
    <tr><td>منشن</td><td>پیام‌های دارای @منشن</td></tr>
  </table>
</section>

<section id="captcha">
  <h2>🤖 ۱۰. کپچای عضویت</h2>
  <p>پیش‌فرض: <b>خاموش</b>. مخصوص گروه‌هایی که در تنظیمات تلگرامشان «تایید درخواست عضویت» را فعال کرده‌اند.</p>
  <table>
    <tr><th>دستور</th><th>کار</th></tr>
    <tr><td><code>روشن کردن کپچا</code></td><td>فعال کردن</td></tr>
    <tr><td><code>خاموش کردن کپچا</code></td><td>غیرفعال کردن</td></tr>
  </table>
  <p>وقتی روشن باشد: هر کسی که درخواست عضویت بدهد، ربات در پیوی او یک سؤال جمع ساده (مثلاً ۳+۵) با ۴ گزینه می‌فرستد. جواب درست ظرف ۶۰ ثانیه → تایید خودکار عضویت. جواب غلط یا بی‌پاسخی → رد خودکار درخواست (کاربر می‌تواند دوباره درخواست بدهد).</p>
</section>

<section id="stats">
  <h2>📊 ۱۱. آمار و پروفایل</h2>
  <table>
    <tr><th>دستور</th><th>کار</th></tr>
    <tr><td><code>آمار روزانه</code></td><td>فعالیت ۲۴ ساعت گذشته: پرپیام‌ترین‌ها + بیشترین اضافه‌کننده‌های عضو</td></tr>
    <tr><td><code>آمار کل</code></td><td>همین آمار از ابتدای فعالیت گروه</td></tr>
    <tr><td><code>پروفایل</code></td><td>جزئیات یک کاربر (بخش ۴ را ببینید)</td></tr>
  </table>
</section>

<section id="images">
  <h2>🖼 ۱۲. تصاویر ربات (بنرها)</h2>
  <p>روی یک عکس ریپلای کنید و بنویسید <code>ثبت تصویر [کلید]</code>. این کار فقط برای <b>مالک ربات</b> است (نه مالک گروه) چون این تصاویر سراسری‌اند، نه مخصوص یک گروه.</p>
  <table>
    <tr><th>کلید</th><th>کجا استفاده می‌شود</th></tr>
    <tr><td><code>start_banner</code></td><td>پیام خوش‌آمدگویی وقتی کسی /start می‌زند (پیوی)</td></tr>
    <tr><td><code>help_banner</code></td><td>پیام اصلی «راهنما»</td></tr>
    <tr><td><code>panel_banner</code></td><td>پیام اصلی «پنل»</td></tr>
  </table>
  <p>ربات فقط <code>file_id</code> تلگرامی تصویر را ذخیره می‌کند، نه خودِ فایل را - یعنی هیچ بار اضافه‌ای روی سرور یا دیتابیس نمی‌گذارد، هر تعداد و هر حجمی که باشد.</p>
</section>

<section id="ping">
  <h2>🏓 ۱۳. پینگ</h2>
  <p>بنویسید <code>پینگ</code> (در گروه یا پیوی، برای همه، نه فقط ادمین‌ها) تا ربات با «پونگ! ربات روشن و در حال کار است» + زمان پاسخ به میلی‌ثانیه جواب دهد.</p>
</section>

<section id="rules">
  <h2>⚙️ ۱۴. قوانین مهم فنی</h2>
  <ul>
    <li><b>همه‌چیز متنی است، نه اسلش‌دار.</b> دستورات با «/» دیگر وجود ندارند (به‌جز <code>/start</code> که توضیحش در بخش ۲ آمد).</li>
    <li><b>تطبیق دقیق متن:</b> اکثر دستورات مدیریتی فقط وقتی پیام دقیقاً همان کلمه باشد اجرا می‌شوند - نوشتن آن کلمه داخل یک جمله‌ی عادی هیچ اثری ندارد (بخش ۴ را ببینید).</li>
    <li><b>هر گروه کاملاً مستقل است</b> - نقش‌ها، تنظیمات ضد اسپم، قفل‌ها، خوش‌آمدگویی، همه چیز per-group است.</li>
    <li><b>کیبورد فارسی/عربی:</b> ربات خودش تفاوت حروف «ی»/«ک» فارسی و عربی را که بعضی کیبوردها (خصوصاً آیفون) اشتباه می‌فرستند، مدیریت می‌کند - نیازی نیست نگرانش باشید.</li>
    <li><b>دکمه‌های شیشه‌ای (اینلاین) قفل‌شده‌اند:</b> در «راهنما»، «پنل»، و صفحه‌ی استارت، فقط همان کسی که آن پیام را باز کرده می‌تواند دکمه‌هایش را بزند - حتی ادمین‌های دیگر هم نمی‌توانند.</li>
    <li><b>حذف = بن دائم، نه کیک موقت:</b> در تلگرام کیک واقعی وجود ندارد؛ «کیک/بن/اخراج/سیک» هرکدام یعنی بن دائم تا کسی «رفع بن» کند.</li>
  </ul>
</section>

</div>

<footer>
  <p>این صفحه دستی نوشته و به‌روزرسانی می‌شود؛ اگر قابلیتی به ربات اضافه/حذف شد، همین‌جا هم باید آپدیت شود.</p>
  <a href="#top" class="back-to-top">⬆ بازگشت به بالا</a>
</footer>

</body>
</html>
"""


async def _handle_docs(request: web.Request) -> web.Response:
    return web.Response(text=DOCS_HTML, content_type="text/html", charset="utf-8")


def register_docs_route(app: web.Application, path: str = "/docs"):
    """Call once from bot.py's run_webhook() to expose the guide at <path>."""
    app.router.add_get(path, _handle_docs)