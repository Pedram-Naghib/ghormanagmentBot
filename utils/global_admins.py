"""
utils/global_admins.py
-------------------------
"ادمین کل" (Global Admin) - promoted by a Global Owner, has IDENTICAL
access to a hardcoded Global Owner (OWNER_USER_IDS in .env): full access,
every group, always. The one difference: a Global Admin can be REMOVED via
a bot command (by a Global Owner, or by whoever promoted them) - hardcoded
Global Owners can only be changed by editing .env and redeploying.

WHY AN IN-MEMORY CACHE, NOT A DIRECT DB CHECK:
is_super_admin() (see utils/permissions.py) is called on effectively every
single group message (it's part of is_normal_member(), the hottest path in
the bot - see handlers/antispam.py). Adding a DB round trip there would
undo the exact per-message-latency fix from the last round. Global admins
change rarely (an occasional bot-command action) and there are realistically
only a handful of them, so keeping the full set in memory - refreshed
immediately on every add/remove, and reloaded from the DB once at startup
via load() - costs nothing per message and is always correct within this
process's lifetime.
"""

from typing import Dict, Optional, Set

_global_admin_ids: Set[int] = set()
_promoted_by: Dict[int, int] = {}


async def load(db) -> None:
    """Call once at startup (after db.connect()) to seed the cache."""
    rows = await db.list_global_admins()
    _global_admin_ids.clear()
    _promoted_by.clear()
    for user_id, promoter_id in rows:
        _global_admin_ids.add(user_id)
        _promoted_by[user_id] = promoter_id


def is_global_admin(user_id: int) -> bool:
    return user_id in _global_admin_ids


def get_promoter(user_id: int) -> Optional[int]:
    return _promoted_by.get(user_id)


def list_ids() -> Set[int]:
    return set(_global_admin_ids)


async def add(db, user_id: int, promoted_by: int) -> None:
    await db.add_global_admin(user_id, promoted_by)
    _global_admin_ids.add(user_id)
    _promoted_by[user_id] = promoted_by


async def remove(db, user_id: int) -> None:
    await db.remove_global_admin(user_id)
    _global_admin_ids.discard(user_id)
    _promoted_by.pop(user_id, None)