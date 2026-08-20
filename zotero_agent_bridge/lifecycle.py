from __future__ import annotations

import os
import secrets
import threading
import time
from collections.abc import Callable
from typing import Any

from .config import Settings
from .errors import BridgeError
from .utils import now_iso
from .version import BRIDGE_VERSION, LIFECYCLE_PROTOCOL_VERSION, bridge_distribution


ShutdownCallback = Callable[[], None]
StatusProvider = Callable[[], dict[str, Any]]


class BridgeLifecycleController:
    """Own authenticated shutdown and stale-add-on cleanup for managed Bridge runs."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.owner_id = settings.lifecycle_owner_id
        self._owner_token = settings.lifecycle_owner_token
        self.managed = bool(self.owner_id and self._owner_token)
        self.started_at = now_iso()
        self._shutdown_callback: ShutdownCallback | None = None
        self._status_provider: StatusProvider | None = None
        self._watchdog_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._shutdown_requested = threading.Event()

    def set_shutdown_callback(self, callback: ShutdownCallback) -> None:
        self._shutdown_callback = callback

    def status(self) -> dict[str, Any]:
        return {
            "managed": self.managed,
            "owner_id": self.owner_id if self.managed else None,
            "pid": os.getpid(),
            "started_at": self.started_at,
            "exit_with_addon": self.managed,
            "bridge_version": BRIDGE_VERSION,
            "protocol_version": LIFECYCLE_PROTOCOL_VERSION,
            "distribution": bridge_distribution(),
        }

    def require_owner(self, owner_token: str | None) -> None:
        if not self.managed or not self._owner_token:
            raise BridgeError(
                409,
                "bridge_not_plugin_managed",
                "This Bridge instance was not started by the Zotero add-on and will not be stopped by it",
            )
        if not owner_token or not secrets.compare_digest(owner_token, self._owner_token):
            raise BridgeError(403, "bridge_owner_mismatch", "Bridge owner token does not match")

    def request_shutdown(self, owner_token: str | None = None, *, require_owner: bool = True) -> None:
        if require_owner:
            self.require_owner(owner_token)
        callback = self._shutdown_callback
        if callback is None:
            raise BridgeError(503, "bridge_shutdown_unavailable", "Bridge shutdown controller is unavailable")
        if self._shutdown_requested.is_set():
            return
        self._shutdown_requested.set()
        threading.Timer(0.05, callback).start()

    def start_watchdog(self, status_provider: StatusProvider) -> None:
        if not self.managed or self._watchdog_thread is not None:
            return
        self._status_provider = status_provider
        self._stop_event.clear()
        self._watchdog_thread = threading.Thread(
            target=self._watchdog_loop,
            name="zab-addon-watchdog",
            daemon=True,
        )
        self._watchdog_thread.start()

    def stop_watchdog(self) -> None:
        self._stop_event.set()
        thread = self._watchdog_thread
        if thread and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        self._watchdog_thread = None

    def _watchdog_loop(self) -> None:
        unavailable_since: float | None = None
        interval = min(1.0, max(0.1, self.settings.lifecycle_watchdog_interval_seconds))
        grace = self.settings.lifecycle_addon_exit_grace_seconds
        while not self._stop_event.wait(interval):
            if self._shutdown_requested.is_set():
                return
            provider = self._status_provider
            try:
                ready = bool(provider and provider().get("ready"))
            except Exception:
                ready = False
            if ready:
                unavailable_since = None
                continue
            now = time.monotonic()
            if unavailable_since is None:
                unavailable_since = now
                continue
            if now - unavailable_since < grace:
                continue
            try:
                self.request_shutdown(require_owner=False)
            except BridgeError:
                pass
            return
