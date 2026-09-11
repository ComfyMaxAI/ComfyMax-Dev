"""Minimal standalone registry for MMGP offload objects.

WanGP keeps a global registry so its UI/application can release models centrally.
The standalone FlashVSR engine only needs register/unregister bookkeeping; MMGP
continues to perform the actual profiling/offloading.
"""

from __future__ import annotations

from threading import RLock
from typing import Any

_LOCK = RLock()
_OBJECTS: dict[str, tuple[Any, Any]] = {}


def register_offloadobj(name: str, offloadobj: Any, release_callback=None) -> None:
    with _LOCK:
        _OBJECTS[name] = (offloadobj, release_callback)


def unregister_offloadobj(name: str, offloadobj: Any | None = None) -> None:
    with _LOCK:
        current = _OBJECTS.get(name)
        if current is None:
            return
        if offloadobj is None or current[0] is offloadobj:
            _OBJECTS.pop(name, None)


def get_offloadobj(name: str) -> Any | None:
    with _LOCK:
        current = _OBJECTS.get(name)
        return None if current is None else current[0]


def clear() -> None:
    with _LOCK:
        _OBJECTS.clear()
