from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .session_transcript import AssistantExchange
from .utils import atomic_write_json, ensure_dir, now_iso

KNOWLEDGE_SCHEMA_VERSION = 2
EXTRACTOR_REVISION = "knowledge-extractor-v1"
ORGANIZER_REVISION = "knowledge-organizer-v1"
RENDERER_REVISION = "knowledge-renderer-v2"

KnowledgeKind = Literal[
    "concept",
    "conclusion",
    "derivation",
    "method",
    "example",
    "limitation",
    "pitfall",
    "open_question",
]
KnowledgeStatus = Literal["active", "superseded", "disputed", "source_missing", "withdrawn_branch"]
RelationKind = Literal[
    "prerequisite",
    "derives",
    "extends",
    "contrasts",
    "corrects",
    "exemplifies",
    "condition",
    "limits",
]
SourceStatus = Literal["available", "missing", "corrupt"]
UpdateMode = Literal["initial_build", "incremental", "up_to_date", "migration", "full_rebuild"]

ALLOWED_SECTION_TITLES = (
    "学习地图",
    "核心概念",
    "推导与知识联系",
    "方法与实践步骤",
    "例子与应用",
    "边界、反例与易错点",
    "认知演进",
    "尚未解决的问题",
    "待整理知识",
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EvidenceDraft(StrictModel):
    source_exchange_id: str = Field(min_length=1, max_length=128)
    kind: KnowledgeKind
    title: str = Field(min_length=1, max_length=160)
    content: str = Field(min_length=1, max_length=100_000)
    formulas: list[str] = Field(default_factory=list, max_length=100)
    steps: list[str] = Field(default_factory=list, max_length=200)
    examples: list[str] = Field(default_factory=list, max_length=100)
    conditions: list[str] = Field(default_factory=list, max_length=100)
    limitations: list[str] = Field(default_factory=list, max_length=100)
    open_questions: list[str] = Field(default_factory=list, max_length=100)

    @field_validator("title", "content")
    @classmethod
    def _strip_required(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value must not be empty")
        return value

    @field_validator("formulas", "steps", "examples", "conditions", "limitations", "open_questions")
    @classmethod
    def _strip_lists(cls, values: list[str]) -> list[str]:
        result: list[str] = []
        for value in values:
            text = str(value).strip()
            if text and text not in result:
                result.append(text)
        return result


class ExtractionEnvelope(StrictModel):
    evidence: list[EvidenceDraft] = Field(default_factory=list, max_length=2000)
    no_knowledge_exchange_ids: list[str] = Field(default_factory=list, max_length=2000)


class RelationDraft(StrictModel):
    from_unit_id: str = Field(min_length=1, max_length=128)
    to_unit_id: str = Field(min_length=1, max_length=128)
    relation: RelationKind
    rationale: str = Field(min_length=1, max_length=20_000)
    source_exchange_ids: list[str] = Field(default_factory=list, max_length=500)


class SectionDraft(StrictModel):
    title: str = Field(min_length=1, max_length=80)
    unit_ids: list[str] = Field(default_factory=list, max_length=5000)

    @field_validator("title")
    @classmethod
    def _known_section(cls, value: str) -> str:
        value = value.strip()
        if value not in ALLOWED_SECTION_TITLES:
            raise ValueError(f"unsupported section title: {value}")
        return value


class MergeDraft(StrictModel):
    unit_ids: list[str] = Field(min_length=2, max_length=100)


class OrganizationEnvelope(StrictModel):
    merge_groups: list[MergeDraft] = Field(default_factory=list, max_length=1000)
    sections: list[SectionDraft] = Field(default_factory=list, max_length=100)
    relations: list[RelationDraft] = Field(default_factory=list, max_length=10_000)


class SessionKnowledgeState(StrictModel):
    source_id: str
    session_file: str
    document_id: str | None = None
    started_at: str | None = None
    updated_at: str | None = None
    status: SourceStatus = "available"
    branch_digest: str = ""
    exchange_digests: list[str] = Field(default_factory=list)
    last_seen_at: str | None = None
    warning: str | None = None


class ExchangeKnowledgeState(StrictModel):
    digest: str
    exchange_id: str
    question: str | None = None
    answer: str
    image_count: int = 0
    timestamp: str | None = None
    source_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    no_knowledge: bool = False


class KnowledgeEvidence(StrictModel):
    evidence_id: str
    source_exchange_digest: str
    kind: KnowledgeKind
    title: str
    content: str
    formulas: list[str] = Field(default_factory=list)
    steps: list[str] = Field(default_factory=list)
    examples: list[str] = Field(default_factory=list)
    conditions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    created_at: str


class KnowledgeUnit(StrictModel):
    unit_id: str
    kind: KnowledgeKind
    title: str
    content: str
    formulas: list[str] = Field(default_factory=list)
    steps: list[str] = Field(default_factory=list)
    examples: list[str] = Field(default_factory=list)
    conditions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    source_exchange_digests: list[str] = Field(default_factory=list)
    status: KnowledgeStatus = "active"


class KnowledgeRelation(StrictModel):
    relation_id: str
    from_unit_id: str
    to_unit_id: str
    relation: RelationKind
    rationale: str
    source_exchange_ids: list[str] = Field(default_factory=list)


class KnowledgeSection(StrictModel):
    title: str
    unit_ids: list[str] = Field(default_factory=list)


class ExperienceKnowledgeState(StrictModel):
    schema_version: Literal[2] = KNOWLEDGE_SCHEMA_VERSION
    scope_key: str
    library_id: int | str
    item_key: str
    note_key: str | None = None
    extractor_revision: str = EXTRACTOR_REVISION
    organizer_revision: str = ORGANIZER_REVISION
    renderer_revision: str = RENDERER_REVISION
    sessions: dict[str, SessionKnowledgeState] = Field(default_factory=dict)
    exchanges: dict[str, ExchangeKnowledgeState] = Field(default_factory=dict)
    evidence: dict[str, KnowledgeEvidence] = Field(default_factory=dict)
    units: dict[str, KnowledgeUnit] = Field(default_factory=dict)
    unit_aliases: dict[str, str] = Field(default_factory=dict)
    relations: list[KnowledgeRelation] = Field(default_factory=list)
    sections: list[KnowledgeSection] = Field(default_factory=list)
    final_markdown: str | None = None
    final_digest: str | None = None
    projection_input_digest: str | None = None
    generated_at: str | None = None


@dataclass(frozen=True, slots=True)
class KnowledgeLoadResult:
    state: ExperienceKnowledgeState | None
    warnings: tuple[str, ...] = ()


class ExperienceKnowledgeStore:
    def __init__(self, root: Path) -> None:
        self.root = ensure_dir(root)
        self._lock = threading.RLock()

    @staticmethod
    def scope_handle(scope_key: str) -> str:
        return hashlib.sha256(scope_key.encode("utf-8")).hexdigest()[:32]

    def path_for(self, scope_key: str) -> Path:
        return self.root / f"{self.scope_handle(scope_key)}.json"

    def checkpoint_path_for(self, scope_key: str) -> Path:
        return self.root / f"{self.scope_handle(scope_key)}.pending.json"

    def _load_path(self, path: Path, scope_key: str, warning_prefix: str) -> KnowledgeLoadResult:
        if not path.is_file():
            return KnowledgeLoadResult(None)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            state = ExperienceKnowledgeState.model_validate(payload)
            if state.scope_key != scope_key:
                raise ValueError("knowledge scope mismatch")
            return KnowledgeLoadResult(state)
        except (OSError, ValueError, json.JSONDecodeError, ValidationError) as exc:
            suffix = f".corrupt-{int(time.time())}"
            quarantine = path.with_name(path.name + suffix)
            try:
                os.replace(path, quarantine)
            except OSError:
                pass
            return KnowledgeLoadResult(None, (f"{warning_prefix}:{type(exc).__name__}",))

    def load(self, scope_key: str) -> KnowledgeLoadResult:
        with self._lock:
            return self._load_path(self.path_for(scope_key), scope_key, "knowledge_store_corrupt")

    def load_checkpoint(self, scope_key: str) -> KnowledgeLoadResult:
        with self._lock:
            return self._load_path(
                self.checkpoint_path_for(scope_key),
                scope_key,
                "knowledge_checkpoint_corrupt",
            )

    def save(self, state: ExperienceKnowledgeState) -> None:
        with self._lock:
            atomic_write_json(self.path_for(state.scope_key), state.model_dump(mode="json"))

    def save_checkpoint(self, state: ExperienceKnowledgeState) -> None:
        with self._lock:
            atomic_write_json(self.checkpoint_path_for(state.scope_key), state.model_dump(mode="json"))

    def clear_checkpoint(self, scope_key: str) -> None:
        with self._lock:
            try:
                self.checkpoint_path_for(scope_key).unlink()
            except FileNotFoundError:
                pass


_JSON_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL | re.IGNORECASE)


def parse_json_object(value: str) -> dict[str, Any]:
    text = value.strip()
    fence = _JSON_FENCE_RE.match(text)
    if fence:
        text = fence.group(1).strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise
        payload = json.loads(text[start:end + 1])
    if not isinstance(payload, dict):
        raise ValueError("structured Pi output must be a JSON object")
    return payload


def normalize_knowledge_text(value: str | None) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    return "\n".join(line.rstrip() for line in text.splitlines())


def exchange_content_digest(exchange: AssistantExchange) -> str:
    payload = {
        "question": normalize_knowledge_text(exchange.question),
        "answer": normalize_knowledge_text(exchange.answer),
        "image_count": int(exchange.image_count),
        "image_digest": exchange.image_digest or "",
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def branch_digest(exchange_digests: list[str]) -> str:
    return hashlib.sha256("\n".join(exchange_digests).encode("utf-8")).hexdigest()


def source_identity(source: dict[str, Any]) -> str:
    provided = str(source.get("session_id") or "").strip().lower()
    if provided:
        return provided
    path = str(source.get("session_file") or "").strip()
    canonical = os.path.normcase(str(Path(path).expanduser().resolve())) if path else "missing"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def evidence_id(exchange_digest: str, draft: EvidenceDraft) -> str:
    payload = "\0".join(
        [exchange_digest, draft.kind, normalize_knowledge_text(draft.title), normalize_knowledge_text(draft.content)]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def unit_key(evidence: KnowledgeEvidence) -> str:
    payload = "\0".join(
        [evidence.kind, normalize_knowledge_text(evidence.title).casefold(), normalize_knowledge_text(evidence.content).casefold()]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def build_units(evidence_map: dict[str, KnowledgeEvidence], active_exchange_digests: set[str]) -> dict[str, KnowledgeUnit]:
    units: dict[str, KnowledgeUnit] = {}
    for evidence in evidence_map.values():
        if evidence.source_exchange_digest not in active_exchange_digests:
            continue
        key = unit_key(evidence)
        unit = units.get(key)
        if unit is None:
            units[key] = KnowledgeUnit(
                unit_id=key,
                kind=evidence.kind,
                title=evidence.title,
                content=evidence.content,
                formulas=list(evidence.formulas),
                steps=list(evidence.steps),
                examples=list(evidence.examples),
                conditions=list(evidence.conditions),
                limitations=list(evidence.limitations),
                open_questions=list(evidence.open_questions),
                evidence_ids=[evidence.evidence_id],
                source_exchange_digests=[evidence.source_exchange_digest],
            )
            continue
        if evidence.evidence_id not in unit.evidence_ids:
            unit.evidence_ids.append(evidence.evidence_id)
        if evidence.source_exchange_digest not in unit.source_exchange_digests:
            unit.source_exchange_digests.append(evidence.source_exchange_digest)
        for field_name in ("formulas", "steps", "examples", "conditions", "limitations", "open_questions"):
            target = getattr(unit, field_name)
            for value in getattr(evidence, field_name):
                if value not in target:
                    target.append(value)
    return units


def default_section_for(kind: KnowledgeKind) -> str:
    return {
        "concept": "核心概念",
        "conclusion": "核心概念",
        "derivation": "推导与知识联系",
        "method": "方法与实践步骤",
        "example": "例子与应用",
        "limitation": "边界、反例与易错点",
        "pitfall": "边界、反例与易错点",
        "open_question": "尚未解决的问题",
    }[kind]


def deterministic_sections(units: dict[str, KnowledgeUnit]) -> list[KnowledgeSection]:
    grouped: dict[str, list[str]] = {title: [] for title in ALLOWED_SECTION_TITLES}
    for unit in units.values():
        grouped[default_section_for(unit.kind)].append(unit.unit_id)
    return [KnowledgeSection(title=title, unit_ids=grouped[title]) for title in ALLOWED_SECTION_TITLES if grouped[title]]


def relation_id(draft: RelationDraft) -> str:
    payload = f"{draft.from_unit_id}\0{draft.to_unit_id}\0{draft.relation}\0{draft.rationale}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def markdown_digest(markdown: str) -> str:
    return hashlib.sha256(markdown.encode("utf-8")).hexdigest()


def new_state(scope_key: str, library_id: int | str, item_key: str) -> ExperienceKnowledgeState:
    return ExperienceKnowledgeState(scope_key=scope_key, library_id=library_id, item_key=item_key, generated_at=now_iso())
