from __future__ import annotations

import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path

from zotero_agent_bridge.config import Settings
from zotero_agent_bridge.errors import BridgeError
from zotero_agent_bridge.lifecycle import BridgeLifecycleController


class BridgeLifecycleControllerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="zab-lifecycle-"))

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def _settings(self, *, managed: bool = True, grace: float = 0.15) -> Settings:
        settings = Settings(
            host="127.0.0.1",
            port=18765,
            api_token="api-token",
            zotero_local_api_base="http://127.0.0.1:23119/api/users/0",
            bridge_home=self.root / "bridge",
            metadata_dir=self.root / "metadata",
            notes_dir=self.root / "notes",
            addon_timeout_seconds=1.0,
            addon_status_ttl_seconds=1.0,
            user_agent="LifecycleTest/0.1",
            lifecycle_owner_id="owner-id" if managed else None,
            lifecycle_owner_token="owner-secret" if managed else None,
            lifecycle_addon_exit_grace_seconds=grace,
            lifecycle_watchdog_interval_seconds=0.02,
        )
        settings.prepare_runtime()
        return settings

    def test_owner_token_is_required_for_managed_shutdown(self) -> None:
        lifecycle = BridgeLifecycleController(self._settings())
        stopped = threading.Event()
        lifecycle.set_shutdown_callback(stopped.set)

        with self.assertRaises(BridgeError) as mismatch:
            lifecycle.request_shutdown("wrong")
        self.assertEqual(mismatch.exception.status_code, 403)
        self.assertFalse(stopped.is_set())

        lifecycle.request_shutdown("owner-secret")
        self.assertTrue(stopped.wait(1.0))
        status = lifecycle.status()
        self.assertEqual(status["owner_id"], "owner-id")
        self.assertEqual(status["bridge_version"], "0.3.5")
        self.assertEqual(status["protocol_version"], 2)
        self.assertEqual(status["product_scope"], "zotero-pi-only")
        self.assertEqual(status["distribution"], "source")

    def test_unmanaged_bridge_cannot_be_stopped_by_addon(self) -> None:
        lifecycle = BridgeLifecycleController(self._settings(managed=False))
        lifecycle.set_shutdown_callback(lambda: None)
        with self.assertRaises(BridgeError) as unmanaged:
            lifecycle.request_shutdown("anything")
        self.assertEqual(unmanaged.exception.status_code, 409)
        self.assertFalse(lifecycle.status()["managed"])

    def test_stale_addon_watchdog_requests_shutdown(self) -> None:
        lifecycle = BridgeLifecycleController(self._settings(grace=0.08))
        stopped = threading.Event()
        lifecycle.set_shutdown_callback(stopped.set)
        lifecycle.start_watchdog(lambda: {"ready": False})
        try:
            self.assertTrue(stopped.wait(1.0))
        finally:
            lifecycle.stop_watchdog()

    def test_fresh_addon_prevents_watchdog_shutdown(self) -> None:
        lifecycle = BridgeLifecycleController(self._settings(grace=0.08))
        stopped = threading.Event()
        lifecycle.set_shutdown_callback(stopped.set)
        lifecycle.start_watchdog(lambda: {"ready": True})
        try:
            time.sleep(0.2)
            self.assertFalse(stopped.is_set())
        finally:
            lifecycle.stop_watchdog()


if __name__ == "__main__":
    unittest.main()
