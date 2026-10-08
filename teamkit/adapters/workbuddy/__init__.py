"""WorkBuddy adapter: package export/install and native Agent Teams sync."""

from __future__ import annotations

from typing import Any


def sync_run(store: Any) -> dict[str, Any]:
    from teamkit.adapters.workbuddy.native import sync_run as _sync

    return _sync(store)
