"""
utils/profanity_words.py
----------------------------
Base Persian profanity word list for قفل فحش (see utils/locks.py's
"profanity" lock and handlers/admin_commands.py's افزودن/حذف فحش commands).

SOURCE: https://github.com/amirshnll/Persian-Swear-Words (data.json, Apache-2.0
license), embedded here as a static list rather than fetched at runtime -
runtime network dependency on GitHub for a moderation feature would be a bad
idea (adds latency/failure modes to every message, and the bot shouldn't be
one GitHub outage away from its profanity filter silently going blank).

⚠️ IMPORTANT CAVEAT: this upstream list is broad, not curated for false
positives. It includes plain insults (احمق، بی‌شعور) but ALSO several
ordinary, non-vulgar words - animal names sometimes used as insults (خر،
گاو، گوسفند), ethnic-group names (ترک، فارس، لر، عرب), and everyday terms
(دوست دختر، دوست پسر، پریود، لخت، جوون). Turning this lock on WILL delete
some completely innocent messages. That's exactly why:
  - This lock defaults OFF (not in LOCKS_DEFAULT_ON in utils/locks.py) -
    an admin has to deliberately opt in from the panel.
  - Per-chat customization exists (افزودن فحش / حذف فحش - see
    handlers/admin_commands.py) specifically so a group that turns this on
    can immediately whitelist any base-list word that's causing false
    positives for their community, without waiting on a code change.

Words are matched via substring containment after utils.text.normalize_fa
normalization (same approach as the custom "کلمه فیلتر" system), so this is
intentionally simple/fast, not a full morphological analyzer - it will also
match the swear word inside a longer word that happens to contain it.
"""

BASE_PROFANITY_WORDS = frozenset({
    "کیری", "کسکش", "سگ پدر", "پدرسگ",
    "بی پدر", "مادرسگ", "جنده", "گایدی", "گایدن", "کیر", "عمتو",
    "خفه شو", "خفه", "خفه خون", "مرض داری", "مرضداری", "گردن دراز", "خری",
    "گاوی", "آشغال",
    "پپه", "خنگ", "دکل", "دله", "قرتی", "گوزو", "کونده", "کون ده", "گاگول",
    "ابله", "گنده گوز", "کس", "خارکیونی", "کله کاندومی", "گشاد", "دخترقرتی",
    "خواهرجنده", "مادرجنده", "لخت", "بخورش", "بپرسرش", "بپرروش", "بیابخورش",
    "میخوریش", "بمال", "دیوس خان", "زنشو", "زنتو", "زن جنده",
    "بکنمت", "بکن", "بکن توش", "بکنش", "لز", "سکس", "سکسی", "ساک",
    "ساک بزن", "پورن", "سکسیی", "کونن", "کیرر", "بدبخت", "خایه", "خایه مال",
    "خایه خور", "ممه", "دخترجنده", "کس ننت", "کیردوس",
    "مادرکونی", "خارکسده", "خارکس ده", "کیروکس", "کس و کیر", "زنا",
    "زنازاده", "ولدزنا", "ملنگ", "سادیسمی", "فاحشه", "خانم جنده",
    "فاحشه خانم", "سیکتیر", "سسکی", "کس خیس", "حشری", "گاییدن", "بکارت",
    "داف", "بچه کونی", "کسشعر", "سرکیر", "سوراخ کون", "حشری شدن",
    "کس کردن", "کس دادن", "بکن بکن", "شق کردن", "کس لیسیدن", "آب کیر",
    "جاکش", "جلق زدن", "جنده خانه", "شهوتی", "عن", "قس", "کردن", "کردنی",
    "کس کش", "کوس", "کیرمکیدن", "لاکونی", "پستان", "پستون", "آلت",
    "آلت تناسلی","مالوندن", "سولاخ", "جنسی", "دوجنسه",
    "سگ تو روحت", "بی غیرت", "نعشه", "بی عفت", "مادرقهوه", "پلشت", "پریود",
    "کله کیری", "کیرناز", "پشمام", "لختی", "کسکیر", "دوست دختر",
    "دوست پسر", "کونشو", "دول", "شنگول", "کیردراز", "داف ناز", "سکسیم",
    "کوص", "کون گنده", "کسخل", "کصخل", "کصکلک بازی",
    "بیناموس", "بی آبرو","باسن", "جکس", "کصکش", "سکس چت",
    "حرومزاده", "کونی","مادر جنده", "کث", "کص",
    "خارکسّه", "دهن گاییده", "پدر سگ",
    "پدر صلواتی", "بی خایه", "صیغه ای", "بچه کیونی",
    "اسگل", "اوسکل", "اوسگل", "اوصگل", "اوصکل", "دیوث", "دیوص", "قرمصاق",
    "قرمساق", "غرمساق", "غرمصاق", "فیلم سوپر", "چاقال", "چاغال", "چس خور",
    "کس خور", "کس خل", "کوس خور", "کوس خل", "کص لیس", "کث لیس", "کس لیس",
    "کوص لیس", "کوث لیس", "کوس لیس", "اوبی", "خارکونی", "کونی مقام",
    "شاش خالی", "دلقک", "عن دونی", "خار سولاخی", "سولاخ مادر", "عمه ننه",
    "خارتو", "بو زنا", "شاش بند", "کیونی", "کصپدر", "شغال", "خپل", "ساکر",
    "زن قوه", "پشم کون", "جنده پولی", "حرومی", "دودول طلا", "چوسو",
    "هزار پدر", "آبم اومد", "چس خوری", "کلفت", "حشر", "زارت",
    "گی مادر", "ظنا", "بی پدرو مادر", "کیرم دهنت", "بکیرم", "به تخم اقام",
    "کیر خر", "ننه مرده", "سلیطه", "لاشخور", "هرزه", "حروم‌لقمه",
    "پاچه‌خوار", "ارگاسم", "دول ننه", "مادر فاکر", "کصپولی",
    "ننه هزار کیر", "قرمدنگ", "توله سگ", "جفنگ", "ریدم", "شومبول",
    "دهنتو گاییدم", "بی مصرف", "خبیث", "زالو",
    "مغز پریودی", "کسپولی", "چرب کنش", "اوب", "فرو کن",
})