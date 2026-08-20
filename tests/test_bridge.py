from __future__ import annotations

import json
import socket
import shutil
import threading
import time
import unittest
import uuid
from copy import deepcopy
from pathlib import Path

import requests
import uvicorn

from zotero_agent_bridge.collection_tree import apply_default_collection_tree
from zotero_agent_bridge.config import ObsidianSettings, Settings
from zotero_agent_bridge.errors import BridgeError
from zotero_agent_bridge.mcp_server import BridgeHttpClient, ZoteroBridgeMCPServer
from zotero_agent_bridge.mirror import MirrorStore
from zotero_agent_bridge.paper_classifier import classify_library
from zotero_agent_bridge.service import BridgeService, create_app
from zotero_agent_bridge.utils import now_iso, strip_html


class FakeAddonClient:
    def __init__(self, ready: bool = True) -> None:
        self.ready = ready

    def status(self) -> dict[str, object]:
        return {
            "ready": self.ready,
            "fresh": self.ready,
            "bridge_home": "test",
            "last_seen": now_iso(),
        }

    def is_ready(self) -> bool:
        return self.ready


class FakeZoteroBackend:
    def __init__(self) -> None:
        self.available = True
        self.library_id = 1
        self.items: dict[str, dict[str, object]] = {}
        self.collections: dict[str, dict[str, object]] = {}
        self.top_level_items: list[dict[str, object]] | None = None
        self.item_counter = 1
        self.attachment_counter = 1
        self.note_counter = 1
        self.collection_counter = 1

    def is_available(self) -> bool:
        return self.available

    def invalidate_collection_cache(self) -> None:
        return None

    def list_collections(self) -> list[dict[str, object]]:
        return [deepcopy(collection) for collection in self.collections.values()]

    def get_collection(self, collection_key: str) -> dict[str, object]:
        return deepcopy(self.collections[collection_key])

    def seed_collection(
        self,
        collection_key: str,
        name: str,
        parent_key: str | None = None,
        *,
        version: int = 1,
    ) -> None:
        self.collections[collection_key] = {
            "library_id": self.library_id,
            "collection_key": collection_key,
            "version": version,
            "name": name,
            "parent_key": parent_key,
        }

    def search_items(self, query: str, limit: int = 20) -> list[dict[str, object]]:
        query_lower = query.lower()
        matches = []
        for bundle in self.items.values():
            title = str(bundle.get("title", "")).lower()
            doi = str(bundle.get("doi", "")).lower()
            if query_lower in title or query_lower in doi:
                matches.append(self._api_item(bundle))
            if len(matches) >= limit:
                break
        return matches

    def find_by_doi(self, doi: str) -> dict[str, object] | None:
        normalized = doi.lower()
        for bundle in self.items.values():
            if str(bundle.get("doi", "")).lower() == normalized:
                return self._api_item(bundle)
        return None

    def build_bundle(self, item_key: str) -> dict[str, object]:
        return deepcopy(self.items[item_key])

    def list_top_level_items(self, start: int = 0, limit: int = 100) -> list[dict[str, object]]:
        if self.top_level_items is not None:
            return deepcopy(self.top_level_items[start : start + limit])
        bundles = list(self.items.values())[start : start + limit]
        return [self._api_item(bundle) for bundle in bundles]

    def handle_command(self, command: str, payload: dict[str, object]) -> dict[str, object]:
        if command == "create_item":
            return self._create_item(payload)
        if command == "update_item":
            return self._update_item(payload)
        if command == "attach_linked_pdf":
            return self._attach_linked_pdf(payload)
        if command == "create_note":
            return self._create_note(payload)
        if command == "create_collection":
            return self._create_collection(payload)
        if command == "update_collection":
            return self._update_collection(payload)
        raise BridgeError(404, "unsupported_command", f"Unsupported command: {command}")

    def _create_item(self, payload: dict[str, object]) -> dict[str, object]:
        item_key = f"I{self.item_counter:04d}"
        self.item_counter += 1
        fields = deepcopy(payload.get("fields", {}))
        creators = deepcopy(payload.get("creators", []))
        tags = [self._tag_name(tag) for tag in payload.get("tags", [])]
        collections = list(payload.get("collections", []))
        bundle = {
            "library_id": self.library_id,
            "item_key": item_key,
            "attachment_key": None,
            "note_key": None,
            "slug": None,
            "pdf_path": None,
            "checksum": None,
            "version": 1,
            "item_type": payload.get("item_type", "journalArticle"),
            "title": fields.get("title") or "Untitled paper",
            "doi": fields.get("DOI"),
            "url": fields.get("url"),
            "fields": fields,
            "creators": creators,
            "tags": tags,
            "collections": self._collection_entries(collections),
            "attachments": [],
            "notes": [],
            "updated_at": now_iso(),
            "sync_status": payload.get("sync_status", "synced"),
        }
        self.items[item_key] = bundle
        return {
            "library_id": self.library_id,
            "item_key": item_key,
            "attachment_key": None,
            "note_key": None,
            "sync_status": bundle["sync_status"],
            "version": 1,
        }

    def _update_item(self, payload: dict[str, object]) -> dict[str, object]:
        item_key = str(payload["item_key"])
        bundle = self.items[item_key]
        expected_version = int(payload["version"])
        if int(bundle["version"]) != expected_version:
            raise BridgeError(
                409,
                "version_conflict",
                "Item version conflict",
                {"expected": expected_version, "actual": bundle["version"], "item_key": item_key},
            )
        fields = payload.get("fields") or {}
        bundle["fields"].update(deepcopy(fields))
        if "title" in fields:
            bundle["title"] = fields["title"]
        if "DOI" in fields:
            bundle["doi"] = fields["DOI"]
        if "url" in fields:
            bundle["url"] = fields["url"]
        if payload.get("creators") is not None:
            bundle["creators"] = deepcopy(payload["creators"])
        if payload.get("tags") is not None:
            bundle["tags"] = [self._tag_name(tag) for tag in payload.get("tags", [])]
        if payload.get("collections") is not None:
            bundle["collections"] = self._collection_entries(payload.get("collections", []))
        bundle["version"] = int(bundle["version"]) + 1
        bundle["updated_at"] = now_iso()
        return {
            "library_id": self.library_id,
            "item_key": item_key,
            "attachment_key": None,
            "note_key": None,
            "sync_status": bundle["sync_status"],
            "version": bundle["version"],
        }

    def _attach_linked_pdf(self, payload: dict[str, object]) -> dict[str, object]:
        item_key = str(payload["item_key"])
        bundle = self.items[item_key]
        attachment_key = f"A{self.attachment_counter:04d}"
        self.attachment_counter += 1
        attachment = {
            "library_id": self.library_id,
            "item_key": item_key,
            "attachment_key": attachment_key,
            "note_key": None,
            "slug": None,
            "title": payload.get("title") or Path(str(payload["path"])).name,
            "pdf_path": str(payload["path"]),
            "path": str(payload["path"]),
            "content_type": payload.get("content_type") or "application/pdf",
            "link_mode": "linked_file",
            "checksum": None,
            "updated_at": now_iso(),
            "sync_status": bundle["sync_status"],
        }
        bundle["attachments"].append(attachment)
        return {
            "library_id": self.library_id,
            "item_key": item_key,
            "attachment_key": attachment_key,
            "note_key": None,
            "sync_status": bundle["sync_status"],
            "version": bundle["version"],
        }

    def _create_note(self, payload: dict[str, object]) -> dict[str, object]:
        item_key = str(payload["item_key"])
        bundle = self.items[item_key]
        note_key = f"N{self.note_counter:04d}"
        self.note_counter += 1
        note_html = str(payload.get("note_html") or "")
        note = {
            "library_id": self.library_id,
            "item_key": item_key,
            "attachment_key": None,
            "note_key": note_key,
            "slug": None,
            "title": strip_html(note_html)[:120] or f"Note {note_key}",
            "pdf_path": None,
            "checksum": None,
            "updated_at": now_iso(),
            "sync_status": bundle["sync_status"],
            "note_html": note_html,
        }
        bundle["notes"].append(note)
        return {
            "library_id": self.library_id,
            "item_key": item_key,
            "attachment_key": None,
            "note_key": note_key,
            "sync_status": bundle["sync_status"],
            "version": bundle["version"],
        }

    def _create_collection(self, payload: dict[str, object]) -> dict[str, object]:
        collection_key = f"C{self.collection_counter:04d}"
        while collection_key in self.collections:
            self.collection_counter += 1
            collection_key = f"C{self.collection_counter:04d}"
        self.collection_counter += 1
        parent_key = payload.get("parent_key")
        if parent_key and parent_key not in self.collections:
            raise BridgeError(404, "collection_not_found", "Parent collection not found", {"parent_key": parent_key})
        collection = {
            "library_id": int(payload.get("library_id") or self.library_id),
            "collection_key": collection_key,
            "version": 1,
            "name": str(payload["name"]),
            "parent_key": str(parent_key) if parent_key else None,
        }
        self.collections[collection_key] = collection
        return deepcopy(collection)

    def _update_collection(self, payload: dict[str, object]) -> dict[str, object]:
        collection_key = str(payload["collection_key"])
        collection = self.collections[collection_key]
        expected_version = int(payload["version"])
        if int(collection["version"]) != expected_version:
            raise BridgeError(
                409,
                "version_conflict",
                "Collection version conflict",
                {"expected": expected_version, "actual": collection["version"], "collection_key": collection_key},
            )
        if "name" in payload:
            collection["name"] = str(payload["name"])
        if "parent_key" in payload:
            parent_key = payload.get("parent_key")
            if parent_key and parent_key == collection_key:
                raise BridgeError(422, "invalid_parent_collection", "Collection cannot be its own parent")
            if parent_key and parent_key not in self.collections:
                raise BridgeError(404, "collection_not_found", "Parent collection not found", {"parent_key": parent_key})
            collection["parent_key"] = str(parent_key) if parent_key else None
        collection["version"] = int(collection["version"]) + 1
        return deepcopy(collection)

    def _api_item(self, bundle: dict[str, object]) -> dict[str, object]:
        return {
            "library": {"id": bundle["library_id"]},
            "key": bundle["item_key"],
            "version": bundle["version"],
            "data": {
                "itemType": bundle["item_type"],
                "title": bundle.get("title") or "",
                "DOI": bundle.get("doi"),
                "tags": [{"tag": tag} for tag in bundle.get("tags", [])],
                "dateModified": bundle.get("updated_at") or now_iso(),
            },
        }

    def _collection_entries(self, collection_keys: list[object]) -> list[dict[str, object]]:
        entries = []
        for value in collection_keys:
            key = str(value)
            entries.append({
                "key": key,
                "name": str(self.collections.get(key, {}).get("name", key)),
            })
        return entries

    @staticmethod
    def _tag_name(tag: object) -> str:
        if isinstance(tag, dict):
            return str(tag.get("tag", ""))
        return str(tag)


class FakeWriter:
    def __init__(self, backend: FakeZoteroBackend) -> None:
        self.backend = backend
        self.addon_client = FakeAddonClient(ready=True)

    def execute(self, command: str, payload: dict[str, object]) -> dict[str, object]:
        return self.backend.handle_command(command, payload)


class LiveServer:
    def __init__(self, app, host: str, port: int) -> None:
        self.host = host
        self.port = port
        config = uvicorn.Config(app=app, host=host, port=port, log_level="error")
        self.server = uvicorn.Server(config=config)
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def start(self) -> None:
        self.thread.start()
        deadline = time.time() + 10
        url = f"http://{self.host}:{self.port}/health"
        while time.time() < deadline:
            if not self.thread.is_alive():
                raise RuntimeError("uvicorn server thread exited before startup")
            try:
                response = requests.get(url, timeout=0.5)
                if response.status_code in {200, 401}:
                    return
            except requests.RequestException:
                pass
            time.sleep(0.1)
        raise RuntimeError("Timed out waiting for test server startup")

    def stop(self) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=10)


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class BridgeTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path.cwd() / "tmp" / "bridge_tests" / uuid.uuid4().hex
        self.root.mkdir(parents=True, exist_ok=True)
        self.sample_pdf = self.root / "sample.pdf"
        self.sample_pdf.write_bytes(b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n")
        self.obsidian_vault = self.root / "obsidian-vault"
        self.obsidian_vault.mkdir(parents=True, exist_ok=True)
        self.raise_doi_lookup = False
        self.pdf_metadata_return: dict[str, str] = {"title": "PDF Imported Title", "doi": "10.2000/pdf"}

        self.settings = Settings(
            host="127.0.0.1",
            port=find_free_port(),
            api_token="test-token",
            zotero_local_api_base="http://127.0.0.1:23119/api/users/0",
            bridge_home=self.root / "bridge-home",
            metadata_dir=self.root / "metadata",
            notes_dir=self.root / "notes",
            addon_timeout_seconds=1.0,
            addon_status_ttl_seconds=60.0,
            user_agent="ZoteroAgentBridgeTest/0.1",
            base_attachment_path=None,
            obsidian=ObsidianSettings(
                vault_name="TestVault",
                vault_path=self.obsidian_vault,
                default_note_dir="Zotero Notes",
                index_path=self.root / "metadata" / "obsidian-index.json",
                bridge_open_base_url=None,
            ),
        )
        self.settings.prepare_runtime()

        self.backend = FakeZoteroBackend()
        self.writer = FakeWriter(self.backend)
        self.mirror = MirrorStore(self.settings.metadata_dir, self.settings.notes_dir)
        self.service = BridgeService(
            self.settings,
            local_client=self.backend,
            mirror=self.mirror,
            writer=self.writer,
            doi_resolver=self._fake_doi_resolver,
            pdf_metadata_extractor=self._fake_pdf_metadata,
        )
        self.base_url = f"http://{self.settings.host}:{self.settings.port}"
        self.server = LiveServer(create_app(settings=self.settings, service=self.service), self.settings.host, self.settings.port)
        self.server.start()
        self.session = requests.Session()
        self.headers = {"X-Bridge-Token": self.settings.api_token}

    def tearDown(self) -> None:
        self.session.close()
        self.server.stop()
        shutil.rmtree(self.root, ignore_errors=True)

    def test_prepare_runtime_persists_static_token_for_addon(self) -> None:
        generated = json.loads(self.settings.generated_config_path.read_text(encoding="utf-8"))
        self.assertEqual(generated["api_token"], self.settings.api_token)

    def request(self, method: str, path: str, **kwargs):
        return self.session.request(method, f"{self.base_url}{path}", timeout=5, **kwargs)

    def create_manual_item(self, title: str) -> dict[str, object]:
        response = self.request(
            "POST",
            "/items",
            headers=self.headers,
            json={"manual_fields": {"fields": {"title": title}}},
        )
        self.assertEqual(response.status_code, 200)
        return response.json()

    def _fake_doi_resolver(self, doi: str, _user_agent: str) -> dict[str, object]:
        if self.raise_doi_lookup:
            raise RuntimeError("doi lookup unavailable")
        return {
            "item_type": "journalArticle",
            "fields": {
                "title": "Resolved DOI Title",
                "DOI": doi,
                "url": f"https://doi.org/{doi}",
            },
            "creators": [{"creatorType": "author", "lastName": "Doe", "firstName": "Jane"}],
            "tags": [],
            "collections": [],
        }

    def _fake_pdf_metadata(self, _path: Path) -> dict[str, str]:
        return dict(self.pdf_metadata_return)

    def test_auth_required_for_http(self) -> None:
        response = self.request("GET", "/health")
        self.assertEqual(response.status_code, 401)

    def test_http_create_update_attach_note_and_export(self) -> None:
        created = self.request("POST", "/items", headers=self.headers, json={"doi": "10.1000/demo"})
        self.assertEqual(created.status_code, 200)
        created_payload = created.json()
        item_key = created_payload["item_key"]
        self.assertEqual(created_payload["sync_status"], "synced")

        updated = self.request(
            "PATCH",
            f"/items/{item_key}",
            headers=self.headers,
            json={
                "version": created_payload["version"],
                "fields": {"title": "Updated Bridge Title"},
                "tags": ["semantic", {"tag": "priority", "type": 0}],
                "collections": ["reading-list"],
            },
        )
        self.assertEqual(updated.status_code, 200)
        updated_payload = updated.json()
        self.assertEqual(updated_payload["title"], "Updated Bridge Title")

        attached = self.request(
            "POST",
            f"/items/{item_key}/attachments/linked-pdf",
            headers=self.headers,
            json={"pdf_path": str(self.sample_pdf), "title": "Updated Bridge Title PDF"},
        )
        self.assertEqual(attached.status_code, 200)
        attachment_key = attached.json()["attachment_key"]
        self.assertTrue(attachment_key)

        noted = self.request(
            "POST",
            f"/items/{item_key}/notes",
            headers=self.headers,
            json={"title": "Summary", "markdown": "Important result."},
        )
        self.assertEqual(noted.status_code, 200)
        note_key = noted.json()["note_key"]
        self.assertTrue(note_key)

        fetched = self.request("GET", f"/items/{item_key}", headers=self.headers)
        self.assertEqual(fetched.status_code, 200)
        fetched_payload = fetched.json()
        self.assertEqual(fetched_payload["title"], "Updated Bridge Title")
        self.assertEqual(len(fetched_payload["attachments"]), 1)
        self.assertEqual(len(fetched_payload["notes"]), 1)

        exported = self.request("POST", "/sync/export", headers=self.headers, json={"item_key": item_key})
        self.assertEqual(exported.status_code, 200)
        self.assertEqual(exported.json()["exported"], 1)

        index = json.loads((self.settings.metadata_dir / "index.json").read_text(encoding="utf-8"))
        self.assertIn(item_key, index["items"])
        self.assertIn(attachment_key, index["attachments"])
        self.assertIn(note_key, index["notes"])
        note_path = Path(index["notes"][note_key]["markdown_path"])
        self.assertTrue(note_path.exists())
        self.assertIn("# Summary", note_path.read_text(encoding="utf-8"))

    def test_prepare_obsidian_sync_uses_note_title_and_frontmatter(self) -> None:
        created = self.create_manual_item("Obsidian Source")
        item_key = str(created["item_key"])
        noted = self.request(
            "POST",
            f"/items/{item_key}/notes",
            headers=self.headers,
            json={"title": "Reading Note", "markdown": "Important result."},
        )
        self.assertEqual(noted.status_code, 200)
        note_key = noted.json()["note_key"]

        prepared = self.request(
            "POST",
            "/obsidian/notes/prepare-sync",
            headers=self.headers,
            json={"item_key": item_key, "note_key": note_key, "note_title": "Reading Note"},
        )
        self.assertEqual(prepared.status_code, 200)
        payload = prepared.json()
        self.assertEqual(payload["filename"], "Reading Note.md")
        self.assertEqual(payload["vault_relative_path"], "Zotero Notes/Reading Note.md")
        self.assertEqual(payload["frontmatter"]["zotero_item_key"], item_key)
        self.assertEqual(payload["frontmatter"]["zotero_note_key"], note_key)
        self.assertEqual(payload["frontmatter"]["zab_stable_id"], f"zotero-note-{note_key}")
        self.assertIn("/obsidian/open/", payload["resolver_url"])

    def test_prepare_obsidian_sync_appends_note_key_when_name_conflicts(self) -> None:
        existing = self.obsidian_vault / "Zotero Notes" / "Reading Note.md"
        existing.parent.mkdir(parents=True, exist_ok=True)
        existing.write_text("existing", encoding="utf-8")
        created = self.create_manual_item("Obsidian Conflict Source")
        item_key = str(created["item_key"])
        noted = self.request(
            "POST",
            f"/items/{item_key}/notes",
            headers=self.headers,
            json={"title": "Conflict", "markdown": "Body"},
        )
        self.assertEqual(noted.status_code, 200)
        note_key = noted.json()["note_key"]

        prepared = self.request(
            "POST",
            "/obsidian/notes/prepare-sync",
            headers=self.headers,
            json={"item_key": item_key, "note_key": note_key, "note_title": "Reading Note"},
        )
        self.assertEqual(prepared.status_code, 200)
        self.assertEqual(prepared.json()["filename"], f"Reading Note - {note_key}.md")

    def test_obsidian_sync_status_updates_mirror_index(self) -> None:
        created = self.create_manual_item("Obsidian Status Source")
        item_key = str(created["item_key"])
        noted = self.request(
            "POST",
            f"/items/{item_key}/notes",
            headers=self.headers,
            json={"title": "Status Note", "markdown": "Body"},
        )
        note_key = noted.json()["note_key"]
        prepared = self.request(
            "POST",
            "/obsidian/notes/prepare-sync",
            headers=self.headers,
            json={"item_key": item_key, "note_key": note_key, "note_title": "Status Note"},
        ).json()

        status = self.request(
            "POST",
            f"/obsidian/notes/{note_key}/sync-status",
            headers=self.headers,
            json={
                "item_key": item_key,
                "stable_id": prepared["stable_id"],
                "status": "synced",
                "markdown_path": prepared["markdown_path"],
                "vault_relative_path": prepared["vault_relative_path"],
            },
        )
        self.assertEqual(status.status_code, 200)
        index = json.loads((self.settings.metadata_dir / "index.json").read_text(encoding="utf-8"))
        obsidian = index["notes"][note_key]["obsidian"]
        self.assertEqual(obsidian["better_notes_sync_status"], "synced")
        self.assertEqual(obsidian["last_known_relative_path"], prepared["vault_relative_path"])

    def test_obsidian_sync_status_rejects_paths_outside_vault(self) -> None:
        created = self.create_manual_item("Obsidian Path Source")
        item_key = str(created["item_key"])
        noted = self.request(
            "POST",
            f"/items/{item_key}/notes",
            headers=self.headers,
            json={"title": "Path Note", "markdown": "Body"},
        )
        note_key = noted.json()["note_key"]
        prepared = self.request(
            "POST",
            "/obsidian/notes/prepare-sync",
            headers=self.headers,
            json={"item_key": item_key, "note_key": note_key, "note_title": "Path Note"},
        ).json()

        status = self.request(
            "POST",
            f"/obsidian/notes/{note_key}/sync-status",
            headers=self.headers,
            json={
                "item_key": item_key,
                "stable_id": prepared["stable_id"],
                "status": "synced",
                "vault_relative_path": "../outside.md",
            },
        )
        self.assertEqual(status.status_code, 422)
        self.assertEqual(status.json()["error"]["code"], "path_outside_obsidian_vault")

    def test_obsidian_resolver_repairs_moved_file_by_stable_id(self) -> None:
        created = self.create_manual_item("Obsidian Move Source")
        item_key = str(created["item_key"])
        noted = self.request(
            "POST",
            f"/items/{item_key}/notes",
            headers=self.headers,
            json={"title": "Move Note", "markdown": "Body"},
        )
        note_key = noted.json()["note_key"]
        prepared = self.request(
            "POST",
            "/obsidian/notes/prepare-sync",
            headers=self.headers,
            json={"item_key": item_key, "note_key": note_key, "note_title": "Move Note"},
        ).json()
        original = Path(prepared["markdown_path"])
        original.write_text(
            "\n".join(
                [
                    "---",
                    f"zotero_item_key: {item_key}",
                    f"zotero_note_key: {note_key}",
                    f"zab_stable_id: {prepared['stable_id']}",
                    "---",
                    "Moved content",
                ]
            ),
            encoding="utf-8",
        )
        moved = self.obsidian_vault / "Moved" / "Move Note.md"
        moved.parent.mkdir(parents=True, exist_ok=True)
        original.replace(moved)

        opened = self.request(
            "GET",
            f"/obsidian/open/{prepared['stable_id']}",
            params={"token": prepared["link_token"]},
            allow_redirects=False,
        )
        self.assertEqual(opened.status_code, 302)
        self.assertIn("obsidian://open", opened.headers["location"])
        self.assertIn("Moved%2FMove%20Note", opened.headers["location"])

    def test_obsidian_reindex_scans_frontmatter(self) -> None:
        md_path = self.obsidian_vault / "Manual" / "Manual Note.md"
        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text(
            "---\nzotero_item_key: I0001\nzotero_note_key: N0001\nzab_stable_id: zotero-note-N0001\n---\nBody",
            encoding="utf-8",
        )
        reindexed = self.request(
            "POST",
            "/obsidian/reindex",
            headers=self.headers,
            json={"limit": 100},
        )
        self.assertEqual(reindexed.status_code, 200)
        self.assertEqual(reindexed.json()["indexed"], 1)

    def test_manual_creator_omits_null_alternate_name(self) -> None:
        created = self.request(
            "POST",
            "/items",
            headers=self.headers,
            json={
                "manual_fields": {
                    "fields": {"title": "Creator serialization"},
                    "creators": [
                        {"creatorType": "author", "firstName": "Ada", "lastName": "Context"}
                    ],
                }
            },
        )
        self.assertEqual(created.status_code, 200)
        creator = self.backend.items[created.json()["item_key"]]["creators"][0]
        self.assertEqual(creator["firstName"], "Ada")
        self.assertEqual(creator["lastName"], "Context")
        self.assertNotIn("name", creator)

    def test_create_from_pdf_marks_needs_review_and_dedupes_by_checksum(self) -> None:
        self.raise_doi_lookup = True
        self.pdf_metadata_return = {"title": "Recovered From PDF"}

        created = self.request("POST", "/items", headers=self.headers, json={"pdf_path": str(self.sample_pdf)})
        self.assertEqual(created.status_code, 200)
        payload = created.json()
        self.assertEqual(payload["sync_status"], "needs_review")
        self.assertTrue(payload["attachment_key"])

        duplicate = self.request("POST", "/items", headers=self.headers, json={"pdf_path": str(self.sample_pdf)})
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(duplicate.json()["error"]["code"], "duplicate_pdf")

    def test_export_limit_counts_only_exported_items(self) -> None:
        created = [self.create_manual_item(f"Item {index}") for index in range(1, 4)]
        item_keys = [payload["item_key"] for payload in created]
        self.backend.top_level_items = [
            self.backend._api_item(self.backend.items[item_keys[0]]),
            {
                "library": {"id": self.backend.library_id},
                "key": "TOPNOTE1",
                "version": 1,
                "data": {
                    "itemType": "note",
                    "title": "Top-level note",
                    "dateModified": now_iso(),
                },
            },
            self.backend._api_item(self.backend.items[item_keys[1]]),
            self.backend._api_item(self.backend.items[item_keys[2]]),
        ]

        exported = self.request("POST", "/sync/export", headers=self.headers, json={"limit": 3})
        self.assertEqual(exported.status_code, 200)
        payload = exported.json()
        self.assertEqual(payload["exported"], 3)
        self.assertEqual(payload["item_keys"], item_keys)

    def test_export_batch_saves_index_once(self) -> None:
        created = [self.create_manual_item(f"Batch Item {index}") for index in range(1, 4)]
        item_keys = [payload["item_key"] for payload in created]
        save_calls = 0
        original_save = self.mirror._save_index

        def counting_save(index: dict[str, object]) -> None:
            nonlocal save_calls
            save_calls += 1
            original_save(index)

        self.mirror._save_index = counting_save  # type: ignore[method-assign]
        try:
            exported = self.request("POST", "/sync/export", headers=self.headers, json={"limit": 3})
        finally:
            self.mirror._save_index = original_save  # type: ignore[method-assign]

        self.assertEqual(exported.status_code, 200)
        self.assertEqual(exported.json()["item_keys"], item_keys)
        self.assertEqual(save_calls, 1)

    def test_update_with_stale_version_returns_409(self) -> None:
        created = self.request(
            "POST",
            "/items",
            headers=self.headers,
            json={"manual_fields": {"fields": {"title": "Versioned Item"}}},
        )
        self.assertEqual(created.status_code, 200)
        item_key = created.json()["item_key"]

        conflict = self.request(
            "PATCH",
            f"/items/{item_key}",
            headers=self.headers,
            json={"version": 0, "fields": {"title": "Should Fail"}},
        )
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(conflict.json()["error"]["code"], "version_conflict")
    def test_http_create_and_reparent_collections(self) -> None:
        themes = self.request("POST", "/collections", headers=self.headers, json={"name": "10_研究主题"})
        self.assertEqual(themes.status_code, 200)
        themes_payload = themes.json()

        shelves = self.request("POST", "/collections", headers=self.headers, json={"name": "30_专题书架"})
        self.assertEqual(shelves.status_code, 200)
        shelves_payload = shelves.json()

        harq = self.request(
            "POST",
            "/collections",
            headers=self.headers,
            json={"name": "HARQ", "parent_key": themes_payload["collection_key"]},
        )
        self.assertEqual(harq.status_code, 200)
        harq_payload = harq.json()
        self.assertEqual(harq_payload["parent_key"], themes_payload["collection_key"])

        moved = self.request(
            "PATCH",
            f"/collections/{harq_payload['collection_key']}",
            headers=self.headers,
            json={
                "version": harq_payload["version"],
                "name": "HARQ专题",
                "parent_key": shelves_payload["collection_key"],
            },
        )
        self.assertEqual(moved.status_code, 200)
        moved_payload = moved.json()
        self.assertEqual(moved_payload["name"], "HARQ专题")
        self.assertEqual(moved_payload["parent_key"], shelves_payload["collection_key"])

        fetched = self.request(
            "GET",
            f"/collections/{harq_payload['collection_key']}",
            headers=self.headers,
        )
        self.assertEqual(fetched.status_code, 200)
        self.assertEqual(fetched.json()["parent_key"], shelves_payload["collection_key"])

        listed = self.request("GET", "/collections", headers=self.headers)
        self.assertEqual(listed.status_code, 200)
        by_key = {collection["collection_key"]: collection for collection in listed.json()}
        self.assertEqual(by_key[harq_payload["collection_key"]]["name"], "HARQ专题")
        self.assertEqual(by_key[harq_payload["collection_key"]]["parent_key"], shelves_payload["collection_key"])

    def test_mcp_list_tools_and_import_pdf(self) -> None:
        http_client = BridgeHttpClient(self.base_url, self.settings.api_token, session=self.session)
        server = ZoteroBridgeMCPServer(http_client)

        initialized = server.handle_request(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "test", "version": "1.0"}},
            }
        )
        self.assertEqual(initialized["result"]["serverInfo"]["name"], "zotero-agent-bridge")
        self.assertIn("resources", initialized["result"]["capabilities"])

        tools = server.handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        tool_names = [tool["name"] for tool in tools["result"]["tools"]]
        self.assertIn("import_pdf", tool_names)
        self.assertIn("create_note", tool_names)

        resources = server.handle_request({"jsonrpc": "2.0", "id": 21, "method": "resources/list", "params": {}})
        resource_uris = [resource["uri"] for resource in resources["result"]["resources"]]
        self.assertIn("zotero://bridge/health", resource_uris)
        self.assertIn("zotero://server/info", resource_uris)

        templates = server.handle_request(
            {"jsonrpc": "2.0", "id": 22, "method": "resources/templates/list", "params": {}}
        )
        self.assertEqual(templates["result"]["resourceTemplates"][0]["uriTemplate"], "zotero://items/{item_key}")

        health = server.handle_request(
            {"jsonrpc": "2.0", "id": 23, "method": "resources/read", "params": {"uri": "zotero://bridge/health"}}
        )
        self.assertIn('"status": "ok"', health["result"]["contents"][0]["text"])

        self.pdf_metadata_return = {"title": "MCP Imported PDF"}
        called = server.handle_request(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "import_pdf",
                    "arguments": {
                        "pdf_path": str(self.sample_pdf),
                        "manual_fields": {"fields": {"title": "MCP Imported Item"}},
                    },
                },
            }
        )
        result = called["result"]
        self.assertFalse(result["isError"])
        structured = result["structuredContent"]
        self.assertEqual(structured["title"], "MCP Imported Item")
        self.assertTrue(structured["attachment_key"])

        search = server.handle_request(
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {"name": "search_items", "arguments": {"q": "MCP Imported Item"}},
            }
        )
        self.assertFalse(search["result"]["isError"])
        items = search["result"]["structuredContent"]["items"]
        self.assertEqual(len(items), 1)

    def test_apply_default_collection_tree_rehomes_existing_collections(self) -> None:
        seeded = [
            ("ZRHJDMFQ", "Exata文档", None),
            ("L6QUUVBZ", "ModelLibrarys", "ZRHJDMFQ"),
            ("UGM8HKPE", "手册、建议书", None),
            ("6XFKDIQM", "CCSDS", "UGM8HKPE"),
            ("HL2J63GW", "杂七杂八", None),
            ("37ANA6WH", "论文", None),
            ("9ZTT5NXY", "FEC", "37ANA6WH"),
            ("M3KRTBCZ", "网络编码", "9ZTT5NXY"),
            ("IZZ84DM3", "HARQ", "37ANA6WH"),
            ("GBVFZDPX", "卫星场景HARQ", "IZZ84DM3"),
            ("8WK2R8EB", "信道", "37ANA6WH"),
            ("DJQ7VVI8", "卫星激光通信", "37ANA6WH"),
            ("539GTEZA", "同门论文", "37ANA6WH"),
            ("MDSFUHPI", "拥塞控制", "37ANA6WH"),
            ("54XWKYG5", "星地物理帧策略", "37ANA6WH"),
            ("7H8VSG3J", "机器学习", "37ANA6WH"),
            ("LQRRRFMS", "ClassicPaperForLLM", "7H8VSG3J"),
            ("XP83YX6Q", "DeepSeek", "7H8VSG3J"),
            ("C23WAPA4", "NeurIPS2025bestpaper", "7H8VSG3J"),
            ("66CJ9XTF", "强化学习", "7H8VSG3J"),
            ("N4JZLXND", "深度学习", "7H8VSG3J"),
            ("XLHQC9PW", "综述类", "37ANA6WH"),
            ("BGMP5ZS2", "语义编码", "37ANA6WH"),
            ("R9JKSHZ5", "遥感卫星", "37ANA6WH"),
        ]
        for collection_key, name, parent_key in seeded:
            self.backend.seed_collection(collection_key, name, parent_key)

        result = apply_default_collection_tree(self.backend, self.writer)

        def build_path(collection_key: str) -> str:
            parts = []
            current_key = collection_key
            while current_key:
                current = self.backend.collections[current_key]
                parts.append(str(current["name"]))
                current_key = current["parent_key"]
            return "/".join(reversed(parts))

        self.assertEqual(build_path("HL2J63GW"), "00_待整理")
        self.assertEqual(build_path("9ZTT5NXY"), "10_研究主题/12_可靠传输与编码/FEC")
        self.assertEqual(build_path("M3KRTBCZ"), "10_研究主题/12_可靠传输与编码/FEC/网络编码")
        self.assertEqual(build_path("XP83YX6Q"), "30_专题书架/模型专题/DeepSeek")
        self.assertEqual(build_path("6XFKDIQM"), "40_工具与标准/CCSDS标准")
        self.assertEqual(result["collection_paths"]["theses"], "20_论文类型/学位论文")

    def test_classify_library_suggests_topic_and_paper_type(self) -> None:
        seeded = [
            ("HL2J63GW", "杂七杂八", None),
            ("37ANA6WH", "论文", None),
            ("IZZ84DM3", "HARQ", "37ANA6WH"),
        ]
        for collection_key, name, parent_key in seeded:
            self.backend.seed_collection(collection_key, name, parent_key)

        created = self.backend.handle_command(
            "create_item",
            {
                "item_type": "journalArticle",
                "fields": {
                    "title": "Hybrid Automatic Repeat Request (HARQ) in Wireless Communications Systems and Standards: A Contemporary Survey",
                    "abstractNote": "This survey reviews HARQ design choices and protocol evolution.",
                },
                "collections": ["37ANA6WH"],
            },
        )

        result = classify_library(self.service, apply=False)
        report_item = next(item for item in result["items"] if item["item_key"] == created["item_key"])

        self.assertTrue(report_item["changed"])
        self.assertIn("10_研究主题/12_可靠传输与编码/HARQ", report_item["suggested_collections"])
        self.assertIn("20_论文类型/综述", report_item["suggested_collections"])
        self.assertIn("10_研究主题", report_item["final_collections"])
        self.assertEqual(result["stats"]["updated"], 0)

    def test_classify_library_apply_moves_inbox_manual_and_falls_back_to_inbox(self) -> None:
        seeded = [
            ("HL2J63GW", "杂七杂八", None),
            ("UGM8HKPE", "手册、建议书", None),
        ]
        for collection_key, name, parent_key in seeded:
            self.backend.seed_collection(collection_key, name, parent_key)

        manual_item = self.backend.handle_command(
            "create_item",
            {
                "item_type": "document",
                "fields": {"title": "OMNeT++手册"},
                "collections": ["HL2J63GW"],
            },
        )
        unknown_item = self.backend.handle_command(
            "create_item",
            {
                "item_type": "journalArticle",
                "fields": {"title": "An Information Flow Model for Conflict and Fission in Small Groups"},
                "collections": [],
            },
        )

        result = classify_library(self.service, apply=True)
        report_items = {item["item_key"]: item for item in result["items"]}

        self.assertIn("40_工具与标准/其他手册", report_items[manual_item["item_key"]]["final_collections"])
        self.assertNotIn("00_待整理", report_items[manual_item["item_key"]]["final_collections"])
        self.assertEqual(
            [collection["name"] for collection in self.backend.items[manual_item["item_key"]]["collections"]],
            ["其他手册"],
        )

        self.assertEqual(report_items[unknown_item["item_key"]]["final_collections"], ["00_待整理"])
        self.assertEqual(
            [collection["name"] for collection in self.backend.items[unknown_item["item_key"]]["collections"]],
            ["00_待整理"],
        )
        self.assertEqual(result["stats"]["updated"], 2)

    def test_classify_library_does_not_mark_survey_from_abstract_only_phrase(self) -> None:
        seeded = [
            ("37ANA6WH", "论文", None),
        ]
        for collection_key, name, parent_key in seeded:
            self.backend.seed_collection(collection_key, name, parent_key)

        created = self.backend.handle_command(
            "create_item",
            {
                "item_type": "journalArticle",
                "fields": {
                    "title": "Online Planning Algorithms for POMDPs",
                    "abstractNote": "We summarize prior art and discuss state of the art planning baselines.",
                },
                "collections": ["37ANA6WH"],
            },
        )

        result = classify_library(self.service, apply=False)
        report_item = next(item for item in result["items"] if item["item_key"] == created["item_key"])

        self.assertNotIn("20_论文类型/综述", report_item["suggested_collections"])

    def test_classify_library_keeps_thesis_out_of_ccsds_standards(self) -> None:
        seeded = [
            ("37ANA6WH", "论文", None),
            ("UGM8HKPE", "手册、建议书", None),
        ]
        for collection_key, name, parent_key in seeded:
            self.backend.seed_collection(collection_key, name, parent_key)

        created = self.backend.handle_command(
            "create_item",
            {
                "item_type": "thesis",
                "fields": {
                    "title": "卫星光网络组网协议与路由算法研究",
                    "abstractNote": "本文研究了卫星光网络组网协议与路由算法，并设计了 MPLS over CCSDS 协议扩展。",
                    "thesisType": "博士学位论文",
                },
                "tags": [{"tag": "MPLS over CCSDS"}],
                "collections": [],
            },
        )

        result = classify_library(self.service, apply=False)
        report_item = next(item for item in result["items"] if item["item_key"] == created["item_key"])

        self.assertIn("20_论文类型/学位论文", report_item["suggested_collections"])
        self.assertNotIn("40_工具与标准/CCSDS标准", report_item["suggested_collections"])

    def test_classify_library_skips_child_note_items(self) -> None:
        parent = self.backend.handle_command(
            "create_item",
            {
                "item_type": "journalArticle",
                "fields": {"title": "Parent Paper"},
                "collections": [],
            },
        )
        note_key = "N_TOP_1"
        self.backend.items[note_key] = {
            "library_id": self.backend.library_id,
            "item_key": note_key,
            "attachment_key": None,
            "note_key": note_key,
            "slug": None,
            "pdf_path": None,
            "checksum": None,
            "version": 1,
            "item_type": "note",
            "title": "",
            "doi": None,
            "url": None,
            "fields": {"itemType": "note", "parentItem": parent["item_key"], "note": "child note"},
            "creators": [],
            "tags": [],
            "collections": [],
            "attachments": [],
            "notes": [],
            "updated_at": now_iso(),
            "sync_status": "synced",
        }
        self.backend.top_level_items = [
            {
                "library": {"id": self.backend.library_id},
                "key": note_key,
                "version": 1,
                "data": {
                    "itemType": "note",
                    "title": "",
                    "DOI": None,
                    "tags": [],
                    "dateModified": now_iso(),
                },
            }
        ]

        result = classify_library(self.service, apply=False)

        self.assertEqual(result["stats"]["scanned"], 1)
        self.assertEqual(result["stats"]["candidates"], 0)
        self.assertEqual(result["items"], [])



if __name__ == "__main__":
    unittest.main()






