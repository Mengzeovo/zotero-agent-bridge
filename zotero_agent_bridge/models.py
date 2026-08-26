from __future__ import annotations

import base64
import binascii
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class AssistantSessionOpenRequest(BaseModel):
    item_key: str = Field(min_length=1)
    attachment_key: str | None = None


class AssistantSessionResumeRequest(BaseModel):
    session_id: str = Field(min_length=16, max_length=16, pattern=r"^[a-f0-9]{16}$")


ASSISTANT_IMAGE_MIME_TYPES = frozenset({"image/png", "image/jpeg", "image/webp", "image/gif"})
ASSISTANT_MAX_IMAGES = 4
ASSISTANT_MAX_IMAGE_BYTES = 10 * 1024 * 1024
ASSISTANT_MAX_TOTAL_IMAGE_BYTES = 20 * 1024 * 1024
ASSISTANT_MAX_IMAGE_BASE64_CHARS = ((ASSISTANT_MAX_IMAGE_BYTES + 2) // 3) * 4


class AssistantImageInput(BaseModel):
    type: Literal["image"] = "image"
    data: str = Field(min_length=4, max_length=ASSISTANT_MAX_IMAGE_BASE64_CHARS)
    mimeType: Literal["image/png", "image/jpeg", "image/webp", "image/gif"]

    def decoded_size(self) -> int:
        try:
            return len(base64.b64decode(self.data, validate=True))
        except (binascii.Error, ValueError) as exc:
            raise ValueError("image data must be valid base64") from exc

    @model_validator(mode="after")
    def validate_image(self) -> "AssistantImageInput":
        size = self.decoded_size()
        if size <= 0:
            raise ValueError("image data cannot be empty")
        if size > ASSISTANT_MAX_IMAGE_BYTES:
            raise ValueError("image exceeds the per-image size limit")
        return self


class AssistantMessageRequest(BaseModel):
    message: str = ""
    images: list[AssistantImageInput] = Field(default_factory=list, max_length=ASSISTANT_MAX_IMAGES)

    @model_validator(mode="after")
    def validate_message(self) -> "AssistantMessageRequest":
        self.message = self.message.strip()
        if not self.message and not self.images:
            raise ValueError("message or image is required")
        total_size = sum(image.decoded_size() for image in self.images)
        if total_size > ASSISTANT_MAX_TOTAL_IMAGE_BYTES:
            raise ValueError("images exceed the total size limit")
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


class AssistantSaveNoteResponse(BaseModel):
    library_id: int | None = None
    item_key: str | None = None
    attachment_key: str | None = None
    note_key: str | None = None
    mirror_ref: str | None = None
    sync_status: str
    version: int | None = None
    title: str | None = None
    note_title: str | None = None
    title_source: Literal["ai", "request", "fallback"] | None = None


class AssistantExperienceNoteUpdateRequest(BaseModel):
    item_key: str = Field(min_length=1, max_length=64)
    attachment_key: str = Field(min_length=1, max_length=64)
    context_fingerprint: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    document_id: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    force_rebuild: bool = False


class AssistantExperienceNoteJobAccepted(BaseModel):
    job_id: str
    status: Literal["queued", "collecting", "generating", "writing", "completed", "failed"]
    poll_interval_ms: int = 1000


class AssistantExperienceNoteJobStatus(BaseModel):
    job_id: str
    status: Literal["queued", "collecting", "generating", "writing", "completed", "failed"]
    stage: str | None = None
    session_count: int = 0
    exchange_count: int = 0
    skipped_session_count: int = 0
    new_exchange_count: int = 0
    reused_exchange_count: int = 0
    knowledge_unit_count: int = 0
    new_knowledge_unit_count: int = 0
    updated_knowledge_unit_count: int = 0
    relation_count: int = 0
    missing_source_knowledge_count: int = 0
    ai_call_count: int = 0
    update_mode: Literal["initial_build", "incremental", "up_to_date", "migration", "full_rebuild"] | None = None
    warnings: list[str] = Field(default_factory=list)
    note_key: str | None = None
    created: bool | None = None
    version: int | None = None
    error: dict[str, Any] | None = None
    poll_interval_ms: int = 1000
