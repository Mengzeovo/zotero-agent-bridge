from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator


class TagModel(BaseModel):
    tag: str
    type: int = 0


class CreatorModel(BaseModel):
    creatorType: str = "author"
    firstName: str | None = None
    lastName: str | None = None
    name: str | None = None


class ManualFields(BaseModel):
    item_type: str = "journalArticle"
    fields: dict[str, Any] = Field(default_factory=dict)
    creators: list[CreatorModel] = Field(default_factory=list)
    tags: list[str | TagModel] = Field(default_factory=list)
    collections: list[str] = Field(default_factory=list)


class CreateItemRequest(BaseModel):
    doi: str | None = None
    pdf_path: str | None = None
    manual_fields: ManualFields | None = None
    tags: list[str | TagModel] = Field(default_factory=list)
    collections: list[str] = Field(default_factory=list)
    dedupe: bool = True

    @model_validator(mode="after")
    def validate_input(self) -> "CreateItemRequest":
        if not any([self.doi, self.pdf_path, self.manual_fields]):
            raise ValueError("At least one of doi, pdf_path, or manual_fields is required")
        return self


class UpdateItemRequest(BaseModel):
    version: int
    fields: dict[str, Any] = Field(default_factory=dict)
    creators: list[CreatorModel] | None = None
    tags: list[str | TagModel] | None = None
    collections: list[str] | None = None


class CollectionRecord(BaseModel):
    library_id: int
    collection_key: str
    version: int
    name: str
    parent_key: str | None = None


class CreateCollectionRequest(BaseModel):
    name: str = Field(min_length=1)
    parent_key: str | None = None
    library_id: int | None = None


class UpdateCollectionRequest(BaseModel):
    version: int
    name: str | None = None
    parent_key: str | None = None
    move_to_root: bool = False

    @model_validator(mode="after")
    def validate_update(self) -> "UpdateCollectionRequest":
        if self.name is None and self.parent_key is None and not self.move_to_root:
            raise ValueError("At least one of name, parent_key, or move_to_root is required")
        return self


class AttachLinkedPdfRequest(BaseModel):
    pdf_path: str
    title: str | None = None
    content_type: str | None = None


class CreateNoteRequest(BaseModel):
    markdown: str
    title: str | None = None

    @model_validator(mode="after")
    def validate_note(self) -> "CreateNoteRequest":
        if not self.markdown.strip():
            raise ValueError("markdown cannot be empty")
        return self


class SyncExportRequest(BaseModel):
    item_key: str | None = None
    limit: int = 200
    start: int = 0
    include_notes: bool = True


class StableWriteResponse(BaseModel):
    library_id: int | None = None
    item_key: str | None = None
    attachment_key: str | None = None
    note_key: str | None = None
    mirror_ref: str | None = None
    sync_status: str
    version: int | None = None
    title: str | None = None

