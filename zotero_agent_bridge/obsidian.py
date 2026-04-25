from __future__ import annotations

import re
import secrets
from pathlib import Path
from typing import Any
from urllib.parse import quote

from .config import Settings
from .errors import BridgeError
from .models import (
    ObsidianNoteSyncPrepared,
    ObsidianReindexRequest,
    ObsidianSyncStatusRequest,
    PrepareObsidianNoteSyncRequest,
)
from .utils import atomic_write_json, ensure_dir, now_iso, read_json, strip_html


INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
FRONTMATTER_RE = re.compile(r"^---\s*\n(?P<body>.*?)\n---\s*(?:\n|$)", re.DOTALL)


def safe_markdown_filename(value: str, fallback: str) -> str:
    cleaned = strip_html(value).strip() or fallback
    cleaned = INVALID_FILENAME_CHARS.sub(" ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    if not cleaned:
        cleaned = fallback
    return f"{cleaned[:120].rstrip()}.md"


def parse_simple_frontmatter(text: str) -> dict[str, str]:
    match = FRONTMATTER_RE.match(text.replace("\r\n", "\n"))
    if not match:
        return {}
    result: dict[str, str] = {}
    for raw_line in match.group("body").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        result[key.strip()] = value.strip().strip("\"'")
    return result


class ObsidianBridge:
    def __init__(self, settings: Settings, mirror) -> None:
        self.settings = settings
        self.mirror = mirror

    @property
    def index_path(self) -> Path:
        if not self.settings.obsidian or not self.settings.obsidian.index_path:
            raise BridgeError(422, "obsidian_not_configured", "Obsidian index path is not configured")
        return self.settings.obsidian.index_path

    @property
    def vault_path(self) -> Path:
        if not self.settings.obsidian or not self.settings.obsidian.vault_path:
            raise BridgeError(422, "obsidian_not_configured", "Obsidian vault_path is not configured")
        return self.settings.obsidian.vault_path.expanduser().resolve()

    @property
    def vault_name(self) -> str:
        if self.settings.obsidian and self.settings.obsidian.vault_name:
            return self.settings.obsidian.vault_name
        return self.vault_path.name

    @property
    def default_note_dir(self) -> str:
        if not self.settings.obsidian:
            return "Zotero Notes"
        return self.settings.obsidian.default_note_dir.strip("/\\") or "Zotero Notes"

    def _open_base_url(self) -> str:
        configured = self.settings.obsidian.bridge_open_base_url if self.settings.obsidian else None
        return (configured or f"http://{self.settings.host}:{self.settings.port}").rstrip("/")

    def _load_index(self) -> dict[str, Any]:
        return read_json(self.index_path, default={"notes": {}})

    def _save_index(self, index: dict[str, Any]) -> None:
        atomic_write_json(self.index_path, index)

    def _stable_id(self, note_key: str) -> str:
        return f"zotero-note-{note_key}"

    def _resolver_url(self, stable_id: str, link_token: str) -> str:
        return f"{self._open_base_url()}/obsidian/open/{quote(stable_id, safe='')}?token={quote(link_token, safe='')}"

    def _obsidian_uri(self, relative_path: str) -> str:
        file_target = relative_path.replace("\\", "/")
        if file_target.lower().endswith(".md"):
            file_target = file_target[:-3]
        return (
            "obsidian://open"
            f"?vault={quote(self.vault_name, safe='')}"
            f"&file={quote(file_target, safe='')}"
        )

    def _relative_to_vault(self, path: Path) -> str:
        try:
            relative = path.resolve().relative_to(self.vault_path)
        except ValueError as exc:
            raise BridgeError(
                422,
                "path_outside_obsidian_vault",
                "Obsidian markdown path must stay inside the configured vault",
                {"path": str(path), "vault_path": str(self.vault_path)},
            ) from exc
        return relative.as_posix()

    def _choose_target_path(self, note_key: str, note_title: str, existing_relative: str | None) -> tuple[Path, str]:
        if existing_relative:
            existing_path = (self.vault_path / existing_relative).resolve()
            return existing_path, self._relative_to_vault(existing_path)

        target_dir = ensure_dir(self.vault_path / self.default_note_dir)
        primary = target_dir / safe_markdown_filename(note_title, fallback=note_key)
        if not primary.exists():
            return primary, self._relative_to_vault(primary)

        stem = primary.stem
        fallback = target_dir / f"{stem} - {note_key}.md"
        if not fallback.exists():
            return fallback, self._relative_to_vault(fallback)

        counter = 2
        while True:
            candidate = target_dir / f"{stem} - {note_key} - {counter}.md"
            if not candidate.exists():
                return candidate, self._relative_to_vault(candidate)
            counter += 1

    def _upsert_note_record(self, note_key: str, item_key: str, obsidian_payload: dict[str, Any]) -> None:
        index = self.mirror._load_index()
        note_record = index.setdefault("notes", {}).setdefault(
            note_key,
            {
                "library_id": None,
                "item_key": item_key,
                "attachment_key": None,
                "note_key": note_key,
                "slug": None,
                "pdf_path": None,
                "checksum": None,
                "updated_at": now_iso(),
                "sync_status": "synced",
                "title": None,
                "markdown_path": None,
                "mirror_ref": None,
            },
        )
        note_record["item_key"] = item_key
        note_record["updated_at"] = now_iso()
        note_record["obsidian"] = {
            **(note_record.get("obsidian") or {}),
            **obsidian_payload,
        }
        self.mirror._save_index(index)

    def prepare_sync(self, request: PrepareObsidianNoteSyncRequest) -> ObsidianNoteSyncPrepared:
        vault_path = self.vault_path
        if not vault_path.exists() or not vault_path.is_dir():
            raise BridgeError(
                422,
                "obsidian_vault_not_found",
                "Configured Obsidian vault_path does not exist or is not a directory",
                {"vault_path": str(vault_path)},
            )

        local_index = self._load_index()
        note_entries = local_index.setdefault("notes", {})
        existing = note_entries.get(request.note_key) or {}
        stable_id = existing.get("stable_id") or self._stable_id(request.note_key)
        link_token = existing.get("link_token") or secrets.token_urlsafe(24)
        existing_relative = existing.get("last_known_relative_path")
        target_path, relative_path = self._choose_target_path(
            request.note_key,
            request.note_title,
            existing_relative,
        )
        ensure_dir(target_path.parent)
        resolver_url = self._resolver_url(stable_id, link_token)
        frontmatter = {
            "zotero_item_key": request.item_key,
            "zotero_note_key": request.note_key,
            "zab_stable_id": stable_id,
            "zab_resolver": resolver_url,
        }

        note_entries[request.note_key] = {
            **existing,
            "item_key": request.item_key,
            "note_key": request.note_key,
            "note_title": request.note_title,
            "stable_id": stable_id,
            "link_token": link_token,
            "vault_name": self.vault_name,
            "last_known_relative_path": relative_path,
            "markdown_path": str(target_path),
            "resolver_url": resolver_url,
            "updated_at": now_iso(),
        }
        self._save_index(local_index)
        self._upsert_note_record(
            request.note_key,
            request.item_key,
            {
                "stable_id": stable_id,
                "vault_name": self.vault_name,
                "last_known_relative_path": relative_path,
                "resolver_url": resolver_url,
                "better_notes_sync_status": existing.get("better_notes_sync_status") or "prepared",
                "last_sync_error": existing.get("last_sync_error"),
            },
        )

        return ObsidianNoteSyncPrepared(
            item_key=request.item_key,
            note_key=request.note_key,
            note_title=request.note_title,
            stable_id=stable_id,
            link_token=link_token,
            markdown_path=str(target_path),
            vault_relative_path=relative_path,
            sync_dir=str(target_path.parent),
            filename=target_path.name,
            vault_name=self.vault_name,
            resolver_url=resolver_url,
            frontmatter=frontmatter,
        )

    def update_sync_status(self, note_key: str, request: ObsidianSyncStatusRequest) -> dict[str, Any]:
        local_index = self._load_index()
        note_entries = local_index.setdefault("notes", {})
        existing = note_entries.get(note_key) or {}
        markdown_path = request.markdown_path or existing.get("markdown_path")
        relative_path = request.vault_relative_path or existing.get("last_known_relative_path")
        if request.vault_relative_path:
            relative_path = self._relative_to_vault(self.vault_path / request.vault_relative_path)
        elif markdown_path:
            relative_path = self._relative_to_vault(Path(markdown_path))
        elif relative_path:
            relative_path = self._relative_to_vault(self.vault_path / relative_path)
        existing.update(
            {
                "item_key": request.item_key,
                "note_key": note_key,
                "stable_id": request.stable_id,
                "better_notes_sync_status": request.status,
                "last_sync_error": request.error,
                "updated_at": now_iso(),
            }
        )
        if relative_path:
            existing["last_known_relative_path"] = relative_path
            existing["markdown_path"] = str((self.vault_path / relative_path).resolve())
        note_entries[note_key] = existing
        self._save_index(local_index)
        self._upsert_note_record(
            note_key,
            request.item_key,
            {
                "stable_id": request.stable_id,
                "vault_name": self.vault_name,
                "last_known_relative_path": relative_path,
                "resolver_url": existing.get("resolver_url"),
                "better_notes_sync_status": request.status,
                "last_sync_error": request.error,
            },
        )
        return {"ok": True, "note_key": note_key, "status": request.status}

    def _scan_vault(self, *, limit: int) -> dict[str, dict[str, Any]]:
        found: dict[str, dict[str, Any]] = {}
        count = 0
        for path in self.vault_path.rglob("*.md"):
            if count >= limit:
                break
            count += 1
            try:
                frontmatter = parse_simple_frontmatter(path.read_text(encoding="utf-8"))
            except UnicodeDecodeError:
                continue
            stable_id = frontmatter.get("zab_stable_id")
            note_key = frontmatter.get("zotero_note_key")
            item_key = frontmatter.get("zotero_item_key")
            if not stable_id:
                continue
            found[stable_id] = {
                "stable_id": stable_id,
                "note_key": note_key,
                "item_key": item_key,
                "last_known_relative_path": self._relative_to_vault(path),
                "markdown_path": str(path.resolve()),
            }
        return found

    def reindex(self, request: ObsidianReindexRequest) -> dict[str, Any]:
        found = self._scan_vault(limit=request.limit)
        local_index = self._load_index()
        note_entries = local_index.setdefault("notes", {})
        updated = 0
        for payload in found.values():
            note_key = payload.get("note_key")
            if not note_key:
                continue
            existing = note_entries.get(note_key) or {}
            existing.update(payload)
            existing["vault_name"] = self.vault_name
            existing["updated_at"] = now_iso()
            note_entries[note_key] = existing
            if payload.get("item_key"):
                self._upsert_note_record(
                    note_key,
                    payload["item_key"],
                    {
                        "stable_id": payload["stable_id"],
                        "vault_name": self.vault_name,
                        "last_known_relative_path": payload["last_known_relative_path"],
                        "resolver_url": existing.get("resolver_url"),
                        "better_notes_sync_status": existing.get("better_notes_sync_status") or "indexed",
                        "last_sync_error": existing.get("last_sync_error"),
                    },
                )
            updated += 1
        self._save_index(local_index)
        return {"indexed": updated, "stable_ids": sorted(found)}

    def _find_by_stable_id(self, stable_id: str, *, token: str) -> dict[str, Any]:
        local_index = self._load_index()
        for note_key, payload in local_index.get("notes", {}).items():
            if payload.get("stable_id") == stable_id:
                if payload.get("link_token") != token:
                    raise BridgeError(401, "invalid_obsidian_link_token", "Invalid Obsidian resolver token")
                relative_path = payload.get("last_known_relative_path")
                if relative_path and (self.vault_path / relative_path).exists():
                    return payload
                found = self._scan_vault(limit=5000).get(stable_id)
                if found:
                    payload.update(found)
                    local_index["notes"][note_key] = payload
                    self._save_index(local_index)
                    return payload
                raise BridgeError(
                    404,
                    "obsidian_note_not_found",
                    "Obsidian markdown file was not found. It may have been deleted or its zab_stable_id frontmatter was removed.",
                    {"stable_id": stable_id},
                )
        raise BridgeError(404, "obsidian_note_not_indexed", "Obsidian note stable_id is not indexed", {"stable_id": stable_id})

    def open_uri(self, stable_id: str, token: str) -> str:
        payload = self._find_by_stable_id(stable_id, token=token)
        relative_path = payload.get("last_known_relative_path")
        if not relative_path:
            raise BridgeError(404, "obsidian_note_path_missing", "Obsidian note path is missing", {"stable_id": stable_id})
        return self._obsidian_uri(relative_path)
