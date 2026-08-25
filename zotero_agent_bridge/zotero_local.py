from __future__ import annotations

from pathlib import Path, PureWindowsPath
from typing import Any

import requests

from .errors import BridgeError
from .utils import file_uri_to_path, now_iso, strip_html


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


    def _list_collections(self) -> list[dict[str, Any]]:
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


    def _get_collections_map(self) -> dict[str, str]:
        if self._collection_cache is not None:
            return self._collection_cache
        self._collection_cache = {
            collection["collection_key"]: collection["name"] for collection in self._list_collections()
        }
        return self._collection_cache


    def _get_item(self, item_key: str) -> dict[str, Any]:
        return self._request(f"items/{item_key}")

    def _get_children(self, item_key: str, item_type: str | None = None) -> list[dict[str, Any]]:
        children: list[dict[str, Any]] = []
        start = 0
        limit = 100
        while True:
            params: dict[str, Any] = {"limit": limit, "start": start}
            if item_type:
                params["itemType"] = item_type
            batch = self._request(f"items/{item_key}/children", params=params)
            children.extend(batch)
            if len(batch) < limit:
                break
            start += len(batch)
        return children



    def _resolve_attachment_path(self, attachment: dict[str, Any]) -> str | None:
        data = attachment["data"]
        enclosure = attachment.get("links", {}).get("enclosure", {}).get("href")
        if enclosure:
            return file_uri_to_path(enclosure)
        path_value = data.get("path")
        if not path_value:
            return None
        if path_value.startswith("file:"):
            return file_uri_to_path(path_value)
        if path_value.startswith("attachments:") and self.base_attachment_path:
            relative_path = path_value.split("attachments:", 1)[1].lstrip("\\/")
            return f"{self.base_attachment_path}\\{relative_path}".replace("\\\\", "\\")
        if Path(path_value).expanduser().is_absolute() or PureWindowsPath(path_value).is_absolute():
            return path_value
        return None

    def _annotation_record(self, annotation: dict[str, Any], item_key: str) -> dict[str, Any]:
        data = annotation["data"]
        return {
            "library_id": annotation["library"]["id"],
            "item_key": item_key,
            "attachment_key": data.get("parentItem"),
            "annotation_key": annotation["key"],
            "annotation_type": data.get("annotationType"),
            "text": data.get("annotationText") or "",
            "comment": data.get("annotationComment") or "",
            "color": data.get("annotationColor"),
            "page_label": data.get("annotationPageLabel"),
            "position": data.get("annotationPosition"),
            "sort_index": data.get("annotationSortIndex"),
            "tags": [tag.get("tag") for tag in data.get("tags", []) if tag.get("tag")],
            "updated_at": data.get("dateModified") or now_iso(),
        }

    def _attachment_annotations(
        self,
        attachment_key: str,
        item_key: str,
    ) -> tuple[list[dict[str, Any]], str | None]:
        try:
            children = self._get_children(attachment_key, item_type="annotation")
        except BridgeError as exc:
            return [], f"Could not load annotations for attachment {attachment_key}: {exc.message}"
        annotations = [
            self._annotation_record(child, item_key)
            for child in children
            if child.get("data", {}).get("itemType") == "annotation"
        ]
        return annotations, None

    def build_bundle(self, item_key: str) -> dict[str, Any]:
        item = self._get_item(item_key)
        children = self._get_children(item_key)
        collection_map = self._get_collections_map()
        attachments = []
        notes = []
        annotations = []
        warnings = []
        for child in children:
            child_data = child["data"]
            if child_data["itemType"] == "attachment":
                content_type = child_data.get("contentType")
                pdf_path = self._resolve_attachment_path(child)
                child_annotations: list[dict[str, Any]] = []
                if content_type == "application/pdf" or str(pdf_path or "").lower().endswith(".pdf"):
                    child_annotations, warning = self._attachment_annotations(child["key"], item_key)
                    annotations.extend(child_annotations)
                    if warning:
                        warnings.append(warning)
                attachments.append(
                    {
                        "library_id": child["library"]["id"],
                        "item_key": child_data.get("parentItem"),
                        "attachment_key": child["key"],
                        "note_key": None,
                        "slug": None,
                        "title": child_data.get("title"),
                        "pdf_path": pdf_path,
                        "path": child_data.get("path"),
                        "content_type": content_type,
                        "link_mode": child_data.get("linkMode"),
                        "checksum": None,
                        "updated_at": child_data.get("dateModified") or now_iso(),
                        "sync_status": "synced",
                        "annotations": child_annotations,
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
            "annotations": annotations,
            "warnings": warnings,
            "updated_at": data.get("dateModified") or now_iso(),
            "sync_status": "synced",
        }

