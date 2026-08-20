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


class AssistantSessionOpenRequest(BaseModel):
    item_key: str = Field(min_length=1)
    attachment_key: str | None = None


class AssistantMessageRequest(BaseModel):
    message: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_message(self) -> "AssistantMessageRequest":
        if not self.message.strip():
            raise ValueError("message cannot be empty")
        return self


class AssistantModelSelectRequest(BaseModel):
    provider: str = Field(min_length=1, max_length=100)
    model_id: str = Field(min_length=1, max_length=300)

    @model_validator(mode="after")
    def validate_model(self) -> "AssistantModelSelectRequest":
        self.provider = self.provider.strip()
        self.model_id = self.model_id.strip()
        if not self.provider or not self.model_id:
            raise ValueError("provider and model_id cannot be empty")
        return self


PI_THINKING_LEVELS = frozenset({"off", "minimal", "low", "medium", "high", "xhigh", "max"})


class AssistantThinkingLevelRequest(BaseModel):
    level: str = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def validate_level(self) -> "AssistantThinkingLevelRequest":
        self.level = self.level.strip().lower()
        if self.level not in PI_THINKING_LEVELS:
            raise ValueError("unsupported thinking level")
        return self


class AssistantSaveNoteRequest(BaseModel):
    item_key: str = Field(min_length=1, max_length=64)
    attachment_key: str = Field(min_length=1, max_length=64)
    context_fingerprint: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    document_id: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    answer: str = Field(min_length=1, max_length=200_000)
    question: str | None = Field(default=None, max_length=50_000)
    title: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def validate_content(self) -> "AssistantSaveNoteRequest":
        if not self.answer.strip():
            raise ValueError("answer cannot be empty")
        if self.question is not None and not self.question.strip():
            self.question = None
        if self.title is not None and not self.title.strip():
            self.title = None
        return self


class AssistantContextMetadata(BaseModel):
    library_id: int | str
    item_key: str
    attachment_key: str
    pdf_path: str
    cwd: str
    page_count: int
    char_count: int
    fingerprint: str
    warnings: list[str] = Field(default_factory=list)
    title: str | None = None


class AssistantSessionOpenResponse(BaseModel):
    session: dict[str, Any]
    context: AssistantContextMetadata
    context_injection_required: bool
    context_updated: bool = False
    poll_interval_ms: int


class AssistantEventsResponse(BaseModel):
    events: list[dict[str, Any]] = Field(default_factory=list)
    last_cursor: int
    cursor_expired: bool = False
    generation: int | None = None
    item_key: str | None = None
    document_id: str | None = None
    poll_interval_ms: int


class SyncExportRequest(BaseModel):
    item_key: str | None = None
    limit: int = 200
    start: int = 0
    include_notes: bool = True


class PrepareObsidianNoteSyncRequest(BaseModel):
    item_key: str
    note_key: str
    note_title: str


class ObsidianSyncStatusRequest(BaseModel):
    item_key: str
    stable_id: str
    status: str
    markdown_path: str | None = None
    vault_relative_path: str | None = None
    error: str | None = None


class ObsidianReindexRequest(BaseModel):
    limit: int = 5000


class ObsidianNoteSyncPrepared(BaseModel):
    item_key: str
    note_key: str
    note_title: str
    stable_id: str
    link_token: str
    markdown_path: str
    vault_relative_path: str
    sync_dir: str
    filename: str
    vault_name: str
    resolver_url: str
    frontmatter: dict[str, Any]


class StableWriteResponse(BaseModel):
    library_id: int | None = None
    item_key: str | None = None
    attachment_key: str | None = None
    note_key: str | None = None
    mirror_ref: str | None = None
    sync_status: str
    version: int | None = None
    title: str | None = None


class AssistantSaveNoteResponse(StableWriteResponse):
    pass

