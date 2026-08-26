from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

from zotero_agent_bridge.config import PiSettings, Settings
from zotero_agent_bridge.errors import BridgeError
from zotero_agent_bridge.pi_generation import PiOneShotGenerator


FAKE_SOURCE = r'''
import json, os, sys, time
log = os.environ.get("FAKE_GENERATOR_LOG")
if log:
    open(log, "w", encoding="utf-8").write(json.dumps(sys.argv[1:]))
for raw in sys.stdin:
    request = json.loads(raw)
    delay = os.environ.get("FAKE_GENERATOR_DELAY")
    if delay:
        time.sleep(float(delay))
    rid = request.get("id")
    print(json.dumps({"id": rid, "type": "response", "command": "prompt", "success": True}), flush=True)
    message = {"role": "assistant", "content": [{"type": "text", "text": "生成结果"}], "stopReason": os.environ.get("FAKE_STOP_REASON", "stop")}
    print(json.dumps({"type": "message_end", "message": message}), flush=True)
    if os.environ.get("FAKE_NO_AGENT_END") != "1":
        print(json.dumps({"type": "agent_end", "messages": [message], "willRetry": False}), flush=True)
    else:
        break
'''


class PiGenerationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.script = self.root / "fake.py"
        self.script.write_text(FAKE_SOURCE, encoding="utf-8")
        prompt = self.root / "prompt.md"
        prompt.write_text("system", encoding="utf-8")
        self.settings = Settings(
            host="127.0.0.1", port=8765, api_token="token",
            zotero_local_api_base="http://127.0.0.1:23119/api/users/0",
            bridge_home=self.root / "home", addon_timeout_seconds=1,
            addon_status_ttl_seconds=10, user_agent="test",
            pi=PiSettings(executable="pi", session_dir=self.root / "sessions", system_prompt_path=prompt),
        )
        self.settings.prepare_runtime()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_uses_ephemeral_safe_rpc_and_returns_final_text(self) -> None:
        log = self.root / "args.json"
        import os
        previous = os.environ.get("FAKE_GENERATOR_LOG")
        os.environ["FAKE_GENERATOR_LOG"] = str(log)
        try:
            generator = PiOneShotGenerator(self.settings, executable_command=[sys.executable, str(self.script)])
            self.assertEqual(generator.generate("input", system_prompt="internal", model="p/m", timeout_seconds=3), "生成结果")
        finally:
            if previous is None: os.environ.pop("FAKE_GENERATOR_LOG", None)
            else: os.environ["FAKE_GENERATOR_LOG"] = previous
        args = json.loads(log.read_text(encoding="utf-8"))
        for flag in ("--mode", "--no-session", "--no-tools", "--no-extensions", "--no-skills", "--no-context-files"):
            self.assertIn(flag, args)
        self.assertIn("p/m", args)

    def test_unlimited_generation_waits_for_completion(self) -> None:
        import os
        generator = PiOneShotGenerator(self.settings, executable_command=[sys.executable, str(self.script)])
        os.environ["FAKE_GENERATOR_DELAY"] = "0.1"
        try:
            self.assertEqual(
                generator.generate("input", system_prompt="internal", timeout_seconds=None),
                "生成结果",
            )
        finally:
            os.environ.pop("FAKE_GENERATOR_DELAY", None)

    def test_rejects_non_stop_early_exit_and_times_out(self) -> None:
        import os
        generator = PiOneShotGenerator(self.settings, executable_command=[sys.executable, str(self.script)])
        os.environ["FAKE_STOP_REASON"] = "length"
        try:
            with self.assertRaises(BridgeError) as stopped:
                generator.generate("input", system_prompt="internal", timeout_seconds=2)
            self.assertEqual(stopped.exception.code, "pi_generation_incomplete")
        finally:
            os.environ.pop("FAKE_STOP_REASON", None)
        os.environ["FAKE_NO_AGENT_END"] = "1"
        try:
            with self.assertRaises(BridgeError) as incomplete:
                generator.generate("input", system_prompt="internal", timeout_seconds=2)
            self.assertEqual(incomplete.exception.code, "pi_generation_failed")
        finally:
            os.environ.pop("FAKE_NO_AGENT_END", None)
        os.environ["FAKE_GENERATOR_DELAY"] = "2"
        try:
            with self.assertRaises(BridgeError) as timed:
                generator.generate("input", system_prompt="internal", timeout_seconds=0.1)
            self.assertEqual(timed.exception.code, "pi_generation_timeout")
        finally:
            os.environ.pop("FAKE_GENERATOR_DELAY", None)


if __name__ == "__main__":
    unittest.main()
