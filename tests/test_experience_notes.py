from __future__ import annotations

import json
import tempfile
from dataclasses import replace
import time
import unittest
from pathlib import Path
from typing import Any

from zotero_agent_bridge.config import PiSettings, Settings
from zotero_agent_bridge.errors import BridgeError
from zotero_agent_bridge.experience_knowledge import exchange_content_digest
from zotero_agent_bridge.experience_notes import (
    EXPERIENCE_NOTE_MARKER,
    ExperienceJob,
    ExperienceNoteIndex,
    ExperienceNoteJobManager,
    ExperienceSnapshot,
)
from zotero_agent_bridge.session_transcript import read_session_transcript


class FakeGenerator:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.error: BridgeError | None = None
        self.closed = False
        self.invalid_output = False
        self.omit_last_unit = False
        self.emit_correction = False
        self.unknown_exchange = False
        self.unknown_unit = False
        self.merge_all = False
        self.self_relation = False
        self.unknown_provenance = False
        self.extra_field = False
        self.merge_first_two = False
        self.emit_extends = False
        self.emit_named_correction = False
        self.merge_named_equivalents = False
        self.emit_named_extends = False
        self.fail_on_call_once: int | None = None

    def generate(self, prompt: str, **kwargs: Any) -> str:
        self.calls.append({"prompt": prompt, **kwargs})
        if self.fail_on_call_once == len(self.calls):
            self.fail_on_call_once = None
            raise BridgeError(504, "pi_generation_timeout", "Internal Pi generation timed out")
        if self.error:
            raise self.error
        system_prompt = str(kwargs.get("system_prompt") or "")
        if self.invalid_output:
            return "not-json"
        source = prompt.split("<ZAB_EXPERIENCE_SOURCE>\n", 1)[1].split("\n</ZAB_EXPERIENCE_SOURCE>", 1)[0]
        payload = json.loads(source)
        if system_prompt.startswith("你是研究学习成果提取器"):
            evidence = [
                {
                    "source_exchange_id": "unknown-exchange" if self.unknown_exchange and index == 0 else exchange["source_exchange_id"],
                    "kind": "concept",
                    "title": f"知识 {index + 1}",
                    "content": exchange.get("answer") or exchange.get("content_fragment") or "",
                    "formulas": [],
                    "steps": [],
                    "examples": [],
                    "conditions": [],
                    "limitations": [],
                    "open_questions": [],
                }
                for index, exchange in enumerate(payload["exchanges"])
            ]
            result = {"evidence": evidence, "no_knowledge_exchange_ids": []}
            if self.extra_field:
                result["unsupported"] = True
            return json.dumps(result, ensure_ascii=False)
        if system_prompt.startswith("你是学习成果遗漏审计器"):
            ids = [exchange["source_exchange_id"] for exchange in payload["exchanges"]]
            return json.dumps({"evidence": [], "no_knowledge_exchange_ids": ids}, ensure_ascii=False)
        unit_ids = [unit["unit_id"] for unit in payload.get("units", [])]
        section_ids = unit_ids[:-1] if self.omit_last_unit and unit_ids else unit_ids
        relations = []
        if self.emit_correction and len(unit_ids) >= 2:
            relations.append({
                "from_unit_id": unit_ids[-1],
                "to_unit_id": unit_ids[0],
                "relation": "corrects",
                "rationale": "新认识修正旧认识",
                "source_exchange_ids": [],
            })
        if self.emit_named_extends:
            equivalent = [unit for unit in payload.get("units", []) if "同一概念" in str(unit.get("content") or "")]
            supplement = next((unit for unit in payload.get("units", []) if "补充知识" in str(unit.get("content") or "")), None)
            if equivalent and supplement:
                relations.append({
                    "from_unit_id": equivalent[0]["unit_id"],
                    "to_unit_id": supplement["unit_id"],
                    "relation": "extends",
                    "rationale": "知识补充关系",
                    "source_exchange_ids": [],
                })
        if self.emit_named_correction:
            old_unit = next((unit for unit in payload.get("units", []) if "旧认识" in str(unit.get("content") or "")), None)
            new_unit = next((unit for unit in payload.get("units", []) if "新认识" in str(unit.get("content") or "")), None)
            if old_unit and new_unit:
                relations.append({
                    "from_unit_id": new_unit["unit_id"],
                    "to_unit_id": old_unit["unit_id"],
                    "relation": "corrects",
                    "rationale": "跨分区新认识修正旧认识",
                    "source_exchange_ids": [],
                })
        if self.emit_extends and len(unit_ids) >= 2:
            relations.append({
                "from_unit_id": unit_ids[0],
                "to_unit_id": unit_ids[-1],
                "relation": "extends",
                "rationale": "知识补充关系",
                "source_exchange_ids": [],
            })
        if self.self_relation and unit_ids:
            relations.append({
                "from_unit_id": unit_ids[0],
                "to_unit_id": unit_ids[0],
                "relation": "extends",
                "rationale": "非法自关系",
                "source_exchange_ids": [],
            })
        if self.unknown_provenance and len(unit_ids) >= 2:
            relations.append({
                "from_unit_id": unit_ids[0],
                "to_unit_id": unit_ids[1],
                "relation": "extends",
                "rationale": "非法来源",
                "source_exchange_ids": ["unknown-exchange"],
            })
        if self.unknown_unit:
            section_ids = [*section_ids, "unknown-unit"]
        return json.dumps({
            "merge_groups": (
                [{"unit_ids": unit_ids}] if self.merge_all and len(unit_ids) >= 2
                else (
                    [{"unit_ids": [unit["unit_id"] for unit in payload.get("units", []) if "同一概念" in str(unit.get("content") or "")]}]
                    if self.merge_named_equivalents and len([unit for unit in payload.get("units", []) if "同一概念" in str(unit.get("content") or "")]) >= 2
                    else ([{"unit_ids": unit_ids[:2]}] if self.merge_first_two and len(unit_ids) >= 2 else [])
                )
            ),
            "sections": [{"title": "核心概念", "unit_ids": section_ids}],
            "relations": relations,
        }, ensure_ascii=False)

    def close(self) -> None:
        self.closed = True


class FakeWriter:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.note_key = "EXPNOTE1"
        self.error: BridgeError | None = None

    def execute(self, command: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((command, dict(payload)))
        if self.error:
            raise self.error
        return {
            "library_id": 7,
            "item_key": payload["item_key"],
            "note_key": self.note_key,
            "version": len(self.calls),
            "created": not bool(payload.get("note_key")),
        }


class ExperienceNotesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        prompt = self.root / "prompt.md"
        prompt.write_text("system", encoding="utf-8")
        self.settings = Settings(
            host="127.0.0.1",
            port=8765,
            api_token="token",
            zotero_local_api_base="http://127.0.0.1:23119/api/users/0",
            bridge_home=self.root / "home",
            addon_timeout_seconds=1,
            addon_status_ttl_seconds=10,
            user_agent="test",
            pi=PiSettings(
                executable="pi",
                session_dir=self.root / "sessions",
                system_prompt_path=prompt,
                experience_chunk_chars=10_000,
                experience_call_timeout_seconds=5,
                experience_total_timeout_seconds=20,
            ),
        )
        self.settings.prepare_runtime()
        self.generator = FakeGenerator()
        self.writer = FakeWriter()
        self.index = ExperienceNoteIndex(self.root / "home" / "pi-chat" / "experience-note-index.json")
        self.manager = ExperienceNoteJobManager(
            self.settings,
            generator=self.generator,
            writer=self.writer,
            render_markdown=lambda value: f"<article>{value}</article>",
            normalize_markdown=lambda value: value,
            index=self.index,
        )

    def tearDown(self) -> None:
        self.manager.close()
        self.temp.cleanup()

    def _session(self, name: str, pairs: int = 2) -> Path:
        path = self.root / name
        entries: list[dict[str, Any]] = []
        parent = None
        for index in range(pairs):
            user_id = f"{name}-u{index}"
            assistant_id = f"{name}-a{index}"
            entries.append({
                "type": "message",
                "id": user_id,
                "parentId": parent,
                "message": {"role": "user", "content": f"问题 {index} " + "很长内容" * 8},
            })
            entries.append({
                "type": "message",
                "id": assistant_id,
                "parentId": user_id,
                "message": {"role": "assistant", "content": f"回答 {index} " + "详细解释" * 8, "stopReason": "stop"},
            })
            parent = assistant_id
        path.write_text("\n".join(json.dumps(entry, ensure_ascii=False) for entry in entries) + "\n", encoding="utf-8")
        return path

    def _snapshot(self, sources: tuple[dict[str, Any], ...]) -> ExperienceSnapshot:
        return ExperienceSnapshot(
            scope_key="7:ABCD1234",
            library_id=7,
            item_key="ABCD1234",
            attachment_key="PDFD1234",
            document_id="d" * 64,
            context_fingerprint="f" * 64,
            paper_title="Test Paper",
            cwd=str(self.root),
            sources=sources,
            model="test/model",
            thinking="medium",
        )

    def _wait(self, job_id: str) -> dict[str, Any]:
        deadline = time.time() + 5
        while time.time() < deadline:
            payload = self.manager.payload(job_id)
            if payload["status"] in {"completed", "failed"}:
                return payload
            time.sleep(0.02)
        self.fail("experience job did not finish")

    def test_formula_list_wraps_raw_latex_without_doubling_existing_delimiters(self) -> None:
        lines: list[str] = []
        self.manager._append_formula_list(lines, [
            r"\sigma_X=\begin{cases}\sigma_0,&X=0\\\sigma_1,&X=1\end{cases}",
            r"\(x+y\)",
            r"$z$",
            r"$$a=b$$",
        ])
        self.assertEqual(lines, [
            "**公式**",
            r"- $\sigma_X=\begin{cases}\sigma_0,&X=0\\\sigma_1,&X=1\end{cases}$",
            r"- $x+y$",
            r"- $z$",
            r"- $a=b$",
            "",
        ])

    def test_full_update_skips_missing_sources_and_reuses_note_key(self) -> None:
        session = self._session("one.jsonl", pairs=120)
        missing = self.root / "missing.jsonl"
        snapshot = self._snapshot((
            {"session_file": str(session), "available": True},
            {"session_file": str(missing), "available": False},
        ))
        first = self._wait(self.manager.submit(snapshot).job_id)
        self.assertEqual(first["status"], "completed")
        self.assertEqual(first["session_count"], 1)
        self.assertEqual(first["exchange_count"], 120)
        self.assertEqual(first["skipped_session_count"], 1)
        self.assertGreater(len(self.generator.calls), 1, "small chunk limit should exercise map/reduce")
        self.assertEqual(self.writer.calls[0][0], "upsert_assistant_experience_note")
        self.assertEqual(self.writer.calls[0][1]["marker"], EXPERIENCE_NOTE_MARKER)
        self.assertIsNone(self.writer.calls[0][1]["note_key"])

        second = self._wait(self.manager.submit(snapshot).job_id)
        self.assertEqual(second["status"], "completed")
        self.assertEqual(self.writer.calls[1][1]["note_key"], "EXPNOTE1")
        self.assertFalse(second["created"])
        self.assertIn("EXPNOTE1", self.index.get(snapshot.scope_key)["note_key"])

    def test_unchanged_update_reuses_ledger_without_ai_calls(self) -> None:
        session = self._session("unchanged.jsonl", pairs=2)
        snapshot = self._snapshot(({"session_file": str(session), "available": True},))
        first = self._wait(self.manager.submit(snapshot).job_id)
        self.assertEqual(first["status"], "completed")
        calls = len(self.generator.calls)
        second = self._wait(self.manager.submit(snapshot).job_id)
        self.assertEqual(second["status"], "completed")
        self.assertEqual(second["update_mode"], "up_to_date")
        self.assertEqual(second["new_exchange_count"], 0)
        self.assertEqual(second["reused_exchange_count"], 2)
        self.assertEqual(second["ai_call_count"], 0)
        self.assertEqual(len(self.generator.calls), calls)
        self.assertEqual(len(self.writer.calls), 2, "cached Markdown is written back to overwrite manual edits")

    def test_metadata_change_rerenders_cached_knowledge_without_ai(self) -> None:
        session = self._session("metadata.jsonl", pairs=1)
        snapshot = self._snapshot(({"session_file": str(session), "available": True},))
        self.assertEqual(self._wait(self.manager.submit(snapshot).job_id)["status"], "completed")
        calls = len(self.generator.calls)
        renamed = replace(snapshot, paper_title="Renamed Paper")
        result = self._wait(self.manager.submit(renamed).job_id)
        self.assertEqual(result["status"], "completed")
        self.assertNotEqual(result["update_mode"], "up_to_date")
        self.assertEqual(result["ai_call_count"], 0)
        self.assertEqual(len(self.generator.calls), calls)
        self.assertIn("文献：Renamed Paper", self.writer.calls[-1][1]["markdown"])

    def test_append_only_extracts_new_exchange(self) -> None:
        session = self._session("append.jsonl", pairs=1)
        snapshot = self._snapshot(({"session_file": str(session), "available": True},))
        self.assertEqual(self._wait(self.manager.submit(snapshot).job_id)["status"], "completed")
        entries = [json.loads(line) for line in session.read_text(encoding="utf-8").splitlines()]
        entries.extend([
            {"type": "message", "id": "append-u1", "parentId": entries[-1]["id"], "message": {"role": "user", "content": "新增问题"}},
            {"type": "message", "id": "append-a1", "parentId": "append-u1", "message": {"role": "assistant", "content": "新增回答", "stopReason": "stop"}},
        ])
        session.write_text("\n".join(json.dumps(entry, ensure_ascii=False) for entry in entries) + "\n", encoding="utf-8")
        result = self._wait(self.manager.submit(snapshot).job_id)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["new_exchange_count"], 1)
        self.assertEqual(result["reused_exchange_count"], 1)
        extraction_calls = [call for call in self.generator.calls if str(call.get("system_prompt") or "").startswith("你是研究学习成果提取器")]
        latest_payload = json.loads(extraction_calls[-1]["prompt"].split("<ZAB_EXPERIENCE_SOURCE>\n", 1)[1].split("\n</ZAB_EXPERIENCE_SOURCE>", 1)[0])
        self.assertEqual(len(latest_payload["exchanges"]), 1)
        self.assertEqual(latest_payload["exchanges"][0]["question"], "新增问题")

    def test_missing_source_retains_knowledge_and_recovers_without_ai(self) -> None:
        session = self._session("recover.jsonl", pairs=1)
        original = session.read_text(encoding="utf-8")
        snapshot = self._snapshot(({"session_file": str(session), "available": True},))
        self.assertEqual(self._wait(self.manager.submit(snapshot).job_id)["status"], "completed")
        calls = len(self.generator.calls)
        session.unlink()
        missing = self._wait(self.manager.submit(snapshot).job_id)
        self.assertEqual(missing["status"], "completed")
        self.assertEqual(missing["new_exchange_count"], 0)
        self.assertGreaterEqual(missing["missing_source_knowledge_count"], 1)
        self.assertEqual(len(self.generator.calls), calls)
        self.assertIn("来源不可用", self.writer.calls[-1][1]["markdown"])
        missing_state = self.manager.knowledge_store.load(snapshot.scope_key).state
        self.assertTrue(all(unit.status == "source_missing" for unit in missing_state.units.values()))
        session.write_text(original, encoding="utf-8")
        recovered = self._wait(self.manager.submit(snapshot).job_id)
        self.assertEqual(recovered["status"], "completed")
        self.assertEqual(recovered["new_exchange_count"], 0)
        self.assertEqual(len(self.generator.calls), calls)
        recovered_state = self.manager.knowledge_store.load(snapshot.scope_key).state
        self.assertTrue(all(unit.status == "active" for unit in recovered_state.units.values()))

    def test_branch_change_withdraws_old_exclusive_knowledge(self) -> None:
        session = self._session("branch.jsonl", pairs=1)
        snapshot = self._snapshot(({"session_file": str(session), "available": True},))
        self.assertEqual(self._wait(self.manager.submit(snapshot).job_id)["status"], "completed")
        session.write_text("\n".join([
            json.dumps({"type": "message", "id": "new-u", "parentId": None, "message": {"role": "user", "content": "新分支问题"}}, ensure_ascii=False),
            json.dumps({"type": "message", "id": "new-a", "parentId": "new-u", "message": {"role": "assistant", "content": "新分支回答", "stopReason": "stop"}}, ensure_ascii=False),
        ]) + "\n", encoding="utf-8")
        result = self._wait(self.manager.submit(snapshot).job_id)
        self.assertEqual(result["status"], "completed")
        markdown = self.writer.calls[-1][1]["markdown"]
        self.assertIn("新分支回答", markdown)
        self.assertNotIn("回答 0 详细解释", markdown)

    def test_coverage_repair_and_correction_are_rendered(self) -> None:
        self.generator.omit_last_unit = True
        self.generator.emit_correction = True
        session = self._session("coverage.jsonl", pairs=2)
        result = self._wait(self.manager.submit(self._snapshot(({"session_file": str(session), "available": True},))).job_id)
        self.assertEqual(result["status"], "completed")
        self.assertTrue(any(warning.startswith("knowledge_coverage_repaired") for warning in result["warnings"]))
        markdown = self.writer.calls[-1][1]["markdown"]
        self.assertIn("## 认知演进", markdown)
        self.assertIn("新认识修正旧认识", markdown)

    def test_withdrawing_correcting_branch_restores_old_unit_to_active(self) -> None:
        self.generator.emit_correction = True
        session = self._session("correction-withdrawal.jsonl", pairs=2)
        snapshot = self._snapshot(({"session_file": str(session), "available": True},))
        first = self._wait(self.manager.submit(snapshot).job_id)
        self.assertEqual(first["status"], "completed")
        self.assertIn("新认识修正旧认识", self.writer.calls[-1][1]["markdown"])
        entries = [json.loads(line) for line in session.read_text(encoding="utf-8").splitlines()][:2]
        session.write_text("\n".join(json.dumps(entry, ensure_ascii=False) for entry in entries) + "\n", encoding="utf-8")
        self.generator.emit_correction = False
        second = self._wait(self.manager.submit(snapshot).job_id)
        self.assertEqual(second["status"], "completed")
        markdown = self.writer.calls[-1][1]["markdown"]
        self.assertIn("回答 0", markdown)
        self.assertNotIn("新认识修正旧认识", markdown)
        state = self.manager.knowledge_store.load(snapshot.scope_key).state
        self.assertTrue(all(unit.status == "active" for unit in state.units.values()))

    def test_cross_session_increment_and_duplicate_content_reuse(self) -> None:
        first_session = self._session("cross-first.jsonl", pairs=1)
        first_snapshot = self._snapshot(({"session_file": str(first_session), "available": True},))
        self.assertEqual(self._wait(self.manager.submit(first_snapshot).job_id)["status"], "completed")
        calls = len(self.generator.calls)
        duplicate = self.root / "cross-duplicate.jsonl"
        duplicate.write_text(first_session.read_text(encoding="utf-8").replace("cross-first", "cross-clone"), encoding="utf-8")
        duplicate_snapshot = self._snapshot((
            {"session_file": str(first_session), "available": True},
            {"session_file": str(duplicate), "available": True},
        ))
        reused = self._wait(self.manager.submit(duplicate_snapshot).job_id)
        self.assertEqual(reused["status"], "completed")
        self.assertEqual(reused["new_exchange_count"], 0)
        self.assertEqual(reused["knowledge_unit_count"], 1)
        self.assertEqual(len(self.generator.calls), calls)
        second_session = self._session("cross-second.jsonl", pairs=1)
        entries = [json.loads(line) for line in second_session.read_text(encoding="utf-8").splitlines()]
        entries[0]["message"]["content"] = "不同问题"
        entries[1]["message"]["content"] = "不同回答"
        second_session.write_text("\n".join(json.dumps(entry, ensure_ascii=False) for entry in entries) + "\n", encoding="utf-8")
        expanded = self._snapshot((
            {"session_file": str(first_session), "available": True},
            {"session_file": str(second_session), "available": True},
        ))
        result = self._wait(self.manager.submit(expanded).job_id)
        self.assertEqual(result["new_exchange_count"], 1)
        self.assertEqual(result["reused_exchange_count"], 1)

    def test_semantic_merge_preserves_all_paraphrased_evidence(self) -> None:
        first_session = self._session("merge-first.jsonl", pairs=1)
        first_entries = [json.loads(line) for line in first_session.read_text(encoding="utf-8").splitlines()]
        first_entries[-1]["message"]["content"] = "梯度下降沿负梯度方向更新参数。"
        first_session.write_text("\n".join(json.dumps(entry, ensure_ascii=False) for entry in first_entries) + "\n", encoding="utf-8")
        snapshot = self._snapshot(({"session_file": str(first_session), "available": True},))
        self.assertEqual(self._wait(self.manager.submit(snapshot).job_id)["status"], "completed")
        second_session = self._session("merge-second.jsonl", pairs=1)
        second_entries = [json.loads(line) for line in second_session.read_text(encoding="utf-8").splitlines()]
        second_entries[-1]["message"]["content"] = "参数更新应朝着目标函数梯度的反方向进行。"
        second_session.write_text("\n".join(json.dumps(entry, ensure_ascii=False) for entry in second_entries) + "\n", encoding="utf-8")
        self.generator.merge_all = True
        merged_snapshot = self._snapshot((
            {"session_file": str(first_session), "available": True},
            {"session_file": str(second_session), "available": True},
        ))
        result = self._wait(self.manager.submit(merged_snapshot).job_id)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["knowledge_unit_count"], 1)
        markdown = self.writer.calls[-1][1]["markdown"]
        self.assertIn("梯度下降沿负梯度方向更新参数", markdown)
        self.assertIn("参数更新应朝着目标函数梯度的反方向", markdown)
        state = self.manager.knowledge_store.load(merged_snapshot.scope_key).state
        unit = next(iter(state.units.values()))
        self.assertEqual(len(unit.evidence_ids), 2)
        calls = len(self.generator.calls)
        third = self._wait(self.manager.submit(merged_snapshot).job_id)
        self.assertEqual(third["status"], "completed")
        self.assertEqual(third["update_mode"], "up_to_date")
        self.assertEqual(third["knowledge_unit_count"], 1)
        self.assertEqual(third["ai_call_count"], 0)
        self.assertEqual(len(self.generator.calls), calls)
        persisted = self.manager.knowledge_store.load(merged_snapshot.scope_key).state
        self.assertEqual(len(persisted.units), 1)
        self.assertEqual(len(persisted.sections[0].unit_ids), 1)

    def test_prior_relation_survives_partial_provenance_withdrawal(self) -> None:
        sessions = [self._session(f"provenance-{index}.jsonl", pairs=1) for index in range(3)]
        answers = ["同一概念的第一种表述", "同一概念的第二种表述", "相关的补充知识"]
        for session, answer in zip(sessions, answers, strict=True):
            entries = [json.loads(line) for line in session.read_text(encoding="utf-8").splitlines()]
            entries[-1]["message"]["content"] = answer
            session.write_text("\n".join(json.dumps(entry, ensure_ascii=False) for entry in entries) + "\n", encoding="utf-8")
        snapshot = self._snapshot(tuple({"session_file": str(session), "available": True} for session in sessions))
        self.generator.merge_named_equivalents = True
        self.generator.emit_named_extends = True
        first = self._wait(self.manager.submit(snapshot).job_id)
        self.assertEqual(first["status"], "completed")
        self.assertEqual(first["knowledge_unit_count"], 2)
        self.assertEqual(first["relation_count"], 1)
        old_digest = exchange_content_digest(read_session_transcript(sessions[0]).exchanges[0])
        replacement = sessions[1].read_text(encoding="utf-8")
        sessions[0].write_text(replacement.replace("provenance-1", "provenance-0-rewritten"), encoding="utf-8")
        self.generator.merge_named_equivalents = False
        self.generator.emit_named_extends = False
        second = self._wait(self.manager.submit(snapshot).job_id)
        self.assertEqual(second["status"], "completed", second)
        self.assertEqual(second["relation_count"], 1)
        after = self.manager.knowledge_store.load(snapshot.scope_key).state
        self.assertNotIn(old_digest, after.exchanges)
        self.assertNotIn(old_digest, after.relations[0].source_exchange_ids)
        self.assertTrue(after.relations[0].source_exchange_ids)

    def test_v1_index_migrates_and_reuses_note_key(self) -> None:
        session = self._session("migration.jsonl", pairs=1)
        snapshot = self._snapshot(({"session_file": str(session), "available": True},))
        self.index.put(snapshot.scope_key, {"note_key": "LEGACYNOTE", "source_hash": "legacy"})
        result = self._wait(self.manager.submit(snapshot).job_id)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["update_mode"], "migration")
        self.assertEqual(self.writer.calls[-1][1]["note_key"], "LEGACYNOTE")

    def test_initial_large_catalog_discovers_cross_partition_correction(self) -> None:
        self.settings.pi.experience_structure_max_chars = 10_000
        self.settings.pi.experience_coverage_audit = False
        self.generator.emit_named_correction = True
        session = self._session("cross-partition.jsonl", pairs=3)
        entries = [json.loads(line) for line in session.read_text(encoding="utf-8").splitlines()]
        answers = ["旧认识" + "甲" * 4000, "中间知识" + "乙" * 4000, "新认识" + "丙" * 4000]
        for index, answer in enumerate(answers):
            entries[index * 2 + 1]["message"]["content"] = answer
        session.write_text("\n".join(json.dumps(entry, ensure_ascii=False) for entry in entries) + "\n", encoding="utf-8")
        result = self._wait(self.manager.submit(self._snapshot(({"session_file": str(session), "available": True},))).job_id)
        self.assertEqual(result["status"], "completed", result)
        self.assertTrue(any(warning.startswith("knowledge_structure_partitioned") for warning in result["warnings"]))
        self.assertTrue(any(warning.startswith("knowledge_cross_partition_passes") for warning in result["warnings"]))
        self.assertEqual(result["relation_count"], 1)
        self.assertIn("跨分区新认识修正旧认识", self.writer.calls[-1][1]["markdown"])

    def test_many_partition_cross_link_calls_are_bounded_and_complete_with_warning(self) -> None:
        self.settings.pi.experience_structure_max_chars = 10_000
        self.settings.pi.experience_extraction_chunk_chars = 500_000
        self.settings.pi.experience_cross_link_max_calls = 2
        self.settings.pi.experience_coverage_audit = False
        session = self._session("many-partitions.jsonl", pairs=100)
        entries = [json.loads(line) for line in session.read_text(encoding="utf-8").splitlines()]
        for index in range(100):
            entries[index * 2 + 1]["message"]["content"] = f"独立知识{index}-" + chr(0x4E00 + index) * 4000
        session.write_text("\n".join(json.dumps(entry, ensure_ascii=False) for entry in entries) + "\n", encoding="utf-8")
        result = self._wait(self.manager.submit(self._snapshot(({"session_file": str(session), "available": True},))).job_id)
        self.assertEqual(result["status"], "completed", result)
        cross_calls = [
            call for call in self.generator.calls
            if str(call.get("system_prompt") or "").startswith("你是跨分区知识联系审计器")
        ]
        self.assertLessEqual(len(cross_calls), 2)
        self.assertIn("knowledge_cross_partition_budget_exhausted", result["warnings"])
        self.assertEqual(result["knowledge_unit_count"], 100)

    def test_large_catalog_is_partitioned_without_omitting_content_or_existing_relations(self) -> None:
        self.generator.emit_correction = True
        session = self._session("large.jsonl", pairs=2)
        snapshot = self._snapshot(({"session_file": str(session), "available": True},))
        initial = self._wait(self.manager.submit(snapshot).job_id)
        self.assertEqual(initial["status"], "completed")
        self.assertGreaterEqual(initial["relation_count"], 1)
        self.settings.pi.experience_structure_max_chars = 10_000
        self.settings.pi.experience_extraction_chunk_chars = 10_000
        self.settings.pi.experience_coverage_audit = False
        entries = [json.loads(line) for line in session.read_text(encoding="utf-8").splitlines()]
        entries.extend([
            {"type": "message", "id": "large-u", "parentId": entries[-1]["id"], "message": {"role": "user", "content": "超长问题"}},
            {"type": "message", "id": "large-a", "parentId": "large-u", "message": {"role": "assistant", "content": "独有知识" * 3000, "stopReason": "stop"}},
        ])
        session.write_text("\n".join(json.dumps(entry, ensure_ascii=False) for entry in entries) + "\n", encoding="utf-8")
        result = self._wait(self.manager.submit(snapshot).job_id)
        self.assertEqual(result["status"], "completed")
        self.assertGreaterEqual(result["relation_count"], 1)
        self.assertIn("独有知识" * 100, self.writer.calls[-1][1]["markdown"])
        extraction_calls = [call for call in self.generator.calls if str(call.get("system_prompt") or "").startswith("你是研究学习成果提取器")]
        for call in extraction_calls:
            source = call["prompt"].split("<ZAB_EXPERIENCE_SOURCE>\n", 1)[1].split("\n</ZAB_EXPERIENCE_SOURCE>", 1)[0]
            self.assertLessEqual(len(source), self.settings.pi.experience_extraction_chunk_chars)
        organization_calls = [call for call in self.generator.calls if str(call.get("system_prompt") or "").startswith("你是知识结构规划器")]
        for call in organization_calls:
            source = call["prompt"].split("<ZAB_EXPERIENCE_SOURCE>\n", 1)[1].split("\n</ZAB_EXPERIENCE_SOURCE>", 1)[0]
            self.assertLessEqual(len(source), self.settings.pi.experience_structure_max_chars)

    def test_unknown_exchange_and_unit_ids_are_rejected(self) -> None:
        session = self._session("unknown.jsonl", pairs=1)
        snapshot = self._snapshot(({"session_file": str(session), "available": True},))
        self.generator.unknown_exchange = True
        unknown_exchange = self._wait(self.manager.submit(snapshot).job_id)
        self.assertEqual(unknown_exchange["status"], "failed")
        self.assertEqual(unknown_exchange["error"]["code"], "experience_structured_output_invalid")
        self.generator.unknown_exchange = False
        self.generator.unknown_unit = True
        unknown_unit = self._wait(self.manager.submit(snapshot).job_id)
        self.assertEqual(unknown_unit["status"], "failed")
        self.assertEqual(unknown_unit["error"]["code"], "experience_structured_output_invalid")
        self.assertEqual(self.writer.calls, [])

    def test_extra_fields_self_relations_and_unknown_provenance_are_rejected(self) -> None:
        session = self._session("strict.jsonl", pairs=2)
        snapshot = self._snapshot(({"session_file": str(session), "available": True},))
        self.generator.extra_field = True
        extra = self._wait(self.manager.submit(snapshot).job_id)
        self.assertEqual(extra["status"], "failed")
        self.assertEqual(extra["error"]["code"], "experience_structured_output_invalid")
        self.generator.extra_field = False
        self.generator.self_relation = True
        self_rel = self._wait(self.manager.submit(snapshot).job_id)
        self.assertEqual(self_rel["status"], "failed")
        self.assertEqual(self_rel["error"]["code"], "experience_structured_output_invalid")
        self.generator.self_relation = False
        self.generator.unknown_provenance = True
        unsupported = self._wait(self.manager.submit(snapshot).job_id)
        self.assertEqual(unsupported["status"], "failed")
        self.assertEqual(unsupported["error"]["code"], "experience_structured_output_invalid")
        self.assertEqual(self.writer.calls, [])

    def test_invalid_structured_output_and_write_failure_do_not_commit_ledger(self) -> None:
        session = self._session("invalid.jsonl", pairs=1)
        snapshot = self._snapshot(({"session_file": str(session), "available": True},))
        self.generator.invalid_output = True
        invalid = self._wait(self.manager.submit(snapshot).job_id)
        self.assertEqual(invalid["status"], "failed")
        self.assertEqual(invalid["error"]["code"], "experience_structured_output_invalid")
        self.assertEqual(self.writer.calls, [])
        self.assertFalse(self.manager.knowledge_store.path_for(snapshot.scope_key).exists())
        self.generator.invalid_output = False
        self.writer.error = BridgeError(503, "write_failed", "boom")
        failed_write = self._wait(self.manager.submit(snapshot).job_id)
        self.assertEqual(failed_write["status"], "failed")
        self.assertEqual(failed_write["error"]["code"], "write_failed")
        self.assertFalse(self.manager.knowledge_store.path_for(snapshot.scope_key).exists())

    def test_timeout_retry_resumes_from_completed_extraction_checkpoint(self) -> None:
        self.settings.pi.experience_extraction_chunk_chars = 10_000
        self.settings.pi.experience_coverage_audit = False
        session = self._session("checkpoint.jsonl", pairs=120)
        snapshot = self._snapshot(({"session_file": str(session), "available": True},))
        self.generator.fail_on_call_once = 2

        failed = self._wait(self.manager.submit(snapshot).job_id)
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["error"]["code"], "pi_generation_timeout")
        self.assertFalse(self.manager.knowledge_store.path_for(snapshot.scope_key).exists())
        self.assertTrue(self.manager.knowledge_store.checkpoint_path_for(snapshot.scope_key).exists())
        first_chunk = json.loads(
            self.generator.calls[0]["prompt"].split("<ZAB_EXPERIENCE_SOURCE>\n", 1)[1].split("\n</ZAB_EXPERIENCE_SOURCE>", 1)[0]
        )["exchanges"]

        completed = self._wait(self.manager.submit(snapshot).job_id)
        self.assertEqual(completed["status"], "completed")
        self.assertIn("knowledge_checkpoint_resumed", completed["warnings"])
        resumed_chunk = json.loads(
            self.generator.calls[2]["prompt"].split("<ZAB_EXPERIENCE_SOURCE>\n", 1)[1].split("\n</ZAB_EXPERIENCE_SOURCE>", 1)[0]
        )["exchanges"]
        self.assertTrue(
            {entry["source_exchange_id"] for entry in first_chunk}.isdisjoint(
                entry["source_exchange_id"] for entry in resumed_chunk
            )
        )
        self.assertTrue(self.manager.knowledge_store.path_for(snapshot.scope_key).exists())
        self.assertFalse(self.manager.knowledge_store.checkpoint_path_for(snapshot.scope_key).exists())

    def test_force_rebuild_ignores_cached_processing_marks(self) -> None:
        session = self._session("rebuild.jsonl", pairs=1)
        snapshot = self._snapshot(({"session_file": str(session), "available": True},))
        self.assertEqual(self._wait(self.manager.submit(snapshot).job_id)["status"], "completed")
        calls = len(self.generator.calls)
        rebuilt_snapshot = replace(snapshot, force_rebuild=True)
        rebuilt = self._wait(self.manager.submit(rebuilt_snapshot).job_id)
        self.assertEqual(rebuilt["status"], "completed")
        self.assertEqual(rebuilt["update_mode"], "full_rebuild")
        self.assertGreater(len(self.generator.calls), calls)

    def test_job_reads_return_immutable_snapshots(self) -> None:
        with self.manager._lock:
            self.manager._jobs["snapshot"] = ExperienceJob(job_id="snapshot", scope_key="7:ABCD1234")
        first_view = self.manager.get("snapshot")
        self.manager._update("snapshot", status="generating", stage="generating", warnings=["new warning"])
        second_view = self.manager.get("snapshot")
        self.assertEqual(first_view.status, "queued")
        self.assertEqual(first_view.warnings, [])
        self.assertEqual(second_view.status, "generating")
        self.assertEqual(second_view.warnings, ["new warning"])

    def test_generation_failure_does_not_write_or_update_index(self) -> None:
        session = self._session("failure.jsonl", pairs=1)
        snapshot = self._snapshot(({"session_file": str(session), "available": True},))
        self.generator.error = BridgeError(503, "pi_generation_failed", "boom")
        result = self._wait(self.manager.submit(snapshot).job_id)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error"]["code"], "pi_generation_failed")
        self.assertEqual(self.writer.calls, [])
        self.assertIsNone(self.index.get(snapshot.scope_key))


if __name__ == "__main__":
    unittest.main()
