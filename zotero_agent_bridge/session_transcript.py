from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

CONTEXT_BEGIN = "<!-- ZAB_SYSTEM_LITERATURE_CONTEXT_V1_BEGIN -->"
CONTEXT_END = "<!-- ZAB_SYSTEM_LITERATURE_CONTEXT_V1_END -->"
QUESTION_BEGIN = "<!-- ZAB_USER_QUESTION_V1_BEGIN -->"
QUESTION_END = "<!-- ZAB_USER_QUESTION_V1_END -->"
CONTEXT_LOADED_MESSAGE = "[Literature context loaded]"


@dataclass(frozen=True, slots=True)
class AssistantExchange:
    question: str | None
    answer: str
    exchange_id: str
    image_count: int = 0
    timestamp: str | None = None
    image_digest: str | None = None


@dataclass(slots=True)
class SessionTranscript:
    session_file: str
    exchanges: list[AssistantExchange] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    started_at: str | None = None
    session_id: str | None = None
    branch_digest: str | None = None


def content_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    return "\n".join(str(block.get("text")) for block in content if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str)).strip()


def image_count(content: Any) -> int:
    return sum(1 for block in content if isinstance(block, dict) and block.get("type") == "image") if isinstance(content, list) else 0


def image_content_digest(content: Any) -> str | None:
    if not isinstance(content, list):
        return None
    images: list[dict[str, str]] = []
    for block in content:
        if not isinstance(block, dict) or block.get("type") != "image":
            continue
        images.append({
            "mimeType": str(block.get("mimeType") or block.get("mime_type") or ""),
            "data_sha256": hashlib.sha256(str(block.get("data") or "").encode("utf-8")).hexdigest(),
            "path": str(block.get("path") or block.get("url") or ""),
        })
    if not images:
        return None
    encoded = json.dumps(images, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def project_bootstrap_text(value: str) -> str | None:
    if CONTEXT_BEGIN not in value or CONTEXT_END not in value:
        return None
    if QUESTION_BEGIN not in value or QUESTION_END not in value:
        return CONTEXT_LOADED_MESSAGE
    question = value.rsplit(QUESTION_BEGIN, 1)[1].split(QUESTION_END, 1)[0].strip()
    return question or CONTEXT_LOADED_MESSAGE


def project_question(message: dict[str, Any]) -> tuple[str | None, int]:
    content = message.get("content")
    text = content_text(content)
    question = project_bootstrap_text(text)
    question = question if question is not None else text
    count = image_count(content)
    if not question and count:
        question = f"图片提问（附图 {count} 张）"
    return question or None, count


def finalized_pairs_from_messages(response: dict[str, Any]) -> list[tuple[str | None, str]]:
    messages = ((response.get("data") or {}).get("messages"))
    if not isinstance(messages, list):
        return []
    pairs: list[tuple[str | None, str]] = []
    question: str | None = None
    for message in messages:
        if not isinstance(message, dict):
            continue
        if message.get("role") == "user":
            question, _ = project_question(message)
            continue
        answer = content_text(message.get("content"))
        if message.get("role") == "assistant" and answer and message.get("stopReason") == "stop":
            pairs.append((question, answer))
            question = None
    return pairs


def read_session_transcript(path_value: str | Path, *, max_bytes: int = 128 * 1024 * 1024) -> SessionTranscript:
    path = Path(path_value).expanduser().resolve()
    result = SessionTranscript(session_file=str(path))
    try:
        if not path.is_file():
            result.warnings.append("session_file_missing")
            return result
        if path.stat().st_size > max_bytes:
            result.warnings.append("session_file_too_large")
            return result
    except OSError:
        result.warnings.append("session_file_unreadable")
        return result
    entries: list[dict[str, Any]] = []
    malformed = 0
    try:
        for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not raw.strip():
                continue
            try:
                entry = json.loads(raw)
            except json.JSONDecodeError:
                malformed += 1
                continue
            if not isinstance(entry, dict):
                continue
            if entry.get("type") in {"session", "session_info"}:
                if result.started_at is None:
                    result.started_at = str(entry.get("timestamp") or entry.get("started_at") or "") or None
                if result.session_id is None:
                    result.session_id = str(entry.get("sessionId") or entry.get("session_id") or entry.get("id") or "") or None
            if isinstance(entry.get("id"), str):
                entries.append(entry)
    except OSError:
        result.warnings.append("session_file_unreadable")
        return result
    if malformed:
        result.warnings.append(f"malformed_lines:{malformed}")
    if not entries:
        result.warnings.append("session_has_no_entries")
        return result
    by_id = {entry["id"]: entry for entry in entries}
    leaf = entries[-1]["id"]
    branch: list[dict[str, Any]] = []
    seen: set[str] = set()
    while leaf and leaf not in seen:
        seen.add(leaf)
        entry = by_id.get(leaf)
        if entry is None:
            result.warnings.append("broken_parent_chain")
            break
        branch.append(entry)
        parent = entry.get("parentId")
        leaf = parent if isinstance(parent, str) else ""
    branch.reverse()
    pending: tuple[str | None, int, str, str | None, str | None] | None = None
    for entry in branch:
        if entry.get("type") != "message" or not isinstance(entry.get("message"), dict):
            continue
        message = entry["message"]
        if message.get("role") == "user":
            question, count = project_question(message)
            pending = (
                question,
                count,
                str(entry.get("id") or ""),
                str(entry.get("timestamp") or "") or None,
                image_content_digest(message.get("content")),
            )
            continue
        answer = content_text(message.get("content"))
        if message.get("role") != "assistant" or not answer or message.get("stopReason") != "stop" or pending is None:
            continue
        question, count, user_id, timestamp, image_digest = pending
        assistant_id = str(entry.get("id") or "")
        stable = f"{user_id}\0{assistant_id}" if user_id and assistant_id else f"{question or ''}\0{answer}"
        result.exchanges.append(
            AssistantExchange(
                question=question,
                answer=answer,
                exchange_id=hashlib.sha256(stable.encode()).hexdigest(),
                image_count=count,
                timestamp=timestamp,
                image_digest=image_digest,
            )
        )
        pending = None
    result.branch_digest = hashlib.sha256(
        "\n".join(exchange.exchange_id for exchange in result.exchanges).encode("utf-8")
    ).hexdigest()
    if result.session_id is None:
        result.session_id = hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:16]
    return result


def deduplicate_exchanges(transcripts: list[SessionTranscript]) -> list[AssistantExchange]:
    seen_ids: set[str] = set()
    seen_content: set[str] = set()
    result: list[AssistantExchange] = []
    for transcript in transcripts:
        for exchange in transcript.exchanges:
            content_hash = hashlib.sha256(f"{exchange.question or ''}\0{exchange.answer}".encode()).hexdigest()
            if exchange.exchange_id in seen_ids or content_hash in seen_content:
                continue
            seen_ids.add(exchange.exchange_id)
            seen_content.add(content_hash)
            result.append(exchange)
    return result
