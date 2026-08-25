from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from zotero_agent_bridge.config import PiSettings, Settings


class PiOnlyConfigTest(unittest.TestCase):
    def _settings(self, root: Path, token: str = "") -> Settings:
        return Settings(
            host="127.0.0.1",
            port=8765,
            api_token=token,
            zotero_local_api_base="http://127.0.0.1:23119/api/users/0",
            bridge_home=root,
            addon_timeout_seconds=30.0,
            addon_status_ttl_seconds=15.0,
            user_agent="ZoteroPiAssistant/test",
            pi=PiSettings(),
        )

    def test_prepare_runtime_preserves_token_and_pi_session_identity(self) -> None:
        with tempfile.TemporaryDirectory(prefix="zpa-config-") as directory:
            bridge_home = Path(directory) / "zotero-agent-bridge"
            first = self._settings(bridge_home)
            first.prepare_runtime()
            token = first.api_token
            self.assertEqual(len(token), 48)
            self.assertEqual(first.pi.session_dir, bridge_home / "pi-sessions")
            self.assertTrue(first.pi.session_dir.is_dir())
            persisted = json.loads(first.generated_config_path.read_text(encoding="utf-8"))
            self.assertEqual(persisted, {"api_token": token})

            second = self._settings(bridge_home)
            second.prepare_runtime()
            self.assertEqual(second.api_token, token)
            self.assertEqual(second.generated_config_path, bridge_home / "bridge.generated.json")
            self.assertEqual(second.pi.session_dir, bridge_home / "pi-sessions")

    def test_explicit_token_updates_only_managed_token_file(self) -> None:
        with tempfile.TemporaryDirectory(prefix="zpa-config-") as directory:
            bridge_home = Path(directory) / "zotero-agent-bridge"
            settings = self._settings(bridge_home, token="explicit-stable-token")
            settings.prepare_runtime()
            persisted = json.loads(settings.generated_config_path.read_text(encoding="utf-8"))
            self.assertEqual(persisted, {"api_token": "explicit-stable-token"})
            self.assertFalse((bridge_home / "mirror").exists())


if __name__ == "__main__":
    unittest.main()
