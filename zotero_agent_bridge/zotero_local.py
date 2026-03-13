from __future__ import annotations

from typing import Any

import requests

from .errors import BridgeError
from .utils import file_uri_to_path, normalize_doi, now_iso, strip_html


class ZoteroLocalClient:
    def __init__(self, base_url: str, user_agent: str, base_attachment_path: str | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.user_agent = user_agent
        self.base_attachment_path = base_attachment_path
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent})
        self._collection_cache: dict[str, str] | None = None

    def _request(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        url = f"{self.base_url}/{path.lstrip('/')}"
        try:
            response = self.session.get(url, params=params, timeout=15)
        except requests.RequestException as exc:
            raise BridgeError(503, "zotero_unavailable", "Zotero Local API is unavailable", {"error": str(exc)}) from exc
        if response.status_code >= 400:
            raise BridgeError(
                503 if response.status_code >= 500 else 404,
                "zotero_request_failed",
                f"Zotero Local API request failed with status {response.status_code}",
                {"path": path, "body": response.text[:500]},
            )
        return response.json()

    def is_available(self) -> bool:
        try:
            self._request("items", params={"limit": 1})
            return True
        except BridgeError:
            return False

    def invalidate_collection_cache(self) -> None:
        self._collection_cache = None

    def list_collections(self) -> list[dict[str, Any]]:
        collections = []
        start = 0
        limit = 100
        while True:
            batch = self._request("collections", params={"limit": limit, "start": start})
            if not batch:
                break
            for collection in batch:
                data = collection["data"]
                parent_key = data.get("parentCollection") or None
                collections.append(
                    {
                        "library_id": collection["library"]["id"],
                        "collection_key": collection["key"],
                        "version": collection["version"],
                        "name": data["name"],
                        "parent_key": parent_key,
                    }
                )
            if len(batch) < limit:
                break
            start += limit
        return collections

    def get_collection(self, collection_key: str) -> dict[str, Any]:
        collection = self._request(f"collections/{collection_key}")
        data = collection["data"]
        parent_key = data.get("parentCollection") or None
        return {
            "library_id": collection["library"]["id"],
            "collection_key": collection["key"],
            "version": collection["version"],
            "name": data["name"],
            "parent_key": parent_key,
        }

    def get_collections_map(self) -> dict[str, str]:
        if self._collection_cache is not None:
            return self._collection_cache
        self._collection_cache = {
            collection["collection_key"]: collection["name"] for collection in self.list_collections()
        }
        return self._collection_cache

    def search_items(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        items = self._request(
            "items",
            params={"q": query, "qmode": "everything", "limit": limit, "itemType": "-attachment"},
        )
        return [item for item in items if item["data"]["itemType"] not in {"attachment", "note"}]

    def get_item(self, item_key: str) -> dict[str, Any]:
        return self._request(f"items/{item_key}")

    def get_children(self, item_key: str, item_type: str | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": 100}
        if item_type:
            params["itemType"] = item_type
        return self._request(f"items/{item_key}/children", params=params)

    def list_top_level_items(self, start: int = 0, limit: int = 100) -> list[dict[str, Any]]:
        return self._request("items/top", params={"start": start, "limit": limit, "itemType": "-attachment"})

    def find_by_doi(self, doi: str) -> dict[str, Any] | None:
        normalized = normalize_doi(doi)
        if not normalized:
            return None
        for item in self.search_items(normalized, limit=25):
            if normalize_doi(item["data"].get("DOI")) == normalized:
                return item
        return None

    def resolve_attachment_path(self, attachment: dict[str, Any]) -> str | None:
        data = attachment["data"]
        enclosure = attachment.get("links", {}).get("enclosure", {}).get("href")
        if enclosure:
            return file_uri_to_path(enclosure)
        path_value = data.get("path")
        if path_value and path_value.startswith("attachments:") and self.base_attachment_path:
            relative_path = path_value.split("attachments:", 1)[1].lstrip("\\/")
            return f"{self.base_attachment_path}\\{relative_path}".replace("\\\\", "\\")
        return None

    def build_bundle(self, item_key: str) -> dict[str, Any]:
        item = self.get_item(item_key)
        children = self.get_children(item_key)
        collection_map = self.get_collections_map()
        attachments = []
        notes = []
        for child in children:
            child_data = child["data"]
            if child_data["itemType"] == "attachment":
                attachments.append(
                    {
                        "library_id": child["library"]["id"],
                        "item_key": child_data.get("parentItem"),
                        "attachment_key": child["key"],
                        "note_key": None,
                        "slug": None,
                        "title": child_data.get("title"),
                        "pdf_path": self.resolve_attachment_path(child),
                        "path": child_data.get("path"),
                        "content_type": child_data.get("contentType"),
                        "link_mode": child_data.get("linkMode"),
                        "checksum": None,
                        "updated_at": child_data.get("dateModified") or now_iso(),
                        "sync_status": "synced",
                    }
                )
            elif child_data["itemType"] == "note":
                notes.append(
                    {
                        "library_id": child["library"]["id"],
                        "item_key": child_data.get("parentItem"),
                        "attachment_key": None,
                        "note_key": child["key"],
                        "slug": None,
                        "title": strip_html(child_data.get("note"))[:120] or f"Note {child['key']}",
                        "pdf_path": None,
                        "checksum": None,
                        "updated_at": child_data.get("dateModified") or now_iso(),
                        "sync_status": "synced",
                        "note_html": child_data.get("note", ""),
                    }
                )
        data = item["data"]
        excluded = {"creators", "tags", "collections", "relations"}
        fields = {key: value for key, value in data.items() if key not in excluded}
        return {
            "library_id": item["library"]["id"],
            "item_key": item["key"],
            "attachment_key": None,
            "note_key": None,
            "slug": None,
            "pdf_path": None,
            "checksum": None,
            "version": item["version"],
            "item_type": data["itemType"],
            "title": data.get("title") or data.get("shortTitle") or "",
            "doi": data.get("DOI"),
            "url": data.get("url"),
            "fields": fields,
            "creators": data.get("creators", []),
            "tags": [tag["tag"] for tag in data.get("tags", [])],
            "collections": [
                {"key": key, "name": collection_map.get(key, key)} for key in data.get("collections", [])
            ],
            "attachments": attachments,
            "notes": notes,
            "updated_at": data.get("dateModified") or now_iso(),
            "sync_status": "synced",
        }

