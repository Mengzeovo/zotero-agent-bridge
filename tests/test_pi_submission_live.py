from __future__ import annotations

import hashlib
import os
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from typing import Any

from pypdf import PdfWriter

from zotero_agent_bridge.config import PiSettings, Settings
from zotero_agent_bridge.errors import BridgeError
from zotero_agent_bridge.pi_chat import PiChatManager
from zotero_agent_bridge.session_transcript import content_text


@unittest.skipUnless(os.environ.get("ZOTERO_AGENT_BRIDGE_PI_LIVE_MODEL"), "需要设置实际可用的 Pi model 才能运行集成测试")
class PiSubmissionLiveTest(unittest.TestCase):
    def setUp(self) -> None:
        test_root = Path(__file__).resolve().parents[1] / "tmp" / "pi-submission-live"
        test_root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=test_root)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        prompt_path = self.root / "system-prompt.txt"
        prompt_path.write_text("严格按照用户要求回答，不使用工具。", encoding="utf-8")
        self.pdf = self.root / "paper.pdf"
        with PdfWriter() as writer:
            writer.add_blank_page(width=72, height=72)
            writer.write(self.pdf)
        self.settings = Settings(
            host="127.0.0.1",
            port=8765,
            api_token="",
            zotero_local_api_base="http://127.0.0.1:23119/api/users/0",
            bridge_home=self.root / "bridge-home",
            addon_timeout_seconds=30,
            addon_status_ttl_seconds=15,
            user_agent="PiSubmissionLiveTest",
            pi=PiSettings(
                executable=os.environ.get("ZOTERO_AGENT_BRIDGE_PI_EXECUTABLE", "pi"),
                model=os.environ["ZOTERO_AGENT_BRIDGE_PI_LIVE_MODEL"],
                session_dir=self.root / "sessions",
                system_prompt_path=prompt_path,
                thinking_level="off",
            ),
        )

    def create_manager(self) -> PiChatManager:
        manager = PiChatManager(self.settings, startup_timeout_seconds=30, request_timeout_seconds=15)
        self.addCleanup(manager.close)
        return manager

    def open_document(self, manager: PiChatManager) -> dict[str, Any]:
        state = manager.open_item("LIVEPI01", self.pdf)
        self.assertTrue(state["running"])
        self.assertIn("active_request", state)
        return {key: state[key] for key in ("instance_id", "generation", "document_id")}

    @staticmethod
    def submission_arguments(message: str, identity: dict[str, Any]) -> dict[str, Any]:
        return {
            "request_id": uuid.uuid4().hex,
            "request_digest": hashlib.sha256(message.encode("utf-8")).hexdigest(),
            "expected_identity": identity,
        }

    def wait_for_completed(self, manager: PiChatManager, arguments: dict[str, Any]) -> dict[str, Any]:
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            record = manager.submission_status(arguments["request_id"], arguments["request_digest"])
            if record["status"] in {"completed", "handled", "rejected", "aborted"}:
                self.assertEqual(record["status"], "completed", record)
                self.assertFalse(manager.status()["streaming"])
                return record
            time.sleep(0.05)
        self.fail("实际 Pi 提交未在 90 秒内完成")

    def user_messages(self, manager: PiChatManager) -> list[str]:
        response = manager.get_messages()
        return [content_text(message["content"]) for message in response["data"]["messages"] if message["role"] == "user"]

    def test_duplicate_busy_identity_and_persisted_submission(self) -> None:
        manager = self.create_manager()
        identity = self.open_document(manager)
        message = "请从 1 写到 60，每行一个数字，不添加其它内容。"
        arguments = self.submission_arguments(message, identity)
        fingerprint = hashlib.sha256(b"pi-submission-live-context").hexdigest()
        arguments["context_fingerprint"] = fingerprint
        initial = manager.prompt(message, **arguments)
        self.assertEqual(initial["request_id"], arguments["request_id"])
        duplicate = manager.prompt(message, **arguments)
        self.assertEqual(duplicate["request_id"], arguments["request_id"])

        conflict = {**arguments, "request_digest": hashlib.sha256(b"different").hexdigest()}
        with self.assertRaises(BridgeError) as conflicting:
            manager.prompt(message, **conflict)
        self.assertEqual(conflicting.exception.status_code, 409)
        with self.assertRaises(BridgeError) as conflicting_status:
            manager.submission_status(arguments["request_id"], conflict["request_digest"])
        self.assertEqual(conflicting_status.exception.status_code, 409)

        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            before_busy = manager.events_after(0)
            if before_busy["events"]:
                break
            time.sleep(0.01)
        self.assertTrue(before_busy["events"])
        self.assertTrue(manager.status()["streaming"])
        self.assertEqual(before_busy["instance_id"], identity["instance_id"])
        busy_message = "请仅回复数字 2。"
        busy_arguments = self.submission_arguments(busy_message, identity)
        with self.assertRaises(BridgeError) as busy:
            manager.prompt(busy_message, **busy_arguments)
        self.assertEqual(busy.exception.status_code, 409)
        after_busy = manager.events_after(0)
        self.assertEqual(after_busy["events"][:len(before_busy["events"])], before_busy["events"])
        self.assertGreaterEqual(after_busy["last_cursor"], before_busy["last_cursor"])

        completed = self.wait_for_completed(manager, arguments)
        self.assertTrue(completed["context_injected"])
        self.assertEqual(manager.status()["context_fingerprint"], fingerprint)
        self.assertEqual(self.user_messages(manager), [message])
        manager.close()

        restored = self.create_manager()
        persisted = restored.submission_status(arguments["request_id"], arguments["request_digest"])
        self.assertEqual(persisted["status"], "completed")
        self.assertEqual(persisted["event_cursor"], completed["event_cursor"])
        restored_identity = self.open_document(restored)
        self.assertNotEqual(restored_identity["instance_id"], identity["instance_id"])
        repeated = restored.prompt(message, **arguments)
        self.assertEqual(repeated["status"], "completed")
        self.assertEqual(self.user_messages(restored), [message])

        stale_arguments = self.submission_arguments("请仅回复数字 3。", identity)
        with self.assertRaises(BridgeError) as stale:
            restored.prompt("请仅回复数字 3。", **stale_arguments)
        self.assertEqual(stale.exception.status_code, 409)
        self.assertEqual(self.user_messages(restored), [message])
        with self.assertRaises(BridgeError) as missing:
            restored.submission_status(uuid.uuid4().hex)
        self.assertEqual(missing.exception.status_code, 404)

    def test_short_rpc_deadline_recovers_submission_without_resending(self) -> None:
        import psutil

        manager = self.create_manager()
        identity = self.open_document(manager)
        message = "请仅回复数字 947，不添加其它内容。"
        arguments = self.submission_arguments(message, identity)
        process = psutil.Process(manager._process.pid)
        process.suspend()
        try:
            manager.request_timeout_seconds = 0.05
            initial = manager.prompt(message, **arguments)
            self.assertEqual(initial["status"], "unknown")
            self.assertEqual(initial["error"]["code"], "pi_rpc_outcome_unknown")
            duplicate = manager.prompt(message, **arguments)
            self.assertEqual(duplicate["status"], "unknown")
        finally:
            process.resume()
        self.wait_for_completed(manager, arguments)
        manager.request_timeout_seconds = 15
        completed = manager.prompt(message, **arguments)
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(self.user_messages(manager), [message])

    def test_aborted_submission_does_not_change_the_next_submission(self) -> None:
        manager = self.create_manager()
        identity = self.open_document(manager)
        first_message = "请从 1 写到 200，每行一个数字，不添加其它内容。"
        first_arguments = self.submission_arguments(first_message, identity)
        accepted = manager.prompt(first_message, **first_arguments)
        self.assertEqual(accepted["status"], "accepted")
        self.assertTrue(manager.status()["streaming"])
        response = manager.abort()
        self.assertTrue(response["success"])
        first_record = manager.submission_status(first_arguments["request_id"], first_arguments["request_digest"])
        self.assertEqual(first_record["status"], "aborted")
        self.assertFalse(manager.status()["streaming"])
        self.assertIsNone(manager.status()["active_request"])
        self.assertTrue(any(event["type"] == "agent_settled" and event.get("aborted") for event in manager.events_after(0)["events"]))

        second_message = "请仅回复数字 269，不添加其它内容。"
        second_arguments = self.submission_arguments(second_message, identity)
        manager.prompt(second_message, **second_arguments)
        second_record = self.wait_for_completed(manager, second_arguments)
        self.assertEqual(second_record["request_id"], second_arguments["request_id"])
        self.assertIsNone(second_record["error"])
        self.assertEqual(manager.submission_status(first_arguments["request_id"]), first_record)
        self.assertEqual(self.user_messages(manager), [first_message, second_message])
        messages = manager.get_messages()["data"]["messages"]
        final = [message for message in messages if message["role"] == "assistant"][-1]
        self.assertEqual(content_text(final["content"]), "269")
        self.assertEqual(final["stopReason"], "stop")

    def test_process_exit_keeps_unknown_submission_after_manager_restart(self) -> None:
        import psutil

        manager = self.create_manager()
        identity = self.open_document(manager)
        message = "请仅回复数字 853，不添加其它内容。"
        arguments = self.submission_arguments(message, identity)
        process = psutil.Process(manager._process.pid)
        process.suspend()
        try:
            manager.request_timeout_seconds = 0.05
            initial = manager.prompt(message, **arguments)
            self.assertEqual(initial["status"], "unknown")
            process.kill()
            process.wait(timeout=10)
        finally:
            if process.is_running():
                process.resume()

        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            state = manager.status()
            if not state["running"] and state["active_request"] is None:
                break
            time.sleep(0.01)
        self.assertFalse(state["running"])
        self.assertIsNone(state["active_request"])
        interrupted = manager.submission_status(arguments["request_id"], arguments["request_digest"])
        self.assertEqual(interrupted["status"], "unknown")
        self.assertEqual(interrupted["error"]["code"], "pi_process_exited")
        manager.close()

        restored = self.create_manager()
        record = restored.submission_status(arguments["request_id"], arguments["request_digest"])
        self.assertEqual(record["status"], "unknown")
        self.assertEqual(record["error"]["code"], "pi_request_interrupted")
        self.open_document(restored)
        repeated = restored.prompt(message, **arguments)
        self.assertEqual(repeated["status"], "unknown")
        self.assertEqual(self.user_messages(restored), [])


if __name__ == "__main__":
    unittest.main()
