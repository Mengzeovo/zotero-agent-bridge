from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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

    def test_experience_note_generation_is_unlimited_by_default(self) -> None:
        pi = PiSettings()
        self.assertFalse(pi.experience_timeout_enabled)
        self.assertEqual(pi.experience_call_timeout_seconds, 600.0)
        self.assertEqual(pi.note_title_timeout_seconds, 20.0)
        self.assertEqual(pi.idle_timeout_seconds, 1800.0)
        self.assertEqual(pi.experience_extraction_chunk_chars, 100_000)
        self.assertEqual(pi.experience_structure_max_chars, 250_000)
        self.assertEqual(pi.experience_cross_link_max_calls, 8)
        self.assertTrue(pi.experience_coverage_audit)
        self.assertEqual(pi.experience_json_repair_attempts, 1)

    def test_knowledge_pipeline_config_validation(self) -> None:
        with self.assertRaises(ValueError):
            PiSettings(experience_extraction_chunk_chars=9999).validate()
        with self.assertRaises(ValueError):
            PiSettings(experience_structure_max_chars=9999).validate()
        with self.assertRaises(ValueError):
            PiSettings(experience_json_repair_attempts=2).validate()
        with self.assertRaises(ValueError):
            PiSettings(experience_cross_link_max_calls=65).validate()

    def test_config_file_can_disable_json_repair_with_zero(self) -> None:
        with tempfile.TemporaryDirectory(prefix="zpa-config-zero-") as directory:
            root = Path(directory)
            config_path = root / "config.json"
            config_path.write_text(json.dumps({
                "bridge_home": str(root / "home"),
                "pi": {"experience_json_repair_attempts": 0},
            }), encoding="utf-8")
            environment = {"ZOTERO_AGENT_BRIDGE_CONFIG": str(config_path)}
            with patch.dict(os.environ, environment, clear=False):
                os.environ.pop("ZOTERO_AGENT_BRIDGE_PI_EXPERIENCE_JSON_REPAIR_ATTEMPTS", None)
                settings = Settings.from_env()
            self.assertEqual(settings.pi.experience_json_repair_attempts, 0)

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
