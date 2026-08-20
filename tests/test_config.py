from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from zotero_agent_bridge.config import Settings


class SettingsConfigTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="zab-config-"))

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_from_env_accepts_utf8_bom_config(self) -> None:
        config_path = self.root / "bridge-config.json"
        payload = {
            "host": "127.0.0.1",
            "port": 18765,
            "bridge_home": str(self.root / "bridge"),
            "metadata_dir": str(self.root / "metadata"),
            "notes_dir": str(self.root / "notes"),
            "pi": {
                "session_dir": str(self.root / "sessions"),
                "system_prompt_path": str(self.root / "prompt.md"),
            },
        }
        config_path.write_text(json.dumps(payload), encoding="utf-8-sig")

        with patch.dict(os.environ, {"ZOTERO_AGENT_BRIDGE_CONFIG": str(config_path)}):
            settings = Settings.from_env()

        self.assertEqual(settings.port, 18765)
        self.assertEqual(settings.bridge_home, self.root / "bridge")
        self.assertTrue(settings.generated_config_path.is_file())


if __name__ == "__main__":
    unittest.main()
