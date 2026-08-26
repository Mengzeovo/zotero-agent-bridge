from __future__ import annotations

import json
import queue
import subprocess
import threading
import time
import uuid
from collections import deque
from pathlib import Path
from typing import Any, Callable

from .config import Settings
from .errors import BridgeError
from .pi_runtime import popen_process_group_kwargs, resolve_pi_executable, terminate_process_tree
from .session_transcript import content_text

PopenFactory = Callable[..., subprocess.Popen[bytes]]


class PiOneShotGenerator:
    """Run isolated Pi RPC prompts without creating or mutating user sessions."""

    def __init__(self, settings: Settings, *, popen_factory: PopenFactory = subprocess.Popen, executable_command: list[str] | None = None) -> None:
        if not settings.pi:
            raise ValueError("Pi settings are required")
        self.settings = settings
        self.pi = settings.pi
        self.popen_factory = popen_factory
        self.executable_command = list(executable_command) if executable_command else None
        self._lock = threading.RLock()
        self._closed = False
        self._processes: set[subprocess.Popen[bytes]] = set()

    def generate(self, prompt: str, *, system_prompt: str, model: str | None = None, thinking: str = "minimal", timeout_seconds: float | None, cwd: str | Path | None = None) -> str:
        if not prompt.strip():
            raise BridgeError(422, "pi_generation_empty_prompt", "The internal Pi prompt is empty")
        with self._lock:
            if self._closed:
                raise BridgeError(503, "pi_generation_closed", "The internal Pi generator is shutting down")
        command = [*resolve_pi_executable(self.pi.executable, self.executable_command), "--mode", "rpc", "--no-session", "--system-prompt", system_prompt, "--thinking", thinking, "--no-context-files", "--no-skills", "--no-prompt-templates", "--no-extensions", "--no-themes", "--no-tools", "--no-approve"]
        selected_model = (model or self.pi.model or "").strip()
        if selected_model:
            command.extend(["--model", selected_model])
        kwargs: dict[str, Any] = {"cwd": str(Path(cwd).resolve()) if cwd else str(self.settings.bridge_home.resolve()), "stdin": subprocess.PIPE, "stdout": subprocess.PIPE, "stderr": subprocess.PIPE, "shell": False, "bufsize": 0}
        kwargs.update(popen_process_group_kwargs())
        try:
            process = self.popen_factory(command, **kwargs)
        except (OSError, ValueError) as exc:
            raise BridgeError(503, "pi_generation_start_failed", "Failed to start internal Pi generation", {"error": str(exc)}) from exc
        if process.stdin is None or process.stdout is None or process.stderr is None:
            process.kill()
            raise BridgeError(503, "pi_generation_start_failed", "Internal Pi process pipes were not created")
        with self._lock:
            if self._closed:
                terminate_process_tree(process)
                raise BridgeError(503, "pi_generation_closed", "The internal Pi generator is shutting down")
            self._processes.add(process)
        events: queue.Queue[dict[str, Any] | None] = queue.Queue()
        stderr_tail: deque[str] = deque(maxlen=20)
        def stdout_reader() -> None:
            try:
                for raw in iter(process.stdout.readline, b""):
                    try:
                        payload = json.loads(raw.decode("utf-8", errors="replace"))
                    except json.JSONDecodeError:
                        continue
                    if isinstance(payload, dict):
                        events.put(payload)
            finally:
                events.put(None)
        def stderr_reader() -> None:
            for raw in iter(process.stderr.readline, b""):
                text = raw.decode("utf-8", errors="replace").strip()
                if text:
                    stderr_tail.append(text)
        stdout_thread = threading.Thread(target=stdout_reader, daemon=True)
        stderr_thread = threading.Thread(target=stderr_reader, daemon=True)
        stdout_thread.start(); stderr_thread.start()
        request_id = uuid.uuid4().hex
        try:
            process.stdin.write((json.dumps({"id": request_id, "type": "prompt", "message": prompt}, ensure_ascii=False) + "\n").encode())
            process.stdin.flush()
            deadline = time.monotonic() + timeout_seconds if timeout_seconds is not None else None
            final: dict[str, Any] | None = None
            completed = False
            while deadline is None or time.monotonic() < deadline:
                try:
                    wait_seconds = 0.2 if deadline is None else min(0.2, max(0.01, deadline - time.monotonic()))
                    payload = events.get(timeout=wait_seconds)
                except queue.Empty:
                    if process.poll() is not None:
                        break
                    continue
                if payload is None:
                    break
                if payload.get("type") == "response" and payload.get("id") == request_id and not payload.get("success", False):
                    raise BridgeError(503, "pi_generation_failed", str(payload.get("error") or "Internal Pi prompt was rejected"), {"stderr": list(stderr_tail)})
                if payload.get("type") == "message_end" and isinstance(payload.get("message"), dict) and payload["message"].get("role") == "assistant":
                    final = payload["message"]
                if payload.get("type") == "agent_end" and not payload.get("willRetry"):
                    messages = payload.get("messages")
                    if isinstance(messages, list):
                        candidates = [m for m in messages if isinstance(m, dict) and m.get("role") == "assistant"]
                        if candidates:
                            final = candidates[-1]
                    completed = True
                    break
            if not completed:
                if deadline is not None and time.monotonic() >= deadline:
                    raise BridgeError(504, "pi_generation_timeout", "Internal Pi generation timed out")
                raise BridgeError(
                    503,
                    "pi_generation_failed",
                    "Internal Pi generation ended before the agent completed",
                    {"stderr": list(stderr_tail)},
                )
            if final is None:
                raise BridgeError(503, "pi_generation_failed", "Internal Pi generation ended without an assistant response", {"stderr": list(stderr_tail)})
            text = content_text(final.get("content"))
            if final.get("stopReason") != "stop" or not text:
                raise BridgeError(503, "pi_generation_incomplete", "Internal Pi generation did not finish cleanly", {"stop_reason": final.get("stopReason"), "stderr": list(stderr_tail)})
            return text
        except (BrokenPipeError, OSError) as exc:
            raise BridgeError(503, "pi_generation_failed", "Internal Pi process communication failed", {"error": str(exc)}) from exc
        finally:
            try: process.stdin.close()
            except (OSError, ValueError): pass
            terminate_process_tree(process)
            stdout_thread.join(timeout=1); stderr_thread.join(timeout=1)
            for stream in (process.stdout, process.stderr):
                try: stream.close()
                except (OSError, ValueError): pass
            with self._lock: self._processes.discard(process)

    def close(self) -> None:
        with self._lock:
            self._closed = True
            processes = list(self._processes)
        for process in processes:
            terminate_process_tree(process)
