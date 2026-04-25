from __future__ import annotations

from pathlib import Path
from typing import Any

import markdown as markdown_lib
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import JSONResponse, RedirectResponse

from .addon_client import AddonClient
from .config import Settings
from .doi import fetch_doi_metadata
from .errors import BridgeError
from .mirror import MirrorStore
from .models import (
    AttachLinkedPdfRequest,
    CollectionRecord,
    CreateCollectionRequest,
    CreateItemRequest,
    CreateNoteRequest,
    ObsidianNoteSyncPrepared,
    ObsidianReindexRequest,
    ObsidianSyncStatusRequest,
    PrepareObsidianNoteSyncRequest,
    StableWriteResponse,
    SyncExportRequest,
    UpdateCollectionRequest,
    UpdateItemRequest,
)
from .obsidian import ObsidianBridge
from .pdf_tools import extract_pdf_metadata
from .utils import guess_content_type, normalize_doi, now_iso, sha256_file
from .write_queue import SerialWriteExecutor
from .zotero_local import ZoteroLocalClient


class BridgeService:
    def __init__(
        self,
        settings: Settings,
        *,
        local_client: ZoteroLocalClient | None = None,
        mirror: MirrorStore | None = None,
        writer: SerialWriteExecutor | None = None,
        doi_resolver=fetch_doi_metadata,
        pdf_metadata_extractor=extract_pdf_metadata,
    ) -> None:
        self.settings = settings
        self.local_client = local_client or ZoteroLocalClient(
            settings.zotero_local_api_base,
            settings.user_agent,
            base_attachment_path=str(settings.base_attachment_path) if settings.base_attachment_path else None,
        )
        self.mirror = mirror or MirrorStore(settings.metadata_dir, settings.notes_dir)
        self.writer = writer or SerialWriteExecutor(
            AddonClient(
                commands_dir=settings.commands_dir,
                responses_dir=settings.responses_dir,
                archive_dir=settings.archive_dir,
                status_path=settings.addon_status_path,
                timeout_seconds=settings.addon_timeout_seconds,
                status_ttl_seconds=settings.addon_status_ttl_seconds,
            ),
            settings.operations_log_path,
        )
        self.doi_resolver = doi_resolver
        self.pdf_metadata_extractor = pdf_metadata_extractor
        self.obsidian = ObsidianBridge(settings, self.mirror)

    def health(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "time": now_iso(),
            "zotero_local_api": {
                "available": self.local_client.is_available(),
                "base_url": self.settings.zotero_local_api_base,
            },
            "addon": self.writer.addon_client.status(),
            "bridge_home": str(self.settings.bridge_home.resolve()),
            "metadata_dir": str(self.settings.metadata_dir.resolve()),
            "notes_dir": str(self.settings.notes_dir.resolve()),
        }

    def capabilities(self) -> dict[str, Any]:
        local_available = self.local_client.is_available()
        addon_ready = self.writer.addon_client.is_ready()
        has_mirror = bool(self.mirror._load_index()["items"])
        return {
            "read": local_available or has_mirror,
            "write": local_available and addon_ready,
            "mcp": True,
            "http": True,
            "linked_pdf_only": True,
            "mirror": {
                "metadata_dir": str(self.settings.metadata_dir.resolve()),
                "notes_dir": str(self.settings.notes_dir.resolve()),
            },
        }

    def list_collections(self) -> list[CollectionRecord]:
        if not self.local_client.is_available():
            raise BridgeError(503, "zotero_unavailable", "Zotero Local API is unavailable")
        collections = sorted(
            self.local_client.list_collections(),
            key=lambda collection: ((collection.get("parent_key") or ""), collection["name"].lower()),
        )
        return [CollectionRecord.model_validate(collection) for collection in collections]

    def get_collection(self, collection_key: str) -> CollectionRecord:
        if not self.local_client.is_available():
            raise BridgeError(503, "zotero_unavailable", "Zotero Local API is unavailable")
        return CollectionRecord.model_validate(self.local_client.get_collection(collection_key))

    def create_collection(self, request: CreateCollectionRequest) -> CollectionRecord:
        payload = request.model_dump(mode="python", exclude_none=True)
        result = self.writer.execute("create_collection", payload)
        self.local_client.invalidate_collection_cache()
        if self.local_client.is_available():
            return CollectionRecord.model_validate(self.local_client.get_collection(result["collection_key"]))
        return CollectionRecord.model_validate(result)

    def update_collection(self, collection_key: str, request: UpdateCollectionRequest) -> CollectionRecord:
        payload = request.model_dump(mode="python", exclude_none=True)
        payload["collection_key"] = collection_key
        result = self.writer.execute("update_collection", payload)
        self.local_client.invalidate_collection_cache()
        if self.local_client.is_available():
            return CollectionRecord.model_validate(self.local_client.get_collection(collection_key))
        return CollectionRecord.model_validate(result)

    def search_items(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        if self.local_client.is_available():
            results = []
            index = self.mirror.index_snapshot()
            for item in self.local_client.search_items(query, limit=limit):
                bundle = self.mirror.apply_index(
                    {
                        "library_id": item["library"]["id"],
                        "item_key": item["key"],
                        "attachment_key": None,
                        "note_key": None,
                        "slug": None,
                        "pdf_path": None,
                        "checksum": None,
                        "version": item["version"],
                        "item_type": item["data"]["itemType"],
                        "title": item["data"].get("title") or "",
                        "doi": item["data"].get("DOI"),
                        "tags": [tag["tag"] for tag in item["data"].get("tags", [])],
                        "collections": [],
                        "attachments": [],
                        "notes": [],
                        "updated_at": item["data"].get("dateModified") or now_iso(),
                        "sync_status": "synced",
                    },
                    index=index,
                )
                results.append(bundle)
            return results
        return self.mirror.search(query, limit)

    def get_item(self, item_key: str) -> dict[str, Any]:
        if self.local_client.is_available():
            return self.mirror.apply_index(self.local_client.build_bundle(item_key))
        bundle = self.mirror.get_bundle(item_key)
        if bundle:
            return bundle
        raise BridgeError(404, "item_not_found", f"Item {item_key} was not found")

    def _validate_pdf(self, pdf_path: str) -> tuple[Path, str]:
        path = Path(pdf_path).expanduser().resolve()
        if not path.exists() or not path.is_file():
            raise BridgeError(422, "invalid_pdf_path", "PDF path does not exist", {"pdf_path": str(path)})
        if path.suffix.lower() != ".pdf":
            raise BridgeError(422, "invalid_pdf_type", "Only PDF files are supported", {"pdf_path": str(path)})
        return path, sha256_file(path)

    def _find_existing_by_doi(self, doi: str | None) -> dict[str, Any] | None:
        if not doi:
            return None
        item = self.local_client.find_by_doi(doi) if self.local_client.is_available() else None
        if item:
            record = self.mirror.get_item_record(item["key"])
            return {
                "library_id": item["library"]["id"],
                "item_key": item["key"],
                "attachment_key": None,
                "note_key": None,
                "mirror_ref": record.get("mirror_ref") if record else None,
                "sync_status": "existing",
            }
        return self.mirror.find_item_by_doi(doi)

    def _normalize_tags(self, tags: list[Any]) -> list[dict[str, Any]]:
        normalized = []
        seen = set()
        for tag in tags:
            if isinstance(tag, str):
                value = {"tag": tag, "type": 0}
            else:
                value = tag.model_dump(mode="python") if hasattr(tag, "model_dump") else dict(tag)
            if value["tag"] in seen:
                continue
            seen.add(value["tag"])
            normalized.append(value)
        return normalized

    def _manual_payload(self, manual_fields) -> dict[str, Any]:
        if not manual_fields:
            return {"item_type": "journalArticle", "fields": {}, "creators": [], "tags": [], "collections": []}
        payload = manual_fields.model_dump(mode="python")
        return {
            "item_type": payload.get("item_type", "journalArticle"),
            "fields": dict(payload.get("fields", {})),
            "creators": payload.get("creators", []),
            "tags": payload.get("tags", []),
            "collections": payload.get("collections", []),
        }

    def _placeholder_payload(self, request: CreateItemRequest, pdf_metadata: dict[str, Any], resolved_doi: str | None) -> dict[str, Any]:
        title = pdf_metadata.get("title") if pdf_metadata else None
        if not title and request.pdf_path:
            title = Path(request.pdf_path).stem.replace("_", " ").replace("-", " ")
        title = title or "Untitled paper"
        fields = {"title": title, "extra": "BridgeStatus: needs_review"}
        if resolved_doi:
            fields["DOI"] = resolved_doi
        return {
            "item_type": "journalArticle",
            "fields": fields,
            "creators": [],
            "tags": [{"tag": "needs_review", "type": 0}],
            "collections": [],
        }

    def _resolve_item_payload(
        self,
        request: CreateItemRequest,
        *,
        resolved_doi: str | None,
        pdf_metadata: dict[str, Any],
    ) -> tuple[dict[str, Any], str]:
        manual_payload = self._manual_payload(request.manual_fields)
        sync_status = "synced"
        base_payload: dict[str, Any] | None = None
        if resolved_doi:
            try:
                base_payload = self.doi_resolver(resolved_doi, self.settings.user_agent)
            except Exception:
                sync_status = "needs_review"
                base_payload = manual_payload if request.manual_fields else self._placeholder_payload(request, pdf_metadata, resolved_doi)
        elif request.manual_fields:
            base_payload = manual_payload
        elif request.pdf_path:
            sync_status = "needs_review"
            base_payload = self._placeholder_payload(request, pdf_metadata, resolved_doi)
        if not base_payload:
            raise BridgeError(422, "insufficient_metadata", "Unable to build item metadata")

        payload = {
            "item_type": manual_payload.get("item_type") or base_payload.get("item_type") or "journalArticle",
            "fields": dict(base_payload.get("fields", {})),
            "creators": list(base_payload.get("creators", [])),
            "tags": list(base_payload.get("tags", [])),
            "collections": list(base_payload.get("collections", [])),
        }
        payload["fields"].update(manual_payload.get("fields", {}))
        if manual_payload.get("creators"):
            payload["creators"] = manual_payload["creators"]
        payload["tags"].extend(manual_payload.get("tags", []))
        payload["tags"].extend(request.tags)
        payload["collections"].extend(manual_payload.get("collections", []))
        payload["collections"].extend(request.collections)
        payload["tags"] = self._normalize_tags(payload["tags"])
        payload["collections"] = list(dict.fromkeys(payload["collections"]))
        if resolved_doi:
            payload["fields"]["DOI"] = resolved_doi
        if sync_status == "needs_review" and "needs_review" not in [tag["tag"] for tag in payload["tags"]]:
            payload["tags"].append({"tag": "needs_review", "type": 0})
        return payload, sync_status

    def _render_note_html(self, markdown_text: str) -> str:
        rendered = markdown_lib.markdown(markdown_text, extensions=["extra", "fenced_code", "tables", "nl2br"])
        return f'<div data-schema-version="9">{rendered}</div>'

    def _build_fallback_bundle(self, result: dict[str, Any], payload: dict[str, Any], sync_status: str) -> dict[str, Any]:
        title = payload["fields"].get("title") or result.get("item_key")
        return {
            "library_id": result.get("library_id"),
            "item_key": result.get("item_key"),
            "attachment_key": None,
            "note_key": None,
            "slug": None,
            "pdf_path": None,
            "checksum": None,
            "version": result.get("version"),
            "item_type": payload.get("item_type", "journalArticle"),
            "title": title,
            "doi": payload["fields"].get("DOI"),
            "url": payload["fields"].get("url"),
            "fields": payload["fields"],
            "creators": payload.get("creators", []),
            "tags": [tag["tag"] for tag in payload.get("tags", [])],
            "collections": [{"key": c, "name": c} for c in payload.get("collections", [])],
            "attachments": [],
            "notes": [],
            "updated_at": now_iso(),
            "sync_status": sync_status,
        }

    def _refresh_bundle(self, item_key: str, fallback: dict[str, Any] | None = None) -> dict[str, Any]:
        if self.local_client.is_available():
            return self.mirror.apply_index(self.local_client.build_bundle(item_key))
        if fallback:
            return self.mirror.apply_index(fallback)
        raise BridgeError(503, "zotero_unavailable", "Zotero Local API is unavailable")

    def create_item(self, request: CreateItemRequest) -> StableWriteResponse:
        resolved_doi = normalize_doi(request.doi)
        pdf_metadata: dict[str, Any] = {}
        pdf_path: Path | None = None
        checksum: str | None = None
        if request.pdf_path:
            pdf_path, checksum = self._validate_pdf(request.pdf_path)
            if request.dedupe:
                existing_attachment = self.mirror.find_attachment_by_checksum(checksum)
                if existing_attachment:
                    raise BridgeError(409, "duplicate_pdf", "PDF already exists in mirror index", existing_attachment)
            pdf_metadata = self.pdf_metadata_extractor(pdf_path)
            if not resolved_doi:
                resolved_doi = normalize_doi(pdf_metadata.get("doi"))
        if request.dedupe:
            existing_item = self._find_existing_by_doi(resolved_doi)
            if existing_item:
                raise BridgeError(409, "duplicate_item", "Item with same DOI already exists", existing_item)
        payload, sync_status = self._resolve_item_payload(request, resolved_doi=resolved_doi, pdf_metadata=pdf_metadata)
        result = self.writer.execute("create_item", payload)
        attachment_result = None
        if pdf_path:
            attachment_result = self._attach_linked_pdf(
                result["item_key"],
                AttachLinkedPdfRequest(pdf_path=str(pdf_path), title=payload["fields"].get("title"), content_type=guess_content_type(pdf_path)),
                checksum=checksum,
                export_after=False,
            )
        bundle = self._refresh_bundle(result["item_key"], self._build_fallback_bundle(result, payload, sync_status))
        bundle["sync_status"] = sync_status
        attachment_checksums = {}
        if attachment_result and checksum:
            attachment_checksums[attachment_result["attachment_key"]] = checksum
        item_record = self.mirror.export_bundle(bundle, attachment_checksums=attachment_checksums)
        return StableWriteResponse(
            library_id=result.get("library_id"),
            item_key=result.get("item_key"),
            attachment_key=attachment_result.get("attachment_key") if attachment_result else None,
            note_key=None,
            mirror_ref=item_record["mirror_ref"],
            sync_status=item_record["sync_status"],
            version=result.get("version"),
            title=bundle.get("title"),
        )

    def update_item(self, item_key: str, request: UpdateItemRequest) -> StableWriteResponse:
        payload = request.model_dump(mode="python", exclude_none=True)
        payload["item_key"] = item_key
        if payload.get("tags") is not None:
            payload["tags"] = self._normalize_tags(payload["tags"])
        result = self.writer.execute("update_item", payload)
        bundle = self._refresh_bundle(item_key)
        item_record = self.mirror.export_bundle(bundle)
        return StableWriteResponse(
            library_id=result.get("library_id"),
            item_key=item_key,
            attachment_key=None,
            note_key=None,
            mirror_ref=item_record["mirror_ref"],
            sync_status=item_record["sync_status"],
            version=result.get("version"),
            title=bundle.get("title"),
        )

    def _attach_linked_pdf(
        self,
        item_key: str,
        request: AttachLinkedPdfRequest,
        *,
        checksum: str | None = None,
        export_after: bool = True,
    ) -> dict[str, Any]:
        pdf_path, computed_checksum = self._validate_pdf(request.pdf_path)
        checksum = checksum or computed_checksum
        existing_attachment = self.mirror.find_attachment_by_checksum(checksum)
        if existing_attachment:
            raise BridgeError(409, "duplicate_pdf", "PDF already exists in mirror index", existing_attachment)
        payload = {
            "item_key": item_key,
            "path": str(pdf_path),
            "title": request.title or pdf_path.name,
            "content_type": request.content_type or guess_content_type(pdf_path),
        }
        result = self.writer.execute("attach_linked_pdf", payload)
        if export_after:
            bundle = self._refresh_bundle(item_key)
            self.mirror.export_bundle(bundle, attachment_checksums={result["attachment_key"]: checksum})
        return result

    def attach_linked_pdf(self, item_key: str, request: AttachLinkedPdfRequest) -> StableWriteResponse:
        result = self._attach_linked_pdf(item_key, request, export_after=True)
        bundle = self._refresh_bundle(item_key)
        item_record = self.mirror.get_item_record(item_key) or self.mirror.export_bundle(bundle)
        return StableWriteResponse(
            library_id=result.get("library_id"),
            item_key=item_key,
            attachment_key=result.get("attachment_key"),
            note_key=None,
            mirror_ref=item_record["mirror_ref"],
            sync_status=item_record["sync_status"],
            version=result.get("version"),
            title=bundle.get("title"),
        )

    def create_note(self, item_key: str, request: CreateNoteRequest) -> StableWriteResponse:
        markdown_text = request.markdown.strip()
        if request.title and not markdown_text.lstrip().startswith("#"):
            markdown_text = f"# {request.title}\n\n{markdown_text}"
        note_html = self._render_note_html(markdown_text)
        result = self.writer.execute("create_note", {"item_key": item_key, "note_html": note_html})
        bundle = self._refresh_bundle(item_key)
        item_record = self.mirror.export_bundle(bundle, note_markdown_overrides={result["note_key"]: markdown_text})
        note_record = self.mirror._load_index()["notes"].get(result["note_key"])
        mirror_ref = note_record["mirror_ref"] if note_record else item_record["mirror_ref"]
        sync_status = note_record["sync_status"] if note_record else item_record["sync_status"]
        return StableWriteResponse(
            library_id=result.get("library_id"),
            item_key=item_key,
            attachment_key=None,
            note_key=result.get("note_key"),
            mirror_ref=mirror_ref,
            sync_status=sync_status,
            version=result.get("version"),
            title=bundle.get("title"),
        )

    def export_items(self, request: SyncExportRequest) -> dict[str, Any]:
        if not self.local_client.is_available():
            raise BridgeError(503, "zotero_unavailable", "Zotero Local API is unavailable")
        if request.item_key:
            bundle = self.local_client.build_bundle(request.item_key)
            record = self.mirror.export_bundle(bundle)
            return {"exported": 1, "item_keys": [request.item_key], "mirror_ref": record["mirror_ref"]}
        exported = []
        start = request.start
        with self.mirror.export_session() as export_bundle:
            while len(exported) < request.limit:
                batch_size = min(max(request.limit - len(exported), 1), 100)
                batch = self.local_client.list_top_level_items(start=start, limit=batch_size)
                if not batch:
                    break
                for item in batch:
                    if item["data"]["itemType"] in {"attachment", "note"}:
                        continue
                    bundle = self.local_client.build_bundle(item["key"])
                    export_bundle(bundle)
                    exported.append(item["key"])
                    if len(exported) >= request.limit:
                        break
                start += len(batch)
                if len(batch) < batch_size:
                    break
        return {"exported": len(exported), "item_keys": exported}

    def prepare_obsidian_note_sync(self, request: PrepareObsidianNoteSyncRequest) -> ObsidianNoteSyncPrepared:
        return self.obsidian.prepare_sync(request)

    def update_obsidian_note_sync_status(self, note_key: str, request: ObsidianSyncStatusRequest) -> dict[str, Any]:
        return self.obsidian.update_sync_status(note_key, request)

    def reindex_obsidian(self, request: ObsidianReindexRequest) -> dict[str, Any]:
        return self.obsidian.reindex(request)

    def obsidian_open_uri(self, stable_id: str, token: str) -> str:
        return self.obsidian.open_uri(stable_id, token)


def build_service(settings: Settings | None = None) -> BridgeService:
    return BridgeService(settings or Settings.from_env())


def create_app(settings: Settings | None = None, service: BridgeService | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    service = service or build_service(settings)
    app = FastAPI(title="Zotero Agent Bridge", version="0.1.0")

    def authorize(
        x_bridge_token: str | None = Header(default=None, alias="X-Bridge-Token"),
        authorization: str | None = Header(default=None, alias="Authorization"),
    ) -> None:
        token = x_bridge_token
        if not token and authorization and authorization.lower().startswith("bearer "):
            token = authorization.split(" ", 1)[1].strip()
        if token != settings.api_token:
            raise HTTPException(status_code=401, detail="Invalid bridge token")

    @app.exception_handler(BridgeError)
    async def bridge_error_handler(_, exc: BridgeError):
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message, "details": exc.details}},
        )

    @app.get("/health", dependencies=[Depends(authorize)])
    def health() -> dict[str, Any]:
        return service.health()

    @app.get("/capabilities", dependencies=[Depends(authorize)])
    def capabilities() -> dict[str, Any]:
        return service.capabilities()

    @app.get("/collections", dependencies=[Depends(authorize)])
    def list_collections() -> list[CollectionRecord]:
        return service.list_collections()

    @app.get("/collections/{collection_key}", dependencies=[Depends(authorize)])
    def get_collection(collection_key: str) -> CollectionRecord:
        return service.get_collection(collection_key)

    @app.post("/collections", dependencies=[Depends(authorize)])
    def create_collection(request: CreateCollectionRequest) -> CollectionRecord:
        return service.create_collection(request)

    @app.patch("/collections/{collection_key}", dependencies=[Depends(authorize)])
    def update_collection(collection_key: str, request: UpdateCollectionRequest) -> CollectionRecord:
        return service.update_collection(collection_key, request)

    @app.get("/items/search", dependencies=[Depends(authorize)])
    def search_items(q: str = Query(..., min_length=1), limit: int = Query(default=20, ge=1, le=100)) -> dict[str, Any]:
        return {"items": service.search_items(q, limit=limit)}

    @app.get("/items/{item_key}", dependencies=[Depends(authorize)])
    def get_item(item_key: str) -> dict[str, Any]:
        return service.get_item(item_key)

    @app.post("/items", dependencies=[Depends(authorize)])
    def create_item(request: CreateItemRequest) -> StableWriteResponse:
        return service.create_item(request)

    @app.patch("/items/{item_key}", dependencies=[Depends(authorize)])
    def update_item(item_key: str, request: UpdateItemRequest) -> StableWriteResponse:
        return service.update_item(item_key, request)

    @app.post("/items/{item_key}/attachments/linked-pdf", dependencies=[Depends(authorize)])
    def attach_linked_pdf(item_key: str, request: AttachLinkedPdfRequest) -> StableWriteResponse:
        return service.attach_linked_pdf(item_key, request)

    @app.post("/items/{item_key}/notes", dependencies=[Depends(authorize)])
    def create_note(item_key: str, request: CreateNoteRequest) -> StableWriteResponse:
        return service.create_note(item_key, request)

    @app.post("/sync/export", dependencies=[Depends(authorize)])
    def export_items(request: SyncExportRequest) -> dict[str, Any]:
        return service.export_items(request)

    @app.post("/obsidian/notes/prepare-sync", dependencies=[Depends(authorize)])
    def prepare_obsidian_note_sync(request: PrepareObsidianNoteSyncRequest) -> ObsidianNoteSyncPrepared:
        return service.prepare_obsidian_note_sync(request)

    @app.post("/obsidian/notes/{note_key}/sync-status", dependencies=[Depends(authorize)])
    def update_obsidian_note_sync_status(note_key: str, request: ObsidianSyncStatusRequest) -> dict[str, Any]:
        return service.update_obsidian_note_sync_status(note_key, request)

    @app.post("/obsidian/reindex", dependencies=[Depends(authorize)])
    def reindex_obsidian(request: ObsidianReindexRequest) -> dict[str, Any]:
        return service.reindex_obsidian(request)

    @app.get("/obsidian/open/{stable_id}")
    def open_obsidian(stable_id: str, token: str = Query(..., min_length=1)) -> RedirectResponse:
        return RedirectResponse(service.obsidian_open_uri(stable_id, token), status_code=302)

    return app



