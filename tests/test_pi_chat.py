from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from zotero_agent_bridge.config import PiSettings, Settings
from zotero_agent_bridge.errors import BridgeError
from zotero_agent_bridge.pi_chat import PiChatManager


ITEM_A = "ITEMAAA1"
ITEM_B = "ITEMBBB2"


FAKE_PI_SOURCE = r'''
from __future__ import annotations
import argparse
import json
import os
import sys
import time
from pathlib import Path

parser = argparse.ArgumentParser(add_help=False)
parser.add_argument("--mode")
parser.add_argument("--session-dir")
parser.add_argument("--session")
parser.add_argument("--name")
parser.add_argument("--system-prompt")
parser.add_argument("--thinking")
parser.add_argument("--model")
args, unknown = parser.parse_known_args()

session_dir = Path(args.session_dir)
session_dir.mkdir(parents=True, exist_ok=True)
if args.session:
    session_file = Path(args.session)
else:
    session_file = session_dir / f"{args.name}.jsonl"
    if session_file.exists():
        session_file = session_dir / f"{args.name}-{time.time_ns()}.jsonl"
session_file.parent.mkdir(parents=True, exist_ok=True)
session_file.touch(exist_ok=True)
reported_session_file = session_file
if args.session and os.environ.get("FAKE_PI_REPORT_DIFFERENT_SESSION") == "1":
    reported_session_file = session_dir / f"different-{time.time_ns()}.jsonl"
    reported_session_file.touch(exist_ok=True)
messages = []
streaming = False
thinking_level = args.thinking or "medium"
available_thinking_levels = ["off", "minimal", "low", "medium", "high"]
current_model = {
    "provider": "test-provider",
    "id": "test-model-a",
    "name": "Test Model A",
    "reasoning": True,
    "contextWindow": 128000,
}
available_models = [
    current_model,
    {
        "provider": "test-provider",
        "id": "test-model-b",
        "name": "Test Model B",
        "reasoning": False,
        "contextWindow": 64000,
    },
]

log_path = os.environ.get("FAKE_PI_LOG")
if log_path:
    with Path(log_path).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({
            "cwd": os.getcwd(),
            "argv": sys.argv[1:],
            "session_file": str(session_file.resolve()),
        }) + "\n")

def send(payload):
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
    sys.stdout.flush()

for raw in sys.stdin:
    command = json.loads(raw)
    request_id = command.get("id")
    command_type = command.get("type")
    if command_type == "get_state":
        send({"id": request_id, "type": "response", "command": command_type, "success": True, "data": {
            "sessionFile": str(reported_session_file.resolve()),
            "sessionId": session_file.stem,
            "isStreaming": streaming,
            "model": current_model,
            "thinkingLevel": thinking_level,
        }})
    elif command_type == "get_available_thinking_levels":
        send({"id": request_id, "type": "response", "command": command_type, "success": True, "data": {"levels": list(available_thinking_levels)}})
    elif command_type == "set_thinking_level":
        level = command.get("level")
        if level not in available_thinking_levels:
            send({"id": request_id, "type": "response", "command": command_type, "success": False, "error": "unsupported thinking level"})
        else:
            thinking_level = level
            send({"id": request_id, "type": "response", "command": command_type, "success": True})
    elif command_type == "get_available_models":
        send({"id": request_id, "type": "response", "command": command_type, "success": True, "data": {"models": available_models}})
    elif command_type == "set_model":
        selected = next((model for model in available_models if model["provider"] == command.get("provider") and model["id"] == command.get("modelId")), None)
        if selected is None:
            send({"id": request_id, "type": "response", "command": command_type, "success": False, "error": "model not found"})
        else:
            current_model = selected
            send({"id": request_id, "type": "response", "command": command_type, "success": True, "data": current_model})
    elif command_type == "get_messages":
        send({"id": request_id, "type": "response", "command": command_type, "success": True, "data": {"messages": messages}})
    elif command_type == "prompt":
        message = command.get("message", "")
        images = command.get("images") or []
        content = message
        if images:
            content = ([{"type": "text", "text": message}] if message else []) + images
        messages.append({"role": "user", "content": content})
        streaming = True
        if message == "delay":
            time.sleep(10)
        if message == "lost-response":
            time.sleep(0.25)
        else:
            send({"id": request_id, "type": "response", "command": command_type, "success": True})
        send({"type": "agent_start"})
        if message == "malformed":
            sys.stdout.write("{not-json}\n")
            sys.stdout.flush()
        if message != "hold":
            answer = f"echo:{message}" + (f":images={len(images)}" if images else "")
            messages.append({"role": "assistant", "content": [{"type": "text", "text": answer}]})
            send({"type": "message_update", "assistantMessageEvent": {"type": "text_delta", "contentIndex": 0, "delta": answer}})
            streaming = False
            send({"type": "agent_settled"})
    elif command_type == "abort":
        streaming = False
        send({"id": request_id, "type": "response", "command": command_type, "success": True})
        send({"type": "agent_settled"})
    else:
        send({"id": request_id, "type": "response", "command": command_type, "success": False, "error": "unknown command"})

if os.environ.get("FAKE_PI_STUBBORN") == "1":
    time.sleep(60)
'''


class PiChatManagerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.fake_pi = self.root / "fake_pi.py"
        self.fake_pi.write_text(FAKE_PI_SOURCE, encoding="utf-8")
        self.launch_log = self.root / "launches.jsonl"
        self.prompt_path = self.root / "literature-assistant.md"
        self.prompt_path.write_text("You are a literature assistant.", encoding="utf-8")
        self.settings = Settings(
            host="127.0.0.1",
            port=8765,
            api_token="test-token",
            zotero_local_api_base="http://127.0.0.1:23119/api/users/0",
            bridge_home=self.root / "bridge-home",
            addon_timeout_seconds=1.0,
            addon_status_ttl_seconds=60.0,
            user_agent="PiChatTest/0.1",
            pi=PiSettings(
                executable="unused-in-test",
                session_dir=self.root / "pi-sessions",
                system_prompt_path=self.prompt_path,
                thinking_level="medium",
            ),
        )
        self.settings.prepare_runtime()
        self.pdf_a = self.root / "papers-a" / "a.pdf"
        self.pdf_b = self.root / "papers-b" / "b.pdf"
        self.pdf_same_dir = self.pdf_a.parent / "alternate.pdf"
        self.pdf_a.parent.mkdir()
        self.pdf_b.parent.mkdir()
        self.pdf_a.write_bytes(b"%PDF-a")
        self.pdf_b.write_bytes(b"%PDF-b")
        self.pdf_same_dir.write_bytes(b"%PDF-alternate")
        self.env_patch = patch.dict(os.environ, {"FAKE_PI_LOG": str(self.launch_log)})
        self.env_patch.start()
        self.managers: list[PiChatManager] = []

    def tearDown(self) -> None:
        for manager in self.managers:
            manager.close()
        self.env_patch.stop()
        self.temp_dir.cleanup()

    def manager(
        self,
        *,
        max_events: int = 2_000,
        stop_timeout_seconds: float = 1,
        request_timeout_seconds: float = 5,
        executable_command: list[str] | None = None,
    ) -> PiChatManager:
        manager = PiChatManager(
            self.settings,
            executable_command=executable_command or [sys.executable, str(self.fake_pi)],
            max_events=max_events,
            startup_timeout_seconds=5,
            request_timeout_seconds=request_timeout_seconds,
            stop_timeout_seconds=stop_timeout_seconds,
        )
        self.managers.append(manager)
        return manager

    def launches(self) -> list[dict[str, object]]:
        if not self.launch_log.exists():
            return []
        return [json.loads(line) for line in self.launch_log.read_text(encoding="utf-8").splitlines()]

    def wait_for_launches(self, count: int) -> list[dict[str, object]]:
        deadline = time.time() + 3
        while time.time() < deadline:
            launches = self.launches()
            if len(launches) >= count:
                return launches
            time.sleep(0.02)
        return self.launches()

    def test_prompt_stream_and_get_messages(self) -> None:
        manager = self.manager()
        opened = manager.open_item(ITEM_A, self.pdf_a, library_id=1)
        self.assertTrue(opened["running"])
        self.assertEqual(opened["cwd"], str(self.pdf_a.parent.resolve()))
        self.assertEqual(opened["session_identity"], f"1:{ITEM_A}")

        accepted = manager.prompt("summarize")
        self.assertTrue(accepted["success"])
        self.assertTrue(manager.wait_until_idle())

        event_result = manager.events_after(0)
        events = event_result["events"]
        deltas = [
            event["assistantMessageEvent"]["delta"]
            for event in events
            if event.get("type") == "message_update"
        ]
        self.assertEqual(deltas, ["echo:summarize"])
        self.assertTrue(all(event["item_key"] == ITEM_A for event in events))
        self.assertTrue(all(event["generation"] == event_result["generation"] for event in events))
        messages = manager.get_messages()["data"]["messages"]
        self.assertEqual(messages[0]["content"], "summarize")

        launch = self.wait_for_launches(1)[0]
        argv = launch["argv"]
        self.assertEqual(Path(launch["cwd"]), self.pdf_a.parent.resolve())
        self.assertIn("--mode", argv)
        self.assertIn("rpc", argv)
        self.assertIn("--no-tools", argv)
        self.assertIn("--no-approve", argv)
        self.assertNotIn("summarize", argv)

    def test_prompt_sends_rpc_image_content_and_allows_image_only_message(self) -> None:
        image = {
            "type": "image",
            "data": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9ZkGQAAAAASUVORK5CYII=",
            "mimeType": "image/png",
        }
        manager = self.manager()
        manager.open_item(ITEM_A, self.pdf_a)
        accepted = manager.prompt("", images=[image])
        self.assertTrue(accepted["success"])
        self.assertTrue(manager.wait_until_idle())
        messages = manager.get_messages()["data"]["messages"]
        self.assertEqual(messages[0]["content"], [image])
        self.assertEqual(messages[1]["content"][0]["text"], "echo::images=1")

    def test_available_models_switch_and_future_launch_preference(self) -> None:
        manager = self.manager()
        manager.open_item(ITEM_A, self.pdf_a)
        models = manager.get_available_models()
        self.assertEqual([model["id"] for model in models], ["test-model-a", "test-model-b"])

        switched = manager.set_model("test-provider", "test-model-b")
        self.assertEqual(switched["data"]["id"], "test-model-b")
        self.assertEqual(manager.get_state()["data"]["model"]["id"], "test-model-b")

        manager.open_item(ITEM_B, self.pdf_b)
        launches = self.wait_for_launches(2)
        self.assertIn("--model", launches[1]["argv"])
        model_index = launches[1]["argv"].index("--model")
        self.assertEqual(launches[1]["argv"][model_index + 1], "test-provider/test-model-b")

    def test_model_switch_is_rejected_while_streaming(self) -> None:
        manager = self.manager()
        manager.open_item(ITEM_A, self.pdf_a)
        manager.prompt("hold")
        with self.assertRaises(BridgeError) as caught:
            manager.set_model("test-provider", "test-model-b")
        self.assertEqual(caught.exception.code, "pi_session_busy")
        manager.abort()

    def test_thinking_level_switch_and_future_launch_preference(self) -> None:
        manager = self.manager()
        manager.open_item(ITEM_A, self.pdf_a)
        self.assertEqual(
            manager.get_available_thinking_levels(),
            ["off", "minimal", "low", "medium", "high"],
        )
        self.assertEqual(manager.get_thinking_level(), "medium")

        manager.set_thinking_level("high")
        self.assertEqual(manager.get_thinking_level(), "high")

        manager.open_item(ITEM_B, self.pdf_b)
        launches = self.wait_for_launches(2)
        thinking_index = launches[1]["argv"].index("--thinking")
        self.assertEqual(launches[1]["argv"][thinking_index + 1], "high")

    def test_thinking_level_change_is_rejected_while_streaming(self) -> None:
        manager = self.manager()
        manager.open_item(ITEM_A, self.pdf_a)
        manager.prompt("hold")
        with self.assertRaises(BridgeError) as caught:
            manager.set_thinking_level("high")
        self.assertEqual(caught.exception.code, "pi_session_busy")
        manager.abort()

    def test_invalid_thinking_level_is_rejected(self) -> None:
        manager = self.manager()
        manager.open_item(ITEM_A, self.pdf_a)
        with self.assertRaises(BridgeError) as caught:
            manager.set_thinking_level("ludicrous")
        self.assertEqual(caught.exception.status_code, 422)
        self.assertEqual(caught.exception.code, "invalid_pi_thinking_level")

    def test_switch_requires_abort_or_wait(self) -> None:
        manager = self.manager()
        manager.open_item(ITEM_A, self.pdf_a)
        manager.prompt("hold")
        self.assertTrue(manager.is_streaming)

        for item_key, path in ((ITEM_B, self.pdf_b), (ITEM_A, self.pdf_same_dir)):
            with self.assertRaises(BridgeError) as caught:
                manager.open_item(item_key, path)
            self.assertEqual(caught.exception.status_code, 409)
            self.assertEqual(caught.exception.code, "pi_session_busy")

        manager.abort()
        self.assertTrue(manager.wait_until_idle())
        opened = manager.open_item(ITEM_B, self.pdf_b)
        self.assertEqual(opened["item_key"], ITEM_B)
        self.assertEqual(Path(opened["cwd"]), self.pdf_b.parent.resolve())

    def test_session_mapping_is_persisted_and_resumed(self) -> None:
        manager = self.manager()
        first = manager.open_item(ITEM_A, self.pdf_a, library_id=7)
        session_file = Path(first["session_file"])
        document_id = first["document_id"]
        self.assertTrue(session_file.is_file())

        manager.open_item(ITEM_B, self.pdf_b)
        manager.open_item(ITEM_A, self.pdf_a, library_id=7)
        launches = self.wait_for_launches(3)
        self.assertEqual(len(launches), 3)
        resumed_argv = launches[2]["argv"]
        self.assertIn("--session", resumed_argv)
        self.assertIn(str(session_file.resolve()), resumed_argv)

        index = json.loads((self.settings.bridge_home / "pi-chat" / "session-index.json").read_text(encoding="utf-8"))
        self.assertEqual(index["version"], 2)
        self.assertEqual(Path(index["sessions"][document_id]["session_file"]), session_file.resolve())
        self.assertEqual(
            index["sessions"][document_id]["pdf_path"],
            os.path.normcase(str(self.pdf_a.resolve())),
        )

        manager.close()
        replacement = self.manager()
        reopened = replacement.open_item(ITEM_A, self.pdf_a, library_id=7)
        self.assertEqual(Path(reopened["session_file"]), session_file.resolve())

    def test_context_fingerprint_persists_across_restart_and_reset(self) -> None:
        fingerprint = "a" * 64
        changed = "b" * 64
        manager = self.manager()
        first = manager.open_item(ITEM_A, self.pdf_a, library_id=7)
        self.assertTrue(manager.context_injection_required(fingerprint))
        manager.mark_context_injected(fingerprint)
        self.assertFalse(manager.context_injection_required(fingerprint))
        self.assertTrue(manager.context_injection_required(changed))
        self.assertEqual(manager.status()["context_fingerprint"], fingerprint)

        index = json.loads((self.settings.bridge_home / "pi-chat" / "session-index.json").read_text(encoding="utf-8"))
        self.assertEqual(index["sessions"][first["document_id"]]["context_fingerprint"], fingerprint)

        manager.close()
        replacement = self.manager()
        replacement.open_item(ITEM_A, self.pdf_a, library_id=7)
        self.assertFalse(replacement.context_injection_required(fingerprint))
        self.assertTrue(replacement.context_injection_required(changed))

        replacement.reset_item(ITEM_A, self.pdf_a, library_id=7)
        replacement.open_item(ITEM_A, self.pdf_a, library_id=7)
        self.assertTrue(replacement.context_injection_required(fingerprint))
        self.assertIsNone(replacement.status()["context_fingerprint"])

    def test_resumed_fingerprint_is_discarded_when_pi_reports_a_different_session(self) -> None:
        fingerprint = "c" * 64
        manager = self.manager()
        first = manager.open_item(ITEM_A, self.pdf_a, library_id=7)
        intended_session = Path(first["session_file"])
        manager.mark_context_injected(fingerprint)
        manager.close()

        replacement = self.manager()
        with patch.dict(os.environ, {"FAKE_PI_REPORT_DIFFERENT_SESSION": "1"}):
            reopened = replacement.open_item(ITEM_A, self.pdf_a, library_id=7)

        self.assertNotEqual(Path(reopened["session_file"]), intended_session)
        self.assertIsNone(reopened["context_fingerprint"])
        self.assertTrue(replacement.context_injection_required(fingerprint))
        resumed_argv = self.wait_for_launches(2)[1]["argv"]
        self.assertIn("--session", resumed_argv)
        self.assertIn(str(intended_session.resolve()), resumed_argv)
        index = json.loads((self.settings.bridge_home / "pi-chat" / "session-index.json").read_text(encoding="utf-8"))
        self.assertIsNone(index["sessions"][reopened["document_id"]]["context_fingerprint"])

    def test_invalid_context_fingerprint_is_rejected(self) -> None:
        manager = self.manager()
        manager.open_item(ITEM_A, self.pdf_a)
        for fingerprint in ("", "not-sha256", "A" * 63, "g" * 64):
            with self.assertRaises(BridgeError) as caught:
                manager.context_injection_required(fingerprint)
            self.assertEqual(caught.exception.code, "invalid_context_fingerprint")

    def test_reset_forgets_mapping_without_deleting_previous_history(self) -> None:
        manager = self.manager()
        first = manager.open_item(ITEM_A, self.pdf_a, library_id=7)
        old_session = Path(first["session_file"])
        old_document = first["document_id"]
        self.assertTrue(old_session.is_file())

        reset = manager.reset_item(ITEM_A, self.pdf_a, library_id=7)
        self.assertTrue(reset["reset"])
        self.assertEqual(reset["document_id"], old_document)
        self.assertEqual(Path(reset["previous_session_file"]), old_session)
        self.assertTrue(old_session.is_file())
        self.assertFalse(manager.status()["running"])

        reopened = manager.open_item(ITEM_A, self.pdf_a, library_id=7)
        self.assertNotEqual(Path(reopened["session_file"]), old_session)
        launches = self.wait_for_launches(2)
        self.assertNotIn("--session", launches[1]["argv"])
        index = json.loads((self.settings.bridge_home / "pi-chat" / "session-index.json").read_text(encoding="utf-8"))
        self.assertIn(reopened["document_id"], index["sessions"])

        manager.prompt("hold")
        with self.assertRaises(BridgeError) as caught:
            manager.reset_item(ITEM_A, self.pdf_a, library_id=7)
        self.assertEqual(caught.exception.code, "pi_session_busy")
        manager.abort()

    def test_reset_archives_session_and_resume_restores_it(self) -> None:
        manager = self.manager()
        first = manager.open_item(ITEM_A, self.pdf_a, library_id=7)
        old_session = Path(first["session_file"])
        document_id = first["document_id"]

        manager.reset_item(ITEM_A, self.pdf_a, library_id=7)
        listing = manager.list_session_history(ITEM_A, self.pdf_a, library_id=7)
        self.assertEqual(listing["document_id"], document_id)
        self.assertEqual(len(listing["sessions"]), 1)
        archived = listing["sessions"][0]
        self.assertFalse(archived["current"])
        self.assertTrue(archived["available"])
        self.assertEqual(Path(archived["session_file"]), old_session)
        self.assertTrue(archived["archived_at"])
        old_session_id = archived["session_id"]

        second = manager.open_item(ITEM_A, self.pdf_a, library_id=7)
        new_session = Path(second["session_file"])
        self.assertNotEqual(new_session, old_session)
        listing = manager.list_session_history(ITEM_A, self.pdf_a, library_id=7)
        self.assertEqual(len(listing["sessions"]), 2)
        self.assertTrue(listing["sessions"][0]["current"])
        self.assertEqual(listing["sessions"][1]["session_id"], old_session_id)

        resumed = manager.resume_session(ITEM_A, self.pdf_a, library_id=7, session_id=old_session_id)
        self.assertTrue(resumed["resumed"])
        self.assertEqual(Path(resumed["session_file"]), old_session)
        self.assertFalse(manager.status()["running"])

        reopened = manager.open_item(ITEM_A, self.pdf_a, library_id=7)
        self.assertEqual(Path(reopened["session_file"]), old_session)
        launches = self.wait_for_launches(3)
        self.assertIn("--session", launches[2]["argv"])
        self.assertIn(str(old_session.resolve()), launches[2]["argv"])

        listing = manager.list_session_history(ITEM_A, self.pdf_a, library_id=7)
        self.assertEqual(len(listing["sessions"]), 2)
        self.assertTrue(listing["sessions"][0]["current"])
        self.assertEqual(Path(listing["sessions"][0]["session_file"]), old_session)
        self.assertEqual(Path(listing["sessions"][1]["session_file"]), new_session)
        self.assertFalse(listing["sessions"][1]["current"])

    def test_item_session_sources_span_documents_and_isolate_libraries(self) -> None:
        manager = self.manager()
        first = manager.open_item(ITEM_A, self.pdf_a, library_id=7)
        first_path = Path(first["session_file"])
        second = manager.open_item(ITEM_A, self.pdf_same_dir, library_id=7)
        second_path = Path(second["session_file"])
        other_library = manager.open_item(ITEM_A, self.pdf_b, library_id=8)
        other_path = Path(other_library["session_file"])

        sources = manager.list_item_session_sources(ITEM_A, library_id=7)
        paths = {Path(entry["session_file"]) for entry in sources}
        self.assertEqual(paths, {first_path, second_path})
        self.assertTrue(all(entry["document_id"] in {first["document_id"], second["document_id"]} for entry in sources))
        self.assertNotIn(other_path, paths)

        first_path.unlink()
        sources = manager.list_item_session_sources(ITEM_A, library_id=7)
        missing = next(entry for entry in sources if Path(entry["session_file"]) == first_path)
        self.assertFalse(missing["available"])

    def test_resume_session_rejects_unknown_and_escaping_handles(self) -> None:
        manager = self.manager()
        first = manager.open_item(ITEM_A, self.pdf_a, library_id=7)
        old_session = Path(first["session_file"])
        document_id = first["document_id"]
        manager.reset_item(ITEM_A, self.pdf_a, library_id=7)

        with self.assertRaises(BridgeError) as caught:
            manager.resume_session(ITEM_A, self.pdf_a, library_id=7, session_id="0" * 16)
        self.assertEqual(caught.exception.code, "pi_session_not_found")
        with self.assertRaises(BridgeError) as caught:
            manager.resume_session(ITEM_A, self.pdf_a, library_id=7, session_id="not-a-handle")
        self.assertEqual(caught.exception.code, "invalid_session_id")

        index_path = self.settings.bridge_home / "pi-chat" / "session-index.json"
        index = json.loads(index_path.read_text(encoding="utf-8"))
        outside = self.root / "outside-session.jsonl"
        outside.write_text("", encoding="utf-8")
        index["sessions"][document_id]["history"].append(
            {"session_file": str(outside), "archived_at": "2026-01-01T00:00:00+00:00", "last_used_at": None}
        )
        index_path.write_text(json.dumps(index), encoding="utf-8")
        outside_id = manager._session_handle(outside)
        with self.assertRaises(BridgeError) as caught:
            manager.resume_session(ITEM_A, self.pdf_a, library_id=7, session_id=outside_id)
        self.assertEqual(caught.exception.code, "pi_session_outside_session_dir")

        old_session.unlink()
        old_id = manager._session_handle(old_session)
        with self.assertRaises(BridgeError) as caught:
            manager.resume_session(ITEM_A, self.pdf_a, library_id=7, session_id=old_id)
        self.assertEqual(caught.exception.code, "pi_session_file_missing")

    def test_resume_session_blocks_while_streaming(self) -> None:
        manager = self.manager()
        first = manager.open_item(ITEM_A, self.pdf_a, library_id=7)
        old_session = Path(first["session_file"])
        manager.reset_item(ITEM_A, self.pdf_a, library_id=7)
        manager.open_item(ITEM_A, self.pdf_a, library_id=7)
        old_session_id = manager._session_handle(old_session)

        manager.prompt("hold")
        with self.assertRaises(BridgeError) as caught:
            manager.resume_session(ITEM_A, self.pdf_a, library_id=7, session_id=old_session_id)
        self.assertEqual(caught.exception.code, "pi_session_busy")
        manager.abort()
        self.assertTrue(manager.wait_until_idle())

        listing = manager.list_session_history(ITEM_A, self.pdf_a, library_id=7)
        self.assertTrue(listing["sessions"][0]["current"])
        self.assertEqual(listing["sessions"][1]["session_id"], old_session_id)

    def _write_orphan_session(self, name: str, session_name: str, user_text: str = "orphan question") -> Path:
        session_dir = self.settings.pi.session_dir
        session_dir.mkdir(parents=True, exist_ok=True)
        path = session_dir / name
        lines = [
            {"type": "session", "version": 3, "id": name.split(".")[0], "timestamp": "2026-08-19T10:19:37Z", "cwd": str(self.pdf_a.parent.resolve())},
            {"type": "session_info", "id": "si1", "parentId": None, "timestamp": "2026-08-19T10:19:38Z", "name": session_name},
            {"type": "message", "id": "m1", "parentId": "si1", "timestamp": "2026-08-19T10:19:40Z", "message": {"role": "user", "content": user_text}},
            {"type": "message", "id": "m2", "parentId": "m1", "timestamp": "2026-08-19T10:19:45Z", "message": {"role": "assistant", "content": [{"type": "text", "text": "orphan answer"}]}},
        ]
        path.write_text("\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8")
        return path

    def test_orphan_sessions_are_listed_and_resumable(self) -> None:
        manager = self.manager()
        opened = manager.open_item(ITEM_A, self.pdf_a, library_id=7)
        document_id = opened["document_id"]
        current_session = Path(opened["session_file"])
        session_name = f"zotero-{ITEM_A}-{document_id[:8]}"
        orphan = self._write_orphan_session("orphan-older.jsonl", session_name)
        unrelated = self._write_orphan_session("unrelated.jsonl", "someone-else")

        listing = manager.list_session_history(ITEM_A, self.pdf_a, library_id=7)
        orphan_entries = [entry for entry in listing["sessions"] if entry.get("orphan")]
        self.assertEqual(len(orphan_entries), 1)
        self.assertEqual(Path(orphan_entries[0]["session_file"]), orphan)
        self.assertTrue(orphan_entries[0]["available"])
        self.assertNotIn(unrelated, [Path(entry["session_file"]) for entry in listing["sessions"]])
        self.assertEqual(listing["sessions"][0]["session_file"], str(current_session))

        orphan_id = orphan_entries[0]["session_id"]
        resumed = manager.resume_session(ITEM_A, self.pdf_a, library_id=7, session_id=orphan_id)
        self.assertEqual(Path(resumed["session_file"]), orphan)
        reopened = manager.open_item(ITEM_A, self.pdf_a, library_id=7)
        self.assertEqual(Path(reopened["session_file"]), orphan)
        launches = self.wait_for_launches(2)
        self.assertIn("--session", launches[1]["argv"])
        self.assertIn(str(orphan.resolve()), launches[1]["argv"])

        listing = manager.list_session_history(ITEM_A, self.pdf_a, library_id=7)
        self.assertEqual(listing["sessions"][0]["session_file"], str(orphan))
        self.assertTrue(listing["sessions"][0]["current"])
        self.assertFalse(listing["sessions"][0].get("orphan", False))
        self.assertFalse(any(entry.get("orphan") for entry in listing["sessions"]))
        archived_current = [entry for entry in listing["sessions"] if entry["session_file"] == str(current_session)]
        self.assertEqual(len(archived_current), 1)
        self.assertFalse(archived_current[0]["current"])

    def test_orphan_listing_works_without_any_index_record(self) -> None:
        manager = self.manager()
        opened = manager.open_item(ITEM_A, self.pdf_a, library_id=7)
        document_id = opened["document_id"]
        session_name = f"zotero-{ITEM_A}-{document_id[:8]}"
        orphan = self._write_orphan_session("orphan-no-record.jsonl", session_name)
        manager.close()

        index_path = self.settings.bridge_home / "pi-chat" / "session-index.json"
        index_path.unlink()

        replacement = self.manager()
        listing = replacement.list_session_history(ITEM_A, self.pdf_a, library_id=7)
        self.assertEqual(len(listing["sessions"]), 1)
        self.assertTrue(listing["sessions"][0]["orphan"])
        self.assertEqual(Path(listing["sessions"][0]["session_file"]), orphan)

        resumed = replacement.resume_session(ITEM_A, self.pdf_a, library_id=7, session_id=listing["sessions"][0]["session_id"])
        self.assertEqual(Path(resumed["session_file"]), orphan)
        reopened = replacement.open_item(ITEM_A, self.pdf_a, library_id=7)
        self.assertEqual(Path(reopened["session_file"]), orphan)

    def test_same_item_key_different_pdf_never_leaks_session(self) -> None:
        manager = self.manager()
        first = manager.open_item(ITEM_A, self.pdf_a)
        first_session = Path(first["session_file"])
        first_document = first["document_id"]

        second = manager.open_item(ITEM_A, self.pdf_b)
        second_session = Path(second["session_file"])
        second_document = second["document_id"]
        self.assertNotEqual(first_document, second_document)
        self.assertNotEqual(first_session, second_session)
        launches = self.wait_for_launches(2)
        self.assertNotIn("--session", launches[1]["argv"])

        reopened = manager.open_item(ITEM_A, self.pdf_a)
        self.assertEqual(Path(reopened["session_file"]), first_session)
        launches = self.wait_for_launches(3)
        self.assertIn(str(first_session), launches[2]["argv"])

        index = json.loads((self.settings.bridge_home / "pi-chat" / "session-index.json").read_text(encoding="utf-8"))
        self.assertEqual(len(index["sessions"]), 2)

    def test_library_id_qualifies_session_identity(self) -> None:
        manager = self.manager()
        first = manager.open_item(ITEM_A, self.pdf_a, library_id=1)
        second = manager.open_item(ITEM_A, self.pdf_a, library_id=2)
        self.assertNotEqual(first["document_id"], second["document_id"])
        self.assertNotEqual(first["session_file"], second["session_file"])
        self.assertNotIn("--session", self.wait_for_launches(2)[1]["argv"])

    def test_events_reset_and_stale_process_output_is_ignored(self) -> None:
        manager = self.manager()
        first = manager.open_item(ITEM_A, self.pdf_a)
        old_process = manager._process
        old_generation = first["generation"]
        manager.prompt("first")
        self.assertTrue(manager.wait_until_idle())
        self.assertTrue(manager.events_after(0)["events"])

        second = manager.open_item(ITEM_B, self.pdf_b)
        self.assertEqual(manager.events_after(0)["events"], [])
        manager._handle_event(
            old_process,
            old_generation,
            {"type": "message_update", "assistantMessageEvent": {"type": "text_delta", "delta": "STALE"}},
        )
        self.assertEqual(manager.events_after(0)["events"], [])

        manager.prompt("second")
        self.assertTrue(manager.wait_until_idle())
        events = manager.events_after(0)["events"]
        self.assertTrue(events)
        self.assertTrue(all(event["generation"] == second["generation"] for event in events))
        self.assertNotIn("STALE", json.dumps(events))

    def test_abort_cleanup_and_bounded_event_cursor(self) -> None:
        manager = self.manager(max_events=3)
        manager.open_item(ITEM_A, self.pdf_a)
        manager.prompt("first")
        self.assertTrue(manager.wait_until_idle())
        manager.prompt("second")
        self.assertTrue(manager.wait_until_idle())
        result = manager.events_after(0)
        self.assertLessEqual(len(result["events"]), 3)
        self.assertTrue(result["cursor_expired"])

        manager.prompt("hold")
        manager.abort()
        self.assertTrue(manager.wait_until_idle())
        manager.close()
        self.assertFalse(manager.status()["running"])
        self.assertIsNone(manager.active_item_key)
        self.assertEqual(manager.events_after(0)["events"], [])

    def test_concurrent_prompt_close_fails_pending_without_request_timeout(self) -> None:
        manager = self.manager(stop_timeout_seconds=0.1, request_timeout_seconds=8)
        manager.open_item(ITEM_A, self.pdf_a)
        result: list[Exception | dict[str, object]] = []

        def send_delayed_prompt() -> None:
            try:
                result.append(manager.prompt("delay"))
            except Exception as exc:
                result.append(exc)

        thread = threading.Thread(target=send_delayed_prompt)
        thread.start()
        time.sleep(0.15)
        started = time.monotonic()
        manager.close()
        thread.join(timeout=3)
        elapsed = time.monotonic() - started
        self.assertFalse(thread.is_alive())
        self.assertLess(elapsed, 3)
        self.assertEqual(len(result), 1)
        self.assertIsInstance(result[0], BridgeError)
        self.assertEqual(result[0].code, "pi_rpc_error")

    def test_prompt_timeout_after_flush_stays_busy_and_persists_bound_fingerprint_from_events(self) -> None:
        fingerprint = "d" * 64
        manager = self.manager(request_timeout_seconds=0.05)
        manager.open_item(ITEM_A, self.pdf_a)
        persist_calls = 0
        original_save_index = manager._save_index

        def count_fingerprint_persist(index: dict[str, object]) -> None:
            nonlocal persist_calls
            sessions = index.get("sessions")
            if isinstance(sessions, dict) and any(
                isinstance(record, dict) and record.get("context_fingerprint") == fingerprint
                for record in sessions.values()
            ):
                persist_calls += 1
            original_save_index(index)

        manager._save_index = count_fingerprint_persist
        with self.assertRaises(BridgeError) as caught:
            manager.prompt("lost-response", context_fingerprint=fingerprint)
        self.assertEqual(caught.exception.code, "pi_rpc_outcome_unknown")
        self.assertIn("indeterminate", caught.exception.message)
        self.assertTrue(manager.is_streaming)
        with self.assertRaises(BridgeError) as retry:
            manager.prompt("lost-response", context_fingerprint=fingerprint)
        self.assertEqual(retry.exception.code, "pi_session_busy")
        with self.assertRaises(BridgeError) as switch:
            manager.open_item(ITEM_B, self.pdf_b)
        self.assertEqual(switch.exception.code, "pi_session_busy")

        self.assertTrue(manager.wait_until_idle(timeout=2))
        self.assertFalse(manager.context_injection_required(fingerprint))
        self.assertEqual(persist_calls, 1)
        messages = manager.get_messages()["data"]["messages"]
        self.assertEqual([message["content"] for message in messages if message["role"] == "user"], ["lost-response"])

    def test_definite_pre_write_failure_keeps_context_required_for_retry(self) -> None:
        fingerprint = "e" * 64
        manager = self.manager()
        manager.open_item(ITEM_A, self.pdf_a)
        process = manager._process
        self.assertIsNotNone(process)
        original_stdin = process.stdin
        self.assertIsNotNone(original_stdin)

        class FailFirstWrite:
            def __init__(self, wrapped) -> None:
                self.wrapped = wrapped
                self.failed = False

            def write(self, data):
                if not self.failed:
                    self.failed = True
                    raise BrokenPipeError("simulated pre-write failure")
                return self.wrapped.write(data)

            def flush(self):
                return self.wrapped.flush()

            def close(self):
                return self.wrapped.close()

        process.stdin = FailFirstWrite(original_stdin)
        with self.assertRaises(BridgeError) as caught:
            manager.prompt("retry-context", context_fingerprint=fingerprint)
        self.assertEqual(caught.exception.code, "pi_rpc_unavailable")
        self.assertFalse(manager.is_streaming)
        self.assertTrue(manager.context_injection_required(fingerprint))

        accepted = manager.prompt("retry-context", context_fingerprint=fingerprint)
        self.assertTrue(accepted["success"])
        self.assertTrue(manager.wait_until_idle())
        self.assertFalse(manager.context_injection_required(fingerprint))
        messages = manager.get_messages()["data"]["messages"]
        self.assertEqual([message["content"] for message in messages if message["role"] == "user"], ["retry-context"])

    def test_closed_stdin_is_reported_as_rpc_unavailable(self) -> None:
        manager = self.manager()
        manager.open_item(ITEM_A, self.pdf_a)
        manager._process.stdin.close()
        with self.assertRaises(BridgeError) as caught:
            manager.get_state()
        self.assertEqual(caught.exception.code, "pi_rpc_unavailable")

    def test_max_context_chars_and_idle_reaping(self) -> None:
        self.settings.pi.max_context_chars = 10
        self.settings.pi.idle_timeout_seconds = 0.05
        manager = self.manager()
        manager.open_item(ITEM_A, self.pdf_a)
        with self.assertRaises(BridgeError) as caught:
            manager.prompt("x" * 11)
        self.assertEqual(caught.exception.code, "pi_context_too_large")
        self.assertEqual(caught.exception.details["max_context_chars"], 10)
        manager.prompt("ok")
        self.assertTrue(manager.wait_until_idle())
        self.assertTrue(manager.events_after(0)["events"])
        time.sleep(0.07)
        self.assertTrue(manager.reap_idle())
        self.assertFalse(manager.status()["running"])
        self.assertEqual(manager.events_after(0)["events"], [])
        self.assertFalse(manager.reap_idle())

    def test_malformed_rpc_line_records_error_without_crashing(self) -> None:
        manager = self.manager()
        manager.open_item(ITEM_A, self.pdf_a)
        manager.prompt("malformed")
        self.assertTrue(manager.wait_until_idle())
        deadline = time.time() + 2
        while manager.status()["last_error"] is None and time.time() < deadline:
            time.sleep(0.02)
        self.assertEqual(manager.status()["last_error"]["code"], "pi_rpc_parse_error")
        self.assertTrue(manager.status()["running"])

    def test_windows_npm_shim_is_resolved_without_cmd_shell(self) -> None:
        shim_dir = self.root / "npm & safe"
        cli = shim_dir / "node_modules" / "pkg" / "dist" / "cli.js"
        cli.parent.mkdir(parents=True)
        cli.write_text("// fake cli", encoding="utf-8")
        node = shim_dir / "node.exe"
        node.write_bytes(b"")
        shim = shim_dir / "pi.cmd"
        shim.write_text(
            '@ECHO off\n"%_prog%" "%dp0%\\node_modules\\pkg\\dist\\cli.js" %*\n',
            encoding="utf-8",
        )
        self.settings.pi.executable = str(shim)
        self.prompt_path.write_text("Assistant & echo PWN | <input> ^caret %PATH% !bang!", encoding="utf-8")
        manager = PiChatManager(self.settings)
        self.managers.append(manager)
        with patch("zotero_agent_bridge.pi_runtime.platform.system", return_value="Windows"):
            command = manager._build_command(item_key=ITEM_A, document_id="a" * 64, session_file=None)
        self.assertEqual(Path(command[0]), node.resolve())
        self.assertEqual(Path(command[1]), cli.resolve())
        self.assertNotIn("cmd.exe", command[0].lower())
        self.assertIn("Assistant & echo PWN | <input> ^caret %PATH% !bang!", command)

    def test_missing_pi_executable_is_reported_without_starting_process(self) -> None:
        self.settings.pi.executable = "definitely-missing-pi-command"
        manager = PiChatManager(self.settings)
        self.managers.append(manager)
        with patch("zotero_agent_bridge.pi_runtime.shutil.which", return_value=None):
            status = manager.executable_status()
            self.assertFalse(status["available"])
            self.assertEqual(status["error"]["code"], "pi_executable_not_found")
            with self.assertRaises(BridgeError) as caught:
                manager.open_item(ITEM_A, self.pdf_a)
        self.assertEqual(caught.exception.code, "pi_executable_not_found")

    def test_item_key_metacharacters_are_rejected_before_launch(self) -> None:
        manager = self.manager()
        for unsafe in ("BAD&KEY!", "ABC|DEF1", "$(PWNED)", "AAAA BBB"):
            with self.assertRaises(BridgeError) as caught:
                manager.open_item(unsafe, self.pdf_a)
            self.assertEqual(caught.exception.code, "invalid_item_key")
        self.assertEqual(self.launches(), [])

    def test_taskkill_failure_falls_back_to_direct_kill(self) -> None:
        class FakeProcess:
            pid = 4321

            def __init__(self) -> None:
                self.killed = False

            def poll(self):
                return 0 if self.killed else None

            def send_signal(self, _signal):
                raise OSError("no console")

            def wait(self, timeout=None):
                if self.killed:
                    return 0
                raise subprocess.TimeoutExpired("fake", timeout)

            def kill(self):
                self.killed = True

        manager = self.manager()
        process = FakeProcess()
        completed = subprocess.CompletedProcess(["taskkill"], 1)
        with (
            patch("zotero_agent_bridge.pi_runtime.platform.system", return_value="Windows"),
            patch("zotero_agent_bridge.pi_runtime.subprocess.run", return_value=completed),
        ):
            manager._terminate_process_tree(process)
        self.assertTrue(process.killed)

    def test_forced_cleanup_terminates_stubborn_process(self) -> None:
        with patch.dict(os.environ, {"FAKE_PI_STUBBORN": "1"}):
            manager = self.manager(stop_timeout_seconds=0.1)
            manager.open_item(ITEM_A, self.pdf_a)
            process = manager._process
            self.assertIsNotNone(process)
            started = time.monotonic()
            manager.close()
            self.assertLess(time.monotonic() - started, 8)
            self.assertIsNotNone(process.poll())

    def test_rejects_invalid_pdf_and_library_id(self) -> None:
        manager = self.manager()
        with self.assertRaises(BridgeError) as caught:
            manager.open_item(ITEM_A, self.root / "missing.pdf")
        self.assertEqual(caught.exception.code, "invalid_pdf_path")
        text_file = self.root / "paper.txt"
        text_file.write_text("not pdf", encoding="utf-8")
        with self.assertRaises(BridgeError) as caught:
            manager.open_item(ITEM_A, text_file)
        self.assertEqual(caught.exception.code, "invalid_pdf_type")
        with self.assertRaises(BridgeError) as caught:
            manager.open_item(ITEM_A, self.pdf_a, library_id="bad/library")
        self.assertEqual(caught.exception.code, "invalid_library_id")


if __name__ == "__main__":
    unittest.main()
