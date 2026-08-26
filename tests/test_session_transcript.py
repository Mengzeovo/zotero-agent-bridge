from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from zotero_agent_bridge.session_transcript import (
    deduplicate_exchanges,
    finalized_pairs_from_messages,
    read_session_transcript,
)


class SessionTranscriptTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _write(self, name: str, entries: list[dict]) -> Path:
        path = self.root / name
        path.write_text("\n".join(json.dumps(entry, ensure_ascii=False) for entry in entries) + "\n", encoding="utf-8")
        return path

    def test_reconstructs_active_branch_and_ignores_aborted_and_image_data(self) -> None:
        entries = [
            {"type": "session", "timestamp": "2026-01-01T00:00:00Z"},
            {"type": "message", "id": "u1", "parentId": None, "message": {"role": "user", "content": "root"}},
            {"type": "message", "id": "a1", "parentId": "u1", "message": {"role": "assistant", "content": [{"type": "text", "text": "root answer"}], "stopReason": "stop"}},
            {"type": "message", "id": "u-old", "parentId": "a1", "message": {"role": "user", "content": "abandoned"}},
            {"type": "message", "id": "a-old", "parentId": "u-old", "message": {"role": "assistant", "content": "old answer", "stopReason": "stop"}},
            {"type": "compaction", "id": "c1", "parentId": "a1", "summary": "ignored"},
            {"type": "message", "id": "u2", "parentId": "c1", "message": {"role": "user", "content": [{"type": "text", "text": "image question"}, {"type": "image", "data": "SECRET", "mimeType": "image/png"}]}},
            {"type": "message", "id": "abort", "parentId": "u2", "message": {"role": "assistant", "content": "partial", "stopReason": "aborted"}},
            {"type": "message", "id": "a2", "parentId": "abort", "message": {"role": "assistant", "content": [{"type": "thinking", "thinking": "hidden"}, {"type": "text", "text": "final answer"}], "stopReason": "stop"}},
        ]
        transcript = read_session_transcript(self._write("session.jsonl", entries))
        self.assertEqual([(e.question, e.answer) for e in transcript.exchanges], [("root", "root answer"), ("image question", "final answer")])
        self.assertEqual(transcript.exchanges[-1].image_count, 1)
        self.assertNotIn("SECRET", transcript.exchanges[-1].question or "")

    def test_session_identity_and_active_branch_digest_change_on_append(self) -> None:
        path = self._write("identity.jsonl", [
            {"type": "session_info", "id": "session-identity", "timestamp": "2026-01-01T00:00:00Z"},
            {"type": "message", "id": "u1", "parentId": None, "message": {"role": "user", "content": "q1"}},
            {"type": "message", "id": "a1", "parentId": "u1", "message": {"role": "assistant", "content": "a1", "stopReason": "stop"}},
        ])
        first = read_session_transcript(path)
        self.assertEqual(first.session_id, "session-identity")
        self.assertIsNotNone(first.branch_digest)
        entries = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        entries.extend([
            {"type": "message", "id": "u2", "parentId": "a1", "message": {"role": "user", "content": "q2"}},
            {"type": "message", "id": "a2", "parentId": "u2", "message": {"role": "assistant", "content": "a2", "stopReason": "stop"}},
        ])
        path.write_text("\n".join(json.dumps(entry, ensure_ascii=False) for entry in entries) + "\n", encoding="utf-8")
        second = read_session_transcript(path)
        self.assertEqual(len(second.exchanges), 2)
        self.assertNotEqual(first.branch_digest, second.branch_digest)

    def test_deduplicates_cloned_content_and_projects_image_question(self) -> None:
        response = {"data": {"messages": [
            {"role": "user", "content": [{"type": "image", "data": "SECRET", "mimeType": "image/png"}]},
            {"role": "assistant", "content": "answer", "stopReason": "stop"},
        ]}}
        self.assertEqual(finalized_pairs_from_messages(response), [("图片提问（附图 1 张）", "answer")])
        path = self._write("one.jsonl", [
            {"type": "message", "id": "u", "parentId": None, "message": {"role": "user", "content": "q"}},
            {"type": "message", "id": "a", "parentId": "u", "message": {"role": "assistant", "content": "a", "stopReason": "stop"}},
        ])
        first = read_session_transcript(path)
        self.assertEqual(len(deduplicate_exchanges([first, first])), 1)

    def test_missing_and_malformed_sessions_report_warnings(self) -> None:
        missing = read_session_transcript(self.root / "missing.jsonl")
        self.assertIn("session_file_missing", missing.warnings)
        path = self.root / "bad.jsonl"
        path.write_text("{bad}\n", encoding="utf-8")
        bad = read_session_transcript(path)
        self.assertTrue(any(warning.startswith("malformed_lines") for warning in bad.warnings))


if __name__ == "__main__":
    unittest.main()
