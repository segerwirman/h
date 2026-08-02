"""Phase 20 — Intent-specific bounded semantic reorder for Content Studio scene list.

Exact trusted surface: Content Studio local timeline (self._scenes).
Only bounded same-model reorder within same surface. No filesystem, no
upload, no browser, no generic drag coordinate, no path/secret leak.

Returns safe metadata only, never raw scene content, never path.
"""

from __future__ import annotations

_INTENT = "content_studio_scene_reorder"


def _is_int_valid(value: object) -> bool:
    if isinstance(value, bool):
        return False
    return isinstance(value, int)


def admit_reorder(from_index: object, to_index: object, size: object) -> dict:
    """Admit only bounded same-surface local scene reorder.

    Rules fail-closed:
    - from_index, to_index, size must be int (bool rejected)
    - 0 <= from_index < size
    - 0 <= to_index < size
    - size >= 2
    - from_index != to_index (no-op rejected)

    Returns {ok, from_index, to_index, intent} or {ok, reason}.
    """
    if not (_is_int_valid(from_index) and _is_int_valid(to_index) and _is_int_valid(size)):
        return {"ok": False, "reason": "content_reorder_type_rejected"}

    s = int(size)
    f = int(from_index)
    t = int(to_index)

    if s < 2:
        return {"ok": False, "reason": "content_reorder_size_rejected"}

    if not (0 <= f < s):
        return {"ok": False, "reason": "content_reorder_from_rejected"}

    if not (0 <= t < s):
        return {"ok": False, "reason": "content_reorder_to_rejected"}

    if f == t:
        return {"ok": False, "reason": "content_reorder_noop_rejected"}

    return {"ok": True, "from_index": f, "to_index": t, "intent": _INTENT}


def apply_reorder(scenes: list, from_index: int, to_index: int) -> list:
    """Pure helper — bounded reorder, returns new list order.

    Assumes indices already admitted via admit_reorder; still checks bounds.
    """
    admitted = admit_reorder(from_index, to_index, len(scenes))
    if not admitted.get("ok"):
        return list(scenes)
    f = admitted["from_index"]
    t = admitted["to_index"]
    items = list(scenes)
    item = items.pop(f)
    items.insert(t, item)
    return items


__all__ = ["admit_reorder", "apply_reorder"]
