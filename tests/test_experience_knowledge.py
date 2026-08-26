from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from zotero_agent_bridge.experience_knowledge import (
    EvidenceDraft,
    ExperienceKnowledgeStore,
    KnowledgeEvidence,
    branch_digest,
    build_units,
    deterministic_sections,
    exchange_content_digest,
    new_state,
    parse_json_object,
)
from zotero_agent_bridge.session_transcript import AssistantExchange


class ExperienceKnowledgeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = ExperienceKnowledgeStore(self.root / "knowledge")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_store_is_atomic_and_isolated_by_library_scope(self) -> None:
        first = new_state("7:ABCD1234", 7, "ABCD1234")
        second = new_state("8:ABCD1234", 8, "ABCD1234")
        first.final_markdown = "first"
        first.unit_aliases = {"old-unit": "canonical-unit", "canonical-unit": "canonical-unit"}
        second.final_markdown = "second"
        self.store.save(first)
        self.store.save(second)
        self.assertNotEqual(self.store.path_for(first.scope_key), self.store.path_for(second.scope_key))
        loaded_first = self.store.load(first.scope_key).state
        self.assertEqual(loaded_first.final_markdown, "first")
        self.assertEqual(loaded_first.unit_aliases["old-unit"], "canonical-unit")
        self.assertEqual(self.store.load(second.scope_key).state.final_markdown, "second")
        self.assertFalse(any(path.suffix == ".tmp" for path in self.store.root.iterdir()))

    def test_corrupt_store_is_quarantined_and_recoverable(self) -> None:
        scope = "7:CORRUPT1"
        path = self.store.path_for(scope)
        path.write_text("{bad", encoding="utf-8")
        result = self.store.load(scope)
        self.assertIsNone(result.state)
        self.assertTrue(result.warnings[0].startswith("knowledge_store_corrupt"))
        self.assertFalse(path.exists())
        self.assertTrue(any(".corrupt-" in candidate.name for candidate in self.store.root.iterdir()))
        recovered = new_state(scope, 7, "CORRUPT1")
        self.store.save(recovered)
        self.assertEqual(self.store.load(scope).state.item_key, "CORRUPT1")
        payload = recovered.model_dump(mode="json")
        payload["schema_version"] = 1
        path.write_text(json.dumps(payload), encoding="utf-8")
        incompatible = self.store.load(scope)
        self.assertIsNone(incompatible.state)
        self.assertTrue(incompatible.warnings[0].startswith("knowledge_store_corrupt"))

    def test_exchange_digest_tracks_semantics_and_image_identity(self) -> None:
        base = AssistantExchange("问题", "回答", "id", image_count=1, image_digest="image-a")
        clone = AssistantExchange("问题", "回答", "different-id", image_count=1, image_digest="image-a")
        changed = AssistantExchange("问题", "回答", "id", image_count=1, image_digest="image-b")
        self.assertEqual(exchange_content_digest(base), exchange_content_digest(clone))
        self.assertNotEqual(exchange_content_digest(base), exchange_content_digest(changed))
        self.assertNotEqual(branch_digest([exchange_content_digest(base)]), branch_digest([exchange_content_digest(changed)]))

    def test_exact_evidence_is_deduplicated_without_losing_sources(self) -> None:
        first = KnowledgeEvidence(
            evidence_id="e1",
            source_exchange_digest="x1",
            kind="concept",
            title="定义",
            content="完整定义",
            created_at="2026-01-01T00:00:00Z",
        )
        second = first.model_copy(update={"evidence_id": "e2", "source_exchange_digest": "x2"})
        units = build_units({"e1": first, "e2": second}, {"x1", "x2"})
        self.assertEqual(len(units), 1)
        unit = next(iter(units.values()))
        self.assertEqual(set(unit.evidence_ids), {"e1", "e2"})
        self.assertEqual(set(unit.source_exchange_digests), {"x1", "x2"})
        self.assertEqual(deterministic_sections(units)[0].title, "核心概念")

    def test_structured_json_parser_accepts_fences_but_rejects_non_objects(self) -> None:
        self.assertEqual(parse_json_object("```json\n{\"evidence\": []}\n```"), {"evidence": []})
        with self.assertRaises(ValueError):
            parse_json_object("[1, 2]")


if __name__ == "__main__":
    unittest.main()
