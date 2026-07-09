"""
utils/text.py
---------------
Normalizes incoming Persian text before matching it against trigger words.

WHY THIS EXISTS: many keyboards (iOS Persian keyboard especially, but also
some Android IMEs) send Arabic Yeh (ي, U+064A) and Arabic Kaf (ك, U+0643)
instead of the correct Persian Yeh (ی, U+06CC) and Persian Keheh (ک,
U+06A9). They render IDENTICALLY on screen, so this is invisible to the
person typing - but "پروفایل" (Persian ی) and "پروفايل" (Arabic ي) are
different strings in Python, so exact matches like `text in TRIGGERS`
silently fail. This is almost certainly why "پروفایل" and "آمار کل" (both
containing ی/ک) stopped working while triggers without those letters
(e.g. "بن") kept working fine.

Every place that compares message.text against a trigger word or prefix
should normalize the incoming text first with normalize_fa(). The trigger
constants themselves are already written with correct Persian characters,
so normalizing only the incoming side is enough.
"""

_ARABIC_TO_PERSIAN = str.maketrans(
    {
        "\u064a": "\u06cc",  # ي (Arabic Yeh) -> ی (Persian Yeh)
        "\u0649": "\u06cc",  # ى (Alef Maksura) -> ی
        "\u0643": "\u06a9",  # ك (Arabic Kaf) -> ک (Persian Keheh)
        # Arabic-Indic and Extended Arabic-Indic (Persian) digits -> ASCII
        "\u0660": "0", "\u0661": "1", "\u0662": "2", "\u0663": "3", "\u0664": "4",
        "\u0665": "5", "\u0666": "6", "\u0667": "7", "\u0668": "8", "\u0669": "9",
        "\u06f0": "0", "\u06f1": "1", "\u06f2": "2", "\u06f3": "3", "\u06f4": "4",
        "\u06f5": "5", "\u06f6": "6", "\u06f7": "7", "\u06f8": "8", "\u06f9": "9",
    }
)

# Invisible characters that sometimes sneak in from mobile keyboards and
# break trigger matching (ZWNJ is legitimate inside Persian words, but our
# trigger phrases don't rely on it, so it's safe to strip for matching).
_INVISIBLE_CHARS = ("\u200c", "\u200b", "\u200e", "\u200f", "\ufeff")


def normalize_fa(text: str) -> str:
    """Canonicalize Persian text for reliable trigger-word matching."""
    if not text:
        return text
    text = text.translate(_ARABIC_TO_PERSIAN)
    for ch in _INVISIBLE_CHARS:
        text = text.replace(ch, "")
    # Collapse repeated whitespace (some keyboards insert double spaces)
    return " ".join(text.split())


def strip_bot_mention(text: str) -> str:
    """
    Telegram appends "@YourBotUsername" to a "/" command in two very common
    cases: whenever the person TAPS it from the bot's own command menu in a
    group (not just when there are multiple bots), and always in channels.
    Our trigger sets/prefixes were only ever written as "/owner", "/admins",
    etc. with no "@..." suffix, so a plain `text in TRIGGERS` or
    `text.startswith(prefix)` check silently fails the moment Telegram adds
    that suffix - this is almost certainly why /owner, /admins, and
    /claimowner "did nothing": they likely arrived as
    "/owner@YourBotUsername" and never matched.
    """
    if not text.startswith("/"):
        return text
    head, _, rest = text.partition(" ")
    if "@" in head:
        head = head.split("@", 1)[0]
    return head + (" " + rest if rest else "")


def normalize_trigger(text: str) -> str:
    """normalize_fa() + strip_bot_mention() - use this (not normalize_fa
    alone) for anything that compares message text against a command/
    trigger word or prefix, whether Persian text or a "/" command."""
    return strip_bot_mention(normalize_fa(text))