from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from zotero_agent_bridge.config import PiSettings, Settings
from zotero_agent_bridge.errors import BridgeError
from zotero_agent_bridge.pi_generation import PiOneShotGenerator
from zotero_agent_bridge.pi_runtime import resolve_pi_executable


@unittest.skipUnless(os.environ.get("ZOTERO_AGENT_BRIDGE_PI_LIVE_MODEL"), "需要设置实际可用的 Pi model 才能运行集成测试")
class PiGenerationLiveTest(unittest.TestCase):
    def setUp(self) -> None:
        test_root = Path(__file__).resolve().parents[1] / "tmp" / "pi-generation-live"
        test_root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=test_root)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.settings = Settings(
            host="127.0.0.1",
            port=8765,
            api_token="",
            zotero_local_api_base="http://127.0.0.1:23119/api/users/0",
            bridge_home=self.root,
            addon_timeout_seconds=30,
            addon_status_ttl_seconds=15,
            user_agent="PiGenerationLiveTest",
            pi=PiSettings(
                executable=os.environ.get("ZOTERO_AGENT_BRIDGE_PI_EXECUTABLE", "pi"),
                model=os.environ["ZOTERO_AGENT_BRIDGE_PI_LIVE_MODEL"],
                session_dir=self.root / "sessions",
            ),
        )
        self.processes: list[subprocess.Popen[bytes]] = []

    def start_pi(self, command: list[str], **kwargs: object) -> subprocess.Popen[bytes]:
        process = subprocess.Popen(command, **kwargs)
        self.processes.append(process)
        return process

    def create_generator(self, **kwargs: object) -> PiOneShotGenerator:
        generator = PiOneShotGenerator(self.settings, popen_factory=self.start_pi, **kwargs)
        self.addCleanup(generator.close)
        return generator

    def assert_processes_stopped(self) -> None:
        self.assertTrue(self.processes)
        self.assertTrue(all(process.poll() is not None for process in self.processes))
        self.assertFalse(list(self.root.rglob("*.jsonl")))

    def test_generates_final_text_and_stops_isolated_process(self) -> None:
        generator = self.create_generator()
        result = generator.generate(
            "请仅回复数字 731，不要添加任何其它内容。",
            system_prompt="严格按照用户要求回答。",
            thinking="off",
            timeout_seconds=90,
        )
        self.assertEqual(result, "731")
        self.assert_processes_stopped()

    def test_deadline_terminates_real_pi_process(self) -> None:
        generator = self.create_generator()
        with self.assertRaises(BridgeError) as raised:
            generator.generate("请仅回复数字 1。", system_prompt="严格按照用户要求回答。", timeout_seconds=0.01)
        self.assertEqual(raised.exception.code, "pi_generation_timeout")
        self.assert_processes_stopped()

    def test_real_pi_exit_without_completion_is_rejected(self) -> None:
        command = resolve_pi_executable(self.settings.pi.executable)
        generator = self.create_generator(executable_command=[*command, "--version"])
        with self.assertRaises(BridgeError) as raised:
            generator.generate("请仅回复数字 1。", system_prompt="严格按照用户要求回答。", timeout_seconds=15)
        self.assertEqual(raised.exception.code, "pi_generation_failed")
        self.assert_processes_stopped()

    def test_empty_prompt_and_closed_generator_do_not_start_pi(self) -> None:
        generator = self.create_generator()
        with self.assertRaises(BridgeError) as empty:
            generator.generate(" \n", system_prompt="严格按照用户要求回答。", timeout_seconds=None)
        self.assertEqual(empty.exception.code, "pi_generation_empty_prompt")
        generator.close()
        with self.assertRaises(BridgeError) as closed:
            generator.generate("请仅回复数字 1。", system_prompt="严格按照用户要求回答。", timeout_seconds=None)
        self.assertEqual(closed.exception.code, "pi_generation_closed")
        self.assertFalse(self.processes)


if __name__ == "__main__":
    unittest.main()
