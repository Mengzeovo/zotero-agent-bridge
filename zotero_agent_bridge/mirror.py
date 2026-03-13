from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from typing import Any

from .utils import atomic_write_json, atomic_write_text, ensure_dir, html_to_markdownish, now_iso, read_json, slugify


class MirrorStore:
    def __init__(self, metadata_dir: Path, notes_dir: Path) -> None:
        self.metadata_dir = metadata_dir
        self.notes_dir = notes_dir
        self.items_dir = ensure_dir(metadata_dir / "items")
        self.index_path = metadata_dir / "index.json"
        if not self.index_path.exists():
            atomic_write_json(self.index_path, {"items": {}, "attachments": {}, "notes": {}})

    def _load_index(self) -> dict[str, Any]:
        return read_json(self.index_path, default={"items": {}, "attachments": {}, "notes": {}})

    def _save_index(self, index: dict[str, Any]) -> None:
        atomic_write_json(self.index_path, index)

    def index_snapshot(self) -> dict[str, Any]:
        return self._load_index()

    def get_item_record(self, item_key: str) -> dict[str, Any] | None:
        return self._load_index()["items"].get(item_key)

    def find_attachment_by_checksum(self, checksum: str | None) -> dict[str, Any] | None:
        if not checksum:
            return None
        for record in self._load_index()["attachments"].values():
            if record.get("checksum") == checksum:
                return record
        return None

    def find_item_by_doi(self, doi: str | None) -> dict[str, Any] | None:
        if not doi:
            return None
        normalized = doi.lower()
        for record in self._load_index()["items"].values():
            if str(record.get("doi", "")).lower() == normalized:
                return record
        return None

    def apply_index(self, bundle: dict[str, Any], *, index: dict[str, Any] | None = None) -> dict[str, Any]:
        index = index or self._load_index()
        enriched = deepcopy(bundle)
        item_record = index["items"].get(bundle["item_key"])
        if item_record:
            enriched["mirror_ref"] = item_record.get("mirror_ref")
            enriched["sync_status"] = item_record.get("sync_status", enriched.get("sync_status", "synced"))
            enriched["slug"] = item_record.get("slug")
        for attachment in enriched.get("attachments", []):
            record = index["attachments"].get(attachment["attachment_key"])
            if record:
                attachment.update(
                    {
                        "checksum": record.get("checksum"),
                        "mirror_ref": record.get("mirror_ref"),
                        "sync_status": record.get("sync_status", attachment.get("sync_status", "synced")),
                    }
                )
        for note in enriched.get("notes", []):
            record = index["notes"].get(note["note_key"])
            if record:
                note.update(
                    {
                        "mirror_ref": record.get("mirror_ref"),
                        "sync_status": record.get("sync_status", note.get("sync_status", "synced")),
                    }
                )
                if record.get("markdown_path"):
                    note["markdown_path"] = record["markdown_path"]
        return enriched

    def search(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        query_lower = query.strip().lower()
        results = []
        for record in self._load_index()["items"].values():
            haystack = " ".join(
                [
                    record.get("title", ""),
                    record.get("doi", ""),
                    " ".join(record.get("tags", [])),
                    " ".join(collection.get("name", "") for collection in record.get("collections", [])),
                ]
            ).lower()
            if query_lower in haystack:
                results.append(record)
            if len(results) >= limit:
                break
        return results

    def _export_bundle_to_index(
        self,
        bundle: dict[str, Any],
        index: dict[str, Any],
        *,
        note_markdown_overrides: dict[str, str] | None = None,
        attachment_checksums: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        note_markdown_overrides = note_markdown_overrides or {}
        attachment_checksums = attachment_checksums or {}

        slug = slugify(bundle.get("title") or bundle["item_key"], fallback=bundle["item_key"])
        item_path = self.items_dir / f"{bundle['item_key']}.json"
        note_dir = ensure_dir(self.notes_dir / slug)
        item_record = {
            "library_id": bundle["library_id"],
            "item_key": bundle["item_key"],
            "attachment_key": None,
            "note_key": None,
            "slug": slug,
            "pdf_path": None,
            "checksum": None,
            "updated_at": bundle.get("updated_at") or now_iso(),
            "sync_status": bundle.get("sync_status", "synced"),
            "title": bundle.get("title"),
            "doi": bundle.get("doi"),
            "tags": bundle.get("tags", []),
            "collections": bundle.get("collections", []),
            "mirror_ref": str(item_path.resolve()),
        }
        index["items"][bundle["item_key"]] = item_record

        for attachment in bundle.get("attachments", []):
            checksum = attachment_checksums.get(attachment["attachment_key"]) or attachment.get("checksum")
            record = {
                "library_id": attachment["library_id"],
                "item_key": attachment["item_key"],
                "attachment_key": attachment["attachment_key"],
                "note_key": None,
                "slug": slug,
                "pdf_path": attachment.get("pdf_path"),
                "checksum": checksum,
                "updated_at": attachment.get("updated_at") or now_iso(),
                "sync_status": attachment.get("sync_status", bundle.get("sync_status", "synced")),
                "title": attachment.get("title"),
                "mirror_ref": str(item_path.resolve()),
            }
            index["attachments"][attachment["attachment_key"]] = record
            attachment["checksum"] = checksum

        for note in bundle.get("notes", []):
            markdown_content = note_markdown_overrides.get(note["note_key"]) or html_to_markdownish(note.get("note_html"))
            note_path = note_dir / f"{note['note_key']}.md"
            atomic_write_text(note_path, markdown_content.strip() + "\n")
            record = {
                "library_id": note["library_id"],
                "item_key": note["item_key"],
                "attachment_key": None,
                "note_key": note["note_key"],
                "slug": slug,
                "pdf_path": None,
                "checksum": None,
                "updated_at": note.get("updated_at") or now_iso(),
                "sync_status": note.get("sync_status", bundle.get("sync_status", "synced")),
                "title": note.get("title"),
                "markdown_path": str(note_path.resolve()),
                "mirror_ref": str(note_path.resolve()),
            }
            index["notes"][note["note_key"]] = record
            note["markdown_path"] = str(note_path.resolve())
            note["mirror_ref"] = str(note_path.resolve())

        exported_bundle = deepcopy(bundle)
        exported_bundle["slug"] = slug
        exported_bundle["mirror_ref"] = str(item_path.resolve())
        atomic_write_json(item_path, exported_bundle)
        return item_record

    @contextmanager
    def export_session(self):
        index = self._load_index()
        dirty = False

        def export(
            bundle: dict[str, Any],
            *,
            note_markdown_overrides: dict[str, str] | None = None,
            attachment_checksums: dict[str, str] | None = None,
        ) -> dict[str, Any]:
            nonlocal dirty
            dirty = True
            return self._export_bundle_to_index(
                bundle,
                index,
                note_markdown_overrides=note_markdown_overrides,
                attachment_checksums=attachment_checksums,
            )

        try:
            yield export
        finally:
            if dirty:
                self._save_index(index)

    def export_bundle(
        self,
        bundle: dict[str, Any],
        *,
        note_markdown_overrides: dict[str, str] | None = None,
        attachment_checksums: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        with self.export_session() as export:
            return export(
                bundle,
                note_markdown_overrides=note_markdown_overrides,
                attachment_checksums=attachment_checksums,
            )

    def get_bundle(self, item_key: str) -> dict[str, Any] | None:
        item_path = self.items_dir / f"{item_key}.json"
        if not item_path.exists():
            return None
        bundle = read_json(item_path)
        return self.apply_index(bundle)
