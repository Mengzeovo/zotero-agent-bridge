from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any

from zotero_agent_bridge.zotero_local import ZoteroLocalClient


class FakeResponse:
    def __init__(self, payload: Any, status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code
        self.text = "fake response"

    def json(self) -> Any:
        return self.payload


class FakeSession:
    def __init__(self, routes: dict[str, Any]) -> None:
        self.routes = routes
        self.headers: dict[str, str] = {}
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def get(self, url: str, *, params: dict[str, Any] | None = None, timeout: int = 15) -> FakeResponse:
        del timeout
        path = url.split("/api/users/0/", 1)[1]
        self.calls.append((path, dict(params or {})))
        value = self.routes[path]
        if isinstance(value, FakeResponse):
            return value
        return FakeResponse(value)


class ZoteroLocalPiBundleTest(unittest.TestCase):
    def _client(self, base_attachment_path: Path, *, annotation_failure: bool = False) -> ZoteroLocalClient:
        routes: dict[str, Any] = {
            "items/ABCD1234": {
                "key": "ABCD1234",
                "version": 9,
                "library": {"id": 1},
                "data": {
                    "itemType": "journalArticle",
                    "title": "Pi-only Paper",
                    "DOI": "10.1000/example",
                    "url": "https://example.test/paper",
                    "creators": [{"creatorType": "author", "firstName": "Ada", "lastName": "Lovelace"}],
                    "tags": [{"tag": "pi"}],
                    "collections": ["COLL0001"],
                    "dateModified": "2026-08-25T00:00:00Z",
                },
            },
            "items/ABCD1234/children": [
                {
                    "key": "PDFD1234",
                    "library": {"id": 1},
                    "data": {
                        "itemType": "attachment",
                        "parentItem": "ABCD1234",
                        "title": "Full Text PDF",
                        "contentType": "application/pdf",
                        "path": "attachments:paper.pdf",
                        "linkMode": "linked_file",
                        "dateModified": "2026-08-25T00:00:00Z",
                    },
                },
                {
                    "key": "NOTE1234",
                    "library": {"id": 1},
                    "data": {
                        "itemType": "note",
                        "parentItem": "ABCD1234",
                        "note": "<p>Useful note</p>",
                        "dateModified": "2026-08-25T00:00:00Z",
                    },
                },
            ],
            "collections": [
                {
                    "key": "COLL0001",
                    "version": 2,
                    "library": {"id": 1},
                    "data": {"name": "Research", "parentCollection": False},
                }
            ],
            "items/PDFD1234/children": FakeResponse([], 500) if annotation_failure else [
                {
                    "key": "ANNO1234",
                    "library": {"id": 1},
                    "data": {
                        "itemType": "annotation",
                        "parentItem": "PDFD1234",
                        "annotationType": "highlight",
                        "annotationText": "Key result",
                        "annotationComment": "Check proof",
                        "annotationPageLabel": "7",
                        "annotationPosition": '{"pageIndex":6}',
                        "annotationSortIndex": "00007|000001",
                        "tags": [{"tag": "important"}],
                        "dateModified": "2026-08-25T00:00:00Z",
                    },
                }
            ],
        }
        client = ZoteroLocalClient(
            "http://127.0.0.1:23119/api/users/0",
            "ZoteroPiAssistant/test",
            base_attachment_path=str(base_attachment_path),
        )
        client.session = FakeSession(routes)
        return client

    def test_build_bundle_contains_only_reading_context_data(self) -> None:
        with tempfile.TemporaryDirectory(prefix="zpa-local-") as directory:
            base = Path(directory)
            client = self._client(base)
            bundle = client.build_bundle("ABCD1234")
            self.assertEqual(bundle["title"], "Pi-only Paper")
            self.assertEqual(bundle["collections"], [{"key": "COLL0001", "name": "Research"}])
            self.assertEqual(bundle["attachments"][0]["attachment_key"], "PDFD1234")
            self.assertEqual(Path(bundle["attachments"][0]["pdf_path"]), base / "paper.pdf")
            self.assertEqual(bundle["notes"][0]["title"], "Useful note")
            self.assertEqual(bundle["annotations"][0]["text"], "Key result")
            self.assertEqual(bundle["annotations"][0]["page_label"], "7")
            self.assertEqual(bundle["warnings"], [])

    def test_annotation_failure_is_a_warning_not_a_bundle_failure(self) -> None:
        with tempfile.TemporaryDirectory(prefix="zpa-local-") as directory:
            client = self._client(Path(directory), annotation_failure=True)
            bundle = client.build_bundle("ABCD1234")
            self.assertEqual(bundle["annotations"], [])
            self.assertEqual(len(bundle["warnings"]), 1)
            self.assertIn("Could not load annotations", bundle["warnings"][0])


if __name__ == "__main__":
    unittest.main()
