from __future__ import annotations

import threading
import uuid
from typing import Any

from .addon_client import AddonClient
from .errors import BridgeError
from .utils import append_jsonl, now_iso


class SerialWriteExecutor:
    def __init__(self, addon_client: AddonClient, operations_log_path) -> None:
        self.addon_client = addon_client
        self.operations_log_path = operations_log_path
        self._lock = threading.Lock()

    def execute(self, command: str, payload: dict[str, Any]) -> dict[str, Any]:
        operation_id = uuid.uuid4().hex
        with self._lock:
            append_jsonl(
                self.operations_log_path,
                {
                    "operation_id": operation_id,
                    "command": command,
                    "state": "started",
                    "payload": payload,
                    "timestamp": now_iso(),
                },
            )
            try:
                result = self.addon_client.submit(command, payload)
            except BridgeError as exc:
                append_jsonl(
                    self.operations_log_path,
                    {
                        "operation_id": operation_id,
                        "command": command,
                        "state": "failed",
                        "error": {"code": exc.code, "message": exc.message, "details": exc.details},
                        "timestamp": now_iso(),
                    },
                )
                raise
            append_jsonl(
                self.operations_log_path,
                {
                    "operation_id": operation_id,
                    "command": command,
                    "state": "completed",
                    "result": result,
                    "timestamp": now_iso(),
                },
            )
            return result
