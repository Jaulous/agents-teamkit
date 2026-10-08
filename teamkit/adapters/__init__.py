"""Host adapters.

An adapter maps the platform-neutral team model onto one host runtime. Each
adapter module may expose:

* ``sync_run(store) -> dict`` — ingest the host's native collaboration records
  (messages, member lifecycle, tasks) for a bound run into TeamKit ledgers.
* packaging/installation helpers used by its CLI sub-commands.

Core modules never import a concrete adapter at import time; they resolve one
through :func:`host_adapter` by the platform name recorded in a run binding.
"""

from __future__ import annotations

import importlib
from types import ModuleType
from typing import Any

_ADAPTERS = {
    "workbuddy": "teamkit.adapters.workbuddy",
}


def available_adapters() -> list[str]:
    return list(_ADAPTERS)


def host_adapter(platform: str) -> ModuleType | None:
    module_name = _ADAPTERS.get(platform or "")
    return importlib.import_module(module_name) if module_name else None


def sync_bound_run(store: Any) -> dict[str, Any] | None:
    """Ingest native host activity for a run bound to a host session.

    Sync is an observation, never a gate: any failure is reported in the
    returned dict and the calling command continues.
    """
    try:
        state = store.load_state()
    except Exception:  # noqa: BLE001 - uninitialized run: nothing to sync
        return None
    host = state.get("host") if isinstance(state.get("host"), dict) else None
    if not host:
        return None
    adapter = host_adapter(str(host.get("platform") or ""))
    if adapter is None or not hasattr(adapter, "sync_run"):
        return None
    try:
        return adapter.sync_run(store)
    except Exception as exc:  # noqa: BLE001 - observation must not break commands
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
