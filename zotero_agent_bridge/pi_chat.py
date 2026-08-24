from __future__ import annotations

import hashlib
import json
import os
import platform
import queue
import re
import shutil
import signal
import subprocess
import threading
import time
import uuid
from collections import deque
from pathlib import Path
from typing import Any, Callable, IO

from .config import Settings
from .errors import BridgeError
from .models import PI_THINKING_LEVELS
from .utils import atomic_write_json, ensure_dir, now_iso, read_json


PopenFactory = Callable[..., subprocess.Popen[bytes]]
ZOTERO_ITEM_KEY_RE = re.compile(r"^[A-Z0-9]{8}$")
LIBRARY_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")
CONTEXT_FINGERPRINT_RE = re.compile(r"^[a-f0-9]{64}$")
PROMPT_ACCEPTED_EVENT_TYPES = {"agent_start", "message_start", "message_update", "message_end"}


class PiChatManager:
    """Own one Pi RPC process and persist one Pi session per Zotero document."""

    def __init__(
        self,
        settings: Settings,
        *,
        popen_factory: PopenFactory = subprocess.Popen,
        executable_command: list[str] | None = None,
        max_events: int = 2_000,
        startup_timeout_seconds: float = 15.0,
        request_timeout_seconds: float = 15.0,
        stop_timeout_seconds: float = 3.0,
    ) -> None:
        if not settings.pi:
            raise ValueError("Pi settings are required")
        if not settings.pi.session_dir:
            raise ValueError("Pi session_dir is required")
        if not settings.pi.system_prompt_path:
            raise ValueError("Pi system_prompt_path is required")
        if max_events <= 0:
            raise ValueError("max_events must be positive")

        self.settings = settings
        self.pi = settings.pi
        self.popen_factory = popen_factory
        self.executable_command = list(executable_command) if executable_command else None
        self._preferred_model = self.pi.model.strip() if self.pi.model and self.pi.model.strip() else None
        self._preferred_thinking_level = self.pi.thinking_level
        self.startup_timeout_seconds = startup_timeout_seconds
        self.request_timeout_seconds = request_timeout_seconds
        self.stop_timeout_seconds = stop_timeout_seconds

        self.chat_home = ensure_dir(settings.bridge_home / "pi-chat")
        self.index_path = self.chat_home / "session-index.json"
        ensure_dir(self.pi.session_dir)

        self._lock = threading.RLock()
        self._lifecycle_lock = threading.Lock()
        self._admission_lock = threading.RLock()
        self._stdin_lock = threading.Lock()
        self._pending_lock = threading.Lock()
        self._process: subprocess.Popen[bytes] | None = None
        self._generation = 0
        self._active_generation: int | None = None
        self._stopping_generation: int | None = None
        self._stdout_thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None
        self._pending: dict[str, tuple[int, queue.Queue[dict[str, Any]]]] = {}
        self._events: deque[dict[str, Any]] = deque(maxlen=max_events)
        self._cursor = 0
        self._active_item_key: str | None = None
        self._active_library_id: str | None = None
        self._active_session_identity: str | None = None
        self._active_document_id: str | None = None
        self._active_pdf_path: Path | None = None
        self._active_cwd: Path | None = None
        self._active_session_file: Path | None = None
        self._active_context_fingerprint: str | None = None
        self._inflight_prompt: dict[str, Any] | None = None
        self._streaming = False
        self._last_error: dict[str, Any] | None = None
        self._stderr_tail: deque[str] = deque(maxlen=20)
        self._last_activity = time.monotonic()

    @property
    def active_item_key(self) -> str | None:
        with self._lock:
            return self._active_item_key

    @property
    def is_streaming(self) -> bool:
        with self._lock:
            return self._streaming

    def status(self) -> dict[str, Any]:
        with self._lock:
            process = self._process
            running = bool(process and process.poll() is None)
            return {
                "running": running,
                "streaming": self._streaming,
                "item_key": self._active_item_key,
                "library_id": self._active_library_id,
                "session_identity": self._active_session_identity,
                "document_id": self._active_document_id,
                "pdf_path": str(self._active_pdf_path) if self._active_pdf_path else None,
                "cwd": str(self._active_cwd) if self._active_cwd else None,
                "session_file": str(self._active_session_file) if self._active_session_file else None,
                "context_fingerprint": self._active_context_fingerprint,
                "last_error": self._last_error,
                "last_cursor": self._cursor,
                "generation": self._active_generation,
            }

    def events_after(self, cursor: int = 0) -> dict[str, Any]:
        with self._lock:
            events = [dict(event) for event in self._events if int(event["cursor"]) > cursor]
            oldest = int(self._events[0]["cursor"]) if self._events else self._cursor + 1
            return {
                "events": events,
                "last_cursor": self._cursor,
                "cursor_expired": bool(self._events and cursor < oldest - 1),
                "generation": self._active_generation,
                "item_key": self._active_item_key,
                "document_id": self._active_document_id,
            }

    def clear_events(self) -> None:
        """Discard buffered assistant event payloads without reusing old cursors."""
        with self._lock:
            self._events.clear()

    def open_item(
        self,
        item_key: str,
        pdf_path: str | Path,
        *,
        library_id: str | int | None = None,
    ) -> dict[str, Any]:
        item_key = self._validate_item_key(item_key)
        normalized_library_id = self._normalize_library_id(library_id)
        path = Path(pdf_path).expanduser().resolve()
        if not path.is_file():
            raise BridgeError(422, "invalid_pdf_path", "PDF path does not exist", {"pdf_path": str(path)})
        if path.suffix.lower() != ".pdf":
            raise BridgeError(422, "invalid_pdf_type", "Only PDF files are supported", {"pdf_path": str(path)})
        cwd = path.parent.resolve()
        canonical_pdf_path = os.path.normcase(str(path))
        canonical_cwd = os.path.normcase(str(cwd))
        session_identity = f"{normalized_library_id}:{item_key}" if normalized_library_id else item_key
        document_id = hashlib.sha256(
            f"{session_identity}\0{canonical_pdf_path}".encode("utf-8")
        ).hexdigest()

        with self._lifecycle_lock, self._admission_lock:
            with self._lock:
                changing_document = (
                    session_identity != self._active_session_identity
                    or document_id != self._active_document_id
                    or path != self._active_pdf_path
                    or cwd != self._active_cwd
                )
                if self._streaming and changing_document:
                    raise BridgeError(
                        409,
                        "pi_session_busy",
                        "Pi is generating a response. Abort it or wait before switching documents.",
                        {"active_item_key": self._active_item_key},
                    )
                if (
                    not changing_document
                    and self._process
                    and self._process.poll() is None
                ):
                    return self.status()
                retired_threads = self._stop_locked()
            self._join_threads(retired_threads)

            index = self._load_index()
            record = index["sessions"].get(document_id) or {}
            record_matches = (
                record.get("session_identity") == session_identity
                and record.get("pdf_path") == canonical_pdf_path
                and record.get("cwd") == canonical_cwd
            )
            stored_session = record.get("session_file") if record_matches else None
            session_file = Path(stored_session).expanduser().resolve() if stored_session else None
            if session_file and not session_file.is_file():
                session_file = None
            stored_context_fingerprint = (
                self._validated_stored_fingerprint(record.get("context_fingerprint"))
                if session_file
                else None
            )

            with self._lock:
                self._start_locked(
                    item_key=item_key,
                    library_id=normalized_library_id,
                    session_identity=session_identity,
                    document_id=document_id,
                    pdf_path=path,
                    cwd=cwd,
                    session_file=session_file,
                )
            try:
                state = self._request("get_state", timeout=self.startup_timeout_seconds)
            except Exception:
                with self._lock:
                    retired_threads = self._stop_locked()
                self._join_threads(retired_threads)
                raise

            actual_session = (state.get("data") or {}).get("sessionFile")
            with self._lock:
                if actual_session:
                    self._active_session_file = Path(actual_session).expanduser().resolve()
                    resumed_intended_session = bool(
                        session_file
                        and self._canonical_path(self._active_session_file) == self._canonical_path(session_file)
                    )
                    restored_fingerprint = stored_context_fingerprint if resumed_intended_session else None
                    self._active_context_fingerprint = restored_fingerprint
                    index["sessions"][document_id] = {
                        "item_key": item_key,
                        "library_id": normalized_library_id,
                        "session_identity": session_identity,
                        "document_id": document_id,
                        "session_file": str(self._active_session_file),
                        "pdf_path": canonical_pdf_path,
                        "cwd": canonical_cwd,
                        "context_fingerprint": restored_fingerprint,
                        "updated_at": now_iso(),
                    }
                    self._save_index(index)
                return self.status()

    def reset_item(
        self,
        item_key: str,
        pdf_path: str | Path,
        *,
        library_id: str | int | None = None,
    ) -> dict[str, Any]:
        """Forget one document's persisted session without deleting its history file."""
        item_key = self._validate_item_key(item_key)
        normalized_library_id = self._normalize_library_id(library_id)
        path = Path(pdf_path).expanduser().resolve()
        if not path.is_file():
            raise BridgeError(422, "invalid_pdf_path", "PDF path does not exist", {"pdf_path": str(path)})
        if path.suffix.lower() != ".pdf":
            raise BridgeError(422, "invalid_pdf_type", "Only PDF files are supported", {"pdf_path": str(path)})
        session_identity = f"{normalized_library_id}:{item_key}" if normalized_library_id else item_key
        canonical_pdf_path = os.path.normcase(str(path))
        document_id = hashlib.sha256(
            f"{session_identity}\0{canonical_pdf_path}".encode("utf-8")
        ).hexdigest()

        with self._lifecycle_lock, self._admission_lock:
            retired_threads: list[threading.Thread] = []
            with self._lock:
                if self._active_document_id == document_id:
                    if self._streaming:
                        raise BridgeError(
                            409,
                            "pi_session_busy",
                            "Pi is generating a response. Abort it or wait before starting a new session.",
                            {"active_item_key": self._active_item_key},
                        )
                    retired_threads = self._stop_locked()
            self._join_threads(retired_threads)
            index = self._load_index()
            removed = index["sessions"].pop(document_id, None)
            self._save_index(index)
            return {
                "reset": True,
                "document_id": document_id,
                "previous_session_file": removed.get("session_file") if isinstance(removed, dict) else None,
            }

    def context_injection_required(self, fingerprint: str) -> bool:
        """Return whether the active persisted Pi session lacks this exact reading context."""
        fingerprint = self._validate_context_fingerprint(fingerprint)
        with self._lifecycle_lock, self._admission_lock:
            with self._lock:
                self._require_running_locked()
                document_id = self._active_document_id
                generation = self._active_generation
                session_file = self._active_session_file
                active_fingerprint = self._active_context_fingerprint
                if not document_id or generation is None or not session_file:
                    return True
            if active_fingerprint == fingerprint:
                return False
            index = self._load_index()
            record = index["sessions"].get(document_id)
            persisted = self._validated_stored_fingerprint(
                record.get("context_fingerprint") if isinstance(record, dict) else None
            )
            with self._lock:
                if generation != self._active_generation or document_id != self._active_document_id:
                    raise BridgeError(409, "pi_session_changed", "The active Pi session changed")
                self._active_context_fingerprint = persisted
            return persisted != fingerprint

    def mark_context_injected(self, fingerprint: str) -> None:
        """Atomically persist that the active Pi session accepted this reading context."""
        fingerprint = self._validate_context_fingerprint(fingerprint)
        with self._lifecycle_lock, self._admission_lock:
            with self._lock:
                self._require_running_locked()
                document_id = self._active_document_id
                generation = self._active_generation
                session_file = self._active_session_file
                if not document_id or generation is None or not session_file:
                    raise BridgeError(409, "pi_session_changed", "The active Pi session is incomplete")
            self._persist_context_fingerprint(
                fingerprint,
                generation=generation,
                document_id=document_id,
                session_file=session_file,
            )

    def _persist_context_fingerprint(
        self,
        fingerprint: str,
        *,
        generation: int,
        document_id: str,
        session_file: Path,
    ) -> None:
        index = self._load_index()
        record = index["sessions"].get(document_id)
        recorded_session = record.get("session_file") if isinstance(record, dict) else None
        if (
            not isinstance(record, dict)
            or not isinstance(recorded_session, str)
            or self._canonical_path(recorded_session) != self._canonical_path(session_file)
        ):
            raise BridgeError(409, "pi_session_changed", "The persisted Pi session no longer matches the active session")
        with self._lock:
            if (
                generation != self._active_generation
                or document_id != self._active_document_id
                or not self._active_session_file
                or self._canonical_path(self._active_session_file) != self._canonical_path(session_file)
            ):
                raise BridgeError(409, "pi_session_changed", "The active Pi session changed")
            record["context_fingerprint"] = fingerprint
            record["context_injected_at"] = now_iso()
            record["updated_at"] = now_iso()
            self._save_index(index)
            self._active_context_fingerprint = fingerprint

    def _accept_inflight_prompt(self, generation: int, *, request_id: str | None = None) -> None:
        with self._lifecycle_lock, self._admission_lock:
            with self._lock:
                prompt = self._inflight_prompt
                if (
                    not prompt
                    or prompt.get("generation") != generation
                    or (request_id is not None and prompt.get("request_id") != request_id)
                    or prompt.get("accepted")
                ):
                    return
                fingerprint = prompt.get("context_fingerprint")
                if fingerprint is None:
                    prompt["accepted"] = True
                    return
                document_id = self._active_document_id
                session_file = self._active_session_file
                if not document_id or not session_file:
                    raise BridgeError(409, "pi_session_changed", "The active Pi session is incomplete")
            self._persist_context_fingerprint(
                fingerprint,
                generation=generation,
                document_id=document_id,
                session_file=session_file,
            )
            with self._lock:
                prompt = self._inflight_prompt
                if (
                    prompt
                    and prompt.get("generation") == generation
                    and (request_id is None or prompt.get("request_id") == request_id)
                ):
                    prompt["accepted"] = True

    def _reject_inflight_prompt(self, generation: int, request_id: str) -> None:
        with self._lock:
            prompt = self._inflight_prompt
            if (
                not prompt
                or prompt.get("generation") != generation
                or prompt.get("request_id") != request_id
                or prompt.get("accepted")
            ):
                return
            self._inflight_prompt = None
            self._streaming = False

    def prompt(
        self,
        message: str,
        *,
        images: list[dict[str, str]] | None = None,
        context_fingerprint: str | None = None,
    ) -> dict[str, Any]:
        message = str(message or "").strip()
        normalized_images = [dict(image) for image in (images or []) if isinstance(image, dict)]
        if not message and not normalized_images:
            raise BridgeError(422, "invalid_prompt", "Prompt message or image is required")
        if len(message) > self.pi.max_context_chars:
            raise BridgeError(
                422,
                "pi_context_too_large",
                "Prompt and literature context exceed the configured Pi context limit",
                {"actual_chars": len(message), "max_context_chars": self.pi.max_context_chars},
            )
        fingerprint = (
            self._validate_context_fingerprint(context_fingerprint)
            if context_fingerprint is not None
            else None
        )
        request_id = uuid.uuid4().hex
        with self._lock:
            self._require_running_locked()
            if self._streaming or self._inflight_prompt:
                raise BridgeError(409, "pi_session_busy", "Pi is already generating a response")
            generation = self._active_generation
            assert generation is not None
            self._inflight_prompt = {
                "request_id": request_id,
                "generation": generation,
                "context_fingerprint": fingerprint,
                "accepted": False,
            }
            self._streaming = True
            self._last_activity = time.monotonic()
        try:
            payload: dict[str, Any] = {"message": message}
            if normalized_images:
                payload["images"] = normalized_images
            response = self._request(
                "prompt",
                payload,
                request_id=request_id,
                outcome_unknown_after_write=True,
            )
        except BridgeError as exc:
            if exc.code != "pi_rpc_outcome_unknown":
                self._reject_inflight_prompt(generation, request_id)
            raise
        self._accept_inflight_prompt(generation, request_id=request_id)
        return response

    def abort(self) -> dict[str, Any]:
        response = self._request("abort")
        with self._lock:
            self._streaming = False
            self._inflight_prompt = None
        return response

    def get_state(self) -> dict[str, Any]:
        return self._request("get_state")

    def get_messages(self) -> dict[str, Any]:
        return self._request("get_messages")

    def get_available_models(self) -> list[dict[str, Any]]:
        response = self._request("get_available_models")
        models = (response.get("data") or {}).get("models")
        return [dict(model) for model in models if isinstance(model, dict)] if isinstance(models, list) else []

    def get_available_thinking_levels(self) -> list[str]:
        response = self._request("get_available_thinking_levels")
        levels = (response.get("data") or {}).get("levels")
        if not isinstance(levels, list):
            return []
        return [str(level) for level in levels if isinstance(level, str) and str(level).strip()]

    def get_thinking_level(self) -> str | None:
        state = self.get_state()
        level = (state.get("data") or {}).get("thinkingLevel")
        return str(level) if isinstance(level, str) and level.strip() else None

    def set_thinking_level(self, level: str) -> dict[str, Any]:
        level = str(level).strip().lower()
        if level not in PI_THINKING_LEVELS:
            raise BridgeError(422, "invalid_pi_thinking_level", "Unsupported Pi thinking level")
        with self._admission_lock:
            with self._lock:
                self._require_running_locked()
                if self._streaming or self._inflight_prompt:
                    raise BridgeError(409, "pi_session_busy", "Wait for the current response before changing the thinking level")
            response = self._request("set_thinking_level", {"level": level})
            with self._lock:
                self._preferred_thinking_level = level
            return response

    def set_model(self, provider: str, model_id: str) -> dict[str, Any]:
        provider = str(provider).strip()
        model_id = str(model_id).strip()
        if not provider or not model_id:
            raise BridgeError(422, "invalid_pi_model", "Pi model provider and id are required")
        with self._admission_lock:
            with self._lock:
                self._require_running_locked()
                if self._streaming or self._inflight_prompt:
                    raise BridgeError(409, "pi_session_busy", "Wait for the current response before switching models")
            response = self._request("set_model", {"provider": provider, "modelId": model_id})
            with self._lock:
                self._preferred_model = f"{provider}/{model_id}"
            return response

    def wait_until_idle(self, timeout: float = 10.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                if not self._streaming:
                    return True
                if self._process and self._process.poll() is not None:
                    return True
            time.sleep(0.02)
        return False

    def reap_idle(self) -> bool:
        """Close a non-streaming process after the configured idle timeout."""
        with self._lifecycle_lock, self._admission_lock:
            with self._lock:
                process = self._process
                if not process or process.poll() is not None or self._streaming:
                    return False
                if time.monotonic() - self._last_activity < self.pi.idle_timeout_seconds:
                    return False
                retired_threads = self._stop_locked()
            self._join_threads(retired_threads)
            return True

    def close(self) -> None:
        with self._lifecycle_lock, self._admission_lock:
            with self._lock:
                retired_threads = self._stop_locked()
            self._join_threads(retired_threads)

    def _validate_item_key(self, item_key: str) -> str:
        normalized = item_key.strip()
        if not ZOTERO_ITEM_KEY_RE.fullmatch(normalized):
            raise BridgeError(
                422,
                "invalid_item_key",
                "item_key must be an 8-character uppercase Zotero key",
            )
        return normalized

    def _validate_context_fingerprint(self, fingerprint: str) -> str:
        normalized = str(fingerprint).strip().lower()
        if not CONTEXT_FINGERPRINT_RE.fullmatch(normalized):
            raise BridgeError(422, "invalid_context_fingerprint", "context fingerprint must be a SHA-256 hex digest")
        return normalized

    def _validated_stored_fingerprint(self, fingerprint: Any) -> str | None:
        if not isinstance(fingerprint, str):
            return None
        normalized = fingerprint.strip().lower()
        return normalized if CONTEXT_FINGERPRINT_RE.fullmatch(normalized) else None

    def _canonical_path(self, path: str | Path) -> str:
        return os.path.normcase(str(Path(path).expanduser().resolve()))

    def _normalize_library_id(self, library_id: str | int | None) -> str | None:
        if library_id is None:
            return None
        normalized = str(library_id).strip()
        if not LIBRARY_ID_RE.fullmatch(normalized):
            raise BridgeError(422, "invalid_library_id", "library_id contains unsupported characters")
        return normalized

    def _load_system_prompt(self) -> str:
        path = self.pi.system_prompt_path
        if not path or not path.is_file():
            raise BridgeError(
                503,
                "pi_system_prompt_missing",
                "Pi literature assistant system prompt was not found",
                {"path": str(path) if path else None},
            )
        content = path.read_text(encoding="utf-8-sig").strip()
        if not content:
            raise BridgeError(503, "pi_system_prompt_empty", "Pi system prompt is empty")
        return content

    def _build_command(
        self,
        *,
        item_key: str,
        document_id: str,
        session_file: Path | None,
    ) -> list[str]:
        args = [
            "--mode",
            "rpc",
            "--session-dir",
            str(self.pi.session_dir),
            "--name",
            f"zotero-{item_key}-{document_id[:8]}",
            "--system-prompt",
            self._load_system_prompt(),
            "--thinking",
            self._preferred_thinking_level,
            "--no-context-files",
            "--no-skills",
            "--no-prompt-templates",
            "--no-extensions",
            "--no-tools",
            "--no-approve",
        ]
        if self._preferred_model:
            args.extend(["--model", self._preferred_model])
        if session_file:
            args.extend(["--session", str(session_file)])
        return [*self._resolve_executable_command(), *args]

    def executable_status(self) -> dict[str, Any]:
        try:
            command = self._resolve_executable_command()
            return {
                "available": True,
                "configured": self.pi.executable,
                "command": command,
                "error": None,
            }
        except BridgeError as exc:
            return {
                "available": False,
                "configured": self.pi.executable,
                "command": None,
                "error": {"code": exc.code, "message": exc.message, "details": exc.details},
            }

    def _resolve_executable_command(self) -> list[str]:
        if self.executable_command:
            return list(self.executable_command)

        configured = self.pi.executable
        resolved_name = shutil.which(configured)
        executable = Path(resolved_name or configured).expanduser()
        if not resolved_name:
            if not executable.is_absolute() or not executable.is_file():
                raise BridgeError(
                    503,
                    "pi_executable_not_found",
                    "Pi CLI was not found. Install Pi or configure an absolute executable path.",
                    {"configured": configured, "searched_path": os.environ.get("PATH", "")},
                )
        if platform.system() != "Windows" or executable.suffix.lower() not in {".cmd", ".bat"}:
            return [str(executable.resolve())]
        if executable.suffix.lower() != ".cmd" or not executable.is_file():
            raise BridgeError(
                503,
                "pi_executable_unsupported",
                "Windows Pi launcher must be a standard npm .cmd shim or a direct executable",
                {"executable": str(executable)},
            )

        text = executable.read_text(encoding="utf-8", errors="replace")
        match = re.search(r'%dp0%[\\/](?P<target>[^"\r\n]+?\.js)"\s+%\*', text, flags=re.IGNORECASE)
        if not match:
            raise BridgeError(
                503,
                "pi_executable_unsupported",
                "Could not safely resolve the Node CLI target from the Pi npm launcher",
                {"executable": str(executable)},
            )
        shim_root = executable.parent.resolve()
        target = (shim_root / Path(match.group("target").replace("\\", os.sep))).resolve()
        try:
            target.relative_to(shim_root)
        except ValueError as exc:
            raise BridgeError(
                503,
                "pi_executable_unsupported",
                "Resolved Pi Node CLI target escapes the npm launcher directory",
                {"target": str(target)},
            ) from exc
        if not target.is_file():
            raise BridgeError(
                503,
                "pi_executable_unsupported",
                "Resolved Pi Node CLI target does not exist",
                {"target": str(target)},
            )
        sibling_node = executable.parent / "node.exe"
        node = sibling_node if sibling_node.is_file() else Path(shutil.which("node") or "")
        if not node or not node.is_file():
            raise BridgeError(503, "pi_executable_unsupported", "Node.js executable was not found")
        return [str(node.resolve()), str(target)]

    def _start_locked(
        self,
        *,
        item_key: str,
        library_id: str | None,
        session_identity: str,
        document_id: str,
        pdf_path: Path,
        cwd: Path,
        session_file: Path | None,
    ) -> None:
        command = self._build_command(item_key=item_key, document_id=document_id, session_file=session_file)
        kwargs: dict[str, Any] = {
            "cwd": str(cwd),
            "stdin": subprocess.PIPE,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "shell": False,
            "bufsize": 0,
        }
        if platform.system() == "Windows":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
        else:
            kwargs["start_new_session"] = True
        try:
            process = self.popen_factory(command, **kwargs)
        except (OSError, ValueError) as exc:
            raise BridgeError(
                503,
                "pi_start_failed",
                "Failed to start Pi RPC process",
                {"error": str(exc), "executable": self.pi.executable},
            ) from exc
        if process.stdin is None or process.stdout is None or process.stderr is None:
            process.kill()
            raise BridgeError(503, "pi_start_failed", "Pi RPC process pipes were not created")

        self._generation += 1
        generation = self._generation
        self._process = process
        self._active_generation = generation
        self._active_item_key = item_key
        self._active_library_id = library_id
        self._active_session_identity = session_identity
        self._active_document_id = document_id
        self._active_pdf_path = pdf_path
        self._active_cwd = cwd
        self._active_session_file = session_file
        self._inflight_prompt = None
        self._streaming = False
        self._stopping_generation = None
        self._last_error = None
        self._stderr_tail.clear()
        self._events.clear()
        self._last_activity = time.monotonic()
        self._stdout_thread = threading.Thread(
            target=self._stdout_loop,
            args=(process, generation, process.stdout),
            name=f"pi-rpc-stdout-{generation}",
            daemon=True,
        )
        self._stderr_thread = threading.Thread(
            target=self._stderr_loop,
            args=(process, generation, process.stderr),
            name=f"pi-rpc-stderr-{generation}",
            daemon=True,
        )
        self._stdout_thread.start()
        self._stderr_thread.start()

    def _request(
        self,
        command_type: str,
        payload: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
        request_id: str | None = None,
        outcome_unknown_after_write: bool = False,
    ) -> dict[str, Any]:
        request_id = request_id or uuid.uuid4().hex
        write_flushed = False
        response_queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
        with self._admission_lock:
            with self._lock:
                process = self._require_running_locked()
                generation = self._active_generation
                assert generation is not None
            with self._pending_lock:
                self._pending[request_id] = (generation, response_queue)
            command = {"id": request_id, "type": command_type, **(payload or {})}
            encoded = (json.dumps(command, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
            try:
                assert process.stdin is not None
                with self._stdin_lock:
                    process.stdin.write(encoded)
                    process.stdin.flush()
                    write_flushed = True
            except (BrokenPipeError, OSError, ValueError) as exc:
                with self._pending_lock:
                    self._pending.pop(request_id, None)
                raise BridgeError(
                    503,
                    "pi_rpc_unavailable",
                    "Pi RPC process is unavailable",
                    {"error": str(exc)},
                ) from exc

        try:
            response = response_queue.get(timeout=timeout or self.request_timeout_seconds)
        except queue.Empty as exc:
            if outcome_unknown_after_write and write_flushed:
                raise BridgeError(
                    503,
                    "pi_rpc_outcome_unknown",
                    "Pi RPC prompt was written, but its acceptance response was not received; the outcome is indeterminate",
                    {"command": command_type, "request_id": request_id},
                ) from exc
            raise BridgeError(
                503,
                "pi_rpc_timeout",
                f"Timed out waiting for Pi RPC response to {command_type}",
            ) from exc
        finally:
            with self._pending_lock:
                self._pending.pop(request_id, None)
        if not response.get("success", False):
            raise BridgeError(
                503,
                "pi_rpc_error",
                response.get("error") or f"Pi RPC command {command_type} failed",
                {"command": command_type},
            )
        with self._lock:
            if generation == self._active_generation:
                self._last_activity = time.monotonic()
        return response

    def _require_running_locked(self) -> subprocess.Popen[bytes]:
        process = self._process
        if not process or process.poll() is not None:
            raise BridgeError(503, "pi_unavailable", "Pi RPC process is not running")
        return process

    def _stdout_loop(self, process: subprocess.Popen[bytes], generation: int, stream: IO[bytes]) -> None:
        try:
            while True:
                try:
                    raw = stream.readline()
                except (OSError, ValueError):
                    break
                if not raw:
                    break
                raw = raw.removesuffix(b"\n").removesuffix(b"\r")
                if not raw:
                    continue
                try:
                    event = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    self._record_error(process, generation, "pi_rpc_parse_error", str(exc))
                    continue
                if isinstance(event, dict):
                    self._handle_event(process, generation, event)
        finally:
            return_code = process.poll()
            if return_code is None:
                try:
                    return_code = process.wait(timeout=0.2)
                except subprocess.TimeoutExpired:
                    return_code = None
            with self._lock:
                current = process is self._process and generation == self._active_generation
                intentional = generation == self._stopping_generation or not current
                if current:
                    self._streaming = False
                    self._inflight_prompt = None
                if current and not intentional:
                    self._last_error = {
                        "code": "pi_process_exited",
                        "message": "Pi RPC process exited unexpectedly",
                        "return_code": return_code,
                    }
                    self._append_event_locked({"type": "bridge_pi_error", "error": dict(self._last_error)})
            if current and not intentional:
                self._fail_pending("Pi RPC process exited unexpectedly", generation=generation)

    def _stderr_loop(self, process: subprocess.Popen[bytes], generation: int, stream: IO[bytes]) -> None:
        while True:
            try:
                raw = stream.readline()
            except (OSError, ValueError):
                return
            if not raw:
                return
            line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
            if line:
                with self._lock:
                    if process is self._process and generation == self._active_generation:
                        self._stderr_tail.append(line[-1_000:])

    def _handle_event(self, process: subprocess.Popen[bytes], generation: int, event: dict[str, Any]) -> None:
        with self._lock:
            if process is not self._process or generation != self._active_generation:
                return
        request_id = event.get("id")
        if event.get("type") == "response" and request_id:
            request_id = str(request_id)
            with self._pending_lock:
                pending_entry = self._pending.get(request_id)
            if pending_entry and pending_entry[0] == generation:
                try:
                    pending_entry[1].put_nowait(event)
                except queue.Full:
                    pass
            with self._lock:
                prompt_response = bool(
                    self._inflight_prompt
                    and self._inflight_prompt.get("generation") == generation
                    and self._inflight_prompt.get("request_id") == request_id
                )
            if prompt_response:
                if event.get("success", False):
                    try:
                        self._accept_inflight_prompt(generation, request_id=request_id)
                    except Exception as exc:
                        self._record_error(process, generation, "context_fingerprint_persist_failed", str(exc))
                else:
                    self._reject_inflight_prompt(generation, request_id)
            return

        event_type = event.get("type")
        if event_type in PROMPT_ACCEPTED_EVENT_TYPES:
            try:
                self._accept_inflight_prompt(generation)
            except Exception as exc:
                self._record_error(process, generation, "context_fingerprint_persist_failed", str(exc))

        with self._lock:
            if process is not self._process or generation != self._active_generation:
                return
            if event_type == "agent_start":
                self._streaming = True
            elif event_type == "agent_settled":
                prompt = self._inflight_prompt
                if not prompt or prompt.get("accepted"):
                    self._streaming = False
                    self._inflight_prompt = None
                else:
                    # A settled event without an observed acceptance does not make
                    # an indeterminate, flushed prompt safe to retry.
                    self._streaming = True
            self._last_activity = time.monotonic()
            self._append_event_locked(event)

    def _append_event_locked(self, event: dict[str, Any]) -> None:
        self._cursor += 1
        self._events.append(
            {
                "cursor": self._cursor,
                "generation": self._active_generation,
                "item_key": self._active_item_key,
                "document_id": self._active_document_id,
                **event,
            }
        )

    def _record_error(
        self,
        process: subprocess.Popen[bytes],
        generation: int,
        code: str,
        message: str,
    ) -> None:
        with self._lock:
            if process is not self._process or generation != self._active_generation:
                return
            self._last_error = {"code": code, "message": message}
            self._append_event_locked({"type": "bridge_pi_error", "error": dict(self._last_error)})

    def _fail_pending(self, message: str, *, generation: int | None = None) -> None:
        with self._pending_lock:
            pending_entries = list(self._pending.values())
        for pending_generation, pending in pending_entries:
            if generation is not None and pending_generation != generation:
                continue
            try:
                pending.put_nowait({"type": "response", "success": False, "error": message})
            except queue.Full:
                pass

    def _load_index(self) -> dict[str, Any]:
        payload = read_json(self.index_path, default={}) or {}
        sessions = payload.get("sessions")
        if not isinstance(sessions, dict):
            sessions = {}
            legacy_items = payload.get("items")
            if isinstance(legacy_items, dict):
                for record in legacy_items.values():
                    if not isinstance(record, dict) or not record.get("pdf_path"):
                        continue
                    identity = str(record.get("session_identity") or record.get("item_key") or "")
                    pdf_path = str(Path(record["pdf_path"]).expanduser().resolve())
                    if identity:
                        document_id = hashlib.sha256(f"{identity}\0{pdf_path}".encode("utf-8")).hexdigest()
                        sessions[document_id] = record
        return {"version": 2, "sessions": sessions}

    def _save_index(self, index: dict[str, Any]) -> None:
        atomic_write_json(self.index_path, index)

    def _stop_locked(self) -> list[threading.Thread]:
        process = self._process
        generation = self._active_generation
        threads = [thread for thread in (self._stdout_thread, self._stderr_thread) if thread]
        if not process:
            self._clear_active_locked()
            return threads

        self._stopping_generation = generation
        if generation is not None:
            self._fail_pending("Pi RPC process is shutting down", generation=generation)
        try:
            if process.stdin:
                try:
                    process.stdin.close()
                except (OSError, ValueError):
                    pass
            try:
                process.wait(timeout=self.stop_timeout_seconds)
            except subprocess.TimeoutExpired:
                self._terminate_process_tree(process)
        finally:
            for stream in (process.stdout, process.stderr):
                if stream:
                    try:
                        stream.close()
                    except (OSError, ValueError):
                        pass
            self._process = None
            self._streaming = False
            self._inflight_prompt = None
            self._clear_active_locked()
            self._stopping_generation = None
        return threads

    def _join_threads(self, threads: list[threading.Thread]) -> None:
        current = threading.current_thread()
        for thread in threads:
            if thread is current:
                continue
            thread.join(timeout=max(0.5, self.stop_timeout_seconds))

    def _clear_active_locked(self) -> None:
        self._events.clear()
        self._active_generation = None
        self._active_item_key = None
        self._active_library_id = None
        self._active_session_identity = None
        self._active_document_id = None
        self._active_pdf_path = None
        self._active_cwd = None
        self._active_session_file = None
        self._active_context_fingerprint = None
        self._inflight_prompt = None
        self._stdout_thread = None
        self._stderr_thread = None

    def _terminate_process_tree(self, process: subprocess.Popen[bytes]) -> None:
        if process.poll() is not None:
            return
        if platform.system() == "Windows":
            try:
                process.send_signal(signal.CTRL_BREAK_EVENT)
                process.wait(timeout=1.0)
                return
            except (OSError, ValueError, subprocess.TimeoutExpired):
                pass
            taskkill_succeeded = False
            try:
                result = subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=5,
                )
                taskkill_succeeded = result.returncode == 0
            except (OSError, subprocess.TimeoutExpired):
                taskkill_succeeded = False
            if taskkill_succeeded:
                try:
                    process.wait(timeout=2.0)
                    return
                except subprocess.TimeoutExpired:
                    pass
            if process.poll() is None:
                process.kill()
        else:
            try:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=1.0)
                return
            except (OSError, ProcessLookupError, subprocess.TimeoutExpired):
                pass
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except (OSError, ProcessLookupError):
                process.kill()
        try:
            process.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            process.kill()
